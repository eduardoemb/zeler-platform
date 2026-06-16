# ruff: noqa: S105,S106
# fmt: off

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from zeler_sheets.extension_tokens import ExtensionTokenService, SellerScope
from zeler_sheets.formulas.dispatcher import (
    FormulaDataUnavailableError,
    FormulaDispatcher,
    FormulaExecutionContext,
)
from zeler_sheets.formulas.handlers_orders_questions import (
    _OrderSkuResolver,
    build_order_question_formula_handlers,
)
from zeler_sheets.formulas.read_models import FormulaReadModelRepository
from zeler_sheets.formulas.registry import FormulaRegistry
from zeler_sheets.sheetseller_backfill import build_formula_row_doc


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


ORDER_LINE_LEGACY_HEADERS = [
    "Fecha",
    "ID Orden",
    "Título",
    "SKU",
    "ID Publicación",
    "Unidades Vendidas",
    "Precio",
    "ID Carrito",
    "% Comisión",
    "Comisión",
    "Costo Por Unidad",
    "Costo De Envío",
    "Status",
]
BUYER_ADDRESS_LEGACY_HEADERS = [
    "Nombre Comprador",
    "Calle",
    "Número",
    "Colonia",
    "Código Postal",
    "Ciudad",
    "Estado",
    "País",
]

PRODUCTOS_SIN_VENTA_LEGACY_HEADERS = [
    "Título",
    "Código ML",
    "ID Publicación",
    "SKU",
    "Stock Actual",
    "Fecha Ultimo Cambio",
    "Status Actual",
    "Envío A Cargo De",
]


def _formula_table_contract(rows: list[list[Any]], *, header_rows: int = 1) -> list[list[Any]]:
    normalized: list[list[Any]] = []
    for index, row in enumerate(rows):
        if index < header_rows or not row or str(row[0]).strip() == "":
            normalized.append(row)
            continue
        normalized.append([row[0], *("NA" if cell == "" else cell for cell in row[1:])])
    return normalized


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
            items=[
                {
                    "seller_sku": "sku-2",
                    "item": {"id": "MLA2", "title": "Second order item"},
                    "quantity": 1,
                    "unit_price": "75.50",
                }
            ],
        ),
        "order-1": _order_doc(
            "order-1",
            seller_id="seller-1",
            status="paid",
            buyer_id="buyer-1",
            date_created="2026-05-10T10:30:00Z",
            total_amount="100.00",
            shipment_id="shipment-1",
            items=[
                {
                    "sku": "sku-1",
                    "item_id": "MLA1",
                    "title": "First order item",
                    "quantity": 2,
                    "unit_price": "50.00",
                }
            ],
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
            "ZELERDATA_ORDENES",
            {
                "fecha_inicial": "2026-05-10",
                "fecha_final": "2026-05-11",
                "estado": "paid",
                "compradores": [["buyer-1"], ["buyer-2"]],
                "encabezados": "si",
            },
        )
    )

    assert result.values == _formula_table_contract([
        ORDER_LINE_LEGACY_HEADERS + BUYER_ADDRESS_LEGACY_HEADERS,
        [
            "2026-05-10T10:30:00Z",
            "order-1",
            "First order item",
            "SKU-1",
            "MLA1",
            2,
            50,
            "",
            "",
            "",
            "",
            "",
            "paid",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
        ],
        [
            "2026-05-11T08:15:00Z",
            "order-2",
            "Second order item",
            "SKU-2",
            "MLA2",
            1,
            75.5,
            "",
            "",
            "",
            "",
            "",
            "paid",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
        ],
    ])
    assert result.meta == {
        "orders_count": 2,
        "status_filter": "paid",
        "buyer_filter_count": 2,
        "columns": "legacy_order_lines_with_buyers",
    }


@pytest.mark.asyncio
async def test_ordenes_keeps_unresolved_sku_lines_and_sku_filter_omits_them() -> None:
    db = FakeDb()
    db["orders"].documents = {
        "unresolved-sku": _order_doc(
            "unresolved-sku",
            seller_id="seller-1",
            status="paid",
            buyer_id="buyer-1",
            date_created=datetime(2026, 5, 10, 8, 30, tzinfo=UTC),
            total_amount="59.97",
            items=[
                {
                    "item_id": "MLA-UNRESOLVED",
                    "title": "Unresolved SKU item",
                    "quantity": 3,
                    "unit_price": "19.99",
                }
            ],
        )
    }
    dispatcher = _order_question_dispatcher(db)

    orders_table = await dispatcher.execute(
        _context(
            "ZELERDATA_ORDENES",
            {
                "fecha_inicial": "2026-05-10",
                "fecha_final": "2026-05-10",
                "estado": "paid",
                "encabezados": "si",
            },
        )
    )
    filtered_table = await dispatcher.execute(
        _context(
            "ZELERDATA_ORDENESPORSKU",
            {
                "skus": "sku-missing",
                "fecha_inicial": "2026-05-10",
                "fecha_final": "2026-05-10",
                "estado": "paid",
                "encabezados": "si",
            },
        )
    )

    assert orders_table.values == _formula_table_contract([
        ORDER_LINE_LEGACY_HEADERS,
        [
            "2026-05-10T08:30:00+00:00",
            "unresolved-sku",
            "Unresolved SKU item",
            "",
            "MLA-UNRESOLVED",
            3,
            19.99,
            "",
            "",
            "",
            "",
            "",
            "paid",
        ],
    ])
    assert orders_table.meta == {
        "orders_count": 1,
        "status_filter": "paid",
        "buyer_filter_count": 0,
        "columns": "legacy_order_lines",
    }
    assert filtered_table.values == [ORDER_LINE_LEGACY_HEADERS]
    assert filtered_table.meta == {
        "orders_count": 0,
        "status_filter": "paid",
        "buyer_filter_count": 0,
        "sku_filter_count": 1,
        "columns": "legacy_order_lines",
    }


@pytest.mark.asyncio
async def test_ordenes_compradores_boolean_flag_adds_buyer_columns_without_filtering() -> None:
    db = FakeDb()
    db["orders"].documents = {
        "order-1": _order_doc(
            "order-1",
            seller_id="seller-1",
            status="paid",
            buyer_id="buyer-1",
            date_created="2026-05-10T10:30:00Z",
            total_amount="100.00",
            shipment_id="shipment-1",
            items=[{"sku": "sku-1", "item_id": "MLA1", "title": "First item", "quantity": 2}],
        ),
        "order-2": _order_doc(
            "order-2",
            seller_id="seller-1",
            status="paid",
            buyer_id="buyer-2",
            date_created="2026-05-11T08:15:00Z",
            total_amount="75.50",
            items=[{"seller_sku": "sku-2", "item": {"id": "MLA2"}, "quantity": 1}],
        ),
    }
    db["shipments"].documents = {
        "shipment-1": {
            "_id": "shipment-1",
            "seller_id": "seller-1",
            "receiver_address": {
                "name": "SNAPSHOT_BUYER_OK",
                "street_name": "SNAPSHOT_STREET_OK",
                "street_number": "SNAPSHOT_NUMBER_OK",
                "neighborhood": "SNAPSHOT_NEIGHBORHOOD_OK",
                "zip_code": "SNAPSHOT_ZIP_OK",
                "city": "SNAPSHOT_CITY_OK",
                "state": "SNAPSHOT_STATE_OK",
                "country": "SNAPSHOT_COUNTRY_OK",
            },
        }
    }
    dispatcher = _order_question_dispatcher(db)

    result = await dispatcher.execute(
        _context(
            "ZELERDATA_ORDENES",
            {
                "fecha_inicial": "2026-05-10",
                "fecha_final": "2026-05-11",
                "estado": "paid",
                "compradores": "verdadero",
                "encabezados": "si",
            },
        )
    )

    assert result.values == _formula_table_contract([
        ORDER_LINE_LEGACY_HEADERS + BUYER_ADDRESS_LEGACY_HEADERS,
        [
            "2026-05-10T10:30:00Z",
            "order-1",
            "First item",
            "SKU-1",
            "MLA1",
            2,
            "",
            "",
            "",
            "",
            "",
            "",
            "paid",
            "SNAPSHOT_BUYER_OK",
            "SNAPSHOT_STREET_OK",
            "SNAPSHOT_NUMBER_OK",
            "SNAPSHOT_NEIGHBORHOOD_OK",
            "SNAPSHOT_ZIP_OK",
            "SNAPSHOT_CITY_OK",
            "SNAPSHOT_STATE_OK",
            "SNAPSHOT_COUNTRY_OK",
        ],
        [
            "2026-05-11T08:15:00Z",
            "order-2",
            "",
            "SKU-2",
            "MLA2",
            1,
            "",
            "",
            "",
            "",
            "",
            "",
            "paid",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
        ],
    ])
    assert result.meta == {
        "orders_count": 2,
        "status_filter": "paid",
        "buyer_filter_count": 0,
        "columns": "legacy_order_lines_with_buyers",
    }


