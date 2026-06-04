from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from bson import BSON
from bson.decimal128 import Decimal128

from zeler_sheets.event_persistence import SheetsEventPersistence

NOW = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)


class FakeReplaceResult:
    matched_count = 1
    modified_count = 1
    upserted_id = None


class FakeCursor:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self._documents = documents

    async def to_list(self, *, length: int | None = None) -> list[dict[str, Any]]:
        return self._documents[:length]


class FakeCollection:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}
        self.replace_calls: list[tuple[dict[str, Any], dict[str, Any], bool]] = []

    async def replace_one(
        self, filter_spec: dict[str, Any], replacement: dict[str, Any], *, upsert: bool = False
    ) -> FakeReplaceResult:
        self.replace_calls.append((dict(filter_spec), dict(replacement), upsert))
        self.documents[str(replacement["_id"])] = dict(replacement)
        return FakeReplaceResult()

    def find(self, filter_spec: dict[str, Any]) -> FakeCursor:
        documents = [
            document
            for document in self.documents.values()
            if all(document.get(key) == value for key, value in filter_spec.items())
        ]
        return FakeCursor(documents)

    async def find_one(self, filter_spec: dict[str, Any]) -> dict[str, Any] | None:
        for document in self.documents.values():
            if all(document.get(key) == value for key, value in filter_spec.items()):
                return document
        return None


class FakeDb:
    def __init__(self) -> None:
        self.collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        return self.collections.setdefault(name, FakeCollection())


@pytest.mark.asyncio
async def test_persists_item_and_refreshes_sheetseller_read_models() -> None:
    db = FakeDb()
    persistence = SheetsEventPersistence(db=db, clock=lambda: NOW)

    await persistence.persist(
        event_type="items.updated",
        seller_id=82453304,
        resource={
            "id": "MLA1",
            "title": "Premium widget",
            "price": "149.99",
            "base_price": "159.99",
            "available_quantity": 7,
            "status": "active",
            "category_id": "MLA123",
            "permalink": "https://articulo.example/MLA1",
            "thumbnail": "https://img.example/MLA1.jpg",
            "catalog_product_id": "CAT-1",
            "inventory_id": "INV-ITEM-1",
            "listing_type_id": "gold_special",
            "shipping": {"logistic_type": "cross_docking", "free_shipping": False},
            "attributes": [{"id": "SELLER_SKU", "value_name": "sku-1"}],
            "variations": [
                {"id": 101, "seller_custom_field": "var-101", "inventory_id": "INV-VAR-101"}
            ],
            "date_created": "2026-05-01T10:00:00+00:00",
            "last_updated": "2026-05-30T11:00:00+00:00",
        },
    )

    item = db["items"].documents["MLA1"]
    assert item["_id"] == "MLA1"
    assert item["seller_id"] == "82453304"
    assert item["schema_version"] == 2
    assert item["last_meli_sync_at"] == NOW
    assert item["price"] == Decimal128("149.99")
    assert item["listing_type_id"] == "gold_special"
    BSON.encode(item)

    assert sorted(db["sheets_item_sku_index"].documents) == [
        "82453304:SKU-1:MLA1:item",
        "82453304:VAR-101:MLA1:101",
    ]
    assert sorted(db["sheets_item_formula_rows"].documents) == [
        "82453304:SKU-1:MLA1",
        "82453304:VAR-101:MLA1:101",
    ]
    variation_row = db["sheets_item_formula_rows"].documents["82453304:VAR-101:MLA1:101"]
    assert variation_row["inventory_id"] == "INV-VAR-101"
    assert variation_row["current"]["title"] == "Premium widget"
    assert variation_row["current"]["listing_type_id"] == "gold_special"
    assert variation_row["current"]["shipping_logistic_type"] == "cross_docking"
    assert variation_row["current"]["shipping_payer"] == "Comprador"


@pytest.mark.asyncio
async def test_persists_order_for_sheetseller_order_formulas() -> None:
    db = FakeDb()
    persistence = SheetsEventPersistence(db=db, clock=lambda: NOW)

    await persistence.persist(
        event_type="orders.updated",
        seller_id=82453304,
        resource={
            "id": 2001,
            "status": "paid",
            "date_created": "2026-05-29T10:00:00+00:00",
            "date_closed": "2026-05-29T10:05:00+00:00",
            "total_amount": "299.90",
            "buyer": {"id": 123},
            "shipping": {"id": 555},
            "order_items": [
                {
                    "item": {"id": "MLA1", "seller_sku": "sku-1"},
                    "quantity": 2,
                    "unit_price": "149.95",
                }
            ],
            "tags": ["paid"],
        },
    )

    order = db["orders"].documents["2001"]
    assert order["_id"] == "2001"
    assert order["seller_id"] == "82453304"
    assert order["buyer_id"] == "123"
    assert order["shipment_id"] == "555"
    assert order["total_amount"] == Decimal128("299.90")
    BSON.encode(order)
    assert order["items"] == [
        {"item_id": "MLA1", "seller_sku": "sku-1", "qty": 2, "unit_price": Decimal128("149.95")}
    ]


