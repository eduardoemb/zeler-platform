# ruff: noqa: S105,S106

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from zeler_sheets.extension_tokens import ExtensionTokenService, SellerScope
from zeler_sheets.formulas.dispatcher import FormulaDispatcher, FormulaExecutionContext
from zeler_sheets.formulas.handlers_orders_questions import (
    build_order_question_formula_handlers,
)
from zeler_sheets.formulas.read_models import FormulaReadModelRepository
from zeler_sheets.formulas.registry import FormulaRegistry


class FakeUpdateResult:
    modified_count = 1


class FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs

    def sort(self, sort_spec: list[tuple[str, int]]) -> FakeCursor:
        sorted_docs = list(self._docs)
        for key, direction in reversed(sort_spec):
            sorted_docs.sort(key=lambda doc: _sort_value(doc.get(key)), reverse=direction < 0)
        return FakeCursor(sorted_docs)

    async def to_list(self, length: int) -> list[dict[str, Any]]:
        return [dict(doc) for doc in self._docs[:length]]


class FakeCollection:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}
        self.last_find_filter: dict[str, Any] | None = None
        self.find_filters: list[dict[str, Any]] = []

    async def insert_one(self, doc: dict[str, Any]) -> None:
        self.documents[str(doc["_id"])] = dict(doc)

    async def find_one(self, filter_spec: dict[str, Any]) -> dict[str, Any] | None:
        self.last_find_filter = dict(filter_spec)
        for doc in self.documents.values():
            if _matches(doc, filter_spec):
                return dict(doc)
        return None

    def find(self, filter_spec: dict[str, Any]) -> FakeCursor:
        self.last_find_filter = dict(filter_spec)
        self.find_filters.append(dict(filter_spec))
        return FakeCursor(
            [dict(doc) for doc in self.documents.values() if _matches(doc, filter_spec)]
        )

    async def update_one(
        self, filter_spec: dict[str, Any], update_spec: dict[str, Any], *, upsert: bool = False
    ) -> FakeUpdateResult:
        assert upsert is False
        for doc_id, doc in self.documents.items():
            if _matches(doc, filter_spec):
                replacement = dict(doc)
                replacement.update(update_spec.get("$set", {}))
                self.documents[doc_id] = replacement
                return FakeUpdateResult()
        raise AssertionError(f"no matching document for {filter_spec}")


class FakeDb:
    def __init__(self) -> None:
        self.collections: dict[str, FakeCollection] = {"sheets_extension_tokens": FakeCollection()}

    @property
    def sheets_extension_tokens(self) -> FakeCollection:
        return self.collections["sheets_extension_tokens"]

    def __getitem__(self, name: str) -> FakeCollection:
        return self.collections.setdefault(name, FakeCollection())


def _matches(doc: dict[str, Any], filter_spec: dict[str, Any]) -> bool:
    for key, expected in filter_spec.items():
        if key == "$or":
            if not any(_matches(doc, branch) for branch in expected):
                return False
            continue
        value = doc.get(key)
        if isinstance(expected, dict):
            try:
                if "$in" in expected and value not in expected["$in"]:
                    return False
                if "$gte" in expected and value < expected["$gte"]:
                    return False
                if "$lte" in expected and value > expected["$lte"]:
                    return False
            except TypeError:
                return False
        elif value != expected:
            return False
    return True


@pytest.mark.asyncio
async def test_ordenes_returns_order_table_with_status_buyer_filters_and_headers() -> None:
    db = FakeDb()
    orders = db["orders"]
    orders.documents = {
        "order-2": _order_doc(
            "order-2",
            seller_id="seller-1",
            status="paid",
            buyer_id="buyer-2",
            date_created="2026-05-11T08:15:00Z",
            total_amount="75.50",
            shipment_id="shipment-2",
            items=[{"seller_sku": "sku-2", "item": {"id": "MLA2"}, "quantity": 1}],
        ),
        "order-1": _order_doc(
            "order-1",
            seller_id="seller-1",
            status="paid",
            buyer_id="buyer-1",
            date_created="2026-05-10T10:30:00Z",
            total_amount="100.00",
            shipment_id="shipment-1",
            items=[{"sku": "sku-1", "item_id": "MLA1", "quantity": 2}],
        ),
        "cancelled": _order_doc(
            "cancelled",
            seller_id="seller-1",
            status="cancelled",
            buyer_id="buyer-1",
            date_created="2026-05-10T12:00:00Z",
            total_amount="55.00",
        ),
        "other-seller": _order_doc(
            "other-seller",
            seller_id="seller-2",
            status="paid",
            buyer_id="buyer-1",
            date_created="2026-05-10T10:30:00Z",
            total_amount="999.00",
        ),
    }
    dispatcher = _order_question_dispatcher(db)

    result = await dispatcher.execute(
        _context(
            "SHEETSELLER_ORDENES",
            {
                "fecha_inicial": "2026-05-10",
                "fecha_final": "2026-05-11",
                "estado": "paid",
                "compradores": [["buyer-1"], ["buyer-2"]],
                "encabezados": "si",
            },
        )
    )

    assert result.values == [
        ["ID Orden", "Fecha", "Estado", "Buyer ID", "Total", "Shipment ID", "Items"],
        [
            "order-1",
            "2026-05-10T10:30:00Z",
            "paid",
            "buyer-1",
            100,
            "shipment-1",
            "SKU-1 x2 (MLA1)",
        ],
        [
            "order-2",
            "2026-05-11T08:15:00Z",
            "paid",
            "buyer-2",
            75.5,
            "shipment-2",
            "SKU-2 x1 (MLA2)",
        ],
    ]
    assert result.meta == {
        "orders_count": 2,
        "status_filter": "paid",
        "buyer_filter_count": 2,
        "columns": "orders_mvp",
    }


