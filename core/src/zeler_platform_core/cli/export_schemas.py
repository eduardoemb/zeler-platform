from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = {"schema_version": {"bsonType": "int"}}
ID_STRING = {"_id": {"bsonType": "string"}}
ID_OBJECT_OR_STRING = {"_id": {"bsonType": ["objectId", "string"]}}
ID_FLEX = {"_id": {"bsonType": ["string", "long", "int"]}}
SELLER = {"seller_id": {"bsonType": ["string", "long", "int"]}}
DATE = {"bsonType": "date"}
NULLABLE_DATE = {"bsonType": ["date", "null"]}
MONEY = {"bsonType": ["decimal", "double", "int", "long"]}
NULLABLE_MONEY = {"bsonType": ["decimal", "double", "int", "long", "null"]}
PROMO_PRICE_PROJECTION = {
    "additionalProperties": False,
    "bsonType": ["object", "null"],
    "required": [
        "source",
        "sale_amount",
        "regular_amount",
        "currency_id",
        "reference_at",
        "synced_at",
    ],
    "properties": {
        "source": {"enum": ["/items/{id}/sale_price"]},
        "sale_amount": MONEY,
        "regular_amount": MONEY,
        "discount_percent": {"bsonType": ["decimal", "double", "int", "long", "null"]},
        "currency_id": {"bsonType": "string"},
        "promotion_id": {"bsonType": ["string", "null"]},
        "promotion_type": {"bsonType": ["string", "null"]},
        "reference_at": DATE,
        "synced_at": DATE,
    },
}
LISTING_PRICE_FIXED_FEE_PARAMS = {
    "additionalProperties": False,
    "bsonType": "object",
    "required": ["site_id", "category_id", "price", "currency_id", "listing_type_id"],
    "properties": {
        "site_id": {"bsonType": "string"},
        "category_id": {"bsonType": "string"},
        "price": MONEY,
        "currency_id": {"bsonType": "string"},
        "listing_type_id": {"bsonType": "string"},
        "shipping_mode": {"bsonType": ["string", "null"]},
        "logistic_type": {"bsonType": ["string", "null"]},
        "billable_weight": {"bsonType": ["decimal", "double", "int", "long", "null"]},
        "tags": {"bsonType": "array"},
    },
}
LISTING_PRICE_FIXED_FEE_PROJECTION = {
    "additionalProperties": False,
    "bsonType": ["object", "null"],
    "required": ["source", "fixed_fee", "currency_id", "synced_at", "params"],
    "properties": {
        "source": {"enum": ["/sites/{site}/listing_prices"]},
        "fixed_fee": MONEY,
        "currency_id": {"bsonType": "string"},
        "synced_at": DATE,
        "params": LISTING_PRICE_FIXED_FEE_PARAMS,
    },
}
LISTING_FEE_PROJECTION = {
    "additionalProperties": False,
    "bsonType": ["object", "null"],
    "required": [
        "source",
        "site_id",
        "currency_id",
        "price",
        "listing_type_id",
        "category_id",
        "sale_fee_amount",
        "percentage_fee",
        "synced_at",
    ],
    "properties": {
        "source": {"enum": ["/sites/{site}/listing_prices"]},
        "site_id": {"bsonType": "string"},
        "currency_id": {"bsonType": "string"},
        "price": MONEY,
        "listing_type_id": {"bsonType": "string"},
        "category_id": {"bsonType": "string"},
        "sale_fee_amount": MONEY,
        "percentage_fee": MONEY,
        "gross_amount": NULLABLE_MONEY,
        "fixed_fee": NULLABLE_MONEY,
        "meli_percentage_fee": NULLABLE_MONEY,
        "financing_add_on_fee": NULLABLE_MONEY,
        "synced_at": DATE,
    },
}
RECEIVER_ADDRESS_SNAPSHOT = {
    "bsonType": ["object", "null"],
    "additionalProperties": False,
    "properties": {
        "name": {"bsonType": ["string", "null"], "maxLength": 120},
        "street_name": {"bsonType": ["string", "null"], "maxLength": 120},
        "street_number": {"bsonType": ["string", "null"], "maxLength": 120},
        "neighborhood": {"bsonType": ["string", "null"], "maxLength": 120},
        "zip_code": {"bsonType": ["string", "null"], "maxLength": 120},
        "city": {"bsonType": ["string", "null"], "maxLength": 120},
        "state": {"bsonType": ["string", "null"], "maxLength": 120},
        "country": {"bsonType": ["string", "null"], "maxLength": 120},
    },
}
SHIPMENT_REAL_SHIPPING_COST = {
    "bsonType": ["object", "null"],
    "additionalProperties": False,
    "required": ["source", "seller_cost", "synced_at"],
    "properties": {
        "source": {"enum": ["/shipments/{shipment_id}/costs"]},
        "seller_cost": MONEY,
        "receiver_cost": {"bsonType": ["decimal", "double", "int", "long", "null"]},
        "currency_id": {"bsonType": ["string", "null"]},
        "matched_sender_id": {"bsonType": ["string", "null"]},
        "synced_at": DATE,
    },
}

