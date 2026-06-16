# ruff: noqa: S105,S106

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from zeler_sheets.formulas.dispatcher import (
    FormulaDataUnavailableError,
    FormulaDispatcher,
    FormulaExecutionContext,
)
from zeler_sheets.formulas.handlers_remaining_phase4 import (
    build_remaining_phase4_formula_handlers,
)
from zeler_sheets.formulas.read_models import (
    CATALOG_BUYBOX_SNAPSHOTS_READ_MODEL,
    CATALOG_TIME_METRICS_READ_MODEL,
    FULL_WITHDRAWALS_READ_MODEL,
    ITEM_FORMULA_ROWS_READ_MODEL,
    ORDERS_READ_MODEL,
    PRICE_HISTORY_SNAPSHOTS_READ_MODEL,
    STOCK_TIME_METRICS_READ_MODEL,
    STOCKOUT_SNAPSHOTS_READ_MODEL,
    FormulaReadModelRepository,
)
from zeler_sheets.formulas.registry import FormulaRegistry


class FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs

    def sort(self, sort_spec: list[tuple[str, int]]) -> FakeCursor:
        sorted_docs = list(self._docs)
        for key, direction in reversed(sort_spec):
            sorted_docs.sort(
                key=lambda doc: str(_dotted_value(doc, key) or ""), reverse=direction < 0
            )
        return FakeCursor(sorted_docs)

    async def to_list(self, length: int | None = None) -> list[dict[str, Any]]:
        if length is None:
            return [dict(doc) for doc in self._docs]
        return [dict(doc) for doc in self._docs[:length]]


class FakeCollection:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}
        self.last_find_filter: dict[str, Any] | None = None

    def find(
        self, filter_spec: dict[str, Any], projection: dict[str, int] | None = None
    ) -> FakeCursor:
        del projection
        self.last_find_filter = dict(filter_spec)
        return FakeCursor(
            [dict(doc) for doc in self.documents.values() if _matches(doc, filter_spec)]
        )

    async def find_one(self, filter_spec: dict[str, Any]) -> dict[str, Any] | None:
        self.last_find_filter = dict(filter_spec)
        for doc in self.documents.values():
            if _matches(doc, filter_spec):
                return dict(doc)
        return None


class FakeDb:
    def __init__(self) -> None:
        self.collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        return self.collections.setdefault(name, FakeCollection())


NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_catalogo_uses_local_item_catalog_buybox_and_sales_snapshots() -> None:
    db = FakeDb()
    _mark_read_model_fresh(db, CATALOG_BUYBOX_SNAPSHOTS_READ_MODEL)
    _mark_read_model_fresh(db, ITEM_FORMULA_ROWS_READ_MODEL)
    _mark_read_model_fresh(db, ORDERS_READ_MODEL)
    db["sheets_item_formula_rows"].documents = {
        "seller-1:SKU-1:MLA1": _item_row(
            item_id="MLA1",
            sku="sku-1",
            title="Catalog item",
            catalog_product_id="CAT-1",
            price=Decimal("100"),
        ),
    }
    db["sheets_catalog_buybox_snapshots"].documents = {
        "seller-1:MLA1": {
            "_id": "seller-1:MLA1",
            "seller_id": "seller-1",
            "item_id": "MLA1",
            "catalog_product_id": "CAT-1",
            "catalog_url": "https://catalog.example/CAT-1",
            "buybox_status": "winning",
            "winning_time_percent": Decimal("75.5"),
            "winning_price": Decimal("95"),
            "winning_user_id": "seller-competitor",
            "competitor_count": 3,
            "price_to_win": Decimal("94"),
            "only_competitor": "No",
        }
    }
    db["orders"].documents = {
        "ORDER-7": _order_doc("ORDER-7", days_ago=2, quantity=1),
        "ORDER-15": _order_doc("ORDER-15", days_ago=10, quantity=2),
        "ORDER-30": _order_doc("ORDER-30", days_ago=20, quantity=3),
        "ORDER-60": _order_doc("ORDER-60", days_ago=50, quantity=4),
        "ORDER-90": _order_doc("ORDER-90", days_ago=80, quantity=5),
        "ORDER-365": _order_doc("ORDER-365", days_ago=200, quantity=6),
        "ORDER-OLD": _order_doc("ORDER-OLD", days_ago=370, quantity=7),
        "ORDER-CANCELLED": _order_doc(
            "ORDER-CANCELLED", days_ago=1, quantity=9, status="cancelled"
        ),
    }
    dispatcher = _dispatcher(db)

    result = await dispatcher.execute(
        _context("ZELERDATA_CATALOGO", {"tipo_precio": "base", "encabezados": "si"})
    )

    assert result.values == [
        [
            "ID CATALOGO",
            "URL CATALOGO",
            "ID PUBLICACION",
            "URL",
            "TITULO",
            "SKU",
            "CODIGO ML",
            "ENVIO A CARGO DE",
            "STOCK ACTUAL",
            "VENTAS 7 DIAS",
            "VENTAS 15 DIAS",
            "VENTAS 30 DIAS",
            "VENTAS 60 DIAS",
            "VENTAS 90 DIAS",
            "VENTAS 365 DIAS",
            "STATUS PUBLICACION CATALOGO",
            "STATUS WINNER CATALOGO",
            "% TIEMPO GANANDO CATALOGO SOBRE EL COMPETIDO",
            "PRECIO GANADOR CATALOGO",
            "MI PRECIO ACTUAL CATALOGO",
            "USUARIO GANADOR CATALOGO",
            "COMPARTIENDO CATALOGO CON USUARIOS",
            "PRICE TO WIN",
            "UNICO COMPETIDOR",
        ],
        [
            "CAT-1",
            "https://catalog.example/CAT-1",
            "MLA1",
            "https://meli.example/MLA1",
            "Catalog item",
            "sku-1",
            "INV-MLA1",
            "buyer",
            5,
            1,
            3,
            6,
            10,
            15,
            21,
            "active",
            "winning",
            75.5,
            95,
            100,
            "seller-competitor",
            3,
            94,
            "No",
        ],
    ]
    assert result.meta == {"rows_count": 1, "columns": "legacy_catalog_matrix"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fresh_read_models", "stale_read_model", "expected_read_model"),
    [
        ([CATALOG_BUYBOX_SNAPSHOTS_READ_MODEL], None, ITEM_FORMULA_ROWS_READ_MODEL),
        (
            [CATALOG_BUYBOX_SNAPSHOTS_READ_MODEL],
            ITEM_FORMULA_ROWS_READ_MODEL,
            ITEM_FORMULA_ROWS_READ_MODEL,
        ),
        (
            [CATALOG_BUYBOX_SNAPSHOTS_READ_MODEL, ITEM_FORMULA_ROWS_READ_MODEL],
            None,
            ORDERS_READ_MODEL,
        ),
        (
            [CATALOG_BUYBOX_SNAPSHOTS_READ_MODEL, ITEM_FORMULA_ROWS_READ_MODEL],
            ORDERS_READ_MODEL,
            ORDERS_READ_MODEL,
        ),
    ],
)
async def test_catalogo_requires_fresh_item_rows_and_orders_markers(
    fresh_read_models: list[str],
    stale_read_model: str | None,
    expected_read_model: str,
) -> None:
    db = FakeDb()
    for read_model in fresh_read_models:
        _mark_read_model_fresh(db, read_model)
    if stale_read_model is not None:
        _mark_read_model_fresh(db, stale_read_model, fresh_until=NOW - timedelta(days=1))
    dispatcher = _dispatcher(db)

    with pytest.raises(FormulaDataUnavailableError, match="ZELERDATA_CATALOGO") as error:
        await dispatcher.execute(_context("ZELERDATA_CATALOGO", {"tipo_precio": "base"}))

    assert expected_read_model in str(error.value)
    assert "freshness/reconciliation" in str(error.value)


