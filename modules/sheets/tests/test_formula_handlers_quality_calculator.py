# ruff: noqa: S105,S106

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from zeler_sheets.formulas.dispatcher import (
    FormulaDataUnavailableError,
    FormulaDispatcher,
    FormulaExecutionContext,
)
from zeler_sheets.formulas.handlers_quality_calculator import (
    build_quality_calculator_formula_handlers,
)
from zeler_sheets.formulas.read_models import (
    ITEM_FORMULA_ROWS_READ_MODEL,
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
QUALITY_CALCULATED_AT = datetime(2026, 6, 14, 9, 30, tzinfo=UTC)


@pytest.mark.asyncio
async def test_calidad_uses_modern_local_quality_projection_without_suggested_price() -> None:
    db = FakeDb()
    _mark_read_model_fresh(db, ITEM_FORMULA_ROWS_READ_MODEL)
    db["sheets_item_formula_rows"].documents = {
        "seller-1:SKU-1:MLA1": _item_row(
            item_id="MLA1",
            sku="sku-1",
            title="Quality item",
            status="active",
            quality_projection={
                "score": Decimal("0.88"),
                "level": "good",
                "calculated_at": QUALITY_CALCULATED_AT,
                "components": {
                    "gtin": {"status": "ok", "score": Decimal("1")},
                    "images": {"status": "warning", "score": Decimal("0.7")},
                    "title": {"status": "ok", "score": Decimal("0.9")},
                    "shipping": {"status": "ok", "score": Decimal("1")},
                },
                "pending_actions": ["ADD_IMAGES", "IMPROVE_TITLE"],
            },
        ),
        "seller-1:SKU-2:MLA2": _item_row(
            item_id="MLA2",
            sku="sku-2",
            title="Health fallback item",
            status="paused",
            health=Decimal("0.51"),
        ),
    }
    dispatcher = _dispatcher(db)

    result = await dispatcher.execute(_context("ZELERDATA_CALIDAD", {"encabezados": "si"}))

    assert "PRECIO SUGERIDO" not in result.values[0]
    assert result.values == [
        [
            "ID PUBLICACION",
            "SKU",
            "TITULO",
            "STATUS",
            "URL",
            "STOCK ACTUAL",
            "TIPO DE PUBLICACION",
            "PUNTAJE CALIDAD",
            "NIVEL CALIDAD",
            "CALCULADO EN",
            "ESTADO GTIN",
            "PUNTAJE GTIN",
            "ESTADO IMAGENES",
            "PUNTAJE IMAGENES",
            "ESTADO TITULO",
            "PUNTAJE TITULO",
            "ESTADO MERCADO ENVIOS",
            "PUNTAJE MERCADO ENVIOS",
            "ACCIONES PENDIENTES",
        ],
        [
            "MLA1",
            "sku-1",
            "Quality item",
            "active",
            "https://meli.example/MLA1",
            7,
            "gold_special",
            0.88,
            "good",
            "2026-06-14T09:30:00+00:00",
            "ok",
            1,
            "warning",
            0.7,
            "ok",
            0.9,
            "ok",
            1,
            "ADD_IMAGES | IMPROVE_TITLE",
        ],
        [
            "MLA2",
            "sku-2",
            "Health fallback item",
            "paused",
            "https://meli.example/MLA2",
            7,
            "gold_special",
            0.51,
            "regular",
            "NA",
            "NA",
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
    assert result.meta == {"rows_count": 2, "columns": "modern_quality_projection"}


@pytest.mark.asyncio
async def test_calidad_handler_can_be_reused_across_recalculations() -> None:
    db = FakeDb()
    _mark_read_model_fresh(db, ITEM_FORMULA_ROWS_READ_MODEL)
    db["sheets_item_formula_rows"].documents = {
        "seller-1:SKU-1:MLA1": _item_row(
            item_id="MLA1",
            sku="sku-1",
            title="Quality item",
            status="active",
            quality_projection={"score": Decimal("0.88"), "level": "good"},
        ),
    }
    dispatcher = _dispatcher(db)
    context = _context("ZELERDATA_CALIDAD", {"encabezados": "si"})

    first = await dispatcher.execute(context)
    second = await dispatcher.execute(context)

    assert first.values == second.values
    assert first.meta == second.meta


@pytest.mark.asyncio
async def test_calculadora_projects_costs_from_local_fee_shipping_and_catalog_data() -> None:
    db = FakeDb()
    _mark_read_model_fresh(db, ITEM_FORMULA_ROWS_READ_MODEL)
    db["sheets_item_formula_rows"].documents = {
        "seller-1:SKU-1:MLA1": _item_row(
            item_id="MLA1",
            sku="sku-1",
            title="Costed item",
            status="active",
            price=Decimal("100"),
            base_price=Decimal("120"),
            seller_shipping_cost=Decimal("25.50"),
            listing_fee_projection={
                "sale_fee_amount": Decimal("15.25"),
                "percentage_fee": Decimal("13.5"),
            },
            listing_price_fixed_fee={"fixed_fee": Decimal("8")},
            category_id="MLA-CAT",
            catalog_product_id="CAT-1",
            logistic_type="fulfillment",
        ),
        "seller-1:SKU-2:MLA2": _item_row(
            item_id="MLA2",
            sku="sku-2",
            title="Missing costs item",
            status="active",
            price=Decimal("80"),
            base_price=Decimal("80"),
            category_id="MLA-OTHER",
            catalog_product_id=None,
            logistic_type="cross_docking",
        ),
    }
    dispatcher = _dispatcher(db)

    result = await dispatcher.execute(
        _context(
            "ZELERDATA_CALCULADORA",
            {"id_publicaciones": ["MLA1", "MLA2", "MLA-X"], "encabezados": "si"},
        )
    )

    assert result.values == [
        [
            "ID PUBLICACION",
            "SKU",
            "TITULO",
            "DIVISA",
            "PRECIO",
            "COSTO ENVIO VENDEDOR",
            "COMISION",
            "% COMISION",
            "COSTO FIJO POR UNIDAD",
            "CATEGORIA",
            "CATALOGO",
            "LOGISTICA",
            "TIPO DE PUBLICACION",
            "TOTAL COSTOS",
            "NETO ESTIMADO",
        ],
        [
            "MLA1",
            "sku-1",
            "Costed item",
            "MXN",
            100,
            25.5,
            15.25,
            13.5,
            8,
            "MLA-CAT",
            "CATALOGO",
            "fulfillment",
            "gold_special",
            48.75,
            51.25,
        ],
        [
            "MLA2",
            "sku-2",
            "Missing costs item",
            "MXN",
            80,
            "NA",
            "NA",
            "NA",
            "NA",
            "MLA-OTHER",
            "REGULAR",
            "cross_docking",
            "gold_special",
            "NA",
            "NA",
        ],
        [
            "MLA-X",
            "NA",
            "NA",
            "NA",
            "NA",
            "NA",
            "NA",
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
    assert result.meta == {
        "partial_misses": 1,
        "rows_count": 3,
        "columns": "modern_cost_projection",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("formula", "args"),
    [
        ("ZELERDATA_CALIDAD", {"encabezados": "si"}),
        ("ZELERDATA_CALCULADORA", {"id_publicaciones": ["MLA1"], "encabezados": "si"}),
    ],
)
async def test_quality_calculator_formulas_require_fresh_item_read_model_marker(
    formula: str, args: dict[str, Any]
) -> None:
    dispatcher = _dispatcher(FakeDb())

    with pytest.raises(FormulaDataUnavailableError, match=formula) as error:
        await dispatcher.execute(_context(formula, args))

    assert ITEM_FORMULA_ROWS_READ_MODEL in str(error.value)
    assert "freshness/reconciliation" in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("formula", "args"),
    [
        ("ZELERDATA_CALIDAD", {"encabezados": "si"}),
        ("ZELERDATA_CALCULADORA", {"id_publicaciones": ["MLA1"], "encabezados": "si"}),
    ],
)
async def test_quality_calculator_formulas_reject_stale_item_read_model_marker(
    formula: str, args: dict[str, Any]
) -> None:
    db = FakeDb()
    _mark_read_model_fresh(db, ITEM_FORMULA_ROWS_READ_MODEL, fresh_until=NOW.replace(day=14))
    dispatcher = _dispatcher(db)

    with pytest.raises(FormulaDataUnavailableError, match=formula) as error:
        await dispatcher.execute(_context(formula, args))

    assert ITEM_FORMULA_ROWS_READ_MODEL in str(error.value)
    assert "freshness/reconciliation" in str(error.value)


def _dispatcher(db: FakeDb) -> FormulaDispatcher:
    repository = FormulaReadModelRepository(db=db)
    return FormulaDispatcher(
        build_quality_calculator_formula_handlers(repository, now_fn=lambda: NOW)
    )


def _mark_read_model_fresh(
    db: FakeDb,
    read_model: str,
    *,
    fresh_until: datetime = NOW,
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
    status: str,
    price: Decimal = Decimal("100"),
    base_price: Decimal = Decimal("100"),
    seller_shipping_cost: Decimal | None = None,
    listing_fee_projection: dict[str, Any] | None = None,
    listing_price_fixed_fee: dict[str, Any] | None = None,
    category_id: str = "MLA-CAT",
    catalog_product_id: str | None = None,
    logistic_type: str = "drop_off",
    health: Decimal | None = None,
    quality_projection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current: dict[str, Any] = {
        "title": title,
        "status": status,
        "available_quantity": 7,
        "price": price,
        "base_price": base_price,
        "currency_id": "MXN",
        "category_id": category_id,
        "catalog_product_id": catalog_product_id,
        "listing_type_id": "gold_special",
        "shipping_logistic_type": logistic_type,
        "permalink": f"https://meli.example/{item_id}",
    }
    if seller_shipping_cost is not None:
        current["seller_shipping_cost"] = seller_shipping_cost
    if listing_fee_projection is not None:
        current["listing_fee_projection"] = listing_fee_projection
    if listing_price_fixed_fee is not None:
        current["listing_price_fixed_fee"] = listing_price_fixed_fee
    if health is not None:
        current["health"] = health
    if quality_projection is not None:
        current["quality_projection"] = quality_projection
    return {
        "_id": f"seller-1:{sku.upper()}:{item_id}",
        "seller_id": "seller-1",
        "item_id": item_id,
        "sku": sku,
        "normalized_sku": sku.upper(),
        "current": current,
    }


def _matches(doc: dict[str, Any], filter_spec: dict[str, Any]) -> bool:
    for key, expected in filter_spec.items():
        value = _dotted_value(doc, key)
        if isinstance(expected, dict):
            try:
                if "$in" in expected and value not in expected["$in"]:
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
