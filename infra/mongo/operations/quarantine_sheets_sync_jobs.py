from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, TypedDict

from pymongo import MongoClient, ReturnDocument

MIGRATION_ID = "sheets_sync_jobs_v2_activation_cutoff"
LEGACY_CREATED_AT_SENTINEL = datetime(1970, 1, 1, tzinfo=UTC)


class QuarantineSummary(TypedDict):
    scanned_count: int
    quarantined_count: int
    eligible_count: int


def _as_utc(value: object) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _record_cutoff(metadata: Any, cutoff: datetime, now: datetime) -> None:
    record = metadata.find_one_and_update(
        {"_id": MIGRATION_ID},
        {"$setOnInsert": {"activation_cutoff": cutoff, "created_at": now}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    recorded_cutoff = _as_utc(record.get("activation_cutoff") if record else None)
    if recorded_cutoff != cutoff:
        raise ValueError("activation cutoff is immutable once recorded")


def _quarantine_patch(
    created_at: datetime | None, cutoff: datetime, now: datetime
) -> dict[str, object]:
    invalid_created_at = created_at is None
    return {
        "state": "quarantined",
        "created_at": LEGACY_CREATED_AT_SENTINEL if invalid_created_at else created_at,
        "available_at": None,
        "attempt_count": 0,
        "attempt_token": None,
        "fence": 0,
        "lease_until": None,
        "append_started_at": None,
        "activation_cutoff": cutoff,
        "quarantined_at": now,
        "quarantine_reason": (
            "missing_or_invalid_created_at"
            if invalid_created_at
            else "created_before_activation_cutoff"
        ),
        "error_code": None,
        "error_message": None,
        "updated_at": now,
        "schema_version": 2,
    }


def quarantine_sheets_sync_jobs(
    database: Any,
    activation_cutoff: datetime,
    *,
    now: datetime | None = None,
) -> QuarantineSummary:
    cutoff = _as_utc(activation_cutoff)
    migration_time = _as_utc(now or datetime.now(UTC))
    if cutoff is None or migration_time is None:
        raise ValueError("activation cutoff and migration time must be datetimes")

    jobs = database["sheets_sync_jobs"]
    _record_cutoff(database["platform_migrations"], cutoff, migration_time)
    pending_jobs = list(jobs.find({"state": "pending"}))
    quarantined_count = 0
    eligible_count = 0

    for document in pending_jobs:
        created_at = _as_utc(document.get("created_at"))
        if created_at is not None and created_at >= cutoff:
            eligible_count += 1
            continue
        result = jobs.update_one(
            {"_id": document["_id"], "state": "pending"},
            {"$set": _quarantine_patch(created_at, cutoff, migration_time)},
        )
        quarantined_count += int(result.modified_count)

    unsafe_pending = [
        document
        for document in jobs.find({"state": "pending"})
        if (created_at := _as_utc(document.get("created_at"))) is None or created_at < cutoff
    ]
    if unsafe_pending:
        raise RuntimeError("post-check failed: pre-cutoff or invalid pending jobs remain")

    return {
        "scanned_count": len(pending_jobs),
        "quarantined_count": quarantined_count,
        "eligible_count": eligible_count,
    }


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    result = _as_utc(parsed)
    if result is None:
        raise argparse.ArgumentTypeError("activation cutoff must be an ISO-8601 datetime")
    return result


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Quarantine pre-cutoff Sheets sync jobs.")
    parser.add_argument("--activation-cutoff", required=True, type=_parse_datetime)
    parser.add_argument("--confirm-approved-runtime", action="store_true", required=True)
    args = parser.parse_args(argv)
    mongo_uri = os.environ.get("MONGO_URI")
    if not mongo_uri:
        print("error: MONGO_URI is required", file=sys.stderr)
        raise SystemExit(2)

    client: MongoClient[Any] = MongoClient(mongo_uri)
    try:
        summary = quarantine_sheets_sync_jobs(client.get_default_database(), args.activation_cutoff)
    finally:
        client.close()
    print(
        "sheets sync jobs quarantine complete: "
        f"scanned={summary['scanned_count']} "
        f"quarantined={summary['quarantined_count']} eligible={summary['eligible_count']}"
    )


if __name__ == "__main__":
    main()
