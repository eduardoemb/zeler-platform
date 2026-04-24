from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_webhook_events_schema_requires_topic_and_idempotency_fields() -> None:
    schema = json.loads(
        (ROOT / "infra/mongo/schemas/webhook_events.json").read_text(encoding="utf-8")
    )
    json_schema = schema["$jsonSchema"]

    assert {"_id", "topic", "user_id", "resource", "received_at", "raw_body", "source_ip"}.issubset(
        set(json_schema["required"])
    )
    assert json_schema["properties"]["topic"]["bsonType"] == "string"
    assert json_schema["properties"]["received_at"]["bsonType"] == "date"


def test_webhook_events_indexes_include_ttl_and_debug_indexes() -> None:
    indexes = json.loads(
        (ROOT / "infra/mongo/indexes/webhook_events.json").read_text(encoding="utf-8")
    )

    assert {
        "keys": {"received_at": 1},
        "options": {"expireAfterSeconds": 3888000, "name": "ttl_received_at_45d"},
    } in indexes
    assert {
        "keys": {"topic": 1, "received_at": -1},
        "options": {"name": "topic_received_at_desc"},
    } in indexes
    assert {
        "keys": {"user_id": 1, "received_at": -1},
        "options": {"name": "user_id_received_at_desc"},
    } in indexes
