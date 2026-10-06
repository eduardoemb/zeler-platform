"""Actual RETURNS collector must not retry a scoped pilot 429."""

from __future__ import annotations

import copy
import os
import socket
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from gateway.tests.test_pilot_get_budget_allocation import allocation_plan
from test_devoluciones_reconciliation import (
    END,
    START,
    FakeMonotonicClock,
    HydratingSource,
)
from test_history_pilot_rate_limit_stop import PausingPlans, Remote

from zeler_sheets import devoluciones_runner as runner
from zeler_sheets.devoluciones_reconciliation import (
    ClaimInventoryError,
    GatewayDevolucionesSource,
    SourceCallBudgetError,
    collect_devoluciones_snapshot,
)


class Source(HydratingSource):
    def __init__(self, client: Any) -> None:
        super().__init__()
        self.adapter = GatewayDevolucionesSource(client, single_attempt=True)

    async def get_returns(self, *, seller_id: str, claim_id: str) -> dict[str, Any]:
        return await self.adapter.get_returns(seller_id=seller_id, claim_id=claim_id)


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(os, "environ", {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path)})

    def denied(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("no sockets")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)


@pytest.mark.asyncio
@pytest.mark.parametrize("metadata", ["1", None, "0"])
async def test_returns_collector_has_one_charge_and_no_second_attempt(
    monkeypatch: pytest.MonkeyPatch, metadata: str | None
) -> None:
    plans, remote = PausingPlans(allocation_plan()), Remote(metadata)
    assert plans.row is not None
    captured = copy.deepcopy(plans.row)
    monkeypatch.setattr(
        runner,
        "_validated_onboarding_plan",
        AsyncMock(side_effect=lambda *args, **kwargs: copy.deepcopy(plans.row)),
    )
    charges = 0

    async def charge() -> None:
        nonlocal charges
        charges += 1

    client = runner.OnboardingDevolucionesGateway(
        {"sheets_history_backfill_plans": plans},
        captured,
        remote,
        charge=charge,
        now=lambda: remote.clock,
    )
    clock = FakeMonotonicClock()
    with pytest.raises(SourceCallBudgetError):
        await collect_devoluciones_snapshot(
            source=Source(client),
            seller_id="82453304",
            start=START,
            end=END,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )
    assert charges == remote.calls == 1 and len(plans.pauses) == 1


@pytest.mark.asyncio
async def test_pilot_stop_becomes_wait_without_failed_window_or_budget_mislabel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from test_devoluciones_onboarding_diagnostic import execute

    from zeler_sheets.history_pilot_stop import HistoryPilotStopError

    result, log, caught = await execute(monkeypatch, HistoryPilotStopError("remote_429"))
    assert result["reason"] == "policy_wait" and result["state"] == "active"
    assert caught == [] and log.calls == []


@pytest.mark.asyncio
async def test_ordinary_returns_retains_existing_bounded_throttle_retry() -> None:
    remote = Remote()
    clock = FakeMonotonicClock()
    with pytest.raises(ClaimInventoryError):
        await collect_devoluciones_snapshot(
            source=Source(remote),
            seller_id="82453304",
            start=START,
            end=END,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )
    assert remote.calls == 3
