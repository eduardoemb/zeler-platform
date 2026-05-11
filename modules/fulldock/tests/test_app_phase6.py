from __future__ import annotations

from typing import Any

import httpx
import pytest


class FakeCollection:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}

    async def replace_one(
        self, filter_doc: dict[str, Any], replacement: dict[str, Any], *, upsert: bool
    ) -> None:
        assert upsert is True
        self.documents[filter_doc["_id"]] = replacement


class FakeDb:
    def __init__(self) -> None:
        self.module_registry = FakeCollection()

    def __getitem__(self, name: str) -> FakeCollection:
        assert name == "module_registry"
        return self.module_registry


def test_fulldock_manifest_validates_owned_collections_and_stock_location_scope() -> None:
    from zeler_platform_core.runtime.manifest import validate_manifest

    manifest = validate_manifest("modules/fulldock/manifest.yaml")

    assert manifest.name == "fulldock"
    assert manifest.routing_keys == ["shipments.*", "stock_locations.*"]
    assert manifest.owned_collections == ["fulldock_inventory_rules", "fulldock_history"]
    assert manifest.allowed_meli_scopes == [
        "GET /items/*",
        "GET /shipments/*",
        "GET /user-products/*/stock",
        "PUT /items/*/stock_locations",
    ]


@pytest.mark.asyncio
async def test_fulldock_startup_registers_manifest_and_health_ready() -> None:
    from zeler_fulldock.app import build_app

    db = FakeDb()
    app = build_app(mongo_db=db)
    for handler in app.router.on_startup:
        await handler()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")

    assert db.module_registry.documents["fulldock"] == {
        "_id": "fulldock",
        "version": "0.1.0",
        "allowed_meli_scopes": [
            "GET /items/*",
            "GET /shipments/*",
            "GET /user-products/*/stock",
            "PUT /items/*/stock_locations",
        ],
        "routing_keys": ["shipments.*", "stock_locations.*"],
        "owned_collections": ["fulldock_inventory_rules", "fulldock_history"],
        "health_endpoint": "/health",
        "status": "enabled",
        "schema_version": 1,
    }
    assert response.status_code == 200
    assert response.json() == {
        "module_id": "fulldock",
        "ready": True,
        "checks": {"mongo": {"ok": True, "detail": "connected"}},
    }
