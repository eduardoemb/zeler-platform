from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from bson.decimal128 import Decimal128

from zeler_platform_core.models import Order
from zeler_sheets.sheetseller_backfill import (
    BackfillSummary,
    ItemDetailEnrichmentSummary,
    OrderIdentityRepairSummary,
    OrderLineIdentityBackfillSummary,
    OrderNormalizationSummary,
    build_arg_parser,
    build_formula_row_doc,
    build_sku_index_doc,
    build_sku_index_docs,
    extract_safe_order_item_identity,
    extract_seller_sku,
    merge_order_items_identity,
    run_item_detail_enrichment,
    run_order_identity_repair,
    run_order_line_identity_backfill,
    run_order_normalization,
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
        self.update_calls: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
        self.last_cursor: FakeCursor | None = None

    def find(self, filter_spec: dict[str, Any]) -> FakeCursor:
        self.find_filters.append(dict(filter_spec))
        docs = [dict(doc) for doc in self.documents.values() if _matches(doc, filter_spec)]
        self.last_cursor = FakeCursor(docs)
        return self.last_cursor

    async def find_one(self, filter_spec: dict[str, Any]) -> dict[str, Any] | None:
        self.find_filters.append(dict(filter_spec))
        for doc in self.documents.values():
            if _matches(doc, filter_spec):
                return dict(doc)
        return None

    async def replace_one(
        self, filter_spec: dict[str, Any], replacement: dict[str, Any], *, upsert: bool = False
    ) -> FakeReplaceResult:
        self.replace_calls.append((dict(filter_spec), dict(replacement), upsert))
        if upsert is False:
            raise AssertionError("backfill writes must be idempotent upserts")
        doc_id = str(filter_spec["_id"])
        self.documents[doc_id] = dict(replacement)
        return FakeReplaceResult()

    async def update_one(
        self,
        filter_spec: dict[str, Any],
        update: dict[str, Any],
        *,
        upsert: bool = False,
        bypass_document_validation: bool = False,
    ) -> FakeReplaceResult:
        self.update_calls.append(
            (
                dict(filter_spec),
                dict(update),
                {"upsert": upsert, "bypass_document_validation": bypass_document_validation},
            )
        )
        if upsert is not False:
            raise AssertionError("order repair must update existing canonical orders only")
        doc_id = str(filter_spec["_id"])
        current = dict(self.documents[doc_id])
        for path, value in update.get("$set", {}).items():
            _set_path(current, path, value)
        self.documents[doc_id] = current
        return FakeReplaceResult()


class FakeDb:
    def __init__(
        self, items: list[dict[str, Any]], orders: list[dict[str, Any]] | None = None
    ) -> None:
        self.collections: dict[str, FakeCollection] = {"items": FakeCollection(items)}
        if orders is not None:
            self.collections["orders"] = FakeCollection(orders)

    def __getitem__(self, name: str) -> FakeCollection:
        return self.collections.setdefault(name, FakeCollection())


def _matches(doc: dict[str, Any], filter_spec: dict[str, Any]) -> bool:
    for key, value in filter_spec.items():
        if key == "$or" and isinstance(value, list):
            if not any(_matches(doc, option) for option in value):
                return False
            continue
        actual = doc.get(key)
        if isinstance(value, dict):
            if "$gte" in value and not _safe_gte(actual, value["$gte"]):
                return False
            if "$lt" in value and not _safe_lt(actual, value["$lt"]):
                return False
            continue
        if actual != value:
            return False
    return True


def _safe_gte(actual: Any, expected: Any) -> bool:
    try:
        return bool(actual >= expected)
    except TypeError:
        return False


def _safe_lt(actual: Any, expected: Any) -> bool:
    try:
        return bool(actual < expected)
    except TypeError:
        return False


def _set_path(document: dict[str, Any], dotted_path: str, value: Any) -> None:
    target: Any = document
    parts = dotted_path.split(".")
    for part in parts[:-1]:
        target = target[int(part)] if isinstance(target, list) else target[part]
    leaf = parts[-1]
    if isinstance(target, list):
        target[int(leaf)] = value
    else:
        target[leaf] = value


class FakeGateway:
    def __init__(self, payloads: dict[str, dict[str, Any] | Exception]) -> None:
        self.payloads = payloads
        self.calls: list[tuple[str, str]] = []

    async def fetch_resource(self, *, seller_id: str, path: str) -> dict[str, Any]:
        self.calls.append((seller_id, path))
        payload = self.payloads[path]
        if isinstance(payload, Exception):
            raise payload
        return payload


class FakeItemGateway:
    def __init__(self, payloads: dict[str, Any | Exception]) -> None:
        self.payloads = payloads
        self.calls: list[tuple[str, str]] = []

    async def fetch_resource(self, *, seller_id: str, path: str) -> Any:
        self.calls.append((seller_id, path))
        payload = self.payloads[path]
        if isinstance(payload, Exception):
            raise payload
        return payload


def test_cli_requires_seller_id_and_defaults_to_dry_run() -> None:
    parser = build_arg_parser()

    args = parser.parse_args(["--seller-id", "82453304"])
    write_args = parser.parse_args(["--seller-id", "82453304", "--write"])
    repair_args = parser.parse_args(
        [
            "--seller-id",
            "82453304",
            "--source",
            "orders-repair",
            "--date-from",
            "2025-04-30",
            "--date-to",
            "2025-05-01",
        ]
    )
    normalize_args = parser.parse_args(
        [
            "--seller-id",
            "82453304",
            "--source",
            "orders-normalize",
            "--date-from",
            "2025-04-30",
            "--date-to",
            "2025-05-01",
        ]
    )

    assert args.seller_id == "82453304"
    assert args.dry_run is True
    assert write_args.dry_run is False
    assert repair_args.source == "orders-repair"
    assert repair_args.date_from == "2025-04-30"
    assert repair_args.date_to == "2025-05-01"
    assert normalize_args.source == "orders-normalize"
    assert normalize_args.dry_run is True
    enrich_args = parser.parse_args(["--seller-id", "82453304", "--source", "items-enrich"])
    assert enrich_args.source == "items-enrich"
    assert enrich_args.dry_run is True
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
        extract_seller_sku({"attributes": [{"id": "SELLER_SKU", "name": "sku-name"}]}) == "sku-name"
    )
    assert extract_seller_sku({"attributes": [{"id": "BRAND", "value_name": "Zeler"}]}) is None
    assert extract_seller_sku({"attributes": [{"id": "SELLER_SKU", "value_name": "   "}]}) is None


