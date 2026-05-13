from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from zeler_sheets.sheetseller_backfill import (
    BackfillSummary,
    build_arg_parser,
    build_formula_row_doc,
    build_sku_index_doc,
    extract_seller_sku,
    run_sheetseller_backfill,
)

NOW = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)


class FakeReplaceResult:
    matched_count = 1
    modified_count = 1
    upserted_id = None


class FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs
        self.sort_spec: list[tuple[str, int]] | None = None

    def sort(self, sort_spec: list[tuple[str, int]]) -> FakeCursor:
        self.sort_spec = sort_spec
        sorted_docs = list(self._docs)
        for key, direction in reversed(sort_spec):
            sorted_docs.sort(key=lambda doc: str(doc.get(key, "")), reverse=direction < 0)
        return FakeCursor(sorted_docs)

    async def to_list(self, length: int | None = None) -> list[dict[str, Any]]:
        if length is None:
            return [dict(doc) for doc in self._docs]
        return [dict(doc) for doc in self._docs[:length]]


class FakeCollection:
    def __init__(self, documents: list[dict[str, Any]] | None = None) -> None:
        self.documents: dict[str, dict[str, Any]] = {
            str(doc["_id"]): dict(doc) for doc in documents or []
        }
        self.find_filters: list[dict[str, Any]] = []
        self.replace_calls: list[tuple[dict[str, Any], dict[str, Any], bool]] = []
        self.last_cursor: FakeCursor | None = None

    def find(self, filter_spec: dict[str, Any]) -> FakeCursor:
        self.find_filters.append(dict(filter_spec))
        docs = [dict(doc) for doc in self.documents.values() if _matches(doc, filter_spec)]
        self.last_cursor = FakeCursor(docs)
        return self.last_cursor

    async def replace_one(
        self, filter_spec: dict[str, Any], replacement: dict[str, Any], *, upsert: bool = False
    ) -> FakeReplaceResult:
        self.replace_calls.append((dict(filter_spec), dict(replacement), upsert))
        if upsert is False:
            raise AssertionError("backfill writes must be idempotent upserts")
        doc_id = str(filter_spec["_id"])
        self.documents[doc_id] = dict(replacement)
        return FakeReplaceResult()


class FakeDb:
    def __init__(self, items: list[dict[str, Any]]) -> None:
        self.collections: dict[str, FakeCollection] = {"items": FakeCollection(items)}

    def __getitem__(self, name: str) -> FakeCollection:
        return self.collections.setdefault(name, FakeCollection())


def _matches(doc: dict[str, Any], filter_spec: dict[str, Any]) -> bool:
    return all(doc.get(key) == value for key, value in filter_spec.items())


def test_cli_requires_seller_id_and_defaults_to_dry_run() -> None:
    parser = build_arg_parser()

    args = parser.parse_args(["--seller-id", "82453304"])
    write_args = parser.parse_args(["--seller-id", "82453304", "--write"])

    assert args.seller_id == "82453304"
    assert args.dry_run is True
    assert write_args.dry_run is False
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_extract_seller_sku_supports_legacy_attribute_value_shapes() -> None:
    assert (
        extract_seller_sku({"attributes": [{"id": "SELLER_SKU", "value_name": " abc-123 "}]})
        == "abc-123"
    )
    assert (
        extract_seller_sku({"attributes": [{"id": "SELLER_SKU", "value": "sku-value"}]})
        == "sku-value"
    )
    assert (
        extract_seller_sku({"attributes": [{"id": "SELLER_SKU", "name": "sku-name"}]})
        == "sku-name"
    )
    assert extract_seller_sku({"attributes": [{"id": "BRAND", "value_name": "Zeler"}]}) is None
    assert extract_seller_sku({"attributes": [{"id": "SELLER_SKU", "value_name": "   "}]}) is None