@pytest.mark.asyncio
async def test_order_tables_emit_na_for_unavailable_fields_and_missing_buyers() -> None:
    db = FakeDb()
    db["orders"].documents = {
        "order-1": _order_doc(
            "order-1",
            seller_id="seller-1",
            status="paid",
            buyer_id="buyer-1",
            date_created="2026-05-10T10:30:00Z",
            total_amount="100.00",
            items=[{"sku": "sku-1", "item_id": "MLA1", "title": "First item", "quantity": 2}],
        )
    }
    dispatcher = _order_question_dispatcher(db)

    result = await dispatcher.execute(
        _context(
            "ZELERDATA_ORDENES",
            {
                "fecha_inicial": "2026-05-10",
                "fecha_final": "2026-05-10",
                "estado": "paid",
                "compradores": "si",
                "encabezados": "si",
            },
        )
    )

    assert result.values == [
        ORDER_LINE_LEGACY_HEADERS + BUYER_ADDRESS_LEGACY_HEADERS,
        [
            "2026-05-10T10:30:00Z",
            "order-1",
            "First item",
            "SKU-1",
            "MLA1",
            2,
            "NA",
            "NA",
            "NA",
            "NA",
            "NA",
            "NA",
            "paid",
            "NA",
            "NA",
            "NA",
            "NA",
            "NA",
            "NA",
            "NA",
            "NA",
        ],
    ]


@pytest.mark.parametrize(
    ("formula_name", "formula_args"),
    [
        ("ZELERDATA_ORDENES", {}),
        ("ZELERDATA_ORDENESPORSKU", {"skus": [["sku-1"], ["sku-2"]]}),
    ],
)
@pytest.mark.parametrize(
    ("compradores", "expected_headers"),
    [
        ("", ORDER_LINE_LEGACY_HEADERS),
        ("verdadero", ORDER_LINE_LEGACY_HEADERS + BUYER_ADDRESS_LEGACY_HEADERS),
    ],
)
@pytest.mark.asyncio
async def test_order_tables_preserve_meli_pack_id_as_id_carrito_for_buyer_variants(
    formula_name: str,
    formula_args: dict[str, Any],
    compradores: str,
    expected_headers: list[str],
) -> None:
    db = FakeDb()
    db["orders"].documents = {
        "packed-order": _order_doc(
            "packed-order",
            seller_id="seller-1",
            status="paid",
            buyer_id="buyer-1",
            date_created="2026-05-10T10:30:00Z",
            total_amount="100.00",
            shipment_id="shipment-1",
            items=[{"sku": "sku-1", "item_id": "MLA1", "title": "Packed item", "quantity": 2}],
        )
        | {"meli_pack_id": "123"},
        "missing-pack-order": _order_doc(
            "missing-pack-order",
            seller_id="seller-1",
            status="paid",
            buyer_id="buyer-1",
            date_created="2026-05-10T11:30:00Z",
            total_amount="50.00",
            shipment_id="shipment-2",
            items=[
                {"sku": "sku-2", "item_id": "MLA2", "title": "No pack item", "quantity": 1}
            ],
        ),
    }
    db["shipments"].documents = {
        "shipment-1": {
            "_id": "shipment-1",
            "seller_id": "seller-1",
            "receiver_address": {
                "name": "SNAPSHOT_BUYER_OK",
                "street_name": "SNAPSHOT_STREET_OK",
                "street_number": "SNAPSHOT_NUMBER_OK",
                "neighborhood": "SNAPSHOT_NEIGHBORHOOD_OK",
                "zip_code": "SNAPSHOT_ZIP_OK",
                "city": "SNAPSHOT_CITY_OK",
                "state": "SNAPSHOT_STATE_OK",
                "country": "SNAPSHOT_COUNTRY_OK",
            },
        }
    }
    dispatcher = _order_question_dispatcher(db)

    result = await dispatcher.execute(
        _context(
            formula_name,
            {
                "fecha_inicial": "2026-05-10",
                "fecha_final": "2026-05-10",
                "compradores": compradores,
                "encabezados": "si",
            }
            | formula_args,
        )
    )

    assert result.values[0] == expected_headers
    assert [row[7] for row in result.values[1:]] == ["123", "NA"]
    assert [row[1] for row in result.values[1:]] == ["packed-order", "missing-pack-order"]
    assert [row[7] for row in result.values[1:]] != ["packed-order", "shipment-2"]
    assert all(len(row) == len(expected_headers) for row in result.values)
    if compradores == "verdadero":
        assert result.values[1][13:] == [
            "SNAPSHOT_BUYER_OK",
            "SNAPSHOT_STREET_OK",
            "SNAPSHOT_NUMBER_OK",
            "SNAPSHOT_NEIGHBORHOOD_OK",
            "SNAPSHOT_ZIP_OK",
            "SNAPSHOT_CITY_OK",
            "SNAPSHOT_STATE_OK",
            "SNAPSHOT_COUNTRY_OK",
        ]
        assert result.values[2][13:] == ["NA"] * len(BUYER_ADDRESS_LEGACY_HEADERS)
    else:
        assert "Nombre Comprador" not in result.values[0]


@pytest.mark.asyncio
async def test_productos_sin_venta_uses_shipping_payer_and_na_for_deferred_change_date() -> None:
    db = FakeDb()
    db["sheets_item_formula_rows"].documents = {
        "seller-1-sku-1-mla1": _item_formula_row(
            "seller-1", "SKU-1", "MLA1", stock=4, title="Unsold item"
        )
        | {
            "sku": "sku-1",
            "inventory_id": None,
            "current": {
                "title": "Unsold item",
                "available_quantity": 4,
                "status": "active",
                "shipping_payer": "Comprador",
            },
        },
    }
    dispatcher = _order_question_dispatcher(
        db, now_fn=lambda: datetime(2026, 5, 14, 12, 0, tzinfo=UTC)
    )

    result = await dispatcher.execute(
        _context("ZELERDATA_PRODUCTOSINVENTA", {"rango_dias": 7, "encabezados": "si"})
    )

    assert result.values == [
        PRODUCTOS_SIN_VENTA_LEGACY_HEADERS,
        ["Unsold item", "NA", "MLA1", "sku-1", 4, "NA", "active", "Comprador"],
    ]