def test_read_model_docs_use_deterministic_ids_and_map_safe_current_item_fields() -> None:
    item = _item_doc(
        "MLA1",
        attributes=[{"id": "SELLER_SKU", "value_name": " abc-123 "}],
        permalink="https://articulo.example/MLA1",
        thumbnail="https://img.example/MLA1.jpg",
        catalog_product_id="MLA-CATALOG-1",
        inventory_id="ITEM-INV-1",
        last_updated=NOW,
    )

    sku_index = build_sku_index_doc(item, seller_id="82453304")
    formula_row = build_formula_row_doc(item, seller_id="82453304")

    expected_sku_index_id = "82453304:ABC-123:MLA1:item"
    expected_formula_row_id = "82453304:ABC-123:MLA1"
    assert sku_index == {
        "_id": expected_sku_index_id,
        "seller_id": "82453304",
        "seller_nickname": None,
        "sku": "abc-123",
        "normalized_sku": "ABC-123",
        "item_id": "MLA1",
        "variation_id": None,
        "identity_level": "item",
        "source": "item_attribute",
        "inventory_id": "ITEM-INV-1",
        "updated_at": NOW,
        "schema_version": 2,
    }
    assert formula_row == {
        "_id": expected_formula_row_id,
        "seller_id": "82453304",
        "seller_nickname": None,
        "sku": "abc-123",
        "normalized_sku": "ABC-123",
        "item_id": "MLA1",
        "variation_id": None,
        "inventory_id": "ITEM-INV-1",
        "current": {
            "title": "Title MLA1",
            "status": "active",
            "available_quantity": 7,
            "base_price": Decimal128("123.45"),
            "category_id": "MLA-CAT",
            "date_created": NOW,
            "updated_at": NOW,
            "permalink": "https://articulo.example/MLA1",
            "thumbnail": "https://img.example/MLA1.jpg",
            "catalog_product_id": "MLA-CATALOG-1",
            "inventory_id": "ITEM-INV-1",
        },
        "date_created": NOW,
        "updated_at": NOW,
        "schema_version": 2,
    }


def test_formula_row_coerces_legacy_string_prices_to_schema_safe_decimals() -> None:
    item = _item_doc("MLA1", attributes=[{"id": "SELLER_SKU", "value_name": "abc-123"}])
    item["price"] = "1499.90"
    item["base_price"] = "1234.56"

    formula_row = build_formula_row_doc(item, seller_id="82453304")

    current = formula_row["current"]
    assert isinstance(current["price"], Decimal128)
    assert isinstance(current["base_price"], Decimal128)
    assert current["price"].to_decimal() == Decimal("1499.90")
    assert current["base_price"].to_decimal() == Decimal("1234.56")


def test_formula_row_coerces_unparseable_legacy_prices_to_none() -> None:
    item = _item_doc("MLA1", attributes=[{"id": "SELLER_SKU", "value_name": "abc-123"}])
    item["price"] = "not-a-number"
    item["base_price"] = "NaN"

    formula_row = build_formula_row_doc(item, seller_id="82453304")

    assert formula_row["current"]["price"] is None
    assert formula_row["current"]["base_price"] is None


def test_formula_row_preserves_blank_enrichment_fields_when_source_is_absent() -> None:
    item = _item_doc("MLA1", attributes=[{"id": "SELLER_SKU", "value_name": "abc-123"}])

    formula_row = build_formula_row_doc(item, seller_id="82453304")

    assert formula_row["inventory_id"] is None
    assert formula_row["current"]["permalink"] is None
    assert formula_row["current"]["thumbnail"] is None
    assert formula_row["current"]["catalog_product_id"] is None
    assert formula_row["current"]["inventory_id"] is None


def test_variation_sku_index_docs_use_stable_v2_ids_and_sources() -> None:
    item = _item_doc(
        "MLA1",
        variations=[
            {
                "id": 101,
                "seller_custom_field": " custom-101 ",
                "inventory_id": "INV-101",
            }
        ],
    )

    docs = build_sku_index_docs(item, seller_id="82453304")

    assert docs == [
        {
            "_id": "82453304:CUSTOM-101:MLA1:101",
            "seller_id": "82453304",
            "seller_nickname": None,
            "sku": "custom-101",
            "normalized_sku": "CUSTOM-101",
            "item_id": "MLA1",
            "variation_id": "101",
            "identity_level": "variation",
            "source": "variation_seller_custom_field",
            "inventory_id": "INV-101",
            "updated_at": NOW,
            "schema_version": 2,
        }
    ]


@pytest.mark.asyncio
async def test_backfill_builds_enriched_formula_rows_from_deterministic_sources() -> None:
    db = FakeDb(
        [
            _item_doc(
                "MLA1",
                attributes=[{"id": "SELLER_SKU", "value_name": "item-sku"}],
                permalink="https://articulo.example/MLA1",
                thumbnail="https://img.example/MLA1.jpg",
                catalog_product_id="MLA-CATALOG-1",
                inventory_id="ITEM-INV-1",
                variations=[
                    {"id": 101, "seller_custom_field": "var-101", "inventory_id": "VAR-INV-101"},
                    {"id": 102, "seller_custom_field": "var-102"},
                ],
            )
        ]
    )

    summary = await run_sheetseller_backfill(db=db, seller_id="82453304", dry_run=False)

    assert summary.planned == 2
    assert summary.updated == 2
    assert summary.unchanged == 0
    assert summary.skipped_missing_source == 1
    assert summary.skipped_ambiguous == 0
    assert summary.errors == 0
    assert summary.formula_rows_with_permalink == 2
    assert summary.formula_rows_with_thumbnail == 2
    assert summary.formula_rows_with_catalog_product_id == 2
    assert summary.formula_rows_with_inventory_id == 2
    assert sorted(db["sheets_item_formula_rows"].documents) == [
        "82453304:ITEM-SKU:MLA1",
        "82453304:VAR-101:MLA1:101",
    ]
    variation_row = db["sheets_item_formula_rows"].documents["82453304:VAR-101:MLA1:101"]
    assert variation_row["variation_id"] == "101"
    assert variation_row["inventory_id"] == "VAR-INV-101"
    assert variation_row["current"]["inventory_id"] == "VAR-INV-101"
    assert variation_row["current"]["permalink"] == "https://articulo.example/MLA1"


