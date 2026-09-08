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


@pytest.mark.asyncio
@pytest.mark.parametrize("participation", [True, False, None])
async def test_catalog_participation_persists_with_mongo_validators(
    recovery_db: Any, participation: bool | None
) -> None:
    import json
    from pathlib import Path

    from zeler_sheets.event_persistence import _canonical_item_document
    from zeler_sheets.sheetseller_backfill import build_formula_row_doc

    for name in ("items", "sheets_item_formula_rows"):
        validator = json.loads(Path(f"infra/mongo/schemas/{name}.json").read_text())
        await recovery_db.create_collection(
            name, validator={"$jsonSchema": validator["$jsonSchema"]}
        )
    now = datetime.now(UTC)
    item = _canonical_item_document(
        {
            "id": "MLA1",
            "title": "Catalog participation",
            "price": 100,
            "available_quantity": 1,
            "status": "active",
            "catalog_product_id": "MLA-PRODUCT-1",
            "catalog_listing": participation,
        },
        seller_id="82453304",
        synced_at=now,
    )
    await recovery_db.items.insert_one(item)
    stored = await recovery_db.items.find_one({"_id": "MLA1"})
    assert stored["catalog_product_id"] == "MLA-PRODUCT-1"
    assert stored.get("catalog_listing") is participation
    row = build_formula_row_doc(stored, seller_id="82453304", sku="sku-1")
    await recovery_db.sheets_item_formula_rows.insert_one(row)
    persisted = await recovery_db.sheets_item_formula_rows.find_one({"_id": row["_id"]})
    assert persisted["current"]["catalog_listing"] is participation


@pytest.mark.parametrize("value", [None, "", "  "])
def test_runtime_recovery_requires_explicit_sellers(value: str | None) -> None:
    from zeler_sheets.formulas.recovery import recovery_sellers

    assert recovery_sellers(value) == frozenset()


def test_runtime_recovery_seller_list_is_explicit_and_validated() -> None:
    from zeler_sheets.formulas.recovery import recovery_sellers

    assert recovery_sellers(" 82453304, 42,82453304 ") == frozenset({"82453304", "42"})
    for value in ("*", "82453304,", "pilot", "１２３"):
        with pytest.raises(ValueError):
            recovery_sellers(value)


@pytest.mark.asyncio
async def test_catalog_source_projection_retains_variation_only_products_in_mongo(
    recovery_db: Any,
) -> None:
    from zeler_sheets.historical_meli_backfill import (
        CatalogSnapshotSource,
        _catalog_snapshot_source_rows,
    )

    await recovery_db.items.insert_many(
        [
            {
                "_id": "MLA1",
                "seller_id": "82453304",
                "catalog_product_id": None,
                "variations": [
                    {"id": 1, "catalog_product_id": "MLA10", "attributes": []},
                    {"id": 2, "catalog_product_id": "MLA10"},
                    {"id": 3, "catalog_product_id": "MLA11"},
                ],
            },
            {"_id": "MLA2", "seller_id": "82453304"},
            {"_id": "MLA3", "seller_id": "42", "catalog_product_id": "MLA12"},
        ]
    )
    rows = await _catalog_snapshot_source_rows(db=recovery_db, seller_id="82453304")
    assert set(rows) == {
        CatalogSnapshotSource("MLA1", None, ("MLA10", "MLA11")),
        CatalogSnapshotSource("MLA2", None),
    }
    assert await recovery_db.items.count_documents({}) == 3
    assert await recovery_db.sheets_catalog_product_snapshots.count_documents({}) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "rate_limit", "cancel"])
async def test_item_recovery_bounds_concurrency_and_joins_all_acquisition_tasks(
    recovery_db: Any, monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    from types import SimpleNamespace

    import httpx

    import zeler_sheets.formulas.recovery_worker as workers
    from zeler_platform_core.clients.meli_gateway_client import GatewayRateLimitError
    from zeler_sheets.formulas.recovery import IMPLEMENTED_MODELS, ItemIdsRecoveryRequest
    from zeler_sheets.sheetseller_backfill import run_sheetseller_backfill

    queue = FormulaRecoveryQueue(recovery_db, enabled_models=IMPLEMENTED_MODELS)
    ids = tuple(f"MLA{i:03d}" for i in range(20))
    key = await queue.enqueue(ItemIdsRecoveryRequest("82453304", ids))
    started = asyncio.Event()
    release = asyncio.Event()
    active = 0
    peak = 0
    batches: list[tuple[str, ...]] = []

    async def acquire(**kwargs: Any) -> Any:
        nonlocal active, peak
        batch = kwargs["acquire_item_ids"]
        batches.append(batch)
        active += 1
        peak = max(peak, active)
        if active == 4:
            started.set()
        try:
            await release.wait()
            if outcome == "rate_limit" and ids[0] in batch:
                raise GatewayRateLimitError(retry_after_seconds=5, response=httpx.Response(429))
            now = queue.now()
            await recovery_db.items.insert_many(
                [
                    {
                        "_id": identity,
                        "seller_id": "82453304",
                        "price": 100,
                        "date_created": now,
                        "last_updated": now,
                        "last_meli_sync_at": now,
                    }
                    for identity in batch
                ]
            )
            return SimpleNamespace(item_details_stale_unavailable=0, diagnostic_reason_counts={})
        finally:
            await asyncio.sleep(0)
            active -= 1

    async def project(**kwargs: Any) -> Any:
        assert active == 0
        assert outcome == "success"
        return await run_sheetseller_backfill(**kwargs)

    monkeypatch.setattr(workers, "run_item_detail_enrichment", acquire)
    monkeypatch.setattr(workers, "run_sheetseller_backfill", project)
    task = asyncio.create_task(
        workers.FormulaRecoveryWorker(db=recovery_db, gateway=object(), queue=queue).process_one()
    )
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        assert peak == 4 and sorted(len(batch) for batch in batches) == [5, 5, 5, 5]
        assert sorted(identity for batch in batches for identity in batch) == list(ids)
        if outcome == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            release.set()
            assert await asyncio.wait_for(task, timeout=5)
        assert active == 0
        job = await queue.collection.find_one({"_id": key})
        if outcome == "success":
            assert job["state"] == "completed"
            assert await recovery_db.sheets_item_formula_rows.count_documents({}) == 20
        elif outcome == "rate_limit":
            assert job["state"] == "pending"
            assert job["failure_reason"] == "source_temporarily_unavailable"
            assert await recovery_db.sheets_item_formula_rows.count_documents({}) == 0
        else:
            assert job["state"] == "running"
            assert await recovery_db.items.count_documents({}) == 0
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("projection_fault", [None, "missing_receipt", "changed_source"])
async def test_calculator_recovers_through_real_worker_and_source_bound_projection(
    recovery_db: Any,
    monkeypatch: pytest.MonkeyPatch,
    projection_fault: str | None,
) -> None:
    import json
    from pathlib import Path
    from types import SimpleNamespace

    import httpx

    import zeler_sheets.formulas.recovery_worker as workers
    from zeler_sheets.api import _request_formula_recovery
    from zeler_sheets.formulas.dispatcher import (
        FormulaDataUnavailableError,
        FormulaDispatcher,
        FormulaExecutionContext,
    )
    from zeler_sheets.formulas.handlers_quality_calculator import (
        build_quality_calculator_formula_handlers,
    )
    from zeler_sheets.formulas.read_models import FormulaReadModelRepository
    from zeler_sheets.formulas.recovery import IMPLEMENTED_MODELS
    from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker
    from zeler_sheets.formulas.registry import FormulaRegistry
    from zeler_sheets.sheetseller_backfill import run_sheetseller_backfill as real_project

    async def project_with_fault(**kwargs: Any) -> Any:
        result = await real_project(**kwargs)
        if projection_fault == "missing_receipt":
            await recovery_db.sheets_item_formula_rows.update_many(
                {"seller_id": "82453304"}, {"$unset": {"source_snapshot": ""}}
            )
        if projection_fault == "changed_source":
            await recovery_db.items.update_one({"_id": "MLA1"}, {"$set": {"price": 101}})
        return result

    monkeypatch.setattr(workers, "run_sheetseller_backfill", project_with_fault)

    for name in ("items", "sheets_item_formula_rows", "sheets_item_sku_index"):
        schema = json.loads(Path(f"infra/mongo/schemas/{name}.json").read_text())
        await recovery_db.create_collection(name, validator={"$jsonSchema": schema["$jsonSchema"]})

    class Gateway:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def fetch_resource(self, *, seller_id: str, path: str) -> Any:
            assert seller_id == "82453304"
            self.calls.append(path)
            if path == "/items?ids=MLA1":
                return [
                    {
                        "code": 200,
                        "body": {
                            "id": "MLA1",
                            "seller_id": 82453304,
                            "title": "Recovered publication",
                            "price": 100,
                            "base_price": 100,
                            "currency_id": "ARS",
                            "category_id": "MLA123",
                            "available_quantity": 2,
                            "status": "active",
                            "listing_type_id": "gold_special",
                            "date_created": "2026-09-01T00:00:00Z",
                            "last_updated": "2026-09-01T00:00:00Z",
                            "attributes": [],
                            "variations": [],
                            "shipping": {"free_shipping": False},
                        },
                    }
                ]
            # Independently unavailable fee/promotion endpoints must not hide
            # the freshly acquired title/price or become fabricated zero costs.
            response = httpx.Response(503, request=httpx.Request("GET", "https://example.invalid"))
            raise httpx.HTTPStatusError(
                "synthetic upstream unavailable", request=response.request, response=response
            )

    gateway = Gateway()
    queue = FormulaRecoveryQueue(
        recovery_db, enabled_models=IMPLEMENTED_MODELS, allowed_sellers=frozenset({"82453304"})
    )
    context = FormulaExecutionContext(
        contract=FormulaRegistry.default().find_required("ZELERDATA_CALCULADORA"),
        cuenta="test",
        seller_id="82453304",
        seller_nickname="",
        token_id="",
        request_id=None,
        args={"id_publicaciones": ["MLA1"], "encabezados": False},
    )
    dispatcher = FormulaDispatcher(
        build_quality_calculator_formula_handlers(FormulaReadModelRepository(db=recovery_db))
    )
    with pytest.raises(FormulaDataUnavailableError) as unavailable:
        await dispatcher.execute(context)
    request: Any = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(formula_recovery_queue=queue))
    )
    assert await _request_formula_recovery(request, context, unavailable.value)
    assert gateway.calls == []
    worker = FormulaRecoveryWorker(db=recovery_db, gateway=gateway, queue=queue)
    assert await worker.process_one()
    job = await queue.collection.find_one({"seller_id": "82453304"})
    if projection_fault:
        assert job["state"] == "pending"
        assert job["failure_reason"] == "source_incomplete"
        with pytest.raises(FormulaDataUnavailableError):
            await dispatcher.execute(context)
        assert await recovery_db.sheets_read_model_freshness.count_documents({}) == 0
        projection_fault = None
        retry_at = job["available_at"].replace(tzinfo=UTC)
        queue.now = lambda: retry_at
        assert await worker.process_one()
        job = await queue.collection.find_one({"seller_id": "82453304"})
        assert job["attempts"] == 2
    # Item rows are already readable, but the synthetic fee/promotion
    # endpoints still fail transiently and must retain their bounded retry.
    assert job["state"] == "pending", job.get("failure_reason")
    calls_after_recovery = list(gateway.calls)
    result = await dispatcher.execute(context)
    assert gateway.calls == calls_after_recovery
    assert len(result.values) == 1
    assert result.values[0][2] == "Recovered publication"
    assert result.values[0][4:6] == [100, 0]
    assert result.values[0][6] == "DATA_UNAVAILABLE"
    assert result.values[0][13:15] == ["DATA_UNAVAILABLE", "DATA_UNAVAILABLE"]
    assert await recovery_db.sheets_read_model_freshness.count_documents({}) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("with_variations", [False, True])
