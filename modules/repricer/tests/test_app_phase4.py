from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest

TEST_RABBITMQ_URL = "amqp://guest:guest@broker:5672/"


class FakeRabbitConnection:
    def __init__(self, *, is_open: bool = True) -> None:
        self.is_open = is_open

    async def close(self) -> None:
        return None


def _connect_ok() -> Callable[..., Awaitable[FakeRabbitConnection]]:
    async def connect(*_args: Any, **_kwargs: Any) -> FakeRabbitConnection:
        return FakeRabbitConnection(is_open=True)

    return connect


class FakeCollection:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}

    async def replace_one(
        self, filter_doc: dict[str, Any], replacement: dict[str, Any], *, upsert: bool
    ) -> None:
        assert upsert is True
        self.documents[filter_doc["_id"]] = replacement

    async def find_one(self, filter_doc: dict[str, Any]) -> dict[str, Any] | None:
        document = self.documents.get(filter_doc["_id"])
        return dict(document) if document is not None else None


class FakeDb:
    def __init__(self) -> None:
        self.module_registry = FakeCollection()

    def __getitem__(self, name: str) -> FakeCollection:
        assert name == "module_registry"
        return self.module_registry


@pytest.mark.asyncio
async def test_repricer_startup_registers_manifest_and_health_ready() -> None:
    from zeler_repricer.app import build_app

    db = FakeDb()
    app = build_app(
        mongo_db=db,
        rabbitmq_url=TEST_RABBITMQ_URL,
        rabbitmq_connect=_connect_ok(),
    )
    for handler in app.router.on_startup:
        await handler()

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/health")
    finally:
        for handler in app.router.on_shutdown:
            await handler()

    assert db.module_registry.documents["repricer"] == {
        "_id": "repricer",
        "version": "0.1.0",
        "allowed_meli_scopes": ["PUT /items/*", "GET /items/*", "GET /items/*/prices"],
        "routing_keys": [
            "items.*",
            "items.price_updated",
            "price_suggestion.*",
            "repricer.sweep.requested",
        ],
        "owned_collections": ["repricer_rules", "repricer_history"],
        "health_endpoint": "/health",
        "display_identity": {
            "display_name": "ZelerPricing",
            "legacy_display_name": "EasyReprice",
            "availability": "active",
        },
        "status": "enabled",
        "schema_version": 1,
    }
    assert response.status_code == 200
    assert response.json()["ready"] is True
