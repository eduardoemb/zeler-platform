"""Seeded publish prerequisites test the primitive, not producer handoff."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import pytest
import pytest_asyncio
from infra.mongo.apply_validators import apply_validators
from motor.motor_asyncio import AsyncIOMotorClient

from zeler_platform_core.devoluciones_readiness import (
    DevolucionesLeaseLostError,
    acquire_devoluciones_operation,
    finish_devoluciones_operation,
)
from zeler_platform_core.models import SheetsHistoryAcquisition, SheetsHistoryReceipt
from zeler_sheets.event_persistence import SheetsEventPersistence
from zeler_sheets.formulas.read_models import read_model_reconciliation_marker_covers
from zeler_sheets.formulas.recovery import FormulaRecoveryQueue, RecoveryRequest
from zeler_sheets.formulas.refresh import reconciled_marker
from zeler_sheets.history_acquisition import (
    HistoryAcquisitionStore,
    HistoryConflictError,
    HistoryLimitError,
)
from zeler_sheets.history_continuation import HistoryContinuation, _binding
from zeler_sheets.history_publication import HistoryOrderPublisher
from zeler_sheets.item_projection import item_source_fingerprint

NOW = datetime(2026, 9, 15, 12, tzinfo=UTC)
OBSERVED = NOW - timedelta(seconds=10)


def order(identity: int, **changes: Any) -> dict[str, Any]:
    return {
        "id": identity,
        "seller": {"id": 82453304},
        "buyer": {"id": 123},
        "status": "paid",
        "tags": ["no_shipping"],
        "total_amount": "100",
        "date_created": (NOW - timedelta(seconds=45)).isoformat(),
        "date_last_updated": (NOW - timedelta(seconds=20)).isoformat(),
        "order_items": [
            {"item": {"id": "MLA1"}, "quantity": 1, "unit_price": "100", "sale_fee": "5"}
        ],
        **changes,
    }


@pytest_asyncio.fixture
async def publisher(
    tmp_path: Path,
) -> AsyncIterator[tuple[HistoryOrderPublisher, dict[str, Any], SheetsHistoryAcquisition]]:
    name = f"zeler_history_publication_{uuid4().hex}"
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        f"mongodb://127.0.0.1:27028/{name}?directConnection=true", tz_aware=True
    )
    hello = await client.admin.command("hello")
    assert hello["isWritablePrimary"] and hello["setName"] == "rs0"
    database = client[name]
    try:
        root = Path(__file__).resolve().parents[3] / "infra/mongo"
        for directory in ("schemas", "indexes"):
            (tmp_path / directory).mkdir()
            for collection in (
                "sheets_history_acquisitions",
                "sheets_history_receipts",
                "orders",
                "sheets_read_model_freshness",
                "sheets_devoluciones_operations",
            ):
                filename = f"{collection}.json"
                source = root / directory / filename
                if source.exists():
                    (tmp_path / directory / filename).write_text(source.read_text())
        await asyncio.to_thread(
            apply_validators,
            f"mongodb://127.0.0.1:27028/{name}?directConnection=true",
            tmp_path / "schemas",
        )
        queue = FormulaRecoveryQueue(database, now=lambda: NOW)
        request = RecoveryRequest(
            "82453304", "orders", NOW - timedelta(minutes=1), NOW - timedelta(seconds=30)
        )
        await queue.enqueue(request)
        job = await queue.claim()
        assert job is not None
        head = SheetsHistoryAcquisition(
            _id="head",
            seller_id="82453304",
            read_model="orders",
            plan_id="plan",
            scope_id="orders:20260915:20260915",
            job_id=job["_id"],
            date_from=request.date_from,
            date_to=request.date_to,
            phase="publish",
            pass_number=2,
            source_total=2,
            discovered_count=2,
            fetched_count=2,
            observed_from=OBSERVED,
            observed_until=OBSERVED,
            created_at=NOW,
            updated_at=NOW,
        )
        await database.sheets_history_acquisitions.insert_one(head.model_dump(by_alias=True))
        await queue.collection.update_one({"_id": job["_id"]}, {"$set": _binding(head)})
        job.update(_binding(head))
        for identity in (1, 2):
            payload = order(identity)
            receipt_kinds: tuple[tuple[int, Literal["detail", "membership"]], ...] = (
                (1, "detail"),
                (2, "membership"),
            )
            for pass_number, kind in receipt_kinds:
                receipt = SheetsHistoryReceipt(
                    _id=f"{identity}:{kind}",
                    acquisition_id="head",
                    seller_id="82453304",
                    read_model="orders",
                    generation=1,
                    pass_number=pass_number,
                    page_sequence=1,
                    kind=kind,
                    resource_id=str(identity),
                    observed_at=OBSERVED,
                    source_payload=payload,
                    source_hash=item_source_fingerprint(payload),
                    payload=payload if kind == "detail" else None,
                    payload_hash=item_source_fingerprint(payload) if kind == "detail" else None,
                )
                await database.sheets_history_receipts.insert_one(receipt.model_dump(by_alias=True))
        await database.sheets_read_model_freshness.insert_one(
            reconciled_marker(
                seller_id="82453304",
                read_model="orders",
                start=NOW - timedelta(minutes=10),
                end=NOW,
                now=NOW,
            )
        )
        yield (
            HistoryOrderPublisher(HistoryContinuation(HistoryAcquisitionStore(database, queue))),
            job,
            head,
        )
    finally:
        await client.drop_database(name)
        client.close()


@pytest.mark.asyncio
async def test_partial_projection_withdraws_only_affected_interval(publisher: Any) -> None:
    writer, job, head = publisher
    saved = await writer.batch(job, head, limit=1)
    assert saved.phase == "publish" and saved.published_count == 1
    row = await writer.store.db.orders.find_one({"_id": "1"})
    assert row["items"][0]["sale_fee_synced_at"] == OBSERVED
    marker = await writer.store.db.sheets_read_model_freshness.find_one({"_id": "82453304:orders"})
    assert not read_model_reconciliation_marker_covers(
        marker, date_from=NOW - timedelta(minutes=2), date_to=NOW - timedelta(seconds=45), now=NOW
    )
    for start, end in (
        (NOW - timedelta(minutes=5), NOW - timedelta(minutes=2)),
        (NOW - timedelta(seconds=20), NOW),
    ):
        assert read_model_reconciliation_marker_covers(
            marker, date_from=start, date_to=end, now=NOW
        )


@pytest.mark.asyncio
async def test_newer_event_wins_between_released_batches(publisher: Any) -> None:
    writer, job, head = publisher
    saved = await writer.batch(job, head, limit=1)
    database = writer.store.db
    operation = await acquire_devoluciones_operation(
        db=database,
        seller_id="82453304",
        scope="devoluciones",
        operation_id="event",
        attempt_token=uuid4().hex,
        invalidate_readiness=False,
    )
    await SheetsEventPersistence(db=database, clock=lambda: NOW).persist(
        event_type="orders.updated",
        seller_id="82453304",
        resource=order(2, status="cancelled", date_last_updated=NOW.isoformat()),
        operation=operation,
    )
    await finish_devoluciones_operation(db=database, operation=operation, succeeded=True)
    claimed = await writer.store.queue.claim(history=True)
    saved = await writer.batch(claimed, saved, limit=1)
    row = await database.orders.find_one({"_id": "2"})
    assert row["status"] == "cancelled" and row["last_updated"] == NOW
    assert saved.phase == "publish" and saved.published_count == 2
    claimed = await writer.store.queue.claim(history=True)
    with pytest.raises(HistoryConflictError, match="finalization"):
        await writer.batch(claimed, saved)


@pytest.mark.asyncio
async def test_verified_batches_finalize_coverage_and_queue_together(publisher: Any) -> None:
    writer, job, head = publisher
    saved = await writer.batch(job, head, limit=2)
    claimed = await writer.store.queue.claim(history=True)
    assert claimed is not None

    completed = await writer.finalize(claimed, saved)

    assert completed.phase == "completed" and completed.published_count == 2
    queued = await writer.store.queue.collection.find_one({"_id": job["_id"]})
    assert queued is not None and queued["state"] == "completed"
    marker = await writer.store.db.sheets_read_model_freshness.find_one({"_id": "82453304:orders"})
    assert read_model_reconciliation_marker_covers(
        marker, date_from=head.date_from, date_to=head.date_to, now=NOW
    )


@pytest.mark.asyncio
async def test_missing_projected_order_cannot_certify_coverage(publisher: Any) -> None:
    writer, job, head = publisher
    saved = await writer.batch(job, head, limit=2)
    claimed = await writer.store.queue.claim(history=True)
    assert claimed is not None
    await writer.store.db.orders.delete_one({"_id": "2"})
    marker_before = await writer.store.db.sheets_read_model_freshness.find_one({})

    with pytest.raises(HistoryConflictError, match="inventory"):
        await writer.finalize(claimed, saved)

    assert await writer.store.db.sheets_read_model_freshness.find_one({}) == marker_before
    stored = await writer.store.heads.find_one({"_id": head.id})
    assert stored is not None and stored["phase"] == "publish"


@pytest.mark.asyncio
async def test_finalization_does_not_revive_failed_retained_proof(publisher: Any) -> None:
    writer, job, head = publisher
    saved = await writer.batch(job, head, limit=2)
    claimed = await writer.store.queue.claim(history=True)
    assert claimed is not None
    await writer.store.db.sheets_read_model_freshness.update_one(
        {"_id": "82453304:orders"}, {"$set": {"state": "failed"}}
    )

    await writer.finalize(claimed, saved)

    marker = await writer.store.db.sheets_read_model_freshness.find_one({"_id": "82453304:orders"})
    assert read_model_reconciliation_marker_covers(
        marker, date_from=head.date_from, date_to=head.date_to, now=NOW
    )
    assert not read_model_reconciliation_marker_covers(
        marker,
        date_from=NOW - timedelta(minutes=5),
        date_to=NOW - timedelta(minutes=2),
        now=NOW,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("damage", ["lease", "head", "receipt", "missing"])
async def test_invalid_prerequisite_has_no_projection(publisher: Any, damage: str) -> None:
    writer, job, head = publisher
    if damage == "lease":
        await writer.store.queue.collection.update_one(
            {"_id": job["_id"]}, {"$set": {"attempt_token": "other"}}
        )
    elif damage == "head":
        await writer.store.heads.update_one({"_id": head.id}, {"$set": {"phase": "verify"}})
    elif damage == "receipt":
        await writer.store.receipts.update_one(
            {"_id": "1:detail"}, {"$set": {"payload.status": "cancelled"}}
        )
    else:
        await writer.store.receipts.delete_one({"_id": "1:detail"})
    marker = await writer.store.db.sheets_read_model_freshness.find_one({})
    with pytest.raises(HistoryConflictError):
        await writer.batch(job, head, limit=1)
    assert await writer.store.db.orders.count_documents({}) == 0
    assert await writer.store.db.sheets_read_model_freshness.find_one({}) == marker


@pytest.mark.asyncio
async def test_lost_operation_aborts_entire_batch(
    publisher: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer, job, head = publisher
    original = SheetsEventPersistence.persist

    async def lose_operation(instance: SheetsEventPersistence, **kwargs: Any) -> None:
        await writer.store.db.sheets_devoluciones_operations.update_one(
            {"seller_id": head.seller_id},
            {"$set": {"lease_until": datetime(2000, 1, 1, tzinfo=UTC)}},
            session=kwargs["session"],
        )
        await original(instance, **kwargs)

    monkeypatch.setattr(SheetsEventPersistence, "persist", lose_operation)
    marker = await writer.store.db.sheets_read_model_freshness.find_one({})
    with pytest.raises(DevolucionesLeaseLostError):
        await writer.batch(job, head, limit=1)
    assert await writer.store.db.orders.count_documents({}) == 0
    assert await writer.store.heads.find_one({"_id": head.id}) == head.model_dump(by_alias=True)
    assert await writer.store.db.sheets_read_model_freshness.find_one({}) == marker


@pytest.mark.asyncio
async def test_interrupted_second_batch_keeps_first_checkpoint(
    publisher: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer, job, head = publisher
    saved = await writer.batch(job, head, limit=1)
    claimed = await writer.store.queue.claim(history=True)
    original = SheetsEventPersistence.persist

    async def interrupt_after_write(instance: SheetsEventPersistence, **kwargs: Any) -> None:
        await original(instance, **kwargs)
        raise RuntimeError("interrupted")

    monkeypatch.setattr(SheetsEventPersistence, "persist", interrupt_after_write)
    with pytest.raises(RuntimeError, match="interrupted"):
        await writer.batch(claimed, saved, limit=1)
    assert await writer.store.db.orders.count_documents({}) == 1
    current = await writer.store.heads.find_one({"_id": head.id})
    assert current["published_count"] == 1 and current["phase"] == "publish"
    marker = await writer.store.db.sheets_read_model_freshness.find_one({})
    assert not read_model_reconciliation_marker_covers(
        marker, date_from=head.date_from, date_to=head.date_to, now=NOW
    )


@pytest.mark.asyncio
async def test_previous_live_edge_cannot_reauthorize_withdrawn_tail(publisher: Any) -> None:
    writer, job, head = publisher
    await writer.store.db.sheets_read_model_freshness.update_one(
        {}, {"$set": {"reconciled_until": head.date_from, "fresh_until": head.date_from}}
    )
    await writer.batch(job, head, limit=1)
    marker = await writer.store.db.sheets_read_model_freshness.find_one({})
    assert not read_model_reconciliation_marker_covers(
        marker, date_from=NOW - timedelta(minutes=2), date_to=NOW - timedelta(seconds=45), now=NOW
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, 21, True])
async def test_invalid_batch_bound_is_rejected(publisher: Any, limit: int) -> None:
    writer, job, head = publisher
    with pytest.raises(HistoryLimitError):
        await writer.batch(job, head, limit=limit)
    assert await writer.store.db.orders.count_documents({}) == 0
