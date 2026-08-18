# ruff: noqa: S105,S106

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import structlog
from bson.decimal128 import Decimal128
from fastapi import FastAPI
from pymongo.errors import DuplicateKeyError, PyMongoError

from zeler_sheets.extension_tokens import (
    ExtensionTokenService,
    ExtensionTokenValidationError,
    SellerScope,
    hash_extension_token,
)
from zeler_sheets.formulas.dispatcher import FormulaExecutionResult
from zeler_sheets.formulas.read_models import ITEM_FORMULA_ROWS_READ_MODEL


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
        self.operations: list[tuple[str, str]] = []
        self.duplicate_aware = False
        self.insert_failure: Exception | None = None

    async def insert_one(self, doc: dict[str, Any]) -> None:
        if self.insert_failure is not None:
            raise self.insert_failure
        doc_id = str(doc["_id"])
        if self.duplicate_aware and doc_id in self.documents:
            raise DuplicateKeyError(f"E11000 duplicate key error collection: {doc_id}")
        self.documents[doc_id] = dict(doc)
        self.operations.append(("insert", doc_id))

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
                self.operations.append(("update", doc_id))
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


class ExplodingCipher:
    def encrypt(self, *_args: Any, **_kwargs: Any) -> dict[str, bytes | str]:
        raise AssertionError("formula validation must not encrypt extension-token secrets")

    async def decrypt(self, *_args: Any, **_kwargs: Any) -> str:
        raise AssertionError("formula validation must not decrypt extension-token secrets")


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
async def test_build_app_persists_sanitized_formula_audit_record() -> None:
    from zeler_sheets.app import build_app

    now = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
    db = FakeDb()
    app = build_app(mongo_db=db)
    app.state.extension_token_pepper = "test-pepper"
    issued = await _token_service(db, now=now).create_token(
        owner_user_id="user-1",
        label="Formula sheet",
        seller_scopes=[SellerScope(seller_id="123456789", nickname="HOPEMOB")],
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/sheets/formulas:execute",
            headers={"Authorization": f"Bearer {issued.token_once}"},
            json={
                "formula": "ZELERDATA_STOCK",
                "cuenta": "HOPEMOB",
                "args": {"skus": ["SKU-1"], "id_publicaciones": ["MLA1"]},
                "request_id": "req-production-audit",
            },
        )

    assert response.status_code == 200
    audit_doc = next(iter(db["sheets_formula_audit"].documents.values()))
    occurred_at = audit_doc.pop("occurred_at")
    assert isinstance(occurred_at, datetime)
    assert audit_doc == {
        "_id": "formula-audit-req-production-audit",
        "token_id": next(iter(db.sheets_extension_tokens.documents.values()))["_id"],
        "seller_id": "123456789",
        "seller_nickname": "HOPEMOB",
        "formula": "ZELERDATA_STOCK",
        "request_id": "req-production-audit",
        "outcome": "allowed",
        "error_code": None,
        "schema_version": 1,
    }


async def _create_token(db: FakeDb) -> str:
    issued = await _token_service(db, now=datetime(2026, 5, 13, 12, 0, tzinfo=UTC)).create_token(
        owner_user_id="user-1",
        label="Formula sheet",
        seller_scopes=[SellerScope(seller_id="123456789", nickname="HOPEMOB")],
    )
    return issued.token_once


async def _execute(client: httpx.AsyncClient, token: str | None, **payload: Any) -> httpx.Response:
    body: dict[str, Any] = {"formula": "ZELERDATA_SKU", "cuenta": "HOPEMOB", "args": {}}
    body.update(payload)
    headers: dict[str, str] = {} if token is None else {"Authorization": f"Bearer {token}"}
    return await client.post("/sheets/formulas:execute", headers=headers, json=body)


