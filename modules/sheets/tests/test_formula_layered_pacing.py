from __future__ import annotations

import asyncio
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from zeler_sheets.formulas import pacing


@pytest.mark.asyncio
async def test_shared_budget_fairness_and_work_conserving_idle_lanes() -> None:
    clock = [datetime(2026, 9, 14, tzinfo=UTC)]
    waits: list[float] = []
    grants: list[str] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)
        clock[0] += timedelta(seconds=seconds)
        await asyncio.sleep(0)

    pacer = pacing.RecoveryRequestPacer(requests_per_minute=4, now=lambda: clock[0], sleep=sleep)

    async def consume(lane: str, count: int) -> None:
        for _ in range(count):
            await pacer.acquire(lane=lane)
            grants.append(lane)

    await asyncio.gather(consume("inventory", 4), consume("ids", 8), consume("ranges", 4))
    assert len(grants) == 16
    for start in range(0, 16, 4):
        assert Counter(grants[start : start + 4]) == {"inventory": 1, "ids": 2, "ranges": 1}
    assert waits == [15.0] * 15
    await consume("inventory", 4)
    assert grants[-4:] == ["inventory"] * 4
    assert waits == [15.0] * 19


@pytest.mark.asyncio
async def test_cancelled_waiters_do_not_leak_or_starve_other_lanes() -> None:
    baseline = asyncio.all_tasks()
    waiting = asyncio.Event()
    release = asyncio.Event()

    async def sleep(seconds: float) -> None:
        waiting.set()
        await release.wait()

    pacer = pacing.RecoveryRequestPacer(requests_per_minute=1, sleep=sleep)
    await pacer.acquire(lane="inventory")
    cancelled = asyncio.create_task(pacer.acquire(lane="ids"))
    await waiting.wait()
    survivor = asyncio.create_task(pacer.acquire(lane="ranges"))
    await asyncio.sleep(0)
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    release.set()
    assert await survivor is True
    await asyncio.sleep(0)
    assert asyncio.all_tasks() == baseline


@pytest.mark.asyncio
async def test_last_waiter_cancellation_stops_quota_timer() -> None:
    baseline = asyncio.all_tasks()
    waiting = asyncio.Event()
    stopped = asyncio.Event()

    async def sleep(seconds: float) -> None:
        waiting.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    pacer = pacing.RecoveryRequestPacer(requests_per_minute=1, sleep=sleep)
    await pacer.acquire(lane="inventory")
    task = asyncio.create_task(pacer.acquire(lane="ids"))
    await waiting.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stopped.is_set()
    assert asyncio.all_tasks() == baseline


class Gateway:
    def __init__(self, delay: float = 0) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.delay = delay

    async def request(self, **kwargs: Any) -> str:
        return await self._call("request", kwargs)

    async def fetch_resource(self, **kwargs: Any) -> str:
        return await self._call("fetch_resource", kwargs)

    async def fetch_resource_once(self, **kwargs: Any) -> str:
        return await self._call("fetch_resource_once", kwargs)

    async def _call(self, name: str, kwargs: dict[str, Any]) -> str:
        self.calls.append((name, kwargs))
        await asyncio.sleep(self.delay)
        return "observed"


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["request", "fetch_resource", "fetch_resource_once"])
async def test_all_gateway_methods_are_paced_and_consume_timeout_option(method: str) -> None:
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    pacer = pacing.RecoveryRequestPacer(requests_per_minute=1, sleep=sleep)
    await pacer.acquire()
    inner = Gateway()
    gateway = pacing.PacedMeliGateway(inner=inner, pacer=pacer, lane="ids")
    assert await getattr(gateway, method)(path="/items", request_timeout=5) == "observed"
    assert len(waits) == 1
    assert inner.calls == [(method, {"path": "/items"})]


@pytest.mark.asyncio
async def test_http_deadline_begins_after_more_than_five_seconds_quota_wait() -> None:
    async def sleep(seconds: float) -> None:
        await asyncio.sleep(5.05)

    pacer = pacing.RecoveryRequestPacer(requests_per_minute=1, sleep=sleep)
    await pacer.acquire(lane="inventory")
    inner = Gateway()
    gateway = pacing.PacedMeliGateway(inner=inner, pacer=pacer, lane="ids")
    assert (
        await pacing.recovery_fetch_resource(gateway, path="/items", request_timeout=5)
        == "observed"
    )
    assert inner.calls == [("fetch_resource", {"path": "/items"})]


@pytest.mark.asyncio
@pytest.mark.parametrize("paced", [False, True])
async def test_http_timeout_still_bounds_actual_provider_call(paced: bool) -> None:
    inner = Gateway(delay=1)
    gateway = (
        pacing.PacedMeliGateway(inner=inner, pacer=pacing.RecoveryRequestPacer(), lane="ids")
        if paced
        else inner
    )
    with pytest.raises(TimeoutError):
        await pacing.recovery_fetch_resource(gateway, path="/items", request_timeout=0.01)
    assert inner.calls == [("fetch_resource", {"path": "/items"})]


