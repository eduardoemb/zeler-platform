from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from typing import Any

from pymongo import MongoClient

ZELER_APP_CLIENT_ID = "zeler-app"
PILOT_SELLER_ID = 82453304
REQUIRED_ADMIN_SCOPES = [
    "admin:repricer",
    "admin:sheets",
    "admin:publicador",
    "admin:autoreply",
]
PLATFORM_USER_ALLOWLIST_ENV = "ZELER_APP_ALLOWED_PLATFORM_USER_IDS"


def _parse_env_allowlist(raw_value: str) -> list[str]:
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def _existing_platform_user_allowlist(existing: Mapping[str, Any] | None) -> list[str]:
    if not existing:
        return []
    raw_allowlist = existing.get("allowed_platform_user_ids")
    if not isinstance(raw_allowlist, list):
        return []
    return [str(item) for item in raw_allowlist if str(item).strip()]


def _deprecated_seller_fallback(existing: Mapping[str, Any] | None) -> list[Any]:
    if existing:
        raw_allowlist = existing.get("allowed_seller_ids")
        if isinstance(raw_allowlist, list) and raw_allowlist:
            return raw_allowlist
    return [PILOT_SELLER_ID]


def ensure_zeler_app_admin_client(mongo_uri: str) -> dict[str, str]:
    client: MongoClient[Mapping[str, Any]] = MongoClient(mongo_uri)
    try:
        database = client.get_default_database()
        module_registry = database["module_registry"]
        existing = module_registry.find_one({"_id": ZELER_APP_CLIENT_ID})
        env_allowlist = os.environ.get(PLATFORM_USER_ALLOWLIST_ENV)
        allowed_platform_user_ids = (
            _parse_env_allowlist(env_allowlist)
            if env_allowlist is not None
            else _existing_platform_user_allowlist(existing)
        )
        module_registry.update_one(
            {"_id": ZELER_APP_CLIENT_ID},
            {
                "$set": {
                    "_id": ZELER_APP_CLIENT_ID,
                    "version": "0.1.0",
                    "allowed_meli_scopes": REQUIRED_ADMIN_SCOPES,
                    "allowed_platform_user_ids": allowed_platform_user_ids,
                    "allowed_seller_ids": _deprecated_seller_fallback(existing),
                    "routing_keys": [],
                    "owned_collections": [],
                    "health_endpoint": "/health",
                    "status": "enabled",
                    "schema_version": 1,
                }
            },
            upsert=True,
        )
        return {"client_id": ZELER_APP_CLIENT_ID, "status": "updated"}
    finally:
        client.close()


def main() -> None:
    mongo_uri = os.environ.get("MONGO_URI")
    if not mongo_uri:
        print("error: MONGO_URI is required", file=sys.stderr)
        sys.exit(2)
    result = ensure_zeler_app_admin_client(mongo_uri)
    print(f"{result['client_id']} admin client {result['status']}")


if __name__ == "__main__":
    main()
