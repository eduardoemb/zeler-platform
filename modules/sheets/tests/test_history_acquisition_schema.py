from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from infra.mongo.apply_validators import apply_validators
from pydantic import ValidationError
from pymongo import MongoClient
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError, WriteError

from zeler_platform_core.cli.export_schemas import export_schemas
from zeler_platform_core.models import (
    SheetsHistoryAcquisition,
    SheetsHistoryOrderRange,
    SheetsHistoryReceipt,
)

COLLECTION = "sheets_history_acquisitions"
RECEIPTS = "sheets_history_receipts"
RANGES = "sheets_history_order_ranges"
ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 9, 15, tzinfo=UTC)


def document(**changes: Any) -> dict[str, Any]:
    return SheetsHistoryAcquisition.model_validate(
        {
            "_id": "head",
            "seller_id": "82453304",
            "read_model": "orders",
            "plan_id": "plan",
            "scope_id": "orders:20260815:20260915",
            "job_id": "job",
            "date_from": NOW - timedelta(days=31),
            "date_to": NOW,
            "created_at": NOW,
            "updated_at": NOW,
            **changes,
        }
    ).model_dump(by_alias=True)


@pytest.fixture
def schema_db(tmp_path: Path) -> Iterator[Database[dict[str, Any]]]:
    """An absent export becomes an empty validator to expose actual Mongo acceptance."""
    name = f"zeler_history_schema_{uuid4().hex}"
    uri = f"mongodb://127.0.0.1:27028/{name}?directConnection=true"
    client: MongoClient[dict[str, Any]] = MongoClient(uri, serverSelectionTimeoutMS=2000)
    hello = client.admin.command("hello")
    assert hello["isWritablePrimary"] and hello["setName"] == "rs0"
    generated = tmp_path / "generated"
    export_schemas(generated)
    schemas = tmp_path / "schemas"
    indexes = tmp_path / "indexes"
    schemas.mkdir()
    indexes.mkdir()
    for collection in (COLLECTION, RECEIPTS, RANGES):
        exported = generated / f"{collection}.json"
        (schemas / exported.name).write_text(exported.read_text() if exported.exists() else "{}")
        index = ROOT / "infra/mongo/indexes" / exported.name
        if index.exists():
            (indexes / index.name).write_text(index.read_text())
    try:
        results = apply_validators(uri, schemas)
        repeated = apply_validators(uri, schemas)
        for collection in (COLLECTION, RECEIPTS, RANGES):
            assert results[collection] == "created"
            assert repeated[collection] == "unchanged"
        yield client[name]
    finally:
        client.drop_database(name)
        client.close()


def range_document(**changes: Any) -> dict[str, Any]:
    return SheetsHistoryOrderRange.model_validate(
        {
            "_id": "range",
            "acquisition_id": "head",
            "seller_id": "82453304",
            "generation": 1,
            "pass_number": 1,
            "node_id": "root",
            "root_id": "root",
            "date_from": NOW - timedelta(days=31),
            "date_to": NOW,
            **changes,
        }
    ).model_dump(by_alias=True)


@pytest.mark.parametrize("field", list(range_document()))
def test_range_schema_requires_fields(schema_db: Database[dict[str, Any]], field: str) -> None:
    payload = range_document()
    del payload[field]
    with pytest.raises(WriteError) as error:
        schema_db[RANGES].insert_one(payload)
    assert error.value.code == 121


@pytest.mark.parametrize(
    "changes",
    [
        {"next_offset": True},
        {"depth": 13},
        {"source_total": -1},
        {"unknown": 1},
        {"state": "completed"},
        {"state": "enumerated", "source_total": None},
        {"state": "split", "source_total": 1, "next_offset": 1},
    ],
)
def test_range_schema_rejects_structural_errors(
    schema_db: Database[dict[str, Any]], changes: dict[str, Any]
) -> None:
    with pytest.raises(WriteError) as error:
        schema_db[RANGES].insert_one({**range_document(), **changes})
    assert error.value.code == 121


@pytest.mark.parametrize("state", ["pending", "split", "enumerated"])
def test_range_schema_accepts_valid_states(schema_db: Database[dict[str, Any]], state: str) -> None:
    payload = range_document(
        state=state,
        source_total=10001 if state == "split" else 1,
        next_offset=1 if state == "enumerated" else 0,
    )
    schema_db[RANGES].insert_one(payload)
    assert schema_db[RANGES].count_documents({}) == 1


def test_range_indexes_bind_acquisition_pass_and_preserve_nodes(
    schema_db: Database[dict[str, Any]],
) -> None:
    collection = schema_db[RANGES]
    collection.insert_one(range_document())
    with pytest.raises(DuplicateKeyError):
        collection.insert_one(range_document(_id="duplicate"))
    collection.insert_one(range_document(_id="other", acquisition_id="other"))
    collection.insert_one(range_document(_id="second-pass", pass_number=2))
    indexes = collection.index_information()
    unique = indexes["uniq_sheets_history_order_range"]
    assert unique["unique"] is True
    assert unique["key"] == [
        ("acquisition_id", 1),
        ("generation", 1),
        ("pass_number", 1),
        ("node_id", 1),
    ]
    assert indexes["idx_sheets_history_order_range_pending"]["key"] == [
        ("acquisition_id", 1),
        ("generation", 1),
        ("pass_number", 1),
        ("state", 1),
        ("date_from", 1),
        ("node_id", 1),
    ]
    assert all("expireAfterSeconds" not in index for index in indexes.values())


