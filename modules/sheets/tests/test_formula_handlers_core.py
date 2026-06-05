# ruff: noqa: S105,S106

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from zeler_sheets.extension_tokens import ExtensionTokenService, SellerScope
from zeler_sheets.formulas.dispatcher import FormulaDispatcher, FormulaExecutionContext
from zeler_sheets.formulas.handlers_core import build_core_formula_handlers
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
            sorted_docs.sort(key=lambda doc: str(doc.get(key, "")), reverse=direction < 0)
        return FakeCursor(sorted_docs)

    async def to_list(self, length: int) -> list[dict[str, Any]]:
        return [dict(doc) for doc in self._docs[:length]]


class FakeCollection:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}
        self.last_find_filter: dict[str, Any] | None = None

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
        self.collections: dict[str, FakeCollection] = {}

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
async def test_sku_and_id_handlers_use_seller_scoped_sku_index_and_preserve_range_order() -> None:
    db = FakeDb()
    sku_index = db["sheets_item_sku_index"]
    sku_index.documents = {
        "seller-1-sku-1-a": {
            "_id": "seller-1-sku-1-a",
            "seller_id": "seller-1",
            "sku": "sku-1",
            "normalized_sku": "SKU-1",
            "item_id": "MLA1",
        },
        "seller-1-sku-1-b": {
            "_id": "seller-1-sku-1-b",
            "seller_id": "seller-1",
            "sku": "sku-1",
            "normalized_sku": "SKU-1",
            "item_id": "MLA3",
        },
        "seller-1-sku-2": {
            "_id": "seller-1-sku-2",
            "seller_id": "seller-1",
            "sku": "Sku 2",
            "normalized_sku": "SKU-2",
            "item_id": "MLA2",
        },
        "seller-2-sku-1": {
            "_id": "seller-2-sku-1",
            "seller_id": "seller-2",
            "sku": "sku-1",
            "normalized_sku": "SKU-1",
            "item_id": "MLB1",
        },
    }
    dispatcher = _core_dispatcher(db)

    sku_result = await dispatcher.execute(
        _context("ZELERDATA_SKU", {"skus": [[" sku-1 ", "SKU-2"], ["SKU-1", "missing"]]})
    )
    id_result = await dispatcher.execute(
        _context("ZELERDATA_ID", {"skus": [[" sku-1 ", "SKU-2"], ["SKU-1", "missing"]]})
    )

    assert sku_result.values == [["sku-1"], ["Sku 2"]]
    assert sku_result.meta == {"partial_misses": 1}
    assert id_result.values == [["MLA1"], ["MLA3"], ["MLA2"]]
    assert id_result.meta == {"partial_misses": 1}
    assert sku_index.last_find_filter == {
        "seller_id": "seller-1",
        "normalized_sku": {"$in": ["SKU-1", "SKU-2", "MISSING"]},
    }


@pytest.mark.asyncio
async def test_stock_and_precio_handlers_lookup_scalar_and_range_pairs_with_blanks_for_misses() -> (
    None
):
    db = FakeDb()
    formula_rows = db["sheets_item_formula_rows"]
    formula_rows.documents = {
        "seller-1-sku-1-mla1": {
            "_id": "seller-1-sku-1-mla1",
            "seller_id": "seller-1",
            "normalized_sku": "SKU-1",
            "item_id": "MLA1",
            "current": {"available_quantity": 7, "base_price": 123.45},
        },
        "seller-1-sku-2-mla2": {
            "_id": "seller-1-sku-2-mla2",
            "seller_id": "seller-1",
            "normalized_sku": "SKU-2",
            "item_id": "MLA2",
            "current": {"available_quantity": 0, "base_price": 10},
        },
        "seller-2-sku-1-mla1": {
            "_id": "seller-2-sku-1-mla1",
            "seller_id": "seller-2",
            "normalized_sku": "SKU-1",
            "item_id": "MLA1",
            "current": {"available_quantity": 99, "base_price": 999},
        },
    }
    dispatcher = _core_dispatcher(db)

    scalar_stock = await dispatcher.execute(
        _context("ZELERDATA_STOCK", {"skus": " sku-1 ", "id_publicaciones": "MLA1"})
    )
    range_stock = await dispatcher.execute(
        _context(
            "ZELERDATA_STOCK",
            {
                "skus": [["sku-1"], ["sku-2"], ["missing"]],
                "id_publicaciones": ["MLA1", "MLA2", "MLA-X"],
            },
        )
    )
    range_precio = await dispatcher.execute(
        _context(
            "ZELERDATA_PRECIO",
            {
                "skus": ["sku-1", "sku-2", "missing"],
                "id_publicaciones": ["MLA1", "MLA2", "MLA-X"],
                "tipo_precio": "base",
            },
        )
    )

    assert scalar_stock.values == [[7]]
    assert range_stock.values == [[7], [0], [""]]
    assert range_stock.meta == {"partial_misses": 1}
    assert range_precio.values == [[123.45], [10], [""]]
    assert range_precio.meta == {"partial_misses": 1}
    assert formula_rows.last_find_filter == {
        "seller_id": "seller-1",
        "normalized_sku": {"$in": ["SKU-1", "SKU-2", "MISSING"]},
        "item_id": {"$in": ["MLA1", "MLA2", "MLA-X"]},
    }


@pytest.mark.asyncio
async def test_title_status_and_days_handlers_lookup_item_ids_with_blanks_for_misses() -> None:
    now = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
    db = FakeDb()
    formula_rows = db["sheets_item_formula_rows"]
    formula_rows.documents = {
        "seller-1-sku-1-mla1": {
            "_id": "seller-1-sku-1-mla1",
            "seller_id": "seller-1",
            "normalized_sku": "SKU-1",
            "item_id": "MLA1",
            "inventory_id": "INV-1",
            "current": {
                "title": "First listing",
                "status": "active",
                "date_created": datetime(2026, 4, 1, 8, 30, tzinfo=UTC),
            },
        },
        "seller-1-sku-2-mla2": {
            "_id": "seller-1-sku-2-mla2",
            "seller_id": "seller-1",
            "normalized_sku": "SKU-2",
            "item_id": "MLA2",
            "inventory_id": "INV-2",
            "current": {
                "title": "Second listing",
                "status": "paused",
                "date_created": "2026-05-10T11:00:00+00:00",
            },
        },
        "seller-2-sku-1-mla1": {
            "_id": "seller-2-sku-1-mla1",
            "seller_id": "seller-2",
            "normalized_sku": "SKU-1",
            "item_id": "MLA1",
            "current": {
                "title": "Wrong tenant",
                "status": "active",
                "date_created": datetime(2020, 1, 1, tzinfo=UTC),
            },
        },
    }
    dispatcher = _core_dispatcher(db, now=now)

    scalar_title = await dispatcher.execute(
        _context("ZELERDATA_TITULO", {"id_publicaciones": "MLA1"})
    )
    range_status = await dispatcher.execute(
        _context("ZELERDATA_STATUS", {"id_publicaciones": [["MLA1"], ["MLA2"], ["MLA-X"]]})
    )
    range_days = await dispatcher.execute(
        _context("ZELERDATA_DIASPUBLICADA", {"id_publicaciones": ["MLA1", "MLA2", "MLA-X"]})
    )

    assert scalar_title.values == [["First listing"]]
    assert scalar_title.meta == {"partial_misses": 0}
    assert range_status.values == [["active"], ["paused"], [""]]
    assert range_status.meta == {"partial_misses": 1}
    assert range_days.values == [[42], [3], [""]]
    assert range_days.meta == {"partial_misses": 1}
    assert formula_rows.last_find_filter == {
        "seller_id": "seller-1",
        "item_id": {"$in": ["MLA1", "MLA2", "MLA-X"]},
    }


