from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from zeler_autoreply import consumer


class FakeAuth:
    def __init__(self) -> None:
        self.seller_ids: list[int] = []

    async def get_token_for_seller(self, seller_id: int) -> str:
        self.seller_ids.append(seller_id)
        return f"jwt-for-{seller_id}"


@pytest.mark.asyncio
async def test_autoreply_gateway_adapter_uses_unified_request_for_get_and_post() -> None:
    calls: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(
            {
                "method": request.method,
                "url": str(request.url),
                "authorization": request.headers["Authorization"],
                "body": request.read().decode(),
            }
        )
        return httpx.Response(200, json={"id": "question-1", "text": "hola"})

    auth = FakeAuth()
    gateway_client = consumer.AutoreplyMeliGatewayClient(
        base_url=consumer.DEFAULT_GATEWAY_BASE_URL,
        auth=auth,  # type: ignore[arg-type]
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    resource = await gateway_client.request(
        "GET", "/questions/question-1", seller_id="82453304", json=None
    )
    answer = await gateway_client.request(
        "POST", "/answers", seller_id="82453304", json={"text": "hola"}
    )

    assert resource == {"id": "question-1", "text": "hola"}
    assert answer == {"id": "question-1", "text": "hola"}
    assert calls == [
        {
            "method": "GET",
            "url": "http://gateway:8080/proxy/meli/questions/question-1",
            "authorization": "Bearer jwt-for-82453304",
            "body": "",
        },
        {
            "method": "POST",
            "url": "http://gateway:8080/proxy/meli/answers",
            "authorization": "Bearer jwt-for-82453304",
            "body": '{"text":"hola"}',
        },
    ]
    assert auth.seller_ids == [82453304, 82453304]


def test_autoreply_gateway_default_and_env_template_use_proxy_prefix() -> None:
    template = Path("infra/gce/env-templates/autoreply-worker.env.template")
    content = template.read_text(encoding="utf-8")

    assert consumer.DEFAULT_GATEWAY_BASE_URL == "http://gateway:8080/proxy/meli"
    assert "GATEWAY_BASE_URL=http://gateway:8080/proxy/meli" in content
