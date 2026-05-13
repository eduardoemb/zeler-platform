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
        "message": "SHEETSELLER_PAUSADAS data is not available yet",
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