@pytest.mark.parametrize("existing_duplicate", [False, True])
async def test_recovery_does_not_duplicate_current_stock_under_historical_sku(
    recovery_db: Any, with_variations: bool, existing_duplicate: bool
) -> None:
    from zeler_sheets.formulas.read_models import FormulaReadModelRepository
    from zeler_sheets.sheetseller_backfill import build_formula_row_doc, run_sheetseller_backfill

    now = datetime(2026, 9, 8, 12, tzinfo=UTC)
    item = {
        "_id": "MLA1",
        "seller_id": "82453304",
        "price": 100,
        "available_quantity": 7,
        "date_created": now,
        "last_updated": now,
        "last_meli_sync_at": now,
        "attributes": [] if with_variations else [{"id": "SELLER_SKU", "value_name": "CURRENT"}],
        "variations": [{"id": 1, "seller_custom_field": "CURRENT", "available_quantity": 7}]
        if with_variations
        else [],
    }
    await recovery_db.items.insert_one(item)
    historical: dict[str, Any] = {
        "_id": "historical-order-identity",
        "seller_id": "82453304",
        "item_id": "MLA1",
        "sku": "OLD",
        "normalized_sku": "OLD",
        "variation_id": "1" if with_variations else None,
        "source": "order_line",
        "updated_at": now,
    }
    await recovery_db.sheets_item_sku_index.insert_one(historical)
    historical_before = await recovery_db.sheets_item_sku_index.find_one({"_id": historical["_id"]})
    if existing_duplicate:
        await recovery_db.sheets_item_formula_rows.insert_one(
            build_formula_row_doc(
                item, seller_id="82453304", sku="OLD", variation_id=historical["variation_id"]
            )
        )
    foreign = {"_id": "foreign-row", "seller_id": "42", "item_id": "MLA1"}
    await recovery_db.sheets_item_formula_rows.insert_one(foreign)
    for _ in range(2):
        await run_sheetseller_backfill(db=recovery_db, seller_id="82453304", dry_run=False)
        rows, missing = await FormulaReadModelRepository(
            db=recovery_db
        ).find_recent_item_formula_rows(
            seller_id="82453304", item_ids=["MLA1"], formula="ZELERDATA_CALCULADORA", now=now
        )
        assert missing == ()
        assert len(rows) == 1
        assert rows[0]["sku"] == "CURRENT"
        assert rows[0]["current"]["available_quantity"] == 7
        assert (
            await recovery_db.sheets_item_sku_index.find_one({"_id": historical["_id"]})
            == historical_before
        )
        assert (
            await recovery_db.sheets_item_formula_rows.find_one({"_id": "foreign-row"}) == foreign
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("existing_row", [False, True])
@pytest.mark.parametrize("history_age", [timedelta(minutes=10), timedelta(0)])
@pytest.mark.parametrize("with_variations", [False, True])
async def test_backfill_keeps_snapshot_status_over_conflicting_older_history(
    recovery_db: Any, existing_row: bool, history_age: timedelta, with_variations: bool
) -> None:
    from zeler_sheets.formulas.read_models import FormulaReadModelRepository
    from zeler_sheets.sheetseller_backfill import build_formula_row_doc, run_sheetseller_backfill

    now = datetime(2026, 9, 8, 12, tzinfo=UTC)
    item = {
        "_id": "MLA1",
        "seller_id": "82453304",
        "status": "active",
        "price": 100,
        "available_quantity": 7,
        "date_created": now - timedelta(days=1),
        "last_updated": now - timedelta(hours=1),
        "last_meli_sync_at": now,
        "attributes": [] if with_variations else [{"id": "SELLER_SKU", "value_name": "CURRENT"}],
        "variations": [{"id": 1, "seller_custom_field": "CURRENT", "available_quantity": 7}]
        if with_variations
        else [],
    }
    history = {
        "_id": "82453304:MLA1",
        "seller_id": "82453304",
        "item_id": "MLA1",
        "current_status": "paused",
        "first_observed_at": now - timedelta(days=1),
        "last_observed_at": now - history_age,
        "status_started_at": now - timedelta(days=1),
        "paused_since": now - timedelta(days=1),
        "last_status_change_at": now - timedelta(days=1),
        "schema_version": 1,
    }
    await recovery_db.items.insert_one(item)
    await recovery_db.item_status_states.insert_one(history)
    persisted_history = await recovery_db.item_status_states.find_one({"_id": history["_id"]})
    if existing_row:
        stale = {**item, "status": "paused", "status_observed_at": now - history_age}
        await recovery_db.sheets_item_formula_rows.insert_one(
            build_formula_row_doc(
                stale,
                seller_id="82453304",
                sku="CURRENT",
                variation_id="1" if with_variations else None,
            )
        )
    for _ in range(2):
        await run_sheetseller_backfill(db=recovery_db, seller_id="82453304", dry_run=False)
        rows, missing = await FormulaReadModelRepository(
            db=recovery_db
        ).find_recent_item_formula_rows(
            seller_id="82453304", item_ids=["MLA1"], formula="ZELERDATA_CALCULADORA", now=now
        )
        assert missing == ()
        assert len(rows) == 1
        assert rows[0]["current"]["status"] == "active"
        if not with_variations:
            assert rows[0]["current"]["status_observed_at"].replace(tzinfo=UTC) == now
        assert not any(
            field in rows[0]["current"]
            for field in ("paused_since", "status_started_at", "last_status_change_at")
        )
        assert (
            await recovery_db.item_status_states.find_one({"_id": history["_id"]})
            == persisted_history
        )


@pytest.mark.parametrize(
    "snapshot_status,snapshot_age", [("paused", 0), ("active", 1), ("active", None)]
)
def test_snapshot_precedence_retains_matching_or_newer_history(
    snapshot_status: str, snapshot_age: int | None
) -> None:
    from zeler_sheets.sheetseller_backfill import _status_history_for_snapshot

    observed = datetime(2026, 9, 8, 12, tzinfo=UTC)
    history = {
        "current_status": "paused",
        "last_observed_at": observed,
        "paused_since": observed - timedelta(days=1),
    }
    assert (
        _status_history_for_snapshot(
            history,
            status=snapshot_status,
            observed_at=observed - timedelta(minutes=snapshot_age)
            if snapshot_age is not None
            else None,
        )
        == history
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("with_variations", [False, True])
async def test_native_sku_event_keeps_recovered_projection_readable(
    recovery_db: Any, with_variations: bool
) -> None:
    from zeler_sheets.event_persistence import SheetsEventPersistence
    from zeler_sheets.formulas.read_models import FormulaReadModelRepository
    from zeler_sheets.sheetseller_backfill import run_sheetseller_backfill

    now = datetime(2026, 9, 7, 12, tzinfo=UTC)
    item = {
        "_id": "MLA1",
        "seller_id": "82453304",
        "title": "Recovered SKU publication",
        "price": 100,
        "available_quantity": 7,
        "currency_id": "ARS",
        "status": "active",
        "last_meli_sync_at": now,
        "last_updated": now,
        "date_created": now,
        "attributes": [{"id": "SELLER_SKU", "value_name": "PARENT"}],
        "variations": (
            [{"id": 1, "seller_custom_field": "VARIANT", "available_quantity": 7}]
            if with_variations
            else []
        ),
    }
    await recovery_db.items.insert_one(item)
    await run_sheetseller_backfill(db=recovery_db, seller_id="82453304", dry_run=False)
    reader = FormulaReadModelRepository(db=recovery_db)
    rows, missing = await reader.find_recent_item_formula_rows(
        seller_id="82453304", item_ids=["MLA1"], formula="ZELERDATA_CALCULADORA", now=now
    )
    assert len(rows) == 1 + int(with_variations)
    assert missing == ()

    later = now + timedelta(minutes=1)
    await SheetsEventPersistence(db=recovery_db, clock=lambda: later).persist(
        event_type="items.updated",
        seller_id="82453304",
        resource={
            **item,
            "id": "MLA1",
            "seller_id": 82453304,
            "price": 120,
            "date_created": now.isoformat(),
            "last_updated": later.isoformat(),
        },
    )
    rows, missing = await reader.find_recent_item_formula_rows(
        seller_id="82453304", item_ids=["MLA1"], formula="ZELERDATA_CALCULADORA", now=later
    )
    assert len(rows) == 1 + int(with_variations)
    assert missing == ()
    assert all(row["current"]["price"].to_decimal() == 120 for row in rows)
    assert await recovery_db.sheets_read_model_freshness.count_documents({}) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("parent_sku", [None, "PARENT"])
@pytest.mark.parametrize("native_event", [False, True])
@pytest.mark.parametrize("first_sku", [None, "KNOWN"])
async def test_variations_without_sku_remain_complete_and_change_identity_safely(
    recovery_db: Any, parent_sku: str | None, native_event: bool, first_sku: str | None
) -> None:
    import json
    from pathlib import Path

    from zeler_sheets.event_persistence import SheetsEventPersistence
    from zeler_sheets.formulas.dispatcher import FormulaDispatcher, FormulaExecutionContext
    from zeler_sheets.formulas.handlers_quality_calculator import (
        build_quality_calculator_formula_handlers,
    )
    from zeler_sheets.formulas.read_models import FormulaReadModelRepository
    from zeler_sheets.formulas.registry import FormulaRegistry
    from zeler_sheets.sheetseller_backfill import run_sheetseller_backfill

    schema = json.loads(Path("infra/mongo/schemas/sheets_item_formula_rows.json").read_text())
    await recovery_db.create_collection(
        "sheets_item_formula_rows", validator={"$jsonSchema": schema["$jsonSchema"]}
    )
    now = datetime(2026, 9, 7, 12, tzinfo=UTC)
    item: dict[str, Any] = {
        "_id": "MLA1",
        "seller_id": "82453304",
        "title": "Mixed SKU variants",
        "price": 100,
        "available_quantity": 20,
        "currency_id": "ARS",
        "status": "active",
        "last_meli_sync_at": now,
        "last_updated": now,
        "date_created": now,
        "attributes": [{"id": "SELLER_SKU", "value_name": parent_sku}] if parent_sku else [],
        "variations": [
            {"id": 1, "seller_custom_field": first_sku, "available_quantity": 2},
            {"id": 2, "available_quantity": 7},
            {"id": 3, "available_quantity": 11},
        ],
    }
    await recovery_db.items.insert_one(item)
    reader = FormulaReadModelRepository(db=recovery_db)
    clock = [now]
    writer = SheetsEventPersistence(db=recovery_db, clock=lambda: clock[0])
    for step, sku in enumerate((None, "ADDED", None)):
        variation = item["variations"][1]
        if sku is None:
            variation.pop("seller_custom_field", None)
        else:
            variation["seller_custom_field"] = sku
        if native_event:
            resource = {
                **item,
                "id": "MLA1",
                "seller_id": 82453304,
                "date_created": "2026-09-01T00:00:00Z",
                "last_updated": f"2026-09-07T12:0{step}:00Z",
            }
            now = datetime(2026, 9, 7, 12, step, tzinfo=UTC)
            clock[0] = now
            await writer.persist(
                event_type="items.updated", seller_id="82453304", resource=resource
            )
        else:
            await recovery_db.items.replace_one({"_id": "MLA1"}, item)
            await run_sheetseller_backfill(db=recovery_db, seller_id="82453304", dry_run=False)
        rows, missing = await reader.find_recent_item_formula_rows(
            seller_id="82453304", item_ids=["MLA1"], formula="ZELERDATA_CALCULADORA", now=now
        )
        assert missing == ()
        assert len(rows) == 3 + int(parent_sku is not None)
        by_variation = {row["variation_id"]: row for row in rows}
        assert by_variation["2"]["sku"] == sku
        assert by_variation["3"]["sku"] is None
        assert by_variation["2"]["current"]["available_quantity"] == 7
        assert by_variation["3"]["current"]["available_quantity"] == 11
        result = await FormulaDispatcher(
            build_quality_calculator_formula_handlers(reader, now_fn=lambda: clock[0])
        ).execute(
            FormulaExecutionContext(
                contract=FormulaRegistry.default().find_required("ZELERDATA_CALCULADORA"),
                cuenta="test",
                seller_id="82453304",
                seller_nickname="",
                token_id="",
                request_id=None,
                args={"id_publicaciones": ["MLA1"], "encabezados": False},
            )
        )
        assert result.meta["partial_misses"] == 0
        assert result.recovery is not None
        assert result.recovery.item_ids == ("MLA1",)
        assert result.meta["unavailable_field_items"] == ["MLA1"]
        assert any(row[1] == "NA" and row[4] == 100 for row in result.values)
        indexes = await recovery_db.sheets_item_sku_index.find({}).to_list(None)
        assert all(row["sku"] for row in indexes)
        assert {row["variation_id"] for row in indexes if row["variation_id"]} == (
            ({"1"} if first_sku else set()) | ({"2"} if sku else set())
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["missing_id", "duplicate_id", "malformed", "ambiguous_sku"])
async def test_missing_sku_support_does_not_certify_unidentified_variations(
    recovery_db: Any, invalid: str
) -> None:
    from zeler_sheets.formulas.dispatcher import FormulaDataUnavailableError
    from zeler_sheets.formulas.read_models import FormulaReadModelRepository
    from zeler_sheets.sheetseller_backfill import run_sheetseller_backfill

    broken: Any = {
        "missing_id": {},
        "duplicate_id": {"id": 1},
        "malformed": "not a variation",
        "ambiguous_sku": {
            "id": 2,
            "attributes": [
                {"id": "SELLER_SKU", "value_name": "A"},
                {"id": "SELLER_SKU", "value_name": "B"},
            ],
        },
    }[invalid]
    now = datetime(2026, 9, 7, 12, tzinfo=UTC)
    await recovery_db.items.insert_one(
        {
            "_id": "MLA1",
            "seller_id": "82453304",
            "price": 100,
            "date_created": now,
            "last_updated": now,
            "last_meli_sync_at": now,
            "variations": [{"id": 1}, broken],
        }
    )
    await run_sheetseller_backfill(db=recovery_db, seller_id="82453304", dry_run=False)
    assert (
        await recovery_db.sheets_item_formula_rows.count_documents(
            {"source_snapshot": {"$exists": True}}
        )
        == 0
    )
    with pytest.raises(FormulaDataUnavailableError):
        await FormulaReadModelRepository(db=recovery_db).find_recent_item_formula_rows(
            seller_id="82453304", item_ids=["MLA1"], formula="ZELERDATA_CALCULADORA", now=now
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_mode", ["none", "retry_last", "exhaust_first"])
async def test_inventory_recovery_resumes_bounded_batches_without_global_readiness(
    recovery_db: Any,
    failure_mode: str,
) -> None:
    from types import SimpleNamespace
    from urllib.parse import parse_qs, urlparse

    import httpx

    from zeler_sheets.api import _request_formula_recovery
    from zeler_sheets.formulas.dispatcher import FormulaDataUnavailableError
    from zeler_sheets.formulas.recovery import IMPLEMENTED_MODELS, ItemInventoryRecoveryRequest
    from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker

    identities = [f"MLA{i:03d}" for i in range(21)]
    batches: list[list[str]] = []
    scans = 0
    failed = False

    class Gateway:
        async def fetch_resource(self, *, seller_id: str, path: str) -> Any:
            nonlocal scans, failed
            assert seller_id == "82453304"
            if path.startswith("/users/82453304/items/search?"):
                scans += 1
                return {"paging": {"total": 21}, "results": identities}
            if path.startswith("/items?ids="):
                batch = parse_qs(urlparse(path).query)["ids"][0].split(",")
                batches.append(batch)
                if (failure_mode == "retry_last" and batch == identities[20:] and not failed) or (
                    failure_mode == "exhaust_first" and batch[0] in identities[:20]
                ):
                    failed = True
                    response = httpx.Response(
                        503, request=httpx.Request("GET", "https://example.invalid")
                    )
                    raise httpx.HTTPStatusError(
                        "synthetic transient request", request=response.request, response=response
                    )
                return [
                    {
                        "code": 200,
                        "body": {
                            "id": identity,
                            "seller_id": 82453304,
                            "title": "Inventory item",
                            "price": 100,
                            "base_price": 100,
                            "currency_id": "ARS",
                            "category_id": "MLA123",
                            "available_quantity": 1,
                            "status": "active",
                            "listing_type_id": "gold_special",
                            "date_created": "2026-09-01T00:00:00Z",
                            "last_updated": "2026-09-01T00:00:00Z",
                            "attributes": [],
                            "variations": [],
                            "shipping": {"free_shipping": False},
                        },
                    }
                    for identity in batch
                ]
            response = httpx.Response(503, request=httpx.Request("GET", "https://example.invalid"))
            raise httpx.HTTPStatusError(
                "synthetic unavailable cost", request=response.request, response=response
            )

    gateway = Gateway()
    queue = FormulaRecoveryQueue(
        recovery_db, enabled_models=IMPLEMENTED_MODELS, allowed_sellers=frozenset({"82453304"})
    )
    request = ItemInventoryRecoveryRequest("82453304")
    http_request: Any = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(formula_recovery_queue=queue))
    )
    context: Any = SimpleNamespace(seller_id="82453304")
    assert await _request_formula_recovery(
        http_request,
        context,
        FormulaDataUnavailableError("ZELERDATA_CALCULADORA", read_model="item_formula_rows"),
    )
    assert scans == 0 and batches == []
    assert await queue.enqueue(request) == request.key
    worker = FormulaRecoveryWorker(db=recovery_db, gateway=gateway, queue=queue)

    async def read_inventory(missing: int, *, expired: bool = False) -> None:
        from zeler_sheets.formulas.dispatcher import FormulaDispatcher, FormulaExecutionContext
        from zeler_sheets.formulas.handlers_quality_calculator import (
            build_quality_calculator_formula_handlers,
        )
        from zeler_sheets.formulas.read_models import FormulaReadModelRepository
        from zeler_sheets.formulas.registry import FormulaRegistry

        dispatcher = FormulaDispatcher(
            build_quality_calculator_formula_handlers(
                FormulaReadModelRepository(db=recovery_db), now_fn=queue.now
            )
        )
        before = (scans, len(batches))
        for formula in ("ZELERDATA_CALCULADORA", "ZELERDATA_CALIDAD"):
            result = await dispatcher.execute(
                FormulaExecutionContext(
                    contract=FormulaRegistry.default().find_required(formula),
                    cuenta="test",
                    seller_id="82453304",
                    seller_nickname="",
                    token_id="",
                    request_id=None,
                    args={"id_publicaciones": [], "encabezados": False},
                )
            )
            assert len(result.values) == 21 + int(expired)
            publication_rows = result.values[:-1] if expired else result.values
            if expired:
                assert result.values[-1][:2] == [
                    "DATA_UNAVAILABLE",
                    "inventory_enumeration_expired",
                ]
            assert {row[0] for row in publication_rows} == set(identities)
            assert (
                sum(all(cell == "DATA_UNAVAILABLE" for cell in row[1:]) for row in publication_rows)
                == missing
            )
            assert result.meta["inventory_rows_complete"] is (missing == 0 and not expired)
            assert result.meta["inventory_enumeration_current"] is not expired
            assert result.meta["partial_misses"] == missing
            if missing or expired:
                assert result.recovery is not None and result.recovery.item_ids == ()
            elif formula == "ZELERDATA_CALCULADORA":
                assert result.recovery is not None
                assert result.recovery.item_ids == tuple(identities)
                assert result.meta["unavailable_field_items"] == identities
            else:
                assert result.recovery is None
        assert (scans, len(batches)) == before

    assert await worker.process_one()
    job = await queue.collection.find_one({"_id": request.key})
    assert job["state"] == "pending" and job["inventory_offset"] == 0
    assert job["inventory_ids"] == identities
    assert scans == 1 and batches == []
    observed = job["inventory_observed_at"]
    await read_inventory(21)
    assert await worker.process_one()
    job = await queue.collection.find_one({"_id": request.key})
    if failure_mode == "exhaust_first":
        for _ in range(2):
            assert job["state"] == "pending" and job["inventory_offset"] == 0
            retry_at = job["available_at"].replace(tzinfo=UTC)

            def retry_clock(at: datetime = retry_at) -> datetime:
                return at

            queue.now = retry_clock
            assert await worker.process_one()
            job = await queue.collection.find_one({"_id": request.key})
    assert job["state"] == "pending" and job["inventory_offset"] == 20
    assert job["inventory_observed_at"] == observed
    await read_inventory(21 if failure_mode == "exhaust_first" else 1)
    restarted = FormulaRecoveryWorker(db=recovery_db, gateway=gateway, queue=queue)
    assert await restarted.process_one()
    job = await queue.collection.find_one({"_id": request.key})
    if failure_mode == "retry_last":
        assert job["state"] == "pending" and job["inventory_offset"] == 20
        retry_at = job["available_at"].replace(tzinfo=UTC)
        queue.now = lambda: retry_at
        assert await restarted.process_one()
        job = await queue.collection.find_one({"_id": request.key})
    assert job["state"] == ("failed" if failure_mode == "exhaust_first" else "completed")
    assert job["inventory_offset"] == 21
    assert job.get("inventory_unavailable_ids", []) == (
        identities[:20] if failure_mode == "exhaust_first" else []
    )
    expected_batches = [identities[offset : offset + 5] for offset in range(0, 20, 5)] * (
        3 if failure_mode == "exhaust_first" else 1
    ) + [identities[20:]] * (2 if failure_mode == "retry_last" else 1)
    assert sorted(batches) == sorted(expected_batches)
    assert scans == 1
    assert await recovery_db.sheets_item_formula_rows.count_documents(
        {"source_snapshot": {"$exists": True}}
    ) == (1 if failure_mode == "exhaust_first" else 21)
    assert await recovery_db.sheets_read_model_freshness.count_documents({}) == 0
    await recovery_db.sheets_item_formula_rows.insert_one(
        {
            "_id": "unlisted-row",
            "seller_id": "82453304",
            "item_id": "MLA999",
            "current": {"title": "Not in current inventory"},
        }
    )
    await read_inventory(20 if failure_mode == "exhaust_first" else 0)
    assert job["inventory_observed_at"] == observed
    await queue.enqueue(request)
    await read_inventory(20 if failure_mode == "exhaust_first" else 0)
    await queue.collection.update_one(
        {"_id": request.key},
        {
            "$set": {
                "inventory_observed_at": queue.now() - timedelta(minutes=16),
                "updated_at": queue.now(),
            }
        },
    )
    await read_inventory(20 if failure_mode == "exhaust_first" else 0, expired=True)
    await queue.enqueue(request)
    reopened = await queue.collection.find_one({"_id": request.key})
    assert reopened["inventory_ids"] == identities and "inventory_offset" not in reopened
    assert "inventory_unavailable_ids" not in reopened
    assert reopened["inventory_observed_at"] is not None
    assert reopened["available_at"] == job["available_at"]
    next_scan_at = job["available_at"].replace(tzinfo=UTC)
    queue.now = lambda: next_scan_at
    assert await worker.process_one()
    refreshed = await queue.collection.find_one({"_id": request.key})
    assert scans == 2 and refreshed["inventory_offset"] == 0
    assert refreshed["inventory_observed_at"].replace(tzinfo=UTC) == next_scan_at


@pytest.mark.asyncio
@pytest.mark.parametrize("duration_minutes", [0, 13, 17])
@pytest.mark.parametrize("unavailable", [False, True])
async def test_inventory_refresh_wait_does_not_restart_after_successful_sweep(
    recovery_db: Any, duration_minutes: int, unavailable: bool
) -> None:
    from zeler_sheets.formulas.read_models import FormulaReadModelRepository
    from zeler_sheets.formulas.recovery import COOLDOWN, ItemInventoryRecoveryRequest

    started = datetime(2026, 9, 8, 12, tzinfo=UTC)
    now = started
    queue = FormulaRecoveryQueue(recovery_db, now=lambda: now)
    request = ItemInventoryRecoveryRequest("82453304")
    await queue.enqueue(request)
    discovery = await queue.claim()
    assert discovery is not None
    identities = ["MLA1", "MLA2"]
    assert await queue.checkpoint_inventory(discovery, item_ids=identities, offset=0)
    for offset in (1, 2):
        batch = await queue.claim()
        assert batch is not None
        # Each batch stays within its lease, including the 17-minute sweep.
        now += timedelta(minutes=duration_minutes / 2)
        assert await queue.checkpoint_inventory(
            batch, item_ids=identities, offset=offset, unavailable=unavailable
        )
    terminal = await queue.collection.find_one({"_id": request.key})
    due = now + COOLDOWN if unavailable else max(now, started + COOLDOWN)
    assert terminal["available_at"].replace(tzinfo=UTC) == due
    assert terminal["inventory_observed_at"].replace(tzinfo=UTC) == started
    assert terminal["state"] == ("failed" if unavailable else "completed")
    # Completion does not create a recurring scan without a formula request.
    assert await queue.claim() is None
    await asyncio.gather(*(queue.enqueue(request) for _ in range(3)))
    scheduled = await queue.collection.find_one({"_id": request.key})
    assert scheduled["available_at"] == terminal["available_at"]
    assert await queue.collection.count_documents({}) == 1
    if now < due:
        assert await queue.claim() is None
    now = due
    # Scheduling must not extend the old inventory's freshness.
    reader = FormulaReadModelRepository(db=recovery_db)
    _, _, missing, current = await reader.find_recent_item_inventory(
        seller_id="82453304", formula="ZELERDATA_CALCULADORA", now=now
    )
    assert not current and missing == tuple(identities)
    next_scan = await queue.claim()
    assert next_scan is not None and "inventory_offset" not in next_scan
    assert await queue.claim() is None
    assert await recovery_db.sheets_read_model_freshness.count_documents({}) == 0


@pytest.mark.asyncio
async def test_inventory_checkpoint_cannot_advance_after_lease_loss(recovery_db: Any) -> None:
    from zeler_sheets.formulas.recovery import LEASE, ItemInventoryRecoveryRequest

    now = datetime(2026, 9, 7, 12, tzinfo=UTC)
    queue = FormulaRecoveryQueue(recovery_db, now=lambda: now)
    key = await queue.enqueue(ItemInventoryRecoveryRequest("82453304"))
    old = await queue.claim()
    now += LEASE
    current = await queue.claim()
    assert old is not None and current is not None
    assert not await queue.checkpoint_inventory(old, item_ids=["MLA1"], offset=0)
    stored = await queue.collection.find_one({"_id": key})
    assert "inventory_ids" not in stored
    assert stored["attempt_token"] == current["attempt_token"]
    assert await queue.checkpoint_inventory(current, item_ids=["MLA1"], offset=0)
    stored = await queue.collection.find_one({"_id": key})
    assert stored["state"] == "pending" and stored["attempts"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid", [None, "missing_time", "expired", "future", "duplicate", "foreign", "bad_offset"]
)
async def test_inventory_read_requires_recent_owned_enumeration(
    recovery_db: Any,
    invalid: str | None,
) -> None:
    from zeler_sheets.formulas.dispatcher import FormulaDataUnavailableError
    from zeler_sheets.formulas.read_models import FormulaReadModelRepository
    from zeler_sheets.formulas.recovery import ItemInventoryRecoveryRequest

    now = datetime(2026, 9, 7, 12, tzinfo=UTC)
    queue = FormulaRecoveryQueue(recovery_db, now=lambda: now)
    key = await queue.enqueue(ItemInventoryRecoveryRequest("82453304"))
    job = await queue.claim()
    assert job is not None
    assert await queue.checkpoint_inventory(job, item_ids=[], offset=0)
    changes: dict[str, Any] = {
        "missing_time": {"inventory_observed_at": None},
        "expired": {"inventory_observed_at": now - timedelta(minutes=16)},
        "future": {"inventory_observed_at": now + timedelta(minutes=1)},
        "duplicate": {"inventory_ids": ["MLA1", "MLA1"]},
        "foreign": {"seller_id": "42"},
        "bad_offset": {"inventory_offset": True},
    }
    if invalid:
        await queue.collection.update_one({"_id": key}, {"$set": changes[invalid]})
    reader = FormulaReadModelRepository(db=recovery_db)
    if invalid:
        with pytest.raises(FormulaDataUnavailableError):
            await reader.find_recent_item_inventory(
                seller_id="82453304", formula="ZELERDATA_CALCULADORA", now=now
            )
    else:
        assert await reader.find_recent_item_inventory(
            seller_id="82453304", formula="ZELERDATA_CALCULADORA", now=now
        ) == ([], [], (), True)


@pytest.mark.asyncio
@pytest.mark.parametrize("formula", ["ZELERDATA_CALCULADORA", "ZELERDATA_CALIDAD"])
@pytest.mark.parametrize("missing_item", [False, True])
@pytest.mark.parametrize("source_state", ["current", "expired", "changed"])
async def test_expired_inventory_preserves_verified_rows_with_visible_warning(
    recovery_db: Any, formula: str, missing_item: bool, source_state: str
) -> None:
    from zeler_sheets.formulas.dispatcher import FormulaDispatcher, FormulaExecutionContext
    from zeler_sheets.formulas.handlers_quality_calculator import (
        build_quality_calculator_formula_handlers,
    )
    from zeler_sheets.formulas.read_models import FormulaReadModelRepository
    from zeler_sheets.formulas.recovery import ItemInventoryRecoveryRequest
    from zeler_sheets.formulas.registry import FormulaRegistry
    from zeler_sheets.sheetseller_backfill import run_sheetseller_backfill

    now = datetime(2026, 9, 8, 12, tzinfo=UTC)
    queue = FormulaRecoveryQueue(recovery_db, now=lambda: now - timedelta(minutes=16))
    request = ItemInventoryRecoveryRequest("82453304")
    await queue.enqueue(request)
    job = await queue.claim()
    assert job is not None
    identities = ["MLA1", "MLA2"] if missing_item else ["MLA1"]
    assert await queue.checkpoint_inventory(job, item_ids=identities, offset=0)
    await recovery_db.items.insert_one(
        {
            "_id": "MLA1",
            "seller_id": "82453304",
            "title": "Recent publication",
            "price": 100,
            "last_updated": now,
            "last_meli_sync_at": now,
            "date_created": now,
            "variations": [],
        }
    )
    await run_sheetseller_backfill(db=recovery_db, seller_id="82453304", dry_run=False)
    if source_state != "current":
        await recovery_db.items.update_one(
            {"_id": "MLA1"},
            {
                "$set": (
                    {"last_meli_sync_at": now - timedelta(minutes=16)}
                    if source_state == "expired"
                    else {"title": "Unprojected source change"}
                )
            },
        )
    before = await queue.collection.find_one({"_id": request.key})
    result = await FormulaDispatcher(
        build_quality_calculator_formula_handlers(
            FormulaReadModelRepository(db=recovery_db), now_fn=lambda: now
        )
    ).execute(
        FormulaExecutionContext(
            contract=FormulaRegistry.default().find_required(formula),
            cuenta="test",
            seller_id="82453304",
            seller_nickname="",
            token_id="",
            request_id=None,
            args={"encabezados": False},
        )
    )
    assert result.values[0][0] == "MLA1"
    assert result.values[0][2] == (
        "Recent publication" if source_state == "current" else "DATA_UNAVAILABLE"
    )
    assert result.values[-1][:2] == ["DATA_UNAVAILABLE", "inventory_enumeration_expired"]
    assert len(result.values) == len(identities) + 1
    assert all(len(row) == len(result.values[0]) for row in result.values)
    assert result.meta["inventory_rows_complete"] is False
    assert result.meta["inventory_enumeration_current"] is False
    assert result.meta["partial_misses"] == int(missing_item) + int(source_state != "current")
    assert result.recovery is not None and result.recovery.item_ids == ()
    assert await queue.collection.find_one({"_id": request.key}) == before
    assert await recovery_db.sheets_read_model_freshness.count_documents({}) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid",
    [
        None,
        "expired",
        "future",
        "missing_row",
        "changed_source",
        "missing_receipt",
        "mixed_selection",
        "mixed_stale",
        "mixed_foreign",
        "mixed_incomplete",
    ],
)
async def test_selected_calculator_reads_complete_recent_projection_without_inventory_marker(
    recovery_db: Any, invalid: str | None
) -> None:
    import json
    from pathlib import Path

    from zeler_sheets.formulas.dispatcher import (
        FormulaDataUnavailableError,
        FormulaDispatcher,
        FormulaExecutionContext,
    )
    from zeler_sheets.formulas.handlers_quality_calculator import (
        build_quality_calculator_formula_handlers,
    )
    from zeler_sheets.formulas.read_models import FormulaReadModelRepository
    from zeler_sheets.formulas.registry import FormulaRegistry
    from zeler_sheets.sheetseller_backfill import run_sheetseller_backfill

    schema = json.loads(Path("infra/mongo/schemas/sheets_item_formula_rows.json").read_text())
    await recovery_db.create_collection(
        "sheets_item_formula_rows", validator={"$jsonSchema": schema["$jsonSchema"]}
    )
    now = datetime(2026, 9, 7, 12, tzinfo=UTC)
    observed = now - timedelta(minutes=1)
    if invalid == "expired":
        observed = now - timedelta(minutes=16)
    if invalid == "future":
        observed = now + timedelta(minutes=1)
    await recovery_db.items.insert_one(
        {
            "_id": "MLA1",
            "seller_id": "82453304",
            "title": "Fresh acquisition, old modification",
            "price": 100,
            "base_price": 100,
            "currency_id": "ARS",
            "category_id": "MLA123",
            "status": "active",
            "available_quantity": 2,
            "last_updated": now - timedelta(days=40),
            "date_created": now - timedelta(days=50),
            "last_meli_sync_at": observed,
            "attributes": [],
            "variations": [
                {"id": 1, "seller_custom_field": "SKU-1"},
                {"id": 2, "seller_custom_field": "SKU-2"},
            ],
        }
    )
    await run_sheetseller_backfill(
        db=recovery_db, seller_id="82453304", item_ids=("MLA1",), dry_run=False
    )
    scope = {"seller_id": "82453304", "item_id": "MLA1"}
    if invalid == "missing_row":
        await recovery_db.sheets_item_formula_rows.delete_one(scope)
    if invalid == "changed_source":
        await recovery_db.items.update_one({"_id": "MLA1"}, {"$set": {"price": 200}})
    if invalid == "missing_receipt":
        await recovery_db.sheets_item_formula_rows.update_many(
            scope, {"$unset": {"source_snapshot": ""}}
        )
    if invalid in {"mixed_stale", "mixed_foreign", "mixed_incomplete"}:
        second = await recovery_db.items.find_one({"_id": "MLA1"})
        second["_id"] = "MLA2"
        if invalid == "mixed_stale":
            second["last_meli_sync_at"] = now - timedelta(minutes=16)
        if invalid == "mixed_foreign":
            second["seller_id"] = "42"
        await recovery_db.items.insert_one(second)
        await run_sheetseller_backfill(
            db=recovery_db, seller_id=second["seller_id"], item_ids=("MLA2",), dry_run=False
        )
        if invalid == "mixed_incomplete":
            await recovery_db.sheets_item_formula_rows.delete_one(
                {"seller_id": "82453304", "item_id": "MLA2"}
            )
    handlers = build_quality_calculator_formula_handlers(
        FormulaReadModelRepository(db=recovery_db), now_fn=lambda: now
    )
    context = FormulaExecutionContext(
        contract=FormulaRegistry.default().find_required("ZELERDATA_CALCULADORA"),
        cuenta="test",
        seller_id="82453304",
        seller_nickname="",
        token_id="",
        request_id=None,
        args={"id_publicaciones": ["MLA1"], "encabezados": False},
    )
    if invalid and invalid.startswith("mixed_"):
        context = FormulaExecutionContext(
            contract=context.contract,
            cuenta=context.cuenta,
            seller_id=context.seller_id,
            seller_nickname="",
            token_id="",
            request_id=None,
            args={"id_publicaciones": ["MLA2", "MLA1"], "encabezados": False},
        )
        result = await FormulaDispatcher(handlers).execute(context)
        assert len(result.values) == 3
        assert result.values[0] == ["MLA2", *["DATA_UNAVAILABLE"] * 14]
        assert [row[4] for row in result.values[1:]] == [100, 100]
        assert result.meta["partial_misses"] == 1
        assert result.meta["unavailable_items"] == ["MLA2"]
        assert result.meta["unavailable_reason"] == "missing_incomplete_or_stale_projection"
        assert result.recovery is not None
        assert result.recovery.item_ids == ("MLA1", "MLA2")
        assert result.meta["unavailable_field_items"] == ["MLA1"]
    elif invalid:
        with pytest.raises(FormulaDataUnavailableError) as error:
            await FormulaDispatcher(handlers).execute(context)
        assert error.value.item_ids == ("MLA1",)
    else:
        result = await FormulaDispatcher(handlers).execute(context)
        assert len(result.values) == 2
        assert result.values[0][5] == "DATA_UNAVAILABLE"
    assert await recovery_db.sheets_read_model_freshness.count_documents({}) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("partial", [False, True])
