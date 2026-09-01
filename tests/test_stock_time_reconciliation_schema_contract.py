from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from zeler_platform_core.cli.export_schemas import ENTITY_SCHEMAS, _validator_payload

ROOT = Path(__file__).resolve().parents[1]
COLLECTION = "sheets_stock_time_reconciliation_operations"
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


def _load(relative_path: str) -> Any:
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


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
    sha256 = {
        "bsonType": "string",
        "minLength": 64,
        "maxLength": 64,
        "pattern": "^[0-9a-f]{64}$",
    }

    assert properties["source_fingerprint"] == sha256
    assert properties["plan_fingerprint"] == sha256
    assert re.fullmatch(sha256["pattern"], "g" * 64) is None
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