@pytest.mark.parametrize("compradores", ["no", "falso", "false", "0", False, 0])
@pytest.mark.asyncio
async def test_ordenes_compradores_false_like_values_do_not_filter_or_add_buyer_columns(
    compradores: Any,
) -> None:
    db = FakeDb()
    db["orders"].documents = {
        "order-1": _order_doc(
            "order-1",
            seller_id="seller-1",
            status="paid",
            buyer_id="buyer-1",
            date_created="2026-05-10T10:30:00Z",
            total_amount="100.00",
            items=[{"sku": "sku-1", "item_id": "MLA1", "title": "First item", "quantity": 2}],
        ),
        "order-2": _order_doc(
            "order-2",
            seller_id="seller-1",
            status="paid",
            buyer_id="buyer-2",
            date_created="2026-05-11T08:15:00Z",
            total_amount="75.50",
            items=[{"seller_sku": "sku-2", "item": {"id": "MLA2"}, "quantity": 1}],
        ),
    }
    dispatcher = _order_question_dispatcher(db)

    result = await dispatcher.execute(
        _context(
            "ZELERDATA_ORDENES",
            {
                "fecha_inicial": "2026-05-10",
                "fecha_final": "2026-05-11",
                "estado": "paid",
                "compradores": compradores,
                "encabezados": "si",
            },
        )
    )

    assert result.values == _formula_table_contract([
        ORDER_LINE_LEGACY_HEADERS,
        [
            "2026-05-10T10:30:00Z",
            "order-1",
            "First item",
            "SKU-1",
            "MLA1",
            2,
            "",
            "",
            "",
            "",
            "",
            "",
            "paid",
        ],
        [
            "2026-05-11T08:15:00Z",
            "order-2",
            "",
            "SKU-2",
            "MLA2",
            1,
            "",
            "",
            "",
            "",
            "",
            "",
            "paid",
        ],
    ])
    assert result.meta == {
        "orders_count": 2,
        "status_filter": "paid",
        "buyer_filter_count": 0,
        "columns": "legacy_order_lines",
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
            "ZELERDATA_VENTASTOTALES",
            {"fecha_inicial": "2026-05-10", "fecha_final": "2026-05-11", "estado": "todos"},
        )
    )
    paid_only = await dispatcher.execute(
        _context(
            "ZELERDATA_VENTASTOTALES",
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
            "ZELERDATA_VENTASTOTALES",
            {"fecha_inicial": "2025-04-30", "fecha_final": "2025-05-01", "estado": "todos"},
        )
    )
    cancelled = await dispatcher.execute(
        _context(
            "ZELERDATA_VENTASTOTALES",
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
async def test_ventas_totales_interprets_date_bounds_in_seller_timezone() -> None:
    db = FakeDb()
    orders = db["orders"]
    orders.documents = {
        "previous-local-day": _order_doc(
            "previous-local-day",
            seller_id="seller-1",
            status="paid",
            date_created=datetime(2026, 5, 1, 5, 59, 59, 999999, tzinfo=UTC),
            total_amount=999,
        ),
        "local-day-start": _order_doc(
            "local-day-start",
            seller_id="seller-1",
            status="paid",
            date_created=datetime(2026, 5, 1, 6, 0, tzinfo=UTC),
            total_amount=100,
        ),
        "local-day-end": _order_doc(
            "local-day-end",
            seller_id="seller-1",
            status="paid",
            date_created=datetime(2026, 5, 2, 5, 59, 59, 999999, tzinfo=UTC),
            total_amount=25,
        ),
        "next-local-day": _order_doc(
            "next-local-day",
            seller_id="seller-1",
            status="paid",
            date_created=datetime(2026, 5, 2, 6, 0, tzinfo=UTC),
            total_amount=999,
        ),
    }
    dispatcher = _order_question_dispatcher(db)

    result = await dispatcher.execute(
        _context(
            "ZELERDATA_VENTASTOTALES",
            {"fecha_inicial": "2026-05-01", "fecha_final": "2026-05-01", "estado": "paid"},
            seller_timezone="America/Mexico_City",
        )
    )

    assert result.values == [[125]]
    assert result.meta == {"orders_count": 2, "status_filter": "paid"}
    assert orders.last_find_filter is not None
    assert orders.last_find_filter["$or"][0] == {
        "date_created": {
            "$gte": datetime(2026, 5, 1, 6, 0, tzinfo=UTC),
            "$lte": datetime(2026, 5, 2, 5, 59, 59, 999999, tzinfo=UTC),
        }
    }


@pytest.mark.asyncio
async def test_ordenes_renders_output_dates_in_seller_timezone() -> None:
    db = FakeDb()
    db["orders"].documents = {
        "order-local": _order_doc(
            "order-local",
            seller_id="seller-1",
            status="paid",
            date_created=datetime(2026, 5, 1, 6, 30, tzinfo=UTC),
            total_amount=100,
            items=[{"sku": "sku-1", "item_id": "MLA1", "title": "Local item", "quantity": 1}],
        ),
    }
    dispatcher = _order_question_dispatcher(db)

    result = await dispatcher.execute(
        _context(
            "ZELERDATA_ORDENES",
            {"fecha_inicial": "2026-05-01", "fecha_final": "2026-05-01", "encabezados": "si"},
            seller_timezone="America/Mexico_City",
        )
    )

    assert result.values == _formula_table_contract([
        ORDER_LINE_LEGACY_HEADERS,
        [
            "2026-05-01T00:30:00-06:00",
            "order-local",
            "Local item",
            "SKU-1",
            "MLA1",
            1,
            "",
            "",
            "",
            "",
            "",
            "",
            "paid",
        ],
    ])


@pytest.mark.asyncio
async def test_ordenes_filters_and_renders_ui_previous_day_in_seller_timezone() -> None:
    db = FakeDb()
    orders = db["orders"]
    orders.documents = {
        "order-ui-local": _order_doc(
            "order-ui-local",
            seller_id="seller-1",
            status="paid",
            date_created=datetime(2026, 6, 1, 6, 30, 41, tzinfo=UTC),
            total_amount=100,
            items=[
                {
                    "sku": "sku-1",
                    "item_id": "MLM1",
                    "title": "UI local item",
                    "quantity": 1,
                    "unit_price": 100,
                }
            ],
        )
    }
    dispatcher = _order_question_dispatcher(db)

    previous_local_day = await dispatcher.execute(
        _context(
            "ZELERDATA_ORDENES",
            {"fecha_inicial": "2026-05-31", "fecha_final": "2026-05-31"},
            seller_timezone="America/Tijuana",
        )
    )
    next_local_day = await dispatcher.execute(
        _context(
            "ZELERDATA_ORDENES",
            {"fecha_inicial": "2026-06-01", "fecha_final": "2026-06-01"},
            seller_timezone="America/Tijuana",
        )
    )

    assert previous_local_day.values[0][0] == "2026-05-31T23:30:41-07:00"
    assert previous_local_day.values[0][1] == "order-ui-local"
    assert next_local_day.values == []
    assert orders.find_filters[-1]["$or"][0] == {
        "date_created": {
            "$gte": datetime(2026, 6, 1, 7, 0, tzinfo=UTC),
            "$lte": datetime(2026, 6, 2, 6, 59, 59, 999999, tzinfo=UTC),
        }
    }


@pytest.mark.asyncio
async def test_ventas_totales_falls_back_to_utc_for_missing_seller_timezone() -> None:
    db = FakeDb()
    orders = db["orders"]
    orders.documents = {
        "utc-day-start": _order_doc(
            "utc-day-start",
            seller_id="seller-1",
            status="paid",
            date_created=datetime(2026, 5, 1, 0, 0, tzinfo=UTC),
            total_amount=100,
        ),
        "next-utc-day": _order_doc(
            "next-utc-day",
            seller_id="seller-1",
            status="paid",
            date_created=datetime(2026, 5, 2, 0, 0, tzinfo=UTC),
            total_amount=999,
        ),
    }
    dispatcher = _order_question_dispatcher(db)

    result = await dispatcher.execute(
        _context(
            "ZELERDATA_VENTASTOTALES",
            {"fecha_inicial": "2026-05-01", "fecha_final": "2026-05-01"},
        )
    )

    assert result.values == [[100]]
    assert result.meta == {"orders_count": 1, "status_filter": "todos"}
    assert orders.last_find_filter is not None
    assert orders.last_find_filter["$or"][0] == {
        "date_created": {
            "$gte": datetime(2026, 5, 1, 0, 0, tzinfo=UTC),
            "$lte": datetime(2026, 5, 1, 23, 59, 59, 999999, tzinfo=UTC),
        }
    }


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
            items=[
                {
                    "sku": "sku-1",
                    "item_id": "MLA1",
                    "title": "First SKU item",
                    "quantity": 1,
                    "unit_price": 30,
                }
            ],
        ),
        "order-sku-2": _order_doc(
            "order-sku-2",
            seller_id="seller-1",
            status="paid",
            buyer_id="buyer-2",
            date_created=datetime(2026, 5, 10, 9, 0, tzinfo=UTC),
            total_amount=40,
            items=[
                {
                    "seller_sku": "sku-2",
                    "item": {"id": "MLA2", "title": "Second SKU item"},
                    "quantity": 3,
                    "unit_price": 40,
                }
            ],
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
            "ZELERDATA_ORDENESPORSKU",
            {
                "skus": [["sku-2"], ["sku-1"]],
                "fecha_inicial": "2026-05-10",
                "fecha_final": "2026-05-10",
                "estado": "todos",
                "encabezados": "si",
            },
        )
    )

    assert result.values == _formula_table_contract([
        ORDER_LINE_LEGACY_HEADERS,
        [
            "2026-05-10T09:00:00+00:00",
            "order-sku-2",
            "Second SKU item",
            "SKU-2",
            "MLA2",
            3,
            40,
            "",
            "",
            "",
            "",
            "",
            "paid",
        ],
        [
            "2026-05-10T08:00:00+00:00",
            "order-sku-1",
            "First SKU item",
            "SKU-1",
            "MLA1",
            1,
            30,
            "",
            "",
            "",
            "",
            "",
            "paid",
        ],
    ])
    assert result.meta == {
        "orders_count": 2,
        "status_filter": "todos",
        "buyer_filter_count": 0,
        "sku_filter_count": 2,
        "columns": "legacy_order_lines",
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
    db["sheets_item_formula_rows"].documents = {
        "seller-1:SKU-1:MLA1": _item_formula_row(
            "seller-1", "SKU-1", "MLA1", stock=4, title="Enriched title"
        ),
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
            "ZELERDATA_ORDENESPORSKU",
            {
                "skus": [["sku-1"], ["amb-1"]],
                "fecha_inicial": "2026-05-10",
                "fecha_final": "2026-05-10",
                "estado": "todos",
                "encabezados": "si",
            },
        )
    )

    assert result.values == _formula_table_contract([
        ORDER_LINE_LEGACY_HEADERS,
        [
            "2026-05-10T08:00:00+00:00",
            "enriched",
            "Enriched title",
            "SKU-1",
            "MLA1",
            2,
            15,
            "",
            "",
            "",
            "",
            "",
            "paid",
        ],
    ])
    assert result.meta == {
        "orders_count": 1,
        "status_filter": "todos",
        "buyer_filter_count": 0,
        "sku_filter_count": 2,
        "columns": "legacy_order_lines",
    }
    assert db["sheets_item_sku_index"].last_find_filter == {
        "seller_id": "seller-1",
        "item_id": {"$in": ["MLA1", "MLA2"]},
    }


