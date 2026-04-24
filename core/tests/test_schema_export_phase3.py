from __future__ import annotations

import json
from pathlib import Path

from zeler_platform_core.cli.export_schemas import export_schemas


def test_export_schemas_writes_mongo_wrapped_validators(tmp_path: Path) -> None:
    written = export_schemas(tmp_path)

    assert "items.json" in written
    payload = json.loads((tmp_path / "items.json").read_text(encoding="utf-8"))
    schema = payload["$jsonSchema"]
    assert schema["bsonType"] == "object"
    assert "seller_id" in schema["required"]
    assert schema["properties"]["schema_version"]["bsonType"] == "int"
