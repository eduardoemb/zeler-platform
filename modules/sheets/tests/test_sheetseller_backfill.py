from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from zeler_sheets.sheetseller_backfill import (
    BackfillSummary,
    OrderIdentityRepairSummary,
    OrderLineIdentityBackfillSummary,
    build_arg_parser,
    build_formula_row_doc,
    build_sku_index_doc,
    build_sku_index_docs,
    extract_safe_order_item_identity,
    extract_seller_sku,
    merge_order_items_identity,
    run_order_identity_repair,
    run_order_line_identity_backfill,
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
        self.update_calls: list[tuple[dict[str, Any], dict[str, Any], bool]] = []
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

    async def update_one(
        self, filter_spec: dict[str, Any], update: dict[str, Any], *, upsert: bool = False
    ) -> FakeReplaceResult:
        self.update_calls.append((dict(filter_spec), dict(update), upsert))
        if upsert is not False:
            raise AssertionError("order repair must update existing canonical orders only")
        doc_id = str(filter_spec["_id"])
        current = dict(self.documents[doc_id])
        current.update(update.get("$set", {}))
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
        return actual >= expected
    except TypeError:
        return False


def _safe_lt(actual: Any, expected: Any) -> bool:
    try:
        return actual < expected
    except TypeError:
        return False


class FakeGateway:
    def __init__(self, payloads: dict[str, dict[str, Any]]) -> None:
        self.payloads = payloads
        self.calls: list[tuple[str, str]] = []

    async def fetch_resource(self, *, seller_id: str, path: str) -> dict[str, Any]:
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

    assert args.seller_id == "82453304"
    assert args.dry_run is True
    assert write_args.dry_run is False
    assert repair_args.source == "orders-repair"
    assert repair_args.date_from == "2025-04-30"
    assert repair_args.date_to == "2025-05-01"
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
        "inventory_id": None,
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
        "schema_version": 2,
    }


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
    )
    assert second == first
    assert sorted(db["sheets_item_sku_index"].documents) == [
        "82453304:SKU 2:MLA2:item",
        "82453304:SKU-1:MLA1:item",
    ]
    assert sorted(db["sheets_item_formula_rows"].documents) == [
        "82453304:SKU 2:MLA2",
        "82453304:SKU-1:MLA1",
    ]
    assert len(db["sheets_item_sku_index"].replace_calls) == 4
    assert len(db["sheets_item_formula_rows"].replace_calls) == 4
    assert all(call[2] is True for call in db["sheets_item_sku_index"].replace_calls)
    assert all(
        call[0] == {"_id": call[1]["_id"]} for call in db["sheets_item_formula_rows"].replace_calls
    )


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
    )
    assert second == first
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
    assert summary.variation_sku_rows == 1
    assert summary.skipped_missing_sku == 1
    assert summary.skipped_missing_variation_sku == 1
    assert db["sheets_item_sku_index"].documents == {}


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


def _item_doc(
    item_id: str,
    *,
    seller_id: str = "82453304",
    attributes: list[dict[str, Any]] | None = None,
    variations: list[dict[str, Any]] | None = None,
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
        "variations": variations or [],
        "schema_version": 1,
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
