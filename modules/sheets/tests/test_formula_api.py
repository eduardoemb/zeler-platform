# ruff: noqa: S105,S106

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from bson.decimal128 import Decimal128
from fastapi import FastAPI

from zeler_sheets.extension_tokens import ExtensionTokenService, SellerScope
from zeler_sheets.formulas.dispatcher import FormulaExecutionResult


class FakeUpdateResult:
    modified_count = 1


class FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs

    def sort(self, *_args: Any) -> FakeCursor:
        return self

    async def to_list(self, length: int) -> list[dict[str, Any]]:
        return [dict(doc) for doc in self._docs[:length]]


class FakeCollection:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}
        self.find_filters: list[dict[str, Any]] = []

    async def insert_one(self, doc: dict[str, Any]) -> None:
        self.documents[str(doc["_id"])] = dict(doc)

    async def find_one(self, filter_spec: dict[str, Any]) -> dict[str, Any] | None:
        self.find_filters.append(dict(filter_spec))
        for doc in self.documents.values():
            if _matches(doc, filter_spec):
                return dict(doc)
        return None

    def find(self, filter_spec: dict[str, Any]) -> FakeCursor:
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
    return all(doc.get(key) == expected for key, expected in filter_spec.items())


@pytest.mark.asyncio
async def test_execute_known_formula_validates_token_and_cuenta_nickname() -> None:
    now = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
    audit_events: list[dict[str, Any]] = []
    app, db, token = await _app_with_token(now=now, formula_audit_hook=audit_events.append)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/sheets/formulas:execute",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "formula": "ZELERDATA_STOCK",
                "cuenta": "HOPEMOB",
                "args": {"skus": ["SKU-1"], "id_publicaciones": ["MLA1"]},
                "request_id": "req-data-unavailable",
            },
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "values": [[""]], "meta": {"partial_misses": 1}}
    stored = next(iter(db.sheets_extension_tokens.documents.values()))
    assert stored["last_used_at"] == now
    assert audit_events[-1] == {
        "token_id": stored["_id"],
        "seller_id": "123456789",
        "seller_nickname": "HOPEMOB",
        "formula": "ZELERDATA_STOCK",
        "request_id": "req-data-unavailable",
        "outcome": "allowed",
        "error_code": None,
        "occurred_at": now,
    }


