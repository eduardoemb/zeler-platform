from __future__ import annotations

import httpx
import pytest

from zeler_platform_core.clients.meli_gateway_client import (
    GatewayRateLimitError,
    MeliGatewayClient,
)


class StubMeliGatewayAuth:
    def __init__(self, token: str) -> None:
        self.token = token

    async def get_token_for_seller(self, seller_id: str) -> str:
        return self.token


def make_client(status_code: int) -> MeliGatewayClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            json={"status": status_code},
            headers={"Retry-After": "7"},
            request=request,
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return MeliGatewayClient(
        "http://gateway:8080/proxy/meli",
        StubMeliGatewayAuth("seller-jwt"),  # type: ignore[arg-type]
        http_client=http_client,
    )


@pytest.mark.asyncio
async def test_request_raises_gateway_rate_limit_error_for_429() -> None:
    client = make_client(429)

    with pytest.raises(GatewayRateLimitError) as exc_info:
        await client.request(method="GET", seller_id="82453304", path="items/MLM123")

    assert exc_info.value.retry_after_seconds == 7
    assert exc_info.value.response.status_code == 429
    assert isinstance(exc_info.value.response, httpx.Response)


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [403, 404, 500, 503])
async def test_request_preserves_http_status_error_for_non_429_errors(
    status_code: int,
) -> None:
    client = make_client(status_code)

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await client.request(method="GET", seller_id="82453304", path="items/MLM123")

    assert exc_info.value.response.status_code == status_code


@pytest.mark.asyncio
async def test_request_returns_successful_response_without_raising() -> None:
    client = make_client(200)

    response = await client.request(
        method="GET",
        seller_id="82453304",
        path="items/MLM123",
    )

    assert response.status_code == 200
    assert response.json() == {"status": 200}
