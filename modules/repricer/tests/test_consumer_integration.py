from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

from zeler_repricer import consumer


class FakeAuth:
    def __init__(self) -> None:
        self.seller_ids: list[int] = []

    async def get_token_for_seller(self, seller_id: int) -> str:
        self.seller_ids.append(seller_id)
        return f"jwt-for-{seller_id}"


@pytest.mark.asyncio
async def test_repricer_consumer_price_client_uses_unified_meli_gateway_client() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["Authorization"]
        captured["json"] = request.read().decode()
        return httpx.Response(202, json={"accepted": True})

    auth = FakeAuth()
    gateway_client = consumer.RepricerMeliGatewayPriceClient(
        base_url=consumer.DEFAULT_GATEWAY_BASE_URL,
        auth=auth,  # type: ignore[arg-type]
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        clock=lambda: 100.0,
    )

    status, latency_ms = await gateway_client.update_price(
        seller_id=82453304,
        item_id="MLM568624063",
        new_price=Decimal("123.45"),
        idempotency_key="idem-1",
    )

    assert status == 202
    assert latency_ms == 0
    assert captured == {
        "method": "POST",
        "url": "http://gateway:8080/proxy/meli/items/MLM568624063/prices",
        "authorization": "Bearer jwt-for-82453304",
        "json": '{"price":"123.45"}',
    }
    assert auth.seller_ids == [82453304]


def test_repricer_gateway_default_and_env_template_use_proxy_prefix() -> None:
    template = Path("infra/gce/env-templates/repricer-worker.env.template")
    content = template.read_text(encoding="utf-8")

    assert consumer.DEFAULT_GATEWAY_BASE_URL == "http://gateway:8080/proxy/meli"
    assert "GATEWAY_BASE_URL=http://gateway:8080/proxy/meli" in content