ENTITY_SCHEMAS: dict[str, dict[str, Any]] = {
    "meli_accounts": {
        "required": [
            "_id",
            "seller_id",
            "nickname",
            "app_id",
            "platform_user_id",
            "access_token_ciphertext",
            "access_token_dek_wrapped",
            "refresh_token_ciphertext",
            "refresh_token_dek_wrapped",
            "token_nonce",
            "refresh_token_nonce",
            "scopes",
            "status",
            "expires_at",
            "kms_key_version",
            "created_at",
            "updated_at",
            "schema_version",
        ],
        "properties": {
            **ID_OBJECT_OR_STRING,
            **SELLER,
            "nickname": {"bsonType": "string"},
            "app_id": {"bsonType": "string"},
            "platform_user_id": {"bsonType": "string"},
            "access_token_ciphertext": {"bsonType": ["binData", "string"]},
            "access_token_dek_wrapped": {"bsonType": ["binData", "string"]},
            "refresh_token_ciphertext": {"bsonType": ["binData", "string"]},
            "refresh_token_dek_wrapped": {"bsonType": ["binData", "string"]},
            "token_nonce": {"bsonType": ["binData", "string"]},
            "refresh_token_nonce": {"bsonType": ["binData", "string"]},
            "scopes": {"bsonType": "array"},
            "status": {
                "enum": [
                    "active",
                    "pending",
                    "refresh_pending",
                    "revoked",
                    "invalid_grant",
                    "error",
                    "invalid",
                    "paused",
                ]
            },
            "expires_at": DATE,
            "refresh_token_expires_at": NULLABLE_DATE,
            "lock_held_until": NULLABLE_DATE,
            "last_refresh_at": NULLABLE_DATE,
            "connected_at": NULLABLE_DATE,
            "kms_key_version": {"bsonType": "string"},
            "last_error": {"bsonType": ["string", "null"]},
            "sync_status": {"bsonType": ["object", "null"]},
            "site_id": {"bsonType": ["string", "null"]},
            "timezone": {"bsonType": ["string", "null"]},
            "created_at": DATE,
            "updated_at": DATE,
            **SCHEMA_VERSION,
        },
    },
    "users": {
        "required": [
            "_id",
            "email",
            "name",
            "auth_provider",
            "created_at",
            "updated_at",
            "schema_version",
        ],
        "properties": {
            **ID_OBJECT_OR_STRING,
            "email": {"bsonType": "string"},
            "name": {"bsonType": "string"},
            "auth_provider": {"enum": ["local", "google", "meli", "internal"]},
            "meli_account_ids": {"bsonType": "array"},
            "module_permissions": {"bsonType": "object"},
            "roles": {"bsonType": "array"},
            "status": {"enum": ["active", "suspended", "deleted"]},
            "created_at": DATE,
            "updated_at": DATE,
            **SCHEMA_VERSION,
        },
    },
    "items": {
        "additionalProperties": False,
        "required": [
            "_id",
            "seller_id",
            "title",
            "price",
            "base_price",
            "available_quantity",
            "status",
            "category_id",
            "last_meli_sync_at",
            "date_created",
            "last_updated",
            "schema_version",
        ],
        "properties": {
            **ID_OBJECT_OR_STRING,
            **SELLER,
            "title": {"bsonType": "string"},
            "price": MONEY,
            "base_price": MONEY,
            "available_quantity": {"bsonType": ["int", "long"]},
            "status": {"bsonType": "string"},
            "category_id": {"bsonType": "string"},
            "currency_id": {"bsonType": ["string", "null"]},
            "site_id": {"bsonType": ["string", "null"]},
            "current_promotion": PROMO_PRICE_PROJECTION,
            "listing_price_fixed_fee": LISTING_PRICE_FIXED_FEE_PROJECTION,
            "listing_fee_projection": LISTING_FEE_PROJECTION,
            "catalog_product_id": {"bsonType": ["string", "null"]},
            "variations": {"bsonType": "array"},
            "attributes": {"bsonType": "array"},
            "shipping": {"bsonType": ["object", "null"]},
            "health": {"bsonType": ["double", "int", "long", "null"]},
            "inventory_id": {"bsonType": ["string", "null"]},
            "listing_type_id": {"bsonType": ["string", "null"]},
            "seller_shipping_cost": {"bsonType": ["decimal", "double", "int", "long", "null"]},
            "billable_weight": {"bsonType": ["decimal", "double", "int", "long", "null"]},
            "tags": {"bsonType": "array"},
            "permalink": {"bsonType": ["string", "null"]},
            "thumbnail": {"bsonType": ["string", "null"]},
            "status_observed_at": NULLABLE_DATE,
            "status_started_at": NULLABLE_DATE,
            "paused_since": NULLABLE_DATE,
            "last_status_change_at": NULLABLE_DATE,
            "last_meli_sync_at": DATE,
            "date_created": DATE,
            "last_updated": DATE,
            **SCHEMA_VERSION,
        },
    },
    "orders": {
        "required": [
            "_id",
            "seller_id",
            "buyer_id",
            "status",
            "date_created",
            "total_amount",
            "schema_version",
        ],
        "properties": {
            **ID_FLEX,
            **SELLER,
            "buyer_id": {"bsonType": ["string", "long", "int"]},
            "status": {"bsonType": "string"},
            "date_created": DATE,
            "date_closed": NULLABLE_DATE,
            "total_amount": MONEY,
            "items": {"bsonType": "array"},
            "shipment_id": {"bsonType": ["string", "long", "int", "null"]},
            "meli_pack_id": {"bsonType": ["string", "long", "int", "null"]},
            "tags": {"bsonType": "array"},
            "feedback": {"bsonType": ["object", "null"]},
            **SCHEMA_VERSION,
        },
    },
    "questions": {
        "required": [
            "_id",
            "seller_id",
            "item_id",
            "text",
            "status",
            "from_user_id",
            "date_created",
            "schema_version",
        ],
        "properties": {
            **ID_FLEX,
            **SELLER,
            "item_id": {"bsonType": "string"},
            "text": {"bsonType": "string"},
            "status": {"enum": ["UNANSWERED", "ANSWERED", "DELETED", "BANNED"]},
            "answer": {"bsonType": ["object", "null"]},
            "from_user_id": {"bsonType": ["string", "long", "int"]},
            "date_created": DATE,
            **SCHEMA_VERSION,
        },
    },
    "messages": {
        "required": [
            "_id",
            "seller_id",
            "pack_id",
            "from_user_id",
            "to_user_id",
            "text",
            "status",
            "date_created",
            "schema_version",
        ],
        "properties": {
            **ID_OBJECT_OR_STRING,
            **SELLER,
            "pack_id": {"bsonType": "string"},
            "order_id": {"bsonType": ["string", "long", "int", "null"]},
            "from_user_id": {"bsonType": ["string", "long", "int"]},
            "to_user_id": {"bsonType": ["string", "long", "int"]},
            "text": {"bsonType": "string"},
            "status": {"bsonType": "string"},
            "date_created": DATE,
            "read_at": NULLABLE_DATE,
            **SCHEMA_VERSION,
        },
    },
    "shipments": {
        "required": [
            "_id",
            "seller_id",
            "order_id",
            "status",
            "logistic_type",
            "date_created",
            "last_updated",
            "schema_version",
        ],
        "properties": {
            **ID_FLEX,
            **SELLER,
            "order_id": {"bsonType": ["string", "long", "int"]},
            "status": {"bsonType": "string"},
            "substatus": {"bsonType": ["string", "null"]},
            "tracking_number": {"bsonType": ["string", "null"]},
            "logistic_type": {"bsonType": "string"},
            "real_shipping_cost": SHIPMENT_REAL_SHIPPING_COST,
            "receiver_address": RECEIVER_ADDRESS_SNAPSHOT,
            "date_created": DATE,
            "last_updated": DATE,
            **SCHEMA_VERSION,
        },
    },
    "claims": {
        "required": [
            "_id",
            "seller_id",
            "order_id",
            "status",
            "stage",
            "type",
            "date_created",
            "schema_version",
        ],
        "properties": {
            **ID_FLEX,
            **SELLER,
            "buyer_id": {"bsonType": ["string", "long", "int", "null"]},
            "order_id": {"bsonType": ["string", "long", "int"]},
            "status": {"bsonType": "string"},
            "stage": {"bsonType": "string"},
            "type": {"bsonType": "string"},
            "date_created": DATE,
            "resolution": {"bsonType": ["object", "null"]},
            **SCHEMA_VERSION,
        },
    },
    "events": {
        "required": [
            "event_id",
            "event_type",
            "account_id",
            "occurred_at",
            "payload",
            "schema_version",
        ],
        "properties": {
            "event_id": {"bsonType": "string"},
            "event_type": {"bsonType": "string"},
            "account_id": {"bsonType": "string"},
            "occurred_at": DATE,
            "payload": {"bsonType": "object"},
            **SCHEMA_VERSION,
        },
    },
    "webhook_events": {
        "required": [
            "_id",
            "topic",
            "user_id",
            "resource",
            "received_at",
            "raw_body",
            "source_ip",
            "schema_version",
        ],
        "properties": {
            **ID_OBJECT_OR_STRING,
            "topic": {"bsonType": "string"},
            "user_id": {"bsonType": ["string", "long", "int"]},
            "resource": {"bsonType": "string"},
            "received_at": DATE,
            "published_at": NULLABLE_DATE,
            "classification": {"bsonType": ["string", "null"]},
            "raw_body": {"bsonType": "object"},
            "source_ip": {"bsonType": "string"},
            **SCHEMA_VERSION,
        },
    },
    "bootstrap_jobs": {
        "required": [
            "_id",
            "seller_id",
            "state",
            "dag",
            "checkpoints",
            "created_at",
            "updated_at",
            "schema_version",
        ],
        "properties": {
            **ID_OBJECT_OR_STRING,
            **SELLER,
            "state": {"enum": ["pending", "running", "paused", "succeeded", "failed", "cancelled"]},
            "dag": {"bsonType": "object"},
            "checkpoints": {"bsonType": "object"},
            "attempt_count": {"bsonType": "int", "minimum": 0},
            "current_stage": {"bsonType": ["string", "null"]},
            "dispatch_attempts": {"bsonType": "int", "minimum": 0},
            "stage_progress": {"bsonType": "object"},
            "started_at": NULLABLE_DATE,
            "finished_at": NULLABLE_DATE,
            "failed_at": NULLABLE_DATE,
            "error": {"bsonType": ["string", "null"]},
            "last_error": {"bsonType": ["string", "null"], "maxLength": 1024},
            "errors": {"bsonType": "array"},
            "triggered_by": {"enum": ["oauth_callback", "oauth_callback_force", "manual", "retry"]},
            "created_at": DATE,
            "updated_at": DATE,
            **SCHEMA_VERSION,
        },
    },
    "module_registry": {
        "required": [
            "_id",
            "version",
            "allowed_meli_scopes",
            "routing_keys",
            "status",
            "schema_version",
        ],
        "properties": {
            **ID_OBJECT_OR_STRING,
            "version": {"bsonType": "string"},
            "allowed_meli_scopes": {"bsonType": "array"},
            "allowed_seller_ids": {
                "bsonType": "array",
                "items": {"bsonType": ["int", "long", "string"]},
            },
            "routing_keys": {"bsonType": "array"},
            "display_identity": {
                "bsonType": "object",
                "required": ["display_name", "availability"],
                "properties": {
                    "display_name": {"bsonType": "string"},
                    "legacy_display_name": {"bsonType": ["string", "null"]},
                    "availability": {"enum": ["active", "retired"]},
                },
            },
            "status": {"enum": ["enabled", "disabled", "degraded"]},
            "last_heartbeat_at": NULLABLE_DATE,
            "health": {"bsonType": ["object", "null"]},
            **SCHEMA_VERSION,
        },
    },
    "repricer_rules": {
        "required": [
            "_id",
            "seller_id",
            "item_id",
            "strategy",
            "min_price",
            "max_price",
            "active",
            "updated_at",
            "schema_version",
        ],
        "properties": {
            **ID_OBJECT_OR_STRING,
            **SELLER,
            "item_id": {"bsonType": "string"},
            "strategy": {"enum": ["min_price", "competitive", "maximize"]},
            "min_price": MONEY,
            "max_price": MONEY,
            "active": {"bsonType": "bool"},
            "updated_at": DATE,
            **SCHEMA_VERSION,
        },
    },
    "repricer_history": {
        "required": [
            "_id",
            "seller_id",
            "item_id",
            "old_price",
            "new_price",
            "reason",
            "applied_at",
            "schema_version",
        ],
        "properties": {
            **ID_OBJECT_OR_STRING,
            **SELLER,
            "item_id": {"bsonType": "string"},
            "old_price": MONEY,
            "new_price": MONEY,
            "reason": {"bsonType": "string"},
            "applied_at": DATE,
            **SCHEMA_VERSION,
        },
    },
    "audit_log": {
        "required": [
            "_id",
            "seller_id",
            "at",
            "module_id",
            "method",
            "path",
            "status",
            "duration_ms",
            "schema_version",
        ],
        "properties": {
            **ID_OBJECT_OR_STRING,
            **SELLER,
            "at": DATE,
            "module_id": {"bsonType": "string"},
            "method": {"bsonType": "string"},
            "path": {"bsonType": "string"},
            "status": {"bsonType": "int"},
            "upstream_status": {"bsonType": ["int", "null"]},
            "duration_ms": {"bsonType": ["int", "long"]},
            "trace_id": {"bsonType": ["string", "null"]},
            **SCHEMA_VERSION,
        },
    },
}

