from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from infra.mongo.validator_contract import validate_document_against_schema

from zeler_platform_core.cli.export_schemas import ENTITY_SCHEMAS, _validator_payload

ROOT = Path(__file__).resolve().parents[1]

LISTING_FEE_PROJECTION_REQUIRED_FIELDS = [
    "source",
    "site_id",
    "currency_id",
    "price",
    "listing_type_id",
    "category_id",
    "sale_fee_amount",
    "percentage_fee",
    "synced_at",
]
LISTING_FEE_PROJECTION_FIELDS = [
    *LISTING_FEE_PROJECTION_REQUIRED_FIELDS,
    "shipping_mode",
    "logistic_type",
    "billable_weight",
    "tags",
    "gross_amount",
    "fixed_fee",
    "meli_percentage_fee",
    "financing_add_on_fee",
]
REMAINING_PHASE4_READ_MODEL_REQUIRED_FIELDS = {
    "sheets_read_model_freshness": [
        "seller_id",
        "read_model",
        "state",
        "fresh_until",
        "updated_at",
        "schema_version",
    ],
    "sheets_catalog_buybox_snapshots": [
        "seller_id",
        "item_id",
        "catalog_product_id",
        "snapshot_at",
        "source",
        "schema_version",
    ],
    "sheets_catalog_product_snapshots": [
        "seller_id",
        "catalog_product_id",
        "snapshot_at",
        "source",
        "schema_version",
    ],
    "sheets_catalog_time_metrics": [
        "seller_id",
        "item_id",
        "date_from",
        "date_to",
        "winning_hours",
        "available_hours",
        "source",
        "schema_version",
    ],
    "sheets_full_withdrawals": [
        "seller_id",
        "withdrawal_id",
        "created_at",
        "source",
        "schema_version",
    ],
    "sheets_price_history_snapshots": [
        "seller_id",
        "item_id",
        "prices",
        "snapshot_at",
        "source",
        "observation_basis",
        "schema_version",
    ],
    "sheets_stock_time_metrics": [
        "seller_id",
        "item_id",
        "date_from",
        "date_to",
        "total_hours",
        "source",
        "schema_version",
    ],
    "sheets_stockout_snapshots": [
        "seller_id",
        "item_id",
        "observed_at",
        "source",
        "observation_basis",
        "schema_version",
    ],
}
REMAINING_PHASE4_INDEX_NAMES = {
    "sheets_read_model_freshness": [
        "uniq_sheets_read_model_freshness_seller_model",
        "idx_sheets_read_model_freshness_seller_state_until",
    ],
    "sheets_catalog_buybox_snapshots": [
        "idx_sheets_catalog_buybox_snapshots_seller_item",
        "idx_sheets_catalog_buybox_snapshots_seller_catalog",
    ],
    "sheets_catalog_product_snapshots": [
        "idx_sheets_catalog_product_snapshots_seller_catalog",
    ],
    "sheets_catalog_time_metrics": [
        "idx_sheets_catalog_time_metrics_seller_item_range",
    ],
    "sheets_full_withdrawals": [
        "idx_sheets_full_withdrawals_seller_created",
        "idx_sheets_full_withdrawals_seller_withdrawal",
    ],
    "sheets_price_history_snapshots": [
        "idx_sheets_price_history_snapshots_seller_item",
    ],
    "sheets_stock_time_metrics": [
        "idx_sheets_stock_time_metrics_seller_item_range",
        "idx_sheets_stock_time_metrics_seller_sku_range",
    ],
    "sheets_stockout_snapshots": [
        "idx_sheets_stockout_snapshots_seller_item",
        "idx_sheets_stockout_snapshots_seller_state_observed",
    ],
}