@pytest.mark.asyncio
async def test_order_tables_use_listing_fixed_fee_projection_without_seller_cost_lookup() -> None:
    db = FakeDb()
    db["orders"].documents = {
        "order-1": _order_doc(
            "order-1",
            seller_id="seller-1",
            status="paid",
            date_created=datetime(2026, 5, 10, 8, 0, tzinfo=UTC),
            total_amount=39,
            items=[
                {"sku": "sku-1", "item_id": "MLA1", "variation_id": 101, "qty": 2},
                {"sku": "sku-2", "item_id": "MLA2", "qty": 1, "sale_fee": 7},
            ],
        )
    }
    db["sheets_item_formula_rows"].documents = {
        "row-1": {
            "_id": "row-1",
            "seller_id": "seller-1",
            "sku": "sku-1",
            "normalized_sku": "SKU-1",
            "item_id": "MLA1",
            "variation_id": "101",
            "current": {
                "base_price": 12345.67,
                "category_id": "MLA-CAT",
                "currency_id": "ARS",
                "site_id": "MLA",
                "listing_type_id": "gold_special",
                "shipping_mode": "me2",
                "logistic_type": "fulfillment",
                "listing_price_fixed_fee": {
                    "source": "/sites/{site}/listing_prices",
                    "fixed_fee": 1350.25,
                    "currency_id": "ARS",
                    "synced_at": datetime(2026, 6, 4, tzinfo=UTC),
                    "params": {
                        "site_id": "MLA",
                        "category_id": "MLA-CAT",
                        "price": 12345.67,
                        "currency_id": "ARS",
                        "listing_type_id": "gold_special",
                        "shipping_mode": "me2",
                        "logistic_type": "fulfillment",
                    },
                }
            },
        },
        "row-2": {
            "_id": "row-2",
            "seller_id": "seller-1",
            "sku": "sku-2",
            "normalized_sku": "SKU-2",
            "item_id": "MLA2",
            "current": {
                "listing_price_fixed_fee": {
                    "source": "/items/{id}/sale_price",
                    "fixed_fee": 7,
                    "currency_id": "ARS",
                    "synced_at": datetime(2026, 6, 4, tzinfo=UTC),
                    "params": {},
                }
            },
        },
    }
    db["seller_unit_costs"].documents = {
        "item-cost": _unit_cost_doc("item-cost", item_id="MLA1", unit_cost="20"),
        "variation-cost": _unit_cost_doc(
            "variation-cost", item_id="MLA1", variation_id="101", unit_cost="25.50"
        ),
        "expired-sku": _unit_cost_doc(
            "expired-sku",
            normalized_sku="SKU-2",
            unit_cost="9",
            effective_to=datetime(2026, 5, 1, tzinfo=UTC),
        ),
    }
    dispatcher = _order_question_dispatcher(db)

    orders = await dispatcher.execute(
        _context(
            "ZELERDATA_ORDENES",
            {"fecha_inicial": "2026-05-10", "fecha_final": "2026-05-10"},
        )
    )
    by_sku = await dispatcher.execute(
        _context(
            "ZELERDATA_ORDENESPORSKU",
            {
                "skus": "sku-1",
                "fecha_inicial": "2026-05-10",
                "fecha_final": "2026-05-10",
            },
        )
    )

    assert [row[8:11] for row in orders.values] == [["NA", "NA", 1350.25], ["NA", "NA", "NA"]]
    assert by_sku.values[0][8:11] == ["NA", "NA", 1350.25]
    assert db["seller_unit_costs"].find_filters == []


@pytest.mark.asyncio
async def test_order_tables_render_realized_sale_fee_math_and_listing_fixed_fee_unit_cost() -> None:
    db = FakeDb()
    db["orders"].documents = {
        "order-1": _order_doc(
            "order-1",
            seller_id="seller-1",
            status="paid",
            date_created=datetime(2026, 5, 10, 8, 0, tzinfo=UTC),
            total_amount=Decimal("188.44"),
            items=[
                {
                    "sku": "sku-1",
                    "item_id": "MLA1",
                    "qty": 2,
                    "unit_price": Decimal("94.22"),
                    "sale_fee": Decimal("13.2"),
                    "sale_fee_source": "/orders/{id}",
                    "sale_fee_synced_at": datetime(2026, 5, 10, 8, 1, tzinfo=UTC),
                },
                {"sku": "sku-2", "item_id": "MLA2", "qty": 1, "unit_price": 50},
            ],
        )
    }
    db["sheets_item_formula_rows"].documents = {
        "row-1": _order_formula_row(
            "sku-1",
            "SKU-1",
            "MLA1",
            base_price=100,
            category_id="MLA-CAT",
            currency_id="ARS",
            site_id="MLA",
            listing_type_id="gold_special",
            shipping_mode="me2",
            logistic_type="fulfillment",
            listing_price_fixed_fee={
                "source": "/sites/{site}/listing_prices",
                "fixed_fee": 8,
                "currency_id": "ARS",
                "synced_at": datetime(2026, 6, 4, tzinfo=UTC),
                "params": {
                    "site_id": "MLA",
                    "category_id": "MLA-CAT",
                    "price": 100,
                    "currency_id": "ARS",
                    "listing_type_id": "gold_special",
                    "shipping_mode": "me2",
                    "logistic_type": "fulfillment",
                },
            },
        ),
        "row-2": _order_formula_row(
            "sku-2",
            "SKU-2",
            "MLA2",
            base_price=50,
            category_id="MLA-CAT",
            currency_id="ARS",
            site_id="MLA",
            listing_type_id="gold_special",
            shipping_mode="me2",
            logistic_type="fulfillment",
            listing_price_fixed_fee={
                "source": "/sites/{site}/listing_prices",
                "fixed_fee": 10,
                "currency_id": "ARS",
                "synced_at": datetime(2026, 6, 4, tzinfo=UTC),
                "params": {
                    "site_id": "MLA",
                    "category_id": "MLA-CAT",
                    "price": 50,
                    "currency_id": "ARS",
                    "listing_type_id": "gold_special",
                    "shipping_mode": "me2",
                    "logistic_type": "fulfillment",
                },
            },
        )
    }
    dispatcher = _order_question_dispatcher(db)

    result = await dispatcher.execute(
        _context(
            "ZELERDATA_ORDENES",
            {"fecha_inicial": "2026-05-10", "fecha_final": "2026-05-10"},
        )
    )

    assert result.values[0][8:11] == ["14%", 26.4, 8]
    assert result.values[1][8:11] == ["NA", "NA", 10]


@pytest.mark.asyncio
async def test_ordenes_keeps_full_commission_percent_for_multi_unit_order_item() -> None:
    db = FakeDb()
    db["orders"].documents = {
        "order-1": _order_doc(
            "order-1",
            seller_id="seller-1",
            status="paid",
            date_created=datetime(2026, 6, 1, 8, 0, tzinfo=UTC),
            total_amount=200,
            items=[
                {
                    "sku": "sku-1",
                    "item_id": "MLM1",
                    "title": "Multi unit item",
                    "quantity": 2,
                    "unit_price": 100,
                    "sale_fee": 15,
                    "sale_fee_source": "/orders/{id}",
                    "sale_fee_synced_at": datetime(2026, 6, 1, 8, 1, tzinfo=UTC),
                }
            ],
        )
    }
    dispatcher = _order_question_dispatcher(db)

    result = await dispatcher.execute(
        _context(
            "ZELERDATA_ORDENES",
            {"fecha_inicial": "2026-06-01", "fecha_final": "2026-06-01"},
        )
    )

    assert result.values[0][8:10] == ["15%", 30]


@pytest.mark.asyncio
async def test_ordenes_formats_decimal_commission_percent_as_whole_percentage() -> None:
    db = FakeDb()
    db["orders"].documents = {
        "order-1": _order_doc(
            "order-1",
            seller_id="seller-1",
            status="paid",
            date_created=datetime(2026, 6, 1, 8, 0, tzinfo=UTC),
            total_amount=Decimal("94.22"),
            items=[
                {
                    "sku": "sku-1",
                    "item_id": "MLM1",
                    "title": "Decimal commission item",
                    "quantity": 1,
                    "unit_price": Decimal("94.22"),
                    "sale_fee": Decimal("13.2"),
                    "sale_fee_source": "/orders/{id}",
                    "sale_fee_synced_at": datetime(2026, 6, 1, 8, 1, tzinfo=UTC),
                }
            ],
        )
    }
    dispatcher = _order_question_dispatcher(db)

    result = await dispatcher.execute(
        _context(
            "ZELERDATA_ORDENES",
            {"fecha_inicial": "2026-06-01", "fecha_final": "2026-06-01"},
        )
    )

    assert result.values[0][8] == "14%"


@pytest.mark.asyncio
async def test_ordenes_repeats_full_commission_percent_for_repeated_listing_rows() -> None:
    db = FakeDb()
    db["orders"].documents = {
        "order-1": _order_doc(
            "order-1",
            seller_id="seller-1",
            status="paid",
            date_created=datetime(2026, 6, 1, 8, 0, tzinfo=UTC),
            total_amount=500,
            items=[
                {
                    "sku": "sku-1",
                    "item_id": "MLM1",
                    "title": "Repeated listing item",
                    "quantity": 2,
                    "unit_price": 100,
                    "sale_fee": 15,
                    "sale_fee_source": "/orders/{id}",
                    "sale_fee_synced_at": datetime(2026, 6, 1, 8, 1, tzinfo=UTC),
                },
                {
                    "sku": "sku-1",
                    "item_id": "MLM1",
                    "title": "Repeated listing item",
                    "quantity": 3,
                    "unit_price": 100,
                    "sale_fee": 15,
                    "sale_fee_source": "/orders/{id}",
                    "sale_fee_synced_at": datetime(2026, 6, 1, 8, 2, tzinfo=UTC),
                },
            ],
        )
    }
    dispatcher = _order_question_dispatcher(db)

    result = await dispatcher.execute(
        _context(
            "ZELERDATA_ORDENES",
            {"fecha_inicial": "2026-06-01", "fecha_final": "2026-06-01"},
        )
    )

    assert [row[8:10] for row in result.values] == [["15%", 30], ["15%", 45]]