@pytest.mark.parametrize(
    ("scenario", "cuenta", "status_code", "error_code", "request_id"),
    [
        ("revoked", "HOPEMOB", 401, "TOKEN_REVOKED", "req-revoked"),
        ("forbidden", "OTHER", 403, "SELLER_FORBIDDEN", "req-forbidden"),
        ("rate-limited", "HOPEMOB", 429, "RATE_LIMITED", "req-rate-limited"),
    ],
)
@pytest.mark.asyncio
async def test_build_app_persists_denied_audit_without_updating_last_used(
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
    cuenta: str,
    status_code: int,
    error_code: str,
    request_id: str,
) -> None:
    db = FakeDb()
    app, _ = await _production_app(db)
    token = await _create_token(db)
    if scenario == "revoked":
        next(iter(db.sheets_extension_tokens.documents.values()))["status"] = "revoked"
    if scenario == "rate-limited":

        async def deny_rate_limit(
            self: Any,
            doc: dict[str, Any],
            scope: SellerScope,
            *,
            formula: str,
            request_id: str | None,
        ) -> None:
            raise ExtensionTokenValidationError("RATE_LIMITED", "extension token rate limited")

        monkeypatch.setattr(ExtensionTokenService, "_enforce_rate_limit", deny_rate_limit)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await _execute(client, token, request_id=request_id, cuenta=cuenta)

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == error_code
    assert next(iter(db.sheets_extension_tokens.documents.values()))["last_used_at"] is None
    audit = db["sheets_formula_audit"].documents[f"formula-audit-{request_id}"]
    assert isinstance(audit["occurred_at"], datetime)
    assert audit["outcome"] == "denied"
    assert audit["error_code"] == error_code
    assert audit["seller_id"] == ("123456789" if scenario == "rate-limited" else "None")


