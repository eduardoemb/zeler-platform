from __future__ import annotations

import json
from pathlib import Path

from infra.mongo.validator_contract import validate_document_against_schema

ROOT = Path(__file__).resolve().parents[1]


def test_publicador_drafts_validator_rejects_missing_required_fields() -> None:
    validator = json.loads((ROOT / "infra/mongo/schemas/publicador_drafts.json").read_text())

    result = validate_document_against_schema({"_id": "draft-1"}, validator)

    assert result.valid is False
    assert result.missing_required_fields == [
        "seller_id",
        "source_product",
        "generated_listing",
        "status",
        "created_at",
        "updated_at",
        "schema_version",
    ]


def test_publicador_history_validator_rejects_missing_required_fields() -> None:
    validator = json.loads((ROOT / "infra/mongo/schemas/publicador_history.json").read_text())

    result = validate_document_against_schema({"_id": "history-1"}, validator)

    assert result.valid is False
    assert result.missing_required_fields == [
        "seller_id",
        "draft_id",
        "action",
        "outcome",
        "created_at",
        "schema_version",
    ]


def test_publicador_indexes_match_phase6_contract() -> None:
    drafts_indexes = json.loads((ROOT / "infra/mongo/indexes/publicador_drafts.json").read_text())
    history_indexes = json.loads((ROOT / "infra/mongo/indexes/publicador_history.json").read_text())

    assert drafts_indexes == [
        {
            "keys": {"seller_id": 1, "status": 1, "updated_at": -1},
            "options": {"name": "idx_publicador_drafts_seller_status_updated"},
        }
    ]
    assert history_indexes == [
        {
            "keys": {"seller_id": 1, "created_at": -1},
            "options": {"name": "idx_publicador_history_seller_created"},
        },
        {
            "keys": {"draft_id": 1},
            "options": {"name": "idx_publicador_history_draft"},
        },
    ]
