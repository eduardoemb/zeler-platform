from copy import deepcopy
from typing import Any

import pytest
from bson.decimal128 import Decimal128
from test_sheetseller_backfill import NOW, FakeDb, FakeItemGateway, _item_detail, _item_doc

from zeler_sheets.enrichment import schema_safe_enrichment_state, trusted_state
from zeler_sheets.sheetseller_backfill import (
    _item_shipping_basis,
    run_item_detail_enrichment,
    run_sheetseller_backfill,
)


def acquisition() -> tuple[FakeDb, FakeItemGateway, dict[str, Any]]:
    detail = _item_detail("MLA1")
    detail.update(currency_id="ARS", listing_type_id="gold_special", site_id="MLA")
    detail["shipping"] = {"mode": "me2", "logistic_type": "fulfillment", "free_shipping": True}
    item = {**_item_doc("MLA1"), **deepcopy(detail)}
    item["seller_shipping_cost"] = Decimal128("83.25")
    item["enrichment_state"] = {
        "seller_shipping_cost": trusted_state(
            source="/users/{seller_id}/shipping_options/free",
            synced_at=NOW,
            basis=_item_shipping_basis(detail),
        )
    }
    db = FakeDb([item])
    gateway = FakeItemGateway(
        {"/items?ids=MLA1&include_attributes=all": [{"code": 200, "body": detail}]}
    )
    return db, gateway, detail


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", [False, True])
async def test_basic_acquisition_skips_enrichment_and_preserves_its_observation(
    changed: bool,
) -> None:
    db, gateway, detail = acquisition()
    if changed:
        detail["price"] = "200.00"
    summary = await run_item_detail_enrichment(
        db=db,
        gateway=gateway,
        seller_id="82453304",
        dry_run=False,
        base_only=True,
        sale_price_enabled=True,
        listing_fixed_fee_enabled=True,
        quality_enabled=True,
    )
    persisted = db["items"].documents["MLA1"]
    state = persisted["enrichment_state"]["seller_shipping_cost"]
    assert state["synced_at"] == NOW
    assert state["status"] == ("basis_mismatch" if changed else "trusted")
    assert persisted["seller_shipping_cost"] == Decimal128("83.25")
    assert persisted["last_meli_sync_at"] > NOW
    assert summary.items_updated == 1
    assert len(gateway.calls) == 1
    assert summary.shipping_options_requested == summary.listing_prices_requested == 0


