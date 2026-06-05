from __future__ import annotations

import json
from pathlib import Path

from infra.mongo.validator_contract import validate_document_against_schema

from zeler_platform_core.cli.export_schemas import ENTITY_SCHEMAS, _validator_payload

ROOT = Path(__file__).resolve().parents[1]


def test_sheets_exports_validator_rejects_missing_required_fields() -> None:
    validator = json.loads((ROOT / "infra/mongo/schemas/sheets_exports.json").read_text())

    result = validate_document_against_schema({"_id": "export-1"}, validator)

    assert result.valid is False
    assert result.missing_required_fields == [
        "seller_id",
        "spreadsheet_id",
        "worksheet_name",
        "enabled",
        "created_at",
        "updated_at",
        "schema_version",
    ]


def test_sheets_sync_jobs_validator_rejects_missing_required_fields() -> None:
    validator = json.loads((ROOT / "infra/mongo/schemas/sheets_sync_jobs.json").read_text())

    result = validate_document_against_schema({"_id": "sync-1"}, validator)

    assert result.valid is False
    assert result.missing_required_fields == [
        "seller_id",
        "spreadsheet_id",
        "state",
        "requested_at",
        "updated_at",
        "schema_version",
    ]


def test_google_oauth_tokens_validator_rejects_missing_required_fields() -> None:
    validator = json.loads((ROOT / "infra/mongo/schemas/google_oauth_tokens.json").read_text())

    result = validate_document_against_schema({"_id": "google-token-seller-1"}, validator)

    assert result.valid is False
    assert result.missing_required_fields == [
        "seller_id",
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
        "connected_at",
        "created_at",
        "updated_at",
        "schema_version",
    ]


def test_google_oauth_state_validator_rejects_missing_required_fields() -> None:
    validator = json.loads((ROOT / "infra/mongo/schemas/google_oauth_state.json").read_text())

    result = validate_document_against_schema({"_id": "state-token"}, validator)

    assert result.valid is False
    assert result.missing_required_fields == [
        "seller_id",
        "code_verifier",
        "created_at",
    ]


def test_sheets_indexes_match_phase6_contract() -> None:
    exports_indexes = json.loads((ROOT / "infra/mongo/indexes/sheets_exports.json").read_text())
    sync_indexes = json.loads((ROOT / "infra/mongo/indexes/sheets_sync_jobs.json").read_text())
    audit_indexes = json.loads((ROOT / "infra/mongo/indexes/sheets_formula_audit.json").read_text())
    sku_index_indexes = json.loads(
        (ROOT / "infra/mongo/indexes/sheets_item_sku_index.json").read_text()
    )
    formula_row_indexes = json.loads(
        (ROOT / "infra/mongo/indexes/sheets_item_formula_rows.json").read_text()
    )

    assert exports_indexes == [
        {
            "keys": {"seller_id": 1, "enabled": 1},
            "options": {"name": "idx_sheets_exports_seller_enabled"},
        },
        {
            "keys": {"spreadsheet_id": 1},
            "options": {"name": "idx_sheets_exports_spreadsheet"},
        },
    ]
    assert sync_indexes == [
        {
            "keys": {"seller_id": 1, "state": 1, "updated_at": -1},
            "options": {"name": "idx_sheets_sync_jobs_seller_state_updated"},
        }
    ]
    assert audit_indexes == [
        {
            "keys": {"token_id": 1, "seller_id": 1, "formula": 1, "occurred_at": -1},
            "options": {"name": "idx_sheets_formula_audit_token_seller_formula_time"},
        },
        {
            "keys": {"request_id": 1},
            "options": {"name": "idx_sheets_formula_audit_request", "sparse": True},
        },
    ]
    assert sku_index_indexes == [
        {
            "keys": {"seller_id": 1, "normalized_sku": 1, "item_id": 1, "variation_id": 1},
            "options": {"name": "idx_sheets_item_sku_index_seller_sku_item_variation"},
        },
        {
            "keys": {"seller_id": 1, "item_id": 1, "variation_id": 1},
            "options": {"name": "idx_sheets_item_sku_index_seller_item_variation"},
        },
    ]
    assert formula_row_indexes == [
        {
            "keys": {"seller_id": 1, "normalized_sku": 1, "item_id": 1},
            "options": {"name": "idx_sheets_item_formula_rows_seller_sku_item"},
        },
        {
            "keys": {"seller_id": 1, "item_id": 1},
            "options": {"name": "idx_sheets_item_formula_rows_seller_item"},
        },
        {
            "keys": {"seller_id": 1, "inventory_id": 1},
            "options": {"name": "idx_sheets_item_formula_rows_seller_inventory"},
        },
    ]