@pytest.mark.asyncio
async def test_backfill_builds_formula_rows_for_order_line_sku_identities() -> None:
    db = FakeDb(
        [
            _item_doc(
                "MLM2169717119",
                permalink="https://articulo.example/MLM2169717119",
                thumbnail="https://img.example/MLM2169717119.jpg",
                catalog_product_id="MLM-CATALOG-1",
            )
        ]
    )
    db["sheets_item_sku_index"].documents["82453304:DEP-04-153-REM:MLM2169717119:182028311662"] = {
        "_id": "82453304:DEP-04-153-REM:MLM2169717119:182028311662",
        "seller_id": "82453304",
        "seller_nickname": None,
        "sku": "DEP-04-153-REM",
        "normalized_sku": "DEP-04-153-REM",
        "item_id": "MLM2169717119",
        "variation_id": "182028311662",
        "identity_level": "variation",
        "source": "order_line",
        "inventory_id": None,
        "updated_at": NOW,
        "schema_version": 1,
    }

    summary = await run_sheetseller_backfill(db=db, seller_id="82453304", dry_run=False)

    assert summary.items_read == 1
    assert summary.items_with_sku == 0
    assert summary.skipped_missing_sku == 1
    assert summary.sku_index_upserts == 0
    assert summary.formula_row_upserts == 1
    assert summary.planned == 1
    assert summary.updated == 1
    row = db["sheets_item_formula_rows"].documents[
        "82453304:DEP-04-153-REM:MLM2169717119:182028311662"
    ]
    assert row["sku"] == "DEP-04-153-REM"
    assert row["item_id"] == "MLM2169717119"
    assert row["variation_id"] == "182028311662"
    assert row["inventory_id"] is None
    assert row["current"]["title"] == "Title MLM2169717119"
    assert row["current"]["permalink"] == "https://articulo.example/MLM2169717119"
    assert db["sheets_item_sku_index"].find_filters == [
        {"seller_id": "82453304", "source": "order_line"}
    ]


@pytest.mark.asyncio
async def test_backfill_prefers_enriched_formula_rows_over_order_line_duplicates() -> None:
    db = FakeDb(
        [
            _item_doc(
                "MLA1",
                variations=[
                    {"id": 101, "seller_custom_field": "sku-1", "inventory_id": "VAR-INV-101"}
                ],
                permalink="https://articulo.example/MLA1",
                thumbnail="https://img.example/MLA1.jpg",
                catalog_product_id="MLA-CATALOG-1",
            )
        ]
    )
    db["sheets_item_sku_index"].documents["82453304:SKU-1:MLA1:101"] = {
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
        "updated_at": NOW,
        "schema_version": 1,
    }

    await run_sheetseller_backfill(db=db, seller_id="82453304", dry_run=False)

    row = db["sheets_item_formula_rows"].documents["82453304:SKU-1:MLA1:101"]
    assert row["inventory_id"] == "VAR-INV-101"
    assert row["current"]["inventory_id"] == "VAR-INV-101"


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
        variation_sku_rows=0,
        skipped_missing_variation_sku=0,
        skipped_ambiguous_sku=0,
        planned=2,
        updated=0,
        unchanged=0,
        skipped_missing_source=2,
        skipped_ambiguous=0,
        errors=0,
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
        variation_sku_rows=0,
        skipped_missing_variation_sku=0,
        skipped_ambiguous_sku=0,
        planned=2,
        updated=2,
        unchanged=0,
        skipped_missing_source=2,
        skipped_ambiguous=0,
        errors=0,
    )
    assert second == BackfillSummary(
        seller_id="82453304",
        dry_run=False,
        items_read=3,
        items_with_sku=2,
        skipped_missing_sku=1,
        sku_index_upserts=2,
        formula_row_upserts=2,
        variation_sku_rows=0,
        skipped_missing_variation_sku=0,
        skipped_ambiguous_sku=0,
        planned=0,
        updated=0,
        unchanged=2,
        skipped_missing_source=2,
        skipped_ambiguous=0,
        errors=0,
    )
    assert sorted(db["sheets_item_sku_index"].documents) == [
        "82453304:SKU 2:MLA2:item",
        "82453304:SKU-1:MLA1:item",
    ]
    assert sorted(db["sheets_item_formula_rows"].documents) == [
        "82453304:SKU 2:MLA2",
        "82453304:SKU-1:MLA1",
    ]
    assert len(db["sheets_item_sku_index"].replace_calls) == 4
    assert len(db["sheets_item_formula_rows"].replace_calls) == 2
    assert all(call[2] is True for call in db["sheets_item_sku_index"].replace_calls)
    assert all(
        call[0] == {"_id": call[1]["_id"]} for call in db["sheets_item_formula_rows"].replace_calls
    )


@pytest.mark.asyncio
async def test_backfill_counts_bson_equivalent_formula_rows_as_unchanged() -> None:
    item_with_bson_price = _item_doc(
        "MLA1",
        attributes=[{"id": "SELLER_SKU", "value_name": "sku-1"}],
        last_updated=NOW,
    )
    item_with_bson_price["price"] = 1499
    item_with_bson_price["date_created"] = "2026-05-13T12:00:00+00:00"
    item_with_decimal_base_price = _item_doc(
        "MLA2",
        attributes=[{"id": "SELLER_SKU", "value_name": "sku-2"}],
        last_updated=NOW,
    )
    db = FakeDb([item_with_bson_price, item_with_decimal_base_price])

    persisted_price_row = build_formula_row_doc(item_with_bson_price, seller_id="82453304")
    persisted_price_row = deepcopy(persisted_price_row)
    persisted_price_row["date_created"] = NOW
    persisted_price_row["current"]["date_created"] = NOW
    persisted_price_row["current"]["price"] = Decimal128("1499")
    persisted_base_price_row = build_formula_row_doc(
        item_with_decimal_base_price, seller_id="82453304"
    )
    persisted_base_price_row = deepcopy(persisted_base_price_row)
    persisted_base_price_row["current"]["base_price"] = Decimal("123.45")
    formula_rows = db["sheets_item_formula_rows"]
    formula_rows.documents[str(persisted_price_row["_id"])] = persisted_price_row
    formula_rows.documents[str(persisted_base_price_row["_id"])] = persisted_base_price_row

    summary = await run_sheetseller_backfill(db=db, seller_id="82453304", dry_run=True)

    assert summary.planned == 0
    assert summary.updated == 0
    assert summary.unchanged == 2
    assert formula_rows.replace_calls == []


