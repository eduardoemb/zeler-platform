from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest
from fastapi.routing import APIRoute

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
        document = self.documents.get(str(filter_doc["_id"]))
        return dict(document) if document is not None else None


class FakeDb:
    def __init__(self) -> None:
        self.module_registry = FakeCollection()

    def __getitem__(self, name: str) -> FakeCollection:
        assert name == "module_registry"
        return self.module_registry


def test_sheets_manifest_validates_owned_collections_and_readonly_scopes() -> None:
    from zeler_gateway.proxy.router import _scope_matches
    from zeler_platform_core.runtime.manifest import validate_manifest

    manifest = validate_manifest("modules/sheets/manifest.yaml")

    assert manifest.name == "sheets"
    assert manifest.routing_keys == [
        "items.*",
        "orders.*",
        "shipments.*",
        "questions.*",
        "claims.updated",
    ]
    assert manifest.owned_collections == [
        "sheets_exports",
        "sheets_sync_jobs",
        "google_oauth_tokens",
        "seller_unit_costs",
    ]
    assert manifest.allowed_meli_scopes == [
        "GET /items",
        "GET /items/*",
        "GET /products/*",
        "GET /sites/*/listing_prices",
        "GET /users/*/shipping_options/free",
        "GET /orders/*",
        "GET /post-purchase/v1/claims/search",
        "GET /post-purchase/v1/claims/*",
        "GET /post-purchase/v2/claims/*/returns",
        "GET /shipments/*",
        "GET /questions/*",
    ]
    assert _scope_matches(
        method="GET", path="/products/CAT-PII-1", allowed_scopes=manifest.allowed_meli_scopes
    )
    assert _scope_matches(
        method="GET",
        path="/products/CAT-PII-1/items",
        allowed_scopes=manifest.allowed_meli_scopes,
    )
    assert _scope_matches(
        method="GET", path="/shipments/3001/costs", allowed_scopes=manifest.allowed_meli_scopes
    )
    assert manifest.display_identity.display_name == "ZelerData"


def test_sheets_app_includes_google_oauth_routes() -> None:
    from zeler_sheets.app import build_app

    app = build_app(
        mongo_db=FakeDb(), rabbitmq_url=TEST_RABBITMQ_URL, rabbitmq_connect=_connect_ok()
    )

    route_paths = {route.path for route in app.routes if isinstance(route, APIRoute)}
    assert "/oauth/google/authorize" in route_paths
    assert "/oauth/google/callback" in route_paths


@pytest.mark.asyncio
async def test_sheets_startup_registers_manifest_and_health_ready() -> None:
    from zeler_sheets.app import build_app

    db = FakeDb()
    app = build_app(
        mongo_db=db, rabbitmq_url=TEST_RABBITMQ_URL, rabbitmq_connect=_connect_ok()
    )
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
            "GET /products/*",
            "GET /sites/*/listing_prices",
            "GET /users/*/shipping_options/free",
            "GET /orders/*",
            "GET /post-purchase/v1/claims/search",
            "GET /post-purchase/v1/claims/*",
            "GET /post-purchase/v2/claims/*/returns",
            "GET /shipments/*",
            "GET /questions/*",
        ],
        "routing_keys": [
            "items.*",
            "orders.*",
            "shipments.*",
            "questions.*",
            "claims.updated",
        ],
        "owned_collections": [
            "sheets_exports",
            "sheets_sync_jobs",
            "google_oauth_tokens",
            "seller_unit_costs",
        ],
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
            "rabbitmq": {"ok": True, "detail": "rabbitmq_ok"},
            "registry": {"ok": True, "detail": "registry_fingerprint_match"},
        },
    }


@pytest.mark.asyncio
async def test_sheets_health_fails_closed_when_registry_fingerprint_drifts() -> None:
    from zeler_sheets.app import build_app

    db = FakeDb()
    app = build_app(
        mongo_db=db, rabbitmq_url=TEST_RABBITMQ_URL, rabbitmq_connect=_connect_ok()
    )
    for handler in app.router.on_startup:
        await handler()
    db.module_registry.documents["sheets"]["routing_keys"] = ["items.*"]

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 503
    assert response.json()["checks"]["registry"] == {
        "ok": False,
        "detail": "registry_fingerprint_mismatch",
    }
