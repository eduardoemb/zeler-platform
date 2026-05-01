from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI
from gateway.tests.test_proxy_flow import FakeJwtKmsClient

from zeler_gateway.proxy.router import router as proxy_router
from zeler_platform_core.auth.jwt import mint_module_jwt, set_kms_client


class FakeCollection:
    def __init__(self, document: dict[str, Any] | None) -> None:
        self.document = document

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        if self.document is None:
            return None
        if query.get("_id") is not None and self.document.get("_id") != query["_id"]:
            return None
        return self.document

    async def insert_one(self, doc: dict[str, Any]) -> None:
        self.document = doc

    async def find_one_and_update(
        self, query: dict[str, Any], update: Any, **_kwargs: Any
    ) -> dict[str, Any]:
        self.document = {"_id": query["_id"], "count": 1}
        return self.document


class FakeDb(dict[str, FakeCollection]):
    def __getitem__(self, name: str) -> FakeCollection:
        return super().__getitem__(name)


@pytest.mark.asyncio
async def test_disabled_module_returns_412_with_code_module_disabled() -> None:
    response = await _request_with_module({"_id": "repricer", "status": "disabled"})

    assert response.status_code == 412
    assert response.json() == {"code": "module_disabled", "detail": "module repricer is disabled"}


@pytest.mark.asyncio
async def test_unknown_module_returns_401() -> None:
    response = await _request_with_module(None)

    assert response.status_code == 401
    assert response.json()["error"] == "unknown_module"


@pytest.mark.asyncio
async def test_enabled_module_proceeds_normally(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_decrypt_token(*_args: Any, **_kwargs: Any) -> str:
        return "meli-token"

    monkeypatch.setattr("zeler_gateway.proxy.router.decrypt_token", fake_decrypt_token)
    with respx.mock(assert_all_called=True) as respx_mock:
        respx_mock.get("https://api.mercadolibre.com/items/MLA123").mock(
            return_value=httpx.Response(200, json={"id": "MLA123"})
        )
        response = await _request_with_module(
            {"_id": "repricer", "status": "enabled", "allowed_meli_scopes": ["GET /items/*"]},
            account={
                "seller_id": 123456789,
                "status": "active",
                "access_token_ciphertext": b"c",
                "token_nonce": b"n",
                "access_token_dek_wrapped": b"d",
                "kms_key_version": "k",
            },
        )

    assert response.status_code == 200
    assert response.json() == {"id": "MLA123"}


async def _request_with_module(
    module_doc: dict[str, Any] | None,
    *,
    account: dict[str, Any] | None = None,
) -> httpx.Response:
    set_kms_client(FakeJwtKmsClient())
    test_app = FastAPI()
    test_app.state.mongo_db = FakeDb(
        {
            "module_registry": FakeCollection(module_doc),
            "meli_accounts": FakeCollection(
                account or {"seller_id": 123456789, "status": "active"}
            ),
            "audit_log": FakeCollection(None),
            "rate_limit_counters": FakeCollection(None),
        }
    )
    test_app.include_router(proxy_router)
    transport = httpx.ASGITransport(app=test_app)
    token = mint_module_jwt("repricer", seller_id=123456789)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/items/MLA123", headers={"Authorization": f"Bearer {token}"})
    set_kms_client(None)
    return response
