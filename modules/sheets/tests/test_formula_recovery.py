from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ServerSelectionTimeoutError

from zeler_sheets.formulas.recovery import FormulaRecoveryQueue, RecoveryRequest


@pytest_asyncio.fixture
async def recovery_db() -> AsyncIterator[Any]:
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        "mongodb://127.0.0.1:27028/?directConnection=true", serverSelectionTimeoutMS=1000
    )
    db = client[f"zeler_recovery_test_{uuid4().hex}"]
    connected = False
    try:
        try:
            await client.admin.command("ping")
            connected = True
        except ServerSelectionTimeoutError:
            pytest.skip("dedicated local Mongo on port 27028 is unavailable")
        yield db
    finally:
        if connected:
            await client.drop_database(db.name)
        client.close()


def request(seller_id: str = "pilot") -> RecoveryRequest:
    return RecoveryRequest(
        seller_id=seller_id,
        read_model="questions",
        date_from=datetime(2026, 8, 8, tzinfo=UTC),
        date_to=datetime(2026, 9, 7, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_concurrent_cells_share_one_persisted_recovery(recovery_db: Any) -> None:
    now = datetime(2026, 9, 7, tzinfo=UTC)
    queue = FormulaRecoveryQueue(recovery_db, now=lambda: now)
    ids = await asyncio.gather(*(queue.enqueue(request()) for _ in range(20)))
    assert len(set(ids)) == 1
    assert await recovery_db.sheets_formula_recovery_jobs.count_documents({}) == 1
    assert await queue.enqueue(request("other")) != ids[0]


@pytest.mark.asyncio
async def test_claim_excludes_other_workers_and_fences_expired_attempt(recovery_db: Any) -> None:
    clock = [datetime(2026, 9, 7, tzinfo=UTC)]
    queue = FormulaRecoveryQueue(recovery_db, now=lambda: clock[0])
    await queue.enqueue(request())
    first = await queue.claim()
    assert first is not None
    assert await queue.claim() is None
    clock[0] += timedelta(minutes=11)
    replacement = await queue.claim()
    assert replacement is not None
    assert replacement["attempt_token"] != first["attempt_token"]
    assert not await queue.finish(first, succeeded=True)
    assert await queue.finish(replacement, succeeded=True)


@pytest.mark.asyncio
async def test_completed_request_has_cooldown_then_can_repair_again(recovery_db: Any) -> None:
    clock = [datetime(2026, 9, 7, tzinfo=UTC)]
    queue = FormulaRecoveryQueue(recovery_db, now=lambda: clock[0])
    await queue.enqueue(request())
    claimed = await queue.claim()
    assert claimed is not None
    assert await queue.finish(claimed, succeeded=True)
    await queue.enqueue(request())
    assert await queue.claim() is None
    clock[0] += timedelta(minutes=16)
    await queue.enqueue(request())
    assert await queue.claim() is not None


def test_unrecoverable_history_is_not_scheduled() -> None:
    with pytest.raises(ValueError, match="recoverable"):
        RecoveryRequest(
            seller_id="pilot",
            read_model="stock_time_metrics",
            date_from=datetime(2026, 8, 8, tzinfo=UTC),
            date_to=datetime(2026, 9, 7, tzinfo=UTC),
        )
