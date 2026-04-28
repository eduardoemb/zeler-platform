from __future__ import annotations

import json
from pathlib import Path

from infra.mongo.validator_contract import validate_document_against_schema

ROOT = Path(__file__).resolve().parents[1]


def test_fulldock_validators_are_strict_and_require_core_fields() -> None:
    for schema_name in ["fulldock_inventory_rules.json", "fulldock_history.json"]:
        payload = json.loads(
            (ROOT / "infra" / "mongo" / "schemas" / schema_name).read_text(encoding="utf-8")
        )

        result = validate_document_against_schema({"schema_version": 1}, payload)

        assert payload["validationAction"] == "error"
        assert payload["validationLevel"] == "strict"
        assert {"_id", "seller_id", "schema_version"}.issubset(payload["$jsonSchema"]["required"])
        assert result.valid is False
        assert {"_id", "seller_id"}.issubset(result.missing_required_fields)


def test_fulldock_history_accepts_stock_location_noop_outcomes() -> None:
    payload = json.loads(
        (ROOT / "infra" / "mongo" / "schemas" / "fulldock_history.json").read_text(encoding="utf-8")
    )

    assert set(payload["$jsonSchema"]["properties"]["outcome"]["enum"]) >= {
        "no_drift",
        "missing_mapping",
        "malformed_resource",
        "resource_not_found",
    }