@pytest.mark.asyncio
async def test_url_and_codigo_ml_handlers_lookup_sku_item_pairs_with_blanks_for_misses() -> None:
    db = FakeDb()
    formula_rows = db["sheets_item_formula_rows"]
    formula_rows.documents = {
        "seller-1-sku-1-mla1": {
            "_id": "seller-1-sku-1-mla1",
            "seller_id": "seller-1",
            "normalized_sku": "SKU-1",
            "item_id": "MLA1",
            "inventory_id": "INV-1",
            "current": {"permalink": "https://meli.example/mla1"},
        },
        "seller-1-sku-2-mla2": {
            "_id": "seller-1-sku-2-mla2",
            "seller_id": "seller-1",
            "normalized_sku": "SKU-2",
            "item_id": "MLA2",
            "current": {"permalink": "https://meli.example/mla2", "inventory_id": "INV-2"},
        },
        "seller-2-sku-1-mla1": {
            "_id": "seller-2-sku-1-mla1",
            "seller_id": "seller-2",
            "normalized_sku": "SKU-1",
            "item_id": "MLA1",
            "inventory_id": "WRONG-TENANT",
            "current": {"permalink": "https://meli.example/wrong"},
        },
    }
    dispatcher = _core_dispatcher(db)

    scalar_url = await dispatcher.execute(
        _context("ZELERDATA_URL", {"skus": "sku-1", "id_publicaciones": "MLA1"})
    )
    range_codigo = await dispatcher.execute(
        _context(
            "ZELERDATA_CODIGOML",
            {
                "skus": [["sku-1"], ["sku-2"], ["missing"]],
                "id_publicaciones": ["MLA1", "MLA2", "MLA-X"],
            },
        )
    )

    assert scalar_url.values == [["https://meli.example/mla1"]]
    assert scalar_url.meta == {"partial_misses": 0}
    assert range_codigo.values == [["INV-1"], ["INV-2"], ["NA"]]
    assert range_codigo.meta == {"partial_misses": 1}
    assert formula_rows.last_find_filter == {
        "seller_id": "seller-1",
        "normalized_sku": {"$in": ["SKU-1", "SKU-2", "MISSING"]},
        "item_id": {"$in": ["MLA1", "MLA2", "MLA-X"]},
    }


@pytest.mark.asyncio
async def test_item_formula_handlers_return_blanks_without_enriched_source_fields() -> None:
    db = FakeDb()
    db["sheets_item_formula_rows"].documents = {
        "seller-1-sku-1-mla1": {
            "_id": "seller-1-sku-1-mla1",
            "seller_id": "seller-1",
            "sku": "sku-1",
            "normalized_sku": "SKU-1",
            "item_id": "MLA1",
            "inventory_id": None,
            "current": {
                "permalink": None,
                "thumbnail": None,
                "catalog_product_id": None,
                "inventory_id": None,
            },
        }
    }
    dispatcher = _core_dispatcher(db)

    url = await dispatcher.execute(
        _context("ZELERDATA_URL", {"skus": "sku-1", "id_publicaciones": "MLA1"})
    )
    imagen = await dispatcher.execute(
        _context("ZELERDATA_IMAGENES", {"skus": "sku-1", "id_publicaciones": "MLA1"})
    )
    codigo = await dispatcher.execute(
        _context("ZELERDATA_CODIGOML", {"skus": "sku-1", "id_publicaciones": "MLA1"})
    )

    assert url.values == [[""]]
    assert url.meta == {"partial_misses": 1}
    assert imagen.values == [[""]]
    assert imagen.meta == {
        "partial_misses": 1,
        "columns": "thumbnail_url",
        "image_variant": "principal",
    }
    assert codigo.values == [["NA"]]
    assert codigo.meta == {"partial_misses": 1}


@pytest.mark.asyncio
async def test_publicaciones_dashboard_emit_na_for_deferred_fields_and_current_shipping() -> None:
    db = FakeDb()
    db["sheets_item_formula_rows"].documents = {
        "seller-1-sku-1-mla1": {
            "_id": "seller-1-sku-1-mla1",
            "seller_id": "seller-1",
            "sku": "sku-1",
            "normalized_sku": "SKU-1",
            "item_id": "MLA1",
            "inventory_id": None,
            "current": {
                "title": "First listing",
                "status": "active",
                "available_quantity": 0,
                "base_price": 0,
                "shipping_logistic_type": "fulfillment",
                "shipping_payer": "Vendedor",
            },
        },
    }
    dispatcher = _core_dispatcher(db)

    publicaciones = await dispatcher.execute(
        _context("ZELERDATA_PUBLICACIONES", {"skus": "todos", "encabezados": "si"})
    )
    dashboard = await dispatcher.execute(
        _context(
            "ZELERDATA_DASHBOARD",
            {"skus": "todos", "encabezados": "si", "tipo_precio": "todos"},
        )
    )

    assert publicaciones.values == [
        PUBLICACIONES_LEGACY_HEADERS,
        [
            "MLA1",
            "First listing",
            "sku-1",
            0,
            0,
            "fulfillment",
            "NA",
            "NA",
            "active",
            "NA",
            "NA",
            "NA",
        ],
    ]
    assert dashboard.values == [
        DASHBOARD_LEGACY_HEADERS + ["Precio Promo"],
        [
            "MLA1",
            "First listing",
            "sku-1",
            0,
            0,
            "fulfillment",
            "NA",
            "NA",
            "active",
            "NA",
            "NA",
            0,
            0,
            0,
            0,
            0,
            "Vendedor",
            "NA",
            "NA",
            "NA",
            "NA",
            "No",
            "NA",
        ],
    ]