def assert_bounded_listing_fee_projection_schema(projection: dict[str, Any]) -> None:
    properties = projection["properties"]

    assert projection["additionalProperties"] is False
    assert projection["required"] == LISTING_FEE_PROJECTION_REQUIRED_FIELDS
    assert sorted(properties) == sorted(LISTING_FEE_PROJECTION_FIELDS)
    assert properties["source"] == {"enum": ["/sites/{site}/listing_prices"]}
    assert properties["site_id"] == {"bsonType": "string"}
    assert properties["currency_id"] == {"bsonType": "string"}
    assert properties["price"] == {"bsonType": ["decimal", "double", "int", "long"]}
    assert properties["shipping_mode"] == {"bsonType": ["string", "null"]}
    assert properties["logistic_type"] == {"bsonType": ["string", "null"]}
    assert properties["billable_weight"] == {
        "bsonType": ["decimal", "double", "int", "long", "null"]
    }
    assert properties["tags"] == {"bsonType": "array"}
    assert properties["sale_fee_amount"] == {"bsonType": ["decimal", "double", "int", "long"]}
    assert properties["percentage_fee"] == {"bsonType": ["decimal", "double", "int", "long"]}
    assert "raw_payload" not in properties
    assert "sale_fee_details" not in properties
    assert "sale_fee" not in properties
    assert "details" not in properties


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
        {
            "keys": {
                "seller_id": 1,
                "item_id": 1,
                "variation_id": 1,
                "normalized_sku": 1,
                "_id": 1,
            },
            "options": {"name": "idx_sheets_item_formula_rows_seller_publication_order"},
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


def test_remaining_phase4_read_model_schemas_are_exported_and_bounded() -> None:
    for collection, missing_fields in REMAINING_PHASE4_READ_MODEL_REQUIRED_FIELDS.items():
        assert collection in ENTITY_SCHEMAS
        validator = json.loads((ROOT / "infra/mongo/schemas" / f"{collection}.json").read_text())
        schema = validator["$jsonSchema"]

        result = validate_document_against_schema({"_id": "doc-1"}, validator)

        assert result.valid is False
        assert result.missing_required_fields == missing_fields
        assert schema["additionalProperties"] is False
        if collection != "sheets_read_model_freshness":
            assert schema["properties"]["source"] == {
                "enum": [
                    "sheets_event_persistence",
                    "sheets_backfill",
                    "historical_meli_backfill",
                    "manual_reconciliation",
                ]
            }


def test_catalog_snapshot_schemas_support_formula_handler_fields() -> None:
    product_schema = json.loads(
        (ROOT / "infra/mongo/schemas/sheets_catalog_product_snapshots.json").read_text()
    )["$jsonSchema"]
    buybox_schema = json.loads(
        (ROOT / "infra/mongo/schemas/sheets_catalog_buybox_snapshots.json").read_text()
    )["$jsonSchema"]

    assert product_schema["additionalProperties"] is False
    assert product_schema["properties"]["attributes"] == {"bsonType": ["array", "object", "null"]}
    assert buybox_schema["additionalProperties"] is False
    assert buybox_schema["properties"]["title"] == {"bsonType": ["string", "null"]}
    assert buybox_schema["properties"]["available_quantity"] == {
        "bsonType": ["int", "long", "null"]
    }
    assert buybox_schema["properties"]["price"] == {
        "bsonType": ["decimal", "double", "int", "long", "null"]
    }
    assert buybox_schema["properties"]["competitor_count"] == {"bsonType": ["int", "long", "null"]}
    assert "winner_count" not in buybox_schema["properties"]


def test_remaining_phase4_read_model_indexes_match_formula_access_patterns() -> None:
    for collection, expected_names in REMAINING_PHASE4_INDEX_NAMES.items():
        indexes = json.loads((ROOT / "infra/mongo/indexes" / f"{collection}.json").read_text())

        assert [index["options"]["name"] for index in indexes] == expected_names


def test_seller_unit_costs_validator_and_indexes_match_contract() -> None:
    validator = json.loads((ROOT / "infra/mongo/schemas/seller_unit_costs.json").read_text())
    indexes = json.loads((ROOT / "infra/mongo/indexes/seller_unit_costs.json").read_text())

    result = validate_document_against_schema({"_id": "cost-1"}, validator)

    assert result.valid is False
    assert result.missing_required_fields == [
        "seller_id",
        "unit_cost",
        "currency",
        "source",
        "status",
        "effective_from",
        "created_at",
        "updated_at",
        "schema_version",
    ]
    schema = validator["$jsonSchema"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["source"] == {"enum": ["manual", "import"]}
    assert schema["properties"]["status"] == {"enum": ["active", "inactive"]}
    assert [index["options"]["name"] for index in indexes] == [
        "idx_seller_unit_costs_seller_identity_status_effective",
        "idx_seller_unit_costs_seller_item_variation",
        "idx_seller_unit_costs_seller_sku",
        "uniq_seller_unit_costs_active_identity_effective",
    ]
    assert indexes[-1]["options"] == {
        "name": "uniq_seller_unit_costs_active_identity_effective",
        "unique": True,
        "partialFilterExpression": {"status": "active"},
    }


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
    assert current_properties["shipping_mode"] == {"bsonType": ["string", "null"]}
    assert current_properties["logistic_type"] == {"bsonType": ["string", "null"]}
    assert current_properties["shipping_payer"] == {"bsonType": ["string", "null"]}
    assert current_properties["billable_weight"] == {
        "bsonType": ["int", "long", "double", "decimal", "null"]
    }
    assert current_properties["tags"] == {"bsonType": "array"}
    assert current_properties["currency_id"] == {"bsonType": ["string", "null"]}
    assert current_properties["site_id"] == {"bsonType": ["string", "null"]}
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


def test_sheets_item_formula_rows_schema_supports_bounded_current_promotion_only() -> None:
    validator = json.loads((ROOT / "infra/mongo/schemas/sheets_item_formula_rows.json").read_text())
    current_promotion = validator["$jsonSchema"]["properties"]["current"]["properties"][
        "current_promotion"
    ]

    assert current_promotion["additionalProperties"] is False
    assert current_promotion["required"] == [
        "source",
        "sale_amount",
        "regular_amount",
        "currency_id",
        "reference_at",
        "synced_at",
    ]
    assert "raw_payload" not in current_promotion["properties"]
    assert "prices" not in current_promotion["properties"]


def test_sheets_item_formula_rows_schema_supports_bounded_listing_price_fixed_fee_only() -> None:
    validator = json.loads((ROOT / "infra/mongo/schemas/sheets_item_formula_rows.json").read_text())
    projection = validator["$jsonSchema"]["properties"]["current"]["properties"][
        "listing_price_fixed_fee"
    ]

    assert projection["additionalProperties"] is False
    assert projection["required"] == ["source", "fixed_fee", "currency_id", "synced_at", "params"]
    assert projection["properties"]["source"] == {"enum": ["/sites/{site}/listing_prices"]}
    assert projection["properties"]["params"]["additionalProperties"] is False
    assert "raw_payload" not in projection["properties"]
    assert "buyer" not in projection["properties"]


def test_sheets_item_formula_rows_schema_supports_bounded_listing_fee_projection_only() -> None:
    validator = json.loads((ROOT / "infra/mongo/schemas/sheets_item_formula_rows.json").read_text())
    current_properties = validator["$jsonSchema"]["properties"]["current"]["properties"]

    assert_bounded_listing_fee_projection_schema(current_properties["listing_fee_projection"])


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
    assert schema["properties"]["billable_weight"] == {
        "bsonType": ["decimal", "double", "int", "long", "null"]
    }
    assert schema["properties"]["tags"] == {"bsonType": "array"}
    assert schema["properties"]["currency_id"] == {"bsonType": ["string", "null"]}
    assert schema["properties"]["site_id"] == {"bsonType": ["string", "null"]}
    fixed_fee = schema["properties"]["listing_price_fixed_fee"]
    assert fixed_fee["additionalProperties"] is False
    assert fixed_fee["required"] == ["source", "fixed_fee", "currency_id", "synced_at", "params"]
    assert fixed_fee["properties"]["source"] == {"enum": ["/sites/{site}/listing_prices"]}
    assert fixed_fee["properties"]["params"]["additionalProperties"] is False
    assert_bounded_listing_fee_projection_schema(schema["properties"]["listing_fee_projection"])
    current_promotion = schema["properties"]["current_promotion"]
    assert current_promotion["additionalProperties"] is False
    assert current_promotion["required"] == [
        "source",
        "sale_amount",
        "regular_amount",
        "currency_id",
        "reference_at",
        "synced_at",
    ]
    assert "raw_payload" not in current_promotion["properties"]
    assert "prices" not in current_promotion["properties"]
    assert "raw_payload" not in fixed_fee["properties"]
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


def test_shipments_schema_supports_bounded_real_shipping_cost_projection_only() -> None:
    validator = json.loads((ROOT / "infra/mongo/schemas/shipments.json").read_text())
    schema = validator["$jsonSchema"]
    projection = schema["properties"]["real_shipping_cost"]

    assert projection["additionalProperties"] is False
    assert projection["bsonType"] == ["object", "null"]
    assert projection["required"] == ["source", "seller_cost", "synced_at"]
    assert projection["properties"] == {
        "source": {"enum": ["/shipments/{shipment_id}/costs"]},
        "seller_cost": {"bsonType": ["decimal", "double", "int", "long"]},
        "receiver_cost": {"bsonType": ["decimal", "double", "int", "long", "null"]},
        "currency_id": {"bsonType": ["string", "null"]},
        "matched_sender_id": {"bsonType": ["string", "null"]},
        "synced_at": {"bsonType": "date"},
    }
    for forbidden_field in ("raw_payload", "senders", "receiver", "buyer", "address", "token"):
        assert forbidden_field not in projection["properties"]


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
    assert "seller_unit_costs" in manifest.owned_collections
    assert "google_oauth_state" not in manifest.owned_collections


def test_sheets_manifest_allows_listing_prices_scope() -> None:
    from zeler_platform_core.runtime.manifest import validate_manifest

    manifest = validate_manifest("modules/sheets/manifest.yaml")

    assert "GET /sites/*/listing_prices" in manifest.allowed_meli_scopes


def test_sheets_manifest_allows_catalog_product_scope() -> None:
    from zeler_platform_core.runtime.manifest import validate_manifest

    manifest = validate_manifest("modules/sheets/manifest.yaml")

    assert "GET /products/*" in manifest.allowed_meli_scopes
    assert "POST /products/*" not in manifest.allowed_meli_scopes