def test_read_model_docs_use_deterministic_ids_and_map_safe_current_item_fields() -> None:
    item = _item_doc(
        "MLA1",
        attributes=[{"id": "SELLER_SKU", "value_name": " abc-123 "}],
        last_updated=NOW,
    )

    sku_index = build_sku_index_doc(item, seller_id="82453304")
    formula_row = build_formula_row_doc(item, seller_id="82453304")

    expected_id = "82453304:ABC-123:MLA1"
    assert sku_index == {
        "_id": expected_id,
        "seller_id": "82453304",
        "seller_nickname": None,
        "sku": "abc-123",
        "normalized_sku": "ABC-123",
        "item_id": "MLA1",
        "variation_id": None,
        "inventory_id": None,
        "updated_at": NOW,
        "schema_version": 1,
    }
    assert formula_row == {
        "_id": expected_id,
        "seller_id": "82453304",
        "seller_nickname": None,
        "sku": "abc-123",
        "normalized_sku": "ABC-123",
        "item_id": "MLA1",
        "variation_id": None,
        "inventory_id": None,
        "current": {
            "title": "Title MLA1",
            "status": "active",
            "available_quantity": 7,
            "base_price": Decimal("123.45"),
            "category_id": "MLA-CAT",
            "date_created": NOW,
            "updated_at": NOW,
            "permalink": None,
            "thumbnail": None,
            "catalog_product_id": None,
            "inventory_id": None,
        },
        "date_created": NOW,
        "updated_at": NOW,
        "schema_version": 1,
    }


@pytest.mark.asyncio
async def test_backfill_dry_run_reads_seller_items_and_reports_counts_without_writes() -> None:
    db = FakeDb(
        [
            _item_doc("MLA2", attributes=[{"id": "SELLER_SKU", "value": " sku 2 "}]),
            _item_doc("MLA1", attributes=[{"id": "SELLER_SKU", "value_name": "sku-1"}]),
            _item_doc("MLA3", attributes=[{"id": "BRAND", "value_name": "Zeler"}]),
            _item_doc("MLB1", seller_id="999", attributes=[{"id": "SELLER_SKU", "value": "other"}]),
        ]
    )

    summary = await run_sheetseller_backfill(db=db, seller_id="82453304")

    assert summary == BackfillSummary(
        seller_id="82453304",
        dry_run=True,
        items_read=3,
        items_with_sku=2,
        skipped_missing_sku=1,
        sku_index_upserts=2,
        formula_row_upserts=2,
    )
    assert db["items"].find_filters == [{"seller_id": "82453304"}]
    assert db["items"].last_cursor is not None
    assert db["items"].last_cursor.sort_spec == [("_id", 1)]
    assert db["sheets_item_sku_index"].documents == {}
    assert db["sheets_item_formula_rows"].documents == {}
    assert db["sheets_item_sku_index"].replace_calls == []
    assert db["sheets_item_formula_rows"].replace_calls == []


@pytest.mark.asyncio
async def test_backfill_write_mode_upserts_both_read_models_and_is_idempotent() -> None:
    db = FakeDb(
        [
            _item_doc("MLA2", attributes=[{"id": "SELLER_SKU", "value": " sku 2 "}]),
            _item_doc("MLA1", attributes=[{"id": "SELLER_SKU", "value_name": "sku-1"}]),
            _item_doc("MLA3", attributes=[{"id": "SELLER_SKU", "name": ""}]),
        ]
    )

    first = await run_sheetseller_backfill(db=db, seller_id="82453304", dry_run=False)
    second = await run_sheetseller_backfill(db=db, seller_id="82453304", dry_run=False)

    assert first == BackfillSummary(
        seller_id="82453304",
        dry_run=False,
        items_read=3,
        items_with_sku=2,
        skipped_missing_sku=1,
        sku_index_upserts=2,
        formula_row_upserts=2,
    )
    assert second == first
    assert sorted(db["sheets_item_sku_index"].documents) == [
        "82453304:SKU 2:MLA2",
        "82453304:SKU-1:MLA1",
    ]
    assert sorted(db["sheets_item_formula_rows"].documents) == [
        "82453304:SKU 2:MLA2",
        "82453304:SKU-1:MLA1",
    ]
    assert len(db["sheets_item_sku_index"].replace_calls) == 4
    assert len(db["sheets_item_formula_rows"].replace_calls) == 4
    assert all(call[2] is True for call in db["sheets_item_sku_index"].replace_calls)
    assert all(
        call[0] == {"_id": call[1]["_id"]}
        for call in db["sheets_item_formula_rows"].replace_calls
    )


def _item_doc(
    item_id: str,
    *,
    seller_id: str = "82453304",
    attributes: list[dict[str, Any]] | None = None,
    last_updated: datetime | None = None,
) -> dict[str, Any]:
    return {
        "_id": item_id,
        "seller_id": seller_id,
        "title": f"Title {item_id}",
        "status": "active",
        "available_quantity": 7,
        "base_price": Decimal("123.45"),
        "category_id": "MLA-CAT",
        "date_created": NOW,
        "last_updated": last_updated or NOW,
        "attributes": attributes or [],
        "schema_version": 1,
    }