@pytest.mark.asyncio
async def test_idstock_returns_seller_scoped_table_with_optional_headers() -> None:
    db = FakeDb()
    formula_rows = db["sheets_item_formula_rows"]
    formula_rows.documents = {
        "seller-1-sku-1-mla1": {
            "_id": "seller-1-sku-1-mla1",
            "seller_id": "seller-1",
            "sku": "sku-1",
            "normalized_sku": "SKU-1",
            "item_id": "MLA1",
            "current": {"available_quantity": 7},
        },
        "seller-1-sku-1-mla3": {
            "_id": "seller-1-sku-1-mla3",
            "seller_id": "seller-1",
            "sku": "sku-1",
            "normalized_sku": "SKU-1",
            "item_id": "MLA3",
            "current": {"available_quantity": 0},
        },
        "seller-1-sku-2-mla2": {
            "_id": "seller-1-sku-2-mla2",
            "seller_id": "seller-1",
            "sku": "sku-2",
            "normalized_sku": "SKU-2",
            "item_id": "MLA2",
            "current": {"available_quantity": 4},
        },
        "seller-2-sku-1-mla1": {
            "_id": "seller-2-sku-1-mla1",
            "seller_id": "seller-2",
            "sku": "sku-1",
            "normalized_sku": "SKU-1",
            "item_id": "MLB1",
            "current": {"available_quantity": 99},
        },
    }
    dispatcher = _core_dispatcher(db)

    without_headers = await dispatcher.execute(
        _context(
            "ZELERDATA_IDSTOCK",
            {"skus": [["sku-1"], ["missing"], ["sku-2"]], "encabezados": ""},
        )
    )
    with_headers = await dispatcher.execute(
        _context("ZELERDATA_IDSTOCK", {"skus": "sku-1", "encabezados": "si"})
    )

    assert without_headers.values == [["MLA1", 7], ["MLA3", 0], ["MLA2", 4]]
    assert without_headers.meta == {"partial_misses": 1}
    assert with_headers.values == [
        ["ID Publicación", "Stock"],
        ["MLA1", 7],
        ["MLA3", 0],
    ]
    assert with_headers.meta == {"partial_misses": 0}
    assert formula_rows.last_find_filter == {
        "seller_id": "seller-1",
        "normalized_sku": {"$in": ["SKU-1"]},
    }


@pytest.mark.asyncio
async def test_codigo_ml_to_sku_id_returns_seller_scoped_table_with_optional_headers() -> None:
    db = FakeDb()
    formula_rows = db["sheets_item_formula_rows"]
    formula_rows.documents = {
        "seller-1-sku-1-mla1": {
            "_id": "seller-1-sku-1-mla1",
            "seller_id": "seller-1",
            "sku": "sku-1",
            "normalized_sku": "SKU-1",
            "item_id": "MLA1",
            "inventory_id": "INV-1",
            "current": {},
        },
        "seller-1-sku-2-mla2": {
            "_id": "seller-1-sku-2-mla2",
            "seller_id": "seller-1",
            "sku": "sku-2",
            "normalized_sku": "SKU-2",
            "item_id": "MLA2",
            "inventory_id": "INV-2",
            "current": {},
        },
        "seller-2-sku-1-mla1": {
            "_id": "seller-2-sku-1-mla1",
            "seller_id": "seller-2",
            "sku": "sku-1",
            "normalized_sku": "SKU-1",
            "item_id": "MLB1",
            "inventory_id": "INV-1",
            "current": {},
        },
    }
    dispatcher = _core_dispatcher(db)

    without_headers = await dispatcher.execute(
        _context(
            "ZELERDATA_CODIGOML2SKUID",
            {"codigo_ml": [[" inv-1 "], ["missing"], ["INV-2"]], "encabezados": ""},
        )
    )
    with_headers = await dispatcher.execute(
        _context("ZELERDATA_CODIGOML2SKUID", {"codigo_ml": "INV-1", "encabezados": "sí"})
    )

    assert without_headers.values == [["MLA1", "sku-1"], ["MLA2", "sku-2"]]
    assert without_headers.meta == {"partial_misses": 1}
    assert with_headers.values == [
        ["ID Publicación", "SKU"],
        ["MLA1", "sku-1"],
    ]
    assert with_headers.meta == {"partial_misses": 0}
    assert formula_rows.last_find_filter == {
        "seller_id": "seller-1",
        "inventory_id": {"$in": ["INV-1"]},
    }


@pytest.mark.asyncio
async def test_publicaciones_returns_minimal_current_item_table_with_optional_headers() -> None:
    db = FakeDb()
    formula_rows = db["sheets_item_formula_rows"]
    formula_rows.documents = {
        "seller-1-sku-1-mla1": {
            "_id": "seller-1-sku-1-mla1",
            "seller_id": "seller-1",
            "sku": "sku-1",
            "normalized_sku": "SKU-1",
            "item_id": "MLA1",
            "inventory_id": "INV-1",
            "current": {
                "title": "First listing",
                "status": "active",
                "available_quantity": 7,
                "base_price": 123.45,
                "permalink": "https://meli.example/mla1",
            },
        },
        "seller-1-sku-2-mla2": {
            "_id": "seller-1-sku-2-mla2",
            "seller_id": "seller-1",
            "sku": "sku-2",
            "normalized_sku": "SKU-2",
            "item_id": "MLA2",
            "inventory_id": "INV-2",
            "current": {
                "title": "Second listing",
                "status": "paused",
                "available_quantity": 0,
                "base_price": 10,
                "permalink": "https://meli.example/mla2",
            },
        },
        "seller-2-sku-1-mla1": {
            "_id": "seller-2-sku-1-mla1",
            "seller_id": "seller-2",
            "sku": "sku-1",
            "normalized_sku": "SKU-1",
            "item_id": "MLB1",
            "current": {
                "title": "Wrong tenant",
                "status": "active",
                "available_quantity": 99,
                "base_price": 999,
                "permalink": "https://meli.example/wrong",
            },
        },
    }
    dispatcher = _core_dispatcher(db)

    with_headers = await dispatcher.execute(
        _context("ZELERDATA_PUBLICACIONES", {"skus": "todos", "encabezados": "si"})
    )
    without_headers = await dispatcher.execute(
        _context(
            "ZELERDATA_PUBLICACIONES",
            {"skus": [["sku-2"], ["missing"]], "encabezados": ""},
        )
    )

    assert with_headers.values == _formula_table_contract(
        [
            PUBLICACIONES_LEGACY_HEADERS,
            [
                "MLA1",
                "First listing",
                "sku-1",
                7,
                123.45,
                "",
                "https://meli.example/mla1",
                "",
                "active",
                "INV-1",
                "INV-1",
                "",
            ],
            [
                "MLA2",
                "Second listing",
                "sku-2",
                0,
                10,
                "",
                "https://meli.example/mla2",
                "",
                "paused",
                "INV-2",
                "INV-2",
                "",
            ],
        ]
    )
    assert with_headers.meta == {"partial_misses": 0, "columns": "legacy_publications"}
    assert without_headers.values == _formula_table_contract(
        [
            [
                "MLA2",
                "Second listing",
                "sku-2",
                0,
                10,
                "",
                "https://meli.example/mla2",
                "",
                "paused",
                "INV-2",
                "INV-2",
                "",
            ]
        ],
        header_rows=0,
    )
    assert without_headers.meta == {"partial_misses": 1, "columns": "legacy_publications"}
    assert formula_rows.last_find_filter == {
        "seller_id": "seller-1",
        "normalized_sku": {"$in": ["SKU-2", "MISSING"]},
    }


