from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

from zeler_sheets.formulas.recovery import ItemInventoryRecoveryRequest
from zeler_sheets.formulas.refresh import ZelerDataRefreshPlanner, ZelerDataRefreshSupervisor


@pytest.mark.asyncio
async def test_inventory_restarts_within_30_seconds_without_range_churn() -> None:
    elapsed = 0.0
    broad: list[float] = []
    inventory: list[float] = []
    side_effects: list[float] = []

    class Explorer:
        async def discover_sellers(self) -> tuple[str, ...]:
            return ("82453304",)

    class Planner:
        async def plan(self, *, seller_id: str, mode: str = "fast") -> bool:
            broad.append(elapsed)
            return True

    async def admit_inventory(seller_id: str) -> bool:
        inventory.append(elapsed)
        return True

    async def renew_returns(seller_id: str) -> bool:
        side_effects.append(elapsed)
        return False

    supervisor = ZelerDataRefreshSupervisor(
        explorer=Explorer(),
        planner=Planner(),
        inventory_refresher=admit_inventory,
        devoluciones_runner=renew_returns,
        monotonic=lambda: elapsed,
        now=lambda: datetime(2026, 9, 10, 0, tzinfo=UTC),
    )

    async def advance(delay: float) -> None:
        nonlocal elapsed
        elapsed += delay
        if elapsed > 900:
            supervisor._stop_event.set()

    supervisor._wait_or_stop = advance  # type: ignore[method-assign]
    await supervisor._run()
    assert inventory[:2] == [30, 60]
    assert max(b - a for a, b in zip([0, *inventory], inventory, strict=False)) <= 30
    assert broad == [0, 900]
    assert side_effects == [0, 900]


@pytest.mark.asyncio
async def test_inventory_tick_is_scoped_and_emits_only_existing_inventory_intent() -> None:
    requests: list[Any] = []

    class Queue:
        async def enqueue(self, request: Any) -> str:
            requests.append(request)
            return str(request.key)

    planner = ZelerDataRefreshPlanner(
        queue=Queue(),
        enabled_models={"orders", "item_formula_rows"},
        allowed_sellers=frozenset({"82453304"}),
    )
    assert await planner.plan_inventory("82453304") is True
    assert await planner.plan_inventory("999") is False
    assert len(requests) == 1
    assert isinstance(requests[0], ItemInventoryRecoveryRequest)
    assert requests[0].key == ItemInventoryRecoveryRequest("82453304").key


@pytest.mark.asyncio
async def test_inventory_failure_isolated_and_stop_drains_owned_loop() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    seen: list[str] = []

    class Explorer:
        async def discover_sellers(self) -> tuple[str, ...]:
            return ("1", "2")

    class Planner:
        async def plan(self, *, seller_id: str, mode: str = "fast") -> bool:
            return True

    async def admit_inventory(seller_id: str) -> bool:
        seen.append(seller_id)
        if seller_id == "1":
            raise RuntimeError("one seller failed")
        entered.set()
        await release.wait()
        return True

    supervisor = ZelerDataRefreshSupervisor(
        explorer=Explorer(),
        planner=Planner(),
        inventory_refresher=admit_inventory,
        inventory_interval_seconds=0.001,
    )
    await supervisor.start()
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        stop = asyncio.create_task(supervisor.stop())
        await asyncio.sleep(0)
        assert not stop.done()
        release.set()
        await asyncio.wait_for(stop, timeout=1)
        assert seen == ["1", "2"]
        assert supervisor._task is not None and supervisor._task.done()
        assert supervisor.health_status == "stopped"
    finally:
        release.set()
        await supervisor.stop()
