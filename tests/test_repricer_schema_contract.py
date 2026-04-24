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