@pytest.mark.parametrize("lose_lease", [False, True])
@pytest.mark.parametrize("transient_enrichment", [False, True])
async def test_explicit_item_recovery_uses_bounded_acquisition_without_global_marker(
    recovery_db: Any,
    monkeypatch: pytest.MonkeyPatch,
    partial: bool,
    lose_lease: bool,
    transient_enrichment: bool,
) -> None:
    from types import SimpleNamespace

    import zeler_sheets.formulas.recovery_worker as workers
    from zeler_sheets.api import _request_formula_recovery
    from zeler_sheets.formulas.dispatcher import FormulaDataUnavailableError
    from zeler_sheets.formulas.recovery import IMPLEMENTED_MODELS, ItemIdsRecoveryRequest
    from zeler_sheets.sheetseller_backfill import run_sheetseller_backfill

    queue = FormulaRecoveryQueue(recovery_db, enabled_models=IMPLEMENTED_MODELS)
    request = ItemIdsRecoveryRequest("82453304", ("MLA2", "MLA1", "MLA1"))
    http_request: Any = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(formula_recovery_queue=queue))
    )
    context: Any = SimpleNamespace(seller_id="82453304")
    missing = FormulaDataUnavailableError(
        "ZELERDATA_CALCULADORA", read_model="item_formula_rows", item_ids=request.item_ids
    )
    assert await _request_formula_recovery(http_request, context, missing)
    key = request.key
    assert key == await queue.enqueue(ItemIdsRecoveryRequest("82453304", ("MLA1", "MLA2")))
    calls = []
    gateway = object()

    async def acquire(**kwargs: Any) -> Any:
        assert kwargs["gateway"] is gateway
        assert kwargs["acquire_item_ids"] == ("MLA1", "MLA2")
        assert kwargs["sale_price_enabled"] and kwargs["listing_fixed_fee_enabled"]
        assert not kwargs["dry_run"]
        calls.append("acquire")
        for identity in ("MLA1",) if partial else ("MLA1", "MLA2"):
            await recovery_db.items.replace_one(
                {"_id": identity},
                {
                    "_id": identity,
                    "seller_id": "82453304",
                    "title": "Acquired item",
                    "price": 100,
                    "status": "active",
                    "currency_id": "ARS",
                    "last_meli_sync_at": queue.now(),
                    "attributes": [],
                    "variations": [],
                },
                upsert=True,
            )
        if lose_lease:
            await queue.collection.update_one(
                {"_id": key}, {"$set": {"lease_until": datetime(2000, 1, 1, tzinfo=UTC)}}
            )
        return SimpleNamespace(
            item_details_stale_unavailable=int(partial),
            diagnostic_reason_counts={"listing_price_fixed_fee:transient:rate_limited": 1}
            if transient_enrichment and calls.count("acquire") == 1
            else {},
        )

    async def project(**kwargs: Any) -> Any:
        assert kwargs["item_ids"] == (("MLA1",) if partial else ("MLA1", "MLA2"))
        assert not kwargs["dry_run"]
        calls.append("project")
        await run_sheetseller_backfill(**kwargs)

    monkeypatch.setattr(workers, "run_item_detail_enrichment", acquire)
    monkeypatch.setattr(workers, "run_sheetseller_backfill", project)
    worker = workers.FormulaRecoveryWorker(
        db=recovery_db, gateway=object(), detail_gateway=gateway, queue=queue
    )
    assert await worker.process_one()
    assert calls == (["acquire"] if lose_lease else ["acquire", "project"])
    assert (await queue.collection.find_one({"_id": key}))["state"] == (
        "running" if lose_lease else "pending" if partial or transient_enrichment else "completed"
    )
    if transient_enrichment and not partial and not lose_lease:
        pending = await queue.collection.find_one({"_id": key})
        assert pending["available_at"] > pending["updated_at"]
        retry_at = pending["available_at"].replace(tzinfo=UTC)
        queue.now = lambda: retry_at
        assert await worker.process_one()
        assert (await queue.collection.find_one({"_id": key}))["state"] == "completed"
        assert calls == ["acquire", "project", "acquire", "project"]
    assert await recovery_db.sheets_read_model_freshness.count_documents({}) == 0
    with pytest.raises(ValueError):
        ItemIdsRecoveryRequest("82453304", tuple(f"MLA{i}" for i in range(21)))
    with pytest.raises(ValueError):
        ItemIdsRecoveryRequest("82453304", ("../items",))
    with pytest.raises(ValueError, match="explicit IDs"):
        await queue.enqueue(
            RecoveryRequest(
                "82453304",
                "item_formula_rows",
                datetime(2026, 9, 1, tzinfo=UTC),
                datetime(2026, 9, 2, tzinfo=UTC),
            )
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("cost_gap", [True, False])
async def test_http_cost_gap_queues_only_affected_item_and_recovers_without_inventory(
    recovery_db: Any,
    cost_gap: bool,
) -> None:
    import httpx

    from zeler_sheets.app import build_app
    from zeler_sheets.extension_tokens import ExtensionTokenService, SellerScope
    from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker
    from zeler_sheets.sheetseller_backfill import (
        run_item_detail_enrichment,
        run_sheetseller_backfill,
    )

    seller = "82453304"
    await recovery_db.meli_accounts.insert_one(
        {"_id": "test", "seller_id": seller, "site_id": "MLA"}
    )
    calls = []

    class Gateway:
        unavailable = True

        async def fetch_resource(self, *, seller_id: str, path: str) -> Any:
            assert seller_id == seller
            calls.append(path)
            if path == "/items?ids=MLA1":
                return [
                    {
                        "code": 200,
                        "body": {
                            "id": "MLA1",
                            "seller_id": seller,
                            "title": "Synthetic item",
                            "catalog_product_id": "MLA-PRODUCT-1",
                            "catalog_listing": None if self.unavailable else False,
                            "price": 100,
                            "base_price": 100,
                            "currency_id": "ARS",
                            "site_id": "MLA",
                            "category_id": "MLA123",
                            "listing_type_id": "gold_special",
                            "available_quantity": 1,
                            "status": "active",
                            "attributes": [],
                            "variations": [],
                            "shipping": {
                                "mode": "me2",
                                "logistic_type": "fulfillment",
                                "free_shipping": False,
                            },
                            "date_created": "2026-09-01T00:00:00Z",
                            "last_updated": "2026-09-07T00:00:00Z",
                        },
                    }
                ]
            if "/sale_price" in path:
                return {"amount": 100, "regular_amount": 100, "currency_id": "ARS"}
            assert path.startswith("/sites/MLA/listing_prices?")
            if self.unavailable and cost_gap:
                from zeler_platform_core.clients.meli_gateway_client import GatewayRateLimitError

                raise GatewayRateLimitError(retry_after_seconds=5, response=httpx.Response(429))
            return {
                "sale_fee_amount": 10,
                "currency_id": "ARS",
                "sale_fee_details": {"percentage_fee": 10, "fixed_fee": 2},
            }

    gateway = Gateway()
    await run_item_detail_enrichment(
        db=recovery_db,
        gateway=gateway,
        seller_id=seller,
        acquire_item_ids=["MLA1"],
        dry_run=False,
        sale_price_enabled=True,
        listing_fixed_fee_enabled=True,
    )
    await run_sheetseller_backfill(
        db=recovery_db, seller_id=seller, item_ids=["MLA1"], dry_run=False
    )
    calls.clear()
    app = build_app(
        mongo_db=recovery_db,
        formula_recovery_enabled=True,
        formula_recovery_sellers=frozenset({seller}),
    )
    app.state.extension_token_pepper = uuid4().hex
    token = await ExtensionTokenService(
        db=recovery_db, token_pepper=app.state.extension_token_pepper
    ).create_token(
        owner_user_id="test-user",
        label="Cost recovery",
        seller_scopes=[SellerScope(seller_id=seller, nickname="PILOT")],
    )
    queue = app.state.formula_recovery_queue
    await queue.ensure_indexes()
    payload = {
        "formula": "ZELERDATA_CALCULADORA",
        "cuenta": "PILOT",
        "args": {"id_publicaciones": ["MLA1"], "encabezados": False},
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        headers = {"Authorization": f"Bearer {token.token_once}"}
        missing = await client.post("/sheets/formulas:execute", headers=headers, json=payload)
        assert missing.status_code == 200
        body = missing.json()
        assert body["ok"] is True
        assert body["values"][0][4] == 100
        assert body["values"][0][6] == ("DATA_UNAVAILABLE" if cost_gap else 10)
        assert body["values"][0][10] == "DATA_UNAVAILABLE"
        assert body["meta"]["recovery_requested"] is True
        assert calls == []
        job = await queue.collection.find_one({"seller_id": seller})
        assert job["item_ids"] == ["MLA1"] and not job.get("inventory_scope")
        gateway.unavailable = False
        assert await FormulaRecoveryWorker(
            db=recovery_db, gateway=gateway, queue=queue
        ).process_one()
        acquired_calls = list(calls)
        ready = await client.post("/sheets/formulas:execute", headers=headers, json=payload)
        assert ready.status_code == 200
        assert ready.json()["values"][0][5:9] == [0, 10, 10, 2]
        assert ready.json()["values"][0][13:] == [12, 88]
        assert ready.json()["values"][0][10] == "REGULAR"
        assert not ready.json()["meta"].get("recovery_requested", False)
        assert calls == acquired_calls
    assert await recovery_db.sheets_read_model_freshness.count_documents({}) == 0


@pytest.mark.asyncio
async def test_no_sku_event_reconciliation_is_bounded_under_source_contention(
    recovery_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import zeler_sheets.event_persistence as events
    from zeler_sheets.sheetseller_backfill import run_sheetseller_backfill

    calls = 0

    async def change_source_after_projection(**kwargs: Any) -> Any:
        nonlocal calls
        result = await run_sheetseller_backfill(**kwargs)
        calls += 1
        await recovery_db.items.update_one(
            {"_id": "MLA1", "seller_id": "82453304"},
            {"$set": {"title": f"Concurrent source {calls}"}},
        )
        return result

    monkeypatch.setattr(events, "run_sheetseller_backfill", change_source_after_projection)
    writer = events.SheetsEventPersistence(
        db=recovery_db, clock=lambda: datetime(2026, 9, 7, 12, tzinfo=UTC)
    )
    with pytest.raises(RuntimeError, match="bounded reconciliation"):
        await writer.persist(
            event_type="items.updated",
            seller_id="82453304",
            resource={
                "id": "MLA1",
                "seller_id": 82453304,
                "title": "Initial source",
                "price": 100,
                "currency_id": "ARS",
                "category_id": "MLA123",
                "available_quantity": 2,
                "status": "active",
                "date_created": "2026-09-01T00:00:00Z",
                "last_updated": "2026-09-07T00:00:00Z",
                "attributes": [],
                "variations": [],
            },
        )
    assert calls == 3
    assert (await recovery_db.items.find_one({"_id": "MLA1"}))["title"] == ("Concurrent source 3")


@pytest.mark.asyncio
@pytest.mark.parametrize("sku_level", ["item", "variation"])
@pytest.mark.parametrize("reverse", [False, True])
async def test_older_item_event_finishing_last_preserves_newer_identity(
    recovery_db: Any, monkeypatch: pytest.MonkeyPatch, sku_level: str, reverse: bool
) -> None:
    import zeler_sheets.sheetseller_backfill as backfill
    from zeler_sheets.event_persistence import SheetsEventPersistence

    paused = asyncio.Event()
    release = asyncio.Event()
    original = backfill._replace_formula_row_from_backfill_if_current

    async def pause_old_write(collection: Any, doc: dict[str, Any], **kwargs: Any) -> bool:
        if doc["normalized_sku"] == "" and doc["current"]["title"] == "Older event":
            paused.set()
            await asyncio.wait_for(release.wait(), timeout=10)
        return await original(collection, doc, **kwargs)

    monkeypatch.setattr(backfill, "_replace_formula_row_from_backfill_if_current", pause_old_write)
    native_original = SheetsEventPersistence._replace_formula_row_if_observation_current

    async def pause_native_write(self: Any, doc: dict[str, Any], **kwargs: Any) -> None:
        if reverse and doc["current"]["title"] == "Older event":
            paused.set()
            await asyncio.wait_for(release.wait(), timeout=10)
        await native_original(self, doc, **kwargs)

    monkeypatch.setattr(
        SheetsEventPersistence, "_replace_formula_row_if_observation_current", pause_native_write
    )
    old = {
        "id": "MLA1",
        "seller_id": 82453304,
        "title": "Older event",
        "price": 100,
        "base_price": 100,
        "currency_id": "ARS",
        "category_id": "MLA123",
        "available_quantity": 2,
        "status": "active",
        "date_created": "2026-09-01T00:00:00Z",
        "last_updated": "2026-09-07T00:00:00Z",
        "attributes": [],
        "variations": [],
    }
    newer = {
        **old,
        "title": "Newer event",
        "last_updated": "2026-09-07T00:01:00Z",
        "attributes": [{"id": "SELLER_SKU", "value_name": "SKU-1"}] if sku_level == "item" else [],
        "variations": [{"id": 101, "seller_custom_field": "SKU-1"}]
        if sku_level == "variation"
        else [],
    }
    if reverse:
        for field in ("attributes", "variations"):
            old[field], newer[field] = newer[field], old[field]
    old_writer = SheetsEventPersistence(
        db=recovery_db, clock=lambda: datetime(2026, 9, 7, 12, tzinfo=UTC)
    )
    new_writer = SheetsEventPersistence(
        db=recovery_db, clock=lambda: datetime(2026, 9, 7, 12, 1, tzinfo=UTC)
    )
    pending = asyncio.create_task(
        old_writer.persist(event_type="items.updated", seller_id="82453304", resource=old)
    )
    try:
        await asyncio.wait_for(paused.wait(), timeout=10)
        await new_writer.persist(event_type="items.updated", seller_id="82453304", resource=newer)
        release.set()
        await asyncio.wait_for(pending, timeout=10)
    finally:
        release.set()
        if not pending.done():
            pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
    source = await recovery_db.items.find_one({"_id": "MLA1"})
    assert source["title"] == "Newer event"
    rows = await recovery_db.sheets_item_formula_rows.find(
        {"seller_id": "82453304", "item_id": "MLA1"}
    ).to_list(length=10)
    assert len(rows) == 1
    assert rows[0]["sku"] == (None if reverse else "SKU-1")
    assert rows[0]["current"]["title"] == "Newer event"
    assert await recovery_db.sheets_item_sku_index.count_documents(
        {"seller_id": "82453304", "item_id": "MLA1"}
    ) == int(not reverse)


@pytest.mark.asyncio
@pytest.mark.parametrize("retry_failure", [False, True])
@pytest.mark.parametrize("sku_level", ["item", "variation"])
async def test_item_events_project_no_sku_and_identity_transitions_without_enrichment(
    recovery_db: Any,
    monkeypatch: pytest.MonkeyPatch,
    retry_failure: bool,
    sku_level: str,
) -> None:
    import zeler_sheets.sheetseller_backfill as backfill
    from zeler_sheets.event_persistence import SheetsEventPersistence
    from zeler_sheets.formulas.read_models import FormulaReadModelRepository

    clock = [datetime(2026, 9, 7, 12, tzinfo=UTC)]
    writer = SheetsEventPersistence(db=recovery_db, clock=lambda: clock[0])
    repository = FormulaReadModelRepository(db=recovery_db)
    original = backfill._replace_formula_row_from_backfill_if_current
    resources = []
    for step, sku in enumerate((None, "SKU-1", None)):
        clock[0] += timedelta(minutes=1)
        resource = {
            "id": "MLA1",
            "seller_id": 82453304,
            "title": f"Synthetic event {step}",
            "price": 100,
            "base_price": 100,
            "currency_id": "ARS",
            "category_id": "MLA123",
            "available_quantity": 2,
            "status": "paused" if sku else "active",
            "date_created": "2026-09-01T00:00:00Z",
            "last_updated": f"2026-09-07T00:0{step}:00Z",
            "attributes": [{"id": "SELLER_SKU", "value_name": sku}]
            if sku and sku_level == "item"
            else [],
            "variations": [{"id": 101, "seller_custom_field": sku}]
            if sku and sku_level == "variation"
            else [],
        }
        resources.append(resource)
        if retry_failure and step == 1:

            async def fail_after_write(*args: Any, **kwargs: Any) -> bool:
                await original(*args, **kwargs)
                raise RuntimeError("synthetic event projection failure")

            with monkeypatch.context() as patch:
                patch.setattr(
                    backfill, "_replace_formula_row_from_backfill_if_current", fail_after_write
                )
                with pytest.raises(RuntimeError):
                    await writer.persist(
                        event_type="items.updated", seller_id="82453304", resource=resource
                    )
            failed_rows = await repository.find_item_formula_rows(
                seller_id="82453304", item_ids=["MLA1"]
            )
            assert len(failed_rows) == 1 and failed_rows[0]["sku"] is None
            assert await repository.find_sku_index_rows(seller_id="82453304") == []
        await writer.persist(event_type="items.updated", seller_id="82453304", resource=resource)
        rows = await repository.find_item_formula_rows(seller_id="82453304", item_ids=["MLA1"])
        assert len(rows) == 1
        assert rows[0]["sku"] == sku
        assert rows[0]["current"]["title"] == f"Synthetic event {step}"
        assert rows[0]["current"]["status"] == resource["status"]
        assert len(await repository.find_sku_index_rows(seller_id="82453304")) == int(
            sku is not None
        )
        assert await repository.find_item_formula_rows(seller_id="other", item_ids=["MLA1"]) == []
    await writer.persist(event_type="items.updated", seller_id="82453304", resource=resources[0])
    rows = await repository.find_item_formula_rows(seller_id="82453304", item_ids=["MLA1"])
    assert len(rows) == 1 and rows[0]["current"]["title"] == "Synthetic event 2"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", [None, "write_failure", "newer_projection", "newer_status", "newer_status_reverse"]
)
@pytest.mark.parametrize("sku_level", ["item", "variation"])
async def test_item_without_sku_remains_queryable_and_later_sku_does_not_duplicate_it(
    recovery_db: Any,
    monkeypatch: pytest.MonkeyPatch,
    failure: str | None,
    sku_level: str,
) -> None:
    import json
    from pathlib import Path

    import zeler_sheets.sheetseller_backfill as backfill
    from zeler_sheets.formulas.read_models import FormulaReadModelRepository
    from zeler_sheets.sheetseller_backfill import run_sheetseller_backfill

    observed = datetime(2026, 9, 7, tzinfo=UTC)
    for collection in ("sheets_item_formula_rows", "sheets_item_sku_index"):
        schema = json.loads(Path(f"infra/mongo/schemas/{collection}.json").read_text())
        await recovery_db.create_collection(
            collection, validator={"$jsonSchema": schema["$jsonSchema"]}
        )
    await recovery_db.items.insert_one(
        {
            "_id": "MLA1",
            "seller_id": "82453304",
            "title": "Synthetic item without SKU",
            "price": 100,
            "base_price": 100,
            "currency_id": "ARS",
            "category_id": "MLA123",
            "available_quantity": 2,
            "status": "active",
            "date_created": observed,
            "last_updated": observed,
            "attributes": [],
            "variations": [],
        }
    )
    repository = FormulaReadModelRepository(db=recovery_db)
    await run_sheetseller_backfill(db=recovery_db, seller_id="82453304", dry_run=False)
    rows = await repository.find_item_formula_rows(seller_id="82453304", item_ids=["MLA1"])
    assert len(rows) == 1
    assert rows[0]["sku"] is None
    assert rows[0]["current"]["title"] == "Synthetic item without SKU"
    assert await repository.find_sku_index_rows(seller_id="82453304") == []
    assert await repository.find_item_formula_rows(seller_id="other", item_ids=["MLA1"]) == []

    if failure == "newer_projection":
        await recovery_db.sheets_item_formula_rows.update_one(
            {"_id": rows[0]["_id"]}, {"$set": {"updated_at": observed + timedelta(minutes=2)}}
        )
    if failure == "newer_status":
        await recovery_db.sheets_item_formula_rows.update_one(
            {"_id": rows[0]["_id"]},
            {
                "$set": {
                    "current.status_observed_at": observed + timedelta(minutes=2),
                    "current.status": "paused",
                }
            },
        )
    previous = await recovery_db.sheets_item_formula_rows.find_one({"_id": rows[0]["_id"]})
    if failure == "write_failure":
        original = backfill._replace_formula_row_from_backfill_if_current

        async def fail_after_write(*args: Any, **kwargs: Any) -> bool:
            await original(*args, **kwargs)
            raise RuntimeError("synthetic transition failure")

        monkeypatch.setattr(
            backfill, "_replace_formula_row_from_backfill_if_current", fail_after_write
        )

    await recovery_db.items.update_one(
        {"_id": "MLA1"},
        {
            "$set": {
                "attributes": (
                    [{"id": "SELLER_SKU", "value_name": "SKU-1"}] if sku_level == "item" else []
                ),
                "variations": (
                    [{"id": 101, "seller_custom_field": "SKU-1"}]
                    if sku_level == "variation"
                    else []
                ),
                "last_updated": observed + timedelta(minutes=1),
            }
        },
    )
    if failure and failure != "newer_status_reverse":
        with pytest.raises(RuntimeError):
            await run_sheetseller_backfill(db=recovery_db, seller_id="82453304", dry_run=False)
        assert await recovery_db.sheets_item_formula_rows.find({}).to_list(length=None) == [
            previous
        ]
        assert await repository.find_sku_index_rows(seller_id="82453304") == []
        return
    await run_sheetseller_backfill(db=recovery_db, seller_id="82453304", dry_run=False)
    rows = await repository.find_item_formula_rows(seller_id="82453304", item_ids=["MLA1"])
    assert len(rows) == 1
    assert rows[0]["sku"] == "SKU-1"
    assert len(await repository.find_sku_index_rows(seller_id="82453304", skus=["SKU-1"])) == 1
    if failure == "newer_status_reverse":
        await recovery_db.sheets_item_formula_rows.update_one(
            {"_id": rows[0]["_id"]},
            {"$set": {"current.status_observed_at": observed + timedelta(minutes=4)}},
        )
    await recovery_db.items.update_one(
        {"_id": "MLA1"},
        {
            "$set": {
                "attributes": [],
                "variations": [],
                "last_updated": observed + timedelta(minutes=3),
            }
        },
    )
    if failure == "newer_status_reverse":
        with pytest.raises(RuntimeError):
            await run_sheetseller_backfill(db=recovery_db, seller_id="82453304", dry_run=False)
        rows = await repository.find_item_formula_rows(seller_id="82453304", item_ids=["MLA1"])
        assert len(rows) == 1 and rows[0]["sku"] == "SKU-1"
        assert len(await repository.find_sku_index_rows(seller_id="82453304")) == 1
    else:
        await run_sheetseller_backfill(db=recovery_db, seller_id="82453304", dry_run=False)
        rows = await repository.find_item_formula_rows(seller_id="82453304", item_ids=["MLA1"])
        assert len(rows) == 1
        assert rows[0]["sku"] is None
        assert await repository.find_sku_index_rows(seller_id="82453304") == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", [None, "price", "status", "delete", "stale_source", "undated_source"]
)
async def test_item_enrichment_cannot_overwrite_newer_or_concurrent_state(
    recovery_db: Any, change: str | None
) -> None:
    from zeler_sheets.sheetseller_backfill import run_item_detail_enrichment

    original = {
        "_id": "MLA1",
        "seller_id": "82453304",
        "title": "Old title",
        "price": 10,
        "base_price": 10,
        "category_id": "MLA123",
        "available_quantity": 2,
        "status": "active",
        "date_created": datetime(2026, 9, 1),
        "last_updated": datetime(2026, 9, 7),
        "attributes": [],
        "variations": [],
    }
    await recovery_db.items.insert_one(original)
    expected = dict(original)

    class Gateway:
        async def fetch_resource(self, *, seller_id: str, path: str) -> Any:
            assert path == "/items?ids=MLA1"
            if change in {"price", "status"}:
                fields = {"price": 99} if change == "price" else {"status": "paused"}
                await recovery_db.items.update_one({"_id": "MLA1"}, {"$set": fields})
                expected.update(fields)
            elif change == "delete":
                await recovery_db.items.delete_one({"_id": "MLA1"})
            detail = {**original, "id": "MLA1", "title": "Source title"}
            if change == "stale_source":
                detail["last_updated"] = datetime(2026, 9, 6, tzinfo=UTC)
            elif change == "undated_source":
                detail.pop("last_updated")
            return [{"code": 200, "body": detail}]

    if change:
        with pytest.raises(RuntimeError, match="item.*(changed|older)"):
            await run_item_detail_enrichment(
                db=recovery_db, gateway=Gateway(), seller_id="82453304", dry_run=False
            )
        assert await recovery_db.items.find_one({"_id": "MLA1"}) == (
            None if change == "delete" else expected
        )
    else:
        summary = await run_item_detail_enrichment(
            db=recovery_db, gateway=Gateway(), seller_id="82453304", dry_run=False
        )
        assert summary.items_updated == 1
        assert (await recovery_db.items.find_one({"_id": "MLA1"}))["title"] == "Source title"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["existing", "discover", "acquire"])