@pytest.mark.parametrize("read_model", ["orders", "questions"])
@pytest.mark.parametrize("phase", ["discover", "completed"])
def test_head_schema_accepts_full_model_dump(
    schema_db: Database[dict[str, Any]], read_model: str, phase: str
) -> None:
    changes: dict[str, Any] = {"read_model": read_model, "phase": phase}
    if read_model == "questions":
        changes.update(scope_id="seller_scan", date_from=NOW - timedelta(days=365))
    if phase == "completed":
        changes.update(source_total=0, observed_from=NOW, observed_until=NOW)
    payload = document(**changes)
    schema_db[COLLECTION].insert_one(payload)
    assert schema_db[COLLECTION].count_documents({}) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"schema_version": True},
        {"schema_version": 2},
        {"generation": False},
        {"generation": 0},
        {"discovered_count": -1},
        {"fetched_count": 1.5},
        {"published_count": "1"},
        {"source_total": True},
        {"next_cursor": True},
        {"drift_restarts": 4},
        {"seller_id": 82453304},
        {"seller_id": "seller"},
        {"_id": " "},
        {"read_model": "items"},
        {"phase": "invalid"},
        {"scope_id": "seller_scan"},
        {"next_cursor": "scan"},
        {"date_from": "2026-08-15"},
        {"unexpected": "field"},
        {"phase": "completed"},
    ],
)
def test_head_schema_rejects_structurally_invalid_bson(
    schema_db: Database[dict[str, Any]], changes: dict[str, Any]
) -> None:
    with pytest.raises(WriteError) as rejected:
        schema_db[COLLECTION].insert_one({**document(), **changes})
    assert rejected.value.code == 121


@pytest.mark.parametrize("missing", ["seller_id", "generation", "phase", "next_cursor"])
def test_head_schema_requires_persisted_fields(
    schema_db: Database[dict[str, Any]], missing: str
) -> None:
    payload = document()
    del payload[missing]
    with pytest.raises(WriteError) as rejected:
        schema_db[COLLECTION].insert_one(payload)
    assert rejected.value.code == 121


def test_scope_index_is_unique_but_seller_scoped(schema_db: Database[dict[str, Any]]) -> None:
    schema_db[COLLECTION].insert_one(document())
    with pytest.raises(DuplicateKeyError):
        schema_db[COLLECTION].insert_one(document(_id="duplicate"))
    schema_db[COLLECTION].insert_one(document(_id="other-seller", seller_id="2"))
    schema_db[COLLECTION].insert_one(document(_id="other-plan", plan_id="second"))
    assert schema_db[COLLECTION].count_documents({}) == 3


def test_mongo_structure_does_not_replace_relational_model_validation(
    schema_db: Database[dict[str, Any]],
) -> None:
    payload = {**document(), "date_from": NOW + timedelta(days=1)}
    schema_db[COLLECTION].insert_one(payload)
    with pytest.raises(ValidationError):
        SheetsHistoryAcquisition.model_validate(payload)


def test_committed_head_schema_matches_export(tmp_path: Path) -> None:
    export_schemas(tmp_path)
    generated = json.loads((tmp_path / f"{COLLECTION}.json").read_text())
    committed = json.loads((ROOT / "infra/mongo/schemas" / f"{COLLECTION}.json").read_text())
    assert generated == committed


def receipt(**changes: Any) -> dict[str, Any]:
    return SheetsHistoryReceipt.model_validate(
        {
            "_id": "receipt",
            "acquisition_id": "head",
            "seller_id": "82453304",
            "read_model": "orders",
            "generation": 1,
            "pass_number": 1,
            "page_sequence": 0,
            "kind": "membership",
            "resource_id": "200001",
            "observed_at": NOW,
            **changes,
        }
    ).model_dump(by_alias=True)