@pytest.mark.asyncio
async def test_stock_history_formulas_use_local_stock_read_models() -> None:
    db = FakeDb()
    _mark_read_model_fresh(db, STOCKOUT_SNAPSHOTS_READ_MODEL)
    _mark_read_model_fresh(db, STOCK_TIME_METRICS_READ_MODEL)
    db["sheets_stockout_snapshots"].documents = {
        "seller-1:MLA1": {
            "_id": "seller-1:MLA1",
            "seller_id": "seller-1",
            "item_id": "MLA1",
            "sku": "sku-1",
            "title": "No stock item",
            "price": Decimal("88"),
            "logistic_type": "fulfillment",
            "url": "https://meli.example/MLA1",
            "status": "paused",
            "current_stock": 0,
            "out_of_stock_since": NOW - timedelta(days=4),
        },
        "seller-1:MLA2": {
            "_id": "seller-1:MLA2",
            "seller_id": "seller-1",
            "item_id": "MLA2",
            "sku": "sku-2",
            "title": "Has stock item",
            "price": Decimal("50"),
            "current_stock": 3,
            "out_of_stock_since": NOW - timedelta(days=1),
        },
    }
    db["sheets_stock_time_metrics"].documents = {
        "seller-1:MLA1": {
            "_id": "seller-1:MLA1",
            "seller_id": "seller-1",
            "item_id": "MLA1",
            "sku": "sku-1",
            "title": "Stock item",
            "url": "https://meli.example/MLA1",
            "date_from": datetime(2026, 6, 1, tzinfo=UTC),
            "date_to": datetime(2026, 6, 14, 23, 59, tzinfo=UTC),
            "active_stock_hours": Decimal("36"),
            "total_hours": Decimal("72"),
            "active_stock_percent": Decimal("50"),
            "weeks": [
                {"start_day": 1, "end_day": 7, "has_stock": True},
                {"start_day": 8, "end_day": 14, "has_stock": False},
            ],
        }
    }
    dispatcher = _dispatcher(db)

    sin_stock = await dispatcher.execute(
        _context("ZELERDATA_TIEMPOSINSTOCK", {"tipo_precio": "base", "encabezados": "si"})
    )
    stock_activo = await dispatcher.execute(
        _context(
            "ZELERDATA_TIEMPOSTOCKACTIVO",
            {
                "fecha_inicial": "2026-06-01",
                "fecha_final": "2026-06-14",
                "id_publicaciones": "todos",
                "encabezados": "si",
            },
        )
    )
    semanas = await dispatcher.execute(
        _context(
            "ZELERDATA_SEMANASCONSTOCK",
            {
                "fecha_inicial": "2026-06-01",
                "fecha_final": "2026-06-14",
                "id_publicaciones": "todos",
                "skus": "todos",
                "encabezados": "si",
            },
        )
    )

    assert sin_stock.values == [
        [
            "ID PUBLICACION",
            "TITULO",
            "SKU",
            "PRECIO",
            "LOGISTICA",
            "URL",
            "STATUS",
            "TIEMPO SIN STOCK",
        ],
        [
            "MLA1",
            "No stock item",
            "sku-1",
            88,
            "fulfillment",
            "https://meli.example/MLA1",
            "paused",
            4,
        ],
    ]
    assert stock_activo.values == [
        [
            "ID PUBLICACION",
            "SKU",
            "TITULO",
            "URL",
            "TIEMPO ACTIVA",
            "TIEMPO TOTAL",
            "% TIEMPO ACTIVA",
        ],
        ["MLA1", "sku-1", "Stock item", "https://meli.example/MLA1", 36, 72, 50],
    ]
    assert semanas.values == [
        ["ID PUBLICACION", "SKU", "TITULO", "1 - 7", "8 - 14"],
        ["MLA1", "sku-1", "Stock item", "Con stock", "Sin stock"],
    ]


