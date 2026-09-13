# ruff: noqa: F811,S105 -- imported pytest fixture and synthetic lease identity

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from test_formula_recovery import recovery_db  # noqa: F401

from zeler_sheets.formulas.recovery import (
    IMPLEMENTED_MODELS,
    FormulaRecoveryQueue,
    ItemIdsRecoveryRequest,
)
from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "dependency_state", ["available", "unavailable", "foreign_owner", "lease_lost"]
)
async def test_buybox_preserves_fresh_sibling_while_recovering_expired_participation(
    recovery_db: Any, dependency_state: str
) -> None:
    now = datetime.now(UTC)
    seller = "82453304"
    await recovery_db.items.insert_many(
        [
            {
                "_id": identity,
                "seller_id": seller,
                "catalog_listing": identity != "MLA3",
                "catalog_product_id": "MLA9",
                "title": identity,
                "available_quantity": 2,
                "last_meli_sync_at": now - timedelta(minutes=20 if identity == "MLA2" else 1),
            }
            for identity in ("MLA1", "MLA2", "MLA3")
        ]
    )
    queue = FormulaRecoveryQueue(recovery_db, enabled_models=IMPLEMENTED_MODELS)
    request = ItemIdsRecoveryRequest(
        seller, ("MLA1", "MLA2", "MLA3"), read_model="catalog_buybox_snapshots"
    )
    await queue.enqueue(request)
    calls: list[str] = []

    class Discovery:
        async def fetch_resource(self, **kwargs: Any) -> Any:
            raise AssertionError("Discovery identity cannot acquire item/product details")

    class Detail:
        async def fetch_resource(self, *, seller_id: str, path: str) -> Any:
            assert seller_id == seller
            calls.append(path)
            if path == "/items?ids=MLA2&include_attributes=all":
                if dependency_state == "unavailable":
                    response = httpx.Response(503, request=httpx.Request("GET", "https://test"))
                    response.raise_for_status()
                if dependency_state == "lease_lost":
                    await queue.collection.update_one(
                        {"_id": request.key}, {"$set": {"attempt_token": "replacement-owner"}}
                    )
                return [
                    {
                        "code": 200,
                        "body": {
                            "id": "MLA2",
                            "seller_id": "42" if dependency_state == "foreign_owner" else seller,
                            "title": "Recovered publication",
                            "catalog_product_id": "MLA9",
                            "catalog_listing": True,
                            "price": 100,
                            "base_price": 100,
                            "currency_id": "ARS",
                            "site_id": "MLA",
                            "category_id": "MLA123",
                            "listing_type_id": "gold_special",
                            "available_quantity": 2,
                            "status": "active",
                            "attributes": [],
                            "variations": [],
                            "shipping": {"mode": "me2", "free_shipping": False},
                            "date_created": "2026-09-01T00:00:00Z",
                            "last_updated": "2026-09-07T00:00:00Z",
                        },
                    }
                ]
            if path == "/items/MLA2/sale_price?context=channel_marketplace":
                return {"amount": 100, "regular_amount": 100, "currency_id": "ARS"}
            if path.startswith("/sites/MLA/listing_prices?"):
                return {
                    "sale_fee_amount": 10,
                    "currency_id": "ARS",
                    "sale_fee_details": {"percentage_fee": 10, "fixed_fee": 2},
                }
            if path == "/item/MLA2/performance":
                return {
                    "entity_type": "ITEM",
                    "entity_id": "MLA2",
                    "score": 69,
                    "level": "Good",
                    "calculated_at": "2026-09-01T00:00:00Z",
                    "buckets": [],
                }
            if path in (
                "/items/MLA1/price_to_win?version=v2",
                "/items/MLA2/price_to_win?version=v2",
            ):
                identity = path.split("/")[2]
                return {
                    "item_id": identity,
                    "status": "winning",
                    "current_price": 100,
                    "competitors_sharing_first_place": 0,
                    "winner": {"item_id": identity, "price": 99},
                }
            assert path == "/products/MLA9/items"
            return {
                "paging": {"total": 2, "offset": 0, "limit": 100},
                "results": [
                    {"item_id": "MLA1", "seller_id": seller},
                    {"item_id": "MLA2", "seller_id": seller},
                ],
            }

    assert await FormulaRecoveryWorker(
        db=recovery_db, queue=queue, gateway=Discovery(), detail_gateway=Detail()
    ).process_one()
    stored = await recovery_db.sheets_catalog_buybox_snapshots.find({}).to_list(10)
    identities = {row["item_id"] for row in stored}
    if dependency_state == "lease_lost":
        assert identities <= {"MLA1"}
    else:
        assert identities == ({"MLA1", "MLA2"} if dependency_state == "available" else {"MLA1"})
    assert "/items?ids=MLA2&include_attributes=all" in calls
    assert not any("MLA3" in path for path in calls)
    assert await recovery_db.sheets_read_model_freshness.count_documents({}) == 0
    job = await queue.collection.find_one({"_id": request.key})
    if dependency_state == "lease_lost":
        assert job["state"] == "running"
        assert job["attempt_token"] == "replacement-owner"
    else:
        assert job["state"] == ("pending" if dependency_state == "unavailable" else "failed")
