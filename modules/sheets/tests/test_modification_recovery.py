from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, cast
from uuid import uuid4

import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import AutoReconnect

from zeler_sheets.formulas.recovery import FormulaRecoveryQueue
from zeler_sheets.modification_recovery import (
    ModificationPage,
    admit_modifications,
    modification_window,
)

NOW = datetime(2026, 9, 15, 12, 17, tzinfo=UTC)
WATERMARK = NOW - timedelta(hours=1)


def row(identity: int, modified: datetime, seller: str = "82453304") -> dict[str, Any]:
    return {
        "id": identity,
        "seller": {"id": int(seller)},
        "date_last_updated": modified.isoformat(),
        "date_created": datetime(2024, 1, 1, tzinfo=UTC).isoformat(),
    }


@pytest_asyncio.fixture
async def queue() -> AsyncIterator[FormulaRecoveryQueue]:
    name = f"zeler_modification_{uuid4().hex}"
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        f"mongodb://127.0.0.1:27028/{name}?directConnection=true",
        tz_aware=True,
    )
    hello = await client.admin.command("hello")
    assert hello["isWritablePrimary"] and hello["setName"] == "rs0"
    try:
        yield FormulaRecoveryQueue(
            client[name],
            now=lambda: NOW,
            allowed_sellers=frozenset({"82453304", "123"}),
            max_active_jobs_per_seller=2,
        )
    finally:
        await client.drop_database(name)
        client.close()


def test_overlap_is_exactly_twenty_four_hours_before_watermark() -> None:
    offset = timezone(timedelta(hours=-6))
    start, end = modification_window(WATERMARK.astimezone(offset), NOW.astimezone(offset))
    assert start == WATERMARK - timedelta(hours=24) and end == NOW
    assert start.tzinfo == UTC and end.tzinfo == UTC
    for watermark, cutoff in ((NOW, WATERMARK), (WATERMARK.replace(tzinfo=None), NOW)):
        with pytest.raises(ValueError):
            modification_window(watermark, cutoff)


@pytest.mark.asyncio
async def test_exact_modification_bounds_include_old_creation(queue: FormulaRecoveryQueue) -> None:
    start = WATERMARK - timedelta(hours=24)
    rows = [row(1, start), row(2, start - timedelta(milliseconds=1)), row(3, NOW)]
    result = (
        await admit_modifications(queue, [ModificationPage("82453304", WATERMARK, NOW, rows)])
    )[0]
    assert result.state == "admitted" and len(result.accepted_keys) == 1
    job = await queue.claim(lane="ids")
    assert job is not None and job["order_ids"] == ["1"]
    assert job["modification_at"] == start
    assert "date_from" not in job and "history_protocol_version" not in job


@pytest.mark.asyncio
@pytest.mark.parametrize("succeeded", [True, False])
async def test_duplicate_version_is_durable_but_new_version_gets_new_job(
    queue: FormulaRecoveryQueue, succeeded: bool
) -> None:
    page = ModificationPage("82453304", WATERMARK, NOW, [row(1, WATERMARK)])
    results = await asyncio.gather(*(admit_modifications(queue, [page]) for _ in range(8)))
    assert len({result[0].accepted_keys for result in results}) == 1
    assert await queue.collection.count_documents({}) == 1
    claimed = await queue.claim()
    assert claimed is not None
    assert await queue.finish(claimed, succeeded=succeeded)
    before = await queue.collection.find_one({"_id": claimed["_id"]})
    await admit_modifications(queue, [page])
    assert await queue.collection.find_one({"_id": claimed["_id"]}) == before
    changed = ModificationPage(
        "82453304", WATERMARK, NOW, [row(1, WATERMARK + timedelta(seconds=1))]
    )
    result = (await admit_modifications(queue, [changed]))[0]
    assert result.accepted_keys != results[0][0].accepted_keys
    assert await queue.collection.count_documents({}) == 2


@pytest.mark.asyncio
async def test_same_timestamp_changed_payload_is_not_silently_coalesced(
    queue: FormulaRecoveryQueue,
) -> None:
    original = row(1, WATERMARK)
    first = (
        await admit_modifications(queue, [ModificationPage("82453304", WATERMARK, NOW, [original])])
    )[0]
    second = (
        await admit_modifications(
            queue,
            [ModificationPage("82453304", WATERMARK, NOW, [{**original, "status": "cancelled"}])],
        )
    )[0]
    assert first.accepted_keys != second.accepted_keys


@pytest.mark.asyncio
async def test_capacity_and_invalid_seller_do_not_block_other_sellers(
    queue: FormulaRecoveryQueue,
) -> None:
    pages = [
        ModificationPage(
            "82453304", WATERMARK, NOW, [row(index, WATERMARK) for index in (1, 2, 3)]
        ),
        ModificationPage("456", WATERMARK, NOW, [row(1, WATERMARK, "456")]),
        ModificationPage("123", WATERMARK, NOW, [row(1, WATERMARK, "123")]),
    ]
    results = await admit_modifications(queue, pages)
    assert [result.state for result in results] == ["deferred", "failed", "admitted"]
    assert len(results[0].accepted_keys) == 2 and len(results[2].accepted_keys) == 1
    assert await queue.collection.count_documents({"seller_id": "456"}) == 0
    assert await queue.collection.database.sheets_history_acquisitions.count_documents({}) == 0
    assert await queue.collection.database.sheets_read_model_freshness.count_documents({}) == 0


@pytest.mark.asyncio
async def test_replay_after_partial_admission_retains_failed_checkpoint_work(
    queue: FormulaRecoveryQueue,
) -> None:
    page = ModificationPage(
        "82453304", WATERMARK, NOW, [row(index, WATERMARK) for index in (1, 2, 3)]
    )
    result = (await admit_modifications(queue, [page]))[0]
    assert result.state == "deferred"
    claimed = await queue.claim()
    assert claimed is not None
    await queue.finish(claimed, succeeded=True)
    replay = (await admit_modifications(queue, [page]))[0]
    assert replay.state == "admitted" and len(replay.accepted_keys) == 3
    assert await queue.collection.count_documents({}) == 3


@pytest.mark.asyncio
async def test_storage_failure_is_isolated_to_its_seller(
    queue: FormulaRecoveryQueue, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = queue.enqueue

    async def unavailable(request: Any, **kwargs: Any) -> str:
        if request.seller_id == "82453304":
            raise AutoReconnect("test failure")
        return await original(request, **kwargs)

    monkeypatch.setattr(queue, "enqueue", unavailable)
    results = await admit_modifications(
        queue,
        [
            ModificationPage("82453304", WATERMARK, NOW, [row(1, WATERMARK)]),
            ModificationPage("123", WATERMARK, NOW, [row(1, WATERMARK, "123")]),
        ],
    )
    assert results[0].reason == "storage_unavailable" and results[1].state == "admitted"
    assert await queue.collection.count_documents({}) == 1


@pytest.mark.asyncio
async def test_invalid_checkpoint_input_does_not_abort_other_sellers(
    queue: FormulaRecoveryQueue,
) -> None:
    results = await admit_modifications(
        queue,
        [
            ModificationPage("82453304", cast(Any, "invalid"), NOW, []),
            ModificationPage("123", WATERMARK, NOW, [row(1, WATERMARK, "123")]),
        ],
    )
    assert [result.state for result in results] == ["failed", "admitted"]