@pytest.mark.asyncio
async def test_ventas_totales_uses_seller_scoped_orders_date_range_and_status_filters() -> None:
    db = FakeDb()
    orders = db["orders"]
    orders.documents = {
        "order-1": _order_doc(
            "order-1",
            seller_id="seller-1",
            status="paid",
            date_created=datetime(2026, 5, 10, 10, 30, tzinfo=UTC),
            total_amount=100.5,
        ),
        "order-2": _order_doc(
            "order-2",
            seller_id="seller-1",
            status="cancelled",
            date_created=datetime(2026, 5, 11, 23, 59, tzinfo=UTC),
            total_amount=25,
        ),
        "order-outside-range": _order_doc(
            "order-outside-range",
            seller_id="seller-1",
            status="paid",
            date_created=datetime(2026, 5, 12, 0, 0, 1, tzinfo=UTC),
            total_amount=999,
        ),
        "order-other-seller": _order_doc(
            "order-other-seller",
            seller_id="seller-2",
            status="paid",
            date_created=datetime(2026, 5, 10, 11, 0, tzinfo=UTC),
            total_amount=999,
        ),
    }
    dispatcher = _order_question_dispatcher(db)

    all_statuses = await dispatcher.execute(
        _context(
            "SHEETSELLER_VENTASTOTALES",
            {"fecha_inicial": "2026-05-10", "fecha_final": "2026-05-11", "estado": "todos"},
        )
    )
    paid_only = await dispatcher.execute(
        _context(
            "SHEETSELLER_VENTASTOTALES",
            {"fecha_inicial": "2026-05-10", "fecha_final": "2026-05-11", "estado": "paid"},
        )
    )

    assert all_statuses.values == [[125.5]]
    assert all_statuses.meta == {"orders_count": 2, "status_filter": "todos"}
    assert paid_only.values == [[100.5]]
    assert paid_only.meta == {"orders_count": 1, "status_filter": "paid"}
    assert orders.last_find_filter is not None
    assert orders.last_find_filter["seller_id"] == "seller-1"
    assert orders.last_find_filter["status"] == "paid"
    assert orders.last_find_filter["$or"] == [
        {
            "date_created": {
                "$gte": datetime(2026, 5, 10, 0, 0, tzinfo=UTC),
                "$lte": datetime(2026, 5, 11, 23, 59, 59, 999999, tzinfo=UTC),
            }
        },
        {"date_created": {"$gte": "2026-05-10", "$lte": "2026-05-11T99:99:99"}},
    ]


@pytest.mark.asyncio
async def test_ventas_totales_matches_production_iso_string_dates() -> None:
    db = FakeDb()
    orders = db["orders"]
    orders.documents = {
        "order-1": _order_doc(
            "order-1",
            seller_id="seller-1",
            status="paid",
            date_created="2025-04-30T13:12:00Z",
            total_amount="100.50",
        ),
        "order-2": _order_doc(
            "order-2",
            seller_id="seller-1",
            status="cancelled",
            date_created="2025-05-01T23:59:59Z",
            total_amount="25.25",
        ),
        "outside": _order_doc(
            "outside",
            seller_id="seller-1",
            status="paid",
            date_created="2025-05-02T00:00:00Z",
            total_amount="999",
        ),
    }
    dispatcher = _order_question_dispatcher(db)

    all_statuses = await dispatcher.execute(
        _context(
            "SHEETSELLER_VENTASTOTALES",
            {"fecha_inicial": "2025-04-30", "fecha_final": "2025-05-01", "estado": "todos"},
        )
    )
    cancelled = await dispatcher.execute(
        _context(
            "SHEETSELLER_VENTASTOTALES",
            {
                "fecha_inicial": "2025-04-30",
                "fecha_final": "2025-05-01",
                "estado": "cancelled",
            },
        )
    )

    assert all_statuses.values == [[125.75]]
    assert all_statuses.meta == {"orders_count": 2, "status_filter": "todos"}
    assert cancelled.values == [[25.25]]
    assert cancelled.meta == {"orders_count": 1, "status_filter": "cancelled"}


@pytest.mark.asyncio
async def test_ordenes_por_sku_filters_orders_by_requested_skus() -> None:
    db = FakeDb()
    orders = db["orders"]
    orders.documents = {
        "order-sku-1": _order_doc(
            "order-sku-1",
            seller_id="seller-1",
            status="paid",
            buyer_id="buyer-1",
            date_created=datetime(2026, 5, 10, 8, 0, tzinfo=UTC),
            total_amount=30,
            items=[{"sku": "sku-1", "item_id": "MLA1", "quantity": 1}],
        ),
        "order-sku-2": _order_doc(
            "order-sku-2",
            seller_id="seller-1",
            status="paid",
            buyer_id="buyer-2",
            date_created=datetime(2026, 5, 10, 9, 0, tzinfo=UTC),
            total_amount=40,
            items=[{"seller_sku": "sku-2", "item": {"id": "MLA2"}, "quantity": 3}],
        ),
        "order-no-sku-match": _order_doc(
            "order-no-sku-match",
            seller_id="seller-1",
            status="paid",
            buyer_id="buyer-3",
            date_created=datetime(2026, 5, 10, 10, 0, tzinfo=UTC),
            total_amount=50,
            items=[{"sku": "other", "item_id": "MLA3", "quantity": 4}],
        ),
    }
    dispatcher = _order_question_dispatcher(db)

    result = await dispatcher.execute(
        _context(
            "SHEETSELLER_ORDENESPORSKU",
            {
                "skus": [["sku-2"], ["sku-1"]],
                "fecha_inicial": "2026-05-10",
                "fecha_final": "2026-05-10",
                "estado": "todos",
                "encabezados": "si",
            },
        )
    )

    assert result.values == [
        ["SKU", "ID Orden", "Fecha", "Estado", "Buyer ID", "Total", "Items"],
        [
            "SKU-2",
            "order-sku-2",
            "2026-05-10T09:00:00+00:00",
            "paid",
            "buyer-2",
            40,
            "SKU-2 x3 (MLA2)",
        ],
        [
            "SKU-1",
            "order-sku-1",
            "2026-05-10T08:00:00+00:00",
            "paid",
            "buyer-1",
            30,
            "SKU-1 x1 (MLA1)",
        ],
    ]
    assert result.meta == {
        "orders_count": 2,
        "status_filter": "todos",
        "buyer_filter_count": 0,
        "sku_filter_count": 2,
        "columns": "orders_by_sku_mvp",
    }


