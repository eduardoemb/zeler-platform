"""Old unchanged orders participate in bounded periodic message recovery."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from test_history_onboarding import db as db  # isolated rs0 fixture

from zeler_platform_core.history_onboarding import admit_history_onboarding
from zeler_sheets.history_onboarding import HistoryOnboardingWorker


class Messages:
    def __init__(self, created: datetime, *, total: int = 1) -> None:
        self.created, self.total = created, total
        self.calls: list[str] = []

    async def fetch_resource(self, *, seller_id: str, path: str) -> dict[str, Any]:
        assert seller_id == "123" and path.startswith("/messages/packs/")
        self.calls.append(path)
        query = parse_qs(urlsplit(path).query)
        assert query["mark_as_read"] == ["false"]
        offset = int(query["offset"][0])
        pack = path.split("/")[3]
        rows = [
            {
                "id": f"{pack}-{i}",
                "from": {"user_id": "321"},
                "to": {"user_id": "123"},
                "text": "isolated new message",
                "status": "available",
                "message_date": {"created": self.created.isoformat()},
            }
            for i in range(offset, min(offset + 50, self.total))
        ]
        return {"paging": {"total": self.total, "offset": offset}, "messages": rows}


async def prepare(db: Any, cutoff: datetime, packs: int = 1) -> None:
    await admit_history_onboarding(db, "123", now=cutoff)
    await db.meli_accounts.insert_one({"_id": "a", "seller_id": 123, "status": "active"})
    await db.orders.insert_many(
        [
            {
                "_id": f"o{i}",
                "seller_id": "123",
                "meli_pack_id": str(400 + i // 2),
                "buyer_id": "321",
                "status": "paid",
                "total_amount": 1.0,
                "date_created": cutoff - timedelta(days=200),
                "last_updated": cutoff - timedelta(days=190),
                "schema_version": 1,
            }
            for i in range(packs * 2)
        ]
    )
    await db.sheets_history_backfill_plans.update_one(
        {"_id": "123"},
        {"$set": {"source_cursor": 3, "onboarding_sources.orders.state": "ready"}},
    )


async def message_turn(db: Any, source: Messages, now: datetime) -> None:
    # Select one real scheduler source turn; no replacement scheduler/collector.
    await db.sheets_history_backfill_plans.update_one(
        {"_id": "123"}, {"$set": {"source_cursor": 3, "next_cycle_at": now}}
    )
    assert (
        await HistoryOnboardingWorker(db, source, source, now=lambda: now).process_once()
        == "processed"
    )


@pytest.mark.asyncio
async def test_old_unchanged_pack_gets_new_message_without_recent_order_dependency(db: Any) -> None:
    cutoff = datetime(2026, 1, 31, tzinfo=UTC)
    await prepare(db, cutoff)
    now = cutoff + timedelta(days=1)
    source = Messages(cutoff + timedelta(hours=1))
    await message_turn(db, source, now)
    message = await db.messages.find_one({"_id": "400-0"})
    assert message is not None and message["pack_id"] == "400"
    unchanged = await db.orders.find_one({"_id": "o0"})
    assert unchanged["last_updated"] == cutoff - timedelta(days=190)
    assert len(source.calls) == 1  # two orders share one pack
    plan = await db.sheets_history_backfill_plans.find_one({"_id": "123"})
    assert plan["total_consumed"] == 0
    assert plan["incremental_source_consumed"]["messages"] == 1
    assert plan["message_periodic_recovery"]["sweep_complete"]


@pytest.mark.asyncio
async def test_rotation_resumes_pages_after_restart_and_preserves_initial_pending_checkpoint(
    db: Any,
) -> None:
    cutoff = datetime(2026, 1, 31, tzinfo=UTC)
    await prepare(db, cutoff)
    checkpoint = {
        "seller_id": "123",
        "source": "messages",
        "start": (cutoff - timedelta(days=365)).isoformat(),
        "end": cutoff.isoformat(),
        "target_ids": ["400"],
        "target_index": 0,
        "offset": 1,
        "persisted": 1,
        "issue_count": 1,
        "pending": [{"code": "invalid_message", "id": "old"}],
        "discovery_complete": False,
    }
    await db.sheets_history_backfill_plans.update_one(
        {"_id": "123"}, {"$set": {"collector_checkpoints.messages": checkpoint}}
    )
    now = cutoff + timedelta(days=1)
    source = Messages(cutoff + timedelta(hours=1), total=151)
    await message_turn(db, source, now)
    first = await db.sheets_history_backfill_plans.find_one({"_id": "123"})
    assert first["collector_checkpoints"]["messages"] == checkpoint
    assert first["message_periodic_recovery"]["checkpoint"]["offset"] == 100
    assert len(source.calls) == 2
    # A restart uses durable state, not page0. Choose the next periodic turn,
    # leaving the ordinary initial turn available to run independently.
    await db.sheets_history_backfill_plans.update_one(
        {"_id": "123"}, {"$inc": {"message_periodic_turn": 1}}
    )
    await message_turn(db, source, now + timedelta(minutes=1))
    assert [int(parse_qs(urlsplit(p).query)["offset"][0]) for p in source.calls] == [
        0,
        50,
        100,
        150,
    ]
    assert await db.messages.count_documents({"seller_id": "123"}) == 151
    plan = await db.sheets_history_backfill_plans.find_one({"_id": "123"})
    assert plan["collector_checkpoints"]["messages"] == checkpoint
    assert plan["message_periodic_recovery"]["sweep_complete"]
    assert plan["incremental_source_consumed"]["messages"] == 4


@pytest.mark.asyncio
async def test_rotating_batches_bound_inventory_and_daily_quota_without_losing_cursor(
    db: Any,
) -> None:
    cutoff = datetime(2026, 1, 31, tzinfo=UTC)
    await prepare(db, cutoff, packs=41)
    now = cutoff + timedelta(days=1)
    source = Messages(cutoff + timedelta(hours=1))
    await db.sheets_history_backfill_plans.update_one(
        {"_id": "123"}, {"$set": {"incremental_policy.max_daily_source": 2}}
    )
    await message_turn(db, source, now)
    plan = await db.sheets_history_backfill_plans.find_one({"_id": "123"})
    rotation = plan["message_periodic_recovery"]
    assert len(rotation["checkpoint"]["target_ids"]) == 40
    assert rotation["checkpoint"]["target_index"] == 2
    await db.sheets_history_backfill_plans.update_one(
        {"_id": "123"}, {"$inc": {"message_periodic_turn": 1}}
    )
    await message_turn(db, source, now + timedelta(minutes=1))
    exhausted = await db.sheets_history_backfill_plans.find_one({"_id": "123"})
    assert (
        exhausted["onboarding_sources"]["messages"]["periodic_recovery"]["reason"]
        == "daily_budget_exhausted"
    )
    assert {
        key: value
        for key, value in exhausted["message_periodic_recovery"]["checkpoint"].items()
        if key != "last_error"
    } == rotation["checkpoint"]
    assert "next_attempt_at" not in exhausted["onboarding_sources"]["messages"]
    assert len(source.calls) == 2
    # Daily maintenance exhaustion must not block the independent initial lane.
    await message_turn(db, source, now + timedelta(minutes=2))
    initial = await db.sheets_history_backfill_plans.find_one({"_id": "123"})
    assert initial["collector_checkpoints"]["messages"]["target_index"] == 2
    assert initial["total_consumed"] == 2
    assert (
        initial["message_periodic_recovery"]["checkpoint"]
        == exhausted["message_periodic_recovery"]["checkpoint"]
    )
    # Next UTC day renews only maintenance counters and continues old targets.
    await message_turn(db, source, now + timedelta(days=1))
    resumed = await db.sheets_history_backfill_plans.find_one({"_id": "123"})
    assert resumed["message_periodic_recovery"]["checkpoint"]["target_index"] == 4
    assert resumed["total_consumed"] == 2


@pytest.mark.asyncio
async def test_rotating_batches_eventually_visit_every_old_pack_without_reopening_annual_history(
    db: Any,
) -> None:
    cutoff = datetime(2026, 1, 31, tzinfo=UTC)
    await prepare(db, cutoff, packs=41)
    await db.sheets_history_backfill_plans.update_one(
        {"_id": "123"},
        {
            "$set": {
                "collector_checkpoints.messages": {
                    "seller_id": "123",
                    "source": "messages",
                    "start": (cutoff - timedelta(days=365)).isoformat(),
                    "end": cutoff.isoformat(),
                    "target_ids": [],
                    "target_index": 0,
                    "offset": 0,
                    "persisted": 0,
                    "issue_count": 0,
                    "discovery_complete": True,
                }
            }
        },
    )
    source = Messages(cutoff + timedelta(hours=1))
    now = cutoff + timedelta(days=1)
    for index in range(41):
        before = len(source.calls)
        await message_turn(db, source, now + timedelta(seconds=30 * index))
        assert len(source.calls) - before <= 2
    packs = [path.split("/")[3] for path in source.calls]
    assert packs == [str(400 + i) for i in range(41)]
    assert await db.messages.count_documents({"seller_id": "123"}) == 41
    assert await db.sheets_formula_recovery_jobs.count_documents({}) == 0
    plan = await db.sheets_history_backfill_plans.find_one({"_id": "123"})
    assert plan["message_periodic_recovery"]["sweep_complete"]
    assert plan["message_periodic_recovery"]["packs_completed"] == 41
    assert plan["total_consumed"] == 0
    assert plan["incremental_consumed"] == 41


@pytest.mark.asyncio
async def test_message_arriving_during_frozen_sweep_is_captured_in_next_window(db: Any) -> None:
    cutoff = datetime(2026, 1, 31, tzinfo=UTC)
    await prepare(db, cutoff)
    now = cutoff + timedelta(days=1)
    source = Messages(cutoff + timedelta(hours=1))
    await message_turn(db, source, now)
    assert await db.messages.count_documents({}) == 1

    class ChangedPack(Messages):
        async def fetch_resource(self, **kwargs: Any) -> dict[str, Any]:
            response = await super().fetch_resource(**kwargs)
            for row in response["messages"]:
                if row["id"] == "400-1":
                    row["message_date"]["created"] = (now + timedelta(minutes=1)).isoformat()
            return response

    changed = ChangedPack(source.created, total=2)
    # Ordinary lane remains independent between rotating turns.
    await message_turn(db, changed, now + timedelta(minutes=2))
    assert await db.messages.count_documents({}) == 1
    await message_turn(db, changed, now + timedelta(minutes=16))
    assert await db.messages.count_documents({}) == 2
    plan = await db.sheets_history_backfill_plans.find_one({"_id": "123"})
    rotation = plan["message_periodic_recovery"]
    assert rotation["sweep_start"] == now - timedelta(minutes=5)
    assert rotation["sweep_end"] == now + timedelta(minutes=16)
    assert rotation["persisted"] == 1  # only this window's new message
    assert plan["total_consumed"] == 1  # ordinary initial lane, never reset/reopened


def test_periodic_progress_never_exposes_pack_ids_or_message_content() -> None:
    from zeler_sheets.history_onboarding import message_periodic_progress

    progress = message_periodic_progress(
        {
            "message_periodic_recovery": {
                "state": "running",
                "checkpoint": {
                    "target_ids": ["private-pack"],
                    "offset": 50,
                    "pending": [{"id": "private-message", "code": "invalid_message"}],
                    "target_index": 0,
                },
                "persisted": 3,
            }
        }
    )
    assert progress is not None and progress["batch_size"] == 1
    assert progress["page_offset"] == 50 and progress["coverage_complete"] is False
    assert "private-" not in str(progress)


@pytest.mark.asyncio
async def test_periodic_checkpoint_cannot_overwrite_replacement_plan_lease(db: Any) -> None:
    cutoff = datetime(2026, 1, 31, tzinfo=UTC)
    await prepare(db, cutoff)
    now = cutoff + timedelta(days=1)

    class ReplacedLease(Messages):
        async def fetch_resource(self, **kwargs: Any) -> dict[str, Any]:
            response = await super().fetch_resource(**kwargs)
            await db.sheets_history_backfill_plans.update_one(
                {"_id": "123"},
                {
                    "$set": {
                        "lease_token": "replacement",
                        "message_periodic_recovery": {"state": "replacement_checkpoint"},
                    }
                },
            )
            return response

    await message_turn(db, ReplacedLease(cutoff + timedelta(hours=1)), now)
    plan = await db.sheets_history_backfill_plans.find_one({"_id": "123"})
    assert plan["message_periodic_recovery"] == {"state": "replacement_checkpoint"}


@pytest.mark.asyncio
async def test_quota_exhaustion_mid_turn_retains_the_successful_page_and_advances_next_day(
    db: Any,
) -> None:
    cutoff = datetime(2026, 1, 31, tzinfo=UTC)
    await prepare(db, cutoff, packs=2)
    now = cutoff + timedelta(days=1)
    source = Messages(cutoff + timedelta(hours=1))
    await db.sheets_history_backfill_plans.update_one(
        {"_id": "123"}, {"$set": {"incremental_policy.max_daily_source": 1}}
    )
    await message_turn(db, source, now)
    plan = await db.sheets_history_backfill_plans.find_one({"_id": "123"})
    assert plan["message_periodic_recovery"]["checkpoint"]["target_index"] == 1
    assert len(source.calls) == 1
    await db.sheets_history_backfill_plans.update_one(
        {"_id": "123"}, {"$inc": {"message_periodic_turn": 1}}
    )
    await message_turn(db, source, now + timedelta(days=1))
    assert [path.split("/")[3] for path in source.calls] == ["400", "401"]
    assert await db.messages.count_documents({}) == 2
