from __future__ import annotations

from typing import Any

from zeler_platform_core.runtime.manifest import ModuleManifest


async def register_module(manifest: ModuleManifest, mongo_db: Any) -> None:
    """Register a module manifest in the runtime registry.

    The manifest model performs ownership validation before this write. The DB dependency
    is intentionally duck-typed so modules can pass a Motor database in production and
    small fakes in tests.
    """

    document = {
        "_id": manifest.module_id,
        "version": manifest.version,
        "allowed_meli_scopes": manifest.allowed_meli_scopes,
        "routing_keys": manifest.routing_keys,
        "owned_collections": manifest.owned_collections,
        "health_endpoint": manifest.health_endpoint,
        "status": "enabled",
        "schema_version": 1,
    }
    await mongo_db["module_registry"].replace_one(
        {"_id": manifest.module_id}, document, upsert=True
    )