@pytest.mark.asyncio
async def test_basic_acquisition_still_resolves_variation_sku() -> None:
    db, gateway, detail = acquisition()
    detail["variations"] = [{"id": 123, "available_quantity": 0}]
    gateway.payloads["/items/MLA1/variations/123"] = {
        "id": 123,
        "attributes": [{"id": "SELLER_SKU", "value_name": "SKU-123"}],
    }
    await run_item_detail_enrichment(
        db=db,
        gateway=gateway,
        seller_id="82453304",
        dry_run=False,
        base_only=True,
    )
    await run_sheetseller_backfill(db=db, seller_id="82453304", item_ids=["MLA1"], dry_run=False)
    assert len(gateway.calls) == 2
    row = db["sheets_item_formula_rows"].documents["82453304:SKU-123:MLA1:123"]
    assert row["current"]["available_quantity"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("selected", [None, ["MLA1"]])
async def test_projection_dependency_reads_match_selected_scope(selected: list[str] | None) -> None:
    db = FakeDb([_item_doc("MLA1"), _item_doc("MLA2")])
    await run_sheetseller_backfill(db=db, seller_id="82453304", item_ids=selected)
    expected = {} if selected is None else {"item_id": {"$in": selected}}
    assert db["sheets_item_sku_index"].find_filters[0] == {
        "seller_id": "82453304",
        "source": "order_line",
        **expected,
    }
    assert db["item_status_states"].find_filters[0] == {"seller_id": "82453304", **expected}


@pytest.mark.parametrize("changed", [False, True])
def test_basic_acquisition_checks_all_projection_bases(changed: bool) -> None:
    from zeler_sheets.sheetseller_backfill import (
        _base_acquisition_enrichment_state,
        _listing_price_fixed_fee_params,
        build_listing_fee_projection_context,
        project_listing_price_fixed_fee_projection,
    )

    db, _, detail = acquisition()
    item = db["items"].documents["MLA1"]
    fee = build_listing_fee_projection_context(site_id="MLA", detail=detail)
    fixed = _listing_price_fixed_fee_params(item_id="MLA1", detail=detail)
    item["listing_fee_projection"] = fee
    assert fixed is not None
    item["listing_price_fixed_fee"] = project_listing_price_fixed_fee_projection(
        {"sale_fee_details": {"fixed_fee": "10"}, "currency_id": "ARS"},
        params=fixed,
        synced_at=NOW,
    )
    for field in (
        "listing_fee_projection",
        "listing_price_fixed_fee",
        "current_promotion",
        "quality_projection",
    ):
        item["enrichment_state"][field] = trusted_state(source="/test", synced_at=NOW)
    if changed:
        detail.update(price="200", title="Changed title")
    states = _base_acquisition_enrichment_state(item, detail=detail, site_id="MLA")
    assert len(states) == 5
    assert {state["synced_at"] for state in states.values()} == {NOW}
    assert {state["status"] for state in states.values()} == {
        "basis_mismatch" if changed else "trusted"
    }


def test_basic_acquisition_invalidates_untracked_quality_when_basis_changes() -> None:
    from zeler_sheets.sheetseller_backfill import _base_acquisition_enrichment_state

    db, _, detail = acquisition()
    item = db["items"].documents["MLA1"]
    item["quality_projection"] = {"source": "/item/{id}/performance", "observed_at": NOW}
    detail["title"] = "Changed title"
    state = _base_acquisition_enrichment_state(item, detail=detail, site_id="MLA")[
        "quality_projection"
    ]
    assert state["status"] == "basis_mismatch"
    assert state["synced_at"] == NOW


@pytest.mark.asyncio
@pytest.mark.parametrize("conflict", [False, True])
async def test_basic_acquisition_preserves_concurrent_writes_in_mongo(
    default_mongo_uri: str,
    conflict: bool,
) -> None:
    from uuid import uuid4

    from motor.motor_asyncio import AsyncIOMotorClient

    from zeler_sheets.sheetseller_backfill import RetryableItemAcquisitionError

    client: Any = AsyncIOMotorClient(default_mongo_uri, serverSelectionTimeoutMS=2000)
    db = client[f"test_layered_basic_{uuid4().hex}"]
    seed, gateway, _ = acquisition()
    document = seed["items"].documents["MLA1"]
    document["enrichment_state"] = schema_safe_enrichment_state(document["enrichment_state"])
    await db.items.insert_one(document)
    original_fetch = gateway.fetch_resource

    async def fetch(*, seller_id: str, path: str) -> Any:
        if conflict:
            await db.items.update_one({"_id": "MLA1"}, {"$set": {"title": "Concurrent title"}})
        return await original_fetch(seller_id=seller_id, path=path)

    gateway.fetch_resource = fetch  # type: ignore[method-assign]
    try:
        if conflict:
            with pytest.raises(RetryableItemAcquisitionError, match="item changed"):
                await run_item_detail_enrichment(
                    db=db,
                    gateway=gateway,
                    seller_id="82453304",
                    base_only=True,
                    dry_run=False,
                )
        else:
            summary = await run_item_detail_enrichment(
                db=db,
                gateway=gateway,
                seller_id="82453304",
                base_only=True,
                dry_run=False,
            )
            assert summary.items_updated == 1
            await run_sheetseller_backfill(
                db=db, seller_id="82453304", item_ids=["MLA1"], dry_run=False
            )
            row = await db.sheets_item_formula_rows.find_one({"item_id": "MLA1"})
            assert row["current"]["available_quantity"] == 7
        stored = await db.items.find_one({"_id": "MLA1"})
        assert stored["title"] == ("Concurrent title" if conflict else "Detail MLA1")
        assert (
            stored["enrichment_state"]["seller_shipping_cost"]["synced_at"].replace(
                tzinfo=NOW.tzinfo
            )
            == NOW
        )
    finally:
        await client.drop_database(db.name)
        client.close()


@pytest.mark.parametrize("currency", ["ARS", "USD"])
def test_basic_promotion_retention_requires_same_currency(currency: str) -> None:
    from zeler_sheets.sheetseller_backfill import _base_acquisition_enrichment_state

    db, _, detail = acquisition()
    item = db["items"].documents["MLA1"]
    item["enrichment_state"]["current_promotion"] = trusted_state(
        source="/items/{id}/sale_price", synced_at=NOW
    )
    detail["currency_id"] = currency
    states = _base_acquisition_enrichment_state(item, detail=detail, site_id="MLA")
    assert states["current_promotion"]["status"] == (
        "trusted" if currency == "ARS" else "basis_mismatch"
    )


@pytest.mark.asyncio
async def test_repeated_basic_acquisition_renews_only_the_observed_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import datetime, timedelta, tzinfo

    clock = [NOW]

    class ClockMeta(type):
        def __instancecheck__(cls, instance: Any) -> bool:
            return isinstance(instance, datetime)

    class AcquisitionClock(datetime, metaclass=ClockMeta):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> Any:
            return clock[0]

    monkeypatch.setattr("zeler_sheets.sheetseller_backfill.datetime", AcquisitionClock)
    db, gateway, _ = acquisition()
    first = await run_item_detail_enrichment(
        db=db, gateway=gateway, seller_id="82453304", dry_run=False, base_only=True
    )
    assert first.items_updated == 1
    clock[0] += timedelta(minutes=16)
    second = await run_item_detail_enrichment(
        db=db, gateway=gateway, seller_id="82453304", dry_run=False, base_only=True
    )
    stored = db["items"].documents["MLA1"]
    assert len(gateway.calls) == 2
    assert second.items_updated == 1
    assert stored["last_meli_sync_at"] == clock[0]
    assert stored["enrichment_state"]["seller_shipping_cost"]["synced_at"] == NOW
