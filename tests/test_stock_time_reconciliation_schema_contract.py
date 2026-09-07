from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from zeler_platform_core.cli.export_schemas import ENTITY_SCHEMAS, _validator_payload

ROOT = Path(__file__).resolve().parents[1]
COLLECTION = "sheets_stock_time_reconciliation_operations"
PREIMAGE_COLLECTION = "sheets_stock_time_reconciliation_preimages"
SHA256: dict[str, Any] = {
    "bsonType": "string",
    "minLength": 64,
    "maxLength": 64,
    "pattern": "^[0-9a-f]{64}$",
}
REQUIRED_FIELDS = [
    "_id",
    "seller_id",
    "read_model",
    "date_from",
    "date_to",
    "source_fingerprint",
    "plan_fingerprint",
    "state",
    "attempt",
    "attempt_token",
    "fence",
    "lease_acquired_at",
    "heartbeat_at",
    "lease_until",
    "planned_insert_count",
    "planned_update_count",
    "planned_delete_count",
    "planned_preimage_count",
    "created_at",
    "updated_at",
    "schema_version",
]
OPTIONAL_FIELDS = {"committed_at", "terminal_at", "error_code"}
PREIMAGE_REQUIRED_FIELDS = [
    "_id",
    "operation_id",
    "sequence",
    "target_collection",
    "target_id",
    "action",
    "preimage",
    "preimage_kind",
    "preimage_fingerprint",
    "expected_forward_revision",
    "created_at",
    "schema_version",
]


def _load(relative_path: str) -> Any:
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def test_preimage_contract_and_target_revision_are_canonically_registered() -> None:
    assert PREIMAGE_COLLECTION in ENTITY_SCHEMAS
    generated = _load(f"infra/mongo/schemas/{PREIMAGE_COLLECTION}.json")
    metrics_validator = _load("infra/mongo/schemas/sheets_stock_time_metrics.json")
    metrics = metrics_validator["$jsonSchema"]

    assert _validator_payload(ENTITY_SCHEMAS[PREIMAGE_COLLECTION]) == generated
    assert _validator_payload(ENTITY_SCHEMAS["sheets_stock_time_metrics"]) == metrics_validator
    assert metrics["properties"]["revision"] == SHA256
    assert "revision" not in metrics["required"]


def test_stock_time_operation_ledger_is_canonically_exported() -> None:
    generated = _load(f"infra/mongo/schemas/{COLLECTION}.json")

    assert _validator_payload(ENTITY_SCHEMAS[COLLECTION]) == generated


def test_stock_time_operation_ledger_is_strict_and_transition_ready() -> None:
    schema = _load(f"infra/mongo/schemas/{COLLECTION}.json")["$jsonSchema"]
    properties = schema["properties"]

    assert schema["additionalProperties"] is False
    assert schema["required"] == REQUIRED_FIELDS
    assert set(properties) == set(REQUIRED_FIELDS) | OPTIONAL_FIELDS
    assert properties["read_model"] == {"enum": ["stock_time_metrics"]}
    assert properties["state"] == {
        "enum": [
            "prepared",
            "committed",
            "rolled_back",
            "rollback_blocked",
            "failed",
            "expired",
        ]
    }
    assert "running" not in properties["state"]["enum"]
    assert "preimages" not in properties


def test_stock_time_operation_ledger_rejects_invalid_fingerprints_fences_and_counts() -> None:
    properties = _load(f"infra/mongo/schemas/{COLLECTION}.json")["$jsonSchema"]["properties"]

    assert properties["source_fingerprint"] == SHA256
    assert properties["plan_fingerprint"] == SHA256
    assert re.fullmatch(SHA256["pattern"], "g" * 64) is None
    for field in ("attempt", "fence"):
        assert properties[field] == {"bsonType": ["int", "long"], "minimum": 1}
    for field in (
        "planned_insert_count",
        "planned_update_count",
        "planned_delete_count",
        "planned_preimage_count",
    ):
        assert properties[field] == {"bsonType": ["int", "long"], "minimum": 0}
    assert properties["error_code"] == {
        "bsonType": ["string", "null"],
        "maxLength": 64,
        "pattern": "^[A-Z][A-Z0-9_]{0,63}$",
    }


def test_preimage_contract_is_strict_and_couples_action_to_exact_preimage() -> None:
    schema = _load(f"infra/mongo/schemas/{PREIMAGE_COLLECTION}.json")["$jsonSchema"]
    properties = schema["properties"]

    assert schema["additionalProperties"] is False
    assert schema["required"] == PREIMAGE_REQUIRED_FIELDS
    assert set(properties) == set(PREIMAGE_REQUIRED_FIELDS)
    assert properties["target_collection"] == {
        "enum": ["sheets_stock_time_metrics", "sheets_read_model_freshness"]
    }
    assert properties["action"] == {"enum": ["insert", "replace", "delete"]}
    assert properties["preimage"] == {"bsonType": ["object", "null"]}
    assert properties["preimage_kind"] == {"enum": ["absent", "exact_document"]}
    assert schema["oneOf"] == [
        {
            "properties": {
                "action": {"enum": ["insert"]},
                "preimage": {"bsonType": "null"},
                "preimage_kind": {"enum": ["absent"]},
            }
        },
        {
            "properties": {
                "action": {"enum": ["replace", "delete"]},
                "preimage": {"bsonType": "object"},
                "preimage_kind": {"enum": ["exact_document"]},
            }
        },
    ]
    assert {"state", "token", "secret", "seller_id", "payload"}.isdisjoint(properties)


def test_preimage_hashes_sequence_and_private_target_identity_are_bounded() -> None:
    properties = _load(f"infra/mongo/schemas/{PREIMAGE_COLLECTION}.json")["$jsonSchema"][
        "properties"
    ]

    for field in ("_id", "operation_id", "preimage_fingerprint", "expected_forward_revision"):
        assert properties[field] == SHA256
    assert re.fullmatch(SHA256["pattern"], "A" * 64) is None
    assert properties["sequence"] == {"bsonType": ["int", "long"], "minimum": 1}
    assert properties["target_id"] == {"bsonType": "string", "minLength": 1}


def test_preimage_indexes_prevent_duplicate_actions_and_support_recovery() -> None:
    assert _load(f"infra/mongo/indexes/{PREIMAGE_COLLECTION}.json") == [
        {
            "keys": {"operation_id": 1, "sequence": 1},
            "options": {
                "name": "uniq_sheets_stock_time_reconciliation_preimages_operation_sequence",
                "unique": True,
            },
        },
        {
            "keys": {"operation_id": 1, "target_collection": 1, "target_id": 1},
            "options": {
                "name": "uniq_sheets_stock_time_reconciliation_preimages_operation_target",
                "unique": True,
            },
        },
        {
            "keys": {"target_collection": 1, "target_id": 1},
            "options": {"name": "idx_sheets_stock_time_reconciliation_preimages_target"},
        },
    ]


def test_stock_time_operation_indexes_match_binding_and_lease_recovery() -> None:
    assert _load(f"infra/mongo/indexes/{COLLECTION}.json") == [
        {
            "keys": {
                "seller_id": 1,
                "read_model": 1,
                "date_from": 1,
                "date_to": 1,
                "source_fingerprint": 1,
                "plan_fingerprint": 1,
            },
            "options": {
                "name": "uniq_sheets_stock_time_reconciliation_operation_binding",
                "unique": True,
            },
        },
        {
            "keys": {"state": 1, "lease_until": 1},
            "options": {"name": "idx_sheets_stock_time_reconciliation_operations_state_lease"},
        },
    ]
