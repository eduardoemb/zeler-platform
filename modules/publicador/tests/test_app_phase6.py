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


def test_publicador_manifest_validates_owned_collections_and_write_scopes() -> None:
    from zeler_platform_core.runtime.manifest import validate_manifest

    manifest = validate_manifest("modules/publicador/manifest.yaml")

    assert manifest.name == "publicador"
    assert manifest.routing_keys == []
    assert manifest.owned_collections == ["publicador_drafts", "publicador_history"]
    assert manifest.allowed_meli_scopes == [
        "POST /items",
        "PUT /items/*",
        "GET /categories/*",
        "POST /items/validate",
    ]


@pytest.mark.asyncio
async def test_publicador_startup_registers_manifest_and_health_ready() -> None:
    from zeler_publicador.app import build_app

    db = FakeDb()
    app = build_app(mongo_db=db)
    for handler in app.router.on_startup:
        await handler()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")

    assert db.module_registry.documents["publicador"] == {
        "_id": "publicador",
        "version": "0.1.0",
        "allowed_meli_scopes": [
            "POST /items",
            "PUT /items/*",
            "GET /categories/*",
            "POST /items/validate",
        ],
        "routing_keys": [],
        "owned_collections": ["publicador_drafts", "publicador_history"],
        "health_endpoint": "/health",
        "status": "enabled",
        "schema_version": 1,
    }
    assert response.status_code == 200
    assert response.json() == {
        "module_id": "publicador",
        "ready": True,
        "checks": {"mongo": {"ok": True, "detail": "connected"}},
    }
