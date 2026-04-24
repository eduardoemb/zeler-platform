from __future__ import annotations

import json
from pathlib import Path

from infra.mongo.validator_contract import validate_document_against_schema

ROOT = Path(__file__).resolve().parents[1]


def test_autoreply_templates_validator_rejects_missing_required_fields() -> None:
    validator = json.loads((ROOT / "infra/mongo/schemas/autoreply_templates.json").read_text())

    result = validate_document_against_schema({"_id": "template-1"}, validator)

    assert result.valid is False
    assert result.missing_required_fields == [
        "seller_id",
        "template_name",
        "match_type",
        "pattern",
        "answer_text",
        "enabled",
        "created_at",
        "updated_at",
        "schema_version",
    ]


def test_autoreply_history_validator_rejects_missing_required_fields() -> None:
    validator = json.loads((ROOT / "infra/mongo/schemas/autoreply_history.json").read_text())

    result = validate_document_against_schema({"_id": "history-1"}, validator)

    assert result.valid is False
    assert result.missing_required_fields == [
        "seller_id",
        "event_id",
        "idempotency_key",
        "resource_type",
        "resource_id",
        "outcome",
        "created_at",
        "schema_version",
    ]


def test_autoreply_indexes_match_phase6_contract() -> None:
    templates_indexes = json.loads(
        (ROOT / "infra/mongo/indexes/autoreply_templates.json").read_text()
    )
    history_indexes = json.loads((ROOT / "infra/mongo/indexes/autoreply_history.json").read_text())

    assert templates_indexes == [
        {
            "keys": {"seller_id": 1, "template_name": 1},
            "options": {"name": "idx_autoreply_templates_seller_name", "unique": True},
        },
        {
            "keys": {"seller_id": 1, "enabled": 1, "updated_at": -1},
            "options": {"name": "idx_autoreply_templates_seller_enabled_updated"},
        },
    ]
    assert history_indexes == [
        {
            "keys": {"idempotency_key": 1},
            "options": {"name": "idx_autoreply_history_idempotency", "unique": True},
        },
        {
            "keys": {"seller_id": 1, "created_at": -1},
            "options": {"name": "idx_autoreply_history_seller_created"},
        },
        {
            "keys": {"seller_id": 1, "resource_type": 1, "resource_id": 1},
            "options": {"name": "idx_autoreply_history_resource"},
        },
    ]
