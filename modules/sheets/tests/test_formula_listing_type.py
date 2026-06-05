# ruff: noqa: S106

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pytest

from zeler_sheets.formulas.dispatcher import FormulaDispatcher, FormulaExecutionContext
from zeler_sheets.formulas.handlers_core import build_core_formula_handlers
from zeler_sheets.formulas.read_models import FormulaReadModelRepository
from zeler_sheets.formulas.registry import FormulaRegistry

PUBLICACIONES_LEGACY_HEADERS = [
    "ID Publicación",
    "Título",
    "SKU",
    "Stock Actual",
    "Precio",
    "Logística",
    "URL",
    "Tipo De Publicación",
    "Status",
    "Código ML",
    "ID Inventario",
    "Tiempo En Pausa",
]

DASHBOARD_LEGACY_HEADERS = [
    "ID Publicación",
    "Título",
    "SKU",
    "Stock Actual",
    "Precio",
    "Logística",
    "URL",
    "Tipo De Publicación",
    "Status",
    "Código ML",
    "Días Pausada",
    "Ventas (7 días)",
    "Ventas (15 días)",
    "Ventas (30 días)",
    "Ventas (60 días)",
    "Ventas (90 días)",
    "Envió A Cargo De",
    "Costo De Envío",
    "% Comisión",
    "Comisión",
    "Costo Por Unidad",
    "Tiene Catálogo",
    "ID Carrito (7 días)",
    "ID Carrito (15 días)",
    "ID Carrito (30 días)",
    "ID Carrito (60 días)",
    "ID Carrito (90 días)",
]


class FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs

    def sort(self, sort_spec: list[tuple[str, int]]) -> FakeCursor:
        sorted_docs = list(self._docs)
        for key, direction in reversed(sort_spec):
            sorted_docs.sort(key=lambda doc: str(doc.get(key, "")), reverse=direction < 0)
        return FakeCursor(sorted_docs)

    async def to_list(self, length: int) -> list[dict[str, Any]]:
        return [dict(doc) for doc in self._docs[:length]]


class FakeCollection:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}

    def find(self, filter_spec: dict[str, Any]) -> FakeCursor:
        return FakeCursor(
            [dict(doc) for doc in self.documents.values() if _matches(doc, filter_spec)]
        )


class FakeDb:
    def __init__(self) -> None:
        self.collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        return self.collections.setdefault(name, FakeCollection())


def _matches(doc: Mapping[str, Any], filter_spec: Mapping[str, Any]) -> bool:
    for key, expected in filter_spec.items():
        value = doc.get(key)
        if isinstance(expected, dict):
            if "$in" in expected and value not in expected["$in"]:
                return False
        elif value != expected:
            return False
    return True


@pytest.mark.asyncio
async def test_publicaciones_dashboard_and_sin_catalogo_emit_listing_type_or_na() -> None:
    db = FakeDb()
    db["sheets_item_formula_rows"].documents = {
        "seller-1-sku-1-mla1": _formula_row(
            sku="sku-1",
            normalized_sku="SKU-1",
            item_id="MLA1",
            title="Listing with type",
            status="active",
            available_quantity=7,
            base_price=100,
            listing_type_id="gold_special",
        ),
        "seller-1-sku-2-mla2": _formula_row(
            sku="sku-2",
            normalized_sku="SKU-2",
            item_id="MLA2",
            title="Listing without type",
            status="paused",
            available_quantity=0,
            base_price=50,
            listing_type_id=None,
        ),
    }
    dispatcher = _core_dispatcher(db)

    publicaciones = await dispatcher.execute(
        _context("ZELERDATA_PUBLICACIONES", {"skus": "todos", "encabezados": "si"})
    )
    dashboard = await dispatcher.execute(
        _context("ZELERDATA_DASHBOARD", {"skus": "todos", "encabezados": "si"})
    )
    sin_catalogo = await dispatcher.execute(
        _context("ZELERDATA_DASHBOARDSINCATALOGO", {"skus": "todos", "encabezados": "si"})
    )

    assert [row[7] for row in publicaciones.values[1:]] == ["gold_special", "NA"]
    assert all(len(row) == len(PUBLICACIONES_LEGACY_HEADERS) for row in publicaciones.values)
    assert [row[7] for row in dashboard.values[1:]] == ["gold_special", "NA"]
    assert all(len(row) == len(DASHBOARD_LEGACY_HEADERS) for row in dashboard.values)
    assert [row[7] for row in sin_catalogo.values[1:]] == ["gold_special", "NA"]
    assert all(len(row) == len(DASHBOARD_LEGACY_HEADERS) for row in sin_catalogo.values)


def _formula_row(
    *,
    sku: str,
    normalized_sku: str,
    item_id: str,
    title: str,
    status: str,
    available_quantity: int,
    base_price: int,
    listing_type_id: str | None,
) -> dict[str, Any]:
    return {
        "_id": f"seller-1-{normalized_sku}-{item_id}",
        "seller_id": "seller-1",
        "sku": sku,
        "normalized_sku": normalized_sku,
        "item_id": item_id,
        "current": {
            "title": title,
            "status": status,
            "available_quantity": available_quantity,
            "base_price": base_price,
            "listing_type_id": listing_type_id,
        },
    }


def _core_dispatcher(db: FakeDb) -> FormulaDispatcher:
    return FormulaDispatcher(
        build_core_formula_handlers(
            FormulaReadModelRepository(db=db),
            now_fn=lambda: datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
        )
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