@pytest.mark.asyncio
async def test_price_and_catalog_time_formulas_use_local_history_read_models() -> None:
    db = FakeDb()
    _mark_read_model_fresh(db, PRICE_HISTORY_SNAPSHOTS_READ_MODEL)
    _mark_read_model_fresh(db, CATALOG_TIME_METRICS_READ_MODEL)
    db["sheets_price_history_snapshots"].documents = {
        "seller-1:MLA1": {
            "_id": "seller-1:MLA1",
            "seller_id": "seller-1",
            "item_id": "MLA1",
            "title": "Price item",
            "prices": [
                {"price": Decimal("120"), "status": "active"},
                {"price": Decimal("115"), "status": "promotion"},
                {"price": Decimal("130"), "status": "paused"},
            ],
        }
    }
    db["sheets_catalog_time_metrics"].documents = {
        "seller-1:MLA1": {
            "_id": "seller-1:MLA1",
            "seller_id": "seller-1",
            "item_id": "MLA1",
            "title": "Catalog winner",
            "url": "https://meli.example/MLA1",
            "date_from": datetime(2026, 6, 1, tzinfo=UTC),
            "date_to": datetime(2026, 6, 14, 23, 59, tzinfo=UTC),
            "winning_hours": Decimal("12"),
            "available_hours": Decimal("24"),
            "winning_percent": Decimal("50"),
        }
    }
    dispatcher = _dispatcher(db)

    price_history = await dispatcher.execute(
        _context(
            "ZELERDATA_PRECIOHISTORICO",
            {"id_publicaciones": "todos", "tipo_precio": "base", "encabezados": "si"},
        )
    )
    catalog_time = await dispatcher.execute(
        _context(
            "ZELERDATA_CATALOGOTIEMPO",
            {
                "fecha_inicial": "2026-06-01",
                "fecha_final": "2026-06-14",
                "id_publicaciones": "todos",
                "encabezados": "si",
            },
        )
    )

    assert price_history.values == [
        [
            "ID PUBLICACION",
            "TITULO",
            "PRECIO 1",
            "STATUS 1",
            "PRECIO 2",
            "STATUS 2",
            "PRECIO 3",
            "STATUS 3",
        ],
        ["MLA1", "Price item", 120, "active", 115, "promotion", 130, "paused"],
    ]
    assert catalog_time.values == [
        [
            "ID PUBLICACION",
            "TITULO",
            "URL",
            "TIEMPO GANANDO CATALOGO EN HORAS",
            "TOTAL DE HORAS DISPONIBLE EN CATALOGO",
            "% DE TIEMPO GANANDO CATALOGO",
        ],
        ["MLA1", "Catalog winner", "https://meli.example/MLA1", 12, 24, 50],
    ]