@pytest.mark.asyncio
async def test_ordenes_por_sku_enriches_canonical_order_items_from_seller_sku_index() -> None:
    db = FakeDb()
    db["sheets_item_sku_index"].documents = {
        "seller-1:SKU-1:MLA1": _sku_index_doc("seller-1", "SKU-1", "MLA1"),
        "seller-2:SKU-1:MLA1": _sku_index_doc("seller-2", "WRONG", "MLA1"),
        "seller-1:AMB-1:MLA2": _sku_index_doc("seller-1", "AMB-1", "MLA2"),
        "seller-1:AMB-2:MLA2": _sku_index_doc("seller-1", "AMB-2", "MLA2"),
    }
    db["orders"].documents = {
        "enriched": _order_doc(
            "enriched",
            seller_id="seller-1",
            status="paid",
            buyer_id="buyer-1",
            date_created=datetime(2026, 5, 10, 8, 0, tzinfo=UTC),
            total_amount=30,
            items=[{"item_id": "MLA1", "qty": 2, "unit_price": "15.00"}],
        ),
        "ambiguous": _order_doc(
            "ambiguous",
            seller_id="seller-1",
            status="paid",
            buyer_id="buyer-2",
            date_created=datetime(2026, 5, 10, 9, 0, tzinfo=UTC),
            total_amount=40,
            items=[{"item_id": "MLA2", "qty": 1, "unit_price": "40.00"}],
        ),
    }
    dispatcher = _order_question_dispatcher(db)

    result = await dispatcher.execute(
        _context(
            "SHEETSELLER_ORDENESPORSKU",
            {
                "skus": [["sku-1"], ["amb-1"]],
                "fecha_inicial": "2026-05-10",
                "fecha_final": "2026-05-10",
                "estado": "todos",
                "encabezados": "si",
            },
        )
    )

    assert result.values == [
        ["SKU", "ID Orden", "Fecha", "Estado", "Buyer ID", "Total", "Items"],
        [
            "SKU-1",
            "enriched",
            "2026-05-10T08:00:00+00:00",
            "paid",
            "buyer-1",
            30,
            "SKU-1 x2 (MLA1)",
        ],
    ]
    assert result.meta == {
        "orders_count": 1,
        "status_filter": "todos",
        "buyer_filter_count": 0,
        "sku_filter_count": 2,
        "columns": "orders_by_sku_mvp",
    }
    assert db["sheets_item_sku_index"].last_find_filter == {
        "seller_id": "seller-1",
        "item_id": {"$in": ["MLA1", "MLA2"]},
    }


@pytest.mark.asyncio
async def test_unidades_vendidas_returns_units_by_sku_item_pair_with_zero_for_misses() -> None:
    db = FakeDb()
    orders = db["orders"]
    orders.documents = {
        "order-1": _order_doc(
            "order-1",
            seller_id="seller-1",
            status="paid",
            date_created=datetime(2026, 5, 10, 12, 0, tzinfo=UTC),
            total_amount=120,
            items=[
                {"sku": "sku-1", "item_id": "MLA1", "quantity": 2},
                {"seller_sku": "sku-2", "item": {"id": "MLA2"}, "quantity": 1},
            ],
        ),
        "order-2": _order_doc(
            "order-2",
            seller_id="seller-1",
            status="paid",
            date_created=datetime(2026, 5, 11, 8, 0, tzinfo=UTC),
            total_amount=50,
            items=[{"sku": "SKU-1", "item_id": "MLA1", "quantity": 1}],
        ),
        "order-other-seller": _order_doc(
            "order-other-seller",
            seller_id="seller-2",
            status="paid",
            date_created=datetime(2026, 5, 10, 12, 0, tzinfo=UTC),
            total_amount=999,
            items=[{"sku": "sku-1", "item_id": "MLA1", "quantity": 99}],
        ),
    }
    dispatcher = _order_question_dispatcher(db)

    result = await dispatcher.execute(
        _context(
            "SHEETSELLER_UNIDADESVENDIDAS",
            {
                "skus": [["sku-1"], ["missing"], ["sku-2"]],
                "id_publicaciones": ["MLA1", "MLA-X", "MLA2"],
                "fecha_inicial": "2026-05-10",
                "fecha_final": "2026-05-11",
            },
        )
    )

    assert result.values == [[3], [0], [1]]
    assert result.meta == {"partial_misses": 1, "orders_count": 2}
    assert orders.last_find_filter is not None
    assert orders.last_find_filter["seller_id"] == "seller-1"
    assert orders.last_find_filter["$or"][0] == {
        "date_created": {
            "$gte": datetime(2026, 5, 10, 0, 0, tzinfo=UTC),
            "$lte": datetime(2026, 5, 11, 23, 59, 59, 999999, tzinfo=UTC),
        }
    }


