from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from zeler_sheets.formulas import recovery

SELLER = "82453304"


@pytest_asyncio.fixture
async def admission_db() -> AsyncIterator[AsyncIOMotorDatabase[dict[str, Any]]]:
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        "mongodb://127.0.0.1:27028/?directConnection=true",
        tz_aware=True,
        serverSelectionTimeoutMS=2000,
    )
    hello = await client.admin.command("hello")
    assert hello["isWritablePrimary"] and hello["setName"] == "rs0"
    database = client[f"zeler_pilot_admission_{uuid4().hex}"]
    try:
        yield database
    finally:
        await client.drop_database(database.name)
        client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("succeeded", [False, True])
async def test_preserve_terminal_job_at_capacity_and_keep_default_reopening(
    admission_db: AsyncIOMotorDatabase[dict[str, Any]], succeeded: bool
) -> None:
    queue = recovery.FormulaRecoveryQueue(admission_db, max_active_jobs_per_seller=1)
    request = recovery.OrderIdsRecoveryRequest(SELLER, ("1",))
    await queue.enqueue(request)
    claimed = await queue.claim()
    assert claimed is not None
    assert await queue.finish(claimed, succeeded=succeeded)
    terminal = await queue.collection.find_one({"_id": request.key})
    assert terminal is not None and terminal["attempts"] == 1
    other = recovery.OrderIdsRecoveryRequest(SELLER, ("2",))
    await queue.enqueue(other)
    for _ in range(2):
        assert await queue.enqueue(request, reopen_terminal=False) == request.key
        assert await queue.collection.find_one({"_id": request.key}) == terminal
    with pytest.raises(recovery.RecoveryCapacityError):
        await queue.enqueue(request)
    claimed = await queue.claim()
    assert claimed is not None
    assert await queue.finish(claimed, succeeded=True)
    assert await queue.enqueue(request) == request.key
    reopened = await queue.collection.find_one({"_id": request.key})
    assert reopened is not None
    assert reopened["state"] == "pending" and reopened["attempts"] == 0
    assert reopened["available_at"] == terminal["available_at"]


@pytest.mark.asyncio
@pytest.mark.parametrize("succeeded", [False, True])
async def test_terminal_created_after_initial_lookup_is_preserved_transactionally(
    admission_db: AsyncIOMotorDatabase[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    succeeded: bool,
) -> None:
    queue = recovery.FormulaRecoveryQueue(admission_db)
    competing_queue = recovery.FormulaRecoveryQueue(admission_db)
    request = recovery.OrderIdsRecoveryRequest(SELLER, ("1",))
    looked_up = asyncio.Event()
    resume = asyncio.Event()
    original_find = queue.collection.find_one

    async def pause_initial_lookup(*args: Any, **kwargs: Any) -> Any:
        result = await original_find(*args, **kwargs)
        if "session" not in kwargs:
            assert result is None
            looked_up.set()
            await resume.wait()
        return result

    monkeypatch.setattr(queue.collection, "find_one", pause_initial_lookup)
    async with asyncio.TaskGroup() as tasks:
        pending = tasks.create_task(queue.enqueue(request, reopen_terminal=False))
        await asyncio.wait_for(looked_up.wait(), timeout=5)
        await competing_queue.enqueue(request)
        claimed = await competing_queue.claim()
        assert claimed is not None
        assert await competing_queue.finish(claimed, succeeded=succeeded)
        terminal = await competing_queue.collection.find_one({"_id": request.key})
        resume.set()
    assert pending.result() == request.key
    assert await competing_queue.collection.find_one({"_id": request.key}) == terminal
    assert await competing_queue.collection.count_documents({}) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("reserved", [0, 1])
async def test_only_actual_capacity_failures_have_capacity_type(
    admission_db: AsyncIOMotorDatabase[dict[str, Any]], reserved: int
) -> None:
    queue = recovery.FormulaRecoveryQueue(
        admission_db,
        max_active_jobs_per_seller=1 + reserved,
        reserved_inventory_slots=reserved,
        allowed_sellers=frozenset({SELLER}),
        enabled_models=frozenset({"orders"}),
    )
    first = recovery.OrderIdsRecoveryRequest(SELLER, ("1",))
    assert await queue.enqueue(first, reopen_terminal=False) == first.key
    assert await queue.enqueue(first, reopen_terminal=False) == first.key
    with pytest.raises(recovery.RecoveryCapacityError, match="capacity") as capacity:
        await queue.enqueue(recovery.OrderIdsRecoveryRequest(SELLER, ("2",)))
    assert isinstance(capacity.value, ValueError)
    for invalid in (
        recovery.OrderIdsRecoveryRequest("2", ("1",)),
        recovery.ShipmentIdsRecoveryRequest(SELLER, ("1",)),
    ):
        with pytest.raises(ValueError) as rejected:
            await queue.enqueue(invalid, reopen_terminal=False)
        assert not isinstance(rejected.value, recovery.RecoveryCapacityError)
    assert await queue.collection.count_documents({}) == 1


@pytest.mark.asyncio
async def test_preservation_never_bypasses_seller_guard(
    admission_db: AsyncIOMotorDatabase[dict[str, Any]],
) -> None:
    queue = recovery.FormulaRecoveryQueue(admission_db)
    request = recovery.OrderIdsRecoveryRequest(SELLER, ("1",))
    await queue.enqueue(request)
    claimed = await queue.claim()
    assert claimed is not None
    assert await queue.finish(claimed, succeeded=True)
    terminal = await queue.collection.find_one({"_id": request.key})
    disabled = recovery.FormulaRecoveryQueue(admission_db, allowed_sellers=frozenset())
    with pytest.raises(ValueError, match="seller is not enabled"):
        await disabled.enqueue(request, reopen_terminal=False)
    assert await queue.collection.find_one({"_id": request.key}) == terminal