@pytest.mark.asyncio
async def test_retiros_uses_local_full_withdrawal_read_model() -> None:
    db = FakeDb()
    _mark_read_model_fresh(db, FULL_WITHDRAWALS_READ_MODEL, fresh_until=NOW + timedelta(days=30))
    db["sheets_full_withdrawals"].documents = {
        "withdrawal-1": {
            "_id": "withdrawal-1",
            "seller_id": "seller-1",
            "withdrawal_id": "RET-1",
            "withdrawal_detail_id": "RET-1-ITEM-1",
            "inventory_id": "INV-MLA1",
            "item_id": "MLA1",
            "sku": "sku-1",
            "title": "Withdrawal item",
            "requested_quantity": 4,
            "created_at": datetime(2026, 6, 2, 10, 0, tzinfo=UTC),
            "delivered_at": datetime(2026, 6, 10, 11, 0, tzinfo=UTC),
        },
        "withdrawal-outside": {
            "_id": "withdrawal-outside",
            "seller_id": "seller-1",
            "withdrawal_id": "RET-OLD",
            "created_at": datetime(2026, 5, 1, tzinfo=UTC),
        },
    }
    dispatcher = _dispatcher(db)

    result = await dispatcher.execute(
        _context(
            "ZELERDATA_RETIROS",
            {"fecha_inicial": "2026-06-01", "fecha_final": "2026-06-30", "encabezados": "si"},
        )
    )

    assert result.values == [
        [
            "ID PRINCIPAL RETIRO",
            "ID SECUNDARIO RETIRO",
            "CODIGO ML",
            "ID PUBLICACION",
            "SKU",
            "TITULO",
            "UNIDADES SOLICITADAS",
            "FECHA DE CREACION",
            "FECHA DE ENTREGA",
        ],
        [
            "RET-1",
            "RET-1-ITEM-1",
            "INV-MLA1",
            "MLA1",
            "sku-1",
            "Withdrawal item",
            4,
            "2026-06-02T10:00:00+00:00",
            "2026-06-10T11:00:00+00:00",
        ],
    ]
    assert result.meta == {"rows_count": 1, "columns": "full_withdrawals"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("formula", "args", "read_model"),
    [
        ("ZELERDATA_CATALOGO", {"tipo_precio": "base"}, CATALOG_BUYBOX_SNAPSHOTS_READ_MODEL),
        ("ZELERDATA_TIEMPOSINSTOCK", {"tipo_precio": "base"}, STOCKOUT_SNAPSHOTS_READ_MODEL),
        (
            "ZELERDATA_TIEMPOSTOCKACTIVO",
            {"fecha_inicial": "2026-06-01", "fecha_final": "2026-06-14"},
            STOCK_TIME_METRICS_READ_MODEL,
        ),
        (
            "ZELERDATA_SEMANASCONSTOCK",
            {"fecha_inicial": "2026-06-01", "fecha_final": "2026-06-14"},
            STOCK_TIME_METRICS_READ_MODEL,
        ),
        ("ZELERDATA_PRECIOHISTORICO", {}, PRICE_HISTORY_SNAPSHOTS_READ_MODEL),
        (
            "ZELERDATA_CATALOGOTIEMPO",
            {"fecha_inicial": "2026-06-01", "fecha_final": "2026-06-14"},
            CATALOG_TIME_METRICS_READ_MODEL,
        ),
        (
            "ZELERDATA_RETIROS",
            {"fecha_inicial": "2026-06-01", "fecha_final": "2026-06-30"},
            FULL_WITHDRAWALS_READ_MODEL,
        ),
    ],
)
async def test_remaining_phase4_formulas_require_fresh_read_model_marker(
    formula: str, args: dict[str, Any], read_model: str
) -> None:
    dispatcher = _dispatcher(FakeDb())

    with pytest.raises(FormulaDataUnavailableError, match=formula) as error:
        await dispatcher.execute(_context(formula, args))

    assert read_model in str(error.value)
    assert "freshness/reconciliation" in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("formula", "args", "read_model"),
    [
        ("ZELERDATA_CATALOGO", {"tipo_precio": "base"}, CATALOG_BUYBOX_SNAPSHOTS_READ_MODEL),
        ("ZELERDATA_TIEMPOSINSTOCK", {"tipo_precio": "base"}, STOCKOUT_SNAPSHOTS_READ_MODEL),
        (
            "ZELERDATA_TIEMPOSTOCKACTIVO",
            {"fecha_inicial": "2026-06-01", "fecha_final": "2026-06-14"},
            STOCK_TIME_METRICS_READ_MODEL,
        ),
        (
            "ZELERDATA_SEMANASCONSTOCK",
            {"fecha_inicial": "2026-06-01", "fecha_final": "2026-06-14"},
            STOCK_TIME_METRICS_READ_MODEL,
        ),
        ("ZELERDATA_PRECIOHISTORICO", {}, PRICE_HISTORY_SNAPSHOTS_READ_MODEL),
        (
            "ZELERDATA_CATALOGOTIEMPO",
            {"fecha_inicial": "2026-06-01", "fecha_final": "2026-06-14"},
            CATALOG_TIME_METRICS_READ_MODEL,
        ),
        (
            "ZELERDATA_RETIROS",
            {"fecha_inicial": "2026-06-01", "fecha_final": "2026-06-30"},
            FULL_WITHDRAWALS_READ_MODEL,
        ),
    ],
)
async def test_remaining_phase4_formulas_reject_stale_read_model_marker(
    formula: str, args: dict[str, Any], read_model: str
) -> None:
    db = FakeDb()
    _mark_read_model_fresh(db, read_model, fresh_until=NOW - timedelta(days=1))
    dispatcher = _dispatcher(db)

    with pytest.raises(FormulaDataUnavailableError, match=formula) as error:
        await dispatcher.execute(_context(formula, args))

    assert read_model in str(error.value)
    assert "freshness/reconciliation" in str(error.value)


