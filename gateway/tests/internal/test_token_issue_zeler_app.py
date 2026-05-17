from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Generator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from fastapi import FastAPI

from zeler_platform_core.auth.jwt import reset_jwt_cache, set_kms_client, verify_module_jwt

BROKER_SECRET = "test-zeler-app-broker-secret"  # noqa: S105 - test fixture only
PILOT_SELLER_ID = 82453304


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
    def __init__(self, *, zeler_app_doc: dict[str, Any] | None = None) -> None:
        self.collections = {
            "module_registry": FakeAsyncCollection(
                [
                    zeler_app_doc
                    or {
                        "_id": "zeler-app",
                        "status": "enabled",
                        "allowed_seller_ids": [PILOT_SELLER_ID],
                        "allowed_meli_scopes": [
                            "admin:repricer",
                            "admin:sheets",
                            "admin:publicador",
                            "admin:autoreply",
                        ],
                    }
                ]
            ),
            "meli_accounts": FakeAsyncCollection(),
            "audit_log": FakeAsyncCollection(),
        }

    def __getitem__(self, name: str) -> FakeAsyncCollection:
        return self.collections[name]


class FakeKmsSignResponse:
    def __init__(self, signature: bytes) -> None:
        self.signature = signature


class FakeKmsPublicKeyResponse:
    def __init__(self, pem: str) -> None:
        self.pem = pem


class FakeKmsSigningClient:
    def __init__(self) -> None:
        self.private_key = ec.generate_private_key(ec.SECP256R1())

    def asymmetric_sign(self, request: dict[str, Any]) -> FakeKmsSignResponse:
        signature = self.private_key.sign(
            request["digest"]["sha256"],
            ec.ECDSA(utils.Prehashed(hashes.SHA256())),
        )
        return FakeKmsSignResponse(signature)

    def get_public_key(self, request: dict[str, str]) -> FakeKmsPublicKeyResponse:
        pem = self.private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return FakeKmsPublicKeyResponse(pem.decode("ascii"))


@dataclass(frozen=True)
class CapturedMint:
    calls: list[dict[str, Any]]


@pytest.fixture(autouse=True)
def fake_kms(monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    set_kms_client(FakeKmsSigningClient())
    reset_jwt_cache()
    monkeypatch.setenv("ZELER_APP_BROKER_SECRET", BROKER_SECRET)
    yield
    set_kms_client(None)
    reset_jwt_cache()


@pytest.mark.asyncio
async def test_zeler_app_broker_auth_issues_module_admin_jwt_with_expected_claims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import zeler_gateway.internal.router as internal_router
    from zeler_gateway.internal.router import router

    def reject_legacy_bearer(_token: str) -> object:
        raise AssertionError("zeler-app broker auth must not verify a legacy bearer JWT")

    monkeypatch.setattr(internal_router, "verify_module_jwt", reject_legacy_bearer)

    app = FastAPI()
    app.state.mongo_db = FakeAsyncDb()
    app.include_router(router)
    body = _json_body(
        {
            "seller_id": PILOT_SELLER_ID,
            "scopes": ["admin:repricer"],
            "ttl_s": 300,
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
    assert response.json()["expires_in"] == 300
    assert response.json()["scopes"] == ["admin:repricer"]
    claims = verify_module_jwt(response.json()["access_token"])
    assert claims.module_id == "repricer"
    assert claims.seller_id == PILOT_SELLER_ID
    assert claims.token_type == "module_admin"  # noqa: S105 - token type enum value.
    assert claims.scopes == ["admin:repricer"]
    assert claims.issued_by == "zeler-app"
    assert claims.exp - claims.iat <= 300
    audit_doc = app.state.mongo_db["audit_log"].documents[0]
    assert audit_doc["module_id"] == "zeler-app"
    assert audit_doc["target_module_id"] == "repricer"


@pytest.mark.asyncio
async def test_zeler_app_broker_auth_rejects_unregistered_seller_without_minting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import zeler_gateway.internal.router as internal_router
    from zeler_gateway.internal.router import router

    mint_calls: list[dict[str, Any]] = []
    def record_mint_call(*args: Any, **kwargs: Any) -> str:
        mint_calls.append({"args": args, "kwargs": kwargs})
        return "bad"

    monkeypatch.setattr(
        internal_router,
        "mint_module_jwt",
        record_mint_call,
    )
    app = FastAPI()
    app.state.mongo_db = FakeAsyncDb()
    app.include_router(router)
    body = _json_body(
        {
            "seller_id": 99999999,
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

    assert response.status_code == 403
    assert response.json() == {"error": "seller_mismatch"}
    assert mint_calls == []
    assert app.state.mongo_db["audit_log"].documents == []


@pytest.mark.asyncio
async def test_zeler_app_broker_auth_rejects_out_of_scope_module_without_minting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import zeler_gateway.internal.router as internal_router
    from zeler_gateway.internal.router import router

    mint_calls: list[dict[str, Any]] = []
    def record_mint_call(*args: Any, **kwargs: Any) -> str:
        mint_calls.append({"args": args, "kwargs": kwargs})
        return "bad"

    monkeypatch.setattr(
        internal_router,
        "mint_module_jwt",
        record_mint_call,
    )
    app = FastAPI()
    app.state.mongo_db = FakeAsyncDb()
    app.include_router(router)
    body = _json_body(
        {
            "seller_id": PILOT_SELLER_ID,
            "scopes": ["admin:orders"],
            "ttl_s": 120,
            "token_kind": "module_admin",
            "target_module_id": "orders",
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

    assert response.status_code == 403
    assert response.json() == {"error": "out_of_scope"}
    assert mint_calls == []
    assert app.state.mongo_db["audit_log"].documents == []


@pytest.mark.asyncio
async def test_zeler_app_broker_auth_rejects_ttl_above_300() -> None:
    from zeler_gateway.internal.router import router

    app = FastAPI()
    app.state.mongo_db = FakeAsyncDb()
    app.include_router(router)
    body = _json_body(
        {
            "seller_id": PILOT_SELLER_ID,
            "scopes": ["admin:repricer"],
            "ttl_s": 301,
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

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "ttl_s"]


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