@pytest.mark.asyncio
async def test_execute_formula_resolves_multi_seller_cuenta_by_id_and_nickname() -> None:
    now = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)

    def seller_echo_handler(context: Any) -> FormulaExecutionResult:
        return FormulaExecutionResult(
            values=[[context.seller_id, context.seller_nickname]],
            meta={"seller_id": context.seller_id, "seller_nickname": context.seller_nickname},
        )

    app, db = _app(now=now, formula_dispatcher=seller_echo_handler)
    issued = await _token_service(db, now=now).create_token(
        owner_user_id="platform-user-123",
        label="Multi seller formula sheet",
        seller_scopes=[
            SellerScope(seller_id="123456789", nickname="HOPEMOB"),
            SellerScope(seller_id="987654321", nickname="TESTUSER"),
        ],
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        by_id = await client.post(
            "/sheets/formulas:execute",
            headers={"Authorization": f"Bearer {issued.token_once}"},
            json={"formula": "ZELERDATA_SKU", "cuenta": "987654321", "args": {}},
        )
        by_nickname = await client.post(
            "/sheets/formulas:execute",
            headers={"Authorization": f"Bearer {issued.token_once}"},
            json={"formula": "ZELERDATA_SKU", "cuenta": "testuser", "args": {}},
        )
        unauthorized = await client.post(
            "/sheets/formulas:execute",
            headers={"Authorization": f"Bearer {issued.token_once}"},
            json={"formula": "ZELERDATA_SKU", "cuenta": "555555555", "args": {}},
        )

    assert by_id.status_code == 200
    assert by_id.json()["values"] == [["987654321", "TESTUSER"]]
    assert by_nickname.status_code == 200
    assert by_nickname.json()["values"] == [["987654321", "TESTUSER"]]
    assert unauthorized.status_code == 403
    assert unauthorized.json()["error"]["code"] == "SELLER_FORBIDDEN"


@pytest.mark.asyncio
async def test_execute_returns_token_error_envelopes_for_missing_and_revoked_tokens() -> None:
    now = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
    app, _db, token = await _app_with_token(now=now)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        missing = await client.post(
            "/sheets/formulas:execute",
            json={"formula": "ZELERDATA_SKU", "cuenta": "HOPEMOB", "args": {}},
        )
        await _token_service(app.state.mongo_db, now=now).revoke_token(
            next(iter(app.state.mongo_db.sheets_extension_tokens.documents)),
            owner_user_id="user-1",
        )
        revoked = await client.post(
            "/sheets/formulas:execute",
            headers={"Authorization": f"Bearer {token}"},
            json={"formula": "ZELERDATA_SKU", "cuenta": "HOPEMOB", "args": {}},
        )

    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "TOKEN_MISSING"
    assert missing.json()["values"] == [["TOKEN_MISSING: missing extension token"]]
    assert revoked.status_code == 401
    assert revoked.json()["error"]["code"] == "TOKEN_REVOKED"
    assert revoked.json()["values"] == [["TOKEN_REVOKED: extension token is revoked"]]


@pytest.mark.asyncio
async def test_execute_returns_forbidden_unknown_and_bad_argument_envelopes() -> None:
    now = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
    app, _db, token = await _app_with_token(now=now)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        forbidden = await client.post(
            "/sheets/formulas:execute",
            headers={"Authorization": f"Bearer {token}"},
            json={"formula": "ZELERDATA_SKU", "cuenta": "OTHER", "args": {}},
        )
        unknown = await client.post(
            "/sheets/formulas:execute",
            headers={"Authorization": f"Bearer {token}"},
            json={"formula": "SHEETSELLER_SKU", "cuenta": "HOPEMOB", "args": {}},
        )
        bad_argument = await client.post(
            "/sheets/formulas:execute",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "formula": "ZELERDATA_STOCK",
                "cuenta": "HOPEMOB",
                "args": {"skus": ["SKU-1"]},
            },
        )

    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "SELLER_FORBIDDEN"
    assert unknown.status_code == 200
    assert unknown.json()["error"] == {
        "code": "FORMULA_UNKNOWN",
        "message": "unknown formula SHEETSELLER_SKU",
        "retryable": False,
    }
    assert bad_argument.status_code == 400
    assert bad_argument.json()["error"] == {
        "code": "BAD_ARGUMENT",
        "message": "missing required argument id_publicaciones",
        "retryable": False,
    }


@pytest.mark.asyncio
async def test_execute_returns_rate_limited_and_internal_envelopes() -> None:
    now = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
    rate_limited_app, _db, limited_token = await _app_with_token(
        now=now,
        formula_rate_limit_hook=lambda context: context["formula"] != "ZELERDATA_PRECIO",
    )
    internal_app, _internal_db, internal_token = await _app_with_token(
        now=now,
        formula_dispatcher=lambda _context: _raise(RuntimeError("boom")),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=rate_limited_app), base_url="http://test"
    ) as client:
        rate_limited = await client.post(
            "/sheets/formulas:execute",
            headers={"Authorization": f"Bearer {limited_token}"},
            json={
                "formula": "ZELERDATA_PRECIO",
                "cuenta": "HOPEMOB",
                "args": {"skus": ["SKU-1"], "id_publicaciones": ["MLA1"]},
                "request_id": "req-rate",
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=internal_app), base_url="http://test"
    ) as client:
        internal = await client.post(
            "/sheets/formulas:execute",
            headers={"Authorization": f"Bearer {internal_token}"},
            json={"formula": "ZELERDATA_SKU", "cuenta": "HOPEMOB", "args": {}},
        )

    assert rate_limited.status_code == 429
    assert rate_limited.json()["error"]["code"] == "RATE_LIMITED"
    assert rate_limited.json()["values"] == [["RATE_LIMITED: extension token rate limited"]]
    assert internal.status_code == 500
    assert internal.json() == {
        "ok": False,
        "error": {
            "code": "INTERNAL",
            "message": "internal formula error",
            "retryable": True,
        },
        "values": [["INTERNAL: internal formula error"]],
    }


