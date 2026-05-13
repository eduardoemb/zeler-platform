# ruff: noqa: S105,S106

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI


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
    def __init__(self, docs: list[dict[str, Any]] | None = None) -> None:
        self.docs = docs or []

    async def insert_one(self, doc: dict[str, Any]) -> None:
        self.docs.append(dict(doc))

    async def find_one(self, filter_spec: dict[str, Any]) -> dict[str, Any] | None:
        for doc in self.docs:
            if _matches(doc, filter_spec):
                return dict(doc)
        return None

    def find(self, filter_spec: dict[str, Any]) -> FakeCursor:
        return FakeCursor([dict(doc) for doc in self.docs if _matches(doc, filter_spec)])

    async def update_one(
        self, filter_spec: dict[str, Any], update_spec: dict[str, Any], *, upsert: bool = False
    ) -> FakeUpdateResult:
        assert upsert is False
        for index, doc in enumerate(self.docs):
            if _matches(doc, filter_spec):
                replacement = dict(doc)
                replacement.update(update_spec.get("$set", {}))
                self.docs[index] = replacement
                return FakeUpdateResult()
        raise AssertionError(f"no matching document for {filter_spec}")


class FakeDb:
    def __init__(self) -> None:
        self.sheets_exports = FakeCollection()
        self.sheets_sync_jobs = FakeCollection()
        self.sheets_extension_tokens = FakeCollection()

    def __getitem__(self, name: str) -> FakeCollection:
        if name == "sheets_exports":
            return self.sheets_exports
        if name == "sheets_sync_jobs":
            return self.sheets_sync_jobs
        if name == "sheets_extension_tokens":
            return self.sheets_extension_tokens
        raise AssertionError(name)


def _matches(doc: dict[str, Any], filter_spec: dict[str, Any]) -> bool:
    return all(doc.get(key) == value for key, value in filter_spec.items())


@pytest.mark.asyncio
async def test_create_and_list_extension_token_show_secret_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, db = _app(monkeypatch, token_values=["api-secret"])

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        create_response = await client.post(
            "/sheets/extension-tokens",
            headers={"Authorization": "Bearer valid"},
            json={
                "label": "Operator sheet",
                "seller_scopes": [{"seller_id": "123456789", "nickname": "HOPEMOB"}],
                "formula_scopes": ["formulas:execute"],
            },
        )
        list_response = await client.get(
            "/sheets/extension-tokens?owner_user_id=user-1",
            headers={"Authorization": "Bearer valid"},
        )

    assert create_response.status_code == 201
    body = create_response.json()
    assert body["token_once"].startswith("zs_ext_")
    assert body["status"] == "active"
    assert body["seller_scopes"] == [{"seller_id": "123456789", "nickname": "HOPEMOB"}]
    stored = db.sheets_extension_tokens.docs[0]
    assert stored["token_prefix"] == body["token_prefix"]
    assert stored["token_hash"] != body["token_once"]
    assert "token_once" not in stored

    assert list_response.status_code == 200
    assert list_response.json() == [
        {key: value for key, value in body.items() if key != "token_once"}
    ]


@pytest.mark.asyncio
async def test_rotate_and_revoke_extension_token_api(monkeypatch: pytest.MonkeyPatch) -> None:
    app, db = _app(monkeypatch, token_values=["api-secret", "rotated-secret"])

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post(
            "/sheets/extension-tokens",
            headers={"Authorization": "Bearer valid"},
            json={
                "label": "Operator sheet",
                "seller_scopes": [{"seller_id": "123456789", "nickname": "HOPEMOB"}],
            },
        )
        token_id = created.json()["id"]
        rotated = await client.post(
            f"/sheets/extension-tokens/{token_id}:rotate",
            headers={"Authorization": "Bearer valid"},
        )
        revoked = await client.post(
            f"/sheets/extension-tokens/{rotated.json()['id']}:revoke",
            headers={"Authorization": "Bearer valid"},
        )

    assert rotated.status_code == 200
    assert rotated.json()["token_once"].startswith("zs_ext_")
    assert rotated.json()["token_once"] != created.json()["token_once"]
    assert db.sheets_extension_tokens.docs[0]["status"] == "revoked"
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"
    assert db.sheets_extension_tokens.docs[-1]["status"] == "revoked"


@pytest.mark.asyncio
async def test_extension_token_api_requires_module_admin_jwt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from zeler_platform_core.auth.jwt import InvalidJWTError

    app, _db = _app(monkeypatch, jwt_error=InvalidJWTError("bad token"))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/sheets/extension-tokens?owner_user_id=user-1",
            headers={"Authorization": "Bearer invalid"},
        )

    assert response.status_code == 401
    assert response.json() == {"error": "invalid_token", "detail": "bad token"}


@pytest.mark.asyncio
async def test_extension_token_api_can_read_pepper_from_app_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pydantic import SecretStr

    from zeler_sheets.sheets_config import SheetsSettings

    app, _db = _app(monkeypatch, token_values=["settings-secret"], configure_pepper=False)
    app.state.settings = SheetsSettings(
        google_oauth_client_id="google-client-id",
        google_oauth_client_secret=SecretStr("google-client-secret"),
        google_oauth_redirect_uri="https://sheets.test/oauth/google/callback",
        kms_project_id="zeler-dev",
        extension_token_pepper=SecretStr("settings-pepper"),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/sheets/extension-tokens",
            headers={"Authorization": "Bearer valid"},
            json={
                "label": "Operator sheet",
                "seller_scopes": [{"seller_id": "123456789", "nickname": "HOPEMOB"}],
            },
        )

    assert response.status_code == 201
    assert response.json()["token_once"].startswith("zs_ext_")


def _app(
    monkeypatch: pytest.MonkeyPatch,
    *,
    token_values: list[str] | None = None,
    jwt_error: Exception | None = None,
    configure_pepper: bool = True,
) -> tuple[FastAPI, FakeDb]:
    import zeler_sheets.api as api
    from zeler_sheets.api import build_router

    values = token_values or ["api-secret"]
    db = FakeDb()
    app = FastAPI()
    app.state.mongo_db = db
    pepper = "test-pepper" if configure_pepper else None
    app.include_router(
        build_router(
            clock=lambda: datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
            extension_token_pepper=pepper,
            extension_token_factory=lambda: values.pop(0),
        )
    )

    def fake_verify(_token: str) -> object:
        if jwt_error is not None:
            raise jwt_error
        return _claims()

    monkeypatch.setattr(api, "verify_module_jwt", fake_verify)
    return app, db


def _claims() -> object:
    from zeler_platform_core.auth.jwt import ModuleClaims

    return ModuleClaims(
        module_id="sheets",
        seller_id=123456789,
        iss="module:sheets",
        aud="gateway",
        iat=1,
        exp=2,
        token_type="module_admin",
        scopes=["admin:sheets"],
        issued_by="user-1",
    )
