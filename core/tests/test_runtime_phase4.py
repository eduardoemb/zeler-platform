from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from zeler_platform_core.runtime.health import HealthCheck, build_health_router
from zeler_platform_core.runtime.manifest import (
    ManifestConflictError,
    ModuleManifest,
    validate_manifest,
)
from zeler_platform_core.runtime.registration import register_module


class FakeAsyncCollection:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}

    async def replace_one(
        self, filter_doc: dict[str, Any], replacement: dict[str, Any], *, upsert: bool
    ) -> None:
        assert upsert is True
        self.documents[filter_doc["_id"]] = replacement


class FakeAsyncDb:
    def __init__(self) -> None:
        self.module_registry = FakeAsyncCollection()

    def __getitem__(self, name: str) -> FakeAsyncCollection:
        assert name == "module_registry"
        return self.module_registry


def test_valid_manifest_loads(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(
        """
name: repricer
version: 0.1.0
subscribed_events:
  - items.*
  - items.price_updated
owned_collections:
  - repricer_rules
  - repricer_history
allowed_meli_scopes:
  - PUT /items/*
  - GET /items/*
health_endpoint: /health
""".strip(),
        encoding="utf-8",
    )

    manifest = validate_manifest(manifest_path)

    assert manifest.name == "repricer"
    assert manifest.allowed_meli_scopes == ["PUT /items/*", "GET /items/*"]
    assert manifest.routing_keys == ["items.*", "items.price_updated"]


def test_manifest_missing_allowed_meli_scopes_raises(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(
        """
name: repricer
version: 0.1.0
subscribed_events:
  - items.*
owned_collections:
  - repricer_rules
health_endpoint: /health
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="allowed_meli_scopes"):
        validate_manifest(manifest_path)


def test_manifest_rejects_gateway_owned_collection() -> None:
    with pytest.raises(ManifestConflictError, match="items"):
        ModuleManifest(
            name="repricer",
            version="0.1.0",
            subscribed_events=["items.*"],
            owned_collections=["repricer_rules", "items"],
            allowed_meli_scopes=["GET /items/*"],
            health_endpoint="/health",
        )


@pytest.mark.asyncio
async def test_registration_upserts_module_registry_doc() -> None:
    db = FakeAsyncDb()
    manifest = ModuleManifest(
        name="repricer",
        version="0.1.0",
        subscribed_events=["items.*", "items.price_updated"],
        owned_collections=["repricer_rules", "repricer_history"],
        allowed_meli_scopes=["PUT /items/*", "GET /items/*"],
        health_endpoint="/health",
    )

    await register_module(manifest, db)

    assert db.module_registry.documents["repricer"] == {
        "_id": "repricer",
        "version": "0.1.0",
        "allowed_meli_scopes": ["PUT /items/*", "GET /items/*"],
        "routing_keys": ["items.*", "items.price_updated"],
        "owned_collections": ["repricer_rules", "repricer_history"],
        "health_endpoint": "/health",
        "status": "enabled",
        "schema_version": 1,
    }


@pytest.mark.asyncio
async def test_health_ready_false_when_consumer_stalled() -> None:
    app = FastAPI()

    async def ok_check() -> tuple[bool, str]:
        return True, "connected"

    async def stalled_check() -> tuple[bool, str]:
        return False, "consumer_stalled"

    app.include_router(
        build_health_router(
            "repricer",
            checks=[
                HealthCheck(name="mongo", check=ok_check),
                HealthCheck(name="rabbitmq", check=stalled_check),
            ],
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "module_id": "repricer",
        "ready": False,
        "checks": {
            "mongo": {"ok": True, "detail": "connected"},
            "rabbitmq": {"ok": False, "detail": "consumer_stalled"},
        },
    }
