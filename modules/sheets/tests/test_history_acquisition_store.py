from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from infra.mongo.apply_validators import apply_validators
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from zeler_platform_core.models import SheetsHistoryAcquisition, SheetsHistoryReceipt
from zeler_sheets.formulas.recovery import FormulaRecoveryQueue, RecoveryRequest
from zeler_sheets.history_acquisition import (
    HistoryAcquisitionStore,
    HistoryConflictError,
    HistoryLimitError,
)
from zeler_sheets.history_continuation import HistoryContinuation
from zeler_sheets.history_range_store import HistoryRangeStore
from zeler_sheets.item_projection import item_source_fingerprint

NOW = datetime(2026, 9, 15, tzinfo=UTC)


@dataclass
class Harness:
    db: AsyncIOMotorDatabase[dict[str, Any]]
    store: HistoryAcquisitionStore
    job: dict[str, Any]
    head: SheetsHistoryAcquisition
    clock: list[datetime]


@pytest_asyncio.fixture
async def harness(tmp_path: Path) -> AsyncIterator[Harness]:
    name = f"zeler_history_store_{uuid4().hex}"
    uri = f"mongodb://127.0.0.1:27028/{name}?directConnection=true"
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        uri, tz_aware=True, serverSelectionTimeoutMS=2000
    )
    hello = await client.admin.command("hello")
    assert hello["isWritablePrimary"] and hello["setName"] == "rs0"
    root = Path(__file__).resolve().parents[3] / "infra/mongo"
    for directory in ("schemas", "indexes"):
        (tmp_path / directory).mkdir()
        for collection in (
            "sheets_history_acquisitions",
            "sheets_history_receipts",
            "sheets_history_order_ranges",
        ):
            filename = f"{collection}.json"
            (tmp_path / directory / filename).write_text((root / directory / filename).read_text())
    try:
        await asyncio.to_thread(apply_validators, uri, tmp_path / "schemas")
        database = client[name]
        clock = [NOW]
        queue = FormulaRecoveryQueue(database, now=lambda: clock[0])
        request = RecoveryRequest("82453304", "orders", NOW - timedelta(days=31), NOW)
        await queue.enqueue(request)
        job = await queue.claim()
        assert job is not None
        head = SheetsHistoryAcquisition(
            _id="head",
            seller_id=request.seller_id,
            read_model="orders",
            plan_id="plan",
            scope_id="orders:20260815:20260915",
            job_id=job["_id"],
            date_from=request.date_from,
            date_to=request.date_to,
            created_at=NOW,
            updated_at=NOW,
        )
        yield Harness(database, HistoryAcquisitionStore(database, queue), job, head, clock)
    finally:
        await client.drop_database(name)
        client.close()


def receipt(**changes: Any) -> SheetsHistoryReceipt:
    return SheetsHistoryReceipt.model_validate(
        {
            "_id": "receipt",
            "acquisition_id": "head",
            "seller_id": "82453304",
            "read_model": "orders",
            "generation": 1,
            "pass_number": 1,
            "page_sequence": 1,
            "kind": "membership",
            "resource_id": "200001",
            "observed_at": NOW,
            **changes,
        }
    )


async def claim_range(harness: Harness, head: SheetsHistoryAcquisition) -> None:
    harness.head = head
    job = await harness.store.queue.claim(history=True)
    assert job is not None
    harness.job = job


async def start_range(harness: Harness) -> HistoryRangeStore:
    await harness.store.initialize(harness.job, harness.head)
    ranges = HistoryRangeStore(HistoryContinuation(harness.store), result_budget=1)
    await claim_range(harness, await ranges.start(harness.job, harness.head))
    return ranges


@pytest.mark.asyncio
async def test_range_split_and_child_pages_are_durable(harness: Harness) -> None:
    ranges = await start_range(harness)
    root_id = harness.head.active_range_id
    await claim_range(harness, await ranges.split(harness.job, harness.head, observed_total=2))
    assert harness.head.active_range_id != root_id
    for identity in (1, 2):
        active = await ranges.collection.find_one({"_id": harness.head.active_range_id})
        assert active is not None
        raw = {
            "id": identity,
            "seller_id": "82453304",
            "date_created": active["date_from"].isoformat(),
        }
        record = receipt(
            _id=str(identity),
            resource_id=str(identity),
            page_sequence=harness.head.page_sequence + 1,
            source_payload=raw,
            source_hash=item_source_fingerprint(raw),
        )
        await claim_range(
            harness,
            await ranges.page(
                harness.job, harness.head, source_total=1, next_offset=1, receipts=[record]
            ),
        )
    assert harness.head.phase == "hydrate" and harness.head.active_range_id is None
    assert harness.head.source_total == 2 and harness.head.discovered_count == 2
    assert harness.head.observed_from == NOW and harness.head.observed_until == NOW
    assert await ranges.collection.count_documents({"state": "enumerated"}) == 2
    assert await harness.db.sheets_read_model_freshness.count_documents({}) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("expired", [False, True])
