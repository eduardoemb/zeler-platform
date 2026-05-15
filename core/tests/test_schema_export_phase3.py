from __future__ import annotations

import json
from pathlib import Path

import pytest

from zeler_platform_core.cli.export_schemas import (
    CANONICAL_SCHEMA_FILES,
    export_schemas,
    validate_export_drift,
)
from zeler_platform_core.models import current_schema_version


def test_export_schemas_writes_mongo_wrapped_validators(tmp_path: Path) -> None:
    written = export_schemas(tmp_path)

    assert set(written) == CANONICAL_SCHEMA_FILES
    payload = json.loads((tmp_path / "items.json").read_text(encoding="utf-8"))
    assert payload["validationLevel"] == "strict"
    assert payload["validationAction"] == "error"
    schema = payload["$jsonSchema"]
    assert schema["bsonType"] == "object"
    assert "seller_id" in schema["required"]
    assert schema["properties"]["schema_version"]["bsonType"] == "int"


def test_schema_export_detects_committed_schema_drift(tmp_path: Path) -> None:
    export_schemas(tmp_path)
    (tmp_path / "items.json").write_text('{"stale": true}\n', encoding="utf-8")

    drift = validate_export_drift(tmp_path)

    assert drift == ["items.json"]


def test_current_schema_version_returns_current_version_for_canonical_entities() -> None:
    assert current_schema_version("items") == 2
    assert current_schema_version("meli_accounts") == 1

    with pytest.raises(KeyError):
        current_schema_version("legacy_collection")