@pytest.mark.asyncio
async def test_publicaciones_and_dashboard_render_real_paused_days_only() -> None:
    now = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
    paused_since = datetime(2026, 5, 10, 8, 0, tzinfo=UTC)
    db = FakeDb()
    db["sheets_item_formula_rows"].documents = {
        "seller-1-sku-1-mla1": {
            "_id": "seller-1-sku-1-mla1",
            "seller_id": "seller-1",
            "sku": "sku-1",
            "normalized_sku": "SKU-1",
            "item_id": "MLA1",
            "inventory_id": "INV-1",
            "current": {
                "title": "Observed paused listing",
                "status": "paused",
                "available_quantity": 0,
                "base_price": 10,
                "paused_since": paused_since,
                "updated_at": datetime(2026, 5, 12, 8, 0, tzinfo=UTC),
            },
        },
        "seller-1-sku-2-mla2": {
            "_id": "seller-1-sku-2-mla2",
            "seller_id": "seller-1",
            "sku": "sku-2",
            "normalized_sku": "SKU-2",
            "item_id": "MLA2",
            "inventory_id": "INV-2",
            "current": {
                "title": "Snapshot-only paused listing",
                "status": "paused",
                "available_quantity": 0,
                "base_price": 20,
                "updated_at": datetime(2026, 4, 1, 8, 0, tzinfo=UTC),
            },
            "updated_at": datetime(2026, 4, 1, 8, 0, tzinfo=UTC),
        },
    }
    dispatcher = _core_dispatcher(db, now=now)

    publicaciones = await dispatcher.execute(
        _context("ZELERDATA_PUBLICACIONES", {"skus": "todos", "encabezados": "si"})
    )
    dashboard = await dispatcher.execute(
        _context("ZELERDATA_DASHBOARD", {"skus": "todos", "encabezados": "si"})
    )

    assert publicaciones.values == _formula_table_contract(
        [
            PUBLICACIONES_LEGACY_HEADERS,
            [
                "MLA1",
                "Observed paused listing",
                "sku-1",
                0,
                10,
                "",
                "",
                "",
                "paused",
                "INV-1",
                "INV-1",
                3,
            ],
            [
                "MLA2",
                "Snapshot-only paused listing",
                "sku-2",
                0,
                20,
                "",
                "",
                "",
                "paused",
                "INV-2",
                "INV-2",
                "NA",
            ],
        ]
    )
    dashboard_rows = dashboard.values[1:]
    assert [row[10] for row in dashboard_rows] == [3, "NA"]


@pytest.mark.asyncio
async def test_dashboard_returns_minimal_current_item_table_with_optional_headers() -> None:
    db = FakeDb()
    formula_rows = db["sheets_item_formula_rows"]
    formula_rows.documents = {
        "seller-1-sku-1-mla1": {
            "_id": "seller-1-sku-1-mla1",
            "seller_id": "seller-1",
            "sku": "sku-1",
            "normalized_sku": "SKU-1",
            "item_id": "MLA1",
            "inventory_id": "INV-1",
            "current": {
                "title": "First listing",
                "status": "active",
                "available_quantity": 7,
                "base_price": 123.45,
                "permalink": "https://meli.example/mla1",
                "category_id": "MLA-CELLPHONES",
                "thumbnail": "https://img.example/mla1.jpg",
            },
        },
        "seller-1-sku-2-mla2": {
            "_id": "seller-1-sku-2-mla2",
            "seller_id": "seller-1",
            "sku": "sku-2",
            "normalized_sku": "SKU-2",
            "item_id": "MLA2",
            "inventory_id": "INV-2",
            "current": {
                "title": "Second listing",
                "status": "paused",
                "available_quantity": 0,
                "base_price": 10,
                "permalink": "https://meli.example/mla2",
                "category_id": "MLA-ACCESSORIES",
                "thumbnail": None,
                "catalog_product_id": "MLA-CATALOG-2",
            },
        },
        "seller-2-sku-1-mla1": {
            "_id": "seller-2-sku-1-mla1",
            "seller_id": "seller-2",
            "sku": "sku-1",
            "normalized_sku": "SKU-1",
            "item_id": "MLB1",
            "current": {
                "title": "Wrong tenant",
                "status": "active",
                "available_quantity": 99,
                "base_price": 999,
                "permalink": "https://meli.example/wrong",
                "category_id": "WRONG-TENANT",
                "thumbnail": "https://img.example/wrong.jpg",
            },
        },
    }
    db["orders"].documents = {
        "recent": {
            "_id": "recent",
            "seller_id": "seller-1",
            "date_created": datetime(2026, 5, 12, 10, 0, tzinfo=UTC),
            "items": [{"sku": "sku-1", "item_id": "MLA1", "quantity": 2}],
        },
        "older": {
            "_id": "older",
            "seller_id": "seller-1",
            "date_created": datetime(2026, 5, 1, 10, 0, tzinfo=UTC),
            "items": [{"sku": "sku-1", "item_id": "MLA1", "quantity": 3}],
        },
        "outside": {
            "_id": "outside",
            "seller_id": "seller-1",
            "date_created": datetime(2026, 2, 1, 10, 0, tzinfo=UTC),
            "items": [{"sku": "sku-1", "item_id": "MLA1", "quantity": 99}],
        },
    }
    dispatcher = _core_dispatcher(db)

    with_headers = await dispatcher.execute(
        _context(
            "ZELERDATA_DASHBOARD",
            {"skus": "todos", "encabezados": "verdadero", "tipo_precio": "todos"},
        )
    )
    without_headers = await dispatcher.execute(
        _context("ZELERDATA_DASHBOARD", {"skus": [["sku-2"], ["missing"]]})
    )

    assert with_headers.values == _formula_table_contract(
        [
            DASHBOARD_LEGACY_HEADERS + ["Precio Promo"],
            [
                "MLA1",
                "First listing",
                "sku-1",
                7,
                123.45,
                "",
                "https://meli.example/mla1",
                "",
                "active",
                "INV-1",
                "",
                2,
                5,
                5,
                5,
                5,
                "",
                "",
                "",
                "",
                "",
                "No",
                "",
            ],
            [
                "MLA2",
                "Second listing",
                "sku-2",
                0,
                10,
                "",
                "https://meli.example/mla2",
                "",
                "paused",
                "INV-2",
                "",
                0,
                0,
                0,
                0,
                0,
                "",
                "",
                "",
                "",
                "",
                "Sí",
                "",
            ],
        ]
    )
    assert with_headers.meta == {"partial_misses": 0, "columns": "legacy_dashboard"}
    assert without_headers.values == _formula_table_contract(
        [
            [
                "MLA2",
                "Second listing",
                "sku-2",
                0,
                10,
                "",
                "https://meli.example/mla2",
                "",
                "paused",
                "INV-2",
                "",
                0,
                0,
                0,
                0,
                0,
                "",
                "",
                "",
                "",
                "",
                "Sí",
            ]
        ],
        header_rows=0,
    )
    assert without_headers.meta == {"partial_misses": 1, "columns": "legacy_dashboard"}
    assert formula_rows.last_find_filter == {
        "seller_id": "seller-1",
        "normalized_sku": {"$in": ["SKU-2", "MISSING"]},
    }