@pytest.mark.asyncio
async def test_batch_returns_independent_formula_envelopes() -> None:
    now = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
    app, _db, token = await _app_with_token(now=now)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/sheets/formulas:batch",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "requests": [
                    {"formula": "ZELERDATA_SKU", "cuenta": "HOPEMOB", "args": {}},
                    {"formula": "SHEETSELLER_SKU", "cuenta": "HOPEMOB", "args": {}},
                ]
            },
        )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    results = response.json()["results"]
    assert [result["status"] for result in results] == [200, 200]
    assert results[0]["body"] == {"ok": True, "values": [], "meta": {"partial_misses": 0}}
    assert results[1]["body"]["error"]["code"] == "FORMULA_UNKNOWN"


@pytest.mark.asyncio
async def test_execute_success_envelope_allows_formula_handlers_to_report_partial_misses() -> None:
    now = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)

    def partial_miss_handler(_context: Any) -> FormulaExecutionResult:
        return FormulaExecutionResult(values=[[""]], meta={"partial_misses": 1})

    app, _db, token = await _app_with_token(
        now=now,
        formula_dispatcher=partial_miss_handler,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/sheets/formulas:execute",
            headers={"Authorization": f"Bearer {token}"},
            json={"formula": "ZELERDATA_SKU", "cuenta": "HOPEMOB", "args": {}},
        )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "values": [[""]],
        "meta": {"partial_misses": 1},
    }


@pytest.mark.asyncio
async def test_execute_resolves_seller_timezone_from_legacy_int_meli_account_id() -> None:
    now = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)

    def timezone_echo_handler(context: Any) -> FormulaExecutionResult:
        return FormulaExecutionResult(
            values=[[context.seller_timezone]],
            meta={"seller_timezone": context.seller_timezone},
        )

    app, db, token = await _app_with_token(
        now=now,
        formula_dispatcher=timezone_echo_handler,
    )
    db["meli_accounts"].documents = {
        "legacy-int-account": {
            "_id": "legacy-int-account",
            "seller_id": 123456789,
            "timezone": "America/Mexico_City",
        }
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/sheets/formulas:execute",
            headers={"Authorization": f"Bearer {token}"},
            json={"formula": "ZELERDATA_SKU", "cuenta": "HOPEMOB", "args": {}},
        )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "values": [["America/Mexico_City"]],
        "meta": {"seller_timezone": "America/Mexico_City"},
    }
    assert db["meli_accounts"].find_filters == [
        {"seller_id": "123456789"},
        {"seller_id": 123456789},
    ]


@pytest.mark.asyncio
async def test_execute_uses_utc_timezone_when_meli_account_timezone_is_missing() -> None:
    now = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)

    def timezone_echo_handler(context: Any) -> FormulaExecutionResult:
        return FormulaExecutionResult(
            values=[[context.seller_timezone]],
            meta={"seller_timezone": context.seller_timezone},
        )

    app, _db, token = await _app_with_token(
        now=now,
        formula_dispatcher=timezone_echo_handler,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/sheets/formulas:execute",
            headers={"Authorization": f"Bearer {token}"},
            json={"formula": "ZELERDATA_SKU", "cuenta": "HOPEMOB", "args": {}},
        )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "values": [["UTC"]],
        "meta": {"seller_timezone": "UTC"},
    }