@pytest.mark.asyncio
async def test_backfill_writes_item_and_variation_identity_rows_idempotently() -> None:
    db = FakeDb(
        [
            _item_doc(
                "MLA1",
                attributes=[{"id": "SELLER_SKU", "value_name": "item-sku"}],
                variations=[
                    {"id": 101, "attributes": [{"id": "SELLER_SKU", "value_name": "var-101"}]},
                    {"id": 102, "seller_custom_field": "var-102"},
                    {"id": 103, "attributes": [{"id": "BRAND", "value_name": "Zeler"}]},
                ],
            )
        ]
    )

    first = await run_sheetseller_backfill(db=db, seller_id="82453304", dry_run=False)
    second = await run_sheetseller_backfill(db=db, seller_id="82453304", dry_run=False)

    assert first == BackfillSummary(
        seller_id="82453304",
        dry_run=False,
        items_read=1,
        items_with_sku=1,
        skipped_missing_sku=0,
        sku_index_upserts=3,
        formula_row_upserts=1,
        variation_sku_rows=2,
        skipped_missing_variation_sku=1,
        skipped_ambiguous_sku=0,
        planned=1,
        updated=1,
        unchanged=0,
        skipped_missing_source=3,
        skipped_ambiguous=0,
        errors=0,
    )
    assert second.updated == 0
    assert second.unchanged == 1
    assert sorted(db["sheets_item_sku_index"].documents) == [
        "82453304:ITEM-SKU:MLA1:item",
        "82453304:VAR-101:MLA1:101",
        "82453304:VAR-102:MLA1:102",
    ]
    assert len(db["sheets_item_sku_index"].replace_calls) == 6


@pytest.mark.asyncio
async def test_backfill_dry_run_counts_variations_without_writing() -> None:
    db = FakeDb(
        [
            _item_doc(
                "MLA1",
                variations=[
                    {"id": 101, "seller_custom_field": "var-101"},
                    {"id": 102},
                ],
            )
        ]
    )

    summary = await run_sheetseller_backfill(db=db, seller_id="82453304", dry_run=True)

    assert summary.sku_index_upserts == 1
    assert summary.formula_row_upserts == 0
    assert summary.planned == 0
    assert summary.variation_sku_rows == 1
    assert summary.skipped_missing_sku == 1
    assert summary.skipped_missing_variation_sku == 1
    assert db["sheets_item_sku_index"].documents == {}


@pytest.mark.asyncio
async def test_item_detail_enrichment_fetches_canonical_ids_and_writes_formula_fields() -> None:
    canonical = _item_doc("MLA1", attributes=[{"id": "SELLER_SKU", "value_name": "sku-1"}])
    canonical["price"] = Decimal("123.45")
    db = FakeDb([canonical, _item_doc("MLB1", seller_id="999")])
    gateway = FakeItemGateway(
        {
            "/items?ids=MLA1": [
                {
                    "code": 200,
                    "body": {
                        "id": "MLA1",
                        "seller_id": 82453304,
                        "title": "Updated title",
                        "price": "222.20",
                        "base_price": "210.00",
                        "available_quantity": 9,
                        "status": "active",
                        "category_id": "MLA-CAT-UPDATED",
                        "permalink": "https://articulo.example/MLA1",
                        "thumbnail": "https://img.example/MLA1.jpg",
                        "catalog_product_id": "MLA-CATALOG-1",
                        "inventory_id": "INV-ITEM-1",
                        "variations": [{"id": 101, "inventory_id": "INV-VAR-101"}],
                        "attributes": [{"id": "SELLER_SKU", "value_name": "sku-1"}],
                        "date_created": NOW.isoformat(),
                        "last_updated": NOW.isoformat(),
                        "unexpected_raw_payload": {"secret": "must-not-persist"},
                    },
                }
            ]
        }
    )

    summary = await run_item_detail_enrichment(
        db=db, gateway=gateway, seller_id="82453304", dry_run=False
    )

    assert summary == ItemDetailEnrichmentSummary(
        dry_run=False,
        items_read=1,
        batches_fetched=1,
        item_details_returned=1,
        items_validated=1,
        items_planned=1,
        items_updated=1,
        unchanged=0,
    )
    assert gateway.calls == [("82453304", "/items?ids=MLA1")]
    assert db["items"].find_filters == [{"seller_id": "82453304"}]
    assert len(db["items"].update_calls) == 1
    filter_spec, update, options = db["items"].update_calls[0]
    assert filter_spec == {"_id": "MLA1", "seller_id": "82453304"}
    assert options == {"upsert": False, "bypass_document_validation": False}
    set_fields = update["$set"]
    assert isinstance(set_fields["last_meli_sync_at"], datetime)
    assert set_fields["last_meli_sync_at"].tzinfo is UTC
    without_sync_time = {
        key: value for key, value in set_fields.items() if key != "last_meli_sync_at"
    }
    price = without_sync_time.pop("price")
    base_price = without_sync_time.pop("base_price")
    assert isinstance(price, Decimal128)
    assert isinstance(base_price, Decimal128)
    assert price.to_decimal() == Decimal("222.20")
    assert base_price.to_decimal() == Decimal("210.00")
    assert without_sync_time == {
        "_id": "MLA1",
        "seller_id": "82453304",
        "title": "Updated title",
        "available_quantity": 9,
        "status": "active",
        "category_id": "MLA-CAT-UPDATED",
        "permalink": "https://articulo.example/MLA1",
        "thumbnail": "https://img.example/MLA1.jpg",
        "catalog_product_id": "MLA-CATALOG-1",
        "inventory_id": "INV-ITEM-1",
        "variations": [{"id": 101, "inventory_id": "INV-VAR-101"}],
        "attributes": [{"id": "SELLER_SKU", "value_name": "sku-1"}],
        "shipping": None,
        "health": None,
        "date_created": NOW,
        "last_updated": NOW,
        "schema_version": 2,
    }
    stored = db["items"].documents["MLA1"]
    assert stored["permalink"] == "https://articulo.example/MLA1"
    assert stored["thumbnail"] == "https://img.example/MLA1.jpg"
    assert stored["catalog_product_id"] == "MLA-CATALOG-1"
    assert stored["inventory_id"] == "INV-ITEM-1"
    assert stored["schema_version"] == 2


@pytest.mark.asyncio
async def test_item_detail_enrichment_writes_mongo_schema_safe_date_and_price_types() -> None:
    canonical = _item_doc("MLA1")
    canonical["price"] = Decimal("111.11")
    db = FakeDb([canonical])
    detail = _item_detail("MLA1")
    detail["price"] = "222.20"
    detail["base_price"] = "210.00"
    detail["date_created"] = NOW.isoformat()
    detail["last_updated"] = NOW.isoformat()
    gateway = FakeItemGateway({"/items?ids=MLA1": [{"code": 200, "body": detail}]})

    await run_item_detail_enrichment(db=db, gateway=gateway, seller_id="82453304", dry_run=False)

    _, update, options = db["items"].update_calls[0]
    set_fields = update["$set"]
    assert options == {"upsert": False, "bypass_document_validation": False}
    assert isinstance(set_fields["last_meli_sync_at"], datetime)
    assert set_fields["last_meli_sync_at"].tzinfo is UTC
    assert set_fields["date_created"] == NOW
    assert set_fields["last_updated"] == NOW
    assert isinstance(set_fields["price"], Decimal128)
    assert isinstance(set_fields["base_price"], Decimal128)
    assert set_fields["price"].to_decimal() == Decimal("222.20")
    assert set_fields["base_price"].to_decimal() == Decimal("210.00")


