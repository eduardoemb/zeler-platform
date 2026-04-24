from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv
from infra.mongo.apply_validators import DEFAULT_MONGO_URI, apply_validators
from infra.mongo.validator_contract import (
    canonical_validator_files,
    validate_document_against_schema,
)
from pymongo import MongoClient
from pymongo.errors import PyMongoError, WriteError

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def test_canonical_validator_contract_covers_phase3_collections() -> None:
    assert canonical_validator_files(ROOT / "infra" / "mongo" / "schemas") == {
        "meli_accounts.json",
        "users.json",
        "items.json",
        "orders.json",
        "questions.json",
        "messages.json",
        "shipments.json",
        "claims.json",
        "events.json",
        "fulldock_history.json",
        "fulldock_inventory_rules.json",
        "webhook_events.json",
        "bootstrap_jobs.json",
        "module_registry.json",
        "repricer_rules.json",
        "repricer_history.json",
        "audit_log.json",
    }


@pytest.mark.parametrize(
    "schema_file", sorted(canonical_validator_files(ROOT / "infra" / "mongo" / "schemas"))
)
def test_canonical_validators_reject_documents_missing_required_fields(schema_file: str) -> None:
    payload = json.loads(
        (ROOT / "infra" / "mongo" / "schemas" / schema_file).read_text(encoding="utf-8")
    )

    result = validate_document_against_schema({"schema_version": 1}, payload)

    assert result.valid is False
    assert result.missing_required_fields


def test_live_dev_mongo_canonical_validators_reject_invalid_documents() -> None:
    mongo_uri = os.environ.get("MONGO_URI", DEFAULT_MONGO_URI)
    client: MongoClient[dict[str, object]] = MongoClient(mongo_uri, serverSelectionTimeoutMS=1000)
    try:
        client.admin.command("ping")
    except PyMongoError as exc:  # pragma: no cover - only for machines without local Docker Mongo
        pytest.skip(f"local Mongo is not available: {exc}")

    database = client.get_default_database()
    schema_files = canonical_validator_files(ROOT / "infra" / "mongo" / "schemas")
    try:
        for schema_file in schema_files:
            database.drop_collection(Path(schema_file).stem)
        apply_validators(mongo_uri, ROOT / "infra" / "mongo" / "schemas")

        for schema_file in sorted(schema_files):
            collection_name = Path(schema_file).stem
            with pytest.raises(WriteError, match="Document failed validation"):
                database[collection_name].insert_one({"schema_version": 1})
    finally:
        for schema_file in schema_files:
            database.drop_collection(Path(schema_file).stem)
        client.close()