@pytest.mark.asyncio
async def test_dashboard_sales_windows_use_sku_index_when_order_item_has_only_item_id() -> None:
    db = FakeDb()
    db["sheets_item_formula_rows"].documents = {
        "seller-1-sku-1-mla1": {
            "_id": "seller-1-sku-1-mla1",
            "seller_id": "seller-1",
            "sku": "sku-1",
            "normalized_sku": "SKU-1",
            "item_id": "MLA1",
            "current": {
                "title": "Resolved listing",
                "status": "active",
                "available_quantity": 7,
            },
        }
    }
    db["sheets_item_sku_index"].documents = {
        "seller-1:SKU-1:MLA1": {
            "_id": "seller-1:SKU-1:MLA1",
            "seller_id": "seller-1",
            "sku": "sku-1",
            "normalized_sku": "SKU-1",
            "item_id": "MLA1",
        }
    }
    db["orders"].documents = {
        "recent": {
            "_id": "recent",
            "seller_id": "seller-1",
            "date_created": datetime(2026, 5, 12, 10, 0, tzinfo=UTC),
            "items": [{"item_id": "MLA1", "quantity": 2}],
        }
    }
    dispatcher = _core_dispatcher(db)

    result = await dispatcher.execute(
        _context("ZELERDATA_DASHBOARD", {"skus": "todos", "encabezados": "si"})
    )

    assert result.values == _formula_table_contract(
        [
            DASHBOARD_LEGACY_HEADERS,
            [
                "MLA1",
                "Resolved listing",
                "sku-1",
                7,
                "",
                "",
                "",
                "",
                "active",
                "",
                "",
                2,
                2,
                2,
                2,
                2,
                "",
                "",
                "",
                "",
                "",
                "No",
            ],
        ]
    )
    assert db["sheets_item_sku_index"].last_find_filter == {
        "seller_id": "seller-1",
        "item_id": {"$in": ["MLA1"]},
    }


@pytest.mark.asyncio
async def test_dashboard_sales_windows_resolve_item_variations_from_seller_sku_index() -> None:
    db = FakeDb()
    db["sheets_item_formula_rows"].documents = {
        "seller-1-sku-blue-mla1": {
            "_id": "seller-1-sku-blue-mla1",
            "seller_id": "seller-1",
            "sku": "sku-blue",
            "normalized_sku": "SKU-BLUE",
            "item_id": "MLA1",
            "current": {"title": "Blue variation", "status": "active", "available_quantity": 6},
        },
        "seller-1-sku-red-mla1": {
            "_id": "seller-1-sku-red-mla1",
            "seller_id": "seller-1",
            "sku": "sku-red",
            "normalized_sku": "SKU-RED",
            "item_id": "MLA1",
            "current": {"title": "Red variation", "status": "active", "available_quantity": 4},
        },
    }
    db["sheets_item_sku_index"].documents = {
        "seller-1:SKU-BLUE:MLA1:102": {
            "_id": "seller-1:SKU-BLUE:MLA1:102",
            "seller_id": "seller-1",
            "sku": "sku-blue",
            "normalized_sku": "SKU-BLUE",
            "item_id": "MLA1",
            "variation_id": "102",
        },
        "seller-1:SKU-RED:MLA1:101": {
            "_id": "seller-1:SKU-RED:MLA1:101",
            "seller_id": "seller-1",
            "sku": "sku-red",
            "normalized_sku": "SKU-RED",
            "item_id": "MLA1",
            "variation_id": "101",
        },
        "seller-2:SKU-BLUE:MLA1:102": {
            "_id": "seller-2:SKU-BLUE:MLA1:102",
            "seller_id": "seller-2",
            "sku": "wrong-tenant",
            "normalized_sku": "WRONG-TENANT",
            "item_id": "MLA1",
            "variation_id": "102",
        },
    }
    db["orders"].documents = {
        "recent": {
            "_id": "recent",
            "seller_id": "seller-1",
            "date_created": datetime(2026, 5, 12, 10, 0, tzinfo=UTC),
            "items": [{"item_id": "MLA1", "variation_id": 102, "quantity": 3}],
        }
    }
    dispatcher = _core_dispatcher(db)

    result = await dispatcher.execute(
        _context("ZELERDATA_DASHBOARD", {"skus": "todos", "encabezados": "si"})
    )

    assert result.values == _formula_table_contract(
        [
            DASHBOARD_LEGACY_HEADERS,
            [
                "MLA1",
                "Blue variation",
                "sku-blue",
                6,
                "",
                "",
                "",
                "",
                "active",
                "",
                "",
                3,
                3,
                3,
                3,
                3,
                "",
                "",
                "",
                "",
                "",
                "No",
            ],
            [
                "MLA1",
                "Red variation",
                "sku-red",
                4,
                "",
                "",
                "",
                "",
                "active",
                "",
                "",
                0,
                0,
                0,
                0,
                0,
                "",
                "",
                "",
                "",
                "",
                "No",
            ],
        ]
    )
    assert db["sheets_item_sku_index"].last_find_filter == {
        "seller_id": "seller-1",
        "item_id": {"$in": ["MLA1"]},
    }