@pytest.mark.asyncio
async def test_persisted_order_feeds_live_sku_index_from_order_line_identity() -> None:
    db = FakeDb()
    persistence = SheetsEventPersistence(db=db, clock=lambda: NOW)

    await persistence.persist(
        event_type="orders.updated",
        seller_id=82453304,
        resource={
            "id": 2001,
            "status": "paid",
            "date_created": "2026-05-29T10:00:00+00:00",
            "total_amount": "299.90",
            "buyer": {"id": 123},
            "order_items": [
                {
                    "item": {"id": "MLA1", "variation_id": 101, "seller_sku": "sku-1"},
                    "quantity": 2,
                    "unit_price": "149.95",
                }
            ],
        },
    )

    assert db["sheets_item_sku_index"].documents["82453304:SKU-1:MLA1:101"] == {
        "_id": "82453304:SKU-1:MLA1:101",
        "seller_id": "82453304",
        "seller_nickname": None,
        "sku": "sku-1",
        "normalized_sku": "SKU-1",
        "item_id": "MLA1",
        "variation_id": "101",
        "identity_level": "variation",
        "source": "order_line",
        "inventory_id": None,
        "updated_at": datetime(2026, 5, 29, 10, 0, tzinfo=UTC),
        "schema_version": 2,
    }


@pytest.mark.asyncio
async def test_persisted_order_feeds_sku_index_from_order_line_seller_sku_attribute() -> None:
    db = FakeDb()
    persistence = SheetsEventPersistence(db=db, clock=lambda: NOW)

    await persistence.persist(
        event_type="orders.updated",
        seller_id=82453304,
        resource={
            "id": 2001,
            "status": "paid",
            "date_created": "2026-05-29T10:00:00+00:00",
            "total_amount": "299.90",
            "buyer": {"id": 123},
            "order_items": [
                {
                    "item": {
                        "id": "MLA1",
                        "variation_id": 101,
                        "variation_attributes": [{"id": "SELLER_SKU", "value_name": "attr-sku-1"}],
                    },
                    "quantity": 2,
                    "unit_price": "149.95",
                }
            ],
        },
    )

    order = db["orders"].documents["2001"]
    assert order["items"] == [
        {
            "item_id": "MLA1",
            "variation_id": "101",
            "seller_sku": "attr-sku-1",
            "qty": 2,
            "unit_price": Decimal128("149.95"),
        }
    ]
    assert (
        db["sheets_item_sku_index"].documents["82453304:ATTR-SKU-1:MLA1:101"]["source"]
        == "order_line"
    )


@pytest.mark.asyncio
async def test_order_line_sku_index_skips_conflicting_live_identity() -> None:
    db = FakeDb()
    db["sheets_item_sku_index"].documents["82453304:SKU-1:MLA1:101"] = {
        "_id": "82453304:SKU-1:MLA1:101",
        "seller_id": "82453304",
        "sku": "sku-1",
        "normalized_sku": "SKU-1",
        "item_id": "MLA1",
        "variation_id": "101",
        "identity_level": "variation",
        "source": "order_line",
        "inventory_id": None,
        "updated_at": datetime(2026, 5, 29, 10, 0, tzinfo=UTC),
        "schema_version": 2,
    }
    persistence = SheetsEventPersistence(db=db, clock=lambda: NOW)

    await persistence.persist(
        event_type="orders.updated",
        seller_id=82453304,
        resource={
            "id": 2002,
            "status": "paid",
            "date_created": "2026-05-30T10:00:00+00:00",
            "total_amount": "299.90",
            "buyer": {"id": 123},
            "order_items": [
                {
                    "item": {"id": "MLA1", "variation_id": 101, "seller_sku": "sku-2"},
                    "quantity": 2,
                    "unit_price": "149.95",
                }
            ],
        },
    )

    assert sorted(db["sheets_item_sku_index"].documents) == ["82453304:SKU-1:MLA1:101"]


