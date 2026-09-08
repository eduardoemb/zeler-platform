# ruff: noqa: S105,S106

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from bson.int64 import Int64

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
@pytest.mark.parametrize("state", ["ready", "missing", "expired", "not_catalog"])
async def test_catalogo_uses_verified_inventory_and_requests_missing_competition(
    state: str,
) -> None:
    from unittest.mock import AsyncMock

    from zeler_sheets.formulas.handlers_remaining_phase4 import RemainingPhase4FormulaHandlers

    row = _item_row(
        item_id="MLA1",
        sku="sku",
        title="Publication",
        catalog_product_id="MLA9",
        price=Decimal("100"),
    )
    snapshot = {"item_id": "MLA1", "competitors_sharing_first_place": 0, "only_competitor": False}
    repository = AsyncMock(spec=FormulaReadModelRepository)
    repository.find_recent_item_inventory.return_value = ([row], ["MLA1"], (), state != "expired")
    repository.find_recent_catalog_buybox_inventory.return_value = (
        [snapshot] if state in {"ready", "expired"} else [],
        ("MLA1",) if state == "missing" else (),
        (),
        state != "expired",
    )
    repository.find_orders.return_value = []
    result = await RemainingPhase4FormulaHandlers(
        repository, now_fn=lambda: NOW
    ).sheetseller_catalogo(_context("ZELERDATA_CATALOGO", {"encabezados": False}))
    assert len(result.values) == (0 if state == "not_catalog" else 2 if state == "expired" else 1)
    if state in {"missing", "expired"}:
        assert result.recovery is not None
        assert result.recovery.read_model == (
            ITEM_FORMULA_ROWS_READ_MODEL
            if state == "expired"
            else CATALOG_BUYBOX_SNAPSHOTS_READ_MODEL
        )
        assert result.recovery.item_ids == (() if state == "expired" else ("MLA1",))
    else:
        assert result.recovery is None
    repository.find_catalog_buybox_snapshots.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("formula", "model"),
    [
        ("ZELERDATA_TIEMPOSINSTOCK", "stockout_snapshots"),
        ("ZELERDATA_TIEMPOSTOCKACTIVO", "stock_time_metrics"),
        ("ZELERDATA_SEMANASCONSTOCK", "stock_time_metrics"),
        ("ZELERDATA_PRECIOHISTORICO", "price_history_snapshots"),
        ("ZELERDATA_CATALOGOTIEMPO", "catalog_time_metrics"),
        ("ZELERDATA_RETIROS", "full_withdrawals"),
    ],
)
async def test_history_formulas_do_not_truncate_complete_read_models(
    formula: str, model: str
) -> None:
    db = FakeDb()
    start = datetime(2026, 6, 1, tzinfo=UTC)
    end = datetime(2026, 6, 15, tzinfo=UTC)
    _mark_read_model_fresh(
        db,
        model,
        date_from=start,
        fresh_until=NOW + timedelta(days=1)
        if model in {"stockout_snapshots", "price_history_snapshots"}
        else end,
    )
    db[f"sheets_{model}"].documents = {
        str(i): {
            "_id": str(i),
            "seller_id": "82453304",
            "item_id": f"MLM{i}",
            "date_from": start,
            "date_to": end,
            "created_at": start,
            "current_stock": 0,
            "out_of_stock_since": start,
        }
        for i in range(1001)
    }
    result = await _dispatcher(db).execute(
        _context(
            formula,
            {
                "fecha_inicial": "2026-06-01",
                "fecha_final": "2026-06-14",
                "id_publicaciones": "todos",
                "skus": "todos",
                "encabezados": False,
            },
        )
    )
    assert result.meta["rows_count"] == 1001
    assert len(result.values) == 1001


@pytest.mark.asyncio
async def test_catalog_sales_include_orders_beyond_the_old_5000_row_cap() -> None:
    db = FakeDb()
    for model in (
        CATALOG_BUYBOX_SNAPSHOTS_READ_MODEL,
        ITEM_FORMULA_ROWS_READ_MODEL,
        ORDERS_READ_MODEL,
    ):
        _mark_read_model_fresh(db, model)
    db["sheets_item_formula_rows"].documents = {
        "item": _item_row(
            item_id="MLA1",
            sku="sku-1",
            title="Catalog item",
            catalog_product_id="CAT-1",
            price=Decimal("100"),
        )
    }
    db["orders"].documents = {
        str(i): _order_doc(str(i), days_ago=1, quantity=1) for i in range(5001)
    }
    _seed_catalog_inventory(db)
    result = await _dispatcher(db).execute(_context("ZELERDATA_CATALOGO", {"encabezados": False}))
    assert result.values[0][9:15] == [5001] * 6
    assert result.values[0][21] == "DATA_UNAVAILABLE"
    assert result.meta["unavailable_shared_users"] == 1
    assert result.meta["unavailable_reason"] == "buybox_missing_expired_or_incomplete"


