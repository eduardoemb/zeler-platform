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
        value = doc.get(key)
        if isinstance(expected, dict) and "$in" in expected:
            if value not in expected["$in"]:
                return False
        elif value != expected:
            return False
    return True


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
        _context("SHEETSELLER_SKU", {"skus": [[" sku-1 ", "SKU-2"], ["SKU-1", "missing"]]})
    )
    id_result = await dispatcher.execute(
        _context("SHEETSELLER_ID", {"skus": [[" sku-1 ", "SKU-2"], ["SKU-1", "missing"]]})
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
        _context("SHEETSELLER_STOCK", {"skus": " sku-1 ", "id_publicaciones": "MLA1"})
    )
    range_stock = await dispatcher.execute(
        _context(
            "SHEETSELLER_STOCK",
            {
                "skus": [["sku-1"], ["sku-2"], ["missing"]],
                "id_publicaciones": ["MLA1", "MLA2", "MLA-X"],
            },
        )
    )
    range_precio = await dispatcher.execute(
        _context(
            "SHEETSELLER_PRECIO",
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
        _context("SHEETSELLER_TITULO", {"id_publicaciones": "MLA1"})
    )
    range_status = await dispatcher.execute(
        _context("SHEETSELLER_STATUS", {"id_publicaciones": [["MLA1"], ["MLA2"], ["MLA-X"]]})
    )
    range_days = await dispatcher.execute(
        _context("SHEETSELLER_DIASPUBLICADA", {"id_publicaciones": ["MLA1", "MLA2", "MLA-X"]})
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
        _context("SHEETSELLER_URL", {"skus": "sku-1", "id_publicaciones": "MLA1"})
    )
    range_codigo = await dispatcher.execute(
        _context(
            "SHEETSELLER_CODIGOML",
            {
                "skus": [["sku-1"], ["sku-2"], ["missing"]],
                "id_publicaciones": ["MLA1", "MLA2", "MLA-X"],
            },
        )
    )

    assert scalar_url.values == [["https://meli.example/mla1"]]
    assert scalar_url.meta == {"partial_misses": 0}
    assert range_codigo.values == [["INV-1"], ["INV-2"], [""]]
    assert range_codigo.meta == {"partial_misses": 1}
    assert formula_rows.last_find_filter == {
        "seller_id": "seller-1",
        "normalized_sku": {"$in": ["SKU-1", "SKU-2", "MISSING"]},
        "item_id": {"$in": ["MLA1", "MLA2", "MLA-X"]},
    }


@pytest.mark.asyncio
async def test_current_item_formula_handlers_return_blanks_when_enriched_source_fields_are_absent(
) -> None:
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
        _context("SHEETSELLER_URL", {"skus": "sku-1", "id_publicaciones": "MLA1"})
    )
    imagen = await dispatcher.execute(
        _context("SHEETSELLER_IMAGENES", {"skus": "sku-1", "id_publicaciones": "MLA1"})
    )
    codigo = await dispatcher.execute(
        _context("SHEETSELLER_CODIGOML", {"skus": "sku-1", "id_publicaciones": "MLA1"})
    )

    assert url.values == [[""]]
    assert url.meta == {"partial_misses": 1}
    assert imagen.values == [[""]]
    assert imagen.meta == {
        "partial_misses": 1,
        "columns": "thumbnail_url",
        "image_variant": "principal",
    }
    assert codigo.values == [[""]]
    assert codigo.meta == {"partial_misses": 1}


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
            "SHEETSELLER_IDSTOCK",
            {"skus": [["sku-1"], ["missing"], ["sku-2"]], "encabezados": ""},
        )
    )
    with_headers = await dispatcher.execute(
        _context("SHEETSELLER_IDSTOCK", {"skus": "sku-1", "encabezados": "si"})
    )

    assert without_headers.values == [
        ["sku-1", "MLA1", 7],
        ["sku-1", "MLA3", 0],
        ["sku-2", "MLA2", 4],
    ]
    assert without_headers.meta == {"partial_misses": 1}
    assert with_headers.values == [
        ["SKU", "ID Publicación", "Stock"],
        ["sku-1", "MLA1", 7],
        ["sku-1", "MLA3", 0],
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
            "SHEETSELLER_CODIGOML2SKUID",
            {"codigo_ml": [[" inv-1 "], ["missing"], ["INV-2"]], "encabezados": ""},
        )
    )
    with_headers = await dispatcher.execute(
        _context("SHEETSELLER_CODIGOML2SKUID", {"codigo_ml": "INV-1", "encabezados": "sí"})
    )

    assert without_headers.values == [["INV-1", "MLA1", "sku-1"], ["INV-2", "MLA2", "sku-2"]]
    assert without_headers.meta == {"partial_misses": 1}
    assert with_headers.values == [
        ["Código ML", "ID Publicación", "SKU"],
        ["INV-1", "MLA1", "sku-1"],
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
        _context("SHEETSELLER_PUBLICACIONES", {"skus": "todos", "encabezados": "si"})
    )
    without_headers = await dispatcher.execute(
        _context(
            "SHEETSELLER_PUBLICACIONES",
            {"skus": [["sku-2"], ["missing"]], "encabezados": ""},
        )
    )

    assert with_headers.values == [
        ["SKU", "ID Publicación", "Título", "Status", "Stock", "Precio", "URL"],
        ["sku-1", "MLA1", "First listing", "active", 7, 123.45, "https://meli.example/mla1"],
        ["sku-2", "MLA2", "Second listing", "paused", 0, 10, "https://meli.example/mla2"],
    ]
    assert with_headers.meta == {"partial_misses": 0, "columns": "minimal_current_item"}
    assert without_headers.values == [
        ["sku-2", "MLA2", "Second listing", "paused", 0, 10, "https://meli.example/mla2"]
    ]
    assert without_headers.meta == {"partial_misses": 1, "columns": "minimal_current_item"}
    assert formula_rows.last_find_filter == {
        "seller_id": "seller-1",
        "normalized_sku": {"$in": ["SKU-2", "MISSING"]},
    }


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
            "current": {
                "title": "Second listing",
                "status": "paused",
                "available_quantity": 0,
                "base_price": 10,
                "permalink": "https://meli.example/mla2",
                "category_id": "MLA-ACCESSORIES",
                "thumbnail": None,
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
    dispatcher = _core_dispatcher(db)

    with_headers = await dispatcher.execute(
        _context("SHEETSELLER_DASHBOARD", {"skus": "todos", "encabezados": "verdadero"})
    )
    without_headers = await dispatcher.execute(
        _context("SHEETSELLER_DASHBOARD", {"skus": [["sku-2"], ["missing"]]})
    )

    assert with_headers.values == [
        [
            "SKU",
            "ID Publicación",
            "Título",
            "Status",
            "Stock",
            "Precio",
            "URL",
            "Categoría",
            "Imagen",
        ],
        [
            "sku-1",
            "MLA1",
            "First listing",
            "active",
            7,
            123.45,
            "https://meli.example/mla1",
            "MLA-CELLPHONES",
            "https://img.example/mla1.jpg",
        ],
        [
            "sku-2",
            "MLA2",
            "Second listing",
            "paused",
            0,
            10,
            "https://meli.example/mla2",
            "MLA-ACCESSORIES",
            "",
        ],
    ]
    assert with_headers.meta == {"partial_misses": 0, "columns": "dashboard_mvp_current_item"}
    assert without_headers.values == [
        [
            "sku-2",
            "MLA2",
            "Second listing",
            "paused",
            0,
            10,
            "https://meli.example/mla2",
            "MLA-ACCESSORIES",
            "",
        ]
    ]
    assert without_headers.meta == {"partial_misses": 1, "columns": "dashboard_mvp_current_item"}
    assert formula_rows.last_find_filter == {
        "seller_id": "seller-1",
        "normalized_sku": {"$in": ["SKU-2", "MISSING"]},
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
            "SHEETSELLER_DASHBOARDSINCATALOGO",
            {"skus": "todos", "encabezados": "sí"},
        )
    )

    assert result.values == [
        [
            "SKU",
            "ID Publicación",
            "Título",
            "Status",
            "Stock",
            "Precio",
            "URL",
            "Categoría",
            "Imagen",
        ],
        [
            "sku-1",
            "MLA1",
            "Classic listing",
            "active",
            4,
            20,
            "https://meli.example/mla1",
            "MLA-CELLPHONES",
            "https://img.example/mla1.jpg",
        ],
        [
            "sku-3",
            "MLA3",
            "Blank catalog indicator listing",
            "paused",
            0,
            5,
            "https://meli.example/mla3",
            "MLA-OTHER",
            "https://img.example/mla3.jpg",
        ],
    ]
    assert result.meta == {
        "partial_misses": 0,
        "columns": "dashboard_mvp_current_item",
        "excluded_catalog_rows": 1,
    }


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
        _context("SHEETSELLER_CATEGORIAS", {"id_publicaciones": "MLA1"})
    )
    range_category = await dispatcher.execute(
        _context("SHEETSELLER_CATEGORIAS", {"id_publicaciones": [["MLA1"], ["MLA-X"], ["MLA2"]]})
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
        _context("SHEETSELLER_IMAGENES", {"skus": "sku-1", "id_publicaciones": "MLA1"})
    )
    range_images = await dispatcher.execute(
        _context(
            "SHEETSELLER_IMAGENES",
            {
                "skus": [["sku-1"], ["sku-2"], ["missing"]],
                "id_publicaciones": ["MLA1", "MLA2", "MLA-X"],
                "imagen": "principal",
            },
        )
    )
    all_images = await dispatcher.execute(
        _context("SHEETSELLER_IMAGENES", {"skus": "todos", "id_publicaciones": "todos"})
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
                "formula": "SHEETSELLER_STOCK",
                "cuenta": "HOPEMOB",
                "args": {"skus": "sku-1", "id_publicaciones": "MLA1"},
            },
        )
        title = await client.post(
            "/sheets/formulas:execute",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "formula": "SHEETSELLER_TITULO",
                "cuenta": "HOPEMOB",
                "args": {"id_publicaciones": "MLA1"},
            },
        )
        not_ready = await client.post(
            "/sheets/formulas:execute",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "formula": "SHEETSELLER_PAUSADAS",
                "cuenta": "HOPEMOB",
                "args": {"id_publicaciones": "MLA1"},
            },
        )

    assert stock.status_code == 200
    assert stock.json() == {"ok": True, "values": [[9]], "meta": {"partial_misses": 0}}
    assert title.status_code == 200
    assert title.json() == {"ok": True, "values": [[""]], "meta": {"partial_misses": 1}}
    assert not_ready.status_code == 200
    assert not_ready.json()["error"] == {
        "code": "DATA_UNAVAILABLE",
        "message": (
            "SHEETSELLER_PAUSADAS data is not available yet: "
            "Historical paused-period read model is not available in zeler-platform yet."
        ),
        "retryable": False,
    }
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
