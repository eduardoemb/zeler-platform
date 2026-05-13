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


def test_autoreply_manifest_validates_events_collections_and_scopes() -> None:
    from zeler_platform_core.runtime.manifest import validate_manifest

    manifest = validate_manifest("modules/autoreply/manifest.yaml")

    assert manifest.name == "autoreply"
    assert manifest.routing_keys == ["questions.new", "messages.new"]
    assert manifest.owned_collections == ["autoreply_templates", "autoreply_history"]
    assert manifest.allowed_meli_scopes == [
        "POST /answers",
        "GET /questions/*",
        "GET /messages/*",
    ]


@pytest.mark.asyncio
async def test_autoreply_startup_registers_manifest_and_health_ready() -> None:
    from zeler_autoreply.app import build_app

    db = FakeDb()
    app = build_app(mongo_db=db)
    for handler in app.router.on_startup:
        await handler()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")

    assert db.module_registry.documents["autoreply"] == {
        "_id": "autoreply",
        "version": "0.1.0",
        "allowed_meli_scopes": [
            "POST /answers",
            "GET /questions/*",
            "GET /messages/*",
        ],
        "routing_keys": ["questions.new", "messages.new"],
        "owned_collections": ["autoreply_templates", "autoreply_history"],
        "health_endpoint": "/health",
        "status": "enabled",
        "schema_version": 1,
    }
    assert response.status_code == 200
    assert response.json() == {
        "module_id": "autoreply",
        "ready": True,
        "checks": {"mongo": {"ok": True, "detail": "connected"}},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("GET", "/autoreply/templates?seller_id=123456789", None),
        (
            "POST",
            "/autoreply/templates/preview",
            {
                "match_type": "keyword",
                "pattern": "envio",
                "answer_text": "Hola",
                "sample_text": "Tienen envio?",
            },
        ),
    ],
)
async def test_autoreply_app_mounts_api_routes(
    method: str, path: str, json_body: dict[str, str] | None
) -> None:
    from zeler_autoreply.app import build_app

    app = build_app(mongo_db=FakeDb())

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.request(method, path, json=json_body)

    assert response.status_code == 401
    assert response.json() == {"error": "invalid_token", "detail": "missing bearer token"}
