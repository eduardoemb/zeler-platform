from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from zeler_sheets.consumer import (
    build_formula_recovery_poller,
    build_zelerdata_refresh_supervisor,
)
from zeler_sheets.formulas.read_models import read_model_reconciliation_marker_covers
from zeler_sheets.formulas.recovery import (
    FormulaRecoveryQueue,
    ItemInventoryRecoveryRequest,
    OrderHistoryRecoveryRequest,
    RecoveryRequest,
)
from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker
from zeler_sheets.history_worker import HistoryOrdersWorker
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


@pytest.mark.asyncio
async def test_opted_in_callback_admits_plan_bound_order_protocol(
    cutoff_db: AsyncIOMotorDatabase[dict[str, Any]],
) -> None:
    queue = FormulaRecoveryQueue(
        cutoff_db, allowed_sellers=frozenset({SELLER}), max_active_jobs_per_seller=1
    )
    await queue.ensure_indexes()
    callback = build_pilot_history_backfill(db=cutoff_db, recovery_queue=queue, order_history=True)
    assert await callback(SELLER)
    plan = await cutoff_db[PLAN_COLLECTION].find_one({"_id": SELLER})
    assert plan is not None
    cutoff = plan["cutoff"].astimezone(UTC)
    recent = HistoryPlanner(cutoff=cutoff, months=12).plan_for("orders").chunks[-1]
    request = OrderHistoryRecoveryRequest(
        SELLER, f"pilot-12m:{cutoff.isoformat(timespec='milliseconds')}", recent.start, recent.end
    )
    job = await queue.collection.find_one({"seller_id": SELLER})
    assert job is not None and job["_id"] == request.key
    assert job["history_plan_id"] == request.plan_id
    assert job["history_protocol_version"] == 1
    assert job["history_acquisition_id"] == request.key
    assert await queue.claim() is None
    assert await callback(SELLER) is False
    assert await queue.collection.count_documents({"seller_id": SELLER}) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("order_history", [False, True])