@pytest.mark.asyncio
async def test_unidades_vendidas_uses_seller_scoped_sku_index_for_canonical_order_items() -> None:
    db = FakeDb()
    db["sheets_item_sku_index"].documents = {
        "seller-1:SKU-1:MLA1": _sku_index_doc("seller-1", "SKU-1", "MLA1"),
        "seller-2:SKU-1:MLA1": _sku_index_doc("seller-2", "SKU-1", "MLA1"),
        "seller-1:AMB-1:MLA2": _sku_index_doc("seller-1", "AMB-1", "MLA2"),
        "seller-1:AMB-2:MLA2": _sku_index_doc("seller-1", "AMB-2", "MLA2"),
    }
    db["orders"].documents = {
        "order-1": _order_doc(
            "order-1",
            seller_id="seller-1",
            status="paid",
            date_created=datetime(2026, 5, 10, 12, 0, tzinfo=UTC),
            total_amount=120,
            items=[
                {"item_id": "MLA1", "qty": 2, "unit_price": "10.00"},
                {"item_id": "MLA2", "qty": 5, "unit_price": "8.00"},
            ],
        ),
        "order-2": _order_doc(
            "order-2",
            seller_id="seller-1",
            status="paid",
            date_created="2026-05-11T08:00:00Z",
            total_amount=50,
            items=[{"item_id": "MLA1", "qty": 1, "unit_price": "10.00"}],
        ),
    }
    dispatcher = _order_question_dispatcher(db)

    result = await dispatcher.execute(
        _context(
            "SHEETSELLER_UNIDADESVENDIDAS",
            {
                "skus": [["sku-1"], ["amb-1"]],
                "id_publicaciones": ["MLA1", "MLA2"],
                "fecha_inicial": "2026-05-10",
                "fecha_final": "2026-05-11",
            },
        )
    )

    assert result.values == [[3], [0]]
    assert result.meta == {"partial_misses": 1, "orders_count": 2, "sku_enriched_items": 2}


@pytest.mark.asyncio
async def test_unidades_vendidas_batches_variation_identity_lookup_once() -> None:
    db = FakeDb()
    db["sheets_item_sku_index"].documents = {
        "seller-1:SKU-RED:MLA1:101": _sku_index_doc(
            "seller-1", "SKU-RED", "MLA1", variation_id="101"
        ),
        "seller-1:SKU-BLUE:MLA1:102": _sku_index_doc(
            "seller-1", "SKU-BLUE", "MLA1", variation_id="102"
        ),
    }
    db["orders"].documents = {
        "order-1": _order_doc(
            "order-1",
            seller_id="seller-1",
            status="paid",
            date_created=datetime(2026, 5, 10, 12, 0, tzinfo=UTC),
            total_amount=120,
            items=[
                {"item_id": "MLA1", "variation_id": 101, "qty": 2, "unit_price": "10.00"},
                {"item_id": "MLA1", "variation_id": "102", "qty": 3, "unit_price": "8.00"},
            ],
        )
    }
    dispatcher = _order_question_dispatcher(db)

    result = await dispatcher.execute(
        _context(
            "SHEETSELLER_UNIDADESVENDIDAS",
            {
                "skus": [["sku-red"], ["sku-blue"]],
                "id_publicaciones": ["MLA1", "MLA1"],
                "fecha_inicial": "2026-05-10",
                "fecha_final": "2026-05-10",
            },
        )
    )

    assert result.values == [[2], [3]]
    assert result.meta == {"partial_misses": 0, "orders_count": 1, "sku_enriched_items": 2}
    assert db["sheets_item_sku_index"].find_filters == [
        {
            "seller_id": "seller-1",
            "item_id": {"$in": ["MLA1"]},
            "variation_id": {"$in": ["101", "102"]},
        }
    ]


@pytest.mark.asyncio
async def test_order_line_direct_sku_wins_over_ambiguous_identity_map() -> None:
    db = FakeDb()
    db["sheets_item_sku_index"].documents = {
        "seller-1:WRONG-1:MLA1:101": _sku_index_doc(
            "seller-1", "WRONG-1", "MLA1", variation_id="101"
        ),
        "seller-1:WRONG-2:MLA1:102": _sku_index_doc(
            "seller-1", "WRONG-2", "MLA1", variation_id="102"
        ),
    }
    db["orders"].documents = {
        "order-1": _order_doc(
            "order-1",
            seller_id="seller-1",
            status="paid",
            date_created=datetime(2026, 5, 10, 12, 0, tzinfo=UTC),
            total_amount=120,
            items=[{"sku": "direct-sku", "item_id": "MLA1", "variation_id": 101, "quantity": 4}],
        )
    }
    dispatcher = _order_question_dispatcher(db)

    result = await dispatcher.execute(
        _context(
            "SHEETSELLER_UNIDADESVENDIDAS",
            {
                "skus": [["direct-sku"], ["wrong-1"]],
                "id_publicaciones": ["MLA1", "MLA1"],
                "fecha_inicial": "2026-05-10",
                "fecha_final": "2026-05-10",
            },
        )
    )

    assert result.values == [[4], [0]]
    assert result.meta == {"partial_misses": 1, "orders_count": 1}


