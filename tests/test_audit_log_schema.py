from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from bson import Int64, ObjectId
from dotenv import load_dotenv
from infra.mongo.apply_validators import apply_validators
from pymongo import MongoClient
from pymongo.errors import PyMongoError, WriteError

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = ROOT / "infra" / "mongo" / "schemas"
load_dotenv(ROOT / ".env")


@pytest.fixture
def audit_log_collection(default_mongo_uri: str) -> Any:
    mongo_uri = default_mongo_uri
    client: MongoClient[dict[str, Any]] = MongoClient(
        mongo_uri, serverSelectionTimeoutMS=1000, tz_aware=True
    )
    try:
        client.admin.command("ping")
    except PyMongoError as exc:  # pragma: no cover - only for machines without local Docker Mongo
        pytest.skip(f"local Mongo is not available: {exc}")

    database = client.get_default_database()
    database.drop_collection("audit_log")
    apply_validators(mongo_uri, SCHEMAS_DIR)
    yield database["audit_log"]
    database.drop_collection("audit_log")
    client.close()


def _valid_audit_log_doc() -> dict[str, Any]:
    return {
        "_id": ObjectId(),
        "at": datetime.now(UTC),
        "module_id": "repricer",
        "seller_id": Int64(123456789),
        "method": "GET",
        "path": "/items/MLA123",
        "upstream_status": 200,
        "status": 200,
        "duration_ms": 12,
        "trace_id": "trace-1",
        "schema_version": 1,
    }


def test_audit_log_schema_rejects_missing_module_id(audit_log_collection: Any) -> None:
    invalid_doc = _valid_audit_log_doc()
    invalid_doc.pop("module_id")

    with pytest.raises(WriteError, match="Document failed validation"):
        audit_log_collection.insert_one(invalid_doc)


def test_audit_log_schema_rejects_missing_at(audit_log_collection: Any) -> None:
    invalid_doc = _valid_audit_log_doc()
    invalid_doc.pop("at")

    with pytest.raises(WriteError, match="Document failed validation"):
        audit_log_collection.insert_one(invalid_doc)


def test_audit_log_schema_accepts_valid_doc(audit_log_collection: Any) -> None:
    valid_doc = _valid_audit_log_doc()

    result = audit_log_collection.insert_one(valid_doc)

    assert result.inserted_id == valid_doc["_id"]
    assert audit_log_collection.count_documents({"module_id": "repricer"}) == 1


def test_audit_log_ttl_index_is_created(audit_log_collection: Any) -> None:
    index = audit_log_collection.index_information()["ttl_audit_log_at_365d"]

    assert index["key"] == [("at", 1)]
    assert index["expireAfterSeconds"] == 31_536_000