async def test_item_enrichment_cli_uses_bootstrap_only_for_inventory(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    from google.cloud import kms_v1
    from motor import motor_asyncio

    import zeler_platform_core.auth.meli_gateway_auth as auth_module
    import zeler_platform_core.clients.meli_gateway_client as client_module
    import zeler_sheets.sheetseller_backfill as backfill

    class Client:
        def __init__(self, *_: Any) -> None:
            pass

        def __getitem__(self, _: str) -> None:
            return None

        def close(self) -> None:
            pass

    async def enrich(**kwargs: Any) -> str:
        assert kwargs["gateway"] == "sheets"
        assert kwargs["inventory_gateway"] == ("bootstrap" if mode == "discover" else None)
        assert kwargs["discover_current_items"] is (mode == "discover")
        assert kwargs["item_ids"] is None
        assert kwargs["acquire_item_ids"] == (["MLA1"] if mode == "acquire" else None)
        return "verified"

    monkeypatch.setenv("MONGO_URI", "mongodb://127.0.0.1:27028/unused_mock")
    monkeypatch.setenv("MONGO_DB", "unused_mock")
    monkeypatch.setattr(motor_asyncio, "AsyncIOMotorClient", Client)
    monkeypatch.setattr(kms_v1, "KeyManagementServiceClient", lambda: None)
    monkeypatch.setattr(auth_module, "MeliGatewayAuth", lambda module, _: module)
    monkeypatch.setattr(client_module, "MeliGatewayClient", lambda _, auth: auth)
    monkeypatch.setattr(backfill, "run_item_detail_enrichment", enrich)
    arguments = ["--seller-id", "82453304", "--source", "items-enrich"]
    if mode == "discover":
        arguments.append("--discover-current-items")
    elif mode == "acquire":
        arguments.extend(["--acquire-item-id", "MLA1"])
    result: Any = await backfill._run_cli(backfill.build_arg_parser().parse_args(arguments))
    assert result == "verified"


@pytest.mark.asyncio
async def test_item_discovery_cli_rejects_wrong_source_before_connection() -> None:
    from zeler_sheets.sheetseller_backfill import _run_cli, build_arg_parser

    args = build_arg_parser().parse_args(["--seller-id", "82453304", "--discover-current-items"])
    with pytest.raises(SystemExit, match="items-enrich"):
        await _run_cli(args)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", [None, "duplicate", "changed_total", "empty", "cursor", "budget", "identity"]
)
async def test_item_discovery_requires_complete_bounded_scan(failure: str | None) -> None:
    from zeler_sheets.sheetseller_backfill import _discover_current_item_ids

    pages = [
        {"paging": {"total": 3}, "results": [f"MLA{i}"], "scroll_id": "same-cursor"}
        for i in range(1, 4)
    ]
    if failure == "duplicate":
        pages[1]["results"] = ["MLA1"]
    elif failure == "changed_total":
        pages[1]["paging"] = {"total": 2}
    elif failure == "empty":
        pages[1]["results"] = []
    elif failure == "cursor":
        pages[0].pop("scroll_id")
    elif failure == "budget":
        pages[0]["paging"] = {"total": 10001}
    elif failure == "identity":
        pages[0]["results"] = ["../invalid"]
    paths = []

    class Gateway:
        async def fetch_resource(self, *, seller_id: str, path: str) -> Any:
            assert seller_id == "82453304"
            paths.append(path)
            return pages.pop(0)

    if failure:
        with pytest.raises(ValueError, match="item discovery"):
            await _discover_current_item_ids(Gateway(), seller_id="82453304")
    else:
        assert await _discover_current_item_ids(Gateway(), seller_id="82453304") == {
            "MLA1",
            "MLA2",
            "MLA3",
        }
        assert len(paths) == 3 and paths[1] == paths[2]
    assert len(paths) <= 3