@pytest.mark.asyncio
async def test_order_tables_return_na_for_invalid_listing_fixed_fee_projection() -> None:
    synced_at = datetime(2026, 6, 4, tzinfo=UTC)
    projection: dict[str, Any] = {
        "source": "/sites/{site}/listing_prices",
        "fixed_fee": 1350.25,
        "currency_id": "ARS",
        "synced_at": synced_at,
        "params": {
            "site_id": "MLA",
            "category_id": "MLA-CAT",
            "price": 12345.67,
            "currency_id": "ARS",
            "listing_type_id": "gold_special",
        },
    }
    db = FakeDb()
    db["orders"].documents = {
        "order-1": _order_doc(
            "order-1",
            seller_id="seller-1",
            status="paid",
            date_created=datetime(2026, 5, 10, 8, 0, tzinfo=UTC),
            total_amount=39,
            items=[
                {"sku": "sku-1", "item_id": "MLA1", "qty": 1},
                {"sku": "sku-2", "item_id": "MLA2", "qty": 1},
                {"sku": "sku-3", "item_id": "MLA3", "qty": 1},
                {"sku": "sku-4", "item_id": "MLA4", "qty": 1},
                {"sku": "sku-5", "item_id": "MLA5", "qty": 1},
            ],
        )
    }
    db["sheets_item_formula_rows"].documents = {
        "currency-mismatch": _order_formula_row(
            "sku-1",
            "SKU-1",
            "MLA1",
            base_price=12345.67,
            category_id="MLA-CAT",
            currency_id="ARS",
            site_id="MLA",
            listing_type_id="gold_special",
            listing_price_fixed_fee=projection
            | {"params": projection["params"] | {"currency_id": "USD"}},
        ),
        "price-mismatch": _order_formula_row(
            "sku-2",
            "SKU-2",
            "MLA2",
            base_price=99999,
            category_id="MLA-CAT",
            currency_id="ARS",
            site_id="MLA",
            listing_type_id="gold_special",
            listing_price_fixed_fee=projection,
        ),
        "category-mismatch": _order_formula_row(
            "sku-3",
            "SKU-3",
            "MLA3",
            base_price=12345.67,
            category_id="MLA-OTHER",
            currency_id="ARS",
            site_id="MLA",
            listing_type_id="gold_special",
            listing_price_fixed_fee=projection,
        ),
        "listing-type-mismatch": _order_formula_row(
            "sku-4",
            "SKU-4",
            "MLA4",
            base_price=12345.67,
            category_id="MLA-CAT",
            currency_id="ARS",
            site_id="MLA",
            listing_type_id="gold_pro",
            listing_price_fixed_fee=projection,
        ),
        "missing-currency-site-basis": _order_formula_row(
            "sku-5",
            "SKU-5",
            "MLA5",
            base_price=12345.67,
            category_id="MLA-CAT",
            listing_type_id="gold_special",
            listing_price_fixed_fee=projection,
        ),
    }
    dispatcher = _order_question_dispatcher(db)

    result = await dispatcher.execute(
        _context(
            "ZELERDATA_ORDENES",
            {"fecha_inicial": "2026-05-10", "fecha_final": "2026-05-10"},
        )
    )

    assert [row[10] for row in result.values] == ["NA", "NA", "NA", "NA", "NA"]


@pytest.mark.asyncio
async def test_order_tables_validate_fixed_fee_price_and_shipping_request_basis() -> None:
    synced_at = datetime(2026, 6, 4, tzinfo=UTC)
    projection: dict[str, Any] = {
        "source": "/sites/{site}/listing_prices",
        "fixed_fee": 1350.25,
        "currency_id": "ARS",
        "synced_at": synced_at,
        "params": {
            "site_id": "MLA",
            "category_id": "MLA-CAT",
            "price": 100,
            "currency_id": "ARS",
            "listing_type_id": "gold_special",
            "shipping_mode": "me2",
            "logistic_type": "fulfillment",
            "billable_weight": 500,
            "tags": ["mandatory_free_shipping"],
        },
    }
    matching_basis = {
        "price": 100,
        "base_price": 120,
        "category_id": "MLA-CAT",
        "currency_id": "ARS",
        "site_id": "MLA",
        "listing_type_id": "gold_special",
        "shipping_mode": "me2",
        "logistic_type": "fulfillment",
        "billable_weight": 500,
        "tags": ["mandatory_free_shipping"],
    }
    logistic_mismatch_basis = matching_basis | {
        "logistic_type": "drop_off",
        "shipping_logistic_type": "drop_off",
    }
    db = FakeDb()
    db["orders"].documents = {
        "order-1": _order_doc(
            "order-1",
            seller_id="seller-1",
            status="paid",
            date_created=datetime(2026, 5, 10, 8, 0, tzinfo=UTC),
            total_amount=39,
            items=[
                {"sku": "sku-1", "item_id": "MLA1", "qty": 1},
                {"sku": "sku-2", "item_id": "MLA2", "qty": 1},
                {"sku": "sku-3", "item_id": "MLA3", "qty": 1},
                {"sku": "sku-4", "item_id": "MLA4", "qty": 1},
                {"sku": "sku-5", "item_id": "MLA5", "qty": 1},
                {"sku": "sku-6", "item_id": "MLA6", "qty": 1},
                {"sku": "sku-7", "item_id": "MLA7", "qty": 1},
                {"sku": "sku-8", "item_id": "MLA8", "qty": 1},
                {"sku": "sku-9", "item_id": "MLA9", "qty": 1},
            ],
        )
    }
    db["sheets_item_formula_rows"].documents = {
        "valid-price-basis": _order_formula_row(
            "sku-1",
            "SKU-1",
            "MLA1",
            **matching_basis,
            listing_price_fixed_fee=projection,
        ),
        "shipping-mode-mismatch": _order_formula_row(
            "sku-2",
            "SKU-2",
            "MLA2",
            **(matching_basis | {"shipping_mode": "me1"}),
            listing_price_fixed_fee=projection,
        ),
        "logistic-type-mismatch": _order_formula_row(
            "sku-3",
            "SKU-3",
            "MLA3",
            **logistic_mismatch_basis,
            listing_price_fixed_fee=projection,
        ),
        "billable-weight-missing": _order_formula_row(
            "sku-4",
            "SKU-4",
            "MLA4",
            **{key: value for key, value in matching_basis.items() if key != "billable_weight"},
            listing_price_fixed_fee=projection,
        ),
        "tags-mismatch": _order_formula_row(
            "sku-5",
            "SKU-5",
            "MLA5",
            **(matching_basis | {"tags": ["other_tag"]}),
            listing_price_fixed_fee=projection,
        ),
        "shipping-mode-param-missing": _order_formula_row(
            "sku-6",
            "SKU-6",
            "MLA6",
            **matching_basis,
            listing_price_fixed_fee=projection
            | {
                "params": {
                    key: value
                    for key, value in projection["params"].items()
                    if key != "shipping_mode"
                }
            },
        ),
        "logistic-type-param-missing": _order_formula_row(
            "sku-7",
            "SKU-7",
            "MLA7",
            **matching_basis,
            listing_price_fixed_fee=projection
            | {
                "params": {
                    key: value
                    for key, value in projection["params"].items()
                    if key != "logistic_type"
                }
            },
        ),
        "shipping-mode-row-missing": _order_formula_row(
            "sku-8",
            "SKU-8",
            "MLA8",
            **{key: value for key, value in matching_basis.items() if key != "shipping_mode"},
            listing_price_fixed_fee=projection,
        ),
        "logistic-type-row-missing": _order_formula_row(
            "sku-9",
            "SKU-9",
            "MLA9",
            **{key: value for key, value in matching_basis.items() if key != "logistic_type"},
            listing_price_fixed_fee=projection,
        ),
    }
    dispatcher = _order_question_dispatcher(db)

    result = await dispatcher.execute(
        _context(
            "ZELERDATA_ORDENES",
            {"fecha_inicial": "2026-05-10", "fecha_final": "2026-05-10"},
        )
    )

    assert [row[10] for row in result.values] == [1350.25, *(["NA"] * 8)]


@pytest.mark.asyncio
async def test_order_tables_return_na_when_fixed_fee_optional_basis_params_are_missing() -> None:
    synced_at = datetime(2026, 6, 4, tzinfo=UTC)
    projection = {
        "source": "/sites/{site}/listing_prices",
        "fixed_fee": 1350.25,
        "currency_id": "ARS",
        "synced_at": synced_at,
        "params": {
            "site_id": "MLA",
            "category_id": "MLA-CAT",
            "price": 100,
            "currency_id": "ARS",
            "listing_type_id": "gold_special",
            "shipping_mode": "me2",
            "logistic_type": "fulfillment",
        },
    }
    matching_basis = {
        "price": 100,
        "base_price": 120,
        "category_id": "MLA-CAT",
        "currency_id": "ARS",
        "site_id": "MLA",
        "listing_type_id": "gold_special",
        "shipping_mode": "me2",
        "logistic_type": "fulfillment",
    }
    db = FakeDb()
    db["orders"].documents = {
        "order-1": _order_doc(
            "order-1",
            seller_id="seller-1",
            status="paid",
            date_created=datetime(2026, 5, 10, 8, 0, tzinfo=UTC),
            total_amount=39,
            items=[
                {"sku": "sku-1", "item_id": "MLA1", "qty": 1},
                {"sku": "sku-2", "item_id": "MLA2", "qty": 1},
                {"sku": "sku-3", "item_id": "MLA3", "qty": 1},
            ],
        )
    }
    db["sheets_item_formula_rows"].documents = {
        "billable-weight-param-missing": _order_formula_row(
            "sku-1",
            "SKU-1",
            "MLA1",
            **(matching_basis | {"billable_weight": 500}),
            listing_price_fixed_fee=projection,
        ),
        "tags-param-missing": _order_formula_row(
            "sku-2",
            "SKU-2",
            "MLA2",
            **(matching_basis | {"tags": ["mandatory_free_shipping"]}),
            listing_price_fixed_fee=projection,
        ),
        "optional-basis-absent": _order_formula_row(
            "sku-3",
            "SKU-3",
            "MLA3",
            **(matching_basis | {"tags": []}),
            listing_price_fixed_fee=projection,
        ),
    }
    dispatcher = _order_question_dispatcher(db)

    result = await dispatcher.execute(
        _context(
            "ZELERDATA_ORDENES",
            {"fecha_inicial": "2026-05-10", "fecha_final": "2026-05-10"},
        )
    )

    assert [row[10] for row in result.values] == ["NA", "NA", 1350.25]


