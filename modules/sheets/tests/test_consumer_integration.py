from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from zeler_platform_core.clients.meli_gateway_client import MeliGatewayClient
from zeler_sheets import consumer


class FakeAuth:
    def __init__(self) -> None:
        self.seller_ids: list[int] = []

    async def get_token_for_seller(self, seller_id: int) -> str:
        self.seller_ids.append(seller_id)
        return f"jwt-for-{seller_id}"


class FakeCursor:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self._documents = documents

    async def to_list(self, *, length: int | None = None) -> list[dict[str, Any]]:
        return self._documents[:length]


class FakeCollection:
    def __init__(self, document: dict[str, Any] | None) -> None:
        self.documents = [document] if document is not None else []

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        for document in self.documents:
            if all(document.get(key) == value for key, value in query.items()):
                return document
        return None

    def find(self, query: dict[str, Any]) -> FakeCursor:
        return FakeCursor(
            [
                document
                for document in self.documents
                if all(document.get(key) == value for key, value in query.items())
            ]
        )

    async def replace_one(
        self, filter_spec: dict[str, Any], replacement: dict[str, Any], *, upsert: bool = False
    ) -> None:
        del filter_spec, upsert
        self.documents.append(dict(replacement))


class FakeDb:
    def __init__(self, document: dict[str, Any] | None) -> None:
        self.collections = {"sheets_exports": FakeCollection(document)}

    def __getitem__(self, name: str) -> FakeCollection:
        return self.collections.setdefault(name, FakeCollection(None))


class FakeSheetsClient:
    def __init__(self) -> None:
        self.rows: list[list[str]] = []

    async def append_row(self, **kwargs: Any) -> None:
        self.rows.append(kwargs["row"])


class FakeIdempotency:
    async def is_duplicate(self, key: str) -> bool:
        assert key == "idem-1"
        return False

    async def mark_processed(self, key: str) -> None:
        assert key == "idem-1"


@pytest.mark.asyncio
async def test_sheets_consumer_uses_unified_meli_gateway_client_end_to_end() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["Authorization"]
        return httpx.Response(
            200,
            json={
                "id": "MLM568624063",
                "title": "Hopemob case",
                "status": "active",
                "price": 199,
                "base_price": 199,
                "available_quantity": 7,
                "category_id": "MLM123",
                "attributes": [{"id": "SELLER_SKU", "value_name": "SKU-HOPE"}],
                "date_created": "2026-05-01T10:00:00Z",
                "last_updated": "2026-05-30T10:00:00Z",
            },
        )

    auth = FakeAuth()
    gateway_client = MeliGatewayClient(
        consumer.DEFAULT_GATEWAY_BASE_URL,
        auth,  # type: ignore[arg-type]
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    sheets_client = FakeSheetsClient()
    event_handler = consumer.SheetsEventHandler(
        db=FakeDb(
            {
                "seller_id": "82453304",
                "enabled": True,
                "spreadsheet_id": "sheet-1",
                "worksheet_name": "Hoja 1",
            }
        ),
        gateway_client=gateway_client,
        sheets_client=sheets_client,
        idempotency_store=FakeIdempotency(),
    )

    result = await event_handler.handle(
        consumer.SheetsEvent(
            event_id="evt-1",
            event_type="items.updated",
            seller_id=82453304,
            resource="/items/MLM568624063",
            idempotency_key="idem-1",
        )
    )

    assert result == "appended"
    assert captured == {
        "url": "http://gateway:8080/proxy/meli/items/MLM568624063",
        "authorization": "Bearer jwt-for-82453304",
    }
    assert auth.seller_ids == [82453304]
    assert sheets_client.rows == [
        ["items.updated", "MLM568624063", "Hopemob case", "active", "199", "7"]
    ]


def test_sheets_gateway_default_and_env_template_use_proxy_prefix() -> None:
    template = Path("infra/gce/env-templates/sheets-worker.env.template")
    content = template.read_text(encoding="utf-8")

    assert consumer.DEFAULT_GATEWAY_BASE_URL == "http://gateway:8080/proxy/meli"
    assert "GATEWAY_BASE_URL=http://gateway:8080/proxy/meli" in content
