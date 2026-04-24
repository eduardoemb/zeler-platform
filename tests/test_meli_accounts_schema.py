from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from bson import Int64, ObjectId
from dotenv import load_dotenv
from infra.mongo.apply_validators import DEFAULT_MONGO_URI, apply_validators
from pymongo import MongoClient
from pymongo.errors import PyMongoError, WriteError

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = ROOT / "infra" / "mongo" / "schemas"
load_dotenv(ROOT / ".env")


@pytest.fixture
def meli_accounts_collection() -> Any:
    import os

    mongo_uri = os.environ.get("MONGO_URI", DEFAULT_MONGO_URI)
    client: MongoClient[dict[str, Any]] = MongoClient(mongo_uri, serverSelectionTimeoutMS=1000)
    try:
        client.admin.command("ping")
    except PyMongoError as exc:  # pragma: no cover - only for machines without local Docker Mongo
        pytest.skip(f"local Mongo is not available: {exc}")

    database = client.get_default_database()
    database.drop_collection("meli_accounts")
    apply_validators(mongo_uri, SCHEMAS_DIR)
    yield database["meli_accounts"]
    database.drop_collection("meli_accounts")
    client.close()


def _valid_meli_account_doc() -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "_id": ObjectId(),
        "seller_id": Int64(123456789),
        "nickname": "TEST_SELLER",
        "app_id": "zeler-platform",
        "platform_user_id": "platform-user-123",
        "access_token_ciphertext": "access-ciphertext-base64",
        "access_token_dek_wrapped": "access-dek-wrapped-base64",
        "refresh_token_ciphertext": "refresh-ciphertext-base64",
        "refresh_token_dek_wrapped": "refresh-dek-wrapped-base64",
        "token_nonce": "nonce-base64",
        "refresh_token_nonce": "refresh-nonce-base64",
        "scopes": ["read", "write"],
        "status": "active",
        "expires_at": now,
        "created_at": now,
        "updated_at": now,
        "kms_key_version": (
            "projects/zeler-platform-dev/locations/us-central1/keyRings/zeler-platform/"
            "cryptoKeys/meli-tokens/cryptoKeyVersions/1"
        ),
        "schema_version": 1,
    }


def test_meli_accounts_schema_rejects_missing_required_field(meli_accounts_collection: Any) -> None:
    invalid_doc = _valid_meli_account_doc()
    invalid_doc.pop("access_token_ciphertext")

    with pytest.raises(WriteError, match="Document failed validation"):
        meli_accounts_collection.insert_one(invalid_doc)


def test_meli_accounts_schema_accepts_valid_doc(meli_accounts_collection: Any) -> None:
    valid_doc = _valid_meli_account_doc()

    result = meli_accounts_collection.insert_one(valid_doc)

    assert result.inserted_id == valid_doc["_id"]
    assert meli_accounts_collection.count_documents({"seller_id": 123456789}) == 1


def test_meli_accounts_indexes_are_created(meli_accounts_collection: Any) -> None:
    index_names = set(meli_accounts_collection.index_information())

    assert "uniq_meli_accounts_seller_app" in index_names
    assert "idx_meli_accounts_status_expires_at" in index_names
    assert "idx_meli_accounts_lock_held_until_sparse" in index_names