@pytest.mark.asyncio
async def test_quota_deadline_is_distinct_from_source_timeout_and_cleans_up() -> None:
    async def sleep(seconds: float) -> None:
        await asyncio.Event().wait()

    baseline = asyncio.all_tasks()
    pacer = pacing.RecoveryRequestPacer(requests_per_minute=1, sleep=sleep)
    await pacer.acquire()
    inner = Gateway()
    gateway = pacing.PacedMeliGateway(inner=inner, pacer=pacer, lane="ranges")
    with (
        pacing.recovery_quota_deadline(asyncio.get_running_loop().time() + 0.01),
        pytest.raises(pacing.LocalQuotaTimeoutError),
    ):
        await gateway.fetch_resource(path="/orders")
    assert inner.calls == []
    assert asyncio.all_tasks() == baseline
    # A deadline context must not leak into the following job.
    fresh = pacing.PacedMeliGateway(inner=inner, pacer=pacing.RecoveryRequestPacer(), lane="ids")
    assert await fresh.fetch_resource(path="/items") == "observed"


@pytest.mark.asyncio
async def test_idle_window_rollover_does_not_allow_extra_requests_in_new_window() -> None:
    clock = [datetime(2026, 9, 14, tzinfo=UTC)]
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)
        clock[0] += timedelta(seconds=seconds)

    pacer = pacing.RecoveryRequestPacer(requests_per_minute=2, now=lambda: clock[0], sleep=sleep)
    assert await pacer.acquire(lane="inventory") is False
    clock[0] += timedelta(seconds=61)
    assert await pacer.acquire(lane="ids") is False
    assert await pacer.acquire(lane="ranges") is True
    assert await pacer.acquire(lane="inventory") is True
    assert waits == [30.0, 30.0]


@pytest.mark.asyncio
async def test_invalid_lane_leaves_shared_budget_available() -> None:
    pacer = pacing.RecoveryRequestPacer(requests_per_minute=1)
    with pytest.raises(ValueError, match="unknown recovery pacing lane"):
        await pacer.acquire(lane="bad")
    assert await pacer.acquire(lane="inventory") is False


@pytest.mark.asyncio
@pytest.mark.parametrize("outer, inner", [(0.01, 1), (1, 0.01)])
async def test_nested_quota_context_never_extends_parent_deadline(
    outer: float, inner: float
) -> None:
    waiting = asyncio.Event()

    async def sleep(seconds: float) -> None:
        waiting.set()
        await asyncio.Event().wait()

    pacer = pacing.RecoveryRequestPacer(requests_per_minute=1, sleep=sleep)
    await pacer.acquire(lane="ids")
    loop = asyncio.get_running_loop()
    with (
        pacing.recovery_quota_deadline(loop.time() + outer),
        pacing.recovery_quota_deadline(loop.time() + inner),
        pytest.raises(pacing.LocalQuotaTimeoutError),
    ):
        async with asyncio.timeout(0.1):
            await pacer.acquire(lane="inventory")
    assert waiting.is_set()


@pytest.mark.asyncio
async def test_1900_items_finish_with_continuous_competitors_and_projection_gaps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Scale 60 seconds to 0.6 seconds. Real coroutine sleeps preserve the gap
    # between batches; competitors stay active for the entire inventory sweep.
    monkeypatch.setattr(pacing, "WINDOW", timedelta(seconds=0.6))
    pacer = pacing.RecoveryRequestPacer(requests_per_minute=180)
    grants: Counter[str] = Counter()
    baseline = asyncio.all_tasks()
    started = asyncio.get_running_loop().time()

    async def competitor(lane: str) -> None:
        while True:
            await pacer.acquire(lane=lane)
            grants[lane] += 1

    competitors = [asyncio.create_task(competitor(lane)) for lane in ("ids", "ranges")]
    try:
        async with asyncio.timeout(9):  # 900 simulated seconds
            for _ in range(95):
                await pacer.acquire(lane="inventory")
                grants["inventory"] += 1
                await asyncio.sleep(0.03)  # Three seconds of per-batch projection.
        elapsed = (asyncio.get_running_loop().time() - started) * 100
        assert elapsed < 900
        assert grants["inventory"] * 20 == 1900
        assert grants["ids"] > 95 and grants["ranges"] > 95
    finally:
        for task in competitors:
            task.cancel()
        await asyncio.gather(*competitors, return_exceptions=True)
    assert asyncio.all_tasks() == baseline


@pytest.mark.asyncio
async def test_lane_admissions_are_spread_across_the_shared_minute() -> None:
    clock = [datetime(2026, 9, 14, tzinfo=UTC)]
    granted: list[datetime] = []

    async def sleep(seconds: float) -> None:
        clock[0] += timedelta(seconds=seconds)

    pacer = pacing.RecoveryRequestPacer(requests_per_minute=180, now=lambda: clock[0], sleep=sleep)
    for _ in range(181):
        await pacer.acquire(lane="inventory")
        granted.append(clock[0])
    assert all(
        (right - left).total_seconds() >= 1 / 3
        for left, right in zip(granted, granted[1:], strict=False)
    )
    assert (granted[-1] - granted[0]).total_seconds() >= 60


@pytest.mark.asyncio
async def test_legacy_calls_cannot_bypass_spacing_after_sharing_a_lane_pacer() -> None:
    clock = [datetime(2026, 9, 14, tzinfo=UTC)]
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)
        clock[0] += timedelta(seconds=seconds)

    pacer = pacing.RecoveryRequestPacer(requests_per_minute=4, now=lambda: clock[0], sleep=sleep)
    assert await pacer.acquire(lane="inventory") is False
    assert await pacer.acquire() is True
    assert await pacer.acquire(lane="ranges") is True
    assert waits == [15.0, 15.0]