@pytest.mark.asyncio
async def test_venta_por_dias_sums_recent_units_from_now_with_sku_enrichment() -> None:
    db = FakeDb()
    db["sheets_item_sku_index"].documents = {
        "seller-1:SKU-1:MLA1": _sku_index_doc("seller-1", "SKU-1", "MLA1"),
    }
    db["orders"].documents = {
        "inside-start": _order_doc(
            "inside-start",
            seller_id="seller-1",
            status="paid",
            date_created="2026-05-08T00:00:00Z",
            total_amount=20,
            items=[{"item_id": "MLA1", "qty": 2, "unit_price": "10.00"}],
        ),
        "inside-end": _order_doc(
            "inside-end",
            seller_id="seller-1",
            status="paid",
            date_created="2026-05-14T23:59:00Z",
            total_amount=10,
            items=[{"item_id": "MLA1", "qty": 1, "unit_price": "10.00"}],
        ),
        "outside": _order_doc(
            "outside",
            seller_id="seller-1",
            status="paid",
            date_created="2026-05-07T23:59:59Z",
            total_amount=999,
            items=[{"item_id": "MLA1", "qty": 99, "unit_price": "10.00"}],
        ),
    }
    dispatcher = _order_question_dispatcher(
        db, now_fn=lambda: datetime(2026, 5, 14, 12, 0, tzinfo=UTC)
    )

    result = await dispatcher.execute(
        _context(
            "SHEETSELLER_VENTAPORDIAS",
            {"skus": ["sku-1", "missing"], "id_publicaciones": ["MLA1", "MLA-X"], "rango_dias": 7},
        )
    )

    assert result.values == [[3], [0]]
    assert result.meta == {
        "partial_misses": 1,
        "orders_count": 2,
        "rango_dias": 7,
        "sku_enriched_items": 2,
    }


@pytest.mark.asyncio
async def test_top_ventas_unidades_and_dinero_rank_enriched_items_deterministically() -> None:
    db = FakeDb()
    db["sheets_item_sku_index"].documents = {
        "seller-1:SKU-1:MLA1": _sku_index_doc("seller-1", "SKU-1", "MLA1"),
        "seller-1:SKU-2:MLA2": _sku_index_doc("seller-1", "SKU-2", "MLA2"),
        "seller-1:SKU-3:MLA3": _sku_index_doc("seller-1", "SKU-3", "MLA3"),
    }
    db["orders"].documents = {
        "order-1": _order_doc(
            "order-1",
            seller_id="seller-1",
            status="paid",
            date_created=datetime(2026, 5, 10, 10, 0, tzinfo=UTC),
            total_amount=55,
            items=[
                {"item_id": "MLA1", "qty": 2, "unit_price": "10.00"},
                {"item_id": "MLA2", "qty": 5, "unit_price": "3.00"},
            ],
        ),
        "order-2": _order_doc(
            "order-2",
            seller_id="seller-1",
            status="paid",
            date_created=datetime(2026, 5, 11, 10, 0, tzinfo=UTC),
            total_amount=20,
            items=[
                {"item_id": "MLA1", "qty": 1, "unit_price": "20.00"},
                {"item_id": "MLA3", "qty": 9},
            ],
        ),
    }
    dispatcher = _order_question_dispatcher(db)

    unidades = await dispatcher.execute(
        _context(
            "SHEETSELLER_TOPVENTASUNIDADES",
            {
                "fecha_inicial": "2026-05-10",
                "fecha_final": "2026-05-11",
                "cantidad_top": 2,
                "encabezados": "si",
            },
        )
    )
    dinero = await dispatcher.execute(
        _context(
            "SHEETSELLER_TOPVENTASDINERO",
            {
                "fecha_inicial": "2026-05-10",
                "fecha_final": "2026-05-11",
                "cantidad_top": 2,
                "encabezados": "si",
            },
        )
    )

    assert unidades.values == [
        ["SKU", "ID Publicación", "Unidades vendidas"],
        ["SKU-3", "MLA3", 9],
        ["SKU-2", "MLA2", 5],
    ]
    assert unidades.meta == {
        "orders_count": 2,
        "rows_count": 2,
        "columns": "top_sales_units_mvp",
        "sku_enriched_items": 4,
    }
    assert dinero.values == [
        ["SKU", "ID Publicación", "Ventas"],
        ["SKU-1", "MLA1", 40],
        ["SKU-2", "MLA2", 15],
    ]
    assert dinero.meta == {
        "orders_count": 2,
        "rows_count": 2,
        "columns": "top_sales_revenue_mvp",
        "sku_enriched_items": 4,
        "items_without_unit_price": 1,
    }


@pytest.mark.asyncio
async def test_ventas_y_stock_combines_recent_sales_windows_with_current_stock() -> None:
    db = FakeDb()
    db["sheets_item_sku_index"].documents = {
        "seller-1:SKU-1:MLA1": _sku_index_doc("seller-1", "SKU-1", "MLA1"),
        "seller-1:SKU-2:MLA2": _sku_index_doc("seller-1", "SKU-2", "MLA2"),
    }
    db["sheets_item_formula_rows"].documents = {
        "seller-1:SKU-1:MLA1": _item_formula_row("seller-1", "SKU-1", "MLA1", stock=8),
        "seller-1:SKU-2:MLA2": _item_formula_row("seller-1", "SKU-2", "MLA2", stock=0),
    }
    db["orders"].documents = {
        "last-7": _order_doc(
            "last-7",
            seller_id="seller-1",
            status="paid",
            date_created="2026-05-30T09:00:00Z",
            total_amount=10,
            items=[{"item_id": "MLA1", "qty": 1, "unit_price": "10.00"}],
        ),
        "last-15": _order_doc(
            "last-15",
            seller_id="seller-1",
            status="paid",
            date_created="2026-05-20T09:00:00Z",
            total_amount=20,
            items=[{"item_id": "MLA1", "qty": 2, "unit_price": "10.00"}],
        ),
        "last-30": _order_doc(
            "last-30",
            seller_id="seller-1",
            status="paid",
            date_created="2026-05-05T09:00:00Z",
            total_amount=40,
            items=[{"item_id": "MLA1", "qty": 4, "unit_price": "10.00"}],
        ),
        "outside": _order_doc(
            "outside",
            seller_id="seller-1",
            status="paid",
            date_created="2026-04-30T23:59:59Z",
            total_amount=999,
            items=[{"item_id": "MLA1", "qty": 99, "unit_price": "10.00"}],
        ),
    }
    dispatcher = _order_question_dispatcher(
        db, now_fn=lambda: datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    )

    result = await dispatcher.execute(
        _context(
            "SHEETSELLER_VENTASYSTOCK",
            {
                "skus": [["sku-1"], ["sku-2"]],
                "id_publicaciones": ["MLA1", "MLA2"],
                "encabezados": "si",
            },
        )
    )

    assert result.values == [
        ["SKU", "ID Publicación", "Ventas 7 días", "Ventas 15 días", "Ventas 30 días", "Stock"],
        ["SKU-1", "MLA1", 1, 3, 7, 8],
        ["SKU-2", "MLA2", 0, 0, 0, 0],
    ]
    assert result.meta == {
        "partial_misses": 0,
        "orders_count": 3,
        "columns": "sales_and_stock_mvp",
        "sku_enriched_items": 3,
    }


