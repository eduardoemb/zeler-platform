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
    assert manifest.display_identity.display_name == "ZelerPricing"
    assert manifest.display_identity.legacy_display_name == "EasyReprice"
    assert manifest.display_identity.availability == "active"


def test_active_and_retired_module_display_identities_are_canonical() -> None:
    from zeler_platform_core.runtime.module_identity import (
        active_module_display_identities,
        resolve_module_display_identity,
        retired_module_display_identities,
    )

    active_identities = active_module_display_identities()

    assert {
        module_id: identity.display_name for module_id, identity in active_identities.items()
    } == {
        "sheets": "ZelerData",
        "repricer": "ZelerPricing",
        "publicador": "ZelerListings",
        "autoreply": "ZelerSupport",
    }
    assert {
        module_id: identity.legacy_display_name for module_id, identity in active_identities.items()
    } == {
        "sheets": "SheetsellerApp",
        "repricer": "EasyReprice",
        "publicador": "Autopubli",
        "autoreply": "AutoReply",
    }
    assert all(identity.availability == "active" for identity in active_identities.values())

    retired_identity = retired_module_display_identities()["fulldock"]
    resolved_retired_identity = resolve_module_display_identity("fulldock")

    assert retired_identity.display_name == "ZelerStock"
    assert retired_identity.availability == "retired"
    assert resolved_retired_identity is not None
    assert resolved_retired_identity.availability == "retired"


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


def test_manifest_validation_rejects_active_module_without_display_identity() -> None:
    with pytest.raises(ValueError, match="display identity"):
        ModuleManifest(
            name="unknown_active_module",
            version="0.1.0",
            subscribed_events=["items.*"],
            owned_collections=["unknown_active_records"],
            allowed_meli_scopes=["GET /items/*"],
            health_endpoint="/health",
        )


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
        "display_identity": {
            "display_name": "ZelerPricing",
            "legacy_display_name": "EasyReprice",
            "availability": "active",
        },
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

    assert response.status_code == 503
    assert response.json() == {
        "module_id": "repricer",
        "ready": False,
        "checks": {
            "mongo": {"ok": True, "detail": "connected"},
            "rabbitmq": {"ok": False, "detail": "consumer_stalled"},
        },
    }
