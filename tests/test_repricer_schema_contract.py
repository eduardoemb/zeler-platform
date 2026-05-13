from __future__ import annotations

import json
from pathlib import Path

from infra.mongo.validator_contract import validate_document_against_schema

ROOT = Path(__file__).resolve().parents[1]


def test_repricer_rules_validator_rejects_missing_required_fields() -> None:
    validator = json.loads((ROOT / "infra/mongo/schemas/repricer_rules.json").read_text())

    result = validate_document_against_schema({"_id": "rule-1"}, validator)

    assert result.valid is False
    assert result.missing_required_fields == [
        "seller_id",
        "item_id",
        "strategy",
        "min_price",
        "max_price",
        "active",
        "updated_at",
        "schema_version",
    ]


def test_repricer_history_validator_rejects_missing_required_fields() -> None:
    validator = json.loads((ROOT / "infra/mongo/schemas/repricer_history.json").read_text())

    result = validate_document_against_schema({"_id": "history-1"}, validator)

    assert result.valid is False
    assert result.missing_required_fields == [
        "seller_id",
        "item_id",
        "old_price",
        "new_price",
        "reason",
        "applied_at",
        "schema_version",
    ]


def test_repricer_indexes_match_phase4_contract() -> None:
    rules_indexes = json.loads((ROOT / "infra/mongo/indexes/repricer_rules.json").read_text())
    history_indexes = json.loads((ROOT / "infra/mongo/indexes/repricer_history.json").read_text())

    assert rules_indexes == [
        {
            "keys": {"seller_id": 1, "active": 1},
            "options": {"name": "idx_repricer_rules_seller_active"},
        },
        {
            "keys": {"item_id": 1},
            "options": {
                "name": "uniq_repricer_rules_item_active",
                "unique": True,
                "partialFilterExpression": {"active": True},
            },
        },
    ]
    assert history_indexes == [
        {
            "keys": {"applied_at": 1},
            "options": {
                "name": "idx_repricer_history_applied_at_ttl",
                "expireAfterSeconds": 31536000,
            },
        },
        {
            "keys": {"item_id": 1, "applied_at": -1},
            "options": {"name": "idx_repricer_history_item_applied_at"},
        },
        {
            "keys": {"seller_id": 1, "applied_at": -1},
            "options": {"name": "idx_repricer_history_seller_applied_at"},
        },
    ]


def test_repricer_phase1_foundation_validators_require_canonical_fields() -> None:
    expectations = {
        "repricer_catalog_rules.json": [
            "seller_id",
            "account_id",
            "item_id",
            "strategy",
            "min_price",
            "max_price",
            "active",
            "execution_state",
            "created_at",
            "updated_at",
            "created_by",
            "updated_by",
            "schema_version",
        ],
        "repricer_limits.json": [
            "seller_id",
            "account_id",
            "enabled",
            "min_price_limit",
            "max_price_limit",
            "undercut_delta",
            "pause_competition",
            "escalate_to_manual_review",
            "created_at",
            "updated_at",
            "schema_version",
        ],
        "repricer_allies.json": [
            "seller_id",
            "allies",
            "created_at",
            "updated_at",
            "schema_version",
        ],
        "repricer_bulk_jobs.json": [
            "seller_id",
            "account_id",
            "status",
            "source_filename",
            "total_rows",
            "processed_rows",
            "success_rows",
            "failed_rows",
            "created_at",
            "updated_at",
            "created_by",
            "schema_version",
        ],
        "repricer_bulk_rows.json": [
            "seller_id",
            "account_id",
            "job_id",
            "row_number",
            "status",
            "payload",
            "created_at",
            "updated_at",
            "schema_version",
        ],
        "repricer_reports.json": [
            "seller_id",
            "account_id",
            "report_type",
            "format",
            "status",
            "storage_path",
            "row_count",
            "created_at",
            "updated_at",
            "requested_by",
            "schema_version",
        ],
        "repricer_monitoring_snapshots.json": [
            "seller_id",
            "account_id",
            "generated_at",
            "worker_heartbeat_at",
            "queue_backlog",
            "error_buckets",
            "active_bulk_job_ids",
            "schema_version",
        ],
    }

    for schema_name, missing_fields in expectations.items():
        validator = json.loads((ROOT / "infra/mongo/schemas" / schema_name).read_text())

        result = validate_document_against_schema({"_id": schema_name.removesuffix(".json")}, validator)

        assert result.valid is False
        assert result.missing_required_fields == missing_fields


def test_repricer_phase1_foundation_indexes_match_access_patterns() -> None:
    expectations = {
        "repricer_catalog_rules.json": [
            {
                "keys": {"seller_id": 1, "account_id": 1, "active": 1, "item_id": 1},
                "options": {"name": "idx_repricer_catalog_rules_scope_active_item"},
            },
            {
                "keys": {"seller_id": 1, "account_id": 1, "item_id": 1},
                "options": {
                    "name": "uniq_repricer_catalog_rules_scope_item_active",
                    "unique": True,
                    "partialFilterExpression": {"active": True},
                },
            },
            {
                "keys": {"item_id": "text", "sku": "text", "title": "text"},
                "options": {"name": "text_repricer_catalog_rules_lookup"},
            },
        ],
        "repricer_limits.json": [
            {
                "keys": {"seller_id": 1, "account_id": 1},
                "options": {"name": "uniq_repricer_limits_scope", "unique": True},
            }
        ],
        "repricer_allies.json": [
            {
                "keys": {"seller_id": 1},
                "options": {"name": "uniq_repricer_allies_seller", "unique": True},
            }
        ],
        "repricer_bulk_jobs.json": [
            {
                "keys": {"seller_id": 1, "created_at": -1},
                "options": {"name": "idx_repricer_bulk_jobs_seller_created_at"},
            },
            {
                "keys": {"seller_id": 1, "account_id": 1, "status": 1},
                "options": {"name": "idx_repricer_bulk_jobs_scope_status"},
            },
        ],
        "repricer_bulk_rows.json": [
            {
                "keys": {"job_id": 1, "status": 1},
                "options": {"name": "idx_repricer_bulk_rows_job_status"},
            },
            {
                "keys": {"seller_id": 1, "account_id": 1, "job_id": 1, "row_number": 1},
                "options": {"name": "uniq_repricer_bulk_rows_scope_job_row", "unique": True},
            },
        ],
        "repricer_reports.json": [
            {
                "keys": {"seller_id": 1, "created_at": -1},
                "options": {"name": "idx_repricer_reports_seller_created_at"},
            },
            {
                "keys": {"seller_id": 1, "account_id": 1, "report_type": 1, "status": 1},
                "options": {"name": "idx_repricer_reports_scope_type_status"},
            },
        ],
        "repricer_monitoring_snapshots.json": [
            {
                "keys": {"seller_id": 1, "generated_at": -1},
                "options": {"name": "idx_repricer_monitoring_snapshots_seller_generated_at"},
            },
            {
                "keys": {"account_id": 1, "generated_at": -1},
                "options": {"name": "idx_repricer_monitoring_snapshots_account_generated_at"},
            },
        ],
    }

    for index_name, expected_indexes in expectations.items():
        indexes = json.loads((ROOT / "infra/mongo/indexes" / index_name).read_text())

        assert indexes == expected_indexes
