"""A year of DEVOLUCIONES: one backward window, only with what nothing more recent wants.

Real-Mongo behavior end to end is in ``tests/integration/test_year_history_new_sellers.py``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ServerSelectionTimeoutError
from structlog.testing import capture_logs

from zeler_sheets import devoluciones_runner as runner
from zeler_sheets.devoluciones_runner import (
    YEAR_HISTORY_AUTHORIZATION,
    advance_due_devoluciones_run,
    advance_year_history_devoluciones,
    year_history_binding,
    year_history_bounds,
)
from zeler_sheets.formulas.refresh import ZelerDataRefreshSupervisor
from zeler_sheets.formulas.year_history import year_history_target

SELLER = "90000001"
NOW = datetime(2026, 10, 12, 14, 35, tzinfo=UTC)
TARGET = year_history_target(NOW)


def test_the_window_ends_at_the_oldest_certificate_and_stops_at_the_year() -> None:
    oldest = datetime(2026, 7, 14, tzinfo=UTC)
    assert year_history_bounds(oldest, now=NOW) == (oldest - timedelta(days=10), oldest)
    # The last window is shorter: it stops at the year.
    near = TARGET + timedelta(days=4)
    assert year_history_bounds(near, now=NOW) == (TARGET, near)
    assert year_history_bounds(TARGET, now=NOW) is None
    assert year_history_bounds(None, now=NOW) is None
    # The admission day is in the identity, like the tail.
    first = year_history_binding(SELLER, TARGET, near, admitted_on=NOW.date())
    again = year_history_binding(SELLER, TARGET, near, admitted_on=NOW.date())
    tomorrow = year_history_binding(
        SELLER, TARGET, near, admitted_on=(NOW + timedelta(days=1)).date()
    )
    assert first.run_id == again.run_id != tomorrow.run_id
    assert first.authorization_id == YEAR_HISTORY_AUTHORIZATION


@pytest_asyncio.fixture
async def devoluciones_db() -> AsyncIterator[Any]:
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        "mongodb://127.0.0.1:27028/?directConnection=true",
        serverSelectionTimeoutMS=1000,
        tz_aware=True,
    )
    db = client[f"zeler_devoluciones_year_{uuid4().hex}"]
    connected = False
    try:
        try:
            await client.admin.command("ping")
            connected = True
        except ServerSelectionTimeoutError:
            pytest.skip("dedicated local Mongo on port 27028 is unavailable")
        yield db
    finally:
        if connected:
            await client.drop_database(db.name)
        client.close()


async def _certificate_seller(db: Any, oldest: datetime, **control: Any) -> None:
    await db.sheets_devoluciones_operations.insert_one(
        {
            "seller_id": SELLER,
            "scope": "devoluciones",
            "coverage_mode": "active",
            "fence": 3,
            "coverage_ack_fence": 3,
            "coverage_epoch": 1,
            **control,
        }
    )
    await db.sheets_devoluciones_certificates.insert_many(
        [
            {"seller_id": SELLER, "coverage_epoch": 1, "date_from": oldest},
            {"seller_id": SELLER, "coverage_epoch": 1, "date_from": oldest + timedelta(days=10)},
            # Another epoch's certificate does not count.
            {"seller_id": SELLER, "coverage_epoch": 0, "date_from": TARGET},
        ]
    )


class _Admission:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.created: list[Any] = []
        monkeypatch.setattr(runner, "_admit_automatic_run", self.admit)

    async def admit(self, db: Any, binding: Any, *, kind: str, current: datetime) -> None:
        self.created.append((binding, kind))


async def _eligible(seller_id: str) -> bool:
    return True


async def _ineligible(seller_id: str) -> bool:
    return False


@pytest.mark.asyncio
async def test_a_certificate_seller_gets_one_window_back_from_its_oldest_certificate(
    devoluciones_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    oldest = datetime(2026, 7, 14, tzinfo=UTC)
    await _certificate_seller(devoluciones_db, oldest)
    admission = _Admission(monkeypatch)
    advanced: list[str] = []

    async def advance(db: Any, run_id: str, *, now: Any = None) -> dict[str, int]:
        advanced.append(run_id)
        return {"advanced": 1, "finalized": 1}

    assert await advance_year_history_devoluciones(
        devoluciones_db, SELLER, eligible=_eligible, now=lambda: NOW, advance=advance
    )
    ((binding, kind),) = admission.created
    assert kind == "year_history"
    assert (binding.start, binding.end) == (oldest - timedelta(days=10), oldest)
    assert advanced == [binding.run_id]


@pytest.mark.asyncio
async def test_the_paused_pilot_gets_its_window_and_its_plan_is_left_alone(
    devoluciones_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Decision of 2026-10-13: a legacy history plan no longer excludes the seller."""
    oldest = datetime(2026, 6, 1, tzinfo=UTC)
    await _certificate_seller(devoluciones_db, oldest)
    plan = {"_id": SELLER, "seller_id": SELLER, "state": "paused"}
    await devoluciones_db.sheets_history_backfill_plans.insert_one(plan)
    admission = _Admission(monkeypatch)

    async def advance(db: Any, run_id: str, *, now: Any = None) -> dict[str, int]:
        return {"advanced": 1, "finalized": 1}

    assert await advance_year_history_devoluciones(
        devoluciones_db, SELLER, eligible=_eligible, now=lambda: NOW, advance=advance
    )
    ((binding, kind),) = admission.created
    assert kind == "year_history"
    assert (binding.start, binding.end) == (oldest - timedelta(days=10), oldest)
    assert await devoluciones_db.sheets_history_backfill_plans.find_one({"_id": SELLER}) == plan


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["legacy_mode", "ineligible", "covered", "failed"])
async def test_no_window_for_a_legacy_seller_or_a_covered_one(
    devoluciones_db: Any, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    oldest = TARGET if case == "covered" else datetime(2026, 7, 14, tzinfo=UTC)
    await _certificate_seller(
        devoluciones_db, oldest, **({"coverage_mode": "legacy"} if case == "legacy_mode" else {})
    )
    if case == "failed":
        binding = year_history_binding(
            SELLER, oldest - timedelta(days=10), oldest, admitted_on=NOW.date()
        )
        await devoluciones_db.sheets_devoluciones_runs.insert_one(
            {"_id": binding.run_id, "seller_id": SELLER, "state": "failed"}
        )
    admission = _Admission(monkeypatch)

    async def advance(db: Any, run_id: str, *, now: Any = None) -> dict[str, int]:
        raise AssertionError("no source work")

    assert not await advance_year_history_devoluciones(
        devoluciones_db,
        SELLER,
        eligible=_ineligible if case == "ineligible" else _eligible,
        now=lambda: NOW,
        advance=advance,
    )
    assert admission.created == []


@pytest.mark.asyncio
async def test_the_regular_pass_never_picks_up_a_year_history_run(
    devoluciones_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def no_renewal(*_: Any, **__: Any) -> bool:
        return False

    async def no_tail(*_: Any, **__: Any) -> None:
        return None

    async def advance(*, db: Any, run_id: str, now: Any = None) -> dict[str, int]:
        raise AssertionError("the year-history pass owns its runs")

    monkeypatch.setattr(runner, "renew_devoluciones_marker_if_proven", no_renewal)
    await devoluciones_db.sheets_devoluciones_runs.insert_one(
        {
            "_id": "year",
            "seller_id": SELLER,
            "scope": "devoluciones",
            "state": "authorized",
            "authorization_id": YEAR_HISTORY_AUTHORIZATION,
            "expires_at": NOW + timedelta(minutes=10),
            "created_at": NOW,
        }
    )
    assert not await advance_due_devoluciones_run(
        devoluciones_db,
        SELLER,
        now=lambda: NOW,
        advance=advance,
        history_work_enabled=False,
        admit_tail=no_tail,
    )


@pytest.mark.asyncio
async def test_renewal_runs_another_batch_while_batches_come_back_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batches: list[int] = []
    attempted = [20, 20, 20, 20]

    async def control(db: Any, seller_id: str, **_: Any) -> dict[str, Any]:
        return {"coverage_mode": "active"}

    async def renew(db: Any, seller_id: str, *, now: Any = None) -> dict[str, Any]:
        batches.append(attempted[len(batches)])
        return {"attempted": batches[-1], "renewed": batches[-1], "failed": 0, "reason": None}

    from zeler_platform_core import devoluciones_certificates

    monkeypatch.setattr(devoluciones_certificates, "coverage_control", control)
    monkeypatch.setattr(runner, "renew_due_certificates", renew)
    # A year of windows: two full batches and the rest; never more than three.
    attempted[:] = [20, 20, 3]
    assert await runner.renew_devoluciones_marker_if_proven(None, SELLER)
    assert batches == [20, 20, 3]
    batches.clear()
    attempted[:] = [20, 20, 20, 20]
    assert await runner.renew_devoluciones_marker_if_proven(None, SELLER)
    assert batches == [20, 20, 20]
    # The pilot's one partial batch is unchanged.
    batches.clear()
    attempted[:] = [12]
    assert await runner.renew_devoluciones_marker_if_proven(None, SELLER)
    assert batches == [12]


class _Explorer:
    async def discover_sellers(self) -> tuple[str, ...]:
        return ("1", "2")


class _Planner:
    async def plan(self, *, seller_id: str, mode: str = "fast") -> bool:
        return False


@pytest.mark.asyncio
async def test_year_windows_take_only_what_the_tail_and_intraday_cuts_leave() -> None:
    calls: list[tuple[str, str]] = []
    regular_due: set[str] = {"1"}
    intraday_due: set[str] = set()

    def advancer(name: str, due: set[str]) -> Any:
        async def advance(seller_id: str) -> bool:
            calls.append((name, seller_id))
            return seller_id in due

        return advance

    async def year_history(seller_id: str) -> bool:
        calls.append(("year", seller_id))
        if seller_id == "1":
            raise RuntimeError("lease busy")
        return True

    async def portions(sellers: tuple[str, ...]) -> bool:
        calls.append(("portion", ",".join(sellers)))
        return True

    supervisor = ZelerDataRefreshSupervisor(
        explorer=_Explorer(),
        planner=_Planner(),
        devoluciones_advancer=advancer("regular", regular_due),
        devoluciones_intraday_advancer=advancer("intraday", intraday_due),
        devoluciones_year_history_advancer=year_history,
        year_history_planner=portions,
        interval_seconds=900,
        now=lambda: NOW,
    )
    with capture_logs() as logs:
        # The tail takes the window; the portion is planned after the pass.
        await supervisor.run_cycle()
        assert calls == [("regular", "1"), ("portion", "1,2")]
        calls.clear()
        intraday_due.add("1")
        regular_due.clear()
        await supervisor.run_cycle()
        assert [name for name, _ in calls] == ["regular", "regular", "intraday", "portion"]
        calls.clear()
        intraday_due.clear()
        # Nothing more recent: a year window, in turns; a failure blocks no one.
        await supervisor.run_cycle()
        await supervisor.run_cycle()
    years = [seller for name, seller in calls if name == "year"]
    assert years == ["1", "2"]
    failures = [log for log in logs if log["event"] == "zelerdata.devoluciones_year_history_failed"]
    assert [log["seller_id"] for log in failures] == ["1"]
    completed = [log for log in logs if log["event"] == "zelerdata.refresh_cycle_completed"]
    assert [log["year_history_portions"] for log in completed] == [1, 1, 1, 1]
    assert [log["devoluciones_windows"] for log in completed] == [1, 1, 1, 1]
