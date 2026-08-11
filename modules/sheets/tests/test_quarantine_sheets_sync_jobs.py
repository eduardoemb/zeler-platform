from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from infra.mongo.operations.quarantine_sheets_sync_jobs import (
    LEGACY_CREATED_AT_SENTINEL,
    MIGRATION_ID,
    quarantine_sheets_sync_jobs,
)
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from pymongo.uri_parser import parse_uri


class _Collection:
    def __init__(self, documents: list[dict[str, Any]] | None = None) -> None:
        self.documents = {document["_id"]: deepcopy(document) for document in documents or []}

    def find(self, query: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            deepcopy(document)
            for document in self.documents.values()
            if all(document.get(key) == value for key, value in query.items())
        ]

    def find_one_and_update(
        self, query: dict[str, Any], update: dict[str, Any], **_kwargs: Any
    ) -> dict[str, Any]:
        document = self.documents.get(query["_id"])
        if document is None:
            document = {"_id": query["_id"], **update["$setOnInsert"]}
            self.documents[query["_id"]] = document
        return deepcopy(document)

    def update_one(self, query: dict[str, Any], update: dict[str, Any]) -> SimpleNamespace:
        document = self.documents.get(query["_id"])
        if document is None or document.get("state") != query["state"]:
            return SimpleNamespace(modified_count=0)
        document.update(update["$set"])
        return SimpleNamespace(modified_count=1)


class _Database:
    def __init__(self, jobs: list[dict[str, Any]]) -> None:
        self.collections = {
            "sheets_sync_jobs": _Collection(jobs),
            "platform_migrations": _Collection(),
        }

    def __getitem__(self, name: str) -> _Collection:
        return self.collections[name]


def _pending(job_id: str, created_at: object = None) -> dict[str, Any]:
    document: dict[str, Any] = {
        "_id": job_id,
        "seller_id": "seller-1",
        "spreadsheet_id": "sheet-1",
        "state": "pending",
        "requested_at": datetime(2026, 8, 1, tzinfo=UTC),
    }
    if created_at is not None:
        document["created_at"] = created_at
    return document


def test_quarantine_migration_is_idempotent_and_preserves_cutoff_boundary() -> None:
    cutoff = datetime(2026, 8, 10, 12, tzinfo=UTC)
    now = cutoff + timedelta(minutes=5)
    database = _Database(
        [
            _pending("old", cutoff - timedelta(microseconds=1)),
            _pending("missing"),
            _pending("invalid", "not-a-date"),
            _pending("boundary", cutoff),
        ]
    )

    first = quarantine_sheets_sync_jobs(database, cutoff, now=now)
    second = quarantine_sheets_sync_jobs(database, cutoff, now=now + timedelta(minutes=1))

    assert first == {"scanned_count": 4, "quarantined_count": 3, "eligible_count": 1}
    assert second == {"scanned_count": 1, "quarantined_count": 0, "eligible_count": 1}
    jobs = database["sheets_sync_jobs"].documents
    assert jobs["old"]["created_at"] == cutoff - timedelta(microseconds=1)
    assert jobs["old"]["quarantine_reason"] == "created_before_activation_cutoff"
    for job_id in ("missing", "invalid"):
        assert jobs[job_id]["created_at"] == LEGACY_CREATED_AT_SENTINEL
        assert jobs[job_id]["quarantine_reason"] == "missing_or_invalid_created_at"
    assert jobs["boundary"]["state"] == "pending"
    quarantined_ids = ("old", "missing", "invalid")
    assert all(jobs[job_id]["activation_cutoff"] == cutoff for job_id in quarantined_ids)


def test_quarantine_migration_rejects_a_changed_recorded_cutoff() -> None:
    cutoff = datetime(2026, 8, 10, 12, tzinfo=UTC)
    database = _Database([])
    quarantine_sheets_sync_jobs(database, cutoff, now=cutoff)

    with pytest.raises(ValueError, match="activation cutoff is immutable"):
        quarantine_sheets_sync_jobs(database, cutoff + timedelta(seconds=1), now=cutoff)


def test_quarantine_migration_accepts_equivalent_bson_millisecond_cutoff() -> None:
    requested_cutoff = datetime(2026, 8, 10, 12, 0, 0, 123456, tzinfo=UTC)
    stored_cutoff = requested_cutoff.replace(microsecond=123000)
    database = _Database([])
    database["platform_migrations"].documents["sheets_sync_jobs_v2_activation_cutoff"] = {
        "_id": "sheets_sync_jobs_v2_activation_cutoff",
        "activation_cutoff": stored_cutoff,
    }

    quarantine_sheets_sync_jobs(database, requested_cutoff, now=requested_cutoff)

    assert (
        database["platform_migrations"].documents["sheets_sync_jobs_v2_activation_cutoff"][
            "activation_cutoff"
        ]
        == stored_cutoff
    )
    with pytest.raises(ValueError, match="activation cutoff is immutable"):
        quarantine_sheets_sync_jobs(
            database, requested_cutoff + timedelta(milliseconds=1), now=requested_cutoff
        )


def test_quarantine_migration_runs_against_local_mongo(default_mongo_uri: str) -> None:
    parsed_uri = parse_uri(default_mongo_uri)
    if any(host not in {"127.0.0.1", "localhost", "::1"} for host, _port in parsed_uri["nodelist"]):
        pytest.skip("runtime harness is restricted to loopback Mongo")

    client: MongoClient[dict[str, Any]] = MongoClient(
        default_mongo_uri, serverSelectionTimeoutMS=500
    )
    database = client["zeler_platform_test_sheets_sync_jobs_quarantine"]
    try:
        client.admin.command("ping")
    except PyMongoError as exc:
        client.close()
        pytest.skip(f"local Mongo is not available: {type(exc).__name__}")

    cutoff = datetime(2026, 8, 10, 12, 0, 0, 123456, tzinfo=UTC)
    bson_cutoff = cutoff.replace(microsecond=123000)
    try:
        database.sheets_sync_jobs.delete_many({})
        database.platform_migrations.delete_many({})
        database.sheets_sync_jobs.insert_many(
            [_pending("old", cutoff - timedelta(seconds=1)), _pending("eligible", cutoff)]
        )

        summary = quarantine_sheets_sync_jobs(database, cutoff, now=cutoff)

        assert summary == {"scanned_count": 2, "quarantined_count": 1, "eligible_count": 1}
        old_job = database.sheets_sync_jobs.find_one({"_id": "old"})
        eligible_job = database.sheets_sync_jobs.find_one({"_id": "eligible"})
        migration = database.platform_migrations.find_one({"_id": MIGRATION_ID})
        assert old_job is not None and old_job["state"] == "quarantined"
        assert eligible_job is not None and eligible_job["state"] == "pending"
        assert migration is not None and migration["activation_cutoff"] == bson_cutoff
    finally:
        client.drop_database(database.name)
        client.close()
