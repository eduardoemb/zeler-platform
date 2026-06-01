from __future__ import annotations

import base64
import hashlib
import hmac
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
BROKER_SECRET = "test-zeler-app-broker-secret"  # noqa: S105 - test fixture only


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


def _json_body(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def _broker_headers(body: bytes) -> dict[str, str]:
    digest = hmac.new(BROKER_SECRET.encode("utf-8"), body, hashlib.sha256).digest()
    signature = "sha256=" + base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return {
        "Content-Type": "application/json",
        "X-Zeler-Client-Id": "zeler-app",
        "X-Zeler-Signature": signature,
    }


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
async def test_zeler_app_bearer_module_admin_token_requires_broker_signature(
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
    mint_calls: list[dict[str, Any]] = []

    def record_mint_call(*args: Any, **kwargs: Any) -> str:
        mint_calls.append({"args": args, "kwargs": kwargs})
        return "bad"

    monkeypatch.setattr(internal_router, "mint_module_jwt", record_mint_call)

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

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_token"
    assert mint_calls == []
    assert app.state.mongo_db["audit_log"].documents == []


@pytest.mark.asyncio
async def test_issue_module_admin_token_requires_target_module_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import zeler_gateway.internal.router as internal_router
    from zeler_gateway.internal.router import router

    app = FastAPI()
    app.state.mongo_db = FakeAsyncDb()
    app.state.mongo_db["module_registry"].documents[0]["allowed_meli_scopes"].append("admin:repricer")
    app.state.mongo_db["module_registry"].documents.append(
        {"_id": "zeler-app", "status": "enabled", "allowed_meli_scopes": ["admin:repricer"]}
    )
    app.include_router(router)
    monkeypatch.setattr(
        internal_router,
        "verify_module_jwt",
        lambda token: FakeClaims(module_id="repricer"),
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


def test_admin_client_seed_contains_zeler_app_active_module_admin_scopes() -> None:
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
    monkeypatch.setenv("ZELER_APP_BROKER_SECRET", BROKER_SECRET)
    monkeypatch.setattr(
        internal_router,
        "mint_module_jwt",
        lambda module_id, seller_id, ttl_s, **_claims: f"jwt:{module_id}:{seller_id}:{ttl_s}",
    )
    body = _json_body(
        {
            "seller_id": 82453304,
            "scopes": ["admin:repricer"],
            "ttl_s": 120,
            "token_kind": "module_admin",
            "target_module_id": "repricer",
        }
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/internal/tokens/issue",
            content=body,
            headers=_broker_headers(body),
        )

    assert response.status_code == 200
    assert response.json()["access_token"] == "jwt:repricer:82453304:120"  # noqa: S105
    audit_doc = app.state.mongo_db["audit_log"].documents[0]
    assert "platform_user_id" not in audit_doc


@pytest.mark.asyncio
async def test_legacy_bearer_module_admin_rejects_platform_user_id_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import zeler_gateway.internal.router as internal_router
    from zeler_gateway.internal.router import router

    mint_calls: list[dict[str, Any]] = []

    def record_mint_call(*args: Any, **kwargs: Any) -> str:
        mint_calls.append({"args": args, "kwargs": kwargs})
        return "bad"

    app = FastAPI()
    app.state.mongo_db = FakeAsyncDb()
    app.state.mongo_db["module_registry"].documents.append(
        {"_id": "zeler-app", "status": "enabled", "allowed_meli_scopes": ["admin:repricer"]}
    )
    app.include_router(router)
    monkeypatch.setattr(
        internal_router,
        "verify_module_jwt",
        lambda token: FakeClaims(module_id="zeler-app", seller_id=82453304),
    )
    monkeypatch.setattr(internal_router, "mint_module_jwt", record_mint_call)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/internal/tokens/issue",
            headers={"Authorization": "Bearer zeler-app-gateway-token"},
            json={
                "seller_id": 82453304,
                "platform_user_id": "browser-controlled-user",
                "scopes": ["admin:repricer"],
                "ttl_s": 120,
                "token_kind": "module_admin",
                "target_module_id": "repricer",
            },
        )

    assert response.status_code == 403
    assert response.json() == {"error": "out_of_scope"}
    assert mint_calls == []
    assert app.state.mongo_db["audit_log"].documents == []


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
    monkeypatch.setenv("ZELER_APP_BROKER_SECRET", BROKER_SECRET)
    monkeypatch.setattr(
        internal_router,
        "mint_module_jwt",
        lambda module_id, seller_id, ttl_s, **_claims: f"jwt:{module_id}:{seller_id}:{ttl_s}",
    )
    body = _json_body(
        {
            "seller_id": 82453304,
            "scopes": ["admin:publicador"],
            "ttl_s": 120,
            "token_kind": "module_admin",
            "target_module_id": "publicador",
        }
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/internal/tokens/issue",
            content=body,
            headers=_broker_headers(body),
        )

    assert response.status_code == 200
    assert response.json()["access_token"] == "jwt:publicador:82453304:120"  # noqa: S105