@pytest.mark.asyncio
async def test_item_detail_enrichment_dry_run_reports_plan_without_writes() -> None:
    canonical = _item_doc("MLA1")
    canonical["price"] = Decimal("123.45")
    db = FakeDb([canonical])
    gateway = FakeItemGateway({"/items?ids=MLA1": [{"code": 200, "body": _item_detail("MLA1")}]})

    summary = await run_item_detail_enrichment(db=db, gateway=gateway, seller_id="82453304")

    assert summary.items_planned == 1
    assert summary.items_updated == 0
    assert db["items"].update_calls == []
    assert db["items"].documents["MLA1"].get("permalink") is None


@pytest.mark.asyncio
async def test_item_detail_enrichment_api_failure_writes_nothing_for_any_batch() -> None:
    first = _item_doc("MLA1")
    first["price"] = Decimal("123.45")
    second = _item_doc("MLA2")
    second["price"] = Decimal("123.45")
    db = FakeDb([first, second])
    gateway = FakeItemGateway(
        {
            "/items?ids=MLA1": [{"code": 200, "body": _item_detail("MLA1")}],
            "/items?ids=MLA2": RuntimeError("gateway failure"),
        }
    )

    with pytest.raises(RuntimeError, match="gateway failure"):
        await run_item_detail_enrichment(
            db=db, gateway=gateway, seller_id="82453304", dry_run=False, batch_size=1
        )

    assert db["items"].update_calls == []
    assert db["items"].documents["MLA1"].get("permalink") is None


@pytest.mark.asyncio
async def test_item_detail_enrichment_persists_only_canonical_item_fields() -> None:
    canonical = _item_doc("MLA1")
    canonical["price"] = Decimal("123.45")
    db = FakeDb([canonical])
    raw_detail = _item_detail("MLA1")
    raw_detail.update(
        {
            "buyer": {"id": "pii"},
            "seller_address": {"address_line": "private"},
            "raw_payload": {"anything": "must-not-persist"},
        }
    )
    gateway = FakeItemGateway({"/items?ids=MLA1": [{"code": 200, "body": raw_detail}]})

    summary = await run_item_detail_enrichment(
        db=db, gateway=gateway, seller_id="82453304", dry_run=False
    )

    assert summary.items_updated == 1
    stored = db["items"].documents["MLA1"]
    assert "buyer" not in stored
    assert "seller_address" not in stored
    assert "raw_payload" not in stored


@pytest.mark.asyncio
async def test_item_detail_enrichment_summary_is_sanitized_and_useful() -> None:
    current = _item_doc("MLA1", permalink="https://articulo.example/MLA1")
    current["price"] = Decimal("123.45")
    db = FakeDb([current])
    detail = _item_detail("MLA1")
    detail["permalink"] = "https://articulo.example/MLA1"
    gateway = FakeItemGateway({"/items?ids=MLA1": [{"code": 200, "body": detail}]})

    summary = await run_item_detail_enrichment(
        db=db, gateway=gateway, seller_id="82453304", dry_run=False
    )

    assert summary.items_read == 1
    assert summary.items_validated == 1
    assert summary.unchanged == 0
    serialized = summary.as_dict()
    assert serialized == {
        "dry_run": False,
        "items_read": 1,
        "batches_fetched": 1,
        "item_details_returned": 1,
        "items_validated": 1,
        "items_planned": 1,
        "items_updated": 1,
        "unchanged": 0,
    }
    assert "82453304" not in str(serialized)
    assert "MLA1" not in str(serialized)
    assert "https://" not in str(serialized)


@pytest.mark.asyncio
async def test_order_line_identity_dry_run_reports_sanitized_counts_without_writes() -> None:
    db = FakeDb(
        [],
        orders=[
            _order_doc(
                "order-1",
                items=[
                    {
                        "item_id": "MLA1",
                        "variation_id": 101,
                        "seller_custom_field": " var-101 ",
                    },
                    {
                        "item": {"id": "MLA1", "variation_id": "102", "seller_sku": "var-102"},
                    },
                    {"item_id": "MLA2", "seller_sku": "item-sku"},
                    {"item_id": "MLA2", "seller_custom_field": "other-sku"},
                    {"item_id": "MLA3", "variation_id": 303},
                ],
            ),
            _order_doc(
                "order-other-seller",
                seller_id="999",
                items=[{"item_id": "MLB1", "seller_sku": "wrong-tenant"}],
            ),
        ],
    )

    summary = await run_order_line_identity_backfill(db=db, seller_id="82453304", dry_run=True)

    assert summary == OrderLineIdentityBackfillSummary(
        seller_id="82453304",
        dry_run=True,
        orders_read=1,
        order_lines_read=5,
        order_lines_with_direct_sku=4,
        order_lines_with_variation_id=3,
        deterministic_pairs=2,
        ambiguous_pairs=1,
        sku_index_upserts=2,
    )
    assert db["orders"].find_filters == [{"seller_id": "82453304"}]
    assert db["sheets_item_sku_index"].documents == {}
    assert db["sheets_item_sku_index"].replace_calls == []


@pytest.mark.asyncio
async def test_order_line_identity_skips_cancelled_orders() -> None:
    cancelled_order = _order_doc(
        "cancelled-order",
        items=[{"item_id": "MLM3484876282", "seller_sku": "HER-05-145"}],
    )
    cancelled_order["status"] = "cancelled"
    db = FakeDb(
        [],
        orders=[
            cancelled_order,
            _order_doc(
                "paid-order",
                items=[{"item_id": "MLA1", "seller_sku": "active-sku"}],
            ),
        ],
    )

    summary = await run_order_line_identity_backfill(db=db, seller_id="82453304", dry_run=False)

    assert summary.orders_read == 2
    assert summary.order_lines_read == 1
    assert summary.order_lines_with_direct_sku == 1
    assert summary.deterministic_pairs == 1
    assert sorted(db["sheets_item_sku_index"].documents) == ["82453304:ACTIVE-SKU:MLA1:item"]


