"""TDD: pilot history backfill wires into the existing refresh supervisor.

The refresh supervisor must call a history backfill callback once per
refresh cycle for each enabled seller, with the same failure isolation it
gives devoluciones and other optional steps. The callback receives the
seller ID and returns True when it admitted work, so the cycle reports
progress honestly.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from zeler_sheets.formulas.refresh import ZelerDataRefreshSupervisor


class FakeExplorer:
    def __init__(self, sellers: tuple[str, ...]) -> None:
        self._sellers = sellers

    async def discover_sellers(self) -> tuple[str, ...]:
        return self._sellers


class FakePlanner:
    async def plan(self, *, seller_id: str, mode: str = "fast") -> bool:
        return False


@pytest.mark.asyncio
async def test_supervisor_calls_history_backfill_per_seller() -> None:
    history_backfill = AsyncMock(return_value=True)
    supervisor = ZelerDataRefreshSupervisor(
        explorer=FakeExplorer(("82453304", "999")),
        planner=FakePlanner(),
        history_backfill=history_backfill,
        interval_seconds=1,
        inventory_interval_seconds=1,
    )
    await supervisor.run_cycle()
    assert history_backfill.call_count == 2
    called_sellers = {call.args[0] for call in history_backfill.call_args_list}
    assert called_sellers == {"82453304", "999"}


@pytest.mark.asyncio
async def test_supervisor_reports_history_work_as_admitted() -> None:
    history_backfill = AsyncMock(return_value=True)
    supervisor = ZelerDataRefreshSupervisor(
        explorer=FakeExplorer(("82453304",)),
        planner=FakePlanner(),
        history_backfill=history_backfill,
        interval_seconds=1,
        inventory_interval_seconds=1,
    )
    assert await supervisor.run_cycle() is True


@pytest.mark.asyncio
async def test_history_backfill_failure_does_not_stop_the_cycle() -> None:
    history_backfill = AsyncMock(side_effect=RuntimeError("history storage unavailable"))
    supervisor = ZelerDataRefreshSupervisor(
        explorer=FakeExplorer(("82453304",)),
        planner=FakePlanner(),
        history_backfill=history_backfill,
        interval_seconds=1,
        inventory_interval_seconds=1,
    )
    assert await supervisor.run_cycle() is False
    assert supervisor.health_status == "ok"
