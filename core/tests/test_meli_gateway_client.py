from __future__ import annotations

import json
from typing import Any, cast

import httpx
import pytest

from zeler_platform_core.clients.meli_gateway_client import MeliGatewayClient


class StubMeliGatewayAuth:
    def __init__(self, token: str) -> None:
        self.token = token
        self.requested_sellers: list[str] = []

    async def get_token_for_seller(self, seller_id: str) -> str:
        self.requested_sellers.append(seller_id)
        return self.token


@pytest.mark.asyncio
async def test_fetch_resource_gets_json_from_proxy_with_seller_jwt() -> None:
    seen_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return httpx.Response(200, json={"id": "MLM123", "status": "active"})

    auth = StubMeliGatewayAuth("jwt-for-seller")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = MeliGatewayClient(
            "http://gateway:8080/proxy/meli",
            auth,  # type: ignore[arg-type]
            http_client=http_client,
        )

        payload = await client.fetch_resource(seller_id="82453304", path="/items/MLM123")

    assert payload == {"id": "MLM123", "status": "active"}
    assert auth.requested_sellers == ["82453304"]
    assert len(seen_requests) == 1
    assert str(seen_requests[0].url) == "http://gateway:8080/proxy/meli/items/MLM123"
    assert seen_requests[0].headers["authorization"] == "Bearer jwt-for-seller"


@pytest.mark.asyncio
async def test_focused_fetch_disables_proxy_retry_and_requires_attempt_metadata() -> None:
    seen_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return httpx.Response(
            200,
            json={"id": "MLM123"},
            headers={"X-Zeler-Upstream-Attempts": "1"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = MeliGatewayClient(
            "http://gateway:8080/proxy/meli",
            StubMeliGatewayAuth("seller-jwt"),  # type: ignore[arg-type]
            http_client=http_client,
        )
        payload = await client.fetch_resource_once(seller_id="82453304", path="/items/MLM123")

    assert payload == {"id": "MLM123"}
    assert seen_requests[0].headers["x-zeler-proxy-retry"] == "disabled"


@pytest.mark.asyncio
async def test_focused_fetch_fails_closed_without_actual_attempt_metadata() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "MLM123"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = MeliGatewayClient(
            "http://gateway:8080/proxy/meli",
            StubMeliGatewayAuth("seller-jwt"),  # type: ignore[arg-type]
            http_client=http_client,
        )
        with pytest.raises(RuntimeError, match="attempt metadata"):
            await client.fetch_resource_once(seller_id="82453304", path="/items/MLM123")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("base_url", "path"),
    [
        ("http://gateway:8080/proxy/meli", "/items/MLM123"),
        ("http://gateway:8080/proxy/meli", "items/MLM123"),
        ("http://gateway:8080/proxy/meli/", "/items/MLM123"),
    ],
)
async def test_fetch_resource_normalizes_base_url_and_path_slashes(
    base_url: str,
    path: str,
) -> None:
    seen_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        return httpx.Response(200, json={"id": "MLM123"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = MeliGatewayClient(
            base_url,
            StubMeliGatewayAuth("seller-jwt"),  # type: ignore[arg-type]
            http_client=http_client,
        )

        payload = await client.fetch_resource(seller_id="82453304", path=path)

    assert payload == {"id": "MLM123"}
    assert seen_urls == ["http://gateway:8080/proxy/meli/items/MLM123"]


def test_init_fails_fast_when_base_url_misses_proxy_prefix() -> None:
    with pytest.raises(ValueError, match="/proxy/meli"):
        MeliGatewayClient(
            "http://gateway:8080",
            StubMeliGatewayAuth("seller-jwt"),  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_request_supports_post_with_json_body_and_seller_jwt() -> None:
    seen_requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return httpx.Response(201, json={"ok": True, "id": "reply-1"})

    auth = StubMeliGatewayAuth("jwt-for-autoreply")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = MeliGatewayClient(
            "http://gateway:8080/proxy/meli/",
            auth,  # type: ignore[arg-type]
            http_client=http_client,
        )

        response = await client.request(
            method="POST",
            seller_id="82453304",
            path="messages/123/replies",
            json={"text": "Hola"},
        )

    assert response.status_code == 201
    assert response.json() == {"ok": True, "id": "reply-1"}
    assert auth.requested_sellers == ["82453304"]
    assert len(seen_requests) == 1
    request = seen_requests[0]
    assert request.method == "POST"
    assert str(request.url) == "http://gateway:8080/proxy/meli/messages/123/replies"
    assert request.headers["authorization"] == "Bearer jwt-for-autoreply"
    assert json_body(request) == {"text": "Hola"}


def json_body(request: httpx.Request) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(request.content))
