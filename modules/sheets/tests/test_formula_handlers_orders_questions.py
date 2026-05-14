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
        not_ready = await client.post(
            "/sheets/formulas:execute",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "formula": "SHEETSELLER_ORDENES",
                "cuenta": "HOPEMOB",
                "args": {"fecha_inicial": "2026-05-10", "fecha_final": "2026-05-10"},
            },
        )

    assert ventas.status_code == 200
    assert ventas.json() == {
        "ok": True,
        "values": [[100]],
        "meta": {"orders_count": 1, "status_filter": "todos"},
    }
    assert not_ready.status_code == 200
    assert not_ready.json()["error"] == {
        "code": "DATA_UNAVAILABLE",
        "message": "SHEETSELLER_ORDENES data is not available yet",
        "retryable": False,
    }


def _order_question_dispatcher(db: FakeDb) -> FormulaDispatcher:
    return FormulaDispatcher(
        build_order_question_formula_handlers(FormulaReadModelRepository(db=db))
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
    date_created: datetime,
    total_amount: int | float,
    items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "_id": order_id,
        "seller_id": seller_id,
        "buyer_id": "buyer-1",
        "status": status,
        "date_created": date_created,
        "total_amount": total_amount,
        "items": items or [],
        "schema_version": 1,
    }


def _question_doc(
    question_id: str,
    *,
    seller_id: str,
    status: str,
    date_created: datetime,
    answer: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "_id": question_id,
        "seller_id": seller_id,
        "item_id": "MLA1",
        "text": "Question?",
        "status": status,
        "from_user_id": "buyer-1",
        "date_created": date_created,
        "answer": answer,
        "schema_version": 1,
    }


def _sort_value(value: Any) -> Any:
    if value is None:
        return ""
    return value