@pytest.mark.asyncio
async def test_dashboard_sales_windows_do_not_guess_item_level_sku_for_missing_variation() -> None:
    db = FakeDb()
    db["sheets_item_formula_rows"].documents = {
        "seller-1-sku-base-mla1": {
            "_id": "seller-1-sku-base-mla1",
            "seller_id": "seller-1",
            "sku": "sku-base",
            "normalized_sku": "SKU-BASE",
            "item_id": "MLA1",
            "current": {
                "title": "Item-level listing",
                "status": "active",
                "available_quantity": 9,
            },
        }
    }
    db["sheets_item_sku_index"].documents = {
        "seller-1:SKU-BASE:MLA1": {
            "_id": "seller-1:SKU-BASE:MLA1",
            "seller_id": "seller-1",
            "sku": "sku-base",
            "normalized_sku": "SKU-BASE",
            "item_id": "MLA1",
            "variation_id": None,
        },
        "seller-1:SKU-BLUE:MLA1:102": {
            "_id": "seller-1:SKU-BLUE:MLA1:102",
            "seller_id": "seller-1",
            "sku": "sku-blue",
            "normalized_sku": "SKU-BLUE",
            "item_id": "MLA1",
            "variation_id": "102",
        },
    }
    db["orders"].documents = {
        "recent": {
            "_id": "recent",
            "seller_id": "seller-1",
            "date_created": datetime(2026, 5, 12, 10, 0, tzinfo=UTC),
            "items": [{"item_id": "MLA1", "variation_id": 103, "quantity": 4}],
        }
    }
    dispatcher = _core_dispatcher(db)

    result = await dispatcher.execute(
        _context("ZELERDATA_DASHBOARD", {"skus": "todos", "encabezados": "si"})
    )

    assert result.values == _formula_table_contract(
        [
            DASHBOARD_LEGACY_HEADERS,
            [
                "MLA1",
                "Item-level listing",
                "sku-base",
                9,
                "",
                "",
                "",
                "",
                "active",
                "",
                "",
                0,
                0,
                0,
                0,
                0,
                "",
                "",
                "",
                "",
                "",
                "No",
            ],
        ]
    )
    assert db["sheets_item_sku_index"].last_find_filter == {
        "seller_id": "seller-1",
        "item_id": {"$in": ["MLA1"]},
    }


@pytest.mark.asyncio
async def test_dashboard_sales_windows_fall_back_to_unique_item_level_variation_sku() -> None:
    db = FakeDb()
    db["sheets_item_formula_rows"].documents = {
        "seller-1-sku-1-mla1": {
            "_id": "seller-1-sku-1-mla1",
            "seller_id": "seller-1",
            "sku": "sku-1",
            "normalized_sku": "SKU-1",
            "item_id": "MLA1",
            "current": {
                "title": "Item-level listing",
                "status": "active",
                "available_quantity": 9,
            },
        }
    }
    db["sheets_item_sku_index"].documents = {
        "seller-1:SKU-1:MLA1": {
            "_id": "seller-1:SKU-1:MLA1",
            "seller_id": "seller-1",
            "sku": "sku-1",
            "normalized_sku": "SKU-1",
            "item_id": "MLA1",
        },
        "seller-2:SKU-OTHER:MLA1:102": {
            "_id": "seller-2:SKU-OTHER:MLA1:102",
            "seller_id": "seller-2",
            "sku": "wrong-tenant",
            "normalized_sku": "SKU-OTHER",
            "item_id": "MLA1",
            "variation_id": "102",
        },
    }
    db["orders"].documents = {
        "recent": {
            "_id": "recent",
            "seller_id": "seller-1",
            "date_created": datetime(2026, 5, 12, 10, 0, tzinfo=UTC),
            "items": [{"item_id": "MLA1", "variation_id": 102, "quantity": 4}],
        }
    }
    dispatcher = _core_dispatcher(db)

    result = await dispatcher.execute(
        _context("ZELERDATA_DASHBOARD", {"skus": "todos", "encabezados": "si"})
    )

    assert result.values == _formula_table_contract(
        [
            DASHBOARD_LEGACY_HEADERS,
            [
                "MLA1",
                "Item-level listing",
                "sku-1",
                9,
                "",
                "",
                "",
                "",
                "active",
                "",
                "",
                4,
                4,
                4,
                4,
                4,
                "",
                "",
                "",
                "",
                "",
                "No",
            ],
        ]
    )
    assert db["sheets_item_sku_index"].last_find_filter == {
        "seller_id": "seller-1",
        "item_id": {"$in": ["MLA1"]},
    }


@pytest.mark.asyncio
async def test_dashboard_sin_catalogo_excludes_rows_with_catalog_product_indicators() -> None:
    db = FakeDb()
    formula_rows = db["sheets_item_formula_rows"]
    formula_rows.documents = {
        "seller-1-sku-1-mla1": {
            "_id": "seller-1-sku-1-mla1",
            "seller_id": "seller-1",
            "sku": "sku-1",
            "normalized_sku": "SKU-1",
            "item_id": "MLA1",
            "current": {
                "title": "Classic listing",
                "status": "active",
                "available_quantity": 4,
                "base_price": 20,
                "permalink": "https://meli.example/mla1",
                "category_id": "MLA-CELLPHONES",
                "thumbnail": "https://img.example/mla1.jpg",
                "catalog_product_id": None,
            },
        },
        "seller-1-sku-2-mla2": {
            "_id": "seller-1-sku-2-mla2",
            "seller_id": "seller-1",
            "sku": "sku-2",
            "normalized_sku": "SKU-2",
            "item_id": "MLA2",
            "current": {
                "title": "Catalog listing",
                "status": "active",
                "available_quantity": 8,
                "base_price": 30,
                "permalink": "https://meli.example/mla2",
                "category_id": "MLA-ACCESSORIES",
                "thumbnail": "https://img.example/mla2.jpg",
                "catalog_product_id": "MLA-CATALOG-1",
            },
        },
        "seller-1-sku-3-mla3": {
            "_id": "seller-1-sku-3-mla3",
            "seller_id": "seller-1",
            "sku": "sku-3",
            "normalized_sku": "SKU-3",
            "item_id": "MLA3",
            "current": {
                "title": "Blank catalog indicator listing",
                "status": "paused",
                "available_quantity": 0,
                "base_price": 5,
                "permalink": "https://meli.example/mla3",
                "category_id": "MLA-OTHER",
                "thumbnail": "https://img.example/mla3.jpg",
                "catalog_product_id": "",
            },
        },
    }
    dispatcher = _core_dispatcher(db)

    result = await dispatcher.execute(
        _context(
            "ZELERDATA_DASHBOARDSINCATALOGO",
            {"skus": "todos", "encabezados": "sí"},
        )
    )

    assert result.values == _formula_table_contract(
        [
            DASHBOARD_LEGACY_HEADERS,
            [
                "MLA1",
                "Classic listing",
                "sku-1",
                4,
                20,
                "",
                "https://meli.example/mla1",
                "",
                "active",
                "",
                "",
                0,
                0,
                0,
                0,
                0,
                "",
                "",
                "",
                "",
                "",
                "No",
            ],
            [
                "MLA3",
                "Blank catalog indicator listing",
                "sku-3",
                0,
                5,
                "",
                "https://meli.example/mla3",
                "",
                "paused",
                "",
                "",
                0,
                0,
                0,
                0,
                0,
                "",
                "",
                "",
                "",
                "",
                "No",
            ],
        ]
    )
    assert result.meta == {
        "partial_misses": 0,
        "columns": "legacy_dashboard",
        "excluded_catalog_rows": 1,
    }


