from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]


def _bootstrap_jobs_validator() -> dict[str, Any]:
    payload = json.loads(
        (ROOT / "infra" / "mongo" / "schemas" / "bootstrap_jobs.json").read_text(encoding="utf-8")
    )
    return cast(dict[str, Any], payload["$jsonSchema"])


def _legacy_document() -> dict[str, Any]:
    now = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)
    return {
        "_id": "job-1",
        "seller_id": "123",
        "state": "pending",
        "dag": {},
        "checkpoints": {},
        "created_at": now,
        "updated_at": now,
        "schema_version": 1,
    }


def _validate_h4_bounds(document: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = schema["required"]
    errors.extend(field for field in required if field not in document)
    properties = schema["properties"]
    if "attempt_count" in document:
        attempt = document["attempt_count"]
        attempt_schema = properties["attempt_count"]
        if not isinstance(attempt, int) or attempt < attempt_schema["minimum"]:
            errors.append("attempt_count")
    if "last_error" in document:
        last_error = document["last_error"]
        max_length = properties["last_error"]["maxLength"]
        if last_error is not None and len(last_error) > max_length:
            errors.append("last_error")
    return errors


def test_bootstrap_jobs_schema_accepts_legacy_document_without_h4_fields() -> None:
    schema = _bootstrap_jobs_validator()

    assert _validate_h4_bounds(_legacy_document(), schema) == []
    assert "attempt_count" not in schema["required"]
    assert "failed_at" not in schema["required"]
    assert "last_error" not in schema["required"]
    assert "additionalProperties" not in schema


def test_bootstrap_jobs_schema_accepts_new_h4_fields() -> None:
    schema = _bootstrap_jobs_validator()
    document = {
        **_legacy_document(),
        "attempt_count": 1,
        "failed_at": datetime(2026, 4, 24, 12, 5, tzinfo=UTC),
        "last_error": "RuntimeError: boom",
    }

    assert _validate_h4_bounds(document, schema) == []


def test_bootstrap_jobs_schema_rejects_h4_bounds_violations() -> None:
    schema = _bootstrap_jobs_validator()

    assert _validate_h4_bounds({**_legacy_document(), "last_error": "x" * 1025}, schema) == [
        "last_error"
    ]
    assert _validate_h4_bounds({**_legacy_document(), "attempt_count": -1}, schema) == [
        "attempt_count"
    ]