@pytest.mark.asyncio
async def test_execute_serializes_mongo_decimal_values_as_json_numbers() -> None:
    now = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)

    def decimal_handler(_context: Any) -> FormulaExecutionResult:
        return FormulaExecutionResult(
            values=[
                ["SKU", "Precio"],
                ["DEP-04-153-REM", Decimal128("101.96")],
            ],
            meta={"decimal": Decimal128("1.50")},
        )

    app, _db, token = await _app_with_token(
        now=now,
        formula_dispatcher=decimal_handler,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/sheets/formulas:execute",
            headers={"Authorization": f"Bearer {token}"},
            json={"formula": "ZELERDATA_SKU", "cuenta": "HOPEMOB", "args": {}},
        )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "values": [["SKU", "Precio"], ["DEP-04-153-REM", 101.96]],
        "meta": {"decimal": 1.5},
    }


@pytest.mark.asyncio
async def test_formula_inventory_route_exposes_all_registered_contracts() -> None:
    app, _db = _app()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/sheets/formulas/inventory")

    assert response.status_code == 200
    contracts = response.json()["formulas"]
    assert len(contracts) == 53
    assert contracts[0]["name"] == "ZELERDATA_PUBLICACIONES"
    assert contracts[0]["status"] == "implemented"
    by_name = {contract["name"]: contract for contract in contracts}
    assert by_name["ZELERDATA_DIASDESDEULTIMAVENTA"]["status"] == "implemented"
    assert by_name["ZELERDATA_COMPRADORES"] == by_name["ZELERDATA_COMPRADORES"] | {
        "status": "implemented"
    }
    assert response.json()["error_codes"] == [
        "TOKEN_MISSING",
        "TOKEN_REVOKED",
        "SELLER_FORBIDDEN",
        "FORMULA_UNKNOWN",
        "BAD_ARGUMENT",
        "DATA_UNAVAILABLE",
        "RATE_LIMITED",
        "INTERNAL",
    ]


def _app(
    *,
    now: datetime | None = None,
    formula_audit_hook: Callable[[dict[str, Any]], Any] | None = None,
    formula_rate_limit_hook: Callable[[dict[str, Any]], bool] | None = None,
    formula_dispatcher: Any | None = None,
) -> tuple[FastAPI, FakeDb]:
    from zeler_sheets.api import build_router

    db = FakeDb()
    app = FastAPI()
    app.state.mongo_db = db
    app.include_router(
        build_router(
            clock=lambda: now or datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
            extension_token_pepper="test-pepper",
            formula_audit_hook=formula_audit_hook,
            formula_rate_limit_hook=formula_rate_limit_hook,
            formula_dispatcher=formula_dispatcher,
        )
    )
    return app, db


async def _app_with_token(
    *,
    now: datetime,
    formula_audit_hook: Callable[[dict[str, Any]], Any] | None = None,
    formula_rate_limit_hook: Callable[[dict[str, Any]], bool] | None = None,
    formula_dispatcher: Any | None = None,
) -> tuple[FastAPI, FakeDb, str]:
    app, db = _app(
        now=now,
        formula_audit_hook=formula_audit_hook,
        formula_rate_limit_hook=formula_rate_limit_hook,
        formula_dispatcher=formula_dispatcher,
    )
    issued = await _token_service(db, now=now).create_token(
        owner_user_id="user-1",
        label="Formula sheet",
        seller_scopes=[SellerScope(seller_id="123456789", nickname="HOPEMOB")],
    )
    return app, db, issued.token_once


def _token_service(db: FakeDb, *, now: datetime) -> ExtensionTokenService:
    return ExtensionTokenService(
        db=db,
        token_pepper="test-pepper",
        now_fn=lambda: now,
        token_factory=lambda: "formula-secret",
    )


def _raise(exc: Exception) -> None:
    raise exc
