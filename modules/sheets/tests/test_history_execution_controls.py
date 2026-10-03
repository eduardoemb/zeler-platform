"""Persisted pause, five-source policy and pilot deadline/cap fence real work."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from test_history_onboarding import Gateway
from test_history_onboarding import db as db

from zeler_platform_core.history_onboarding import SOURCES, admit_history_onboarding
from zeler_sheets.history_onboarding import HistoryOnboardingWorker, PlanBudgetGateway


async def prepare(db: Any, now: datetime) -> dict[str, Any]:
    await admit_history_onboarding(db, "82453304", now=now)
    await db.meli_accounts.insert_one({"_id": "pilot", "seller_id": 82453304, "status": "active"})
    return cast(
        dict[str, Any], await db.sheets_history_backfill_plans.find_one({"_id": "82453304"})
    )


@pytest.mark.asyncio
async def test_coordinator_rotates_persisted_five_sources_never_full(db: Any) -> None:
    now = datetime(2026, 10, 3, 12, tzinfo=UTC)
    await prepare(db, now)
    sources = list(SOURCES[:-1])
    await db.sheets_history_backfill_plans.update_one(
        {"_id": "82453304"},
        {"$set": {"sources": sources, "onboarding_sources.full_withdrawals": {"state": "blocked"}}},
    )
    seen: list[str] = []

    class Worker(HistoryOnboardingWorker):
        async def advance_source(self, plan: Any, source: str, *args: Any) -> dict[str, Any]:
            seen.append(source)
            return {"state": "ready"}

    worker = Worker(
        db, Gateway(), Gateway(), now=lambda: now, allowed_sellers=frozenset({"82453304"})
    )
    for _ in range(10):
        await db.sheets_history_backfill_plans.update_one(
            {"_id": "82453304"}, {"$set": {"next_cycle_at": now}}
        )
        assert await worker.process_once() == "processed"
    assert seen == sources * 2
    plan = await db.sheets_history_backfill_plans.find_one({"_id": "82453304"})
    assert plan["onboarding_status"] == "ready"
    assert plan["budget"]["full_withdrawals"]["consumed"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fields",
    [
        {"state": "paused"},
        {"execution_until": datetime(2026, 10, 3, 12, tzinfo=UTC)},
        {"execution_utc_day": "2026-10-02"},
        {"execution_attempt_limit": 2500, "execution_consumed": 2500},
    ],
)
async def test_paused_expired_or_capped_plan_is_not_claimed_or_renewed(
    db: Any, fields: Any
) -> None:
    now = datetime(2026, 10, 3, 12, tzinfo=UTC)
    await prepare(db, now)
    await db.sheets_history_backfill_plans.update_one({"_id": "82453304"}, {"$set": fields})
    before = await db.sheets_history_backfill_plans.find_one({"_id": "82453304"})
    worker = HistoryOnboardingWorker(
        db, Gateway(), Gateway(), now=lambda: now, allowed_sellers=frozenset({"82453304"})
    )
    assert await worker.process_once() == "idle"
    assert await db.sheets_history_backfill_plans.find_one({"_id": "82453304"}) == before


@pytest.mark.asyncio
async def test_every_phase_shares_monotonic_cap_preserving_existing_counters(db: Any) -> None:
    now = datetime(2026, 10, 3, 12, tzinfo=UTC)
    await prepare(db, now)
    await db.sheets_history_backfill_plans.update_one(
        {"_id": "82453304"},
        {
            "$set": {
                "execution_until": now + timedelta(minutes=90),
                "execution_utc_day": "2026-10-03",
                "execution_consumed": 7,
                "execution_id": "a" * 32,
                "execution_attempt_limit": 9,
                "total_consumed": 11,
                "budget.orders.consumed": 11,
            }
        },
    )

    class TracedGateway(Gateway):
        def __init__(self) -> None:
            super().__init__()
            self.traces: list[str] = []

        async def fetch_resource_once(self, **kwargs: Any) -> Any:
            self.traces.append(kwargs.pop("headers")["X-Zeler-History-Trace"])
            return await self.fetch_resource(**kwargs)

    source = TracedGateway()
    initial = PlanBudgetGateway(db, source, "82453304", "orders", now=lambda: now)
    await initial.fetch_resource(seller_id="82453304", path="/orders/1")
    upkeep = PlanBudgetGateway(db, source, "82453304", "messages", now=lambda: now)
    upkeep.incremental = True
    await upkeep.fetch_resource(seller_id="82453304", path="/messages/packs/1/sellers/82453304")
    with pytest.raises(ValueError, match="budget|execution"):
        await initial.fetch_resource(seller_id="82453304", path="/orders/2")
    with pytest.raises(ValueError, match="budget|execution"):
        await upkeep.fetch_resource(seller_id="82453304", path="/messages/packs/2/sellers/82453304")
    plan = await db.sheets_history_backfill_plans.find_one({"_id": "82453304"})
    assert plan["execution_consumed"] == 9
    assert plan["execution_charged"] == {
        "a" * 32: {"orders": {"initial": 1}, "messages": {"maintenance": 1}}
    }
    assert plan["total_consumed"] == 12 and plan["budget"]["orders"]["consumed"] == 12
    assert plan["incremental_consumed"] == 1 and len(source.calls) == 2
    assert source.traces == [
        "h1-" + "a" * 32 + ":orders:initial",
        "h1-" + "a" * 32 + ":messages:maintenance",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("incremental", [False, True])
async def test_deadline_and_next_utc_day_deny_inflight_guard_without_quota_reset(
    db: Any, incremental: bool
) -> None:
    now = datetime(2026, 10, 3, 23, 59, tzinfo=UTC)
    await prepare(db, now)
    await db.sheets_history_backfill_plans.update_one(
        {"_id": "82453304"},
        {
            "$set": {
                "execution_until": now + timedelta(minutes=1),
                "execution_utc_day": "2026-10-03",
                "incremental_day": "2026-10-03",
                "incremental_consumed": 2,
                "incremental_source_consumed": dict.fromkeys(SOURCES, 2),
            }
        },
    )
    source = Gateway()
    guard = PlanBudgetGateway(
        db, source, "82453304", "orders", now=lambda: now + timedelta(minutes=1)
    )
    guard.incremental = incremental
    with pytest.raises(ValueError, match="budget|execution"):
        await guard.fetch_resource(seller_id="82453304", path="/orders/1")
    plan = await db.sheets_history_backfill_plans.find_one({"_id": "82453304"})
    assert not source.calls and plan["incremental_day"] == "2026-10-03"
    assert plan["incremental_consumed"] == 2


@pytest.mark.asyncio
async def test_late_gateway_wait_is_deferred_not_invalid_source(db: Any) -> None:
    import httpx

    from zeler_sheets.formulas.pacing import HistoryPolicyWaitError

    now = datetime(2026, 10, 3, 12, tzinfo=UTC)
    await prepare(db, now)

    class LateDenied(Gateway):
        async def fetch_resource_once(self, **kwargs: Any) -> Any:
            request = httpx.Request("GET", "http://gateway.test/proxy/meli/orders/1")
            raise httpx.HTTPStatusError(
                "policy wait",
                request=request,
                response=httpx.Response(
                    412,
                    request=request,
                    headers={"X-Zeler-History-Policy-Status": "wait"},
                ),
            )

    guard = PlanBudgetGateway(db, LateDenied(), "82453304", "orders", now=lambda: now)
    with pytest.raises(HistoryPolicyWaitError):
        await guard.fetch_resource(seller_id="82453304", path="/orders/1")


@pytest.mark.asyncio
async def test_coordinator_policy_wait_does_not_consume_source_failure(db: Any) -> None:
    from zeler_sheets.formulas.pacing import HistoryPolicyWaitError

    now = datetime(2026, 10, 3, 12, tzinfo=UTC)
    await prepare(db, now)

    class HeldCoordinator(HistoryOnboardingWorker):
        async def advance_source(self, *args: Any, **kwargs: Any) -> Any:
            raise HistoryPolicyWaitError("late pause")

    worker = HeldCoordinator(db, Gateway(), Gateway(), now=lambda: now)
    assert await worker.process_once() == "processed"
    plan = await db.sheets_history_backfill_plans.find_one({"_id": "82453304"})
    entry = plan["onboarding_sources"]["orders"]
    assert entry["state"] == "pending" and entry["reason"] == "policy_wait"
    assert entry.get("consecutive_failures", 0) == 0
    assert "next_attempt_at" not in entry


@pytest.mark.asyncio
@pytest.mark.parametrize("api", ["fetch", "request"])
async def test_concurrent_policy_charges_cannot_cluster_paced_rpc_starts(api: str) -> None:
    import asyncio

    import httpx

    from zeler_sheets.formulas.pacing import PacedMeliGateway

    now = datetime(2026, 10, 3, 12, tzinfo=UTC)
    clock, charges, starts, grants = [now], [], [], []
    charged = asyncio.Event()

    class Pacer:
        async def acquire(self, **kwargs: Any) -> bool:
            grants.append(True)
            clock[0] += timedelta(microseconds=333334)
            return True

    class Remote:
        async def fetch_resource_once(self, **kwargs: Any) -> Any:
            starts.append(clock[0])
            return {}

        async def fetch_resource(self, **kwargs: Any) -> Any:
            return await self.fetch_resource_once(**kwargs)

        async def request(self, **kwargs: Any) -> Any:
            starts.append(clock[0])
            return httpx.Response(200, headers={"X-Zeler-Upstream-Attempts": "1"})

    class Guard(PlanBudgetGateway):
        async def charge(self) -> None:
            charges.append(True)
            if len(charges) == 2:
                charged.set()
            await charged.wait()

        async def check_dates(self, path: str) -> None:
            pass

    physical = PacedMeliGateway(inner=Remote(), pacer=cast(Any, Pacer()), lane="ids")
    guards = [Guard({}, physical, "82453304", "orders", now=lambda: clock[0]) for _ in range(2)]
    if api == "fetch":
        await asyncio.gather(
            *(guard.fetch_resource(seller_id="82453304", path="/orders/1") for guard in guards)
        )
    else:
        await asyncio.gather(
            *(
                guard.request(method="GET", seller_id="82453304", path="/orders/1")
                for guard in guards
            )
        )
    assert len(charges) == len(starts) == len(grants) == 2
    assert (starts[1] - starts[0]).total_seconds() >= 0.333333


@pytest.mark.asyncio
@pytest.mark.parametrize("api", ["fetch", "request"])
@pytest.mark.parametrize("crossing", ["deadline", "utc_day"])
async def test_reserved_credit_is_not_dispatched_after_pacing_crosses_window(
    api: str, crossing: str
) -> None:
    import httpx

    from zeler_sheets.formulas.pacing import HistoryPolicyWaitError, PacedMeliGateway

    now = datetime(2026, 10, 3, 23, 59, 59, tzinfo=UTC)
    clock, charges, calls, grants = [now], [], [], []

    class Pacer:
        async def acquire(self, **kwargs: Any) -> bool:
            grants.append(True)
            clock[0] += timedelta(seconds=2)
            return True

    class Remote:
        async def fetch_resource_once(self, **kwargs: Any) -> Any:
            calls.append(True)
            return {}

        async def fetch_resource(self, **kwargs: Any) -> Any:
            return await self.fetch_resource_once(**kwargs)

        async def request(self, **kwargs: Any) -> Any:
            calls.append(True)
            return httpx.Response(200, headers={"X-Zeler-Upstream-Attempts": "1"})

    class Guard(PlanBudgetGateway):
        async def charge(self) -> None:
            charges.append(True)
            self._charged_plan = (
                {"execution_until": now + timedelta(seconds=1)}
                if crossing == "deadline"
                else {"execution_utc_day": "2026-10-03"}
            )

        async def check_dates(self, path: str) -> None:
            pass

    physical = PacedMeliGateway(inner=Remote(), pacer=cast(Any, Pacer()), lane="ids")
    guard = Guard({}, physical, "82453304", "orders", now=lambda: clock[0])
    with pytest.raises(HistoryPolicyWaitError, match="execution"):
        if api == "fetch":
            await guard.fetch_resource(seller_id="82453304", path="/orders/1")
        else:
            await guard.request(method="GET", seller_id="82453304", path="/orders/1")
    assert charges == [True] and grants == [True] and calls == []