@pytest.mark.asyncio
async def test_item_without_seller_sku_refreshes_formula_rows_from_known_order_line_sku() -> None:
    db = FakeDb()
    db["sheets_item_sku_index"].documents["82453304:SKU-1:MLA1:101"] = {
        "_id": "82453304:SKU-1:MLA1:101",
        "seller_id": "82453304",
        "sku": "sku-1",
        "normalized_sku": "SKU-1",
        "item_id": "MLA1",
        "variation_id": "101",
        "identity_level": "variation",
        "source": "order_line",
        "inventory_id": None,
        "updated_at": datetime(2026, 5, 29, 10, 0, tzinfo=UTC),
        "schema_version": 2,
    }
    persistence = SheetsEventPersistence(db=db, clock=lambda: NOW)

    await persistence.persist(
        event_type="items.updated",
        seller_id=82453304,
        resource={
            "id": "MLA1",
            "title": "Premium widget updated",
            "price": "149.99",
            "base_price": "159.99",
            "available_quantity": 7,
            "status": "active",
            "category_id": "MLA123",
            "permalink": "https://articulo.example/MLA1",
            "thumbnail": "https://img.example/MLA1.jpg",
            "catalog_product_id": "CAT-1",
            "attributes": [],
            "variations": [{"id": 101, "inventory_id": "INV-VAR-101"}],
            "date_created": "2026-05-01T10:00:00+00:00",
            "last_updated": "2026-05-30T11:00:00+00:00",
        },
    )

    formula_row = db["sheets_item_formula_rows"].documents["82453304:SKU-1:MLA1:101"]
    assert formula_row["sku"] == "sku-1"
    assert formula_row["inventory_id"] == "INV-VAR-101"
    assert formula_row["current"]["title"] == "Premium widget updated"
    assert formula_row["current"]["catalog_product_id"] == "CAT-1"
    assert formula_row["current"]["inventory_id"] == "INV-VAR-101"


@pytest.mark.asyncio
async def test_item_with_direct_sku_does_not_create_stale_order_line_duplicate() -> None:
    db = FakeDb()
    db["sheets_item_sku_index"].documents["82453304:STALE-SKU:MLA1:item"] = {
        "_id": "82453304:STALE-SKU:MLA1:item",
        "seller_id": "82453304",
        "sku": "stale-sku",
        "normalized_sku": "STALE-SKU",
        "item_id": "MLA1",
        "variation_id": None,
        "identity_level": "item",
        "source": "order_line",
        "inventory_id": None,
        "updated_at": datetime(2026, 5, 29, 10, 0, tzinfo=UTC),
        "schema_version": 2,
    }
    persistence = SheetsEventPersistence(db=db, clock=lambda: NOW)

    await persistence.persist(
        event_type="items.updated",
        seller_id=82453304,
        resource={
            "id": "MLA1",
            "title": "Premium widget",
            "price": "149.99",
            "base_price": "159.99",
            "available_quantity": 7,
            "status": "active",
            "category_id": "MLA123",
            "attributes": [{"id": "SELLER_SKU", "value_name": "fresh-sku"}],
            "date_created": "2026-05-01T10:00:00+00:00",
            "last_updated": "2026-05-30T11:00:00+00:00",
        },
    )

    assert sorted(db["sheets_item_formula_rows"].documents) == ["82453304:FRESH-SKU:MLA1"]


@pytest.mark.asyncio
async def test_item_event_refreshes_formula_rows_from_persisted_current_promotion() -> None:
    db = FakeDb()
    persistence = SheetsEventPersistence(db=db, clock=lambda: NOW)

    await persistence.persist(
        event_type="items.updated",
        seller_id=82453304,
        resource={
            "id": "MLA1",
            "title": "Promoted listing",
            "price": "99.90",
            "base_price": "149.90",
            "available_quantity": 7,
            "status": "active",
            "category_id": "MLA123",
            "attributes": [{"id": "SELLER_SKU", "value_name": "sku-1"}],
            "date_created": "2026-05-01T10:00:00+00:00",
            "last_updated": "2026-05-30T11:00:00+00:00",
            "current_promotion": {
                "source": "/items/{id}/sale_price",
                "sale_amount": "99.90",
                "regular_amount": "149.90",
                "discount_percent": "33.36",
                "currency_id": "MXN",
                "promotion_id": "PROMO-1",
                "promotion_type": "deal",
                "reference_at": NOW,
                "synced_at": NOW,
            },
        },
    )

    item = db["items"].documents["MLA1"]
    row = db["sheets_item_formula_rows"].documents["82453304:SKU-1:MLA1"]
    assert item["current_promotion"]["sale_amount"] == Decimal128("99.90")
    assert row["current"]["current_promotion"]["sale_amount"] == Decimal128("99.90")


