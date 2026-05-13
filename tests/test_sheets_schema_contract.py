from __future__ import annotations

import json
from pathlib import Path

from infra.mongo.validator_contract import validate_document_against_schema

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
            "keys": {"seller_id": 1, "normalized_sku": 1, "item_id": 1},
            "options": {"name": "idx_sheets_item_sku_index_seller_sku_item"},
        },
        {
            "keys": {"seller_id": 1, "item_id": 1},
            "options": {"name": "idx_sheets_item_sku_index_seller_item"},
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
    }

    for file_name, missing_fields in expected.items():
        validator = json.loads((ROOT / "infra/mongo/schemas" / file_name).read_text())
        result = validate_document_against_schema({"_id": "doc-1"}, validator)
        assert result.valid is False
        assert result.missing_required_fields == missing_fields


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