async def test_pilot_history_keeps_admission_for_query_and_inventory(
    cutoff_db: AsyncIOMotorDatabase[dict[str, Any]],
    order_history: bool,
) -> None:
    queue = FormulaRecoveryQueue(
        cutoff_db,
        allowed_sellers=frozenset({SELLER}),
        max_active_jobs_per_seller=20,
        reserved_inventory_slots=1,
    )
    await queue.ensure_indexes()
    callback = build_pilot_history_backfill(
        db=cutoff_db, recovery_queue=queue, order_history=order_history
    )

    assert await callback(SELLER)
    plan = await cutoff_db[PLAN_COLLECTION].find_one({"_id": SELLER})
    assert plan is not None
    assert await queue.collection.count_documents({"state": "pending"}) == 4
    assert await queue.collection.count_documents({"read_model": "orders", "state": "pending"}) == 2
    assert (
        await queue.collection.count_documents({"read_model": "questions", "state": "pending"}) == 2
    )
    query = RecoveryRequest(
        SELLER, "orders", plan["cutoff"] - timedelta(days=2), plan["cutoff"] - timedelta(days=1)
    )
    inventory = ItemInventoryRecoveryRequest(SELLER)
    assert await queue.enqueue(query) == query.key
    assert await queue.enqueue(inventory) == inventory.key
    assert await callback(SELLER) is False
    assert await queue.collection.count_documents({"state": "pending"}) == 6

    history_job = await queue.collection.find_one(
        {"read_model": "orders", "state": "pending", "_id": {"$ne": query.key}}
    )
    assert history_job is not None
    await queue.collection.update_one({"_id": history_job["_id"]}, {"$set": {"state": "completed"}})
    assert await callback(SELLER)
    assert await queue.collection.count_documents({"state": "pending"}) == 6


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled,expected_lanes", [(False, 3), (True, 4)])
async def test_recovery_supervisor_gates_order_history_worker(
    cutoff_db: AsyncIOMotorDatabase[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    enabled: bool,
    expected_lanes: int,
) -> None:
    monkeypatch.setenv("ZELERDATA_FORMULA_RECOVERY_SELLERS", SELLER)
    monkeypatch.setenv("ZELERDATA_ORDER_HISTORY_PROTOCOL_ENABLED", "true" if enabled else "false")
    monkeypatch.setattr("zeler_sheets.consumer.make_meli_gateway_client", lambda **kwargs: object())

    supervisor = await build_formula_recovery_poller(
        db=cutoff_db, kms_client=object(), detail_gateway=object()
    )

    assert len(supervisor.lanes) == expected_lanes
    if enabled:
        history = supervisor.lanes[-1]._processor
        assert isinstance(history, HistoryOrdersWorker)
        assert history.queue.allowed_sellers == frozenset({SELLER})
        legacy = supervisor.lanes[0]._processor
        assert history.producer.worker.gateway._pacer is legacy.gateway._pacer


@pytest.mark.asyncio
async def test_refresh_supervisor_admits_order_protocol_when_enabled(
    cutoff_db: AsyncIOMotorDatabase[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in (
        "ZELERDATA_DEVOLUCIONES_ADVANCE_ENABLED",
        "ZELERDATA_PRECALCULATED_FORMULAS_ENABLED",
        "ZELERDATA_DLQ_ARCHIVE_ENABLED",
        "ZELERDATA_FRESHNESS_ALERTS_ENABLED",
    ):
        monkeypatch.setenv(name, "false")
    monkeypatch.setenv("ZELERDATA_REFRESH_ENABLED", "true")
    monkeypatch.setenv("ZELERDATA_FORMULA_RECOVERY_ENABLED", "true")
    monkeypatch.setenv("ZELERDATA_REFRESH_SELLERS", SELLER)
    monkeypatch.setenv("ZELERDATA_ORDER_HISTORY_PROTOCOL_ENABLED", "true")

    supervisor = await build_zelerdata_refresh_supervisor(db=cutoff_db)
    callback = supervisor._history_backfill
    assert callback is not None and await callback(SELLER)
    job = await cutoff_db.sheets_formula_recovery_jobs.find_one({"history_protocol_version": 1})
    assert job is not None and job["read_model"] == "orders"


@pytest.mark.asyncio
async def test_order_protocol_waits_for_active_legacy_interval(
    cutoff_db: AsyncIOMotorDatabase[dict[str, Any]],
) -> None:
    cutoff = datetime(2026, 9, 15, 12, 34, 56, tzinfo=UTC)
    await cutoff_db[PLAN_COLLECTION].insert_one(
        {"_id": SELLER, "seller_id": SELLER, "cutoff": cutoff, "schema_version": 1}
    )
    recent = HistoryPlanner(cutoff=cutoff, months=12).plan_for("orders").chunks[-1]
    legacy_request = chunk_to_recovery_request(recent, seller_id=SELLER)
    queue = FormulaRecoveryQueue(cutoff_db, max_active_jobs_per_seller=2)
    await queue.enqueue(legacy_request)
    callback = build_pilot_history_backfill(db=cutoff_db, recovery_queue=queue, order_history=True)

    assert await callback(SELLER)
    assert await queue.collection.count_documents({"history_protocol_version": 1}) == 0
    plan = await cutoff_db[PLAN_COLLECTION].find_one({"_id": SELLER})
    assert plan is not None
    recent_progress = next(
        entry for entry in plan["progress"]["orders"]["chunks"] if entry["chunk_id"] == recent.id
    )
    assert recent_progress["state"] == "blocked"
    assert recent_progress["reason"] == "legacy_order_job_active"

    claimed = await queue.claim()
    assert claimed is not None and claimed["_id"] == legacy_request.key
    assert await queue.finish(claimed, succeeded=True)
    assert await callback(SELLER)
    protocol = await queue.collection.find_one({"history_protocol_version": 1})
    assert protocol is not None and protocol["date_from"] == recent.start


@pytest.mark.asyncio
async def test_pilot_callback_to_history_worker_completes_verified_empty_month(
    cutoff_db: AsyncIOMotorDatabase[dict[str, Any]],
) -> None:
    queue = FormulaRecoveryQueue(
        cutoff_db, allowed_sellers=frozenset({SELLER}), max_active_jobs_per_seller=1
    )
    await queue.ensure_indexes()
    callback = build_pilot_history_backfill(db=cutoff_db, recovery_queue=queue, order_history=True)
    assert await callback(SELLER)
    job = await queue.collection.find_one({"history_protocol_version": 1})
    assert job is not None

    class EmptyOrdersGateway:
        async def fetch_resource(self, *, seller_id: str, path: str) -> dict[str, Any]:
            assert seller_id == SELLER and path.startswith("/orders/search?")
            return {"paging": {"total": 0}, "results": []}

    worker = HistoryOrdersWorker(
        FormulaRecoveryWorker(
            db=cutoff_db,
            queue=FormulaRecoveryQueue(
                cutoff_db,
                enabled_models=frozenset({"orders"}),
                allowed_sellers=frozenset({SELLER}),
            ),
            gateway=EmptyOrdersGateway(),
            detail_gateway=EmptyOrdersGateway(),
        )
    )
    for _ in range(5):
        assert await worker.process_one()

    completed = await queue.collection.find_one({"_id": job["_id"]})
    assert completed is not None and completed["state"] == "completed"
    marker = await cutoff_db.sheets_read_model_freshness.find_one({"_id": f"{SELLER}:orders"})
    assert read_model_reconciliation_marker_covers(
        marker, date_from=job["date_from"], date_to=job["date_to"], now=job["date_to"]
    )


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