@pytest.mark.asyncio
async def test_price_event_does_not_treat_prices_payload_as_promo_source() -> None:
    db = FakeDb()
    persistence = SheetsEventPersistence(db=db, clock=lambda: NOW)

    await persistence.persist(
        event_type="items.price_updated",
        seller_id=82453304,
        resource={
            "id": "MLA1",
            "title": "Price updated listing",
            "price": "99.90",
            "base_price": "149.90",
            "available_quantity": 7,
            "status": "active",
            "category_id": "MLA123",
            "attributes": [{"id": "SELLER_SKU", "value_name": "sku-1"}],
            "prices": [{"amount": "99.90", "regular_amount": "149.90"}],
            "date_created": "2026-05-01T10:00:00+00:00",
            "last_updated": "2026-05-30T11:00:00+00:00",
        },
    )

    item = db["items"].documents["MLA1"]
    row = db["sheets_item_formula_rows"].documents["82453304:SKU-1:MLA1"]
    assert "current_promotion" not in item
    assert "current_promotion" not in row["current"]


@pytest.mark.asyncio
async def test_persists_shipment_for_live_shipping_notifications() -> None:
    db = FakeDb()
    persistence = SheetsEventPersistence(db=db, clock=lambda: NOW)

    await persistence.persist(
        event_type="shipments.updated",
        seller_id=82453304,
        resource={
            "id": 3001,
            "order_id": 2001,
            "status": "ready_to_ship",
            "substatus": "printed",
            "tracking_number": "TRACK-1",
            "logistic_type": "fulfillment",
            "date_created": "2026-05-29T10:00:00+00:00",
            "last_updated": "2026-05-30T11:00:00+00:00",
        },
    )

    shipment = db["shipments"].documents["3001"]
    assert shipment == {
        "_id": "3001",
        "seller_id": "82453304",
        "order_id": "2001",
        "status": "ready_to_ship",
        "substatus": "printed",
        "tracking_number": "TRACK-1",
        "logistic_type": "fulfillment",
        "date_created": datetime(2026, 5, 29, 10, 0, tzinfo=UTC),
        "last_updated": datetime(2026, 5, 30, 11, 0, tzinfo=UTC),
        "schema_version": 1,
    }
    BSON.encode(shipment)


@pytest.mark.asyncio
async def test_persists_shipment_receiver_address_from_allowlisted_snapshot_only() -> None:
    db = FakeDb()
    persistence = SheetsEventPersistence(db=db, clock=lambda: NOW)

    await persistence.persist(
        event_type="shipments.updated",
        seller_id=82453304,
        resource={
            "id": 3001,
            "order_id": 2001,
            "status": "ready_to_ship",
            "substatus": "printed",
            "tracking_number": "TRACK-1",
            "logistic_type": "fulfillment",
            "date_created": "2026-05-29T10:00:00+00:00",
            "last_updated": "2026-05-30T11:00:00+00:00",
            "receiver_address": {
                "receiver_name": "  Synthetic Buyer  ",
                "street_name": " Sentinel Street ",
                "street_number": 123,
                "neighborhood": {"name": " Test Neighborhood "},
                "zip_code": " 1000 ",
                "city": {"name": " Test City "},
                "state": {"name": " Test State "},
                "country": {"id": "AR", "name": " Argentina "},
                "phone": "+54-PII-PHONE",
                "email": "pii@example.invalid",
                "document": "PII-DOCUMENT",
                "comment": "PII-COMMENT",
                "latitude": "PII-GEO-LAT",
                "longitude": "PII-GEO-LON",
            },
            "receiver": {"name": "RAW-RECEIVER-PII", "phone": "+54-RAW-PHONE"},
            "buyer": {"email": "raw-buyer@example.invalid"},
            "token": "PII-OAUTH-TOKEN",
        },
    )

    shipment = db["shipments"].documents["3001"]
    assert shipment["receiver_address"] == {
        "name": "Synthetic Buyer",
        "street_name": "Sentinel Street",
        "street_number": "123",
        "neighborhood": "Test Neighborhood",
        "zip_code": "1000",
        "city": "Test City",
        "state": "Test State",
        "country": "Argentina",
    }
    serialized_shipment = repr(shipment)
    for forbidden in (
        "+54-PII-PHONE",
        "pii@example.invalid",
        "PII-DOCUMENT",
        "PII-COMMENT",
        "PII-GEO-LAT",
        "PII-GEO-LON",
        "RAW-RECEIVER-PII",
        "raw-buyer@example.invalid",
        "PII-OAUTH-TOKEN",
    ):
        assert forbidden not in serialized_shipment
    BSON.encode(shipment)


