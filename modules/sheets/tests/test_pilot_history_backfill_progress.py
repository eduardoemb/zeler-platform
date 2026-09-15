"""TDD: durable per-chunk progress, counts, errors and safe cursor.

Task 3.2 requires: per-resource/tramo progress, counts, errors, exclusions
and a safe cursor persisted in ``sheets_history_backfill_plans`` so the
pilot can see coverage, retries and pending work without querying the
recovery queue's internal fields.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from zeler_sheets.pilot_history_backfill import PLAN_COLLECTION, build_pilot_history_backfill

SELLER = "82453304"
CUTOFF = None  # set by fixture


class FakePlanCollection:
    def __init__(self) -> None:
        self.docs: dict[str, dict[str, Any]] = {}

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        return self.docs.get(query["_id"])

    async def update_one(
        self, query: dict[str, Any], update: dict[str, Any], *, upsert: bool = False
    ) -> None:
        doc = self.docs.setdefault(query["_id"], {})
        doc.update(update.get("$set", {}))

    async def find_one_and_update(
        self, query: dict[str, Any], update: dict[str, Any], *, upsert: bool, return_document: bool
    ) -> dict[str, Any]:
        return self.docs.setdefault(query["_id"], dict(update["$setOnInsert"]))


class FakeJobCollection:
    def __init__(self, states: dict[str, str] | None = None) -> None:
        # maps job key -> {"state": ...}
        self.states = states or {}

    async def find_one(
        self, query: dict[str, Any], projection: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        state = self.states.get(query["_id"])
        if state is None:
            return None
        return {"_id": query["_id"], "state": state}

    async def update_one(self, *args: Any, **kwargs: Any) -> object:
        return type("R", (), {"matched_count": 1, "modified_count": 1})()


class FakeDb:
    def __init__(self) -> None:
        self.plans = FakePlanCollection()

    def __getitem__(self, name: str) -> Any:
        if name == "sheets_history_backfill_plans":
            return self.plans
        raise AssertionError(f"unexpected collection {name}")


class FakeRecoveryQueue:
    def __init__(self, states: dict[str, str] | None = None) -> None:
        self.collection = AsyncMock()
        self.states = states or {}

    async def find_one(
        self, query: dict[str, Any], projection: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        state = self.states.get(query["_id"])
        if state is None:
            return None
        return {"_id": query["_id"], "state": state}


@pytest.fixture
def db() -> dict[str, FakePlanCollection]:
    return {PLAN_COLLECTION: FakePlanCollection()}


class FakeCollection:
    def __init__(self, states: dict[str, str] | None = None) -> None:
        self.states = states or {}

    async def find_one(
        self, query: dict[str, Any], projection: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        state = self.states.get(query["_id"])
        if state is None:
            return None
        return {"_id": query["_id"], "state": state}


@pytest.fixture
def recovery_queue() -> AsyncMock:
    queue = AsyncMock()
    queue.collection = FakeCollection()

    def enqueue(request: Any, *, reopen_terminal: bool) -> str:
        assert reopen_terminal is False
        queue.collection.states.setdefault(request.key, "pending")
        return str(request.key)

    queue.enqueue = AsyncMock(side_effect=enqueue)
    return queue


@pytest.mark.asyncio
async def test_backfill_persists_plan_and_counts_enqueued(
    recovery_queue: AsyncMock,
) -> None:
    db = {"sheets_history_backfill_plans": FakePlanCollection()}
    backfill = build_pilot_history_backfill(db=db, recovery_queue=recovery_queue)
    result = await backfill(SELLER)
    assert result is True
    plan_doc = db["sheets_history_backfill_plans"].docs[SELLER]
    assert plan_doc["seller_id"] == SELLER
    assert plan_doc["schema_version"] == 1
    assert "cutoff" in plan_doc


@pytest.mark.asyncio
async def test_backfill_persists_progress_after_enqueue(
    recovery_queue: AsyncMock,
) -> None:
    db = {"sheets_history_backfill_plans": FakePlanCollection()}
    backfill = build_pilot_history_backfill(db=db, recovery_queue=recovery_queue)
    await backfill(SELLER)
    # After enqueue, the plan document must record the chunk as admitted.
    plan_doc = db["sheets_history_backfill_plans"].docs[SELLER]
    assert "progress" in plan_doc


@pytest.mark.asyncio
async def test_progress_persists_completed_and_errors_per_resource(
    recovery_queue: AsyncMock,
) -> None:
    from zeler_sheets.pilot_history import HistoryPlanner
    from zeler_sheets.pilot_history_recovery_bridge import chunk_to_recovery_request

    plan_collection = FakePlanCollection()
    db = {"sheets_history_backfill_plans": plan_collection}
    backfill = build_pilot_history_backfill(db=db, recovery_queue=recovery_queue)

    # First run: creates plan and enqueues chunks; no failures yet.
    await backfill(SELLER)
    plan_doc = plan_collection.docs[SELLER]
    assert "cutoff" in plan_doc

    # Simulate that one chunk completed and one failed.
    planner = None

    planner = HistoryPlanner(cutoff=plan_doc["cutoff"], months=12)
    plan = planner.plan_for("orders")
    first_chunk = plan.chunks[0]
    request = chunk_to_recovery_request(chunk=first_chunk, seller_id=SELLER)
    # Simulate a completed job in the queue for this chunk key.
    recovery_queue.collection.states[request.key] = "completed"
    # Mark one chunk as failed.
    second_chunk = plan.chunks[1]
    request2 = chunk_to_recovery_request(second_chunk, seller_id=SELLER)
    recovery_queue.collection.states[request2.key] = "failed"

    result = await backfill(SELLER)
    assert result is False
    assert plan_collection.docs[SELLER]["progress"]["orders"]["completed"] == 1
    assert plan_collection.docs[SELLER]["progress"]["orders"]["failed"] == 1
