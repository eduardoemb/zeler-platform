from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

ADMIN_CLIENT_SEED_PATH = (
    Path(__file__).resolve().parents[2]
    / "infra"
    / "mongo"
    / "seeds"
    / "module_registry.admin_clients.json"
)


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


@pytest.mark.asyncio
async def test_issue_can_return_short_lived_module_admin_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import zeler_gateway.internal.router as internal_router
    from zeler_gateway.internal.router import router

    app = FastAPI()
    app.state.mongo_db = FakeAsyncDb()
    app.state.mongo_db["module_registry"].documents.append(
        {"_id": "zeler-app", "status": "enabled", "allowed_meli_scopes": ["admin:repricer"]}
    )
    app.include_router(router)
    monkeypatch.setattr(
        internal_router,
        "verify_module_jwt",
        lambda token: FakeClaims(module_id="zeler-app"),
    )
    monkeypatch.setattr(
        internal_router,
        "mint_module_jwt",
        lambda module_id, seller_id, ttl_s, **_claims: f"jwt:{module_id}:{seller_id}:{ttl_s}",
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/internal/tokens/issue",
            headers={"Authorization": "Bearer app-gateway-token"},
            json={
                "seller_id": 123456789,
                "scopes": ["admin:repricer"],
                "ttl_s": 120,
                "token_kind": "module_admin",
                "target_module_id": "repricer",
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "access_token": "jwt:repricer:123456789:120",
        "token_type": "Bearer",
        "expires_in": 120,
        "scopes": ["admin:repricer"],
    }
    audit_doc = app.state.mongo_db["audit_log"].documents[0]
    assert audit_doc["module_id"] == "zeler-app"
    assert audit_doc["target_module_id"] == "repricer"
    assert audit_doc["token_kind"] == "module_admin"  # noqa: S105 - token type discriminator


@pytest.mark.asyncio
async def test_issue_module_admin_token_requires_target_module_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import zeler_gateway.internal.router as internal_router
    from zeler_gateway.internal.router import router

    app = FastAPI()
    app.state.mongo_db = FakeAsyncDb()
    app.state.mongo_db["module_registry"].documents.append(
        {"_id": "zeler-app", "status": "enabled", "allowed_meli_scopes": ["admin:repricer"]}
    )
    app.include_router(router)
    monkeypatch.setattr(
        internal_router,
        "verify_module_jwt",
        lambda token: FakeClaims(module_id="zeler-app"),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/internal/tokens/issue",
            headers={"Authorization": "Bearer app-gateway-token"},
            json={
                "seller_id": 123456789,
                "scopes": ["admin:repricer"],
                "ttl_s": 120,
                "token_kind": "module_admin",
            },
        )

    assert response.status_code == 422
    assert response.json() == {"error": "target_module_id_required"}


def test_admin_client_seed_contains_zeler_app_all_module_admin_scopes() -> None:
    seed = json.loads(ADMIN_CLIENT_SEED_PATH.read_text(encoding="utf-8"))

    assert seed["collection"] == "module_registry"
    zeler_app = next(doc for doc in seed["documents"] if doc["_id"] == "zeler-app")
    assert zeler_app == {
        "_id": "zeler-app",
        "version": "0.1.0",
        "allowed_meli_scopes": [
            "admin:repricer",
            "admin:sheets",
            "admin:publicador",
            "admin:autoreply",
            "admin:fulldock",
        ],
        "allowed_seller_ids": [82453304],
        "routing_keys": [],
        "owned_collections": [],
        "health_endpoint": "/health",
        "status": "enabled",
        "schema_version": 1,
    }


@pytest.mark.asyncio
async def test_zeler_app_seed_allows_repricer_admin_token_exchange(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import zeler_gateway.internal.router as internal_router
    from zeler_gateway.internal.router import router

    seed = json.loads(ADMIN_CLIENT_SEED_PATH.read_text(encoding="utf-8"))
    app = FastAPI()
    app.state.mongo_db = FakeAsyncDb()
    app.state.mongo_db["module_registry"].documents.extend(seed["documents"])
    app.include_router(router)
    monkeypatch.setattr(
        internal_router,
        "verify_module_jwt",
        lambda token: FakeClaims(module_id="zeler-app", seller_id=82453304),
    )
    monkeypatch.setattr(
        internal_router,
        "mint_module_jwt",
        lambda module_id, seller_id, ttl_s, **_claims: f"jwt:{module_id}:{seller_id}:{ttl_s}",
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/internal/tokens/issue",
            headers={"Authorization": "Bearer zeler-app-gateway-token"},
            json={
                "seller_id": 82453304,
                "scopes": ["admin:repricer"],
                "ttl_s": 120,
                "token_kind": "module_admin",
                "target_module_id": "repricer",
            },
        )

    assert response.status_code == 200
    assert response.json()["access_token"] == "jwt:repricer:82453304:120"  # noqa: S105


@pytest.mark.asyncio
async def test_zeler_app_seed_allows_all_module_admin_scopes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import zeler_gateway.internal.router as internal_router
    from zeler_gateway.internal.router import router

    seed = json.loads(ADMIN_CLIENT_SEED_PATH.read_text(encoding="utf-8"))
    app = FastAPI()
    app.state.mongo_db = FakeAsyncDb()
    app.state.mongo_db["module_registry"].documents.extend(seed["documents"])
    app.include_router(router)
    monkeypatch.setattr(
        internal_router,
        "verify_module_jwt",
        lambda token: FakeClaims(module_id="zeler-app", seller_id=82453304),
    )
    monkeypatch.setattr(
        internal_router,
        "mint_module_jwt",
        lambda module_id, seller_id, ttl_s, **_claims: f"jwt:{module_id}:{seller_id}:{ttl_s}",
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/internal/tokens/issue",
            headers={"Authorization": "Bearer zeler-app-gateway-token"},
            json={
                "seller_id": 82453304,
                "scopes": ["admin:publicador"],
                "ttl_s": 120,
                "token_kind": "module_admin",
                "target_module_id": "publicador",
            },
        )

    assert response.status_code == 200
    assert response.json()["access_token"] == "jwt:publicador:82453304:120"  # noqa: S105