@pytest.mark.asyncio
async def test_build_app_repeats_request_id_idempotently_without_rewriting_audit() -> None:
    db = FakeDb()
    audit = db["sheets_formula_audit"]
    audit.duplicate_aware = True
    app, _ = await _production_app(db)
    token = await _create_token(db)
    payload = {
        "formula": "ZELERDATA_STOCK",
        "args": {"skus": ["SKU-1"], "id_publicaciones": ["MLA1"]},
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await _execute(client, token, request_id="req-repeated", **payload)
        second = await _execute(client, token, request_id="req-repeated", **payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert (
        first.json()
        == second.json()
        == {"ok": True, "values": [[""]], "meta": {"partial_misses": 1}}
    )
    assert len(audit.documents) == 1
    assert audit.documents["formula-audit-req-repeated"]["outcome"] == "allowed"
    assert audit.operations == [("insert", "formula-audit-req-repeated")]


@pytest.mark.asyncio
async def test_build_app_allowed_result_survives_audit_failure_without_leaking_secrets() -> None:
    db = FakeDb()
    db["sheets_formula_audit"].insert_failure = PyMongoError("mongo unavailable")
    app, _ = await _production_app(db)
    token = await _create_token(db)
    payload = {
        "formula": "ZELERDATA_STOCK",
        "args": {"skus": ["SKU-1"], "id_publicaciones": ["MLA1"]},
    }

    with structlog.testing.capture_logs() as entries:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await _execute(client, token, request_id="req-failing-allowed", **payload)

    assert response.status_code == 200
    assert response.json() == {"ok": True, "values": [[""]], "meta": {"partial_misses": 1}}
    assert next(iter(db.sheets_extension_tokens.documents.values()))["last_used_at"] is not None
    assert db["sheets_formula_audit"].documents == {}
    assert set(entries[0]) == {"event", "log_level", "exception_type", "outcome", "error_code"}
    serialized = str(entries)
    assert token not in serialized
    assert "SKU-1" not in serialized
    assert "Bearer" not in serialized


@pytest.mark.asyncio
async def test_build_app_revoked_denial_preserved_when_audit_write_fails() -> None:
    db = FakeDb()
    db["sheets_formula_audit"].insert_failure = PyMongoError("mongo unavailable")
    app, _ = await _production_app(db)
    token = await _create_token(db)
    next(iter(db.sheets_extension_tokens.documents.values()))["status"] = "revoked"

    with structlog.testing.capture_logs() as entries:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await _execute(client, token, request_id="req-failing-revoked")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_REVOKED"
    assert len(entries) == 1
    assert entries[0]["error_code"] == "TOKEN_REVOKED"


@pytest.mark.asyncio
async def test_build_app_allowed_updates_last_used_before_audit_insert() -> None:
    db = FakeDb()
    app, _ = await _production_app(db)
    token = await _create_token(db)
    token_id = next(iter(db.sheets_extension_tokens.documents.values()))["_id"]

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await _execute(client, token, request_id="req-ordered")

    assert response.status_code == 200
    assert db.sheets_extension_tokens.operations[-1] == ("update", token_id)
    assert db["sheets_formula_audit"].operations == [("insert", "formula-audit-req-ordered")]


@pytest.mark.asyncio
async def test_build_app_missing_token_and_unknown_hash_create_no_audit() -> None:
    db = FakeDb()
    app, _ = await _production_app(db)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        missing = await _execute(client, None, request_id="req-missing")
        unknown = await _execute(client, "zs_ext_never_minted", request_id="req-unknown")

    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "TOKEN_MISSING"
    assert unknown.status_code == 401
    assert unknown.json()["error"]["code"] == "TOKEN_REVOKED"
    assert db["sheets_formula_audit"].documents == {}


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
async def test_execute_rejects_deleted_token_without_revealing_secret() -> None:
    now = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
    app, db, token = await _app_with_token(now=now)
    stored = next(iter(db.sheets_extension_tokens.documents.values()))
    stored["deleted_at"] = now

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/sheets/formulas:execute",
            headers={"Authorization": f"Bearer {token}"},
            json={"formula": "ZELERDATA_SKU", "cuenta": "HOPEMOB", "args": {}},
        )

    assert response.status_code == 401
    assert response.json()["error"] == {
        "code": "TOKEN_REVOKED",
        "message": "El token fue eliminado.",
        "retryable": False,
    }
    assert response.json()["values"] == [["TOKEN_REVOKED: El token fue eliminado."]]
    assert token not in str(response.json())


@pytest.mark.asyncio
async def test_execute_accepts_legacy_hash_only_token_without_decrypting() -> None:
    now = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
    app, db = _app(now=now)
    app.state.extension_token_secret_cipher = ExplodingCipher()
    legacy_token = "zs_ext_legacy-formula-material"
    await db.sheets_extension_tokens.insert_one(
        {
            "_id": "sheets-ext-token-legacy-formula",
            "label": "Legacy formula token",
            "token_prefix": legacy_token[:18],
            "token_hash": hash_extension_token(legacy_token, token_pepper="test-pepper"),
            "owner_user_id": "user-1",
            "seller_scopes": [{"seller_id": "123456789", "nickname": "HOPEMOB"}],
            "formula_scopes": ["formulas:execute"],
            "status": "active",
            "expires_at": None,
            "created_at": now,
            "updated_at": now,
            "rotated_at": None,
            "revoked_at": None,
            "last_used_at": None,
            "schema_version": 1,
        }
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/sheets/formulas:execute",
            headers={"Authorization": f"Bearer {legacy_token}"},
            json={"formula": "ZELERDATA_SKU", "cuenta": "HOPEMOB", "args": {}},
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "values": [], "meta": {"partial_misses": 0}}


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
        deprecated = await client.post(
            "/sheets/formulas:execute",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "formula": "ZELERDATA_COMPETENCIA",
                "cuenta": "HOPEMOB",
                "args": {"id_publicaciones": "todos"},
            },
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
    assert deprecated.status_code == 200
    assert deprecated.json()["error"] == {
        "code": "FORMULA_UNKNOWN",
        "message": "unknown formula ZELERDATA_COMPETENCIA",
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
async def test_execute_propagates_seller_specific_meli_account_timezone() -> None:
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
        "hopemob-account": {
            "_id": "hopemob-account",
            "seller_id": "123456789",
            "timezone": "America/Tijuana",
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
        "values": [["America/Tijuana"]],
        "meta": {"seller_timezone": "America/Tijuana"},
    }
    assert db["meli_accounts"].find_filters == [{"seller_id": "123456789"}]


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
async def test_execute_questions_returns_data_unavailable_without_freshness_marker() -> None:
    now = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
    app, _db, token = await _app_with_token(now=now)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/sheets/formulas:execute",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "formula": "ZELERDATA_PREGUNTAS",
                "cuenta": "HOPEMOB",
                "args": {
                    "fecha_inicial": "2026-05-10",
                    "fecha_final": "2026-05-10",
                    "horario_inicial": "00:00",
                    "horario_final": "23:59",
                },
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["error"] == {
        "code": "DATA_UNAVAILABLE",
        "message": (
            "ZELERDATA_PREGUNTAS data is not available yet: Questions read model has "
            "not passed freshness/reconciliation for the requested range."
        ),
        "retryable": False,
    }
    assert body["values"] == [[f"DATA_UNAVAILABLE: {body['error']['message']}"]]


@pytest.mark.asyncio
async def test_execute_retiros_requires_fresh_read_model_marker() -> None:
    now = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
    app, _db, token = await _app_with_token(now=now)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/sheets/formulas:execute",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "formula": "ZELERDATA_RETIROS",
                "cuenta": "HOPEMOB",
                "args": {
                    "fecha_inicial": "2026-05-01",
                    "fecha_final": "2026-05-31",
                    "encabezados": "si",
                },
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "DATA_UNAVAILABLE"
    assert body["error"]["message"] == (
        "ZELERDATA_RETIROS data is not available yet: Read model "
        "full_withdrawals has not passed freshness/reconciliation for the requested range."
    )
    assert body["values"] == [[f"DATA_UNAVAILABLE: {body['error']['message']}"]]


@pytest.mark.asyncio
async def test_execute_calidad_requires_fresh_item_read_model_marker() -> None:
    now = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
    app, _db, token = await _app_with_token(now=now)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/sheets/formulas:execute",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "formula": "ZELERDATA_CALIDAD",
                "cuenta": "HOPEMOB",
                "args": {"encabezados": "si"},
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "DATA_UNAVAILABLE"
    assert body["error"]["message"] == (
        "ZELERDATA_CALIDAD data is not available yet: Read model "
        "item_formula_rows has not passed freshness/reconciliation for the requested range."
    )
    assert body["values"] == [[f"DATA_UNAVAILABLE: {body['error']['message']}"]]


@pytest.mark.asyncio
async def test_execute_calidad_uses_default_runtime_handler() -> None:
    now = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
    app, db, token = await _app_with_token(now=now)
    db["sheets_read_model_freshness"].documents[f"123456789:{ITEM_FORMULA_ROWS_READ_MODEL}"] = {
        "_id": f"123456789:{ITEM_FORMULA_ROWS_READ_MODEL}",
        "seller_id": "123456789",
        "read_model": ITEM_FORMULA_ROWS_READ_MODEL,
        "state": "fresh",
        "fresh_until": now,
        "reconciled_until": now,
        "updated_at": now,
        "schema_version": 1,
    }
    db["sheets_item_formula_rows"].documents = {
        "123456789:SKU-1:MLA1": {
            "_id": "123456789:SKU-1:MLA1",
            "seller_id": "123456789",
            "item_id": "MLA1",
            "sku": "SKU-1",
            "normalized_sku": "SKU-1",
            "current": {
                "title": "Quality item",
                "status": "active",
                "permalink": "https://meli.example/MLA1",
                "available_quantity": 4,
                "listing_type_id": "gold_special",
                "health": 0.82,
            },
        }
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/sheets/formulas:execute",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "formula": "ZELERDATA_CALIDAD",
                "cuenta": "HOPEMOB",
                "args": {"encabezados": "si"},
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["values"][0][:4] == ["ID PUBLICACION", "SKU", "TITULO", "STATUS"]
    assert body["values"][1][:9] == [
        "MLA1",
        "SKU-1",
        "Quality item",
        "active",
        "https://meli.example/MLA1",
        4,
        "gold_special",
        0.82,
        "good",
    ]
    assert body["meta"] == {"rows_count": 1, "columns": "modern_quality_projection"}


@pytest.mark.asyncio
async def test_formula_inventory_route_exposes_all_registered_contracts() -> None:
    app, _db = _app()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/sheets/formulas/inventory")

    assert response.status_code == 200
    contracts = response.json()["formulas"]
    assert len(contracts) == 52
    assert contracts[0]["name"] == "ZELERDATA_PUBLICACIONES"
    assert contracts[0]["status"] == "implemented"
    by_name = {contract["name"]: contract for contract in contracts}
    assert "ZELERDATA_COMPETENCIA" not in by_name
    assert "ZELERDATA_ENVIARAFULL" not in by_name
    assert by_name["ZELERDATA_CATALOGO_COMPLETO"] == by_name["ZELERDATA_CATALOGO_COMPLETO"] | {
        "status": "implemented"
    }
    assert by_name["ZELERDATA_CATALOGO"]["status"] == "implemented"
    assert by_name["ZELERDATA_DIASDESDEULTIMAVENTA"]["status"] == "implemented"
    assert by_name["ZELERDATA_COMPRADORES"] == by_name["ZELERDATA_COMPRADORES"] | {
        "status": "implemented"
    }
    assert by_name["ZELERDATA_DEVOLUCIONES"]["status"] == "implemented"
    assert by_name["ZELERDATA_PUBLICACIONESDESCUIDADAS"]["status"] == "implemented"
    assert by_name["ZELERDATA_TIEMPOACTIVA"]["status"] == "implemented"
    assert by_name["ZELERDATA_CALIDAD"]["status"] == "implemented"
    assert by_name["ZELERDATA_CALCULADORA"]["status"] == "implemented"
    for formula in [
        "ZELERDATA_CATALOGOTIEMPO",
        "ZELERDATA_PRECIOHISTORICO",
        "ZELERDATA_RETIROS",
        "ZELERDATA_SEMANASCONSTOCK",
        "ZELERDATA_TIEMPOSINSTOCK",
        "ZELERDATA_TIEMPOSTOCKACTIVO",
    ]:
        assert by_name[formula]["status"] == "implemented"
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


async def _production_app(db: FakeDb) -> tuple[FastAPI, FakeDb]:
    from zeler_sheets.app import build_app

    app = build_app(mongo_db=db)
    app.state.extension_token_pepper = "test-pepper"
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
