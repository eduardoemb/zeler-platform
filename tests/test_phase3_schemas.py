from __future__ import annotations

import json
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = ROOT / "infra" / "mongo" / "schemas"
INDEXES_DIR = ROOT / "infra" / "mongo" / "indexes"

MAIN_SCHEMA_FILES = {
    "meli_accounts.json",
    "users.json",
    "items.json",
    "orders.json",
    "questions.json",
    "messages.json",
    "shipments.json",
    "claims.json",
    "webhook_events.json",
    "bootstrap_jobs.json",
    "module_registry.json",
    "repricer_rules.json",
    "repricer_history.json",
    "audit_log.json",
}


def _load_schema(file_name: str) -> dict[str, object]:
    payload = json.loads((SCHEMAS_DIR / file_name).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _json_schema(file_name: str) -> dict[str, object]:
    payload = _load_schema(file_name)
    schema = payload.get("$jsonSchema")
    assert isinstance(schema, dict), file_name
    return cast(dict[str, object], schema)


def test_phase3_main_schemas_are_concrete_validators_without_todo_placeholders() -> None:
    for file_name in sorted(MAIN_SCHEMA_FILES):
        payload = _load_schema(file_name)
        assert "TODO" not in json.dumps(payload)
        assert "P3" not in str(payload.get("$comment", ""))

        schema = _json_schema(file_name)
        assert schema["bsonType"] == "object"
        assert isinstance(schema.get("required"), list)
        required = schema["required"]
        assert isinstance(required, list)
        assert "schema_version" in required


def test_entity_schemas_require_tenant_and_canonical_ids() -> None:
    expectations = {
        "items.json": {"_id", "seller_id", "title", "status", "schema_version"},
        "orders.json": {"_id", "seller_id", "buyer_id", "status", "date_created", "schema_version"},
        "questions.json": {
            "_id",
            "seller_id",
            "item_id",
            "status",
            "date_created",
            "schema_version",
        },
        "messages.json": {
            "_id",
            "seller_id",
            "pack_id",
            "status",
            "date_created",
            "schema_version",
        },
        "shipments.json": {
            "_id",
            "seller_id",
            "order_id",
            "status",
            "date_created",
            "schema_version",
        },
        "claims.json": {"_id", "seller_id", "order_id", "status", "date_created", "schema_version"},
    }

    for file_name, required_fields in expectations.items():
        required_value = _json_schema(file_name)["required"]
        assert isinstance(required_value, list)
        required = set(required_value)
        assert required_fields <= required


def test_orders_schema_allows_optional_meli_pack_id_without_requiring_it() -> None:
    schema = _json_schema("orders.json")
    properties = schema["properties"]
    required = schema["required"]

    assert isinstance(properties, dict)
    assert properties["meli_pack_id"] == {"bsonType": ["string", "long", "int", "null"]}
    assert isinstance(required, list)
    assert "meli_pack_id" not in required


def test_ttl_indexes_are_declared_for_ephemeral_collections() -> None:
    ttl_expectations = {
        "webhook_events.json": ("ttl_received_at_45d", "received_at", 45 * 24 * 60 * 60),
        "repricer_history.json": (
            "idx_repricer_history_applied_at_ttl",
            "applied_at",
            365 * 24 * 60 * 60,
        ),
        "audit_log.json": ("ttl_audit_log_at_365d", "at", 365 * 24 * 60 * 60),
    }

    for file_name, (index_name, key, seconds) in ttl_expectations.items():
        indexes = json.loads((INDEXES_DIR / file_name).read_text(encoding="utf-8"))
        assert {
            "keys": {key: 1},
            "options": {"name": index_name, "expireAfterSeconds": seconds},
        } in indexes


def test_shipments_schema_allows_only_minimal_receiver_address_snapshot() -> None:
    schema = _json_schema("shipments.json")
    properties = schema["properties"]
    assert isinstance(properties, dict)
    receiver_address = properties["receiver_address"]
    assert isinstance(receiver_address, dict)

    assert receiver_address["bsonType"] == ["object", "null"]
    assert receiver_address["additionalProperties"] is False
    allowed_fields = {
        "name",
        "street_name",
        "street_number",
        "neighborhood",
        "zip_code",
        "city",
        "state",
        "country",
    }
    snapshot_properties = receiver_address["properties"]
    assert isinstance(snapshot_properties, dict)
    assert set(snapshot_properties) == allowed_fields

    for field_schema in snapshot_properties.values():
        assert isinstance(field_schema, dict)
        assert field_schema == {"bsonType": ["string", "null"], "maxLength": 120}


def test_shipments_indexes_do_not_include_receiver_address_or_name_fields() -> None:
    indexes = json.loads((INDEXES_DIR / "shipments.json").read_text(encoding="utf-8"))
    forbidden_fragments = {
        "receiver_address",
        "name",
        "street",
        "neighborhood",
        "zip_code",
        "city",
        "state",
        "country",
    }

    for index in indexes:
        keys = index["keys"]
        assert isinstance(keys, dict)
        serialized_keys = json.dumps(keys, sort_keys=True)
        index_name = str(index.get("options", {}).get("name", ""))
        assert all(fragment not in serialized_keys for fragment in forbidden_fragments)
        assert all(fragment not in index_name for fragment in forbidden_fragments)