@pytest.mark.asyncio
@pytest.mark.parametrize("acquire", [False, True])
@pytest.mark.parametrize("scenario", ["write", "dry_run", "foreign_source", "concurrent"])
async def test_item_discovery_enriches_new_items_and_preserves_unavailable_history(
    recovery_db: Any, scenario: str, acquire: bool
) -> None:
    from pymongo.errors import DuplicateKeyError

    from zeler_sheets.sheetseller_backfill import run_item_detail_enrichment

    old = {"_id": "MLA2", "seller_id": "82453304", "status": "closed"}
    await recovery_db.items.insert_one(old)
    unrelated = {"_id": "MLA3", "seller_id": "82453304", "status": "paused"}
    if acquire:
        await recovery_db.items.insert_one(unrelated)
    calls: list[str] = []

    class Gateway:
        async def fetch_resource(self, *, seller_id: str, path: str) -> Any:
            assert seller_id == "82453304"
            calls.append(path)
            assert path == "/items?ids=MLA1,MLA2"
            if scenario == "concurrent":
                await recovery_db.items.insert_one(
                    {"_id": "MLA1", "seller_id": "other", "title": "must survive"}
                )
            return [
                {"code": 404, "body": {"id": "MLA2"}},
                {
                    "code": 200,
                    "body": {
                        "id": "MLA1",
                        "seller_id": "other" if scenario == "foreign_source" else seller_id,
                        "title": "Synthetic item",
                        "price": 10,
                        "base_price": 10,
                        "category_id": "MLA123",
                        "available_quantity": 2,
                        "status": "active",
                        "attributes": [],
                        "variations": [],
                        "date_created": "2026-09-01T00:00:00Z",
                        "last_updated": "2026-09-07T00:00:00Z",
                        "raw_sentinel": "discard",
                    },
                },
            ]

    class InventoryGateway:
        async def fetch_resource(self, *, seller_id: str, path: str) -> Any:
            assert seller_id == "82453304" and path.startswith("/users/82453304/items/search?")
            calls.append(path)
            return {"paging": {"total": 1}, "results": ["MLA1"]}

    async def run() -> Any:
        return await run_item_detail_enrichment(
            db=recovery_db,
            gateway=Gateway(),
            inventory_gateway=InventoryGateway(),
            seller_id="82453304",
            discover_current_items=not acquire,
            acquire_item_ids=["MLA2", "MLA1"] if acquire else None,
            dry_run=scenario == "dry_run",
        )

    if scenario in {"foreign_source", "concurrent"}:
        with pytest.raises(DuplicateKeyError if scenario == "concurrent" else RuntimeError):
            await run()
    else:
        summary = await run()
        assert summary.item_details_stale_unavailable == 1
        assert summary.items_validated == 1
        assert summary.items_updated == (1 if scenario == "write" else 0)
    assert await recovery_db.items.find_one({"_id": "MLA2"}) == old
    new = await recovery_db.items.find_one({"_id": "MLA1"})
    if scenario == "write":
        assert new["seller_id"] == "82453304" and new["title"] == "Synthetic item"
        assert isinstance(new["last_meli_sync_at"], datetime)
        assert "raw_sentinel" not in new
    elif scenario == "concurrent":
        assert new == {"_id": "MLA1", "seller_id": "other", "title": "must survive"}
    else:
        assert new is None
    assert len(calls) == (1 if acquire else 2)
    if acquire:
        assert await recovery_db.items.find_one({"_id": "MLA3"}) == unrelated
    assert await recovery_db.sheets_read_model_freshness.count_documents({}) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "options",
    [
        {"acquire_item_ids": []},
        {"acquire_item_ids": ["MLA1"] * 2},
        {"acquire_item_ids": [f"MLA{i}" for i in range(21)]},
        {"acquire_item_ids": ["MLA１"]},
        {"acquire_item_ids": ["MLA1/other"]},
        {"acquire_item_ids": ["MLA1"], "discover_current_items": True},
        {"acquire_item_ids": ["MLA1"], "item_ids": ["MLA1"]},
        {"acquire_item_ids": ["MLA1"], "seller_id": "other"},
        {"acquire_item_ids": ["MLA1"], "batch_size": 21},
    ],
)
async def test_item_acquisition_scope_fails_before_storage_or_network(
    options: dict[str, Any],
) -> None:
    from zeler_sheets.sheetseller_backfill import run_item_detail_enrichment

    unavailable: Any = None
    with pytest.raises(ValueError, match="item acquisition"):
        await run_item_detail_enrichment(
            db=unavailable, gateway=unavailable, **({"seller_id": "82453304"} | options)
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "extra",
    [
        [],
        ["--source", "items-enrich", "--item-id", "MLA1"],
        ["--source", "items-enrich", "--discover-current-items"],
        ["--source", "items-enrich", "--acquire-item-id", "MLA1"],
    ],
)
async def test_item_acquisition_cli_rejects_invalid_scope_before_connect(extra: list[str]) -> None:
    from zeler_sheets.sheetseller_backfill import _run_cli, build_arg_parser

    args = build_arg_parser().parse_args(
        ["--seller-id", "82453304", "--acquire-item-id", "MLA1", *extra]
    )
    with pytest.raises(SystemExit, match="item acquisition"):
        await _run_cli(args)


@pytest.mark.asyncio
async def test_item_acquisition_batches_retry_without_rewriting_completed_batch(
    recovery_db: Any,
) -> None:
    from zeler_sheets.sheetseller_backfill import run_item_detail_enrichment

    fail_second = True
    calls = []

    class Gateway:
        async def fetch_resource(self, *, seller_id: str, path: str) -> Any:
            calls.append(path)
            identity = path.removeprefix("/items?ids=")
            if identity == "MLA2" and fail_second:
                raise RuntimeError("synthetic acquisition failure")
            if identity == "MLA3":
                return [{"code": 404, "body": {"id": identity}}]
            return [
                {
                    "code": 200,
                    "body": {
                        "id": identity,
                        "seller_id": seller_id,
                        "title": "Synthetic",
                        "price": 10,
                        "base_price": 10,
                        "category_id": "MLA123",
                        "available_quantity": 2,
                        "status": "active",
                        "attributes": [],
                        "variations": [],
                        "date_created": "2026-09-01T00:00:00Z",
                        "last_updated": "2026-09-07T00:00:00Z",
                    },
                }
            ]

    async def run(identity: str) -> Any:
        return await run_item_detail_enrichment(
            db=recovery_db,
            gateway=Gateway(),
            seller_id="82453304",
            acquire_item_ids=[identity],
            dry_run=False,
        )

    assert (await run("MLA1")).items_updated == 1
    first = await recovery_db.items.find_one({"_id": "MLA1"})
    with pytest.raises(RuntimeError, match="synthetic acquisition"):
        await run("MLA2")
    assert await recovery_db.items.count_documents({}) == 1
    fail_second = False
    assert (await run("MLA2")).items_updated == 1
    absent = await run("MLA3")
    assert absent.items_updated == 0 and absent.item_details_stale_unavailable == 1
    assert await recovery_db.items.count_documents({}) == 2
    assert await recovery_db.items.find_one({"_id": "MLA1"}) == first
    assert calls == ["/items?ids=MLA1", "/items?ids=MLA2", "/items?ids=MLA2", "/items?ids=MLA3"]
    assert await recovery_db.sheets_read_model_freshness.count_documents({}) == 0


@pytest.mark.asyncio
async def test_recovery_pilot_scope_limits_admission_claim_and_expiry(recovery_db: Any) -> None:
    now = datetime.now(UTC)
    unrestricted = FormulaRecoveryQueue(recovery_db, now=lambda: now)
    requests = {
        seller: RecoveryRequest(seller, "orders", now - timedelta(days=1), now)
        for seller in ("pilot", "other", "expired")
    }
    for request in requests.values():
        await unrestricted.enqueue(request)
    await unrestricted.collection.update_one(
        {"_id": requests["expired"].key},
        {"$set": {"state": "running", "attempts": 3, "lease_until": now}},
    )
    before = await unrestricted.collection.find_one({"_id": requests["expired"].key})
    queue = FormulaRecoveryQueue(recovery_db, now=lambda: now, allowed_sellers=frozenset({"pilot"}))
    with pytest.raises(ValueError, match="seller"):
        await queue.enqueue(requests["other"])
    assert await queue.enqueue(requests["pilot"]) == requests["pilot"].key
    claimed = await queue.claim()
    assert claimed is not None and claimed["seller_id"] == "pilot"
    assert await queue.claim() is None
    assert await unrestricted.collection.find_one({"_id": requests["expired"].key}) == before
    disabled = FormulaRecoveryQueue(recovery_db, allowed_sellers=frozenset())
    assert await disabled.claim() is None
    with pytest.raises(ValueError, match="seller"):
        await disabled.enqueue(requests["pilot"])


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "concurrent", "foreign", "naive", "precision"])
async def test_shipment_date_repair_is_exact_scoped_and_atomic(
    recovery_db: Any, failure: str | None
) -> None:
    from infra.operations.shipment_date_repair import repair_shipment_dates

    originals = [
        {
            "_id": identity,
            "seller_id": "pilot",
            "date_created": "2026-09-01T01:00:00.123-06:00",
            "last_updated": "2026-09-02T07:00:00+00:00",
        }
        for identity in ("1", "2")
    ]
    await recovery_db.shipments.insert_many([{**row, "status": "delivered"} for row in originals])
    if failure == "concurrent":
        await recovery_db.shipments.update_one(
            {"_id": "2"}, {"$set": {"last_updated": "2026-09-03T00:00:00Z"}}
        )
    elif failure == "foreign":
        originals[1]["seller_id"] = "other"
    elif failure == "naive":
        originals[1]["date_created"] = "2026-09-01T01:00:00"
    elif failure == "precision":
        originals[1]["date_created"] = "2026-09-01T01:00:00.123456Z"
    before = await recovery_db.shipments.find({}).sort("_id").to_list(None)
    if failure:
        with pytest.raises((ValueError, RuntimeError)):
            await repair_shipment_dates(recovery_db, seller_id="pilot", originals=originals)
        assert await recovery_db.shipments.find({}).sort("_id").to_list(None) == before
    else:
        assert await repair_shipment_dates(recovery_db, seller_id="pilot", originals=originals) == 2
        rows = await recovery_db.shipments.find({}).sort("_id").to_list(None)
        for prior, row in zip(before, rows, strict=True):
            assert row == {
                **prior,
                "date_created": datetime(2026, 9, 1, 7, 0, 0, 123000),
                "last_updated": datetime(2026, 9, 2, 7),
            }


@pytest.mark.asyncio
@pytest.mark.parametrize("flagged", [False, True])
async def test_shipment_event_retains_recovered_fields_without_refreshing_them(
    recovery_db: Any, flagged: bool
) -> None:
    from zeler_sheets.event_persistence import SheetsEventPersistence
    from zeler_sheets.formulas.dispatcher import FormulaDataUnavailableError
    from zeler_sheets.formulas.read_models import FormulaReadModelRepository

    observed = datetime.now(UTC) - timedelta(hours=2)
    original = {
        "_id": "3001",
        "seller_id": "pilot",
        "order_id": "42",
        "status": "shipped",
        "last_updated": observed,
        "receiver_address": {"name": "Synthetic Receiver"},
        "real_shipping_cost": {"seller_cost": 12.5, "synced_at": observed},
        "formula_observed_at": observed,
        "unavailable_fields": ["real_shipping_cost"] if flagged else [],
        "legacy_raw": "must not survive normalization",
    }
    await recovery_db.shipments.insert_one(original)
    prior = await recovery_db.shipments.find_one({"_id": "3001"})
    writer = SheetsEventPersistence(db=recovery_db)
    await writer.persist(
        event_type="shipments.updated",
        seller_id="pilot",
        resource={
            "id": "3001",
            "order_id": "42",
            "status": "delivered",
            "logistic_type": "fulfillment",
            "date_created": observed,
            "last_updated": observed + timedelta(hours=1),
        },
    )
    stored = await recovery_db.shipments.find_one({"_id": "3001"})
    assert stored["status"] == "delivered"
    for field in (
        "receiver_address",
        "real_shipping_cost",
        "formula_observed_at",
        "unavailable_fields",
    ):
        assert stored[field] == prior[field]
    assert "legacy_raw" not in stored
    repository = FormulaReadModelRepository(db=recovery_db)
    for read in (
        repository.find_shipment_receiver_addresses,
        repository.find_shipment_real_shipping_costs,
    ):
        with pytest.raises(FormulaDataUnavailableError):
            await read(seller_id="pilot", shipment_ids=["3001"])


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["receiver_address", "real_shipping_cost"])
@pytest.mark.parametrize("state", ["ready", "missing", "expired", "flagged", "future", "malformed"])
async def test_shipment_fields_require_available_current_seller_data(
    recovery_db: Any, field: str, state: str
) -> None:
    from zeler_sheets.formulas.dispatcher import FormulaDataUnavailableError
    from zeler_sheets.formulas.read_models import FormulaReadModelRepository

    observed = datetime.now(UTC) + (
        timedelta(minutes=-16)
        if state == "expired"
        else timedelta(minutes=1)
        if state == "future"
        else timedelta(0)
    )
    if state != "missing":
        await recovery_db.shipments.insert_one(
            {
                "_id": "3001",
                "seller_id": "pilot",
                "formula_observed_at": observed,
                "receiver_address": {"name": "Synthetic Receiver"},
                "real_shipping_cost": {"seller_cost": 12.5, "synced_at": observed},
                "unavailable_fields": [field] if state == "flagged" else [],
            }
        )
    repository = FormulaReadModelRepository(db=recovery_db)
    if state == "malformed":
        await recovery_db.shipments.update_one({"_id": "3001"}, {"$set": {field: "invalid"}})
    method = (
        repository.find_shipment_receiver_addresses
        if field == "receiver_address"
        else repository.find_shipment_real_shipping_costs
    )
    if state == "ready":
        assert "3001" in await method(seller_id="pilot", shipment_ids=["3001"])
        with pytest.raises(FormulaDataUnavailableError):
            await method(seller_id="other", shipment_ids=["3001"])
    else:
        with pytest.raises(FormulaDataUnavailableError) as missing:
            await method(seller_id="pilot", shipment_ids=["3001"])
        assert missing.value.read_model == "shipments"
        assert missing.value.shipment_ids == ("3001",)
        if state == "flagged":
            other = (
                repository.find_shipment_real_shipping_costs
                if field == "receiver_address"
                else repository.find_shipment_receiver_addresses
            )
            assert "3001" in await other(seller_id="pilot", shipment_ids=["3001"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        None,
        "foreign",
        "wrong_id",
        "partial",
        "lease_lost",
        "invalid_second",
        "foreign_cost",
        "existing_foreign",
        "newer_snapshot",
        "cost_error",
        "hidden_address",
        "cached_fields",
    ],
)
async def test_shipment_id_recovery_publishes_owned_detail_and_costs_atomically(
    recovery_db: Any, failure: str | None
) -> None:
    import json
    from pathlib import Path

    import httpx
    from bson.decimal128 import Decimal128

    from zeler_sheets.formulas.recovery import ShipmentIdsRecoveryRequest
    from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker

    schema = json.loads(Path("infra/mongo/schemas/shipments.json").read_text())
    await recovery_db.create_collection(
        "shipments", validator={"$jsonSchema": schema["$jsonSchema"]}
    )
    clock = [datetime.now(UTC)]
    queue = FormulaRecoveryQueue(recovery_db, now=lambda: clock[0])
    requested = ShipmentIdsRecoveryRequest("pilot", ("3001", "3002"))
    await queue.enqueue(requested)
    prior = None
    if failure in {"existing_foreign", "newer_snapshot", "cached_fields"}:
        await recovery_db.shipments.insert_one(
            {
                "_id": "3002",
                "seller_id": "foreign" if failure == "existing_foreign" else "pilot",
                "order_id": "42",
                "status": "delivered",
                "logistic_type": "fulfillment",
                "date_created": datetime(2026, 8, 20, 10, tzinfo=UTC),
                "last_updated": datetime(
                    2026, 8, 20 if failure == "cached_fields" else 21, tzinfo=UTC
                ),
                "schema_version": 1,
            }
        )
        if failure == "cached_fields":
            await recovery_db.shipments.update_one(
                {"_id": "3002"},
                {
                    "$set": {
                        "receiver_address": {"name": "Previous Receiver"},
                        "real_shipping_cost": {
                            "source": "/shipments/{shipment_id}/costs",
                            "seller_cost": Decimal128("99"),
                            "synced_at": datetime(2026, 8, 20, tzinfo=UTC),
                        },
                    }
                },
            )
        prior = await recovery_db.shipments.find_one({"_id": "3002"})
    calls: list[str] = []

    class Gateway:
        async def request(self, **kwargs: Any) -> httpx.Response:
            path = kwargs["path"]
            calls.append(path)
            identity = path.split("/")[2]
            second = identity == "3002"
            if path.endswith("/orders"):
                assert kwargs["headers"] == {"X-New-Domain": "true"}
                return httpx.Response(
                    200,
                    json=[
                        {
                            "order_id": "42",
                            "seller_id": "foreign" if second and failure == "foreign" else "pilot",
                        }
                    ],
                )
            assert kwargs["headers"] == {"x-format-new": "true"}
            if path.endswith("/costs"):
                if second and failure in {"cost_error", "cached_fields"}:
                    raise httpx.HTTPStatusError(
                        "UPSTREAM_MUST_NOT_PERSIST",
                        request=httpx.Request("GET", "https://example.test"),
                        response=httpx.Response(503),
                    )
                if second and failure == "lease_lost":
                    await queue.collection.update_one(
                        {"_id": requested.key}, {"$set": {"attempt_token": "superseded"}}
                    )
                return httpx.Response(
                    200,
                    json={
                        "senders": [
                            {
                                "user_id": "foreign"
                                if second and failure == "foreign_cost"
                                else "pilot",
                                "cost": 12.5,
                            }
                        ]
                    },
                )
            return httpx.Response(
                206 if second and failure == "partial" else 200,
                json={
                    "id": "9999" if second and failure == "wrong_id" else identity,
                    "status": "ready_to_ship",
                    "logistic": {
                        "type": "invalid"
                        if second and failure == "invalid_second"
                        else "fulfillment"
                    },
                    "date_created": "2026-08-20T10:00:00Z",
                    "last_updated": "2026-08-20T11:00:00Z",
                    "destination": {}
                    if second and failure in {"hidden_address", "cached_fields"}
                    else {
                        "receiver_name": "Synthetic Receiver",
                        "receiver_phone": "PHONE_MUST_NOT_PERSIST",
                        "shipping_address": {"street_name": "Synthetic Street"},
                    },
                },
            )

    await FormulaRecoveryWorker(db=recovery_db, gateway=Gateway(), queue=queue).process_one()
    job = await queue.collection.find_one({"_id": requested.key})
    partial_fields = failure in {"foreign_cost", "cost_error", "hidden_address", "cached_fields"}
    if failure and not partial_fields:
        assert job["state"] != "completed"
        assert await recovery_db.shipments.count_documents({}) == (1 if prior else 0)
        if prior:
            assert await recovery_db.shipments.find_one({"_id": "3002"}) == prior
    else:
        expected_state = "pending" if failure in {"cost_error", "cached_fields"} else "completed"
        assert job["state"] == expected_state, job.get("failure_reason")
        stored = await recovery_db.shipments.find({}).to_list(None)
        assert len(stored) == 2
        assert all(row["seller_id"] == "pilot" and row["order_id"] == "42" for row in stored)
        assert all(isinstance(row["formula_observed_at"], datetime) for row in stored)
        first, second_row = sorted(stored, key=lambda row: row["_id"])
        assert first["real_shipping_cost"]["seller_cost"] == Decimal128("12.5")
        assert first["receiver_address"]["name"] == "Synthetic Receiver"
        expected_missing = []
        if failure in {"foreign_cost", "cost_error", "cached_fields"}:
            expected_missing.append("real_shipping_cost")
        else:
            assert second_row["real_shipping_cost"]["seller_cost"] == Decimal128("12.5")
        if failure in {"hidden_address", "cached_fields"}:
            expected_missing.append("receiver_address")
        else:
            assert second_row["receiver_address"]["name"] == "Synthetic Receiver"
        assert second_row.get("unavailable_fields", []) == sorted(expected_missing)
        if failure == "cached_fields":
            assert prior is not None
            for field in expected_missing:
                assert second_row[field] == prior[field]
        elif failure in {"foreign_cost", "cost_error"}:
            assert "real_shipping_cost" not in second_row
        elif failure == "hidden_address":
            assert "receiver_address" not in second_row
        assert "MUST_NOT_PERSIST" not in repr(stored)
        assert len(calls) == 6
    # An explicit ID set is not evidence of complete shipment history.
    assert await recovery_db.sheets_read_model_freshness.count_documents({}) == 0
    if failure in {"cost_error", "cached_fields"}:
        # A transient field failure retries without another formula request.
        assert await queue.claim() is None
        clock[0] += timedelta(minutes=1)
        failure = None
        await FormulaRecoveryWorker(db=recovery_db, gateway=Gateway(), queue=queue).process_one()
        retried = await queue.collection.find_one({"_id": requested.key})
        assert retried["state"] == "completed"
        recovered = await recovery_db.shipments.find_one({"_id": "3002"})
        assert not recovered.get("unavailable_fields")
        assert recovered["real_shipping_cost"]["seller_cost"] == Decimal128("12.5")
        assert recovered["receiver_address"]["name"] == "Synthetic Receiver"