@pytest.mark.asyncio
async def test_dashboard_formulas_use_seller_shipping_cost_scalar_or_zero_only() -> None:
    db = FakeDb()
    formula_rows = db["sheets_item_formula_rows"]
    formula_rows.documents = {
        "seller-1-sku-1-mla1": {
            "_id": "seller-1-sku-1-mla1",
            "seller_id": "seller-1",
            "sku": "sku-1",
            "normalized_sku": "SKU-1",
            "item_id": "MLA1",
            "current": {
                "title": "Free shipping listing",
                "status": "active",
                "available_quantity": 4,
                "base_price": 20,
                "seller_shipping_cost": 83.25,
            },
        },
        "seller-1-sku-2-mla2": {
            "_id": "seller-1-sku-2-mla2",
            "seller_id": "seller-1",
            "sku": "sku-2",
            "normalized_sku": "SKU-2",
            "item_id": "MLA2",
            "current": {
                "title": "Non-free shipping listing",
                "status": "active",
                "available_quantity": 8,
                "base_price": 30,
                "seller_shipping_cost": 0,
            },
        },
        "seller-1-sku-3-mla3": {
            "_id": "seller-1-sku-3-mla3",
            "seller_id": "seller-1",
            "sku": "sku-3",
            "normalized_sku": "SKU-3",
            "item_id": "MLA3",
            "current": {
                "title": "Unvalidated shipping listing",
                "status": "paused",
                "available_quantity": 0,
                "base_price": 5,
                "seller_shipping_cost": None,
            },
        },
    }
    dispatcher = _core_dispatcher(db)

    dashboard = await dispatcher.execute(
        _context("ZELERDATA_DASHBOARD", {"skus": "todos", "encabezados": "si"})
    )
    sin_catalogo = await dispatcher.execute(
        _context("ZELERDATA_DASHBOARDSINCATALOGO", {"skus": "todos", "encabezados": "si"})
    )
    publicaciones = await dispatcher.execute(
        _context("ZELERDATA_PUBLICACIONES", {"skus": [["sku-1"]], "encabezados": "si"})
    )

    dashboard_costs = [row[17] for row in dashboard.values[1:]]
    sin_catalogo_costs = [row[17] for row in sin_catalogo.values[1:]]
    assert dashboard_costs == [83.25, 0, "NA"]
    assert sin_catalogo_costs == [83.25, 0, "NA"]
    assert publicaciones.values == _formula_table_contract(
        [
            PUBLICACIONES_LEGACY_HEADERS,
            ["MLA1", "Free shipping listing", "sku-1", 4, 20, "", "", "", "active", "", "", "NA"],
        ]
    )


@pytest.mark.asyncio
async def test_categorias_returns_category_by_item_id_with_blanks_for_misses() -> None:
    db = FakeDb()
    formula_rows = db["sheets_item_formula_rows"]
    formula_rows.documents = {
        "seller-1-sku-1-mla1": {
            "_id": "seller-1-sku-1-mla1",
            "seller_id": "seller-1",
            "normalized_sku": "SKU-1",
            "item_id": "MLA1",
            "current": {"category_id": "MLA-CELLPHONES"},
        },
        "seller-1-sku-2-mla2": {
            "_id": "seller-1-sku-2-mla2",
            "seller_id": "seller-1",
            "normalized_sku": "SKU-2",
            "item_id": "MLA2",
            "current": {"category_id": "MLA-ACCESSORIES"},
        },
        "seller-2-sku-1-mla1": {
            "_id": "seller-2-sku-1-mla1",
            "seller_id": "seller-2",
            "normalized_sku": "SKU-1",
            "item_id": "MLA1",
            "current": {"category_id": "WRONG-TENANT"},
        },
    }
    dispatcher = _core_dispatcher(db)

    scalar_category = await dispatcher.execute(
        _context("ZELERDATA_CATEGORIAS", {"id_publicaciones": "MLA1"})
    )
    range_category = await dispatcher.execute(
        _context("ZELERDATA_CATEGORIAS", {"id_publicaciones": [["MLA1"], ["MLA-X"], ["MLA2"]]})
    )

    assert scalar_category.values == [["MLA-CELLPHONES"]]
    assert scalar_category.meta == {"partial_misses": 0}
    assert range_category.values == [["MLA-CELLPHONES"], [""], ["MLA-ACCESSORIES"]]
    assert range_category.meta == {"partial_misses": 1}
    assert formula_rows.last_find_filter == {
        "seller_id": "seller-1",
        "item_id": {"$in": ["MLA1", "MLA-X", "MLA2"]},
    }