def test_item_status_history_indexes_match_forward_only_access_patterns() -> None:
    transition_indexes = json.loads(
        (ROOT / "infra/mongo/indexes/item_status_transitions.json").read_text()
    )
    state_indexes = json.loads((ROOT / "infra/mongo/indexes/item_status_states.json").read_text())

    assert transition_indexes == [
        {
            "keys": {"seller_id": 1, "item_id": 1, "observed_at": -1},
            "options": {"name": "idx_item_status_transitions_seller_item_observed"},
        },
        {
            "keys": {
                "seller_id": 1,
                "item_id": 1,
                "from_status": 1,
                "to_status": 1,
                "observed_at": 1,
            },
            "options": {"name": "uniq_item_status_transition_observation", "unique": True},
        },
    ]
    assert state_indexes == [
        {
            "keys": {"seller_id": 1, "item_id": 1},
            "options": {"name": "uniq_item_status_states_seller_item", "unique": True},
        },
        {
            "keys": {"seller_id": 1, "current_status": 1, "last_observed_at": -1},
            "options": {"name": "idx_item_status_states_seller_status_last_observed"},
        },
    ]


def test_sheets_formula_foundation_validators_reject_missing_required_fields() -> None:
    expected = {
        "sheets_formula_audit.json": [
            "token_id",
            "seller_id",
            "formula",
            "outcome",
            "occurred_at",
            "schema_version",
        ],
        "sheets_item_sku_index.json": [
            "seller_id",
            "normalized_sku",
            "item_id",
            "schema_version",
        ],
        "sheets_item_formula_rows.json": [
            "seller_id",
            "normalized_sku",
            "item_id",
            "current",
            "schema_version",
        ],
        "item_status_transitions.json": [
            "seller_id",
            "item_id",
            "from_status",
            "to_status",
            "observed_at",
            "source",
            "schema_version",
        ],
        "item_status_states.json": [
            "seller_id",
            "item_id",
            "current_status",
            "first_observed_at",
            "last_observed_at",
            "schema_version",
        ],
    }

    for file_name, missing_fields in expected.items():
        validator = json.loads((ROOT / "infra/mongo/schemas" / file_name).read_text())
        result = validate_document_against_schema({"_id": "doc-1"}, validator)
        assert result.valid is False
        assert result.missing_required_fields == missing_fields


def test_sheets_item_sku_index_schema_supports_v2_identity_fields() -> None:
    validator = json.loads((ROOT / "infra/mongo/schemas/sheets_item_sku_index.json").read_text())
    schema = validator["$jsonSchema"]

    assert schema["required"] == ["_id", "seller_id", "normalized_sku", "item_id", "schema_version"]
    assert schema["properties"]["identity_level"] == {"enum": ["item", "variation"]}
    assert schema["properties"]["source"] == {
        "enum": [
            "item_attribute",
            "variation_attribute",
            "variation_seller_custom_field",
            "order_line",
        ]
    }
    assert schema["properties"]["variation_id"] == {"bsonType": ["string", "long", "int", "null"]}


def test_sheets_item_formula_rows_schema_supports_current_shipping_fields() -> None:
    validator = json.loads((ROOT / "infra/mongo/schemas/sheets_item_formula_rows.json").read_text())
    current_properties = validator["$jsonSchema"]["properties"]["current"]["properties"]

    assert current_properties["shipping_logistic_type"] == {"bsonType": ["string", "null"]}
    assert current_properties["shipping_payer"] == {"bsonType": ["string", "null"]}
    assert current_properties["listing_type_id"] == {"bsonType": ["string", "null"]}
    assert current_properties["seller_shipping_cost"] == {
        "bsonType": ["int", "long", "double", "decimal", "null"]
    }


