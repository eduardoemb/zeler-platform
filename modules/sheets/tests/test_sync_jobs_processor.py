import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import DuplicateKeyError, PyMongoError
from pymongo.uri_parser import parse_uri

from zeler_sheets.sync_jobs_processor import SyncJobsProcessor

NOW = datetime(2026, 8, 10, 12, tzinfo=UTC)
CUTOFF = NOW - timedelta(days=1)


def job(job_id: str = "job", **changes: Any) -> dict[str, Any]:
    value = {
        "_id": job_id,
        "seller_id": "82453304",
        "spreadsheet_id": "sheet-1",
        "state": "pending",
        "created_at": CUTOFF,
        "requested_at": NOW - timedelta(hours=1),
        "available_at": None,
        "attempt_count": 0,
        "fence": 0,
        "lease_until": None,
        "append_started_at": None,
    }
    value.update(changes)
    return value


def event(event_id: str, age: int, topic: str = "items.updated") -> dict[str, Any]:
    return {
        "_id": event_id,
        "user_id": 82453304,
        "received_at": NOW - timedelta(minutes=age),
        "classification": topic,
        "resource": f"/items/{event_id}",
    }


class Cursor:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.documents = documents

    def sort(self, keys: list[tuple[str, int]]) -> "Cursor":
        self.documents.sort(key=lambda doc: tuple(doc[key] for key, _ in keys))
        return self

    async def to_list(self, *, length: int | None = None) -> list[dict[str, Any]]:
        return self.documents[:length]


def handler(error: Exception | None = None) -> Any:
    return SimpleNamespace(handle=AsyncMock(side_effect=error, return_value="appended"))


def processor(jobs: Any, events: Any = None, h: Any = None, **kwargs: Any) -> SyncJobsProcessor:
    return SyncJobsProcessor(
        db={"sheets_sync_jobs": jobs, "webhook_events": events or MagicMock()},
        handler=h or handler(),
        activation_cutoff=CUTOFF,
        clock=lambda: NOW,
        **kwargs,
    )


def prepared_process(
    events: list[dict[str, Any]], h: Any = None, **changes: Any
) -> tuple[Any, Any, Any]:
    jobs = MagicMock()
    jobs.update_one = AsyncMock(return_value=SimpleNamespace(matched_count=1))
    events_collection = MagicMock()
    events_collection.find.return_value = Cursor(events)
    jobs.events = events_collection
    selected_handler = h or handler()
    instance = processor(jobs, events_collection, selected_handler)
    claimed = job(attempt_token=str(NOW.timestamp()), fence=1, delta_through_at=NOW, **changes)
    instance.recover_uncertain_appends = AsyncMock(return_value=0)  # type: ignore[method-assign]
    instance.claim_next = AsyncMock(return_value=claimed)  # type: ignore[method-assign]
    return instance, jobs, selected_handler


@pytest.mark.asyncio
async def test_atomic_claim_has_cutoff_fencing_and_one_winner() -> None:
    jobs = MagicMock()
    jobs.find_one = AsyncMock(return_value=job())
    jobs.find_one_and_update = AsyncMock(
        side_effect=[job(state="running", attempt_count=1, fence=1), None]
    )
    first, second = await asyncio.gather(processor(jobs).claim_next(), processor(jobs).claim_next())
    assert sorted(value is not None for value in (first, second)) == [False, True]
    assert jobs.find_one.await_args.args[0]["created_at"] == {"$gte": CUTOFF}
    recovery = MagicMock()
    recovery.find_one = AsyncMock(
        return_value=job(state="running", lease_until=NOW - timedelta(seconds=1))
    )
    recovery.find_one_and_update = AsyncMock(
        return_value=job(state="running", attempt_count=2, fence=2)
    )
    claimed = await processor(recovery).claim_next()
    assert claimed and (claimed["attempt_count"], claimed["fence"]) == (2, 2)


