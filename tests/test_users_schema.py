from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from bson import Int64, ObjectId
from dotenv import load_dotenv
from infra.mongo.apply_validators import DEFAULT_MONGO_URI, apply_validators
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError, PyMongoError, WriteError

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = ROOT / "infra" / "mongo" / "schemas"
load_dotenv(ROOT / ".env")


@pytest.fixture
def users_collection() -> Any:
    mongo_uri = os.environ.get("MONGO_URI", DEFAULT_MONGO_URI)
    client: MongoClient[dict[str, Any]] = MongoClient(
        mongo_uri, serverSelectionTimeoutMS=1000, tz_aware=True
    )
    try:
        client.admin.command("ping")
    except PyMongoError as exc:  # pragma: no cover - only for machines without local Docker Mongo
        pytest.skip(f"local Mongo is not available: {exc}")

    database = client.get_default_database()
    database.drop_collection("users")
    apply_validators(mongo_uri, SCHEMAS_DIR)
    yield database["users"]
    database.drop_collection("users")
    client.close()


def _valid_user_doc(email: str = "operator@example.com") -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "_id": ObjectId(),
        "email": email,
        "name": "Operator One",
        "auth_provider": "local",
        "created_at": now,
        "updated_at": now,
        "meli_account_ids": [Int64(123456789)],
        "roles": ["user"],
        "status": "active",
    }


def test_users_schema_rejects_missing_email(users_collection: Any) -> None:
    invalid_doc = _valid_user_doc()
    invalid_doc.pop("email")

    with pytest.raises(WriteError, match="Document failed validation"):
        users_collection.insert_one(invalid_doc)


def test_users_schema_rejects_invalid_auth_provider(users_collection: Any) -> None:
    invalid_doc = _valid_user_doc()
    invalid_doc["auth_provider"] = "password"

    with pytest.raises(WriteError, match="Document failed validation"):
        users_collection.insert_one(invalid_doc)


def test_users_schema_rejects_duplicate_email(users_collection: Any) -> None:
    users_collection.insert_one(_valid_user_doc("operator@example.com"))

    with pytest.raises(DuplicateKeyError):
        users_collection.insert_one(_valid_user_doc("operator@example.com"))


def test_users_schema_accepts_valid_doc(users_collection: Any) -> None:
    valid_doc = _valid_user_doc()

    result = users_collection.insert_one(valid_doc)

    assert result.inserted_id == valid_doc["_id"]
    assert users_collection.count_documents({"email": "operator@example.com"}) == 1
