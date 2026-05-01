from __future__ import annotations

import pytest

from zeler_bootstrap.dispatcher import BootstrapDispatcher

from .test_dispatcher import FakeCloudRunJobsClient, FakeDb


@pytest.mark.asyncio
async def test_acquires_under_cap() -> None:
    db = FakeDb()
    dispatcher = BootstrapDispatcher(db, FakeCloudRunJobsClient(), max_concurrent=2)

    acquired = await dispatcher._acquire_lock()

    assert acquired is True
    assert db["bootstrap_dispatcher_locks"].docs["counter"]["count"] == 1


@pytest.mark.asyncio
async def test_returns_backpressure_at_cap() -> None:
    db = FakeDb()
    db["bootstrap_jobs"].docs["job-1"] = {
        "_id": "job-1",
        "seller_id": "123",
        "state": "pending",
        "dispatch_attempts": 0,
    }
    db["bootstrap_dispatcher_locks"].docs["counter"] = {"_id": "counter", "count": 1}

    result = await BootstrapDispatcher(
        db, FakeCloudRunJobsClient(), max_concurrent=1
    ).handle_accounts_linked({"seller_id": "123"})

    assert result == "backpressure"
    assert db["bootstrap_jobs"].docs["job-1"]["state"] == "pending"


@pytest.mark.asyncio
async def test_release_decrements_counter() -> None:
    db = FakeDb()
    db["bootstrap_dispatcher_locks"].docs["counter"] = {"_id": "counter", "count": 2}
    dispatcher = BootstrapDispatcher(db, FakeCloudRunJobsClient(), max_concurrent=5)

    await dispatcher._release_lock()

    assert db["bootstrap_dispatcher_locks"].docs["counter"]["count"] == 1
