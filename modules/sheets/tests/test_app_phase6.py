from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi.routing import APIRoute


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


def test_sheets_manifest_validates_owned_collections_and_readonly_scopes() -> None:
    from zeler_platform_core.runtime.manifest import validate_manifest

    manifest = validate_manifest("modules/sheets/manifest.yaml")

    assert manifest.name == "sheets"
    assert manifest.routing_keys == ["items.*", "orders.*", "shipments.*"]
    assert manifest.owned_collections == [
        "sheets_exports",
        "sheets_sync_jobs",
        "google_oauth_tokens",
    ]
    assert manifest.allowed_meli_scopes == [
        "GET /items",
        "GET /items/*",
        "GET /orders/*",
        "GET /shipments/*",
    ]
    assert manifest.display_identity.display_name == "ZelerData"


def test_sheets_app_includes_google_oauth_routes() -> None:
    from zeler_sheets.app import build_app

    app = build_app(mongo_db=FakeDb(), rabbitmq_ready=lambda: True)

    route_paths = {route.path for route in app.routes if isinstance(route, APIRoute)}
    assert "/oauth/google/authorize" in route_paths
    assert "/oauth/google/callback" in route_paths


@pytest.mark.asyncio
async def test_sheets_startup_registers_manifest_and_health_ready() -> None:
    from zeler_sheets.app import build_app

    db = FakeDb()
    app = build_app(mongo_db=db, rabbitmq_ready=lambda: True)
    for handler in app.router.on_startup:
        await handler()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")

    assert db.module_registry.documents["sheets"] == {
        "_id": "sheets",
        "version": "0.1.0",
        "allowed_meli_scopes": [
            "GET /items",
            "GET /items/*",
            "GET /orders/*",
            "GET /shipments/*",
        ],
        "routing_keys": ["items.*", "orders.*", "shipments.*"],
        "owned_collections": ["sheets_exports", "sheets_sync_jobs", "google_oauth_tokens"],
        "health_endpoint": "/health",
        "display_identity": {
            "display_name": "ZelerData",
            "legacy_display_name": "SheetsellerApp",
            "availability": "active",
        },
        "status": "enabled",
        "schema_version": 1,
    }
    assert response.status_code == 200
    assert response.json() == {
        "module_id": "sheets",
        "ready": True,
        "checks": {
            "mongo": {"ok": True, "detail": "connected"},
            "rabbitmq": {"ok": True, "detail": "connected"},
        },
    }