@pytest.mark.asyncio
@pytest.mark.parametrize("transaction", ["none", "commit", "abort", "inactive"])
async def test_current_shipment_projection_joins_recovery_transaction(
    recovery_db: Any, transaction: str
) -> None:
    import json
    from pathlib import Path

    from zeler_sheets.event_persistence import SheetsEventPersistence

    schema = json.loads(Path("infra/mongo/schemas/shipments.json").read_text())
    await recovery_db.create_collection(
        "shipments", validator={"$jsonSchema": schema["$jsonSchema"]}
    )
    resource = {
        "id": 3001,
        # Supplied by the caller's verified order/shipment relationship, not
        # expected in the current /shipments detail response.
        "order_id": 42,
        "status": "ready_to_ship",
        "logistic": {"type": "fulfillment", "direction": "forward", "mode": "me2"},
        "date_created": "2026-08-20T10:00:00Z",
        "last_updated": "2026-08-20T11:00:00Z",
        "destination": {
            "receiver_name": "Synthetic Receiver",
            "receiver_phone": "PHONE_MUST_NOT_PERSIST",
            "shipping_address": {
                "street_name": "Synthetic Street",
                "street_number": 12,
                "city": {"name": "Synthetic City"},
                "latitude": "GEO_MUST_NOT_PERSIST",
            },
        },
    }
    writer = SheetsEventPersistence(db=recovery_db)

    async def write(session: Any = None) -> None:
        await writer.persist(
            event_type="shipments.updated", seller_id="pilot", resource=resource, session=session
        )

    if transaction == "none":
        await write()
    else:
        async with await recovery_db.client.start_session() as session:
            if transaction == "inactive":
                with pytest.raises(ValueError, match="active transaction"):
                    await write(session)
                assert await recovery_db.shipments.count_documents({}) == 0
                return
            session.start_transaction()
            await write(session)
            assert await recovery_db.shipments.count_documents({}) == 0
            if transaction == "commit":
                await session.commit_transaction()
            else:
                await session.abort_transaction()
    stored = await recovery_db.shipments.find_one({"_id": "3001"})
    if transaction == "abort":
        assert stored is None
        return
    assert stored["logistic_type"] == "fulfillment"
    assert stored["receiver_address"] == {
        "name": "Synthetic Receiver",
        "street_name": "Synthetic Street",
        "street_number": "12",
        "city": "Synthetic City",
    }
    assert "destination" not in stored and "logistic" not in stored
    assert "MUST_NOT_PERSIST" not in repr(stored)


@pytest.mark.asyncio
@pytest.mark.parametrize("partial", [False, True])
async def test_order_detail_recovers_purchase_shipment_from_hosted_relationship(
    partial: bool,
) -> None:
    from unittest.mock import Mock

    import httpx

    from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker

    resource = {
        "id": 42,
        "seller": {"id": "pilot"},
        "date_created": "2026-08-20T10:00:00Z",
        "order_items": [{"item": {"id": "MLM42"}, "quantity": 1, "unit_price": 30}],
        "shipping": {},
    }
    calls: list[str] = []

    class Gateway:
        async def request(self, **kwargs: Any) -> httpx.Response:
            calls.append(kwargs["path"])
            assert kwargs["seller_id"] == "pilot"
            if kwargs["path"] == "/orders/42":
                return httpx.Response(
                    206 if partial else 200,
                    headers={"X-Content-Missing": "shipping,feedback"} if partial else {},
                    json=resource,
                )
            assert kwargs["path"] == "/orders/42/shipments?hosted=true"
            assert kwargs["headers"] == {"X-New-Domain": "true"}
            return httpx.Response(
                200, json=[{"id": 999, "type": "return"}, {"id": 456, "type": "forward"}]
            )

    worker = FormulaRecoveryWorker(db=None, queue=Mock(), gateway=Gateway())
    detail, missing = await worker._order_detail(
        "pilot", "42", request().date_from, request().date_to
    )
    assert calls == ["/orders/42", "/orders/42/shipments?hosted=true"]
    assert detail["shipping"] == {"id": "456"}
    assert missing == (frozenset({"feedback"}) if partial else frozenset())
    assert resource["shipping"] == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,relations",
    [
        (204, None),
        (503, {}),
        (206, [{"id": 456, "type": "forward"}]),
        (200, []),
        (200, {"id": 456, "type": "forward"}),
        (200, [{"id": 999, "type": "return"}]),
        (200, [{"id": 456, "type": "forward"}, {"id": 789, "type": "forward"}]),
        (200, [{"id": 456, "type": "forward", "seller_id": "foreign"}]),
        (200, [{"id": 456, "type": "forward", "order_id": 999}]),
        (200, [{"id": True, "type": "forward"}]),
    ],
)
async def test_unresolved_forward_relationship_keeps_order_data_unavailable(
    status: int, relations: Any
) -> None:
    from unittest.mock import Mock

    import httpx

    from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker

    resource = {"id": 42, "total_amount": 30}

    class Gateway:
        async def request(self, **kwargs: Any) -> httpx.Response:
            return httpx.Response(status, json=relations)

    detail, missing = await FormulaRecoveryWorker(
        db=None, queue=Mock(), gateway=Gateway()
    )._recover_order_shipment("pilot", "42", resource, frozenset({"feedback"}))
    assert detail == resource
    assert missing == frozenset({"shipping", "feedback"})


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_field", ["buyer", "shipping"])
@pytest.mark.parametrize("recover_shipping", [False, True])
async def test_missing_identity_keeps_sales_but_rejects_consumers_that_require_it(
    recovery_db: Any,
    missing_field: str,
    recover_shipping: bool,
) -> None:
    import json
    from pathlib import Path

    import httpx
    from pymongo.errors import WriteError

    from zeler_sheets.formulas.dispatcher import (
        FormulaDataUnavailableError,
        FormulaExecutionContext,
    )
    from zeler_sheets.formulas.handlers_orders_questions import OrderQuestionFormulaHandlers
    from zeler_sheets.formulas.read_models import FormulaReadModelRepository
    from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker
    from zeler_sheets.formulas.registry import FormulaRegistry

    schema = json.loads(Path("infra/mongo/schemas/orders.json").read_text())
    await recovery_db.create_collection("orders", validator={"$jsonSchema": schema["$jsonSchema"]})
    requested = RecoveryRequest(
        seller_id="pilot",
        read_model="orders",
        date_from=request().date_from,
        date_to=request().date_to,
    )
    queue = FormulaRecoveryQueue(recovery_db, enabled_models=frozenset({"orders"}))
    await queue.enqueue(requested)
    resource = {
        "id": 42,
        "seller": {"id": "pilot"},
        "buyer": {} if missing_field == "buyer" else {"id": 123},
        "status": "paid",
        "date_created": "2026-08-20T10:00:00Z",
        "last_updated": "2026-08-20T11:00:00Z",
        "total_amount": 30,
        "order_items": [
            {"item": {"id": "MLM42", "seller_sku": "sku-42"}, "quantity": 1, "unit_price": 30}
        ],
    }
    calls: list[str] = []

    class Gateway:
        async def fetch_resource(self, **kwargs: Any) -> dict[str, Any]:
            calls.append(kwargs["path"])
            return {"paging": {"total": 1}, "results": [resource]}

        async def request(self, **kwargs: Any) -> httpx.Response:
            calls.append(kwargs["path"])
            if kwargs["path"].endswith("/shipments?hosted=true"):
                if recover_shipping:
                    return httpx.Response(200, json=[{"id": 456, "type": "forward"}])
                return httpx.Response(204)
            return httpx.Response(206, headers={"X-Content-Missing": missing_field}, json=resource)

    await FormulaRecoveryWorker(db=recovery_db, gateway=Gateway(), queue=queue).process_one()
    job = await queue.collection.find_one({"_id": requested.key})
    assert job["state"] == "completed", job.get("failure_reason")
    stored = await recovery_db.orders.find_one({"_id": "42"})
    if recover_shipping and missing_field == "shipping":
        assert stored["shipment_id"] == "456"
        assert "shipment_id" not in stored.get("unavailable_fields", [])
        assert stored["total_amount"].to_decimal() == 30
        return
    identity_field = "buyer_id" if missing_field == "buyer" else "shipment_id"
    assert identity_field not in stored
    assert identity_field in stored["unavailable_fields"]
    undeclared = {key: value for key, value in stored.items() if key != "unavailable_fields"}
    for invalid in (
        ()
        if missing_field == "shipping"
        else (
            undeclared,
            {**undeclared, "unavailable_fields": ["feedback"]},
            {**stored, "buyer_id": "123"},
            {**stored, "unavailable_fields": ["buyer_id", "unexpected"]},
        )
    ):
        with pytest.raises(WriteError):
            await recovery_db.orders.insert_one({**invalid, "_id": "invalid"})
    handlers = OrderQuestionFormulaHandlers(FormulaReadModelRepository(db=recovery_db))

    def context(name: str, **args: Any) -> FormulaExecutionContext:
        return FormulaExecutionContext(
            contract=FormulaRegistry.default().find_required(name),
            cuenta="pilot",
            seller_id="pilot",
            seller_nickname="pilot",
            token_id=uuid4().hex,
            request_id=None,
            args={"fecha_inicial": "2026-08-08", "fecha_final": "2026-09-06", **args},
        )

    result = await handlers.sheetseller_ventas_totales(context("ZELERDATA_VENTASTOTALES"))
    assert result.values == [[30]]
    if missing_field == "buyer":
        with pytest.raises(FormulaDataUnavailableError) as missing:
            await handlers.sheetseller_ordenes(context("ZELERDATA_ORDENES", compradores="123"))
        assert missing.value.read_model == "orders"
    else:
        for method, name, args in (
            (handlers.sheetseller_ordenes, "ORDENES", {}),
            (handlers.sheetseller_ordenes_por_sku, "ORDENESPORSKU", {"skus": ["sku-42"]}),
            (handlers.sheetseller_compradores, "COMPRADORES", {"id_ordenes": ["42"]}),
        ):
            with pytest.raises(FormulaDataUnavailableError) as missing:
                await method(context("ZELERDATA_" + name, **args))
            assert missing.value.read_model == "orders"
            assert missing.value.date_from is not None and missing.value.date_to is not None
        # An unrelated SKU has no displayed order; it must not require this shipment.
        await handlers.sheetseller_ordenes_por_sku(
            context("ZELERDATA_ORDENESPORSKU", skus=["unrelated"], compradores="si")
        )
    assert len(calls) == 3  # Only acquisition performs the additional relationship request.
    assert calls[-1] == "/orders/42/shipments?hosted=true"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "transport", "cancel"])