CANONICAL_SCHEMA_FILES = {f"{collection}.json" for collection in ENTITY_SCHEMAS}


def _validator_payload(schema: dict[str, Any]) -> dict[str, Any]:
    json_schema = {
        "bsonType": "object",
        "required": schema["required"],
        "properties": schema["properties"],
    }
    if "additionalProperties" in schema:
        json_schema["additionalProperties"] = schema["additionalProperties"]
    return {
        "validationAction": "error",
        "validationLevel": "strict",
        "$jsonSchema": json_schema,
    }


def _payload_text(collection: str) -> str:
    return (
        json.dumps(_validator_payload(ENTITY_SCHEMAS[collection]), indent=2, sort_keys=True) + "\n"
    )


def export_schemas(output_dir: Path) -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for collection in sorted(ENTITY_SCHEMAS):
        path = output_dir / f"{collection}.json"
        path.write_text(_payload_text(collection), encoding="utf-8")
        written.append(path.name)
    return written


def validate_export_drift(committed_dir: Path) -> list[str]:
    drifted: list[str] = []
    for collection in sorted(ENTITY_SCHEMAS):
        path = committed_dir / f"{collection}.json"
        if not path.exists() or path.read_text(encoding="utf-8") != _payload_text(collection):
            drifted.append(path.name)
    return drifted


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Export Mongo $jsonSchema validators from core models"
    )
    parser.add_argument("output_dir", type=Path)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail when committed schemas differ from generated output",
    )
    args = parser.parse_args()
    if args.check:
        drift = validate_export_drift(args.output_dir)
        if drift:
            raise SystemExit(f"schema export drift detected: {', '.join(drift)}")
        return
    export_schemas(args.output_dir)


if __name__ == "__main__":
    main()
