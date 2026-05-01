from __future__ import annotations

import json
from pathlib import Path

SCHEMA_PATH = Path("infra/mongo/schemas/bootstrap_jobs.json")


def test_schema_allows_dispatch_attempts_and_triggered_by() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))["$jsonSchema"]
    properties = schema["properties"]

    assert properties["dispatch_attempts"]["bsonType"] == "int"
    assert properties["dispatch_attempts"]["minimum"] == 0
    assert "oauth_callback" in properties["triggered_by"]["enum"]
    assert "retry" in properties["triggered_by"]["enum"]


def test_existing_doc_without_fields_still_validates() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))["$jsonSchema"]

    assert "dispatch_attempts" not in schema["required"]
    assert "triggered_by" not in schema["required"]