@pytest.mark.asyncio
async def test_paused_days_formula_ignores_snapshot_timestamps() -> None:
    now = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
    paused_since = datetime(2026, 5, 10, 8, 0, tzinfo=UTC)
    db = FakeDb()
    formula_rows = db["sheets_item_formula_rows"]
    formula_rows.documents = {
        "paused-with-history": {
            "_id": "paused-with-history",
            "seller_id": "seller-1",
            "normalized_sku": "SKU-1",
            "item_id": "MLA1",
            "current": {
                "status": "paused",
                "paused_since": paused_since,
                "updated_at": datetime(2026, 5, 12, 8, 0, tzinfo=UTC),
            },
        },
        "paused-snapshot-only": {
            "_id": "paused-snapshot-only",
            "seller_id": "seller-1",
            "normalized_sku": "SKU-2",
            "item_id": "MLA2",
            "current": {
                "status": "paused",
                "updated_at": datetime(2026, 4, 1, 8, 0, tzinfo=UTC),
            },
            "updated_at": datetime(2026, 4, 1, 8, 0, tzinfo=UTC),
            "last_updated": datetime(2026, 4, 1, 8, 0, tzinfo=UTC),
        },
        "active-with-paused-history": {
            "_id": "active-with-paused-history",
            "seller_id": "seller-1",
            "normalized_sku": "SKU-3",
            "item_id": "MLA3",
            "current": {"status": "active", "paused_since": paused_since},
        },
    }
    dispatcher = _core_dispatcher(db, now=now)

    result = await dispatcher.execute(
        _context("ZELERDATA_PAUSADAS", {"id_publicaciones": ["MLA1", "MLA2", "MLA3", "MLA-X"]})
    )

    assert result.values == [[3], ["NA"], ["NA"], ["NA"]]
    assert result.meta == {"partial_misses": 3}
    assert formula_rows.last_find_filter == {
        "seller_id": "seller-1",
        "item_id": {"$in": ["MLA1", "MLA2", "MLA3", "MLA-X"]},
    }


@pytest.mark.asyncio
async def test_imagenes_returns_thumbnail_urls_for_item_sku_pairs_and_todos() -> None:
    db = FakeDb()
    formula_rows = db["sheets_item_formula_rows"]
    formula_rows.documents = {
        "seller-1-sku-1-mla1": {
            "_id": "seller-1-sku-1-mla1",
            "seller_id": "seller-1",
            "sku": "sku-1",
            "normalized_sku": "SKU-1",
            "item_id": "MLA1",
            "current": {"thumbnail": "https://img.example/mla1.jpg"},
        },
        "seller-1-sku-2-mla2": {
            "_id": "seller-1-sku-2-mla2",
            "seller_id": "seller-1",
            "sku": "sku-2",
            "normalized_sku": "SKU-2",
            "item_id": "MLA2",
            "current": {"thumbnail": "https://img.example/mla2.jpg"},
        },
        "seller-1-sku-3-mla3": {
            "_id": "seller-1-sku-3-mla3",
            "seller_id": "seller-1",
            "sku": "sku-3",
            "normalized_sku": "SKU-3",
            "item_id": "MLA3",
            "current": {"thumbnail": None},
        },
        "seller-2-sku-1-mla1": {
            "_id": "seller-2-sku-1-mla1",
            "seller_id": "seller-2",
            "sku": "sku-1",
            "normalized_sku": "SKU-1",
            "item_id": "MLA1",
            "current": {"thumbnail": "https://img.example/wrong.jpg"},
        },
    }
    dispatcher = _core_dispatcher(db)

    scalar_image = await dispatcher.execute(
        _context("ZELERDATA_IMAGENES", {"skus": "sku-1", "id_publicaciones": "MLA1"})
    )
    range_images = await dispatcher.execute(
        _context(
            "ZELERDATA_IMAGENES",
            {
                "skus": [["sku-1"], ["sku-2"], ["missing"]],
                "id_publicaciones": ["MLA1", "MLA2", "MLA-X"],
                "imagen": "principal",
            },
        )
    )
    all_images = await dispatcher.execute(
        _context("ZELERDATA_IMAGENES", {"skus": "todos", "id_publicaciones": "todos"})
    )

    assert scalar_image.values == [["https://img.example/mla1.jpg"]]
    assert scalar_image.meta == {
        "partial_misses": 0,
        "columns": "thumbnail_url",
        "image_variant": "principal",
    }
    assert range_images.values == [
        ["https://img.example/mla1.jpg"],
        ["https://img.example/mla2.jpg"],
        [""],
    ]
    assert range_images.meta == {
        "partial_misses": 1,
        "columns": "thumbnail_url",
        "image_variant": "principal",
    }
    assert all_images.values == [
        ["https://img.example/mla1.jpg"],
        ["https://img.example/mla2.jpg"],
        [""],
    ]
    assert all_images.meta == {
        "partial_misses": 0,
        "columns": "thumbnail_url",
        "image_variant": "principal",
    }
    assert formula_rows.last_find_filter == {"seller_id": "seller-1"}


@pytest.mark.asyncio
async def test_formula_api_uses_core_handlers_and_keeps_other_formulas_data_unavailable() -> None:
    now = datetime(2026, 5, 13, 17, 0, tzinfo=UTC)
    app, db, token = await _app_with_token(now=now)
    db["sheets_item_formula_rows"].documents = {
        "seller-1-sku-1-mla1": {
            "_id": "seller-1-sku-1-mla1",
            "seller_id": "seller-1",
            "normalized_sku": "SKU-1",
            "item_id": "MLA1",
            "current": {"available_quantity": 9, "base_price": 200},
        }
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        stock = await client.post(
            "/sheets/formulas:execute",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "formula": "ZELERDATA_STOCK",
                "cuenta": "HOPEMOB",
                "args": {"skus": "sku-1", "id_publicaciones": "MLA1"},
            },
        )
        title = await client.post(
            "/sheets/formulas:execute",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "formula": "ZELERDATA_TITULO",
                "cuenta": "HOPEMOB",
                "args": {"id_publicaciones": "MLA1"},
            },
        )
        pausadas = await client.post(
            "/sheets/formulas:execute",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "formula": "ZELERDATA_PAUSADAS",
                "cuenta": "HOPEMOB",
                "args": {"id_publicaciones": "MLA1"},
            },
        )

    assert stock.status_code == 200
    assert stock.json() == {"ok": True, "values": [[9]], "meta": {"partial_misses": 0}}
    assert title.status_code == 200
    assert title.json() == {"ok": True, "values": [[""]], "meta": {"partial_misses": 1}}
    assert pausadas.status_code == 200
    assert pausadas.json() == {"ok": True, "values": [["NA"]], "meta": {"partial_misses": 1}}
    assert db["sheets_item_formula_rows"].last_find_filter == {
        "seller_id": "seller-1",
        "item_id": {"$in": ["MLA1"]},
    }


def _core_dispatcher(db: FakeDb, *, now: datetime | None = None) -> FormulaDispatcher:
    return FormulaDispatcher(
        build_core_formula_handlers(
            FormulaReadModelRepository(db=db),
            now_fn=lambda: now or datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
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
