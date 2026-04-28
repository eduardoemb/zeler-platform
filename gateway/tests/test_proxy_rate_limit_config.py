from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from starlette.requests import Request

from zeler_gateway.config import Settings
from zeler_gateway.proxy import router as proxy_router
from zeler_gateway.proxy.rate_limit import DEFAULT_RATE_LIMIT, RateLimitExceeded


def test_settings_default_proxy_rate_limit_is_600(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GATEWAY_PROXY_RATE_LIMIT", raising=False)

    settings = Settings()

    assert settings.gateway_proxy_rate_limit == 600


def test_rate_limit_counter_default_constant_matches_settings_default() -> None:
    assert DEFAULT_RATE_LIMIT == 600


def test_settings_proxy_rate_limit_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GATEWAY_PROXY_RATE_LIMIT", "100")

    settings = Settings()

    assert settings.gateway_proxy_rate_limit == 100


@pytest.mark.asyncio
async def test_proxy_uses_settings_proxy_rate_limit_for_counter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_limits: list[int] = []

    class FakeRateLimitCounter:
        def __init__(self, db: Any, *, default_limit: int) -> None:
            self._db = db
            captured_limits.append(default_limit)

        async def check_and_increment(self, *, module_id: str, seller_id: int) -> None:
            raise RateLimitExceeded(retry_after_s=10)

    monkeypatch.setenv("GATEWAY_PROXY_RATE_LIMIT", "100")
    monkeypatch.setattr(
        proxy_router,
        "verify_module_jwt",
        lambda token: SimpleNamespace(module_id="repricer", seller_id=123456789),
    )
    monkeypatch.setattr(proxy_router, "RateLimitCounter", FakeRateLimitCounter)

    request = _request_with_db(_FakeProxyDb())

    response = await proxy_router.proxy_meli(request, "items/MLM1")

    assert response.status_code == 429
    assert captured_limits == [100]


class _FakeProxyDb:
    def __getitem__(self, collection_name: str) -> _FakeCollection:
        return _FakeCollection(collection_name)


class _FakeCollection:
    def __init__(self, collection_name: str) -> None:
        self._collection_name = collection_name

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        if self._collection_name == "module_registry":
            return {
                "_id": query["_id"],
                "status": "enabled",
                "allowed_meli_scopes": ["GET /items/*"],
            }
        if self._collection_name == "meli_accounts":
            return {"seller_id": query["seller_id"], "status": "active"}
        return None


def _request_with_db(db: Any) -> Request:
    app = FastAPI()
    app.state.mongo_db = db
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/proxy/meli/items/MLM1",
            "headers": [(b"authorization", b"Bearer test-token")],
            "query_string": b"",
            "app": app,
        }
    )