@pytest.mark.asyncio
async def test_order_tables_return_na_for_fixed_fee_mismatch_from_backfill_row() -> None:
    synced_at = datetime(2026, 6, 4, tzinfo=UTC)
    db = FakeDb()
    db["orders"].documents = {
        "order-1": _order_doc(
            "order-1",
            seller_id="seller-1",
            status="paid",
            date_created=datetime(2026, 5, 10, 8, 0, tzinfo=UTC),
            total_amount=39,
            items=[{"sku": "sku-1", "item_id": "MLB1", "qty": 1}],
        )
    }
    row = build_formula_row_doc(
        {
            "_id": "MLB1",
            "seller_id": "seller-1",
            "title": "USD MLB listing",
            "status": "active",
            "available_quantity": 7,
            "price": 12345.67,
            "base_price": 12345.67,
            "category_id": "MLA-CAT",
            "currency_id": "USD",
            "site_id": "MLB",
            "listing_type_id": "gold_special",
            "date_created": synced_at,
            "last_updated": synced_at,
            "attributes": [{"id": "SELLER_SKU", "value_name": "sku-1"}],
            "variations": [],
            "listing_price_fixed_fee": {
                "source": "/sites/{site}/listing_prices",
                "fixed_fee": 1350.25,
                "currency_id": "ARS",
                "synced_at": synced_at,
                "params": {
                    "site_id": "MLA",
                    "category_id": "MLA-CAT",
                    "price": 12345.67,
                    "currency_id": "ARS",
                    "listing_type_id": "gold_special",
                },
            },
        },
        seller_id="seller-1",
    )
    db["sheets_item_formula_rows"].documents = {row["_id"]: row}
    dispatcher = _order_question_dispatcher(db)

    result = await dispatcher.execute(
        _context(
            "ZELERDATA_ORDENES",
            {"fecha_inicial": "2026-05-10", "fecha_final": "2026-05-10"},
        )
    )

    assert result.values[0][10] == "NA"


@pytest.mark.asyncio
async def test_find_shipment_real_shipping_costs_returns_seller_scoped_seller_costs_only() -> None:
    db = FakeDb()
    db["shipments"].documents = {
        "ship-ok": _shipment_doc(
            "ship-ok",
            seller_id="seller-1",
            real_shipping_cost={
                "source": "/shipments/{shipment_id}/costs",
                "seller_cost": "27.90",
                "receiver_cost": "11.10",
                "currency_id": "ARS",
            },
        ),
        "ship-receiver-only": _shipment_doc(
            "ship-receiver-only",
            seller_id="seller-1",
            real_shipping_cost={
                "source": "/shipments/{shipment_id}/costs",
                "receiver_cost": "99.99",
            },
        ),
        "ship-malformed": _shipment_doc(
            "ship-malformed",
            seller_id="seller-1",
            real_shipping_cost={"seller_cost": {"raw": "unsafe"}},
        ),
        "ship-other-seller": _shipment_doc(
            "ship-other-seller",
            seller_id="seller-2",
            real_shipping_cost={
                "source": "/shipments/{shipment_id}/costs",
                "seller_cost": "888",
            },
        ),
    }
    repository = FormulaReadModelRepository(db=db)

    result = await repository.find_shipment_real_shipping_costs(
        seller_id="seller-1",
        shipment_ids=["ship-ok", "ship-ok", "ship-receiver-only", "ship-malformed", "missing"],
    )

    assert result == {"ship-ok": Decimal("27.90")}
    assert db["shipments"].last_find_filter == {
        "seller_id": "seller-1",
        "_id": {"$in": ["ship-ok", "ship-receiver-only", "ship-malformed", "missing"]},
    }


@pytest.mark.asyncio
async def test_ordenes_renders_seller_paid_real_shipping_cost_from_shipment_projection() -> None:
    db = FakeDb()
    db["orders"].documents = {
        "order-1": _order_doc(
            "order-1",
            seller_id="seller-1",
            status="paid",
            date_created=datetime(2026, 5, 10, 8, 0, tzinfo=UTC),
            total_amount=39,
            shipment_id="ship-1",
            items=[{"sku": "sku-1", "item_id": "MLA1", "title": "Shipped item", "qty": 1}],
        )
    }
    db["shipments"].documents = {
        "ship-1": _shipment_doc(
            "ship-1",
            seller_id="seller-1",
            real_shipping_cost={
                "source": "/shipments/{shipment_id}/costs",
                "seller_cost": "27.90",
                "receiver_cost": "11.10",
                "currency_id": "ARS",
            },
        )
    }
    dispatcher = _order_question_dispatcher(db)

    result = await dispatcher.execute(
        _context(
            "ZELERDATA_ORDENES",
            {"fecha_inicial": "2026-05-10", "fecha_final": "2026-05-10"},
        )
    )

    assert result.values[0][11] == 27.9
    assert db["shipments"].last_find_filter == {
        "seller_id": "seller-1",
        "_id": {"$in": ["ship-1"]},
    }


@pytest.mark.asyncio
async def test_ordenes_fails_closed_without_seller_cost_and_ignores_estimates() -> None:
    db = FakeDb()
    db["orders"].documents = {
        "receiver-only": _order_doc(
            "receiver-only",
            seller_id="seller-1",
            status="paid",
            date_created=datetime(2026, 5, 10, 8, 0, tzinfo=UTC),
            total_amount=39,
            shipment_id="ship-receiver-only",
            items=[{"sku": "sku-1", "item_id": "MLA1", "title": "Receiver-only", "qty": 1}],
        ),
        "no-shipment": _order_doc(
            "no-shipment",
            seller_id="seller-1",
            status="paid",
            date_created=datetime(2026, 5, 10, 9, 0, tzinfo=UTC),
            total_amount=40,
            items=[{"sku": "sku-2", "item_id": "MLA2", "title": "No shipment", "qty": 1}],
        ),
    }
    db["shipments"].documents = {
        "ship-receiver-only": _shipment_doc(
            "ship-receiver-only",
            seller_id="seller-1",
            real_shipping_cost={
                "source": "/shipments/{shipment_id}/costs",
                "receiver_cost": "99.99",
            },
        )
    }
    db["sheets_item_formula_rows"].documents = {
        "seller-1:SKU-1:MLA1": _item_formula_row("seller-1", "SKU-1", "MLA1", stock=1)
        | {"current": {"seller_shipping_cost": "88.88"}}
    }
    dispatcher = _order_question_dispatcher(db)

    result = await dispatcher.execute(
        _context(
            "ZELERDATA_ORDENES",
            {"fecha_inicial": "2026-05-10", "fecha_final": "2026-05-10"},
        )
    )

    assert [row[11] for row in result.values] == ["NA", "NA"]


@pytest.mark.asyncio
async def test_ordenes_por_sku_repeats_full_real_shipping_cost_for_each_sku_row() -> None:
    db = FakeDb()
    db["orders"].documents = {
        "order-1": _order_doc(
            "order-1",
            seller_id="seller-1",
            status="paid",
            date_created=datetime(2026, 5, 10, 8, 0, tzinfo=UTC),
            total_amount=80,
            shipment_id="ship-1",
            items=[
                {"sku": "sku-1", "item_id": "MLA1", "title": "First SKU", "qty": 1},
                {"sku": "sku-2", "item_id": "MLA2", "title": "Second SKU", "qty": 1},
            ],
        )
    }
    db["shipments"].documents = {
        "ship-1": _shipment_doc(
            "ship-1",
            seller_id="seller-1",
            real_shipping_cost={
                "source": "/shipments/{shipment_id}/costs",
                "seller_cost": "45.20",
            },
        )
    }
    dispatcher = _order_question_dispatcher(db)

    result = await dispatcher.execute(
        _context(
            "ZELERDATA_ORDENESPORSKU",
            {
                "skus": [["sku-1"], ["sku-2"]],
                "fecha_inicial": "2026-05-10",
                "fecha_final": "2026-05-10",
            },
        )
    )

    assert [row[11] for row in result.values] == [45.2, 45.2]


