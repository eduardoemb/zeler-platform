from __future__ import annotations

import json
from pathlib import Path

from infra.mongo.validator_contract import validate_document_against_schema

ROOT = Path(__file__).resolve().parents[1]


def test_meli_oauth_state_schema_file_exists() -> None:
    validator = json.loads((ROOT / "infra/mongo/schemas/meli_oauth_state.json").read_text())

    schema = validator["$jsonSchema"]
    assert validator["validationAction"] == "error"
    assert validator["validationLevel"] == "strict"
    assert schema["required"] == ["_id", "platform_user_id", "code_verifier", "created_at"]
    assert schema["properties"]["_id"] == {"bsonType": "string"}
    assert schema["properties"]["platform_user_id"] == {"bsonType": "string"}
    assert schema["properties"]["code_verifier"] == {
        "bsonType": "string",
        "minLength": 32,
    }
    assert schema["properties"]["created_at"] == {"bsonType": "date"}


def test_meli_oauth_state_index_file_exists() -> None:
    indexes = json.loads((ROOT / "infra/mongo/indexes/meli_oauth_state.json").read_text())

    assert indexes == [
        {
            "keys": {"created_at": 1},
            "options": {"name": "ttl_meli_oauth_state_created_at", "expireAfterSeconds": 600},
        }
    ]


def test_meli_oauth_state_validator_rejects_missing_required_fields() -> None:
    validator = json.loads((ROOT / "infra/mongo/schemas/meli_oauth_state.json").read_text())

    result = validate_document_against_schema({"_id": "s"}, validator)

    assert result.valid is False
    assert result.missing_required_fields == ["platform_user_id", "code_verifier", "created_at"]