@pytest.mark.parametrize(
    "snapshot,expected",
    [
        ({"competitor_count": 99}, "DATA_UNAVAILABLE"),
        ({"competitors_sharing_first_place": 0, "competitor_count": 99}, 0),
        ({"competitors_sharing_first_place": Int64(3)}, 3),
        ({"competitors_sharing_first_place": None}, "NA"),
        ({"competitors_sharing_first_place": True}, "DATA_UNAVAILABLE"),
    ],
)
def test_catalogo_shared_users_keeps_absence_zero_and_unknown_distinct(
    snapshot: dict[str, Any], expected: Any
) -> None:
    from zeler_sheets.formulas.handlers_remaining_phase4 import _catalogo_row

    row = _catalogo_row({"item_id": "MLA1"}, buybox=snapshot, sales={}, tipo_precio="base")
    assert row[21] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("unrelated_buyboxes", [0, 1000])
async def test_catalogo_uses_local_item_catalog_buybox_and_sales_snapshots(
    unrelated_buyboxes: int,
) -> None:
    db = FakeDb()
    _mark_read_model_fresh(db, CATALOG_BUYBOX_SNAPSHOTS_READ_MODEL)
    _mark_read_model_fresh(db, ITEM_FORMULA_ROWS_READ_MODEL)
    _mark_read_model_fresh(db, ORDERS_READ_MODEL)
    db["sheets_item_formula_rows"].documents = {
        "82453304:SKU-1:MLA1": _item_row(
            item_id="MLA1",
            sku="sku-1",
            title="Catalog item",
            catalog_product_id="CAT-1",
            price=Decimal("100"),
        ),
    }
    db["sheets_catalog_buybox_snapshots"].documents = {
        "82453304:MLA1": {
            "_id": "82453304:MLA1",
            "seller_id": "82453304",
            "item_id": "MLA1",
            "catalog_product_id": "CAT-1",
            "catalog_url": "https://catalog.example/CAT-1",
            "buybox_status": "sharing_first_place",
            "winning_time_percent": Decimal("75.5"),
            "winning_price": Decimal("95"),
            "winning_user_id": "seller-competitor",
            "competitor_count": 99,
            "competitors_sharing_first_place": 3,
            "price_to_win": Decimal("94"),
            "only_competitor": "No",
        }
    }
    db["sheets_catalog_buybox_snapshots"].documents.update(
        {
            f"other-{i}": {"_id": f"other-{i}", "seller_id": "82453304", "item_id": f"AAA{i}"}
            for i in range(unrelated_buyboxes)
        }
    )
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
    _seed_catalog_inventory(db)
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
            "MLA9",
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
            "sharing_first_place",
            75.5,
            95,
            100,
            "seller-competitor",
            3,
            94,
            False,
        ],
    ]
    assert result.meta == {
        "rows_count": 1,
        "columns": "legacy_catalog_matrix",
        "unavailable_shared_users": 0,
        "inventory_enumeration_current": True,
        "unavailable_buybox_items": 0,
    }


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
    if expected_read_model == ORDERS_READ_MODEL:
        _seed_catalog_inventory(db)
    dispatcher = _dispatcher(db)

    with pytest.raises(FormulaDataUnavailableError, match="ZELERDATA_CATALOGO") as error:
        await dispatcher.execute(_context("ZELERDATA_CATALOGO", {"tipo_precio": "base"}))

    assert error.value.read_model == expected_read_model


