from __future__ import annotations

import json
from pathlib import Path

from infra.mongo.validator_contract import validate_document_against_schema

ROOT = Path(__file__).resolve().parents[2]


def test_publicador_foundation_validators_require_scope_version_and_status_fields() -> None:
    expectations = {
        "publicador_drafts.json": [
            "seller_id",
            "account_id",
            "sku",
            "source_product",
            "generated_listing",
            "status",
            "enrichment_status",
            "approval_status",
            "process_status",
            "created_at",
            "updated_at",
            "created_by",
            "schema_version",
        ],
        "publicador_assets.json": [
            "seller_id",
            "account_id",
            "owner_type",
            "owner_id",
            "sku",
            "storage_uri",
            "content_type",
            "width",
            "height",
            "status",
            "created_at",
            "updated_at",
            "schema_version",
        ],
        "publicador_batches.json": [
            "seller_id",
            "account_id",
            "source_filename",
            "idempotency_key",
            "status",
            "total_items",
            "publishable_items",
            "blocked_items",
            "created_at",
            "updated_at",
            "created_by",
            "schema_version",
        ],
        "publicador_batch_items.json": [
            "seller_id",
            "account_id",
            "batch_id",
            "row_number",
            "sku",
            "parsed_fields",
            "status",
            "created_at",
            "updated_at",
            "schema_version",
        ],
        "publicador_catalog_suggestions.json": [
            "seller_id",
            "account_id",
            "status",
            "created_at",
            "updated_at",
            "schema_version",
        ],
        "publicador_events.json": [
            "seller_id",
            "account_id",
            "aggregate_type",
            "aggregate_id",
            "operation",
            "status",
            "created_at",
            "schema_version",
        ],
        "publicador_settings.json": [
            "seller_id",
            "account_id",
            "defaults",
            "ai_provider_ref",
            "catalog_behavior",
            "created_at",
            "updated_at",
            "schema_version",
        ],
        "publicador_ai_generations.json": [
            "seller_id",
            "account_id",
            "provider",
            "model",
            "config_fingerprint",
            "redacted_input",
            "status",
            "created_at",
            "schema_version",
        ],
    }

    for schema_name, missing_fields in expectations.items():
        validator = json.loads((ROOT / "infra/mongo/schemas" / schema_name).read_text())

        result = validate_document_against_schema(
            {"_id": schema_name.removesuffix(".json")}, validator
        )

        assert result.valid is False
        assert result.missing_required_fields == missing_fields


def test_publicador_foundation_indexes_match_access_patterns() -> None:
    expectations = {
        "publicador_drafts.json": [
            {
                "keys": {"seller_id": 1, "account_id": 1, "status": 1, "updated_at": -1},
                "options": {"name": "idx_publicador_drafts_scope_status_updated"},
            },
            {
                "keys": {"seller_id": 1, "account_id": 1, "sku": 1},
                "options": {
                    "name": "uniq_publicador_drafts_scope_sku",
                    "unique": True,
                    "partialFilterExpression": {"sku": {"$exists": True}},
                },
            },
            {"keys": {"meli_item_id": 1}, "options": {"name": "idx_publicador_drafts_meli_item"}},
        ],
        "publicador_assets.json": [
            {
                "keys": {"seller_id": 1, "owner_id": 1, "status": 1},
                "options": {"name": "idx_publicador_assets_seller_owner_status"},
            },
            {
                "keys": {"seller_id": 1, "hash": 1},
                "options": {
                    "name": "uniq_publicador_assets_seller_hash",
                    "unique": True,
                    "partialFilterExpression": {"hash": {"$exists": True}},
                },
            },
        ],
        "publicador_batches.json": [
            {
                "keys": {"seller_id": 1, "account_id": 1, "idempotency_key": 1},
                "options": {"name": "uniq_publicador_batches_scope_idempotency", "unique": True},
            },
            {
                "keys": {"seller_id": 1, "status": 1, "created_at": -1},
                "options": {"name": "idx_publicador_batches_seller_status_created"},
            },
        ],
        "publicador_batch_items.json": [
            {
                "keys": {"batch_id": 1, "status": 1},
                "options": {"name": "idx_publicador_batch_items_batch_status"},
            },
            {
                "keys": {"batch_id": 1, "sku": 1},
                "options": {"name": "uniq_publicador_batch_items_batch_sku", "unique": True},
            },
            {
                "keys": {"seller_id": 1, "sku": 1},
                "options": {"name": "idx_publicador_batch_items_seller_sku"},
            },
        ],
        "publicador_catalog_suggestions.json": [
            {
                "keys": {"seller_id": 1, "status": 1, "updated_at": -1},
                "options": {"name": "idx_publicador_catalog_suggestions_seller_status_updated"},
            },
            {
                "keys": {"draft_id": 1},
                "options": {"name": "idx_publicador_catalog_suggestions_draft"},
            },
        ],
        "publicador_events.json": [
            {
                "keys": {"seller_id": 1, "created_at": -1},
                "options": {"name": "idx_publicador_events_seller_created"},
            },
            {
                "keys": {"aggregate_type": 1, "aggregate_id": 1},
                "options": {"name": "idx_publicador_events_aggregate"},
            },
        ],
        "publicador_settings.json": [
            {
                "keys": {"seller_id": 1, "account_id": 1},
                "options": {"name": "uniq_publicador_settings_scope", "unique": True},
            }
        ],
        "publicador_ai_generations.json": [
            {
                "keys": {"seller_id": 1, "created_at": -1},
                "options": {"name": "idx_publicador_ai_generations_seller_created"},
            },
            {"keys": {"draft_id": 1}, "options": {"name": "idx_publicador_ai_generations_draft"}},
        ],
    }

    for index_name, expected_indexes in expectations.items():
        indexes = json.loads((ROOT / "infra/mongo/indexes" / index_name).read_text())

        assert indexes == expected_indexes
