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
        return self.document


class FakeDb(dict[str, FakeCollection]):
    def __getitem__(self, name: str) -> FakeCollection:
        return super().__getitem__(name)


@pytest.mark.asyncio
async def test_proxy_returns_423_for_paused_account() -> None:
    response = await _request_with_paused_account()

    assert response.status_code == 423
    assert response.json() == {"code": "seller_paused"}


@pytest.mark.asyncio
async def test_proxy_does_not_call_meli_for_paused_account() -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.get("https://api.mercadolibre.com/items/MLA123").mock(
            return_value=httpx.Response(200, json={"id": "MLA123"})
        )

        response = await _request_with_paused_account()

    assert response.status_code == 423
    assert route.calls.call_count == 0


async def _request_with_paused_account() -> httpx.Response:
    set_kms_client(FakeJwtKmsClient())
    test_app = FastAPI()
    test_app.state.mongo_db = FakeDb(
        {
            "module_registry": FakeCollection(
                {
                    "_id": "repricer",
                    "status": "enabled",
                    "allowed_meli_scopes": ["GET /items/*"],
                }
            ),
            "meli_accounts": FakeCollection({"seller_id": 123456789, "status": "paused"}),
        }
    )
    test_app.include_router(proxy_router)
    transport = httpx.ASGITransport(app=test_app)
    token = mint_module_jwt("repricer", seller_id=123456789)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/items/MLA123", headers={"Authorization": f"Bearer {token}"})
    set_kms_client(None)
    return response
