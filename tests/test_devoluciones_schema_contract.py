from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from infra.mongo.validator_contract import validate_document_against_schema

from zeler_platform_core.cli.export_schemas import ENTITY_SCHEMAS, _validator_payload

ROOT = Path(__file__).resolve().parents[1]


def _load(relative_path: str) -> Any:
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def test_devoluciones_operation_schema_is_exported_and_fenced() -> None:
    exported = _validator_payload(ENTITY_SCHEMAS["sheets_devoluciones_operations"])
    generated = _load("infra/mongo/schemas/sheets_devoluciones_operations.json")
    schema = generated["$jsonSchema"]

    assert exported == generated
    assert schema["additionalProperties"] is False
    assert schema["required"] == [
        "_id",
        "seller_id",
        "scope",
        "operation_id",
        "attempt_token",
        "fence",
        "state",
        "lease_until",
        "heartbeat_at",
        "started_at",
        "updated_at",
        "schema_version",
    ]
    assert schema["properties"]["fence"] == {"bsonType": ["int", "long"], "minimum": 1}
    assert schema["properties"]["state"] == {"enum": ["running", "succeeded", "failed", "released"]}
    assert validate_document_against_schema({"_id": "seller:scope"}, generated).valid is False


def test_devoluciones_claim_and_freshness_schemas_include_exact_source_facts() -> None:
    claims = _load("infra/mongo/schemas/claims.json")["$jsonSchema"]
    freshness = _load("infra/mongo/schemas/sheets_read_model_freshness.json")["$jsonSchema"]

    assert claims["properties"]["type"] == {
        "enum": ["mediations", "returns", "fulfillment", "cancel_purchase"]
    }
    assert claims["properties"]["item_id"] == {"bsonType": ["string", "long", "int", "null"]}
    assert claims["properties"]["returned_quantity"] == {
        "bsonType": ["int", "long", "null"],
        "minimum": 1,
    }
    for source_field in (
        "claim_version",
        "last_updated",
        "return_id",
        "return_last_updated",
        "return_status",
        "return_subtype",
        "return_context_type",
        "return_quantity_basis",
        "productive",
    ):
        assert source_field in claims["properties"]
    assert freshness["properties"]["valid_until"] == {"bsonType": ["date", "null"]}


def test_devoluciones_indexes_match_claim_order_freshness_and_operation_access() -> None:
    claims = _load("infra/mongo/indexes/claims.json")
    orders = _load("infra/mongo/indexes/orders.json")
    freshness = _load("infra/mongo/indexes/sheets_read_model_freshness.json")
    operations = _load("infra/mongo/indexes/sheets_devoluciones_operations.json")

    assert {
        "keys": {"seller_id": 1, "type": 1, "date_created": 1, "_id": 1},
        "options": {"name": "idx_claims_seller_type_date_id"},
    } in claims
    assert {
        "keys": {"seller_id": 1, "_id": 1},
        "options": {"name": "idx_orders_seller_id_keyset"},
    } in orders
    assert freshness[-1] == {
        "keys": {"seller_id": 1, "state": 1, "valid_until": 1},
        "options": {"name": "idx_sheets_read_model_freshness_seller_state_valid_until"},
    }
    assert operations == [
        {
            "keys": {"seller_id": 1, "scope": 1},
            "options": {"name": "uniq_sheets_devoluciones_operation_scope", "unique": True},
        },
        {
            "keys": {"state": 1, "lease_until": 1},
            "options": {"name": "idx_sheets_devoluciones_operations_state_lease"},
        },
    ]