async def test_range_split_rejects_stale_or_expired_owner(harness: Harness, expired: bool) -> None:
    ranges = await start_range(harness)
    prior = harness.head
    if expired:
        harness.clock[0] += timedelta(hours=1)
    else:
        await claim_range(harness, await ranges.split(harness.job, prior, observed_total=2))
    with pytest.raises(HistoryConflictError):
        await ranges.split(harness.job, prior, observed_total=2)


@pytest.mark.asyncio
async def test_range_split_rolls_back_children_pointer_and_queue(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    ranges = await start_range(harness)
    before = harness.head

    async def interrupted(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("split interrupted")

    monkeypatch.setattr(ranges.continuation, "_pending", interrupted)
    with pytest.raises(RuntimeError, match="split interrupted"):
        await ranges.split(harness.job, before, observed_total=2)
    assert await ranges.collection.count_documents({}) == 1
    assert await ranges.collection.count_documents({"state": "split"}) == 0
    assert await harness.store.heads.find_one({"_id": before.id}) == before.model_dump(
        by_alias=True
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("defect", ["seller", "date", "naive", "offset"])
async def test_range_page_rejects_bad_scope_and_cursor(harness: Harness, defect: str) -> None:
    ranges = await start_range(harness)
    created = harness.head.date_from + timedelta(days=1)
    if defect == "date":
        created = harness.head.date_to + timedelta(hours=2)
    if defect == "naive":
        created = created.replace(tzinfo=None)
    raw = {
        "id": 200001,
        "seller_id": "999" if defect == "seller" else "82453304",
        "date_created": created.isoformat(),
    }
    record = receipt(
        page_sequence=harness.head.page_sequence + 1,
        source_payload=raw,
        source_hash=item_source_fingerprint(raw),
    )
    with pytest.raises(ValueError):
        await ranges.page(
            harness.job,
            harness.head,
            source_total=1,
            next_offset=2 if defect == "offset" else 1,
            receipts=[record],
        )
    assert await harness.store.receipts.count_documents({}) == 0
    assert await ranges.collection.count_documents({"state": "enumerated"}) == 0


@pytest.mark.asyncio
async def test_range_empty_children_cannot_erase_nonempty_parent_total(harness: Harness) -> None:
    ranges = await start_range(harness)
    await claim_range(harness, await ranges.split(harness.job, harness.head, observed_total=2))
    await claim_range(
        harness,
        await ranges.page(harness.job, harness.head, source_total=0, next_offset=0, receipts=[]),
    )
    with pytest.raises(HistoryConflictError, match="source totals changed"):
        await ranges.page(harness.job, harness.head, source_total=0, next_offset=0, receipts=[])
    assert harness.head.phase == "discover"
    assert await ranges.collection.count_documents({"state": "pending"}) == 1


@pytest.mark.asyncio
async def test_range_legacy_head_and_restart_keep_old_nodes(harness: Harness) -> None:
    await harness.store.initialize(harness.job, harness.head)
    await harness.store.heads.update_one(
        {"_id": harness.head.id}, {"$unset": {"active_range_id": ""}}
    )
    ranges = HistoryRangeStore(HistoryContinuation(harness.store))
    await claim_range(harness, await ranges.start(harness.job, harness.head))
    previous = harness.head
    restarted = await ranges.continuation.release(harness.job, previous, reason="source_drift")
    assert restarted.active_range_id is None and restarted.pass_number == 2
    assert await ranges.collection.count_documents({"pass_number": 1}) == 1


@pytest.mark.asyncio
async def test_range_partial_page_resume_rejects_duplicate_identity(harness: Harness) -> None:
    ranges = await start_range(harness)
    ranges.result_budget = 2
    for identity in (1, 2):
        raw = {
            "id": identity,
            "seller_id": "82453304",
            "date_created": harness.head.date_from.isoformat(),
        }
        record = receipt(
            _id=str(identity),
            resource_id=str(identity),
            page_sequence=harness.head.page_sequence + 1,
            source_payload=raw,
            source_hash=item_source_fingerprint(raw),
        )
        await claim_range(
            harness,
            await ranges.page(
                harness.job, harness.head, source_total=2, next_offset=identity, receipts=[record]
            ),
        )
        if identity == 1:
            duplicate = record.model_copy(update={"page_sequence": harness.head.page_sequence + 1})
            with pytest.raises(HistoryConflictError, match="repeats acquired identity"):
                await ranges.page(
                    harness.job, harness.head, source_total=2, next_offset=2, receipts=[duplicate]
                )
            ranges = HistoryRangeStore(HistoryContinuation(harness.store), result_budget=2)
    assert harness.head.phase == "hydrate"
    assert await harness.store.receipts.count_documents({}) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [{"seller_id": "999"}, {"generation": 2}, {"root_id": "other"}])
async def test_range_node_cannot_escape_head_ownership(
    harness: Harness, changes: dict[str, Any]
) -> None:
    ranges = await start_range(harness)
    await ranges.collection.update_one({"_id": harness.head.active_range_id}, {"$set": changes})
    with pytest.raises(HistoryConflictError):
        await ranges.split(harness.job, harness.head, observed_total=2)
    assert await ranges.collection.count_documents({}) == 1


@pytest.mark.asyncio
async def test_range_rejects_oversized_batch_before_transaction_work(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    ranges = await start_range(harness)

    async def unexpected(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("unbounded batch reached transaction")

    monkeypatch.setattr(ranges, "_active", unexpected)
    with pytest.raises(HistoryLimitError):
        await ranges.page(
            harness.job, harness.head, source_total=51, next_offset=51, receipts=[receipt()] * 51
        )


def next_head(head: SheetsHistoryAcquisition, **changes: Any) -> SheetsHistoryAcquisition:
    return SheetsHistoryAcquisition.model_validate(
        {
            **head.model_dump(by_alias=True),
            "checkpoint_revision": head.checkpoint_revision + 1,
            "page_sequence": head.page_sequence + 1,
            "discovered_count": 1,
            **changes,
        }
    )


@pytest.mark.asyncio
async def test_initialize_checkpoint_replay_and_resume(harness: Harness) -> None:
    store, job, head = harness.store, harness.job, harness.head
    assert await store.initialize(job, head) == head
    candidate = next_head(head, next_cursor=50)
    assert await store.checkpoint(job, head, candidate, [receipt()]) == candidate
    assert await store.checkpoint(job, head, candidate, [receipt()]) == candidate
    assert await store.initialize(job, head) == candidate
    detail = receipt(
        _id="detail",
        kind="detail",
        page_sequence=2,
        payload={"id": 200001, "status": "paid"},
        payload_hash=item_source_fingerprint({"id": 200001, "status": "paid"}),
    )
    hydrated = next_head(candidate, phase="hydrate", fetched_count=1)
    assert await store.checkpoint(job, candidate, hydrated, [detail]) == hydrated
    assert await harness.db.sheets_history_receipts.count_documents({}) == 2


@pytest.mark.asyncio
async def test_head_timestamp_cannot_regress(harness: Harness) -> None:
    await harness.store.initialize(harness.job, harness.head)
    current = next_head(harness.head, updated_at=NOW + timedelta(seconds=2))
    await harness.store.checkpoint(harness.job, harness.head, current, [receipt()])
    regressed = next_head(current, updated_at=NOW + timedelta(seconds=1))
    with pytest.raises(HistoryConflictError):
        await harness.store.checkpoint(harness.job, current, regressed, [])


@pytest.mark.asyncio
async def test_duplicate_page_preserves_original_observation(harness: Harness) -> None:
    await harness.store.initialize(harness.job, harness.head)
    current = next_head(harness.head)
    await harness.store.checkpoint(harness.job, harness.head, current, [receipt()])
    repeated = receipt(_id="different-id", page_sequence=2, observed_at=NOW + timedelta(seconds=1))
    await harness.store.checkpoint(harness.job, current, next_head(current), [repeated])
    stored = await harness.db.sheets_history_receipts.find_one({"_id": "receipt"})
    assert stored is not None and stored["observed_at"] == NOW
    assert await harness.db.sheets_history_receipts.count_documents({}) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["expired", "replaced", "seller", "generation", "disabled"])
async def test_lost_fence_or_binding_cannot_write(harness: Harness, change: str) -> None:
    await harness.store.initialize(harness.job, harness.head)
    job = dict(harness.job)
    candidate = next_head(harness.head)
    if change == "expired":
        harness.clock[0] += timedelta(hours=1)
    elif change == "replaced":
        await harness.store.queue.collection.update_one(
            {"_id": job["_id"]}, {"$set": {"attempt_token": "new"}}
        )
    elif change == "seller":
        job["seller_id"] = "2"
    elif change == "disabled":
        harness.store.queue.allowed_sellers = frozenset()
    else:
        candidate = next_head(harness.head, generation=2)
    with pytest.raises(HistoryConflictError):
        await harness.store.checkpoint(job, harness.head, candidate, [receipt()])
    assert await harness.db.sheets_history_receipts.count_documents({}) == 0
    stored = await harness.db.sheets_history_acquisitions.find_one({"_id": "head"})
    assert stored is not None and stored["checkpoint_revision"] == 0


@pytest.mark.asyncio
async def test_initialization_cannot_expand_owned_request(harness: Harness) -> None:
    expanded = harness.head.model_copy(update={"date_from": NOW - timedelta(days=32)})
    with pytest.raises(HistoryConflictError):
        await harness.store.initialize(harness.job, expanded)
    assert await harness.db.sheets_history_acquisitions.count_documents({}) == 0


@pytest.mark.asyncio
async def test_failure_after_receipt_insert_rolls_back_every_write(
    harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await harness.store.initialize(harness.job, harness.head)
    before = await harness.store.queue.collection.find_one({"_id": harness.job["_id"]})

    async def fail_replace(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("simulated interrupted checkpoint")

    monkeypatch.setattr(harness.store.heads, "replace_one", fail_replace)
    with pytest.raises(RuntimeError, match="interrupted checkpoint"):
        await harness.store.checkpoint(
            harness.job, harness.head, next_head(harness.head), [receipt()]
        )
    assert await harness.db.sheets_history_receipts.count_documents({}) == 0
    assert await harness.store.queue.collection.find_one({"_id": harness.job["_id"]}) == before


@pytest.mark.asyncio
async def test_conflicting_duplicate_and_stale_checkpoint_preserve_history(
    harness: Harness,
) -> None:
    await harness.store.initialize(harness.job, harness.head)
    candidate = next_head(harness.head)
    await harness.store.checkpoint(harness.job, harness.head, candidate, [receipt()])
    conflicting = receipt(source_version="changed")
    with pytest.raises(HistoryConflictError):
        await harness.store.checkpoint(harness.job, harness.head, candidate, [conflicting])
    with pytest.raises(HistoryConflictError):
        await harness.store.checkpoint(
            harness.job, harness.head, next_head(harness.head, next_cursor=99), [receipt()]
        )
    stored = await harness.db.sheets_history_receipts.find_one({"_id": "receipt"})
    assert stored is not None and stored["source_version"] is None
    with pytest.raises(HistoryConflictError):
        await harness.store.checkpoint(
            harness.job,
            candidate,
            next_head(candidate, discovered_count=2),
            [receipt(resource_id="other", page_sequence=2)],
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "unsafe",
    [
        {"bad.key": 1},
        {"$bad": 1},
        {"bad\0key": 1},
        {"nested": [{"$bad": 1}]},
        {"value": float("inf")},
    ],
)
async def test_unsafe_payload_never_reaches_storage(
    harness: Harness, unsafe: dict[str, Any]
) -> None:
    await harness.store.initialize(harness.job, harness.head)
    detail = receipt(kind="detail", payload={"id": 200001, **unsafe}, payload_hash="a" * 64)
    with pytest.raises(ValueError):
        await harness.store.checkpoint(harness.job, harness.head, next_head(harness.head), [detail])
    assert await harness.db.sheets_history_receipts.count_documents({}) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", ["receipt", "batch", "count", "head"])
async def test_whole_document_and_batch_budgets(harness: Harness, limit: str) -> None:
    await harness.store.initialize(harness.job, harness.head)
    candidate = next_head(harness.head)
    receipts = [receipt(source_version="x" * (1024 * 1024))]
    if limit == "batch":
        receipts = [
            receipt(_id=str(index), resource_id=str(index), source_version="x" * 900_000)
            for index in range(5)
        ]
        candidate = next_head(harness.head, discovered_count=5)
    elif limit == "count":
        receipts = [receipt(_id=str(index), resource_id=str(index)) for index in range(51)]
        candidate = next_head(harness.head, discovered_count=51)
    elif limit == "head":
        oversized = harness.head.model_copy(update={"plan_id": "x" * 65536})
        with pytest.raises(HistoryLimitError):
            await harness.store.initialize(harness.job, oversized)
        return
    with pytest.raises(HistoryLimitError):
        await harness.store.checkpoint(harness.job, harness.head, candidate, receipts)
    assert await harness.db.sheets_history_receipts.count_documents({}) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("identical", [True, False])
async def test_concurrent_checkpoint_only_commits_one_revision(
    harness: Harness, identical: bool
) -> None:
    await harness.store.initialize(harness.job, harness.head)
    first = next_head(harness.head, next_cursor=50)
    second = first if identical else next_head(harness.head, next_cursor=100)
    results = await asyncio.gather(
        harness.store.checkpoint(harness.job, harness.head, first, [receipt()]),
        harness.store.checkpoint(harness.job, harness.head, second, [receipt()]),
        return_exceptions=True,
    )
    assert sum(isinstance(result, SheetsHistoryAcquisition) for result in results) == (
        2 if identical else 1
    )
    if not identical:
        assert sum(isinstance(result, HistoryConflictError) for result in results) == 1
    stored = await harness.db.sheets_history_acquisitions.find_one({"_id": "head"})
    assert stored is not None and stored["checkpoint_revision"] == stored["discovered_count"] == 1
    assert await harness.db.sheets_history_receipts.count_documents({}) == 1


@pytest.mark.asyncio
async def test_lease_expiring_after_insert_aborts_transaction(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    await harness.store.initialize(harness.job, harness.head)
    original = harness.store.receipts.insert_one

    async def expire_after_insert(*args: Any, **kwargs: Any) -> Any:
        result = await original(*args, **kwargs)
        harness.clock[0] += timedelta(hours=1)
        return result

    monkeypatch.setattr(harness.store.receipts, "insert_one", expire_after_insert)
    with pytest.raises(HistoryConflictError):
        await harness.store.checkpoint(
            harness.job, harness.head, next_head(harness.head), [receipt()]
        )
    assert await harness.db.sheets_history_receipts.count_documents({}) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "defect", ["hash", "identity", "membership", "count", "receipt_seller", "publication"]
)
async def test_unproven_receipts_or_progress_cannot_advance(harness: Harness, defect: str) -> None:
    await harness.store.initialize(harness.job, harness.head)
    candidate = next_head(harness.head)
    records = [receipt()]
    if defect in {"hash", "identity", "membership"}:
        payload = {"id": 2 if defect == "identity" else 200001}
        records = [
            receipt(
                kind="detail",
                payload=payload,
                payload_hash="a" * 64 if defect == "hash" else item_source_fingerprint(payload),
            )
        ]
        candidate = next_head(harness.head, fetched_count=1)
    elif defect == "count":
        candidate = next_head(harness.head, discovered_count=2)
    elif defect == "receipt_seller":
        records = [receipt(seller_id="2")]
    else:
        candidate = next_head(harness.head, phase="publish")
    with pytest.raises(HistoryConflictError):
        await harness.store.checkpoint(harness.job, harness.head, candidate, records)
    assert await harness.db.sheets_history_receipts.count_documents({}) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("defect", [None, "hash", "identity", "seller"])
async def test_raw_source_identity_and_hash_are_checked(
    harness: Harness, defect: str | None
) -> None:
    await harness.store.initialize(harness.job, harness.head)
    source: dict[str, Any] = {"id": 2 if defect == "identity" else 200001, "tags": ["paid"]}
    if defect == "seller":
        source["seller_id"] = "other"
    record = receipt(
        source_payload=source,
        source_hash="0" * 64 if defect == "hash" else item_source_fingerprint(source),
    )
    if defect is not None:
        with pytest.raises(HistoryConflictError):
            await harness.store.checkpoint(
                harness.job, harness.head, next_head(harness.head), [record]
            )
        assert await harness.db.sheets_history_receipts.count_documents({}) == 0
    else:
        await harness.store.checkpoint(harness.job, harness.head, next_head(harness.head), [record])
        stored = await harness.db.sheets_history_receipts.find_one({"_id": record.id})
        assert stored is not None and stored["source_payload"] == source


@pytest.mark.asyncio
@pytest.mark.parametrize("large", [False, True])
async def test_raw_source_obeys_existing_safety_and_whole_document_limits(
    harness: Harness, large: bool
) -> None:
    await harness.store.initialize(harness.job, harness.head)
    source = (
        {"id": 200001, "value": "x" * 1048576}
        if large
        else {"id": 200001, "nested": {"$unsafe": 1}}
    )
    record = receipt(source_payload=source, source_hash=item_source_fingerprint(source))
    with pytest.raises(HistoryLimitError if large else ValueError):
        await harness.store.checkpoint(harness.job, harness.head, next_head(harness.head), [record])
    assert await harness.db.sheets_history_receipts.count_documents({}) == 0
