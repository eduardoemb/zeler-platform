# ruff: noqa: F811 -- imported pytest fixture
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from test_formula_item_history_recovery import _execute
from test_formula_recovery import recovery_db  # noqa: F401

from zeler_sheets.formulas.recovery import FormulaRecoveryQueue, ItemIdsRecoveryRequest
from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["active", "paused"])
async def test_real_item_recovery_projects_history_at_actual_acquisition(
    recovery_db: Any, status: str
) -> None:
    now = datetime.now(UTC)
    old = now - timedelta(days=3)
    seller = "82453304"
    await recovery_db.items.insert_one(
        {"_id": "MLM1", "seller_id": seller, "status": status, "last_meli_sync_at": old}
    )
    await recovery_db.item_status_states.insert_one(
        {
            "_id": f"{seller}:MLM1",
            "seller_id": seller,
            "item_id": "MLM1",
            "current_status": status,
            "first_observed_at": old,
            "status_started_at": old,
            "last_observed_at": old,
        }
    )

    class Gateway:
        async def fetch_resource(self, *, seller_id: str, path: str) -> Any:
            assert seller_id == seller
            if path == "/items?ids=MLM1&include_attributes=all":
                return [
                    {
                        "code": 200,
                        "body": {
                            "id": "MLM1",
                            "seller_id": seller,
                            "title": "Fixture",
                            "price": 100,
                            "base_price": 100,
                            "currency_id": "MXN",
                            "site_id": "MLM",
                            "category_id": "MLM123",
                            "listing_type_id": "gold_special",
                            "available_quantity": 0,
                            "status": status,
                            "attributes": [],
                            "variations": [],
                            "shipping": {"mode": "me2", "free_shipping": False},
                            "date_created": "2026-09-01T00:00:00Z",
                            "last_updated": "2026-09-07T00:00:00Z",
                        },
                    }
                ]
            if "/sale_price?" in path:
                return {"amount": 100, "regular_amount": 100, "currency_id": "MXN"}
            if path.startswith("/sites/MLM/listing_prices?"):
                return {
                    "sale_fee_amount": 10,
                    "currency_id": "MXN",
                    "sale_fee_details": {"percentage_fee": 10, "fixed_fee": 0},
                }
            if path == "/items/MLM1/health":
                return {"health": 0.8}
            if path == "/item/MLM1/performance":
                return {"score": 80}
            raise AssertionError(path)

    queue = FormulaRecoveryQueue(recovery_db)
    await queue.enqueue(ItemIdsRecoveryRequest(seller, ("MLM1",)))
    claimed = await queue.claim()
    assert claimed is not None
    await FormulaRecoveryWorker(db=recovery_db, gateway=Gateway(), queue=queue)._items(claimed)
    item = await recovery_db.items.find_one({"_id": "MLM1"})
    job = await queue.collection.find_one({"read_model": "item_formula_rows"})
    assert job["state"] == "completed", job
    assert item["last_meli_sync_at"] > old.replace(tzinfo=None)
    state = await recovery_db.item_status_states.find_one({"item_id": "MLM1"})
    assert state["last_observed_at"] == item["last_meli_sync_at"]
    assert state["status_started_at"] == old.replace(
        tzinfo=None, microsecond=old.microsecond // 1000 * 1000
    )
    price = await recovery_db.sheets_price_history_snapshots.find_one({"item_id": "MLM1"})
    stock = await recovery_db.sheets_stockout_snapshots.find_one({"item_id": "MLM1"})
    assert price["prices"][0]["observed_at"] == item["last_meli_sync_at"]
    assert stock["observed_at"] == item["last_meli_sync_at"]
    assert stock["current_stock"] == 0
    assert await recovery_db.sheets_read_model_freshness.count_documents({}) == 0
    active = await _execute(recovery_db, "TIEMPOACTIVA", now=datetime.now(UTC))
    assert active.values == [[3 if status == "active" else "NA"]]
    assert active.recovery is None
    price_result = await _execute(recovery_db, "PRECIOHISTORICO", now=datetime.now(UTC))
    assert price_result.values == [["MLM1", "Fixture", 100, status, "NA", "NA", "NA", "NA"]]
    assert price_result.recovery is None


@pytest.mark.asyncio
@pytest.mark.parametrize("foreign_owner", [True, False])
async def test_acquired_history_cannot_replace_newer_or_foreign_observation(
    recovery_db: Any, foreign_owner: bool
) -> None:
    from zeler_sheets.event_persistence import SheetsEventPersistence

    now = datetime.now(UTC).replace(microsecond=0)
    await recovery_db.items.insert_one(
        {
            "_id": "MLM1",
            "seller_id": "other" if foreign_owner else "82453304",
            "status": "active",
            "last_meli_sync_at": now - timedelta(days=1),
            "price": 100,
            "available_quantity": 0,
        }
    )
    state = {
        "_id": "82453304:MLM1",
        "seller_id": "82453304",
        "item_id": "MLM1",
        "current_status": "paused",
        "first_observed_at": now,
        "status_started_at": now,
        "last_observed_at": now,
    }
    await recovery_db.item_status_states.insert_one(state)
    await SheetsEventPersistence(db=recovery_db).project_acquired_item_history(
        seller_id="82453304", item_id="MLM1"
    )
    stored = await recovery_db.item_status_states.find_one({"_id": state["_id"]})
    assert stored["current_status"] == "paused"
    assert stored["last_observed_at"] == now.replace(tzinfo=None)
    assert await recovery_db.sheets_price_history_snapshots.count_documents({}) == 0
    assert await recovery_db.sheets_stockout_snapshots.count_documents({}) == 0
