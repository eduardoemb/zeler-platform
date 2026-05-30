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
