from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from bson import Int64
from dotenv import load_dotenv
from infra.mongo.apply_validators import DEFAULT_MONGO_URI, apply_validators
from pymongo import MongoClient
from pymongo.errors import PyMongoError, WriteError

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = ROOT / "infra" / "mongo" / "schemas"
load_dotenv(ROOT / ".env")


@pytest.fixture
def rate_limit_counters_collection() -> Any:
    mongo_uri = os.environ.get("MONGO_URI", DEFAULT_MONGO_URI)
    client: MongoClient[dict[str, Any]] = MongoClient(
        mongo_uri, serverSelectionTimeoutMS=1000, tz_aware=True
    )
    try:
        client.admin.command("ping")
    except PyMongoError as exc:  # pragma: no cover - only for machines without local Docker Mongo
        pytest.skip(f"local Mongo is not available: {exc}")

    database = client.get_default_database()
    database.drop_collection("rate_limit_counters")
    apply_validators(mongo_uri, SCHEMAS_DIR)
    yield database["rate_limit_counters"]
    database.drop_collection("rate_limit_counters")
    client.close()


def _valid_rate_limit_doc() -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "_id": "repricer:123456789",
        "module_id": "repricer",
        "seller_id": Int64(123456789),
        "window_start": now.replace(second=0, microsecond=0),
        "count": 1,
        "updated_at": now,
    }


def test_rate_limit_counters_schema_rejects_missing_module_id(
    rate_limit_counters_collection: Any,
) -> None:
    invalid_doc = _valid_rate_limit_doc()
    invalid_doc.pop("module_id")

    with pytest.raises(WriteError, match="Document failed validation"):
        rate_limit_counters_collection.insert_one(invalid_doc)


def test_rate_limit_counters_schema_rejects_negative_count(
    rate_limit_counters_collection: Any,
) -> None:
    invalid_doc = _valid_rate_limit_doc()
    invalid_doc["count"] = -1

    with pytest.raises(WriteError, match="Document failed validation"):
        rate_limit_counters_collection.insert_one(invalid_doc)


def test_rate_limit_counters_schema_accepts_valid_doc(
    rate_limit_counters_collection: Any,
) -> None:
    valid_doc = _valid_rate_limit_doc()

    result = rate_limit_counters_collection.insert_one(valid_doc)

    assert result.inserted_id == valid_doc["_id"]
    assert rate_limit_counters_collection.count_documents({"module_id": "repricer"}) == 1


def test_rate_limit_counters_ttl_index_is_created(rate_limit_counters_collection: Any) -> None:
    index = rate_limit_counters_collection.index_information()["ttl_rate_limit_updated_at_120s"]

    assert index["key"] == [("updated_at", 1)]
    assert index["expireAfterSeconds"] == 120
