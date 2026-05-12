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
    "admin:fulldock",
]


def ensure_zeler_app_admin_client(mongo_uri: str) -> dict[str, str]:
    client: MongoClient[Mapping[str, Any]] = MongoClient(mongo_uri)
    try:
        database = client.get_default_database()
        database["module_registry"].update_one(
            {"_id": ZELER_APP_CLIENT_ID},
            {
                "$set": {
                    "_id": ZELER_APP_CLIENT_ID,
                    "version": "0.1.0",
                    "allowed_meli_scopes": REQUIRED_ADMIN_SCOPES,
                    "allowed_seller_ids": [PILOT_SELLER_ID],
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