@pytest.mark.asyncio
async def test_delta_is_bounded_ordered_skips_unsupported_and_checkpoints() -> None:
    values = [
        event("b", 10),
        event("skip", 20, "payments.updated"),
        event("a", 30),
    ]
    instance, jobs, handler = prepared_process(values)
    assert await instance.process_once() == "succeeded"
    assert [call.args[0].event_id for call in handler.handle.await_args_list] == ["a", "b"]
    updates = [call.args[1]["$set"] for call in jobs.update_one.await_args_list]
    assert any(update.get("cursor_event_id") == "b" for update in updates)
    assert any(update.get("unsupported_event_count") == 1 for update in updates)
    assert jobs.events.find.call_args.args[0]["received_at"] == {
        "$gte": NOW - timedelta(hours=1),
        "$lte": NOW,
    }
    unavailable, unavailable_jobs, unused_handler = prepared_process(
        [], requested_at=NOW - timedelta(days=46)
    )
    assert await unavailable.process_once() == "failed"
    assert (
        unavailable_jobs.update_one.await_args_list[-1].args[1]["$set"]["error_code"]
        == "delta_unavailable"
    )
    assert unused_handler.handle.await_count == 0


@pytest.mark.asyncio
async def test_lifecycle_success_and_sanitized_failure() -> None:
    success, success_jobs, _ = prepared_process([event("one", 0)])
    failed, failed_jobs, _ = prepared_process([event("two", 0)], handler(RuntimeError("secret")))
    await success.process_once()
    assert success_jobs.update_one.await_args_list[-1].args[1]["$set"]["state"] == "succeeded"
    assert await failed.process_once() == "failed"
    terminal = failed_jobs.update_one.await_args_list[-1].args[1]["$set"]
    assert (terminal["state"], terminal["error_message"]) == (
        "failed",
        "RuntimeError: sync job processing failed",
    )


@pytest.mark.asyncio
async def test_uncertain_append_fails_and_duplicate_pair_backs_off() -> None:
    uncertain = MagicMock()
    uncertain.update_many = AsyncMock(return_value=SimpleNamespace(modified_count=1))
    assert await processor(uncertain).recover_uncertain_appends() == 1
    assert (
        uncertain.update_many.await_args.args[1]["$set"]["error_code"] == "append_outcome_unknown"
    )
    loser = MagicMock()
    loser.find_one = AsyncMock(return_value=job("loser"))
    loser.find_one_and_update = AsyncMock(side_effect=DuplicateKeyError("pair conflict"))
    loser.update_one = AsyncMock(return_value=SimpleNamespace(matched_count=1))
    assert await processor(loser).claim_next() is None
    backoff = loser.update_one.await_args.args[1]["$set"]
    assert backoff["available_at"] > NOW


@pytest.mark.asyncio
async def test_real_mongo_processor_enforces_running_pair_exclusion(default_mongo_uri: str) -> None:
    parsed = parse_uri(default_mongo_uri)
    if any(host not in {"127.0.0.1", "localhost", "::1"} for host, _ in parsed["nodelist"]):
        pytest.skip("runtime harness is restricted to loopback Mongo")
    client: AsyncIOMotorClient[Any] = AsyncIOMotorClient(
        default_mongo_uri, serverSelectionTimeoutMS=500
    )
    database = client["zeler_platform_test_sheets_sync_jobs_processor"]
    try:
        await client.admin.command("ping")
    except PyMongoError as exc:
        client.close()
        pytest.skip(f"local Mongo is not available: {type(exc).__name__}")
    try:
        await database.sheets_sync_jobs.delete_many({})
        await database.sheets_sync_jobs.create_index(
            [("seller_id", 1), ("spreadsheet_id", 1)],
            unique=True,
            partialFilterExpression={"state": "running"},
        )
        await database.sheets_sync_jobs.insert_many([job("first"), job("second")])
        results = await asyncio.gather(
            processor(database.sheets_sync_jobs).claim_next(),
            processor(database.sheets_sync_jobs).claim_next(),
        )
        assert sum(result is not None for result in results) == 1
        assert await database.sheets_sync_jobs.count_documents({"state": "running"}) == 1
        assert await database.sheets_sync_jobs.count_documents({"state": "pending"}) == 1
    finally:
        await client.drop_database(database.name)
        client.close()
