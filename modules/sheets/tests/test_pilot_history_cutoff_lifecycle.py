from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from zeler_sheets.formulas.recovery import FormulaRecoveryQueue
from zeler_sheets.pilot_history import HistoryPlanner
from zeler_sheets.pilot_history_backfill import PLAN_COLLECTION, build_pilot_history_backfill
from zeler_sheets.pilot_history_recovery_bridge import chunk_to_recovery_request

SELLER = "82453304"


@pytest_asyncio.fixture
async def cutoff_db() -> AsyncIterator[AsyncIOMotorDatabase[dict[str, Any]]]:
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        "mongodb://127.0.0.1:27028/?directConnection=true",
        tz_aware=True,
        serverSelectionTimeoutMS=2000,
    )
    hello = await client.admin.command("hello")
    assert hello["isWritablePrimary"] and hello["setName"] == "rs0"
    database = client[f"zeler_pilot_cutoff_{uuid4().hex}"]
    try:
        yield database
    finally:
        await client.drop_database(database.name)
        client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("preexisting", [False, True])
async def test_repeated_callback_keeps_bson_cutoff_and_job_identity(
    cutoff_db: AsyncIOMotorDatabase[dict[str, Any]], preexisting: bool
) -> None:
    cutoff = datetime(2026, 9, 15, 12, 34, 56, tzinfo=UTC)
    if preexisting:
        await cutoff_db[PLAN_COLLECTION].insert_one(
            {"_id": SELLER, "seller_id": SELLER, "cutoff": cutoff, "schema_version": 1}
        )
    queue = FormulaRecoveryQueue(
        cutoff_db, allowed_sellers=frozenset({SELLER}), max_active_jobs_per_seller=1
    )
    await queue.ensure_indexes()
    callback = build_pilot_history_backfill(db=cutoff_db, recovery_queue=queue)
    expected_plan = None
    expected_job = None
    for cycle in range(2):
        assert await callback(SELLER) is (cycle == 0)
        plan = await cutoff_db[PLAN_COLLECTION].find_one({"_id": SELLER})
        job = await queue.collection.find_one({"seller_id": SELLER})
        assert plan is not None and job is not None
        assert plan["cutoff"].tzinfo != UTC
        if preexisting:
            assert plan["cutoff"] == cutoff
        if expected_plan is not None:
            assert plan["cutoff"] == expected_plan["cutoff"]
            assert job == expected_job
        expected_plan, expected_job = plan, job
        assert await queue.collection.count_documents({"seller_id": SELLER}) == 1


class ConcurrentPlanReads:
    def __init__(self, database: AsyncIOMotorDatabase[dict[str, Any]]) -> None:
        self.database = database
        self.collection = database[PLAN_COLLECTION]
        self.readers = 0
        self.ready = asyncio.Event()

    def __getitem__(self, name: str) -> Any:
        return self if name == PLAN_COLLECTION else self.database[name]

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        document = await self.collection.find_one(query)
        if document is None:
            self.readers += 1
            first = self.readers == 1
            if self.readers == 2:
                self.ready.set()
            await self.ready.wait()
            if not first:
                await asyncio.sleep(1.1)
        return document

    async def update_one(self, *args: Any, **kwargs: Any) -> Any:
        return await self.collection.update_one(*args, **kwargs)

    async def find_one_and_update(self, *args: Any, **kwargs: Any) -> Any:
        return await self.collection.find_one_and_update(*args, **kwargs)


@pytest.mark.asyncio
async def test_concurrent_initializers_use_first_persisted_cutoff(
    cutoff_db: AsyncIOMotorDatabase[dict[str, Any]],
) -> None:
    queue = FormulaRecoveryQueue(
        cutoff_db, allowed_sellers=frozenset({SELLER}), max_active_jobs_per_seller=1
    )
    await queue.ensure_indexes()
    database = ConcurrentPlanReads(cutoff_db)
    callback = build_pilot_history_backfill(db=database, recovery_queue=queue)
    results = await asyncio.wait_for(
        asyncio.gather(callback(SELLER), callback(SELLER), return_exceptions=True), timeout=10
    )
    assert results[0] is True and results[1] is False
    plan = await cutoff_db[PLAN_COLLECTION].find_one({"_id": SELLER})
    assert plan is not None
    planner = HistoryPlanner(cutoff=plan["cutoff"].astimezone(UTC), months=12)
    recent = planner.plan_for("orders").chunks[-1]
    expected = chunk_to_recovery_request(recent, seller_id=SELLER)
    jobs = await queue.collection.find({"seller_id": SELLER}).to_list(length=None)
    assert len(jobs) == 1
    assert jobs[0]["_id"] == expected.key
    assert jobs[0]["date_to"] == plan["cutoff"]


