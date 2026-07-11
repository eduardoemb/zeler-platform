from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from zeler_platform_core.runtime.manifest import ModuleManifest


async def register_module(manifest: ModuleManifest, mongo_db: Any) -> None:
    """Register a module manifest in the runtime registry.

    The manifest model performs ownership validation before this write. The DB dependency
    is intentionally duck-typed so modules can pass a Motor database in production and
    small fakes in tests.
    """

    document = module_registration_document(manifest)
    await mongo_db["module_registry"].replace_one(
        {"_id": manifest.module_id}, document, upsert=True
    )


def module_registration_document(manifest: ModuleManifest) -> dict[str, Any]:
    return {
        "_id": manifest.module_id,
        "version": manifest.version,
        "allowed_meli_scopes": manifest.allowed_meli_scopes,
        "routing_keys": manifest.routing_keys,
        "owned_collections": manifest.owned_collections,
        "health_endpoint": manifest.health_endpoint,
        "display_identity": manifest.display_identity.model_dump(mode="json"),
        "status": "enabled",
        "schema_version": 1,
    }


def module_registration_fingerprint(document: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(document),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def registration_matches_manifest(
    *, document: Mapping[str, Any] | None, manifest: ModuleManifest
) -> bool:
    if document is None:
        return False
    expected = module_registration_document(manifest)
    return module_registration_fingerprint(document) == module_registration_fingerprint(expected)