@pytest.mark.parametrize("read_model", ["orders", "questions"])
@pytest.mark.parametrize("kind", ["membership", "detail", "exclusion"])
def test_receipt_schema_accepts_full_model_dump(
    schema_db: Database[dict[str, Any]], read_model: str, kind: str
) -> None:
    changes: dict[str, Any] = {"read_model": read_model, "kind": kind, "source_hash": "b" * 64}
    if kind == "detail":
        changes.update(
            payload={"id": 200001}, payload_hash="a" * 64, unavailable_fields=["buyer_id"]
        )
    if kind == "exclusion":
        changes.update(exclusion_reason="outside_subscribed_intervals", source_version="revision-2")
    schema_db[RECEIPTS].insert_one(receipt(**changes))
    assert schema_db[RECEIPTS].count_documents({}) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"schema_version": True},
        {"schema_version": 2},
        {"generation": 0},
        {"pass_number": False},
        {"page_sequence": -1},
        {"seller_id": 82453304},
        {"read_model": "items"},
        {"acquisition_id": " "},
        {"resource_id": ""},
        {"observed_at": "2026-09-15"},
        {"source_version": 1},
        {"source_hash": "G" * 64},
        {"kind": "invalid"},
        {"payload": {"id": 200001}},
        {"payload_hash": "a" * 64},
        {"unavailable_fields": ["buyer_id"]},
        {"exclusion_reason": "absent"},
        {"kind": "exclusion"},
        {"kind": "detail", "payload": {}, "payload_hash": "a" * 64},
        {"kind": "detail", "payload": {"id": 200001}, "payload_hash": "bad"},
        {"unexpected": True},
    ],
)
def test_receipt_schema_rejects_invalid_bson(
    schema_db: Database[dict[str, Any]], changes: dict[str, Any]
) -> None:
    with pytest.raises(WriteError) as rejected:
        schema_db[RECEIPTS].insert_one({**receipt(), **changes})
    assert rejected.value.code == 121


@pytest.mark.parametrize("missing", [field for field in receipt() if field != "source_payload"])
def test_receipt_schema_requires_every_persisted_field(
    schema_db: Database[dict[str, Any]], missing: str
) -> None:
    payload = receipt()
    del payload[missing]
    with pytest.raises(WriteError) as rejected:
        schema_db[RECEIPTS].insert_one(payload)
    assert rejected.value.code == 121


@pytest.mark.parametrize(
    "changes",
    [
        {"payload_hash": None},
        {"payload": []},
        {"unavailable_fields": ["buyer_id", "buyer_id"]},
        {"unavailable_fields": [""]},
        {"exclusion_reason": "absent"},
    ],
)
def test_receipt_detail_rejects_mixed_or_missing_evidence(
    schema_db: Database[dict[str, Any]], changes: dict[str, Any]
) -> None:
    payload = receipt(kind="detail", payload={"id": 200001}, payload_hash="a" * 64)
    with pytest.raises(WriteError) as rejected:
        schema_db[RECEIPTS].insert_one({**payload, **changes})
    assert rejected.value.code == 121


def test_receipt_indexes_reject_replay_duplicates_and_order_pages(
    schema_db: Database[dict[str, Any]],
) -> None:
    collection = schema_db[RECEIPTS]
    collection.insert_one(receipt())
    with pytest.raises(DuplicateKeyError):
        collection.insert_one(receipt(_id="duplicate"))
    for field, value in (("acquisition_id", "other"), ("generation", 2), ("pass_number", 2)):
        collection.insert_one(receipt(_id=field, **{field: value}))
    collection.insert_one(
        receipt(_id="detail", kind="detail", payload={"id": 200001}, payload_hash="a" * 64)
    )
    collection.insert_one(receipt(_id="late", page_sequence=1, resource_id="100000"))
    collection.insert_one(receipt(_id="same-page", resource_id="300001"))
    indexes = collection.index_information()
    unique_keys = [
        (field, 1)
        for field in ("acquisition_id", "generation", "pass_number", "kind", "resource_id")
    ]
    ordered_keys = unique_keys[:-1] + [("page_sequence", 1), ("resource_id", 1)]
    assert indexes["uniq_history_receipt_identity"]["key"] == unique_keys
    assert indexes["uniq_history_receipt_identity"]["unique"] is True
    assert indexes["history_receipt_pages"]["key"] == ordered_keys
    assert all("expireAfterSeconds" not in index for index in indexes.values())
    rows = (
        collection.find(
            {"acquisition_id": "head", "generation": 1, "pass_number": 1, "kind": "membership"}
        )
        .hint("history_receipt_pages")
        .sort([("page_sequence", 1), ("resource_id", 1)])
    )
    assert [row["_id"] for row in rows] == ["receipt", "same-page", "late"]


def test_committed_receipt_schema_matches_export(tmp_path: Path) -> None:
    export_schemas(tmp_path)
    generated = json.loads((tmp_path / f"{RECEIPTS}.json").read_text())
    committed = json.loads((ROOT / "infra/mongo/schemas" / f"{RECEIPTS}.json").read_text())
    assert generated == committed


def test_receipt_schema_accepts_optional_source_payload_and_legacy_documents(
    schema_db: Database[dict[str, Any]],
) -> None:
    source = {**receipt(), "source_payload": {"id": 200001}, "source_hash": "a" * 64}
    schema_db[RECEIPTS].insert_one(source)
    legacy = receipt(_id="legacy", resource_id="2")
    legacy.pop("source_payload", None)
    schema_db[RECEIPTS].insert_one(legacy)
    assert schema_db[RECEIPTS].count_documents({}) == 2


@pytest.mark.parametrize("source", [{}, [], {"id": 200001}])
def test_receipt_schema_rejects_unhashed_or_invalid_source(
    schema_db: Database[dict[str, Any]],
    source: Any,
) -> None:
    with pytest.raises(WriteError) as rejected:
        schema_db[RECEIPTS].insert_one({**receipt(), "source_payload": source})
    assert rejected.value.code == 121
