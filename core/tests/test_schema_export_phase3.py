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


def test_exported_items_schema_includes_listing_price_fixed_fee_projection(tmp_path: Path) -> None:
    export_schemas(tmp_path)
    payload = json.loads((tmp_path / "items.json").read_text(encoding="utf-8"))
    schema = payload["$jsonSchema"]
    projection = schema["properties"]["listing_price_fixed_fee"]

    assert schema["properties"]["currency_id"] == {"bsonType": ["string", "null"]}
    assert schema["properties"]["site_id"] == {"bsonType": ["string", "null"]}
    assert projection["additionalProperties"] is False
    assert projection["required"] == ["source", "fixed_fee", "currency_id", "synced_at", "params"]
    assert projection["properties"]["source"] == {"enum": ["/sites/{site}/listing_prices"]}
    assert projection["properties"]["params"]["additionalProperties"] is False
    assert projection["properties"]["params"]["required"] == [
        "site_id",
        "category_id",
        "price",
        "currency_id",
        "listing_type_id",
    ]


def test_module_registry_schema_exposes_optional_display_identity(tmp_path: Path) -> None:
    export_schemas(tmp_path)
    payload = json.loads((tmp_path / "module_registry.json").read_text(encoding="utf-8"))
    schema = payload["$jsonSchema"]
    display_identity = schema["properties"]["display_identity"]

    assert "display_identity" not in schema["required"]
    assert display_identity == {
        "bsonType": "object",
        "properties": {
            "availability": {"enum": ["active", "retired"]},
            "display_name": {"bsonType": "string"},
            "legacy_display_name": {"bsonType": ["string", "null"]},
        },
        "required": ["display_name", "availability"],
    }


def test_shipment_schema_export_includes_sanitized_real_shipping_cost_projection(
    tmp_path: Path,
) -> None:
    export_schemas(tmp_path)
    payload = json.loads((tmp_path / "shipments.json").read_text(encoding="utf-8"))
    schema = payload["$jsonSchema"]
    projection = schema["properties"]["real_shipping_cost"]

    assert projection["additionalProperties"] is False
    assert projection["bsonType"] == ["object", "null"]
    assert projection["required"] == ["source", "seller_cost", "synced_at"]
    assert projection["properties"] == {
        "source": {"enum": ["/shipments/{shipment_id}/costs"]},
        "seller_cost": {"bsonType": ["decimal", "double", "int", "long"]},
        "receiver_cost": {"bsonType": ["decimal", "double", "int", "long", "null"]},
        "currency_id": {"bsonType": ["string", "null"]},
        "matched_sender_id": {"bsonType": ["string", "null"]},
        "synced_at": {"bsonType": "date"},
    }
    for forbidden_field in ("raw_payload", "senders", "receiver", "buyer", "address", "token"):
        assert forbidden_field not in projection["properties"]


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