@pytest.mark.asyncio
@pytest.mark.parametrize("capacity", [2, 4])
async def test_capacity_persists_all_chunks_and_prioritizes_both_resources(
    cutoff_db: AsyncIOMotorDatabase[dict[str, Any]], capacity: int
) -> None:
    queue = FormulaRecoveryQueue(cutoff_db, max_active_jobs_per_seller=capacity)
    callback = build_pilot_history_backfill(db=cutoff_db, recovery_queue=queue)
    assert await callback(SELLER) is True
    before = await queue.collection.find({}).sort("_id", 1).to_list(length=None)
    assert len(before) == capacity
    plan = await cutoff_db[PLAN_COLLECTION].find_one({"_id": SELLER})
    assert plan is not None
    planner = HistoryPlanner(cutoff=plan["cutoff"].astimezone(UTC), months=12)
    expected = {
        chunk_to_recovery_request(chunk, seller_id=SELLER).key
        for resource in ("orders", "questions")
        for chunk in planner.plan_for(resource).chunks
        if chunk.priority.value in ({"recent"} if capacity == 2 else {"recent", "oldest_edge"})
    }
    assert {job["_id"] for job in before} == expected
    assert set(plan["progress"]) == {"orders", "questions", "shipments", "items"}
    for resource, progress in plan["progress"].items():
        assert len(progress["chunks"]) == 12
        assert (
            sum(
                progress[state]
                for state in ("queued", "running", "completed", "failed", "pending", "blocked")
            )
            == 12
        )
        assert "admitted_this_cycle" not in progress
        for chunk in progress["chunks"]:
            assert chunk["date_from"] < chunk["date_to"] <= plan["cutoff"]
            assert chunk["chunk_id"]
        if resource in {"shipments", "items"}:
            assert progress["blocked"] == 12
            assert all(
                chunk["reason"] == "acquisition_path_unresolved" for chunk in progress["chunks"]
            )
        else:
            assert progress["queued"] == capacity // 2
            assert progress["pending"] == 12 - capacity // 2
    assert await callback(SELLER) is False
    assert await queue.collection.find({}).sort("_id", 1).to_list(length=None) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("succeeded", [False, True])
async def test_callback_retains_terminal_and_running_jobs(
    cutoff_db: AsyncIOMotorDatabase[dict[str, Any]], succeeded: bool
) -> None:
    queue = FormulaRecoveryQueue(cutoff_db, max_active_jobs_per_seller=2)
    callback = build_pilot_history_backfill(db=cutoff_db, recovery_queue=queue)
    await callback(SELLER)
    claimed = await queue.claim()
    assert claimed is not None
    assert await queue.finish(claimed, succeeded=succeeded)
    terminal = await queue.collection.find_one({"_id": claimed["_id"]})
    running = await queue.claim()
    assert running is not None
    await callback(SELLER)
    assert await queue.collection.find_one({"_id": claimed["_id"]}) == terminal
    assert await queue.collection.find_one({"_id": running["_id"]}) == running
    plan = await cutoff_db[PLAN_COLLECTION].find_one({"_id": SELLER})
    assert plan is not None
    rows = [chunk for progress in plan["progress"].values() for chunk in progress["chunks"]]
    states = {chunk.get("request_key"): chunk["state"] for chunk in rows}
    assert states[claimed["_id"]] == ("completed" if succeeded else "failed")
    assert states[running["_id"]] == "running"


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["seller", "source"])
async def test_callback_does_not_swallow_scope_rejection(
    cutoff_db: AsyncIOMotorDatabase[dict[str, Any]], scope: str
) -> None:
    queue = FormulaRecoveryQueue(
        cutoff_db,
        allowed_sellers=frozenset() if scope == "seller" else frozenset({SELLER}),
        enabled_models=frozenset({"questions"}),
    )
    callback = build_pilot_history_backfill(db=cutoff_db, recovery_queue=queue)
    with pytest.raises(ValueError, match=f"recovery {scope} is not enabled"):
        await callback(SELLER)
    assert await queue.collection.count_documents({}) == 0


@pytest.mark.asyncio
async def test_callback_records_post_coalescence_terminal_state(
    cutoff_db: AsyncIOMotorDatabase[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    queue = FormulaRecoveryQueue(cutoff_db, max_active_jobs_per_seller=1)
    competitor = FormulaRecoveryQueue(cutoff_db)
    original_enqueue = queue.enqueue
    terminal: dict[str, Any] | None = None

    async def competing_completion(request: Any, *, reopen_terminal: bool) -> str:
        nonlocal terminal
        if terminal is None:
            await competitor.enqueue(request)
            claimed = await competitor.claim()
            assert claimed is not None
            assert await competitor.finish(claimed, succeeded=True)
            terminal = await competitor.collection.find_one({"_id": request.key})
        return await original_enqueue(request, reopen_terminal=reopen_terminal)

    monkeypatch.setattr(queue, "enqueue", competing_completion)
    callback = build_pilot_history_backfill(db=cutoff_db, recovery_queue=queue)
    assert await callback(SELLER) is True
    assert terminal is not None
    assert await competitor.collection.find_one({"_id": terminal["_id"]}) == terminal
    plan = await cutoff_db[PLAN_COLLECTION].find_one({"_id": SELLER})
    assert plan is not None
    orders = plan["progress"]["orders"]
    assert orders["completed"] == 1 and orders["accepted_or_coalesced_this_cycle"] == 1
    assert plan["progress"]["questions"]["queued"] == 1
    assert await competitor.collection.count_documents({}) == 2