def _dispatcher(db: FakeDb) -> FormulaDispatcher:
    repository = FormulaReadModelRepository(db=db)
    return FormulaDispatcher(
        build_remaining_phase4_formula_handlers(repository, now_fn=lambda: NOW)
    )


def _mark_read_model_fresh(
    db: FakeDb,
    read_model: str,
    *,
    fresh_until: datetime = NOW + timedelta(days=1),
) -> None:
    db["sheets_read_model_freshness"].documents[f"seller-1:{read_model}"] = {
        "_id": f"seller-1:{read_model}",
        "seller_id": "seller-1",
        "read_model": read_model,
        "state": "fresh",
        "fresh_until": fresh_until,
        "reconciled_until": fresh_until,
        "updated_at": NOW,
        "schema_version": 1,
    }


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


def _item_row(
    *,
    item_id: str,
    sku: str,
    title: str,
    catalog_product_id: str,
    price: Decimal,
) -> dict[str, Any]:
    return {
        "_id": f"seller-1:{sku.upper()}:{item_id}",
        "seller_id": "seller-1",
        "item_id": item_id,
        "sku": sku,
        "normalized_sku": sku.upper(),
        "inventory_id": f"INV-{item_id}",
        "current": {
            "title": title,
            "status": "active",
            "permalink": f"https://meli.example/{item_id}",
            "available_quantity": 5,
            "base_price": price,
            "price": price,
            "catalog_product_id": catalog_product_id,
            "shipping_payer": "buyer",
        },
    }


def _order_doc(
    order_id: str,
    *,
    days_ago: int,
    quantity: int,
    status: str = "paid",
) -> dict[str, Any]:
    return {
        "_id": order_id,
        "seller_id": "seller-1",
        "date_created": NOW - timedelta(days=days_ago),
        "status": status,
        "items": [
            {
                "item_id": "MLA1",
                "sku": "sku-1",
                "title": "Catalog item",
                "quantity": quantity,
                "unit_price": Decimal("100"),
            }
        ],
    }


def _matches(doc: dict[str, Any], filter_spec: dict[str, Any]) -> bool:
    for key, expected in filter_spec.items():
        if key == "$or" and isinstance(expected, list):
            if not any(_matches(doc, branch) for branch in expected):
                return False
            continue
        value = _dotted_value(doc, key)
        if isinstance(expected, dict):
            if "$in" in expected and value not in expected["$in"]:
                return False
            try:
                if "$gte" in expected and (value is None or value < expected["$gte"]):
                    return False
                if "$lte" in expected and (value is None or value > expected["$lte"]):
                    return False
            except TypeError:
                return False
        elif value != expected:
            return False
    return True


def _dotted_value(doc: dict[str, Any], key: str) -> Any:
    current: Any = doc
    for part in key.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current