@pytest.mark.asyncio
async def test_order_line_identity_write_is_idempotent_and_skips_ambiguous_pairs() -> None:
    db = FakeDb(
        [],
        orders=[
            _order_doc(
                "order-1",
                items=[
                    {
                        "item_id": "MLA1",
                        "variation_id": 101,
                        "seller_custom_field": " var-101 ",
                    },
                    {
                        "item_id": "MLA1",
                        "variation_id": "101",
                        "seller_sku": "VAR-101",
                    },
                    {"item_id": "MLA2", "seller_sku": "amb-1"},
                    {"item_id": "MLA2", "seller_custom_field": "amb-2"},
                ],
            )
        ],
    )

    first = await run_order_line_identity_backfill(db=db, seller_id="82453304", dry_run=False)
    second = await run_order_line_identity_backfill(db=db, seller_id="82453304", dry_run=False)

    assert first == OrderLineIdentityBackfillSummary(
        seller_id="82453304",
        dry_run=False,
        orders_read=1,
        order_lines_read=4,
        order_lines_with_direct_sku=4,
        order_lines_with_variation_id=2,
        deterministic_pairs=1,
        ambiguous_pairs=1,
        sku_index_upserts=1,
    )
    assert second == first
    assert db["sheets_item_sku_index"].documents == {
        "82453304:VAR-101:MLA1:101": {
            "_id": "82453304:VAR-101:MLA1:101",
            "seller_id": "82453304",
            "seller_nickname": None,
            "sku": "var-101",
            "normalized_sku": "VAR-101",
            "item_id": "MLA1",
            "variation_id": "101",
            "identity_level": "variation",
            "source": "order_line",
            "inventory_id": None,
            "updated_at": NOW,
            "schema_version": 2,
        }
    }
    assert len(db["sheets_item_sku_index"].replace_calls) == 2
    assert db["sheets_item_sku_index"].replace_calls[0][2] is True


@pytest.mark.asyncio
async def test_order_line_identity_write_coerces_canonical_iso_updated_at() -> None:
    db = FakeDb(
        [],
        orders=[
            _order_doc(
                "order-1",
                date_created="2025-04-30T00:51:07-04:00",
                items=[
                    {
                        "item_id": "MLA1",
                        "seller_custom_field": "sku-1",
                    }
                ],
            )
        ],
    )

    summary = await run_order_line_identity_backfill(
        db=db,
        seller_id="82453304",
        date_from="2025-04-30",
        date_to="2025-05-01",
        dry_run=False,
    )

    assert summary.sku_index_upserts == 1
    assert db["sheets_item_sku_index"].documents["82453304:SKU-1:MLA1:item"][
        "updated_at"
    ] == datetime(2025, 4, 30, 4, 51, 7, tzinfo=UTC)


def test_extract_safe_order_item_identity_keeps_identity_fields_only() -> None:
    raw_item = {
        "id": "line-id-is-not-canonical",
        "buyer": {"id": "buyer-pii"},
        "item": {
            "id": "MLA1",
            "variation_id": 101,
            "seller_custom_field": " custom-101 ",
            "attributes": [{"id": "SELLER_SKU", "value_name": " item-sku "}],
        },
        "variation_attributes": [{"id": "SELLER_SKU", "value_name": " var-101 "}],
    }

    identity = extract_safe_order_item_identity(raw_item)

    assert identity == {
        "item_id": "MLA1",
        "variation_id": "101",
        "seller_sku": "var-101",
        "seller_custom_field": "custom-101",
    }
    assert "buyer" not in identity
    assert "item" not in identity
    assert "variation_attributes" not in identity


def test_merge_order_items_identity_adds_missing_fields_without_overwriting() -> None:
    existing_items = [
        {"item_id": "MLA1", "qty": 1, "unit_price": "10.00", "seller_sku": "existing-sku"},
        {"item_id": "MLA2", "qty": 1, "unit_price": "20.00"},
        {"item_id": "MLA2", "qty": 1, "unit_price": "21.00"},
    ]
    enriched_items = [
        {
            "item_id": "MLA1",
            "variation_id": "101",
            "seller_sku": "new-sku",
            "seller_custom_field": "custom-101",
        },
        {"item_id": "MLA2", "variation_id": "201", "seller_sku": "ambiguous-position"},
    ]

    merged, stats = merge_order_items_identity(existing_items, enriched_items)

    assert merged == [
        {
            "item_id": "MLA1",
            "qty": 1,
            "unit_price": "10.00",
            "seller_sku": "existing-sku",
            "variation_id": "101",
            "seller_custom_field": "custom-101",
        },
        {"item_id": "MLA2", "qty": 1, "unit_price": "20.00"},
        {"item_id": "MLA2", "qty": 1, "unit_price": "21.00"},
    ]
    assert stats.matched_order_lines == 1
    assert stats.updated_order_lines == 1
    assert stats.identity_fields_added == 2
    assert stats.skipped_unmatched_lines == 2


@pytest.mark.asyncio
async def test_order_identity_repair_dry_run_fetches_date_scoped_orders_without_writes() -> None:
    db = FakeDb(
        [],
        orders=[
            _order_doc(
                "order-1",
                date_created=datetime(2025, 4, 30, 12, tzinfo=UTC),
                items=[{"item_id": "MLA1", "qty": 1, "unit_price": "10.00"}],
            ),
            _order_doc(
                "order-2",
                date_created=datetime(2025, 5, 2, 12, tzinfo=UTC),
                items=[{"item_id": "MLA2", "qty": 1, "unit_price": "20.00"}],
            ),
            _order_doc(
                "order-other-seller",
                seller_id="999",
                date_created=datetime(2025, 4, 30, 12, tzinfo=UTC),
                items=[{"item_id": "MLB1", "qty": 1, "unit_price": "30.00"}],
            ),
        ],
    )
    gateway = FakeGateway(
        {
            "/orders/order-1": {
                "order_items": [
                    {
                        "item": {
                            "id": "MLA1",
                            "variation_id": 101,
                            "seller_custom_field": "custom-101",
                        },
                        "variation_attributes": [{"id": "SELLER_SKU", "value_name": "var-101"}],
                    }
                ]
            }
        }
    )

    summary = await run_order_identity_repair(
        db=db,
        gateway=gateway,
        seller_id="82453304",
        date_from="2025-04-30",
        date_to="2025-05-01",
        dry_run=True,
    )

    assert summary == OrderIdentityRepairSummary(
        seller_id="82453304",
        dry_run=True,
        date_from="2025-04-30",
        date_to="2025-05-01",
        orders_read=1,
        orders_fetched=1,
        orders_with_safe_identity=1,
        orders_updated=0,
        order_lines_read=1,
        enriched_order_lines=1,
        matched_order_lines=1,
        updated_order_lines=1,
        identity_fields_added=3,
        skipped_unmatched_lines=0,
    )
    assert db["orders"].find_filters == [
        {
            "seller_id": "82453304",
            "$or": [
                {
                    "date_created": {
                        "$gte": datetime(2025, 4, 30, tzinfo=UTC),
                        "$lt": datetime(2025, 5, 2, tzinfo=UTC),
                    }
                },
                {"date_created": {"$gte": "2025-04-30", "$lt": "2025-05-02"}},
            ],
        }
    ]
    assert gateway.calls == [("82453304", "/orders/order-1")]
    assert db["orders"].update_calls == []