async def test_order_shipment_fallback_preserves_data_but_propagates_cancellation(
    failure: str,
) -> None:
    from unittest.mock import Mock

    import httpx

    from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker

    class Gateway:
        async def request(self, **kwargs: Any) -> Any:
            if failure == "cancel":
                raise asyncio.CancelledError
            if failure == "timeout":
                raise TimeoutError
            raise httpx.ReadTimeout("must not persist upstream error")

    resource = {"id": 42, "total_amount": 30}
    worker = FormulaRecoveryWorker(db=None, queue=Mock(), gateway=Gateway())
    if failure == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await worker._recover_order_shipment("pilot", "42", resource, frozenset())
    else:
        detail, missing = await worker._recover_order_shipment("pilot", "42", resource, frozenset())
        assert detail == resource
        assert missing == frozenset({"shipping"})


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["invalid_identity", "over_budget"])
async def test_known_order_detail_acquisition_is_bounded(recovery_db: Any, case: str) -> None:
    from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker

    requested = RecoveryRequest("pilot", "orders", request().date_from, request().date_to)
    queue = FormulaRecoveryQueue(recovery_db, enabled_models=frozenset({"orders"}))
    await queue.enqueue(requested)
    identities = ["invalid"] if case == "invalid_identity" else [str(i) for i in range(10001)]
    await recovery_db.orders.insert_many(
        [
            {"_id": identity, "seller_id": "pilot", "date_created": datetime(2026, 8, 20)}
            for identity in identities
        ]
    )

    class Gateway:
        async def fetch_resource(self, **kwargs: Any) -> dict[str, Any]:
            return {"paging": {"total": 0}, "results": []}

        async def request(self, **kwargs: Any) -> Any:
            pytest.fail("invalid or over-budget identities must not trigger detail acquisition")

    await FormulaRecoveryWorker(db=recovery_db, gateway=Gateway(), queue=queue).process_one()
    job = await queue.collection.find_one({"_id": requested.key})
    assert job["state"] == "failed"
    assert job["failure_reason"] == "source_incomplete"
    assert await recovery_db.sheets_read_model_freshness.count_documents({}) == 0
    assert await recovery_db.orders.count_documents({}) == len(identities)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        None,
        "empty",
        "missing_total",
        "foreign_detail",
        "extra_mongo_row",
        "partial_response",
        "partial_recovered",
        "extra_confirmed",
        "extra_partial",
        "extra_empty_search",
        "extra_foreign",
        "extra_missing_owner",
        "extra_wrong_id",
        "extra_outside",
        "extra_404",
    ],
)
async def test_order_recovery_publishes_only_complete_owned_inventory(
    recovery_db: Any, failure: str | None
) -> None:
    import httpx

    from zeler_sheets.formulas.read_models import read_model_reconciliation_marker_covers
    from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker

    requested = RecoveryRequest(
        seller_id="pilot",
        read_model="orders",
        date_from=request().date_from,
        date_to=request().date_to,
    )
    queue = FormulaRecoveryQueue(recovery_db, enabled_models=frozenset({"orders"}))
    await queue.enqueue(requested)
    resources = [
        {
            "id": identity,
            "seller": {"id": "pilot"},
            "buyer": {"id": 123},
            "status": "paid",
            "date_created": "2026-08-20T10:00:00Z",
            "last_updated": "2026-08-20T11:00:00Z",
            "total_amount": 30,
            "order_items": [{"item": {"id": "MLM42"}, "quantity": 1, "unit_price": 30}],
        }
        for identity in (42, 43)
    ]
    if failure and failure.startswith("extra_"):
        await recovery_db.orders.insert_one(
            {"_id": "999", "seller_id": "pilot", "date_created": datetime(2026, 8, 20)}
        )
    if failure == "partial_recovered":
        from zeler_sheets.event_persistence import _canonical_order_document

        for resource in resources:
            await recovery_db.orders.insert_one(
                _canonical_order_document(
                    {
                        **resource,
                        "shipping": {"id": 456},
                        "feedback": {"sale": {"fulfilled": True}},
                    },
                    seller_id="pilot",
                    sale_fee_synced_at=datetime.now(UTC),
                )
            )
    before = await recovery_db.orders.find({}).to_list(None)
    calls: list[str] = []

    class Gateway:
        async def fetch_resource(self, *, seller_id: str, path: str) -> dict[str, Any]:
            from urllib.parse import parse_qs, urlsplit

            assert seller_id == "pilot"
            calls.append(path)
            offset = int(parse_qs(urlsplit(path).query)["offset"][0])
            if failure in {"empty", "extra_empty_search"}:
                return {"paging": {"total": 0}, "results": []}
            return {
                "paging": {} if failure == "missing_total" else {"total": 2},
                "results": resources[offset : offset + 1],
            }

        async def request(
            self, *, method: str, seller_id: str, path: str, headers: Any = None
        ) -> httpx.Response:
            assert method == "GET" and seller_id == "pilot"
            calls.append(path)
            if path.endswith("/shipments?hosted=true"):
                return httpx.Response(204)
            if path == "/orders/999" and failure != "extra_mongo_row":
                extra = {**resources[0], "id": 999, "status": "cancelled"}
                if failure == "extra_foreign":
                    extra["seller"] = {"id": "foreign"}
                elif failure == "extra_missing_owner":
                    extra["seller"] = {}
                elif failure == "extra_wrong_id":
                    extra["id"] = 998
                elif failure == "extra_outside":
                    extra["date_created"] = "2025-01-01T00:00:00Z"
                elif failure == "extra_404":
                    return httpx.Response(404, json={})
                elif failure == "extra_partial":
                    extra["buyer"] = {}
                    return httpx.Response(206, headers={"X-Content-Missing": "buyer"}, json=extra)
                return httpx.Response(200, json=extra)
            resource = resources[int(path.rsplit("/", 1)[1]) - 42]
            if failure == "foreign_detail":
                resource = {**resource, "seller": {"id": "foreign"}}
            if failure == "partial_response":
                return httpx.Response(206, headers={"X-Content-Missing": "buyer"}, json=resource)
            if failure == "partial_recovered":
                return httpx.Response(
                    206,
                    headers={"X-Content-Missing": "buyer, shipping, feedback, seller"},
                    json={
                        **resource,
                        "buyer": {},
                        "shipping": {},
                        "seller": {},
                        "feedback": {},
                        "status": "cancelled",
                        "last_updated": "2026-08-20T12:00:00Z",
                    },
                )
            return httpx.Response(200, json=resource)

    await FormulaRecoveryWorker(db=recovery_db, gateway=Gateway(), queue=queue).process_one()
    assert calls, "order source acquisition must actually run"
    job = await queue.collection.find_one({"_id": requested.key})
    marker = await recovery_db.sheets_read_model_freshness.find_one({"_id": "pilot:orders"})
    if failure not in {
        None,
        "empty",
        "partial_recovered",
        "partial_response",
        "extra_confirmed",
        "extra_partial",
        "extra_empty_search",
    }:
        assert job["state"] == "failed"
        assert await recovery_db.orders.find({}).to_list(None) == before
        assert marker is None
    else:
        assert job["state"] == "completed", job.get("failure_reason")
        assert await recovery_db.orders.count_documents({"seller_id": "pilot"}) == (
            0
            if failure == "empty"
            else 1
            if failure == "extra_empty_search"
            else 3
            if failure in {"extra_confirmed", "extra_partial"}
            else 2
        )
        assert len(calls) == (
            1
            if failure == "empty"
            else 3
            if failure == "extra_empty_search"
            else 8
            if failure in {"extra_confirmed", "extra_partial"}
            else 6
        )
        if failure in {"extra_confirmed", "extra_partial", "extra_empty_search"}:
            extra_stored = await recovery_db.orders.find_one({"_id": "999"})
            assert extra_stored["status"] == "cancelled"
            if failure == "extra_partial":
                assert extra_stored["unavailable_fields"] == ["buyer_id", "shipment_id"]
        assert read_model_reconciliation_marker_covers(
            marker, date_from=requested.date_from, date_to=requested.date_to
        )
        operation = await recovery_db.sheets_devoluciones_operations.find_one(
            {"_id": "pilot:devoluciones"}
        )
        assert operation["state"] == "succeeded"
        if failure == "partial_response":
            for stored in await recovery_db.orders.find({}).to_list(None):
                assert "buyer_id" not in stored
                assert stored["unavailable_fields"] == ["buyer_id", "shipment_id"]
        if failure == "partial_recovered":
            for stored in await recovery_db.orders.find({}).to_list(None):
                assert stored["status"] == "cancelled"
                assert stored["buyer_id"] == "123"
                assert stored["shipment_id"] == "456"
                assert stored["feedback"] == {"sale": {"fulfilled": True}}


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["commit", "abort", "expired_lease", "no_transaction"])
async def test_order_write_joins_recovery_transaction_without_losing_lease_guard(
    recovery_db: Any, outcome: str
) -> None:
    from zeler_platform_core.devoluciones_readiness import (
        DevolucionesLeaseLostError,
        acquire_devoluciones_operation,
    )
    from zeler_sheets.event_persistence import SheetsEventPersistence

    operation = await acquire_devoluciones_operation(
        db=recovery_db,
        seller_id="pilot",
        scope="devoluciones",
        operation_id=uuid4().hex,
        attempt_token=uuid4().hex,
    )
    if outcome == "expired_lease":
        await recovery_db.sheets_devoluciones_operations.update_one(
            {"_id": "pilot:devoluciones"}, {"$set": {"lease_until": datetime(2000, 1, 1)}}
        )
    writer = SheetsEventPersistence(db=recovery_db)
    resource = {
        "id": 42,
        "seller": {"id": "pilot"},
        "buyer": {"id": 123},
        "status": "paid",
        "date_created": "2026-08-20T10:00:00Z",
        "last_updated": "2026-08-20T11:00:00Z",
        "total_amount": 30,
        "order_items": [
            {"item": {"id": "MLM42", "seller_sku": "sku-42"}, "quantity": 1, "unit_price": 30}
        ],
    }

    async def write(session: Any) -> None:
        await writer.persist(
            event_type="orders.updated",
            seller_id="pilot",
            resource=resource,
            operation=operation,
            session=session,
        )
        await recovery_db.sheets_formula_recovery_jobs.insert_one(
            {"_id": "atomic-completion", "state": "completed"}, session=session
        )

    async with await recovery_db.client.start_session() as session:
        if outcome == "no_transaction":
            with pytest.raises(ValueError, match="active transaction"):
                await write(session)
        elif outcome == "commit":
            async with session.start_transaction():
                await write(session)
        else:
            error = DevolucionesLeaseLostError if outcome == "expired_lease" else RuntimeError
            with pytest.raises(error):
                async with session.start_transaction():
                    await write(session)
                    raise RuntimeError("abort the entire recovery publication")
    expected = 1 if outcome == "commit" else 0
    assert await recovery_db.orders.count_documents({}) == expected
    assert await recovery_db.sheets_item_sku_index.count_documents({}) == expected
    assert await recovery_db.sheets_formula_recovery_jobs.count_documents({}) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source_owner",
    [
        {"seller": {"id": 999}},
        {"seller_id": "999"},
        {"seller_id": "pilot", "seller": {"id": 999}},
        {"seller_id": "999", "seller": {"id": "pilot"}},
    ],
)
async def test_foreign_order_cannot_create_or_replace_seller_data(
    recovery_db: Any, source_owner: dict[str, Any]
) -> None:
    from zeler_platform_core.devoluciones_readiness import acquire_devoluciones_operation
    from zeler_sheets.event_persistence import SheetsEventPersistence

    operation = await acquire_devoluciones_operation(
        db=recovery_db,
        seller_id="pilot",
        scope="devoluciones",
        operation_id=uuid4().hex,
        attempt_token=uuid4().hex,
    )
    writer = SheetsEventPersistence(db=recovery_db)
    resource = {
        "id": 42,
        "seller_id": "pilot",
        "seller": {"id": "pilot"},
        "buyer": {"id": 123},
        "shipping": {"id": 456},
        "status": "paid",
        "date_created": "2026-08-20T10:00:00Z",
        "last_updated": "2026-08-20T11:00:00Z",
        "total_amount": 30,
        "order_items": [],
    }
    for preexisting in (False, True):
        if preexisting:
            await writer.persist(
                event_type="orders.updated",
                seller_id="pilot",
                resource=resource,
                operation=operation,
            )
        before = await recovery_db.orders.find({}).to_list(None)
        with pytest.raises(ValueError, match="order seller scope mismatch"):
            await writer.persist(
                event_type="orders.updated",
                seller_id="pilot",
                operation=operation,
                resource={
                    **{
                        key: value
                        for key, value in resource.items()
                        if key not in {"seller_id", "seller"}
                    },
                    **source_owner,
                    "status": "cancelled",
                    "last_updated": "2026-08-20T12:00:00Z",
                },
            )
        assert await recovery_db.orders.find({}).to_list(None) == before


@pytest.mark.asyncio
async def test_order_partial_update_uses_same_seller_state_in_real_transaction(
    recovery_db: Any,
) -> None:
    from zeler_platform_core.devoluciones_readiness import acquire_devoluciones_operation
    from zeler_sheets.event_persistence import SheetsEventPersistence

    operation = await acquire_devoluciones_operation(
        db=recovery_db,
        seller_id="pilot",
        scope="devoluciones",
        operation_id=uuid4().hex,
        attempt_token=uuid4().hex,
    )
    writer = SheetsEventPersistence(db=recovery_db)
    resource = {
        "id": 42,
        "seller_id": "pilot",
        "buyer": {"id": 123},
        "shipping": {"id": 456},
        "status": "paid",
        "date_created": "2026-08-20T10:00:00Z",
        "last_updated": "2026-08-20T11:00:00Z",
        "total_amount": 30,
        "order_items": [],
    }
    await writer.persist(
        event_type="orders.updated", seller_id="pilot", resource=resource, operation=operation
    )
    await writer.persist(
        event_type="orders.updated",
        seller_id="pilot",
        operation=operation,
        resource={
            **resource,
            "buyer": {},
            "shipping": {},
            "status": "cancelled",
            "last_updated": "2026-08-20T12:00:00Z",
        },
    )
    stored = await recovery_db.orders.find_one({"_id": "42", "seller_id": "pilot"})
    assert (stored["status"], stored["buyer_id"], stored["shipment_id"]) == (
        "cancelled",
        "123",
        "456",
    )


@pytest.mark.asyncio
async def test_app_wires_only_implemented_recovery_sources(recovery_db: Any) -> None:
    from zeler_sheets.app import build_app

    app = build_app(
        mongo_db=recovery_db,
        formula_recovery_enabled=True,
        formula_recovery_sellers=frozenset({"pilot"}),
    )
    queue = app.state.formula_recovery_queue
    await queue.enqueue(request())
    with pytest.raises(ValueError, match="seller"):
        await queue.enqueue(
            RecoveryRequest("other", "orders", request().date_from, request().date_to)
        )
    unsupported = RecoveryRequest(
        seller_id="pilot",
        read_model="shipments",
        date_from=request().date_from,
        date_to=request().date_to,
    )
    with pytest.raises(ValueError):
        await queue.enqueue(unsupported)
    assert await queue.collection.count_documents({}) == 1
    disabled = build_app(mongo_db=recovery_db)
    assert not hasattr(disabled.state, "formula_recovery_queue")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("read_model", "partial"),
    [
        ("questions", False),
        ("orders", False),
        ("orders", True),
        ("order_ids", False),
        ("order_ids", True),
        ("shipments", False),
        ("shipments", True),
    ],
)
async def test_http_missing_data_recovers_in_background_and_next_http_succeeds(
    recovery_db: Any,
    read_model: str,
    partial: bool,
) -> None:
    import httpx

    from zeler_sheets.app import build_app
    from zeler_sheets.consumer import SyncJobsPollerSupervisor
    from zeler_sheets.extension_tokens import ExtensionTokenService, SellerScope
    from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker

    app = build_app(mongo_db=recovery_db, formula_recovery_enabled=True)
    app.state.extension_token_pepper = uuid4().hex
    token = await ExtensionTokenService(
        db=recovery_db,
        token_pepper=app.state.extension_token_pepper,
    ).create_token(
        owner_user_id="test-user",
        label="Local recovery integration",
        seller_scopes=[SellerScope(seller_id="123456789", nickname="PILOT")],
    )
    calls: list[str] = []
    order = {
        "id": 42,
        "seller": {"id": "123456789"},
        "buyer": {} if partial and read_model == "orders" else {"id": 123},
        "status": "paid",
        "date_created": "2026-08-20T10:00:00Z",
        "last_updated": "2026-08-20T11:00:00Z",
        "total_amount": 30,
        "order_items": [{"item": {"id": "MLM42"}, "quantity": 1, "unit_price": 30}],
        "tags": ["no_shipping"],
    }
    if read_model == "shipments":
        await recovery_db.orders.insert_one(
            {
                "_id": "42",
                "seller_id": "123456789",
                "shipment_id": "3001",
                "date_created": datetime(2026, 8, 20, tzinfo=UTC),
            }
        )

    class Gateway:
        async def fetch_resource(self, **kwargs: Any) -> dict[str, Any]:
            calls.append(kwargs["path"])
            if read_model in {"orders", "order_ids"}:
                return {"paging": {"total": 1}, "results": [order]}
            return {"total": 0, "questions": []}

        async def request(self, **kwargs: Any) -> httpx.Response:
            calls.append(kwargs["path"])
            if read_model == "shipments":
                if kwargs["path"].endswith("/orders"):
                    return httpx.Response(200, json=[{"order_id": "42", "seller_id": "123456789"}])
                if kwargs["path"].endswith("/costs"):
                    return httpx.Response(
                        503 if partial else 200,
                        json={"senders": [{"user_id": "123456789", "cost": 12.5}]},
                    )
                return httpx.Response(
                    200,
                    json={
                        "id": 3001,
                        "status": "ready_to_ship",
                        "logistic": {"type": "fulfillment"},
                        "date_created": "2026-08-20T10:00:00Z",
                        "last_updated": "2026-08-20T11:00:00Z",
                        "destination": {
                            "receiver_name": "Synthetic Receiver",
                            "shipping_address": {"street_name": "Synthetic Street"},
                        },
                    },
                )
            if partial and read_model == "order_ids":
                return httpx.Response(
                    206, headers={"X-Content-Missing": "seller"}, json={**order, "seller": {}}
                )
            if partial:
                return httpx.Response(206, headers={"X-Content-Missing": "buyer"}, json=order)
            return httpx.Response(200, json=order)

    queue = app.state.formula_recovery_queue
    await queue.ensure_indexes()
    worker = SyncJobsPollerSupervisor(
        FormulaRecoveryWorker(db=recovery_db, gateway=Gateway(), queue=queue),
        poll_interval=0.01,
    )
    payload = {
        "formula": {
            "questions": "ZELERDATA_PREGUNTAS",
            "orders": "ZELERDATA_VENTASTOTALES",
            "order_ids": "ZELERDATA_COMPRADORES",
            "shipments": "ZELERDATA_COMPRADORES",
        }[read_model],
        "cuenta": "PILOT",
        "args": {
            "fecha_inicial": "2026-08-08",
            "fecha_final": "2026-09-06",
            "horario_inicial": "00:00",
            "horario_final": "23:59",
        },
    }
    if read_model in {"order_ids", "shipments"}:
        payload["args"] = {"id_ordenes": ["42"]}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        headers = {"Authorization": f"Bearer {token.token_once}"}
        missing = await client.post("/sheets/formulas:execute", headers=headers, json=payload)
        assert missing.json()["error"]["code"] == "DATA_UNAVAILABLE"
        assert missing.json()["meta"]["recovery_requested"] is True
        assert calls == []
        await worker.start()
        try:
            async with asyncio.timeout(3):
                while not await queue.collection.find_one(
                    {
                        "state": {"$in": ["completed", "pending"]}
                        if read_model == "shipments"
                        else "completed",
                        "attempts": 1,
                    }
                ):
                    await asyncio.sleep(0.01)
            ready = await client.post("/sheets/formulas:execute", headers=headers, json=payload)
            assert ready.json()["ok"] is True, ready.json()
            assert (
                len(calls)
                == {"questions": 1, "orders": 2, "order_ids": 3, "shipments": 3}[read_model]
            )
            if read_model == "orders":
                assert ready.json()["values"] == [[30]]
            elif read_model == "order_ids":
                assert len(ready.json()["values"]) == 1
                assert await recovery_db.orders.count_documents({"_id": "42"}) == 1
            elif read_model == "shipments":
                assert ready.json()["values"][0][0] == "Synthetic Receiver"
        finally:
            await worker.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["foreign", "missing_owner", "wrong_id", "missing_search"])
async def test_id_recovery_never_publishes_unproven_requested_orders(
    recovery_db: Any, failure: str
) -> None:
    import httpx

    from zeler_sheets.formulas.recovery import OrderIdsRecoveryRequest
    from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker

    queue = FormulaRecoveryQueue(recovery_db)
    requested = OrderIdsRecoveryRequest("pilot", ("42",))
    await queue.enqueue(requested)
    detail = {
        "id": 43 if failure == "wrong_id" else 42,
        "seller": {}
        if failure == "missing_owner"
        else {"id": "foreign" if failure == "foreign" else "pilot"},
        "date_created": "2026-08-20T10:00:00Z",
    }
    calls: list[str] = []

    class Gateway:
        async def request(self, **kwargs: Any) -> httpx.Response:
            calls.append(kwargs["path"])
            return httpx.Response(200, json=detail)

        async def fetch_resource(self, **kwargs: Any) -> dict[str, Any]:
            calls.append(kwargs["path"])
            return {"paging": {"total": 0}, "results": []}

    await FormulaRecoveryWorker(db=recovery_db, gateway=Gateway(), queue=queue).process_one()
    job = await queue.collection.find_one({"_id": requested.key})
    assert job["state"] == "failed"
    assert job["failure_reason"] == "source_incomplete"
    assert await recovery_db.orders.count_documents({}) == 0
    assert await recovery_db.sheets_read_model_freshness.count_documents({}) == 0
    assert len(calls) == (2 if failure == "missing_search" else 1)


