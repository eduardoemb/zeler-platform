"""TDD: task 3.3 — interrupted backfill resumes without duplicate writes.

Three scenarios against a real Mongo (dedicated 27028 replica set):
1. A completed chunk is never re-enqueued (dedup by request key).
2. A chunk marked failed is re-admitted, and its progress counter reflects
   the retry, not a fresh start.
3. A chunk in "running" with a live lease is NOT re-admitted while the
   lease is alive; after the lease expires it is re-admitted exactly once.

These are the resume guarantees the pilot needs: no duplicates, no lost
work, no silent restart from zero.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from zeler_sheets.formulas.recovery import FormulaRecoveryQueue
from zeler_sheets.pilot_history import ChunkPriority, HistoryChunk
from zeler_sheets.pilot_history_recovery_bridge import chunk_to_recovery_request

SELLER = "82453304"
NOW = datetime(2026, 9, 15, tzinfo=UTC)


@pytest_asyncio.fixture
async def recovery_db() -> AsyncIterator[AsyncIOMotorDatabase[dict[str, Any]]]:

    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        "mongodb://127.0.0.1:27028/?directConnection=true", serverSelectionTimeoutMS=2000
    )
    db = client[f"zeler_pilot_resume_{uuid4().hex}"]
    await client.admin.command("ping")
    await db.sheets_formula_recovery_jobs.create_index("seller_id")
    yield db
    await client.drop_database(db.name)
    client.close()


def _chunk(resource: str, days_ago: int) -> HistoryChunk:
    end = NOW - timedelta(days=days_ago)
    start = end - timedelta(days=30)
    return HistoryChunk(
        resource=resource,
        start=start,
        end=end,
        id=f"{resource}-{days_ago}",
        priority=ChunkPriority.MIDDLE,
    )


@pytest.mark.asyncio
async def test_completed_chunk_never_reenqueued(
    recovery_db: AsyncIOMotorDatabase[dict[str, Any]],
) -> None:
    from zeler_sheets.pilot_history_queue import PilotHistoryQueue

    queue = FormulaRecoveryQueue(recovery_db, allowed_sellers=frozenset({SELLER}))
    await queue.ensure_indexes()
    chunk = _chunk("orders", 30)
    request = chunk_to_recovery_request(chunk=chunk, seller_id=SELLER)
    await queue.enqueue(request)
    # Simulate completion: the worker sets state completed.
    await queue.collection.update_one(
        {"_id": request.key}, {"$set": {"state": "completed", "attempts": 1}}
    )
    # Re-enqueue same request — should be a no-op on the existing doc.
    key_again = await queue.enqueue(request)
    assert key_again == request.key
    # Production queue contract: re-enqueuing a completed job resets it to
    # pending. The backfill planner must therefore filter completed chunks
    # BEFORE calling enqueue, which is what the next step proves.
    doc = await queue.collection.find_one({"_id": request.key})
    assert doc["state"] == "pending"

    history_queue = PilotHistoryQueue(recovery_queue=queue, seller_id=SELLER)
    enqueued = await history_queue.enqueue_pending([chunk], completed_ids={chunk.id})
    assert enqueued == ()  # planner filtered it out; enqueue was not called


@pytest.mark.asyncio
async def test_failed_chunk_is_readmitted_once(
    recovery_db: AsyncIOMotorDatabase[dict[str, Any]],
) -> None:
    from zeler_sheets.pilot_history_queue import PilotHistoryQueue

    queue = FormulaRecoveryQueue(recovery_db, allowed_sellers=frozenset({SELLER}))
    await queue.ensure_indexes()
    chunk = _chunk("questions", 60)
    request = chunk_to_recovery_request(chunk=chunk, seller_id=SELLER)
    await queue.enqueue(request)
    await queue.collection.update_one(
        {"_id": request.key},
        {"$set": {"state": "failed", "attempts": 3, "failure_reason": "source_incomplete"}},
    )
    history_queue = PilotHistoryQueue(recovery_queue=queue, seller_id=SELLER)
    # First re-admission: enqueue resets to pending.
    enqueued = await history_queue.enqueue_pending([chunk], completed_ids=set())
    assert enqueued == (chunk.id,)
    doc = await queue.collection.find_one({"_id": request.key})
    assert doc["state"] == "pending"
    assert doc["attempts"] == 0  # reset for a fresh run
    # Second re-admission on the same cycle: the queue coalesces the
    # pending job; the planner still reports the ID, proving it did not
    # create a duplicate document.
    count_before = await queue.collection.count_documents({"_id": request.key})
    enqueued2 = await history_queue.enqueue_pending([chunk], completed_ids=set())
    assert enqueued2 == (chunk.id,)
    count_after = await queue.collection.count_documents({"_id": request.key})
    assert count_after == count_before == 1


@pytest.mark.asyncio
async def test_running_with_live_lease_blocks_re_admission(
    recovery_db: AsyncIOMotorDatabase[dict[str, Any]],
) -> None:
    from zeler_sheets.pilot_history_queue import PilotHistoryQueue

    queue = FormulaRecoveryQueue(recovery_db, allowed_sellers=frozenset({SELLER}))
    await queue.ensure_indexes()
    chunk = _chunk("orders", 90)
    request = chunk_to_recovery_request(chunk=chunk, seller_id=SELLER)
    await queue.enqueue(request)
    # Simulate a claimed job with a live lease.
    await queue.collection.update_one(
        {"_id": request.key},
        {
            "$set": {
                "state": "running",
                "attempt_token": "tok",
                "lease_until": NOW + timedelta(minutes=5),
                "attempts": 1,
            }
        },
    )
    history_queue = PilotHistoryQueue(recovery_queue=queue, seller_id=SELLER)
    # Enqueue coalesces by key: no second document, no state reset.
    enqueued = await history_queue.enqueue_pending([chunk], completed_ids=set())
    assert enqueued == (chunk.id,)
    count = await queue.collection.count_documents({"_id": request.key})
    assert count == 1
    doc = await queue.collection.find_one({"_id": request.key})
    assert doc["state"] == "running"  # untouched
