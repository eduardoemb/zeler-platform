from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from infra.mongo.validator_contract import validate_document_against_schema

ROOT = Path(__file__).resolve().parents[1]


def _load(relative_path: str) -> Any:
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def test_reconciliation_ledger_validator_is_strict_and_requires_chain_contract() -> None:
    validator = _load("infra/mongo/schemas/sheets_dlq_reconciliation_events.json")
    schema = validator["$jsonSchema"]

    assert validator["validationLevel"] == "strict"
    assert validator["validationAction"] == "error"
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "_id",
        "run_id",
        "sequence",
        "event_hash",
        "event_type",
        "actor",
        "occurred_at",
        "schema_version",
    }
    assert schema["properties"]["event_hash"]["bsonType"] == "string"
    assert schema["properties"]["sequence"]["bsonType"] == ["int", "long"]
    assert schema["properties"]["occurred_at"]["bsonType"] == "date"


def test_reconciliation_ledger_validator_rejects_malformed_event() -> None:
    validator = _load("infra/mongo/schemas/sheets_dlq_reconciliation_events.json")
    malformed = {"_id": "run-1:1", "event_hash": "h1"}

    result = validate_document_against_schema(malformed, validator)

    assert result.valid is False
    for field in ("run_id", "sequence", "event_type", "actor", "occurred_at", "schema_version"):
        assert field in result.missing_required_fields


def test_reconciliation_ledger_indexes_are_unique_on_hash_and_run_sequence() -> None:
    indexes = _load("infra/mongo/indexes/sheets_dlq_reconciliation_events.json")

    assert {
        "keys": {"event_hash": 1},
        "options": {"name": "uniq_sheets_dlq_reconciliation_event_hash", "unique": True},
    } in indexes
    assert {
        "keys": {"run_id": 1, "sequence": 1},
        "options": {"name": "uniq_sheets_dlq_reconciliation_run_sequence", "unique": True},
    } in indexes


def test_reconciliation_ledger_indexes_have_no_duplicate_run_sequence_definition() -> None:
    indexes = _load("infra/mongo/indexes/sheets_dlq_reconciliation_events.json")

    run_sequence_definitions = [
        index for index in indexes if index.get("keys") == {"run_id": 1, "sequence": 1}
    ]
    assert len(run_sequence_definitions) == 1