@pytest.mark.asyncio
async def test_dias_desde_ultima_venta_uses_last_seller_scoped_order_date() -> None:
    db = FakeDb()
    db["sheets_item_sku_index"].documents = {
        "seller-1:SKU-1:MLA1": _sku_index_doc("seller-1", "SKU-1", "MLA1"),
        "seller-1:SKU-2:MLA2": _sku_index_doc("seller-1", "SKU-2", "MLA2"),
    }
    db["orders"].documents = {
        "latest": _order_doc(
            "latest",
            seller_id="seller-1",
            status="paid",
            date_created="2026-05-12T10:00:00Z",
            total_amount=20,
            items=[{"item_id": "MLA1", "qty": 2, "unit_price": "10.00"}],
        ),
        "older": _order_doc(
            "older",
            seller_id="seller-1",
            status="paid",
            date_created="2026-05-05T10:00:00Z",
            total_amount=10,
            items=[{"item_id": "MLA1", "qty": 1, "unit_price": "10.00"}],
        ),
        "other-seller": _order_doc(
            "other-seller",
            seller_id="seller-2",
            status="paid",
            date_created="2026-05-14T10:00:00Z",
            total_amount=999,
            items=[{"item_id": "MLA1", "qty": 99, "unit_price": "10.00"}],
        ),
    }
    dispatcher = _order_question_dispatcher(
        db, now_fn=lambda: datetime(2026, 5, 14, 12, 0, tzinfo=UTC)
    )

    result = await dispatcher.execute(
        _context(
            "SHEETSELLER_DIASDESDEULTIMAVENTA",
            {"skus": [["sku-1"], ["sku-2"]], "id_publicaciones": ["MLA1", "MLA2"]},
        )
    )

    assert result.values == [[2], [""]]
    assert result.meta == {
        "partial_misses": 1,
        "orders_count": 2,
        "sku_enriched_items": 2,
    }
    assert db["orders"].last_find_filter is not None
    assert db["orders"].last_find_filter["seller_id"] == "seller-1"
    assert db["orders"].last_find_filter["$or"][0] == {
        "date_created": {
            "$gte": datetime(1970, 1, 1, 0, 0, tzinfo=UTC),
            "$lte": datetime(2026, 5, 14, 23, 59, 59, 999999, tzinfo=UTC),
        }
    }


@pytest.mark.asyncio
async def test_productos_sin_venta_returns_current_items_without_recent_sales() -> None:
    db = FakeDb()
    db["sheets_item_sku_index"].documents = {
        "seller-1:SKU-1:MLA1": _sku_index_doc("seller-1", "SKU-1", "MLA1"),
        "seller-1:SKU-2:MLA2": _sku_index_doc("seller-1", "SKU-2", "MLA2"),
        "seller-1:SKU-3:MLA3": _sku_index_doc("seller-1", "SKU-3", "MLA3"),
    }
    db["sheets_item_formula_rows"].documents = {
        "seller-1:SKU-1:MLA1": _item_formula_row(
            "seller-1", "SKU-1", "MLA1", stock=8, title="Sold recently"
        ),
        "seller-1:SKU-2:MLA2": _item_formula_row(
            "seller-1", "SKU-2", "MLA2", stock=0, title="Old sale"
        ),
        "seller-1:SKU-3:MLA3": _item_formula_row(
            "seller-1", "SKU-3", "MLA3", stock=5, title="Never sold"
        ),
        "seller-2:SKU-2:MLA2": _item_formula_row(
            "seller-2", "SKU-2", "MLA2", stock=99, title="Wrong tenant"
        ),
    }
    db["orders"].documents = {
        "recent": _order_doc(
            "recent",
            seller_id="seller-1",
            status="paid",
            date_created="2026-05-12T10:00:00Z",
            total_amount=10,
            items=[{"item_id": "MLA1", "qty": 1, "unit_price": "10.00"}],
        ),
        "old": _order_doc(
            "old",
            seller_id="seller-1",
            status="paid",
            date_created="2026-05-01T10:00:00Z",
            total_amount=20,
            items=[{"item_id": "MLA2", "qty": 2, "unit_price": "10.00"}],
        ),
    }
    dispatcher = _order_question_dispatcher(
        db, now_fn=lambda: datetime(2026, 5, 14, 12, 0, tzinfo=UTC)
    )

    result = await dispatcher.execute(
        _context("SHEETSELLER_PRODUCTOSINVENTA", {"rango_dias": 7, "encabezados": "si"})
    )

    assert result.values == [
        ["SKU", "ID Publicación", "Título", "Stock", "Días sin venta"],
        ["SKU-2", "MLA2", "Old sale", 0, 13],
        ["SKU-3", "MLA3", "Never sold", 5, ""],
    ]
    assert result.meta == {
        "rows_count": 2,
        "orders_count": 1,
        "rango_dias": 7,
        "columns": "products_without_sales_mvp",
        "sku_enriched_items": 1,
    }