@pytest.mark.asyncio
async def test_ordenes_por_sku_buyer_id_filter_includes_buyer_columns() -> None:
    db = FakeDb()
    db["orders"].documents = {
        "matching-buyer": _order_doc(
            "matching-buyer",
            seller_id="seller-1",
            status="paid",
            buyer_id="buyer-2",
            date_created=datetime(2026, 5, 10, 9, 0, tzinfo=UTC),
            total_amount=40,
            items=[{"sku": "sku-1", "item_id": "MLA1", "title": "Included", "quantity": 1}],
        ),
        "other-buyer": _order_doc(
            "other-buyer",
            seller_id="seller-1",
            status="paid",
            buyer_id="buyer-1",
            date_created=datetime(2026, 5, 10, 10, 0, tzinfo=UTC),
            total_amount=50,
            items=[{"sku": "sku-1", "item_id": "MLA1", "title": "Excluded", "quantity": 1}],
        ),
    }
    dispatcher = _order_question_dispatcher(db)

    result = await dispatcher.execute(
        _context(
            "ZELERDATA_ORDENESPORSKU",
            {
                "skus": "sku-1",
                "fecha_inicial": "2026-05-10",
                "fecha_final": "2026-05-10",
                "estado": "paid",
                "compradores": "buyer-2",
                "encabezados": "si",
            },
        )
    )

    assert result.values == _formula_table_contract([
        ORDER_LINE_LEGACY_HEADERS + BUYER_ADDRESS_LEGACY_HEADERS,
        [
            "2026-05-10T09:00:00+00:00",
            "matching-buyer",
            "Included",
            "SKU-1",
            "MLA1",
            1,
            "",
            "",
            "",
            "",
            "",
            "",
            "paid",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
        ],
    ])
    assert result.meta == {
        "orders_count": 1,
        "status_filter": "paid",
        "buyer_filter_count": 1,
        "sku_filter_count": 1,
        "columns": "legacy_order_lines_with_buyers",
    }


@pytest.mark.asyncio
async def test_unidades_vendidas_ignores_unresolved_sku_order_lines() -> None:
    db = FakeDb()
    db["orders"].documents = {
        "unresolved-sku": _order_doc(
            "unresolved-sku",
            seller_id="seller-1",
            status="paid",
            buyer_id="buyer-1",
            date_created=datetime(2026, 5, 10, 8, 30, tzinfo=UTC),
            total_amount="59.97",
            items=[
                {
                    "item_id": "MLA-UNRESOLVED",
                    "title": "Unresolved SKU item",
                    "quantity": 3,
                    "unit_price": "19.99",
                }
            ],
        )
    }
    dispatcher = _order_question_dispatcher(db)

    result = await dispatcher.execute(
        _context(
            "ZELERDATA_UNIDADESVENDIDAS",
            {
                "skus": [["sku-1"]],
                "id_publicaciones": [["MLA-UNRESOLVED"]],
                "fecha_inicial": "2026-05-10",
                "fecha_final": "2026-05-10",
            },
        )
    )

    assert result.values == [[0]]
    assert result.meta == {"partial_misses": 1, "orders_count": 1}


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
            "ZELERDATA_UNIDADESVENDIDAS",
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
            "ZELERDATA_UNIDADESVENDIDAS",
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
            "ZELERDATA_UNIDADESVENDIDAS",
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
        }
    ]


def test_order_sku_resolver_does_not_guess_missing_variation_from_other_variation_row() -> None:
    resolver = _OrderSkuResolver(
        [_sku_index_doc("seller-1", "SKU-RED", "MLA1", variation_id="101")]
    )

    resolution = resolver.resolve({"item_id": "MLA1", "variation_id": "102"})

    assert resolution.sku == ""
    assert resolution.enriched is False


@pytest.mark.asyncio
async def test_unidades_vendidas_variation_order_uses_unique_item_level_fallback() -> None:
    db = FakeDb()
    db["sheets_item_sku_index"].documents = {
        "seller-1:SKU-BASE:MLA1:item": _sku_index_doc("seller-1", "SKU-BASE", "MLA1"),
    }
    db["orders"].documents = {
        "order-1": _order_doc(
            "order-1",
            seller_id="seller-1",
            status="paid",
            date_created=datetime(2026, 5, 10, 12, 0, tzinfo=UTC),
            total_amount=120,
            items=[{"item_id": "MLA1", "variation_id": "102", "qty": 4, "unit_price": "10.00"}],
        )
    }
    dispatcher = _order_question_dispatcher(db)

    result = await dispatcher.execute(
        _context(
            "ZELERDATA_UNIDADESVENDIDAS",
            {
                "skus": [["sku-base"]],
                "id_publicaciones": ["MLA1"],
                "fecha_inicial": "2026-05-10",
                "fecha_final": "2026-05-10",
            },
        )
    )

    assert result.values == [[4]]
    assert result.meta == {"partial_misses": 0, "orders_count": 1, "sku_enriched_items": 1}
    assert db["sheets_item_sku_index"].find_filters == [
        {
            "seller_id": "seller-1",
            "item_id": {"$in": ["MLA1"]},
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
            "ZELERDATA_UNIDADESVENDIDAS",
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
            "ZELERDATA_VENTAPORDIAS",
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
    db["sheets_item_formula_rows"].documents = {
        "seller-1:SKU-1:MLA1": _item_formula_row(
            "seller-1", "SKU-1", "MLA1", stock=8, title="First top title"
        ),
        "seller-1:SKU-2:MLA2": _item_formula_row(
            "seller-1", "SKU-2", "MLA2", stock=5, title="Second top title"
        ),
        "seller-1:SKU-3:MLA3": _item_formula_row(
            "seller-1", "SKU-3", "MLA3", stock=0, title="Third top title"
        ),
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
            "ZELERDATA_TOPVENTASUNIDADES",
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
            "ZELERDATA_TOPVENTASDINERO",
            {
                "fecha_inicial": "2026-05-10",
                "fecha_final": "2026-05-11",
                "cantidad_top": 2,
                "encabezados": "si",
            },
        )
    )

    assert unidades.values == [
        ["ID Publicación", "SKU", "Título", "Unidades Vendidas"],
        ["MLA3", "SKU-3", "Third top title", 9],
        ["MLA2", "SKU-2", "Second top title", 5],
    ]
    assert unidades.meta == {
        "orders_count": 2,
        "rows_count": 2,
        "columns": "top_sales_units_mvp",
        "sku_enriched_items": 4,
    }
    assert dinero.values == [
        ["ID Publicación", "SKU", "Título", "Unidades Vendidas", "Cantidad De Dinero"],
        ["MLA1", "SKU-1", "First top title", 3, 40],
        ["MLA2", "SKU-2", "Second top title", 5, 15],
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
            "ZELERDATA_VENTASYSTOCK",
            {
                "skus": [["sku-1"], ["sku-2"]],
                "id_publicaciones": ["MLA1", "MLA2"],
                "encabezados": "si",
            },
        )
    )

    assert result.values == [
        [
            "Unidades Vendidas (7 días)",
            "Unidades Vendidas (15 días)",
            "Unidades Vendidas (30 días)",
            "Stock actual",
        ],
        [1, 3, 7, 8],
        [0, 0, 0, 0],
    ]
    assert result.meta == {
        "partial_misses": 0,
        "orders_count": 3,
        "columns": "legacy_sales_and_stock",
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
            "ZELERDATA_DIASDESDEULTIMAVENTA",
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
            "seller-1",
            "SKU-2",
            "MLA2",
            stock=0,
            title="Old sale",
            inventory_id="INV-2",
            status="paused",
        ),
        "seller-1:SKU-3:MLA3": _item_formula_row(
            "seller-1",
            "SKU-3",
            "MLA3",
            stock=5,
            title="Never sold",
            inventory_id="INV-3",
            status="active",
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
        _context("ZELERDATA_PRODUCTOSINVENTA", {"rango_dias": 7, "encabezados": "si"})
    )

    assert result.values == _formula_table_contract([
        PRODUCTOS_SIN_VENTA_LEGACY_HEADERS,
        ["Old sale", "INV-2", "MLA2", "SKU-2", 0, "", "paused", ""],
        ["Never sold", "INV-3", "MLA3", "SKU-3", 5, "", "active", ""],
    ])
    assert result.meta == {
        "rows_count": 2,
        "orders_count": 1,
        "rango_dias": 7,
        "columns": "legacy_products_without_sales",
        "sku_enriched_items": 1,
    }
    assert len(db["orders"].find_filters) == 1
    assert db["orders"].last_find_filter is not None
    assert db["orders"].last_find_filter["$or"][0] == {
        "date_created": {
            "$gte": datetime(2026, 5, 8, 0, 0, tzinfo=UTC),
            "$lte": datetime(2026, 5, 14, 23, 59, 59, 999999, tzinfo=UTC),
        }
    }


@pytest.mark.asyncio
async def test_preguntas_blocks_productive_output_until_questions_read_model_is_fresh() -> None:
    db = FakeDb()
    db["questions"].documents = {
        "q-stale": _question_doc(
            "q-stale",
            seller_id="seller-1",
            status="ANSWERED",
            date_created="2026-05-10T17:45:00Z",
            answer={"text": "Yes", "date_created": "2026-05-10T18:00:00Z"},
        )
    }
    dispatcher = _order_question_dispatcher(db)

    with pytest.raises(FormulaDataUnavailableError, match="Questions read model"):
        await dispatcher.execute(
            _context(
                "ZELERDATA_PREGUNTAS",
                {
                    "fecha_inicial": "2026-05-10",
                    "fecha_final": "2026-05-10",
                    "horario_inicial": "00:00",
                    "horario_final": "23:59",
                },
            )
        )


