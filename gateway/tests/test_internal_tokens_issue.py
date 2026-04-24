from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from fastapi import FastAPI


class FakeAsyncCollection:
    def __init__(self, documents: list[dict[str, Any]] | None = None) -> None:
        self.documents = documents or []

    async def find_one(self, filter_doc: dict[str, Any]) -> dict[str, Any] | None:
        for document in self.documents:
            if all(document.get(key) == value for key, value in filter_doc.items()):
                return document
        return None

    async def insert_one(self, document: dict[str, Any]) -> None:
        self.documents.append(document)


class FakeAsyncDb:
    def __init__(self) -> None:
        self.collections = {
            "module_registry": FakeAsyncCollection(
                [
                    {
                        "_id": "repricer",
                        "status": "enabled",
                        "allowed_meli_scopes": ["PUT /items/*"],
                    }
                ]
            ),
            "meli_accounts": FakeAsyncCollection(
                [
                    {
                        "seller_id": 123456789,
                        "status": "active",
                        "access_token_ciphertext": b"ciphertext",
                        "access_token_dek_wrapped": b"wrapped",
                        "token_nonce": b"nonce-1234567",
                        "kms_key_version": "key-version-1",
                    }
                ]
            ),
            "audit_log": FakeAsyncCollection(),
        }

    def __getitem__(self, name: str) -> FakeAsyncCollection:
        return self.collections[name]


@dataclass(frozen=True)
class FakeClaims:
    module_id: str = "repricer"
    seller_id: int = 123456789


@pytest.mark.asyncio
async def test_issue_returns_token_and_audits_issuance(monkeypatch: pytest.MonkeyPatch) -> None:
    import zeler_gateway.internal.router as internal_router
    from zeler_gateway.internal.router import router

    app = FastAPI()
    app.state.mongo_db = FakeAsyncDb()
    app.include_router(router)
    monkeypatch.setattr(internal_router, "verify_module_jwt", lambda token: FakeClaims())

    async def fake_decrypt_token(_token: object, *, account_id: str) -> str:
        assert account_id == "123456789"
        return "plain-meli-access-token"

    monkeypatch.setattr(internal_router, "decrypt_token", fake_decrypt_token)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/internal/tokens/issue",
            headers={"Authorization": "Bearer valid"},
            json={"seller_id": 123456789, "scopes": ["PUT /items/MLA123"], "ttl_s": 300},
        )

    assert response.status_code == 200
    assert response.json() == {
        "access_token": "plain-meli-access-token",
        "token_type": "Bearer",
        "expires_in": 300,
        "scopes": ["PUT /items/MLA123"],
    }
    audit_doc = app.state.mongo_db["audit_log"].documents[0]
    assert audit_doc["module_id"] == "repricer"
    assert audit_doc["seller_id"] == 123456789
    assert audit_doc["method"] == "POST"
    assert audit_doc["path"] == "/internal/tokens/issue"
    assert audit_doc["status"] == 200


@pytest.mark.asyncio
async def test_issue_requires_valid_jwt(monkeypatch: pytest.MonkeyPatch) -> None:
    import zeler_gateway.internal.router as internal_router
    from zeler_gateway.internal.router import router
    from zeler_platform_core.auth.jwt import InvalidJWTError

    app = FastAPI()
    app.state.mongo_db = FakeAsyncDb()
    app.include_router(router)

    def reject_token(_token: str) -> FakeClaims:
        raise InvalidJWTError("bad token")

    monkeypatch.setattr(internal_router, "verify_module_jwt", reject_token)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/internal/tokens/issue",
            headers={"Authorization": "Bearer invalid"},
            json={"seller_id": 123456789, "scopes": ["PUT /items/MLA123"], "ttl_s": 60},
        )

    assert response.status_code == 401
    assert response.json() == {"error": "invalid_token", "detail": "bad token"}


@pytest.mark.asyncio
async def test_issue_scope_narrowed_to_allowed_scopes(monkeypatch: pytest.MonkeyPatch) -> None:
    import zeler_gateway.internal.router as internal_router
    from zeler_gateway.internal.router import router

    app = FastAPI()
    app.state.mongo_db = FakeAsyncDb()
    app.include_router(router)
    monkeypatch.setattr(internal_router, "verify_module_jwt", lambda token: FakeClaims())

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/internal/tokens/issue",
            headers={"Authorization": "Bearer valid"},
            json={"seller_id": 123456789, "scopes": ["DELETE /items/MLA123"], "ttl_s": 60},
        )

    assert response.status_code == 403
    assert response.json() == {"error": "out_of_scope"}


@pytest.mark.asyncio
async def test_issue_rejects_ttl_over_five_minutes(monkeypatch: pytest.MonkeyPatch) -> None:
    import zeler_gateway.internal.router as internal_router
    from zeler_gateway.internal.router import router

    app = FastAPI()
    app.state.mongo_db = FakeAsyncDb()
    app.include_router(router)
    monkeypatch.setattr(internal_router, "verify_module_jwt", lambda token: FakeClaims())

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/internal/tokens/issue",
            headers={"Authorization": "Bearer valid"},
            json={"seller_id": 123456789, "scopes": ["PUT /items/MLA123"], "ttl_s": 301},
        )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "ttl_s"]