@pytest.mark.asyncio
async def test_preguntas_returns_question_table_with_date_and_hour_filters() -> None:
    db = FakeDb()
    questions = db["questions"]
    questions.documents = {
        "q1": _question_doc(
            "q1",
            seller_id="seller-1",
            status="UNANSWERED",
            date_created="2026-05-10T09:30:00Z",
            text="Still available?",
            from_user_id="buyer-1",
            item_id="MLA1",
        ),
        "q2": _question_doc(
            "q2",
            seller_id="seller-1",
            status="ANSWERED",
            date_created="2026-05-10T17:45:00Z",
            text="Can you ship today?",
            from_user_id="buyer-2",
            item_id="MLA2",
            answer={
                "text": "Yes",
                "date_created": "2026-05-10T18:00:00Z",
                "status": "ACTIVE",
            },
        ),
        "q-before-hours": _question_doc(
            "q-before-hours",
            seller_id="seller-1",
            status="ANSWERED",
            date_created="2026-05-10T08:59:59Z",
        ),
        "q-other-seller": _question_doc(
            "q-other-seller",
            seller_id="seller-2",
            status="UNANSWERED",
            date_created="2026-05-10T09:30:00Z",
        ),
    }
    dispatcher = _order_question_dispatcher(db)

    result = await dispatcher.execute(
        _context(
            "SHEETSELLER_PREGUNTAS",
            {
                "fecha_inicial": "2026-05-10",
                "fecha_final": "2026-05-10",
                "horario_inicial": "09:00",
                "horario_final": "18:00",
                "encabezados": "si",
            },
        )
    )

    assert result.values == [
        [
            "ID Pregunta",
            "Fecha",
            "Item ID",
            "Buyer ID",
            "Estado",
            "Pregunta",
            "Respuesta",
            "Fecha respuesta",
        ],
        ["q1", "2026-05-10T09:30:00Z", "MLA1", "buyer-1", "UNANSWERED", "Still available?", "", ""],
        [
            "q2",
            "2026-05-10T17:45:00Z",
            "MLA2",
            "buyer-2",
            "ANSWERED",
            "Can you ship today?",
            "Yes",
            "2026-05-10T18:00:00Z",
        ],
    ]
    assert result.meta == {"questions_count": 2, "columns": "questions_mvp"}


@pytest.mark.asyncio
async def test_preguntas_kpi_returns_canonical_question_counts_with_optional_headers() -> None:
    db = FakeDb()
    questions = db["questions"]
    questions.documents = {
        "q1": _question_doc(
            "q1",
            seller_id="seller-1",
            status="UNANSWERED",
            date_created=datetime(2026, 5, 10, 9, 0, tzinfo=UTC),
        ),
        "q2": _question_doc(
            "q2",
            seller_id="seller-1",
            status="ANSWERED",
            date_created=datetime(2026, 5, 11, 11, 0, tzinfo=UTC),
            answer={"date_created": datetime(2026, 5, 11, 13, 0, tzinfo=UTC)},
        ),
        "q-outside-range": _question_doc(
            "q-outside-range",
            seller_id="seller-1",
            status="BANNED",
            date_created=datetime(2026, 5, 12, 0, 0, 1, tzinfo=UTC),
        ),
        "q-other-seller": _question_doc(
            "q-other-seller",
            seller_id="seller-2",
            status="ANSWERED",
            date_created=datetime(2026, 5, 10, 9, 0, tzinfo=UTC),
        ),
    }
    dispatcher = _order_question_dispatcher(db)

    result = await dispatcher.execute(
        _context(
            "SHEETSELLER_PREGUNTASKPI",
            {"fecha_inicio": "2026-05-10", "fecha_final": "2026-05-11", "encabezados": "si"},
        )
    )

    assert result.values == [
        ["Métrica", "Valor"],
        ["Total preguntas", 2],
        ["Respondidas", 1],
        ["Sin responder", 1],
        ["Eliminadas/Baneadas", 0],
        ["Tiempo promedio respuesta (min)", 120],
    ]
    assert result.meta == {"questions_count": 2, "columns": "preguntas_kpi_mvp"}
    assert questions.last_find_filter is not None
    assert questions.last_find_filter["seller_id"] == "seller-1"
    assert questions.last_find_filter["$or"][0] == {
        "date_created": {
            "$gte": datetime(2026, 5, 10, 0, 0, tzinfo=UTC),
            "$lte": datetime(2026, 5, 11, 23, 59, 59, 999999, tzinfo=UTC),
        }
    }


@pytest.mark.asyncio
async def test_preguntas_kpi_matches_production_iso_string_dates() -> None:
    db = FakeDb()
    questions = db["questions"]
    questions.documents = {
        "q1": _question_doc(
            "q1",
            seller_id="seller-1",
            status="ANSWERED",
            date_created="2025-09-26T10:00:00Z",
            answer={"date_created": "2025-09-26T10:30:00Z"},
        ),
        "q2": _question_doc(
            "q2",
            seller_id="seller-1",
            status="UNANSWERED",
            date_created="2025-10-27T23:59:59Z",
        ),
        "outside": _question_doc(
            "outside",
            seller_id="seller-1",
            status="ANSWERED",
            date_created="2025-10-28T00:00:00Z",
        ),
    }
    dispatcher = _order_question_dispatcher(db)

    result = await dispatcher.execute(
        _context(
            "SHEETSELLER_PREGUNTASKPI",
            {"fecha_inicio": "2025-09-26", "fecha_final": "2025-10-27", "encabezados": "si"},
        )
    )

    assert result.values == [
        ["Métrica", "Valor"],
        ["Total preguntas", 2],
        ["Respondidas", 1],
        ["Sin responder", 1],
        ["Eliminadas/Baneadas", 0],
        ["Tiempo promedio respuesta (min)", 30],
    ]
    assert result.meta == {"questions_count": 2, "columns": "preguntas_kpi_mvp"}