@pytest.mark.asyncio
async def test_preguntas_kpi_blocks_stale_questions_freshness_marker() -> None:
    db = FakeDb()
    _mark_questions_fresh(
        db,
        fresh_until=datetime(2026, 5, 10, 23, 59, 59, 999999, tzinfo=UTC),
    )
    db["questions"].documents = {
        "q1": _question_doc(
            "q1",
            seller_id="seller-1",
            status="ANSWERED",
            date_created=datetime(2026, 5, 11, 11, 0, tzinfo=UTC),
            answer={"date_created": datetime(2026, 5, 11, 13, 0, tzinfo=UTC)},
        )
    }
    dispatcher = _order_question_dispatcher(db)

    with pytest.raises(FormulaDataUnavailableError, match="Questions read model"):
        await dispatcher.execute(
            _context(
                "ZELERDATA_PREGUNTASKPI",
                {"fecha_inicio": "2026-05-10", "fecha_final": "2026-05-11"},
            )
        )


@pytest.mark.asyncio
async def test_preguntas_blocks_event_fresh_marker_without_historical_reconciliation() -> None:
    db = FakeDb()
    _mark_questions_fresh(
        db,
        fresh_until=datetime(2026, 5, 10, 23, 59, 59, 999999, tzinfo=UTC),
    )
    db["questions"].documents = {
        "q1": _question_doc(
            "q1",
            seller_id="seller-1",
            status="ANSWERED",
            date_created=datetime(2026, 5, 10, 11, 0, tzinfo=UTC),
            answer={"text": "Yes", "date_created": datetime(2026, 5, 10, 11, 5, tzinfo=UTC)},
        )
    }
    dispatcher = _order_question_dispatcher(db)

    with pytest.raises(FormulaDataUnavailableError, match="Questions read model"):
        await dispatcher.execute(
            _context(
                "ZELERDATA_PREGUNTAS",
                {"fecha_inicial": "2026-05-10", "fecha_final": "2026-05-10"},
            )
        )


@pytest.mark.asyncio
async def test_preguntas_kpi_blocks_event_fresh_marker_without_historical_reconciliation() -> None:
    db = FakeDb()
    _mark_questions_fresh(
        db,
        fresh_until=datetime(2026, 5, 10, 23, 59, 59, 999999, tzinfo=UTC),
    )
    db["questions"].documents = {
        "q1": _question_doc(
            "q1",
            seller_id="seller-1",
            status="ANSWERED",
            date_created=datetime(2026, 5, 10, 11, 0, tzinfo=UTC),
            answer={"date_created": datetime(2026, 5, 10, 11, 5, tzinfo=UTC)},
        )
    }
    dispatcher = _order_question_dispatcher(db)

    with pytest.raises(FormulaDataUnavailableError, match="Questions read model"):
        await dispatcher.execute(
            _context(
                "ZELERDATA_PREGUNTASKPI",
                {"fecha_inicio": "2026-05-10", "fecha_final": "2026-05-10"},
            )
        )


@pytest.mark.asyncio
async def test_preguntas_returns_question_table_with_date_and_hour_filters() -> None:
    db = FakeDb()
    _mark_questions_fresh(
        db,
        fresh_until=datetime(2026, 5, 10, 23, 59, 59, 999999, tzinfo=UTC),
        last_event_synced_at=datetime(2026, 5, 10, tzinfo=UTC),
        state="reconciled",
    )
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
            "ZELERDATA_PREGUNTAS",
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
    _mark_questions_fresh(
        db,
        fresh_until=datetime(2026, 5, 11, 23, 59, 59, 999999, tzinfo=UTC),
        last_event_synced_at=datetime(2026, 5, 10, tzinfo=UTC),
        state="reconciled",
    )
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
            "ZELERDATA_PREGUNTASKPI",
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
    _mark_questions_fresh(
        db,
        fresh_until=datetime(2025, 10, 27, 23, 59, 59, 999999, tzinfo=UTC),
        last_event_synced_at=datetime(2025, 9, 26, tzinfo=UTC),
        state="reconciled",
    )
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
            "ZELERDATA_PREGUNTASKPI",
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
            items=[
                {
                    "sku": "sku-1",
                    "item_id": "MLA1",
                    "title": "API item",
                    "quantity": 2,
                    "unit_price": 50,
                }
            ],
        ),
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        ventas = await client.post(
            "/sheets/formulas:execute",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "formula": "ZELERDATA_VENTASTOTALES",
                "cuenta": "HOPEMOB",
                "args": {"fecha_inicial": "2026-05-10", "fecha_final": "2026-05-10"},
            },
        )
        orders_table = await client.post(
            "/sheets/formulas:execute",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "formula": "ZELERDATA_ORDENES",
                "cuenta": "HOPEMOB",
                "args": {
                    "fecha_inicial": "2026-05-10",
                    "fecha_final": "2026-05-10",
                    "encabezados": "si",
                },
            },
        )
        compradores = await client.post(
            "/sheets/formulas:execute",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "formula": "ZELERDATA_COMPRADORES",
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
    assert orders_table.json()["values"] == _formula_table_contract([
        ORDER_LINE_LEGACY_HEADERS,
        [
            "2026-05-10T10:30:00+00:00",
            "order-1",
            "API item",
            "SKU-1",
            "MLA1",
            2,
            50,
            "",
            "",
            "",
            "",
            "",
            "paid",
        ],
    ])
    assert compradores.status_code == 200
    assert compradores.json() == {
        "ok": True,
        "values": [["NA", "NA", "NA", "NA", "NA", "NA", "NA", "NA"]],
        "meta": {
            "orders_count": 1,
            "address_available": 0,
            "address_missing": 1,
            "columns": "buyer_address_snapshot",
        },
    }


def _order_question_dispatcher(db: FakeDb, *, now_fn: Any | None = None) -> FormulaDispatcher:
    return FormulaDispatcher(
        build_order_question_formula_handlers(FormulaReadModelRepository(db=db), now_fn=now_fn)
    )


def _context(
    formula: str, args: dict[str, Any], *, seller_timezone: str = "UTC"
) -> FormulaExecutionContext:
    return FormulaExecutionContext(
        contract=FormulaRegistry.default().find_required(formula),
        cuenta="HOPEMOB",
        seller_id="seller-1",
        seller_nickname="HOPEMOB",
        token_id="token-1",
        args=args,
        request_id="req-1",
        seller_timezone=seller_timezone,
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


def _mark_questions_fresh(
    db: FakeDb,
    *,
    seller_id: str = "seller-1",
    fresh_until: datetime,
    last_event_synced_at: datetime | None = None,
    state: str = "fresh",
) -> None:
    db["sheets_read_model_freshness"].documents[f"{seller_id}:questions"] = {
        "_id": f"{seller_id}:questions",
        "seller_id": seller_id,
        "read_model": "questions",
        "state": state,
        "fresh_until": fresh_until,
        "last_event_synced_at": last_event_synced_at,
        "reconciled_until": fresh_until if state == "reconciled" else None,
        "updated_at": datetime(2026, 5, 30, 12, 0, tzinfo=UTC),
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


def _unit_cost_doc(
    doc_id: str,
    *,
    normalized_sku: str | None = None,
    item_id: str | None = None,
    variation_id: str | None = None,
    unit_cost: str,
    effective_to: datetime | None = None,
) -> dict[str, Any]:
    return {
        "_id": doc_id,
        "seller_id": "seller-1",
        "normalized_sku": normalized_sku,
        "item_id": item_id,
        "variation_id": variation_id,
        "unit_cost": unit_cost,
        "currency": "ARS",
        "source": "manual",
        "status": "active",
        "effective_from": datetime(2026, 1, 1, tzinfo=UTC),
        "effective_to": effective_to,
        "schema_version": 1,
    }


def _item_formula_row(
    seller_id: str,
    sku: str,
    item_id: str,
    *,
    stock: int,
    title: str = "",
    inventory_id: str = "",
    status: str = "",
) -> dict[str, Any]:
    return {
        "_id": f"{seller_id}:{sku}:{item_id}",
        "seller_id": seller_id,
        "sku": sku,
        "normalized_sku": sku.upper(),
        "item_id": item_id,
        "inventory_id": inventory_id,
        "current": {
            "available_quantity": stock,
            "title": title,
            "status": status,
            "inventory_id": inventory_id,
        },
        "schema_version": 1,
    }


def _order_formula_row(
    sku: str, normalized_sku: str, item_id: str, **current: Any
) -> dict[str, Any]:
    return {
        "_id": item_id,
        "seller_id": "seller-1",
        "sku": sku,
        "normalized_sku": normalized_sku,
        "item_id": item_id,
        "current": {"title": item_id} | current,
        "schema_version": 1,
    }


def _shipment_doc(
    shipment_id: str,
    *,
    seller_id: str,
    real_shipping_cost: dict[str, Any] | None = None,
) -> dict[str, Any]:
    shipment: dict[str, Any] = {
        "_id": shipment_id,
        "seller_id": seller_id,
        "status": "delivered",
        "schema_version": 1,
    }
    if real_shipping_cost is not None:
        shipment["real_shipping_cost"] = real_shipping_cost
    return shipment


def _sort_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return value
