from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
import pytest_asyncio
from infra.mongo.apply_validators import apply_validators
from motor.motor_asyncio import AsyncIOMotorClient

from zeler_sheets.formulas.recovery import FormulaRecoveryQueue
from zeler_sheets.modification_recovery import (
    ModificationEnumerationDriftError,
    ModificationPage,
    ModificationSearchPage,
)
from zeler_sheets.modification_scan_store import ModificationScanStore
from zeler_sheets.modification_scan_worker import ModificationScanWorker

NOW = datetime(2026, 9, 15, 12, 17, tzinfo=UTC)
WATERMARK = NOW - timedelta(hours=1)
SELLER = "82453304"


def order(identity: int, *, modified: datetime = WATERMARK) -> dict[str, Any]:
    return {
        "id": identity,
        "seller": {"id": 82453304},
        "date_created": "2026-02-01T00:00:00Z",
        "date_last_updated": modified.isoformat(),
    }


def page(
    rows: list[dict[str, Any]], *, total: int, next_offset: int | None
) -> ModificationSearchPage:
    return ModificationSearchPage(
        ModificationPage(SELLER, WATERMARK, NOW, rows), total, next_offset
    )


@pytest_asyncio.fixture
async def runtime(
    tmp_path: Path,
) -> AsyncIterator[tuple[Any, FormulaRecoveryQueue, ModificationScanStore]]:
    name = f"zeler_modification_scan_{uuid4().hex}"
    uri = f"mongodb://127.0.0.1:27028/{name}?directConnection=true"
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        uri,
        tz_aware=True,
        serverSelectionTimeoutMS=2000,
    )
    hello = await client.admin.command("hello")
    assert hello["isWritablePrimary"] and hello["setName"] == "rs0"
    schema_dir = tmp_path / "schemas"
    schema_dir.mkdir()
    schema_source = (
        Path(__file__).resolve().parents[3] / "infra/mongo/schemas/sheets_history_receipts.json"
    )
    (schema_dir / schema_source.name).write_text(schema_source.read_text())
    await asyncio.to_thread(apply_validators, uri, schema_dir)
    db = client[name]
    await db.sheets_history_backfill_plans.insert_one(
        {"_id": SELLER, "seller_id": SELLER, "cutoff": WATERMARK, "schema_version": 1}
    )
    await db.sheets_history_receipts.create_index(
        [
            ("acquisition_id", 1),
            ("generation", 1),
            ("pass_number", 1),
            ("kind", 1),
            ("resource_id", 1),
        ],
        unique=True,
    )
    queue = FormulaRecoveryQueue(
        db, now=lambda: NOW, allowed_sellers=frozenset({SELLER}), max_active_jobs_per_seller=5
    )
    store = ModificationScanStore(db, queue, now=lambda: NOW)
    try:
        yield db, queue, store
    finally:
        await client.drop_database(name)
        client.close()


@pytest.mark.asyncio
async def test_scan_checkpoint_waits_for_jobs_before_advancing_watermark(
    runtime: tuple[Any, FormulaRecoveryQueue, ModificationScanStore],
) -> None:
    db, queue, store = runtime
    scan = await store.begin(SELLER, cutoff=NOW)
    assert scan.watermark == WATERMARK and scan.phase == "discover"
    observed = page([order(1)], total=1, next_offset=None)
    scan = await store.advance(scan, observed)
    assert scan.phase == "verify" and scan.next_offset == 0
    assert await db.sheets_history_receipts.count_documents({"pass_number": 1}) == 1
    assert (await db.sheets_history_backfill_plans.find_one({"_id": SELLER})).get(
        "modification_watermark"
    ) is None
    assert await store.advance(scan, observed) == scan
    job = await queue.claim(lane="ids")
    assert job is not None and await queue.finish(job, succeeded=True)
    completed = await store.advance(scan, observed)
    assert completed.phase == "completed"
    persisted = await db.sheets_history_backfill_plans.find_one({"_id": SELLER})
    assert persisted["modification_watermark"] == NOW
    assert await db.sheets_history_receipts.count_documents({"pass_number": 2}) == 1