@pytest.mark.asyncio
async def test_stock_history_formulas_use_local_stock_read_models() -> None:
    db = FakeDb()
    _mark_read_model_fresh(db, STOCKOUT_SNAPSHOTS_READ_MODEL)
    _mark_read_model_fresh(
        db,
        STOCK_TIME_METRICS_READ_MODEL,
        date_from=datetime(2026, 6, 1, tzinfo=UTC),
        fresh_until=datetime(2026, 6, 15, tzinfo=UTC),
    )
    db["sheets_stockout_snapshots"].documents = {
        "82453304:MLA1": {
            "_id": "82453304:MLA1",
            "seller_id": "82453304",
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
        "82453304:MLA2": {
            "_id": "82453304:MLA2",
            "seller_id": "82453304",
            "item_id": "MLA2",
            "sku": "sku-2",
            "title": "Has stock item",
            "price": Decimal("50"),
            "current_stock": 3,
            "out_of_stock_since": NOW - timedelta(days=1),
        },
    }
    db["sheets_stock_time_metrics"].documents = {
        "82453304:MLA1": {
            "_id": "82453304:MLA1",
            "seller_id": "82453304",
            "item_id": "MLA1",
            "sku": "sku-1",
            "title": "Stock item",
            "url": "https://meli.example/MLA1",
            "date_from": datetime(2026, 6, 1, tzinfo=UTC),
            "date_to": datetime(2026, 6, 15, tzinfo=UTC),
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
    _mark_read_model_fresh(
        db,
        CATALOG_TIME_METRICS_READ_MODEL,
        date_from=datetime(2026, 6, 1, tzinfo=UTC),
        fresh_until=datetime(2026, 6, 15, tzinfo=UTC),
    )
    db["sheets_price_history_snapshots"].documents = {
        "82453304:MLA1": {
            "_id": "82453304:MLA1",
            "seller_id": "82453304",
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
        "82453304:MLA1": {
            "_id": "82453304:MLA1",
            "seller_id": "82453304",
            "item_id": "MLA1",
            "title": "Catalog winner",
            "url": "https://meli.example/MLA1",
            "date_from": datetime(2026, 6, 1, tzinfo=UTC),
            "date_to": datetime(2026, 6, 15, tzinfo=UTC),
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
            "seller_id": "82453304",
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
            "seller_id": "82453304",
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
        ("ZELERDATA_CATALOGO", {"tipo_precio": "base"}, ITEM_FORMULA_ROWS_READ_MODEL),
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

    assert error.value.read_model == read_model
    assert (
        "inventory enumeration" if formula == "ZELERDATA_CATALOGO" else "freshness/reconciliation"
    ) in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("formula", "args", "read_model"),
    [
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
async def test_source_gated_formulas_require_interval_marker_coverage_from_range_start(
    formula: str, args: dict[str, Any], read_model: str
) -> None:
    db = FakeDb()
    db["sheets_read_model_freshness"].documents[f"82453304:{read_model}"] = {
        "_id": f"82453304:{read_model}",
        "seller_id": "82453304",
        "read_model": read_model,
        "state": "reconciled",
        "date_from": datetime(2026, 6, 5, tzinfo=UTC),
        "fresh_until": datetime(2026, 7, 1, tzinfo=UTC),
        "reconciled_until": datetime(2026, 7, 1, tzinfo=UTC),
        "last_event_synced_at": datetime(2026, 6, 5, tzinfo=UTC),
        "coverage_basis": "observed_only",
        "updated_at": NOW,
        "schema_version": 1,
    }
    dispatcher = _dispatcher(db)

    with pytest.raises(FormulaDataUnavailableError, match=formula) as error:
        await dispatcher.execute(_context(formula, args))

    assert read_model in str(error.value)
    assert (
        "inventory enumeration" if formula == "ZELERDATA_CATALOGO" else "freshness/reconciliation"
    ) in str(error.value)


@pytest.mark.asyncio
async def test_interval_aggregate_formula_rejects_broader_marker_and_metric_row() -> None:
    db = FakeDb()
    _mark_read_model_fresh(
        db,
        STOCK_TIME_METRICS_READ_MODEL,
        date_from=datetime(2026, 6, 1, tzinfo=UTC),
        fresh_until=datetime(2026, 7, 1, tzinfo=UTC),
    )
    db["sheets_stock_time_metrics"].documents = {
        "82453304:MLA1:SKU1:2026-06-01:2026-07-01": {
            "_id": "82453304:MLA1:SKU1:2026-06-01:2026-07-01",
            "seller_id": "82453304",
            "item_id": "MLA1",
            "sku": "sku-1",
            "normalized_sku": "SKU-1",
            "date_from": datetime(2026, 6, 1, tzinfo=UTC),
            "date_to": datetime(2026, 7, 1, tzinfo=UTC),
            "active_stock_hours": Decimal("720"),
            "total_hours": Decimal("720"),
            "active_stock_percent": Decimal("100"),
            "weeks": [{"start_day": 1, "end_day": 30, "has_stock": True}],
        }
    }
    dispatcher = _dispatcher(db)

    with pytest.raises(FormulaDataUnavailableError, match="ZELERDATA_TIEMPOSTOCKACTIVO"):
        await dispatcher.execute(
            _context(
                "ZELERDATA_TIEMPOSTOCKACTIVO",
                {
                    "fecha_inicial": "2026-06-01",
                    "fecha_final": "2026-06-14",
                    "id_publicaciones": "todos",
                },
            )
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("formula", "args", "read_model"),
    [
        ("ZELERDATA_CATALOGO", {"tipo_precio": "base"}, ITEM_FORMULA_ROWS_READ_MODEL),
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

    assert error.value.read_model == read_model
    assert (
        "inventory enumeration" if formula == "ZELERDATA_CATALOGO" else "freshness/reconciliation"
    ) in str(error.value)


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
    date_from: datetime | None = None,
) -> None:
    source_gated = {
        STOCK_TIME_METRICS_READ_MODEL,
        CATALOG_TIME_METRICS_READ_MODEL,
        FULL_WITHDRAWALS_READ_MODEL,
    }
    source_gated_date_from = date_from or NOW - timedelta(days=400)
    db["sheets_read_model_freshness"].documents[f"82453304:{read_model}"] = {
        "_id": f"82453304:{read_model}",
        "seller_id": "82453304",
        "read_model": read_model,
        "state": "reconciled" if read_model in source_gated else "fresh",
        "fresh_until": fresh_until,
        "date_from": source_gated_date_from if read_model in source_gated else None,
        "reconciled_until": fresh_until,
        "last_event_synced_at": source_gated_date_from if read_model in source_gated else None,
        "coverage_basis": "legacy_imported" if read_model in source_gated else None,
        "updated_at": NOW,
        "schema_version": 1,
    }


def _context(formula: str, args: dict[str, Any]) -> FormulaExecutionContext:
    return FormulaExecutionContext(
        contract=FormulaRegistry.default().find_required(formula),
        cuenta="HOPEMOB",
        seller_id="82453304",
        seller_nickname="HOPEMOB",
        token_id="token-1",
        args=args,
        request_id="req-1",
    )


def _seed_catalog_inventory(db: FakeDb) -> None:
    from zeler_sheets.formulas.recovery import ItemInventoryRecoveryRequest
    from zeler_sheets.item_projection import item_source_fingerprint

    ids = []
    for row in db["sheets_item_formula_rows"].documents.values():
        identity = row["item_id"]
        ids.append(identity)
        row["current"].update(catalog_listing=True, catalog_product_id="MLA9")
        source = {
            "_id": identity,
            "seller_id": "82453304",
            **{
                key: str(value) if isinstance(value, Decimal) else value
                for key, value in row["current"].items()
            },
            "last_meli_sync_at": NOW,
        }
        db["items"].documents[identity] = source
        row["source_snapshot"] = {
            "fingerprint": item_source_fingerprint(source),
            "observed_at": NOW,
            "rows_count": 1,
        }
        snapshot = db["sheets_catalog_buybox_snapshots"].documents.get(f"82453304:{identity}")
        if snapshot is not None:
            snapshot.update(
                catalog_product_id="MLA9",
                title=source["title"],
                available_quantity=source["available_quantity"],
                snapshot_at=NOW,
                source="sheets_backfill",
                only_competitor=False,
            )
    key = ItemInventoryRecoveryRequest("82453304").key
    db["sheets_formula_recovery_jobs"].documents[key] = {
        "_id": key,
        "seller_id": "82453304",
        "read_model": ITEM_FORMULA_ROWS_READ_MODEL,
        "inventory_scope": True,
        "state": "completed",
        "inventory_ids": sorted(ids),
        "inventory_observed_at": NOW,
        "inventory_offset": len(ids),
    }


def _item_row(
    *,
    item_id: str,
    sku: str,
    title: str,
    catalog_product_id: str,
    price: Decimal,
) -> dict[str, Any]:
    return {
        "_id": f"82453304:{sku.upper()}:{item_id}",
        "seller_id": "82453304",
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
        "seller_id": "82453304",
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