@pytest.mark.asyncio
async def test_formula_api_wires_batch_b_handlers_and_keeps_other_batch_b_data_unavailable() -> (
    None
):
    now = datetime(2026, 5, 13, 17, 0, tzinfo=UTC)
    app, db, token = await _app_with_token(now=now)
    db["orders"].documents = {
        "order-1": _order_doc(
            "order-1",
            seller_id="seller-1",
            status="paid",
            date_created=datetime(2026, 5, 10, 10, 30, tzinfo=UTC),
            total_amount=100,
        ),
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        ventas = await client.post(
            "/sheets/formulas:execute",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "formula": "SHEETSELLER_VENTASTOTALES",
                "cuenta": "HOPEMOB",
                "args": {"fecha_inicial": "2026-05-10", "fecha_final": "2026-05-10"},
            },
        )
        orders_table = await client.post(
            "/sheets/formulas:execute",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "formula": "SHEETSELLER_ORDENES",
                "cuenta": "HOPEMOB",
                "args": {
                    "fecha_inicial": "2026-05-10",
                    "fecha_final": "2026-05-10",
                    "encabezados": "si",
                },
            },
        )
        not_ready = await client.post(
            "/sheets/formulas:execute",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "formula": "SHEETSELLER_COMPRADORES",
                "cuenta": "HOPEMOB",
                "args": {"id_ordenes": ["order-1"]},
            },
        )

    assert ventas.status_code == 200
    assert ventas.json() == {
        "ok": True,
        "values": [[100]],
        "meta": {"orders_count": 1, "status_filter": "todos"},
    }
    assert orders_table.status_code == 200
    assert orders_table.json()["values"] == [
        ["ID Orden", "Fecha", "Estado", "Buyer ID", "Total", "Shipment ID", "Items"],
        ["order-1", "2026-05-10T10:30:00+00:00", "paid", "buyer-1", 100, "", ""],
    ]
    assert not_ready.status_code == 200
    assert not_ready.json()["error"] == {
        "code": "DATA_UNAVAILABLE",
        "message": (
            "SHEETSELLER_COMPRADORES data is not available yet: "
            "Current canonical orders do not expose buyer/shipping address fields."
        ),
        "retryable": False,
    }


def _order_question_dispatcher(db: FakeDb, *, now_fn: Any | None = None) -> FormulaDispatcher:
    return FormulaDispatcher(
        build_order_question_formula_handlers(FormulaReadModelRepository(db=db), now_fn=now_fn)
    )


def _context(formula: str, args: dict[str, Any]) -> FormulaExecutionContext:
    return FormulaExecutionContext(
        contract=FormulaRegistry.default().find_required(formula),
        cuenta="HOPEMOB",
        seller_id="seller-1",
        seller_nickname="HOPEMOB",
        token_id="token-1",
        args=args,
        request_id="req-1",
    )


async def _app_with_token(*, now: datetime) -> tuple[FastAPI, FakeDb, str]:
    from zeler_sheets.api import build_router

    db = FakeDb()
    app = FastAPI()
    app.state.mongo_db = db
    app.include_router(
        build_router(
            clock=lambda: now,
            extension_token_pepper="test-pepper",
        )
    )
    issued = await ExtensionTokenService(
        db=db,
        token_pepper="test-pepper",
        now_fn=lambda: now,
        token_factory=lambda: "formula-secret",
    ).create_token(
        owner_user_id="user-1",
        label="Formula sheet",
        seller_scopes=[SellerScope(seller_id="seller-1", nickname="HOPEMOB")],
    )
    return app, db, issued.token_once


def _order_doc(
    order_id: str,
    *,
    seller_id: str,
    status: str,
    buyer_id: str = "buyer-1",
    date_created: Any,
    total_amount: Any,
    shipment_id: str | None = None,
    items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "_id": order_id,
        "seller_id": seller_id,
        "buyer_id": buyer_id,
        "status": status,
        "date_created": date_created,
        "shipment_id": shipment_id,
        "total_amount": total_amount,
        "items": items or [],
        "schema_version": 1,
    }


def _question_doc(
    question_id: str,
    *,
    seller_id: str,
    status: str,
    date_created: Any,
    item_id: str = "MLA1",
    text: str = "Question?",
    from_user_id: str = "buyer-1",
    answer: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "_id": question_id,
        "seller_id": seller_id,
        "item_id": item_id,
        "text": text,
        "status": status,
        "from_user_id": from_user_id,
        "date_created": date_created,
        "answer": answer,
        "schema_version": 1,
    }


def _sku_index_doc(
    seller_id: str, sku: str, item_id: str, *, variation_id: str | None = None
) -> dict[str, Any]:
    return {
        "_id": f"{seller_id}:{sku}:{item_id}:{variation_id or 'item'}",
        "seller_id": seller_id,
        "sku": sku,
        "normalized_sku": sku.upper(),
        "item_id": item_id,
        "variation_id": variation_id,
        "identity_level": "variation" if variation_id else "item",
        "schema_version": 2,
    }


def _item_formula_row(
    seller_id: str, sku: str, item_id: str, *, stock: int, title: str = ""
) -> dict[str, Any]:
    return {
        "_id": f"{seller_id}:{sku}:{item_id}",
        "seller_id": seller_id,
        "sku": sku,
        "normalized_sku": sku.upper(),
        "item_id": item_id,
        "current": {"available_quantity": stock, "title": title},
        "schema_version": 1,
    }


def _sort_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return value