def test_sheets_item_formula_rows_schema_supports_status_history_scalars() -> None:
    validator = json.loads((ROOT / "infra/mongo/schemas/sheets_item_formula_rows.json").read_text())
    current_properties = validator["$jsonSchema"]["properties"]["current"]["properties"]

    assert current_properties["status_started_at"] == {"bsonType": ["date", "null"]}
    assert current_properties["paused_since"] == {"bsonType": ["date", "null"]}
    assert current_properties["last_status_change_at"] == {"bsonType": ["date", "null"]}


def test_item_status_history_schemas_require_real_observation_sources() -> None:
    transition = json.loads(
        (ROOT / "infra/mongo/schemas/item_status_transitions.json").read_text()
    )["$jsonSchema"]
    state = json.loads((ROOT / "infra/mongo/schemas/item_status_states.json").read_text())[
        "$jsonSchema"
    ]

    assert transition["properties"]["observed_at"] == {"bsonType": "date"}
    assert transition["properties"]["source"] == {"enum": ["sheets_event_persistence"]}
    assert "webhook_received_at" not in transition["properties"]
    assert "last_updated" not in transition["properties"]
    assert state["properties"]["paused_since"] == {"bsonType": ["date", "null"]}
    assert state["properties"]["status_started_at"] == {"bsonType": ["date", "null"]}
    assert state["properties"]["last_status_change_at"] == {"bsonType": ["date", "null"]}


def test_items_schema_supports_v2_formula_fields_without_raw_payload_drift() -> None:
    validator = json.loads((ROOT / "infra/mongo/schemas/items.json").read_text())
    schema = validator["$jsonSchema"]

    assert schema["additionalProperties"] is False
    assert schema["properties"]["permalink"] == {"bsonType": ["string", "null"]}
    assert schema["properties"]["thumbnail"] == {"bsonType": ["string", "null"]}
    assert schema["properties"]["catalog_product_id"] == {"bsonType": ["string", "null"]}
    assert schema["properties"]["inventory_id"] == {"bsonType": ["string", "null"]}
    assert schema["properties"]["listing_type_id"] == {"bsonType": ["string", "null"]}
    assert schema["properties"]["seller_shipping_cost"] == {
        "bsonType": ["decimal", "double", "int", "long", "null"]
    }
    assert "raw_payload_blob" not in schema["properties"]
    assert schema["required"] == [
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
    ]


def test_canonical_items_schema_exports_status_history_date_fields() -> None:
    committed_schema = json.loads((ROOT / "infra/mongo/schemas/items.json").read_text())[
        "$jsonSchema"
    ]
    generated_schema = _validator_payload(ENTITY_SCHEMAS["items"])["$jsonSchema"]

    expected = {"bsonType": ["date", "null"]}
    for field_name in (
        "status_observed_at",
        "status_started_at",
        "paused_since",
        "last_status_change_at",
    ):
        assert committed_schema["properties"][field_name] == expected
        assert generated_schema["properties"][field_name] == expected
        assert field_name not in generated_schema["required"]


def test_google_oauth_indexes_match_contract() -> None:
    tokens_indexes = json.loads((ROOT / "infra/mongo/indexes/google_oauth_tokens.json").read_text())
    state_indexes = json.loads((ROOT / "infra/mongo/indexes/google_oauth_state.json").read_text())

    assert tokens_indexes == [
        {
            "keys": {"seller_id": 1},
            "options": {"name": "uniq_google_oauth_tokens_seller", "unique": True},
        },
        {
            "keys": {"status": 1, "expires_at": 1},
            "options": {"name": "idx_google_oauth_tokens_status_expires_at"},
        },
        {
            "keys": {"lock_held_until": 1},
            "options": {"name": "idx_google_oauth_tokens_lock_held_until_sparse", "sparse": True},
        },
    ]
    assert state_indexes == [
        {
            "keys": {"created_at": 1},
            "options": {"name": "ttl_google_oauth_state_created_at", "expireAfterSeconds": 600},
        }
    ]


def test_sheets_manifest_owns_google_oauth_tokens_not_transient_state() -> None:
    from zeler_platform_core.runtime.manifest import validate_manifest

    manifest = validate_manifest("modules/sheets/manifest.yaml")

    assert "google_oauth_tokens" in manifest.owned_collections
    assert "google_oauth_state" not in manifest.owned_collections