@pytest.mark.asyncio
async def test_interrupted_page_admission_replays_without_advancing_cursor(
    runtime: tuple[Any, FormulaRecoveryQueue, ModificationScanStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, queue, store = runtime
    scan = await store.begin(SELLER, cutoff=NOW)
    original = store._checkpoint

    async def interrupted(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("checkpoint interrupted after admission")

    monkeypatch.setattr(store, "_checkpoint", interrupted)
    with pytest.raises(RuntimeError, match="checkpoint interrupted"):
        await store.advance(scan, page([order(1)], total=1, next_offset=None))
    assert await queue.collection.count_documents({}) == 1
    assert await db.sheets_history_receipts.count_documents({}) == 0
    assert (await store.begin(SELLER, cutoff=NOW)) == scan
    monkeypatch.setattr(store, "_checkpoint", original)
    resumed = await store.advance(scan, page([order(1)], total=1, next_offset=None))
    assert resumed.phase == "verify"
    assert await queue.collection.count_documents({}) == 1
    assert await db.sheets_history_receipts.count_documents({}) == 1


@pytest.mark.asyncio
async def test_same_total_changed_membership_cannot_advance_watermark(
    runtime: tuple[Any, FormulaRecoveryQueue, ModificationScanStore],
) -> None:
    db, queue, store = runtime
    scan = await store.begin(SELLER, cutoff=NOW)
    scan = await store.advance(scan, page([order(1)], total=1, next_offset=None))
    job = await queue.claim(lane="ids")
    assert job is not None and await queue.finish(job, succeeded=True)
    with pytest.raises(ModificationEnumerationDriftError):
        await store.advance(scan, page([order(2)], total=1, next_offset=None))
    assert (await db.sheets_history_backfill_plans.find_one({"_id": SELLER})).get(
        "modification_watermark"
    ) is None
    assert await db.sheets_history_receipts.count_documents({"pass_number": 2}) == 0


@pytest.mark.asyncio
async def test_resumed_multi_page_scan_keeps_exact_cursor_and_completion(
    runtime: tuple[Any, FormulaRecoveryQueue, ModificationScanStore],
) -> None:
    db, queue, store = runtime
    scan = await store.begin(SELLER, cutoff=NOW)
    scan = await store.advance(scan, page([order(1)], total=2, next_offset=1))
    assert scan.phase == "discover" and scan.next_offset == 1
    resumed_store = ModificationScanStore(db, queue, now=lambda: NOW)
    scan = await resumed_store.begin(SELLER, cutoff=NOW)
    assert scan.next_offset == 1
    scan = await resumed_store.advance(scan, page([order(2)], total=2, next_offset=None))
    assert scan.phase == "verify" and scan.next_offset == 0
    for _ in range(2):
        job = await queue.claim(lane="ids")
        assert job is not None and await queue.finish(job, succeeded=True)
    scan = await resumed_store.advance(scan, page([order(1)], total=2, next_offset=1))
    assert scan.phase == "verify" and scan.next_offset == 1
    scan = await resumed_store.advance(scan, page([order(2)], total=2, next_offset=None))
    assert scan.phase == "completed"
    assert (await db.sheets_history_backfill_plans.find_one({"_id": SELLER}))[
        "modification_watermark"
    ] == NOW


@pytest.mark.asyncio
async def test_partial_capacity_replays_page_without_committing_evidence(
    runtime: tuple[Any, FormulaRecoveryQueue, ModificationScanStore],
) -> None:
    db, queue, store = runtime
    queue.max_active_jobs_per_seller = 1
    scan = await store.begin(SELLER, cutoff=NOW)
    observed = page([order(1), order(2)], total=2, next_offset=None)
    assert await store.advance(scan, observed) == scan
    assert await db.sheets_history_receipts.count_documents({}) == 0
    assert await queue.collection.count_documents({}) == 1
    job = await queue.claim(lane="ids")
    assert job is not None and await queue.finish(job, succeeded=True)
    resumed = await store.advance(scan, observed)
    assert resumed.phase == "verify"
    assert await db.sheets_history_receipts.count_documents({"pass_number": 1}) == 2


@pytest.mark.asyncio
async def test_repeated_identity_on_later_page_rejects_checkpoint(
    runtime: tuple[Any, FormulaRecoveryQueue, ModificationScanStore],
) -> None:
    db, _, store = runtime
    scan = await store.begin(SELLER, cutoff=NOW)
    scan = await store.advance(scan, page([order(1)], total=2, next_offset=1))
    with pytest.raises(ModificationEnumerationDriftError):
        await store.advance(scan, page([order(1)], total=2, next_offset=None))
    assert await db.sheets_history_receipts.count_documents({"pass_number": 1}) == 1
    assert (await store.begin(SELLER, cutoff=NOW)).next_offset == 1


@pytest.mark.asyncio
async def test_failed_id_job_never_advances_watermark(
    runtime: tuple[Any, FormulaRecoveryQueue, ModificationScanStore],
) -> None:
    db, queue, store = runtime
    scan = await store.begin(SELLER, cutoff=NOW)
    observed = page([order(1)], total=1, next_offset=None)
    scan = await store.advance(scan, observed)
    job = await queue.claim(lane="ids")
    assert job is not None and await queue.finish(job, succeeded=False)
    with pytest.raises(ValueError, match="did not complete"):
        await store.advance(scan, observed)
    assert (await db.sheets_history_backfill_plans.find_one({"_id": SELLER})).get(
        "modification_watermark"
    ) is None


@pytest.mark.asyncio
async def test_corrupt_stored_scan_fails_before_any_source_or_queue_work(
    runtime: tuple[Any, FormulaRecoveryQueue, ModificationScanStore],
) -> None:
    db, queue, store = runtime
    scan = await store.begin(SELLER, cutoff=NOW)
    await db.sheets_history_backfill_plans.update_one(
        {"_id": SELLER}, {"$set": {"modification_scan.source_total": -1}}
    )
    with pytest.raises(ValueError, match="scan state"):
        await store.begin(SELLER, cutoff=NOW)
    assert await queue.collection.count_documents({}) == 0
    assert scan.phase == "discover"


@pytest.mark.asyncio
async def test_completed_scan_waits_for_next_cycle_then_keeps_watermark(
    runtime: tuple[Any, FormulaRecoveryQueue, ModificationScanStore],
) -> None:
    _, _, store = runtime
    scan = await store.begin(SELLER, cutoff=NOW)
    scan = await store.advance(scan, page([], total=0, next_offset=None))
    scan = await store.advance(scan, page([], total=0, next_offset=None))
    assert scan.phase == "completed"
    assert await store.begin(SELLER, cutoff=NOW + timedelta(minutes=10)) == scan
    next_scan = await store.begin(SELLER, cutoff=NOW + timedelta(minutes=16))
    assert next_scan.phase == "discover" and next_scan.watermark == NOW
    assert next_scan.cutoff == NOW + timedelta(minutes=16)


@pytest.mark.asyncio
async def test_repeated_source_drift_is_bounded_without_watermark(
    runtime: tuple[Any, FormulaRecoveryQueue, ModificationScanStore],
) -> None:
    db, _, store = runtime
    scan = await store.begin(SELLER, cutoff=NOW)
    for generation in (2, 3, 4):
        scan = await store.restart(scan)
        assert scan.phase == "discover" and scan.generation == generation
        assert scan.next_offset == 0 and scan.source_total is None
    failed = await store.restart(scan)
    assert failed.phase == "failed"
    assert await store.begin(SELLER, cutoff=NOW + timedelta(hours=1)) == failed
    assert (await db.sheets_history_backfill_plans.find_one({"_id": SELLER})).get(
        "modification_watermark"
    ) is None


class Gateway:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.offsets: list[int] = []

    async def fetch_resource(self, *, seller_id: str, path: str) -> dict[str, Any]:
        assert seller_id == SELLER
        assert urlsplit(path).path == "/orders/search"
        query = parse_qs(urlsplit(path).query)
        offset = int(query["offset"][0])
        self.offsets.append(offset)
        return {
            "paging": {"total": len(self.rows), "offset": offset, "limit": 50},
            "results": self.rows[offset : offset + 50],
        }


@pytest.mark.asyncio
async def test_worker_reconciles_old_order_then_waits_for_next_cycle(
    runtime: tuple[Any, FormulaRecoveryQueue, ModificationScanStore],
) -> None:
    db, queue, store = runtime
    gateway = Gateway([order(1)])
    worker = ModificationScanWorker(store, gateway, sellers=frozenset({SELLER}), now=lambda: NOW)
    assert await worker.process_once() == "processed"
    assert await worker.process_once() == "idle"
    job = await queue.claim(lane="ids")
    assert job is not None and await queue.finish(job, succeeded=True)
    assert await worker.process_once() == "processed"
    assert (await db.sheets_history_backfill_plans.find_one({"_id": SELLER}))[
        "modification_watermark"
    ] == NOW
    assert await worker.process_once() == "idle"
    assert gateway.offsets == [0, 0, 0]


@pytest.mark.asyncio
async def test_worker_restarts_drift_then_preserves_other_seller_progress(
    runtime: tuple[Any, FormulaRecoveryQueue, ModificationScanStore],
) -> None:
    db, queue, store = runtime
    other = "82453305"
    queue.allowed_sellers = frozenset({SELLER, other})
    await db.sheets_history_backfill_plans.insert_one(
        {"_id": other, "seller_id": other, "cutoff": NOW, "schema_version": 1}
    )

    class DriftingGateway:
        async def fetch_resource(self, *, seller_id: str, path: str) -> dict[str, Any]:
            query = parse_qs(urlsplit(path).query)
            offset = int(query["offset"][0])
            if seller_id == SELLER:
                return {"paging": {"total": 1, "offset": offset, "limit": 50}, "results": []}
            return {"paging": {"total": 0, "offset": offset, "limit": 50}, "results": []}

    worker = ModificationScanWorker(
        store, DriftingGateway(), sellers=frozenset({SELLER, other}), now=lambda: NOW
    )
    assert await worker.process_once() == "processed"
    first = await db.sheets_history_backfill_plans.find_one({"_id": SELLER})
    assert first["modification_scan"]["generation"] == 2
    assert await worker.process_once() == "processed"
    second = await db.sheets_history_backfill_plans.find_one({"_id": other})
    assert second["modification_scan"]["phase"] == "verify"
    assert await worker.process_once() == "processed"
    assert await worker.process_once() == "processed"
    second = await db.sheets_history_backfill_plans.find_one({"_id": other})
    assert second["modification_watermark"] == NOW


@pytest.mark.asyncio
async def test_worker_rejects_empty_or_unscoped_sellers(
    runtime: tuple[Any, FormulaRecoveryQueue, ModificationScanStore],
) -> None:
    _, _, store = runtime
    for sellers in (frozenset(), frozenset({"abc"})):
        with pytest.raises(ValueError, match="seller"):
            ModificationScanWorker(
                store, Gateway([]), sellers=sellers, now=lambda: datetime.now(UTC)
            )