@pytest.mark.asyncio
async def test_shipment_receiver_address_drops_nested_string_values() -> None:
    db = FakeDb()
    persistence = SheetsEventPersistence(db=db, clock=lambda: NOW)

    await persistence.persist(
        event_type="shipments.updated",
        seller_id=82453304,
        resource={
            "id": 3001,
            "order_id": 2001,
            "status": "ready_to_ship",
            "logistic_type": "fulfillment",
            "date_created": "2026-05-29T10:00:00+00:00",
            "last_updated": "2026-05-30T11:00:00+00:00",
            "receiver_address": {
                "receiver_name": {"raw": "PII-NESTED-NAME"},
                "street_name": ["PII-NESTED-STREET"],
                "street_number": {"raw": "PII-NESTED-NUMBER"},
                "neighborhood": {"name": ["PII-NESTED-NEIGHBORHOOD"]},
                "zip_code": {"raw": "PII-NESTED-ZIP"},
                "city": {"name": {"raw": "PII-NESTED-CITY"}},
                "state": {"name": " Safe State "},
                "country": {"id": "AR"},
            },
        },
    )

    shipment = db["shipments"].documents["3001"]
    assert shipment["receiver_address"] == {"state": "Safe State", "country": "AR"}
    serialized_shipment = repr(shipment)
    for forbidden in (
        "PII-NESTED-NAME",
        "PII-NESTED-STREET",
        "PII-NESTED-NUMBER",
        "PII-NESTED-NEIGHBORHOOD",
        "PII-NESTED-ZIP",
        "PII-NESTED-CITY",
    ):
        assert forbidden not in serialized_shipment


@pytest.mark.asyncio
async def test_shipment_receiver_address_uses_scalar_fallback_when_primary_name_is_nested() -> None:
    db = FakeDb()
    persistence = SheetsEventPersistence(db=db, clock=lambda: NOW)

    await persistence.persist(
        event_type="shipments.updated",
        seller_id=82453304,
        resource={
            "id": 3001,
            "order_id": 2001,
            "status": "ready_to_ship",
            "logistic_type": "fulfillment",
            "date_created": "2026-05-29T10:00:00+00:00",
            "last_updated": "2026-05-30T11:00:00+00:00",
            "receiver_address": {
                "receiver_name": {"raw": "PII-NESTED-NAME"},
                "name": " Safe Buyer ",
            },
        },
    )

    shipment = db["shipments"].documents["3001"]
    assert shipment["receiver_address"] == {"name": "Safe Buyer"}
    assert "PII-NESTED-NAME" not in repr(shipment)


@pytest.mark.asyncio
async def test_shipment_persistence_errors_do_not_leak_receiver_address_pii(
    caplog: pytest.LogCaptureFixture,
) -> None:
    db = FakeDb()
    persistence = SheetsEventPersistence(db=db, clock=lambda: NOW)
    caplog.set_level("DEBUG")
    resource = {
        "id": 3001,
        "order_id": 2001,
        "status": "invalid-status",
        "logistic_type": "fulfillment",
        "date_created": "2026-05-29T10:00:00+00:00",
        "last_updated": "2026-05-30T11:00:00+00:00",
        "receiver_address": {
            "receiver_name": "PII-SENTINEL-NAME",
            "street_name": "PII-SENTINEL-STREET",
            "phone": "+54-PII-PHONE",
            "email": "pii@example.invalid",
        },
    }

    with pytest.raises(ValueError) as exc_info:
        await persistence.persist(
            event_type="shipments.updated", seller_id=82453304, resource=resource
        )

    error_text = str(exc_info.value)
    assert "shipment resource failed validation" in error_text
    assert exc_info.value.args == ("shipment resource failed validation",)
    assert exc_info.value.__cause__ is None
    assert db["shipments"].replace_calls == []
    captured_logs = "\n".join(
        f"{record.getMessage()} {record.__dict__}" for record in caplog.records
    )
    for forbidden in (
        "PII-SENTINEL-NAME",
        "PII-SENTINEL-STREET",
        "+54-PII-PHONE",
        "pii@example.invalid",
    ):
        assert forbidden not in error_text
        assert forbidden not in captured_logs
