from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest

from zeler_sheets import consumer
from zeler_sheets.formulas.pacing import LocalQuotaTimeoutError
from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker


@pytest.mark.asyncio
async def test_inventory_progresses_while_range_job_is_blocked() -> None:
    progress = asyncio.Event()
    release = asyncio.Event()

    class Inventory:
        async def process_once(self) -> str:
            progress.set()
            return "idle"

    class History:
        async def process_once(self) -> str:
            await release.wait()
            return "idle"

    lanes = [
        consumer.SyncJobsPollerSupervisor(Inventory()),
        consumer.SyncJobsPollerSupervisor(History()),
    ]
    supervisor = consumer.FormulaRecoverySupervisor(tuple(lanes))
    await supervisor.start()
    try:
        await asyncio.wait_for(progress.wait(), timeout=1)
        assert supervisor.health_status == "ok"
    finally:
        release.set()
        await supervisor.stop()
    assert all(lane.health_status == "stopped" for lane in lanes)


@pytest.mark.asyncio
async def test_lane_failure_is_observed_and_all_lanes_stop() -> None:
    class Broken:
        async def process_once(self) -> str:
            raise RuntimeError("test failure")

    child = consumer.SyncJobsPollerSupervisor(Broken(), restart_delays=())
    supervisor = consumer.FormulaRecoverySupervisor((child,))
    await supervisor.start()
    with pytest.raises(RuntimeError, match="restart budget"):
        await supervisor.wait()
    assert supervisor.health_status == "error"
    await supervisor.stop()


@pytest.mark.asyncio
async def test_worker_defers_local_quota_without_reporting_source_failure() -> None:
    job = {"_id": "job", "read_model": "item_formula_rows"}

    class Queue:
        def __init__(self) -> None:
            self.deferred: list[Any] = []

        async def claim(self, *, lane: str) -> dict[str, Any]:
            assert lane == "inventory"
            return job

        async def defer_quota(self, owned: dict[str, Any]) -> bool:
            self.deferred.append(owned)
            return True

        async def finish(self, *args: Any, **kwargs: Any) -> None:
            pytest.fail("local budget wait cannot consume source retries")

    class Worker(FormulaRecoveryWorker):
        async def _items(self, owned: dict[str, Any]) -> None:
            raise LocalQuotaTimeoutError

    queue = Queue()
    worker = Worker(db=None, queue=cast("Any", queue), gateway=None, lane="inventory")
    assert await worker.process_one()
    assert queue.deferred == [job]