@pytest.mark.asyncio
async def test_order_identity_repair_date_scope_matches_canonical_iso_dates() -> None:
    db = FakeDb(
        [],
        orders=[
            _order_doc(
                "order-1",
                date_created="2025-04-30T12:00:00.000+00:00",
                items=[{"item_id": "MLA1", "qty": 1, "unit_price": "10.00"}],
            ),
            _order_doc(
                "order-2",
                date_created="2025-05-02T00:00:00.000+00:00",
                items=[{"item_id": "MLA2", "qty": 1, "unit_price": "20.00"}],
            ),
        ],
    )
    gateway = FakeGateway(
        {
            "/orders/order-1": {
                "order_items": [
                    {
                        "item": {"id": "MLA1", "variation_id": 101},
                        "seller_custom_field": "custom-101",
                    }
                ]
            }
        }
    )

    summary = await run_order_identity_repair(
        db=db,
        gateway=gateway,
        seller_id="82453304",
        date_from="2025-04-30",
        date_to="2025-05-01",
        dry_run=True,
    )

    assert summary.orders_read == 1
    assert summary.identity_fields_added == 2


@pytest.mark.asyncio
async def test_order_identity_repair_write_is_idempotent_and_unlocks_order_line_identity() -> None:
    db = FakeDb(
        [],
        orders=[
            _order_doc(
                "order-1",
                date_created=datetime(2025, 4, 30, 12, tzinfo=UTC),
                items=[{"item_id": "MLA1", "qty": 1, "unit_price": "10.00"}],
            )
        ],
    )
    gateway = FakeGateway(
        {
            "/orders/order-1": {
                "order_items": [
                    {
                        "item": {"id": "MLA1", "variation_id": 101},
                        "seller_custom_field": "custom-101",
                    }
                ]
            }
        }
    )

    first = await run_order_identity_repair(
        db=db,
        gateway=gateway,
        seller_id="82453304",
        date_from="2025-04-30",
        date_to="2025-05-01",
        dry_run=False,
    )
    second = await run_order_identity_repair(
        db=db,
        gateway=gateway,
        seller_id="82453304",
        date_from="2025-04-30",
        date_to="2025-05-01",
        dry_run=False,
    )
    order_line_summary = await run_order_line_identity_backfill(
        db=db,
        seller_id="82453304",
        date_from="2025-04-30",
        date_to="2025-05-01",
        dry_run=True,
    )

    assert first.orders_updated == 1
    assert first.identity_fields_added == 2
    assert second.orders_updated == 0
    assert second.identity_fields_added == 0
    assert db["orders"].documents["order-1"]["items"] == [
        {
            "item_id": "MLA1",
            "qty": 1,
            "unit_price": "10.00",
            "variation_id": "101",
            "seller_custom_field": "custom-101",
        }
    ]
    assert order_line_summary.deterministic_pairs == 1
    assert order_line_summary.sku_index_upserts == 1
    assert db["orders"].update_calls[0][2] == {
        "upsert": False,
        "bypass_document_validation": True,
    }


@pytest.mark.asyncio
async def test_order_identity_repair_api_failure_writes_nothing() -> None:
    db = FakeDb(
        [],
        orders=[
            _order_doc(
                "order-1",
                date_created=datetime(2025, 4, 30, 12, tzinfo=UTC),
                items=[{"item_id": "MLA1", "qty": 1, "unit_price": "10.00"}],
            ),
            _order_doc(
                "order-2",
                date_created=datetime(2025, 4, 30, 13, tzinfo=UTC),
                items=[{"item_id": "MLA2", "qty": 1, "unit_price": "20.00"}],
            ),
        ],
    )
    gateway = FakeGateway(
        {
            "/orders/order-1": {
                "order_items": [
                    {
                        "item": {"id": "MLA1", "variation_id": 101},
                        "seller_custom_field": "custom-101",
                    }
                ]
            },
            "/orders/order-2": RuntimeError("rate-limit or auth failure"),
        }
    )

    with pytest.raises(RuntimeError, match="rate-limit or auth failure"):
        await run_order_identity_repair(
            db=db,
            gateway=gateway,
            seller_id="82453304",
            date_from="2025-04-30",
            date_to="2025-05-01",
            dry_run=False,
        )

    assert db["orders"].update_calls == []


@pytest.mark.asyncio
async def test_order_identity_repair_skips_payloads_without_identity_fields() -> None:
    db = FakeDb(
        [],
        orders=[
            _order_doc(
                "order-1",
                date_created=datetime(2025, 4, 30, 12, tzinfo=UTC),
                items=[{"item_id": "MLA1", "qty": 1, "unit_price": "10.00"}],
            )
        ],
    )
    gateway = FakeGateway({"/orders/order-1": {"order_items": [{"item": {"id": "MLA1"}}]}})

    summary = await run_order_identity_repair(
        db=db,
        gateway=gateway,
        seller_id="82453304",
        date_from="2025-04-30",
        date_to="2025-05-01",
        dry_run=False,
    )

    assert summary.orders_with_safe_identity == 0
    assert summary.identity_fields_added == 0
    assert db["orders"].update_calls == []


@pytest.mark.asyncio
async def test_order_normalization_dry_run_counts_parseable_legacy_strings_without_writes() -> None:
    db = FakeDb(
        [],
        orders=[
            _canonical_order_doc(
                "order-1",
                date_created="2025-04-30T12:00:00.000+00:00",
                date_closed="2025-04-30T12:05:00Z",
                total_amount="20.50",
                items=[{"item_id": "MLA1", "qty": 2, "unit_price": "10.25"}],
            ),
            _canonical_order_doc(
                "order-2",
                date_created=datetime(2025, 4, 30, 13, tzinfo=UTC),
                total_amount=Decimal128("5.00"),
                items=[{"item_id": "MLA2", "qty": 1, "unit_price": Decimal128("5.00")}],
            ),
            _canonical_order_doc(
                "order-outside",
                date_created="2025-05-02T00:00:00.000+00:00",
                total_amount="9.99",
                items=[{"item_id": "MLA3", "qty": 1, "unit_price": "9.99"}],
            ),
        ],
    )

    summary = await run_order_normalization(
        db=db,
        seller_id="82453304",
        date_from="2025-04-30",
        date_to="2025-05-01",
        dry_run=True,
    )

    assert summary == OrderNormalizationSummary(
        seller_id="82453304",
        dry_run=True,
        date_from="2025-04-30",
        date_to="2025-05-01",
        orders_read=2,
        orders_to_update=1,
        orders_updated=0,
        date_fields_converted=2,
        money_fields_converted=2,
        skipped_unparseable_orders=0,
        unparseable_date_values=0,
        unparseable_money_values=0,
    )
    assert db["orders"].update_calls == []