def test_id_requests_coalesce_and_reject_non_order_or_unbounded_targets() -> None:
    from zeler_sheets.formulas.recovery import OrderIdsRecoveryRequest

    request_a = OrderIdsRecoveryRequest("pilot", ("43", "42", "42"))
    assert request_a.order_ids == ("42", "43")
    assert request_a.key == OrderIdsRecoveryRequest("pilot", ("42", "43")).key
    assert request_a.key != OrderIdsRecoveryRequest("other", ("42", "43")).key
    for identities in ((), ("../42",), ("４２",), tuple(str(i) for i in range(101))):
        with pytest.raises(ValueError):
            OrderIdsRecoveryRequest("pilot", identities)
    with pytest.raises(ValueError):
        OrderIdsRecoveryRequest("pilot", ("42",), read_model="questions")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "formula",
    [
        "ORDENES",
        "VENTASTOTALES",
        "UNIDADESVENDIDAS",
        "ORDENESPORSKU",
        "PRODUCTOSINVENTA",
        "VENTAPORDIAS",
        "VENTASYSTOCK",
        "TOPVENTASUNIDADES",
        "TOPVENTASDINERO",
    ],
)
async def test_bounded_order_formulas_cannot_present_unproven_inventory_as_complete(
    recovery_db: Any,
    formula: str,
) -> None:
    from zeler_sheets.formulas.dispatcher import (
        FormulaDataUnavailableError,
        FormulaDispatcher,
        FormulaExecutionContext,
    )
    from zeler_sheets.formulas.handlers_orders_questions import (
        build_order_question_formula_handlers,
    )
    from zeler_sheets.formulas.read_models import FormulaReadModelRepository
    from zeler_sheets.formulas.registry import FormulaRegistry

    name = "ZELERDATA_" + formula
    context = FormulaExecutionContext(
        contract=FormulaRegistry.default().find_required(name),
        cuenta="pilot",
        seller_id="pilot",
        seller_nickname="pilot",
        token_id=uuid4().hex,
        request_id=None,
        args={
            "fecha_inicial": "2026-08-08",
            "fecha_final": "2026-09-06",
            "skus": ["sku-42"],
            "id_publicaciones": ["MLM42"],
            "cantidad_top": 10,
            "rango_dias": 30,
        },
    )
    dispatcher = FormulaDispatcher(
        build_order_question_formula_handlers(
            FormulaReadModelRepository(db=recovery_db),
            now_fn=lambda: datetime(2026, 9, 7, tzinfo=UTC),
        )
    )
    with pytest.raises(FormulaDataUnavailableError) as missing:
        await dispatcher.execute(context)
    assert missing.value.read_model == "orders"
    assert missing.value.date_from is not None and missing.value.date_to is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["expired_lease", "invalid_second_row", "newer_recovery"])
async def test_failed_recovery_cannot_leave_partial_writes_or_change_prior_proof(
    recovery_db: Any,
    failure: str,
) -> None:
    from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker

    clock = [datetime.now(UTC)]
    queue = FormulaRecoveryQueue(recovery_db, now=lambda: clock[0])
    await queue.enqueue(request())
    await recovery_db.sheets_read_model_freshness.insert_one(
        {"_id": "pilot:questions", "seller_id": "pilot", "state": "reconciled", "proof": "prior"}
    )
    resource = {
        "id": 42,
        "seller_id": "pilot",
        "item_id": "MLM42",
        "text": "Available?",
        "status": "UNANSWERED",
        "from": {"id": 123},
        "date_created": "2026-08-20T10:00:00Z",
    }

    class Gateway:
        async def fetch_resource(self, **kwargs: Any) -> dict[str, Any]:
            if "search?" in kwargs["path"]:
                if failure == "newer_recovery":
                    await recovery_db.sheets_read_model_freshness.update_one(
                        {"_id": "pilot:questions"},
                        {"$set": {"proof": "newer"}},
                    )
                rows = (
                    [resource, {**resource, "id": 43}]
                    if failure == "invalid_second_row"
                    else [resource]
                )
                return {"total": len(rows), "questions": rows}
            if failure == "expired_lease":
                clock[0] += timedelta(minutes=11)
            if kwargs["path"].endswith("/43"):
                return {**resource, "id": 43, "status": "INVALID"}
            return resource

    await FormulaRecoveryWorker(db=recovery_db, gateway=Gateway(), queue=queue).process_one()
    assert await recovery_db.questions.count_documents({}) == 0
    marker = await recovery_db.sheets_read_model_freshness.find_one({"_id": "pilot:questions"})
    assert marker["state"] == "reconciled"
    assert marker["proof"] == ("newer" if failure == "newer_recovery" else "prior")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("search_date", "succeeds"),
    [
        ("2026-08-20T10:00:00Z", True),
        ("2026-08-20T10:00:00.000435Z", True),
        ("2026-08-20T10:00:00.001435Z", False),
    ],
)
async def test_question_recovery_persists_data_and_unlocks_next_query(
    recovery_db: Any, search_date: str, succeeds: bool
) -> None:
    from zeler_sheets.formulas.read_models import FormulaReadModelRepository
    from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker

    now = datetime.now(UTC)
    queue = FormulaRecoveryQueue(recovery_db, now=lambda: now)
    await queue.enqueue(request())
    calls: list[str] = []
    resource = {
        "id": 42,
        "seller_id": "pilot",
        "item_id": "MLM42",
        "text": "Is it available?",
        "status": "UNANSWERED",
        "from": {"id": 123},
        "date_created": "2026-08-20T10:00:00Z",
        "answer": None,
    }

    class Gateway:
        async def fetch_resource(self, *, seller_id: str, path: str) -> dict[str, Any]:
            assert seller_id == "pilot"
            calls.append(path)
            if path.startswith("/questions/search?"):
                return {"total": 1, "questions": [{**resource, "date_created": search_date}]}
            raise AssertionError("search identity must not fetch question details")

    class Details:
        async def fetch_resource(self, *, seller_id: str, path: str) -> dict[str, Any]:
            assert seller_id == "pilot"
            calls.append(path)
            return resource

    worker = FormulaRecoveryWorker(
        db=recovery_db, gateway=Gateway(), detail_gateway=Details(), queue=queue
    )
    assert await worker.process_one()
    if not succeeds:
        job = await queue.collection.find_one({"_id": request().key})
        assert job["state"] == "failed"
        assert job["failure_reason"] == "source_incomplete"
        assert await recovery_db.questions.count_documents({}) == 0
        return
    repository = FormulaReadModelRepository(db=recovery_db)
    await repository.require_questions_read_model_productive(
        seller_id="pilot",
        date_from=request().date_from,
        date_to=request().date_to,
        formula="ZELERDATA_PREGUNTAS",
    )
    rows = await repository.find_questions(
        seller_id="pilot",
        date_from=request().date_from,
        date_to=request().date_to,
    )
    assert len(rows) == 1
    assert rows[0]["text"] == resource["text"]
    assert len(calls) == 2
    assert not await worker.process_one()


@pytest.mark.asyncio
@pytest.mark.parametrize("prior_is_later", [False, True])
async def test_question_recovery_rechecks_prior_coverage_and_the_gap(
    recovery_db: Any, prior_is_later: bool
) -> None:
    from zeler_sheets.formulas.read_models import FormulaReadModelRepository
    from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker

    prior_start = datetime(2026, 6, 1, tzinfo=UTC)
    prior_end = datetime(2026, 7, 11, tzinfo=UTC)
    earliest = prior_start
    requested = request()
    if prior_is_later:
        requested = RecoveryRequest("pilot", "questions", prior_start, prior_end)
        prior_start, prior_end = request().date_from, request().date_to
    await recovery_db.sheets_read_model_freshness.insert_one(
        {
            "_id": "pilot:questions",
            "seller_id": "pilot",
            "read_model": "questions",
            "state": "reconciled",
            "date_from": prior_start,
            "reconciled_until": prior_end,
        }
    )
    resources = [
        {
            "id": 40 + month,
            "seller_id": "pilot",
            "item_id": "MLM42",
            "text": "Available?",
            "status": "UNANSWERED",
            "from": {"id": 123},
            "date_created": f"2026-{month:02d}-20T10:00:00Z",
        }
        for month in (6, 7, 8)
    ]
    fetched: list[int] = []

    class Gateway:
        async def fetch_resource(self, *, seller_id: str, path: str) -> dict[str, Any]:
            assert seller_id == "pilot"
            if path.startswith("/questions/search?"):
                return {"total": 3, "questions": resources}
            question_id = int(path.rsplit("/", 1)[-1])
            fetched.append(question_id)
            return next(row for row in resources if row["id"] == question_id)

    queue = FormulaRecoveryQueue(recovery_db)
    await queue.enqueue(requested)
    await FormulaRecoveryWorker(db=recovery_db, queue=queue, gateway=Gateway()).process_one()
    assert fetched == [46, 47, 48]
    assert await recovery_db.questions.count_documents({"seller_id": "pilot"}) == 3
    await FormulaReadModelRepository(db=recovery_db).require_questions_read_model_productive(
        seller_id="pilot",
        date_from=earliest,
        date_to=request().date_to,
        formula="ZELERDATA_PREGUNTAS",
    )


@pytest.mark.asyncio
async def test_incomplete_remote_search_cannot_publish_coverage(recovery_db: Any) -> None:
    from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker

    queue = FormulaRecoveryQueue(recovery_db)
    await queue.enqueue(request())

    class Gateway:
        async def fetch_resource(self, **kwargs: Any) -> dict[str, Any]:
            return {"total": 12, "questions": []}

    worker = FormulaRecoveryWorker(db=recovery_db, gateway=Gateway(), queue=queue)
    assert await worker.process_one()
    marker = await recovery_db.sheets_read_model_freshness.find_one({"_id": "pilot:questions"})
    assert marker is None or marker["state"] != "reconciled"
    job = await recovery_db.sheets_formula_recovery_jobs.find_one({"_id": request().key})
    assert job["state"] == "failed"


@pytest.mark.asyncio
async def test_local_rows_absent_from_remote_inventory_do_not_become_verified(
    recovery_db: Any,
) -> None:
    from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker

    queue = FormulaRecoveryQueue(recovery_db)
    await queue.enqueue(request())
    await recovery_db.questions.insert_one(
        {"_id": "99", "seller_id": "pilot", "date_created": request().date_from}
    )

    class Gateway:
        async def fetch_resource(self, **kwargs: Any) -> dict[str, Any]:
            return {"total": 0, "questions": []}

    await FormulaRecoveryWorker(db=recovery_db, gateway=Gateway(), queue=queue).process_one()
    marker = await recovery_db.sheets_read_model_freshness.find_one({"_id": "pilot:questions"})
    assert marker is None or marker["state"] != "reconciled"


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


@pytest.mark.asyncio
async def test_scan_continues_when_server_reuses_cursor_with_new_rows(recovery_db: Any) -> None:
    from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker

    queue = FormulaRecoveryQueue(recovery_db)
    await queue.enqueue(request())

    class Gateway:
        pages = 0

        async def fetch_resource(self, **kwargs: Any) -> dict[str, Any]:
            self.pages += 1
            return {
                "total": 3,
                "scroll_id": "same-cursor",
                "questions": [{"id": self.pages, "date_created": "2026-07-01T00:00:00Z"}],
            }

    gateway = Gateway()
    await FormulaRecoveryWorker(db=recovery_db, gateway=gateway, queue=queue).process_one()
    job = await queue.collection.find_one({"_id": request().key})
    assert job["state"] == "completed"
    assert gateway.pages == 3


def request(seller_id: str = "pilot") -> RecoveryRequest:
    return RecoveryRequest(
        seller_id=seller_id,
        read_model="questions",
        date_from=datetime(2026, 8, 8, tzinfo=UTC),
        date_to=datetime(2026, 9, 7, tzinfo=UTC),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["connection", "gateway_quota"])
async def test_transient_source_failure_retries_without_another_formula(
    recovery_db: Any,
    failure: str,
) -> None:
    import httpx

    from zeler_platform_core.clients.meli_gateway_client import GatewayRateLimitError
    from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker

    clock = [datetime.now(UTC)]
    queue = FormulaRecoveryQueue(recovery_db, now=lambda: clock[0])
    await queue.enqueue(request())

    class Gateway:
        calls = 0

        async def fetch_resource(self, **kwargs: Any) -> dict[str, Any]:
            self.calls += 1
            if self.calls == 1:
                if failure == "gateway_quota":
                    raise GatewayRateLimitError(
                        retry_after_seconds=30,
                        response=httpx.Response(
                            429, request=httpx.Request("GET", "https://example.test")
                        ),
                    )
                raise httpx.ConnectError("sensitive upstream diagnostic")
            return {"total": 0, "questions": []}

    worker = FormulaRecoveryWorker(db=recovery_db, gateway=Gateway(), queue=queue)
    assert await worker.process_one()
    job = await queue.collection.find_one({"_id": request().key})
    assert job["state"] == "pending"
    assert job["failure_reason"] == "source_temporarily_unavailable"
    assert "sensitive" not in str(job)
    assert not await worker.process_one()
    clock[0] += timedelta(minutes=5)
    assert await worker.process_one()
    job = await queue.collection.find_one({"_id": request().key})
    assert job["state"] == "completed"
    assert "failure_reason" not in job


@pytest.mark.asyncio
@pytest.mark.parametrize("status, attempts", [(429, 3), (503, 3), (403, 1)])
async def test_upstream_status_controls_bounded_retries(
    recovery_db: Any, status: int, attempts: int
) -> None:
    import httpx

    from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker

    clock = [datetime.now(UTC)]
    queue = FormulaRecoveryQueue(recovery_db, now=lambda: clock[0])
    await queue.enqueue(request())

    class Gateway:
        async def fetch_resource(self, **kwargs: Any) -> dict[str, Any]:
            response = httpx.Response(status, request=httpx.Request("GET", "https://example.test"))
            response.raise_for_status()
            raise AssertionError("failure response must raise")

    worker = FormulaRecoveryWorker(db=recovery_db, gateway=Gateway(), queue=queue)
    for _ in range(attempts):
        assert await worker.process_one()
        clock[0] += timedelta(minutes=5)
    assert not await worker.process_one()
    job = await queue.collection.find_one({"_id": request().key})
    assert job["state"] == "failed"
    assert job["attempts"] == attempts


@pytest.mark.asyncio
async def test_crashed_recovery_stops_after_three_attempts(recovery_db: Any) -> None:
    clock = [datetime.now(UTC)]
    queue = FormulaRecoveryQueue(recovery_db, now=lambda: clock[0])
    await queue.enqueue(request())
    for expected in range(1, 4):
        job = await queue.claim()
        assert job is not None and job["attempts"] == expected
        clock[0] += timedelta(minutes=11)
    assert await queue.claim() is None
    job = await queue.collection.find_one({"_id": request().key})
    assert job["state"] == "failed"
    assert job["failure_reason"] == "attempts_exhausted"


@pytest.mark.asyncio
async def test_recovery_admission_is_bounded_under_concurrent_distinct_requests(
    recovery_db: Any,
) -> None:
    from zeler_sheets.formulas.recovery import OrderIdsRecoveryRequest

    queue = FormulaRecoveryQueue(recovery_db, max_active_jobs_per_seller=3)
    await queue.ensure_indexes()
    requests = [OrderIdsRecoveryRequest("pilot", (str(i),)) for i in range(20)]
    results = await asyncio.gather(
        *(queue.enqueue(item) for item in requests), return_exceptions=True
    )
    accepted = [result for result in results if isinstance(result, str)]
    assert len(accepted) == 3
    assert all(
        isinstance(result, str) or isinstance(result, ValueError) and "capacity" in str(result)
        for result in results
    )
    assert await queue.collection.count_documents({"seller_id": "pilot"}) == 3
    for item in requests:
        if item.key in accepted:
            assert await queue.enqueue(item) == item.key
    assert await queue.enqueue(OrderIdsRecoveryRequest("other", ("1",)))
    claimed = await queue.claim()
    assert claimed is not None
    # Running work consumes the same slot as pending work.
    with pytest.raises(ValueError, match="capacity"):
        await queue.enqueue(OrderIdsRecoveryRequest("pilot", ("100",)))


@pytest.mark.asyncio
async def test_cancelled_recovery_admission_does_not_consume_capacity(
    recovery_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue = FormulaRecoveryQueue(recovery_db, max_active_jobs_per_seller=1)
    inserted = asyncio.Event()
    original = queue.collection.insert_one

    async def pause_after_insert(*args: Any, **kwargs: Any) -> Any:
        result = await original(*args, **kwargs)
        inserted.set()
        await asyncio.Event().wait()
        return result

    monkeypatch.setattr(queue.collection, "insert_one", pause_after_insert)
    pending = asyncio.create_task(queue.enqueue(request()))
    await asyncio.wait_for(inserted.wait(), timeout=5)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert await queue.collection.count_documents({}) == 0
    monkeypatch.setattr(queue.collection, "insert_one", original)
    assert await queue.enqueue(request()) == request().key


@pytest.mark.parametrize("capacity", [0, -1, True, 1.5])
def test_recovery_capacity_must_be_positive_integer(capacity: Any) -> None:
    with pytest.raises(ValueError, match="capacity"):
        FormulaRecoveryQueue({}, max_active_jobs_per_seller=capacity)


@pytest.mark.asyncio
@pytest.mark.parametrize("succeeded", [True, False])
async def test_recovery_terminal_reopening_respects_capacity_and_cooldown(
    recovery_db: Any, succeeded: bool
) -> None:
    from zeler_sheets.formulas.recovery import OrderIdsRecoveryRequest

    queue = FormulaRecoveryQueue(recovery_db, max_active_jobs_per_seller=1)
    first = OrderIdsRecoveryRequest("pilot", ("1",))
    second = OrderIdsRecoveryRequest("pilot", ("2",))
    await queue.enqueue(first)
    claimed = await queue.claim()
    assert claimed is not None
    assert await queue.finish(claimed, succeeded=succeeded)
    terminal = await queue.collection.find_one({"_id": first.key})
    await queue.enqueue(second)
    with pytest.raises(ValueError, match="capacity"):
        await queue.enqueue(first)
    assert await queue.collection.find_one({"_id": first.key}) == terminal
    claimed = await queue.claim()
    assert claimed is not None
    assert await queue.finish(claimed, succeeded=True)
    assert await queue.enqueue(first) == first.key
    reopened = await queue.collection.find_one({"_id": first.key})
    assert reopened["state"] == "pending"
    assert reopened["available_at"] == terminal["available_at"]
    assert await queue.claim() is None


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
@pytest.mark.parametrize("succeeded", [True, False])
async def test_terminal_request_stays_scheduled_through_cooldown_without_another_recalculation(
    recovery_db: Any,
    succeeded: bool,
) -> None:
    clock = [datetime(2026, 9, 7, tzinfo=UTC)]
    queue = FormulaRecoveryQueue(recovery_db, now=lambda: clock[0])
    await queue.enqueue(request())
    claimed = await queue.claim()
    assert claimed is not None
    assert await queue.finish(claimed, succeeded=succeeded)
    terminal = await queue.collection.find_one({"_id": request().key})
    await asyncio.gather(*(queue.enqueue(request()) for _ in range(20)))
    scheduled = await queue.collection.find_one({"_id": request().key})
    assert scheduled["state"] == "pending"
    assert scheduled["available_at"] == terminal["available_at"]
    assert await queue.collection.count_documents({}) == 1
    assert await queue.claim() is None
    clock[0] += timedelta(minutes=16)
    next_attempt = await queue.claim()
    assert next_attempt is not None
    assert next_attempt["attempts"] == 1


def test_unrecoverable_history_is_not_scheduled() -> None:
    with pytest.raises(ValueError, match="recoverable"):
        RecoveryRequest(
            seller_id="pilot",
            read_model="stock_time_metrics",
            date_from=datetime(2026, 8, 8, tzinfo=UTC),
            date_to=datetime(2026, 9, 7, tzinfo=UTC),
        )