@pytest.mark.asyncio
async def test_order_normalization_write_uses_targeted_sets_and_is_idempotent() -> None:
    db = FakeDb(
        [],
        orders=[
            _canonical_order_doc(
                "order-1",
                date_created="2025-04-30T12:00:00.000+00:00",
                date_closed=None,
                total_amount="20.50",
                items=[
                    {"item_id": "MLA1", "qty": 1, "unit_price": "10.25"},
                    {"item_id": "MLA2", "qty": 1, "unit_price": Decimal128("10.25")},
                ],
            )
        ],
    )

    first = await run_order_normalization(
        db=db,
        seller_id="82453304",
        date_from="2025-04-30",
        date_to="2025-05-01",
        dry_run=False,
    )
    second = await run_order_normalization(
        db=db,
        seller_id="82453304",
        date_from="2025-04-30",
        date_to="2025-05-01",
        dry_run=False,
    )

    assert first.orders_to_update == 1
    assert first.orders_updated == 1
    assert second.orders_to_update == 0
    assert second.orders_updated == 0
    assert db["orders"].update_calls[0] == (
        {"_id": "order-1", "seller_id": "82453304"},
        {
            "$set": {
                "date_created": datetime(2025, 4, 30, 12, tzinfo=UTC),
                "total_amount": Decimal128("20.50"),
                "items.0.unit_price": Decimal128("10.25"),
            }
        },
        {"upsert": False, "bypass_document_validation": False},
    )
    assert db["orders"].documents["order-1"]["date_created"] == datetime(
        2025, 4, 30, 12, tzinfo=UTC
    )
    assert db["orders"].documents["order-1"]["items"][0]["unit_price"] == Decimal128("10.25")


@pytest.mark.asyncio
async def test_order_normalization_skips_unparseable_values_without_partial_updates() -> None:
    db = FakeDb(
        [],
        orders=[
            _canonical_order_doc(
                "bad-date",
                date_created="2025-04-30Tbad",
                total_amount="20.50",
                items=[{"item_id": "MLA1", "qty": 1, "unit_price": "10.25"}],
            ),
            _canonical_order_doc(
                "bad-money",
                date_created="2025-04-30T12:00:00.000+00:00",
                total_amount="not-money",
                items=[{"item_id": "MLA2", "qty": 1, "unit_price": "10.25"}],
            ),
        ],
    )

    summary = await run_order_normalization(
        db=db,
        seller_id="82453304",
        date_from="2025-04-30",
        date_to="2025-05-01",
        dry_run=False,
    )

    assert summary.orders_read == 2
    assert summary.orders_to_update == 0
    assert summary.orders_updated == 0
    assert summary.skipped_unparseable_orders == 2
    assert summary.unparseable_date_values == 1
    assert summary.unparseable_money_values == 1
    assert db["orders"].update_calls == []


@pytest.mark.asyncio
async def test_order_normalization_converted_documents_validate_against_order_model() -> None:
    db = FakeDb(
        [],
        orders=[
            _canonical_order_doc(
                "order-1",
                date_created="2025-04-30T12:00:00.000+00:00",
                date_closed="2025-04-30T12:05:00.000+00:00",
                total_amount="20.50",
                items=[{"item_id": "MLA1", "qty": 2, "unit_price": "10.25"}],
            )
        ],
    )

    summary = await run_order_normalization(
        db=db,
        seller_id="82453304",
        date_from="2025-04-30",
        date_to="2025-05-01",
        dry_run=False,
    )
    normalized = db["orders"].documents["order-1"]
    model = Order.model_validate(normalized)

    assert summary.orders_updated == 1
    assert model.date_created == datetime(2025, 4, 30, 12, tzinfo=UTC)
    assert model.date_closed == datetime(2025, 4, 30, 12, 5, tzinfo=UTC)
    assert model.total_amount == Decimal("20.50")
    assert model.items[0].unit_price == Decimal("10.25")


def _item_doc(
    item_id: str,
    *,
    seller_id: str = "82453304",
    attributes: list[dict[str, Any]] | None = None,
    variations: list[dict[str, Any]] | None = None,
    permalink: str | None = None,
    thumbnail: str | None = None,
    catalog_product_id: str | None = None,
    inventory_id: str | None = None,
    last_updated: datetime | None = None,
) -> dict[str, Any]:
    document = {
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
        "variations": variations or [],
        "schema_version": 2,
    }
    for key, value in (
        ("permalink", permalink),
        ("thumbnail", thumbnail),
        ("catalog_product_id", catalog_product_id),
        ("inventory_id", inventory_id),
    ):
        if value is not None:
            document[key] = value
    return document


def _item_detail(item_id: str, *, seller_id: str = "82453304") -> dict[str, Any]:
    return {
        "id": item_id,
        "seller_id": seller_id,
        "title": f"Detail {item_id}",
        "price": "123.45",
        "base_price": "123.45",
        "available_quantity": 7,
        "status": "active",
        "category_id": "MLA-CAT",
        "permalink": f"https://articulo.example/{item_id}",
        "thumbnail": f"https://img.example/{item_id}.jpg",
        "catalog_product_id": f"CATALOG-{item_id}",
        "inventory_id": f"INV-{item_id}",
        "attributes": [],
        "variations": [],
        "date_created": NOW.isoformat(),
        "last_updated": NOW.isoformat(),
    }


def _order_doc(
    order_id: str,
    *,
    seller_id: str = "82453304",
    date_created: datetime | str = NOW,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "_id": order_id,
        "seller_id": seller_id,
        "date_created": date_created,
        "items": items,
        "schema_version": 1,
    }


def _canonical_order_doc(
    order_id: str,
    *,
    seller_id: str = "82453304",
    date_created: Any = NOW,
    date_closed: Any = None,
    total_amount: Any = None,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "_id": order_id,
        "seller_id": seller_id,
        "buyer_id": "buyer-redacted",
        "status": "paid",
        "date_created": date_created,
        "date_closed": date_closed,
        "total_amount": total_amount if total_amount is not None else Decimal128("10.00"),
        "items": items,
        "schema_version": 1,
    }
