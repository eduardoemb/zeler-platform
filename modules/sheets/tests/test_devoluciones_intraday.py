"""DEVOLUCIONES covers the day in progress up to an hourly intraday cut.

Until 2026-10-12 the ordinary tail certified only closed UTC days, so a range
that ends today answered ``DATA_UNAVAILABLE`` all day. The refresh loop now
acquires ``[today 00:00, cut)`` once per hourly cut with the tail's executor,
in its own pass that never takes a window from the tail or an initial window.
Real-Mongo behavior is covered in ``tests/integration/test_devoluciones_intraday.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest
from structlog.testing import capture_logs

from zeler_sheets import devoluciones_runner as runner
from zeler_sheets.devoluciones_runner import (
    INTRADAY_AUTHORIZATION,
    ORDINARY_TAIL_AUTHORIZATION,
    admit_ordinary_devoluciones_tail,
    advance_due_devoluciones_run,
    advance_intraday_devoluciones,
    intraday_binding,
    intraday_bounds,
)
from zeler_sheets.formulas.read_models import devoluciones_intraday_prefix_readable
from zeler_sheets.formulas.refresh import ZelerDataRefreshSupervisor

SELLER = "82453304"
TODAY = datetime(2026, 10, 12, tzinfo=UTC)
NOW = TODAY + timedelta(hours=14, minutes=35)


def _at(hours: int, minutes: int = 0, *, day: datetime = TODAY) -> datetime:
    return day + timedelta(hours=hours, minutes=minutes)


@pytest.mark.parametrize(
    ("now", "bounds"),
    [
        # Before 00:30 the settled instant is still yesterday: its 23:00 cut.
        (_at(0, 10), (TODAY - timedelta(days=1), _at(23, day=TODAY - timedelta(days=1)))),
        # The first cut of the day needs one settled hour.
        (_at(0, 45), None),
        (_at(1, 29), None),
        (_at(1, 30), (TODAY, _at(1))),
        (_at(14, 29), (TODAY, _at(13))),
        (_at(14, 31), (TODAY, _at(14))),
        (_at(23, 59), (TODAY, _at(23))),
    ],
)
def test_intraday_bounds_follow_the_settled_hourly_cut(
    now: datetime, bounds: tuple[datetime, datetime] | None
) -> None:
    assert intraday_bounds(now=now) == bounds


def test_each_cut_is_its_own_run_identity() -> None:
    first = intraday_binding(SELLER, TODAY, _at(14))
    assert first.run_id == intraday_binding(SELLER, TODAY, _at(14)).run_id
    assert first.run_id != intraday_binding(SELLER, TODAY, _at(15)).run_id
    assert first.authorization_id == INTRADAY_AUTHORIZATION


@pytest.mark.parametrize(
    ("covered_until", "date_to", "now", "readable"),
    [
        # A range ending today (tomorrow 00:00) with a recent cut.
        (_at(14), TODAY + timedelta(days=1), _at(14, 36), True),
        # A range ending now.
        (_at(14), _at(14, 36), _at(14, 36), True),
        # Up to three hours: one missed hourly pass and the cycle's delays.
        (_at(14), TODAY + timedelta(days=1), _at(17), True),
        (_at(14), TODAY + timedelta(days=1), _at(17, 1), False),
        # A range ending after tomorrow 00:00 is never served partially.
        (_at(14), TODAY + timedelta(days=2), _at(14, 36), False),
        # Shortly after midnight the previous day's last cut serves it.
        (_at(23, day=TODAY - timedelta(days=1)), TODAY, _at(0, 40), True),
    ],
)
def test_reader_serves_a_recent_cut_only_up_to_the_end_of_today(
    covered_until: datetime, date_to: datetime, now: datetime, readable: bool
) -> None:
    assert (
        devoluciones_intraday_prefix_readable(covered_until=covered_until, date_to=date_to, now=now)
        is readable
    )


def _matches(document: dict[str, Any], query: dict[str, Any]) -> bool:
    for field, expected in query.items():
        if field == "$or":
            if not any(_matches(document, clause) for clause in expected):
                return False
            continue
        actual = document.get(field)
        if not isinstance(expected, dict):
            if actual != expected:
                return False
            continue
        if "$in" in expected and actual not in expected["$in"]:
            return False
        if "$nin" in expected and actual in expected["$nin"]:
            return False
        if "$ne" in expected and actual == expected["$ne"]:
            return False
        if "$gt" in expected and not actual > expected["$gt"]:
            return False
        if "$lte" in expected and not actual <= expected["$lte"]:
            return False
        if "$exists" in expected and (field in document) is not expected["$exists"]:
            return False
        if "$not" in expected and str(actual).startswith(expected["$not"]["$regex"][1:]):
            return False
    return True


class _Collection:
    def __init__(self, documents: list[dict[str, Any]] | None = None) -> None:
        self.documents = documents or []

    async def find_one(
        self, query: dict[str, Any], *args: Any, sort: list[tuple[str, int]] | None = None
    ) -> dict[str, Any] | None:
        matches = [document for document in self.documents if _matches(document, query)]
        for field, direction in reversed(sort or []):
            matches.sort(key=lambda document: document[field], reverse=direction < 0)
        return matches[0] if matches else None


class _Db:
    def __init__(self, **collections: list[dict[str, Any]]) -> None:
        self.collections = {name: _Collection(rows) for name, rows in collections.items()}

    def __getitem__(self, name: str) -> _Collection:
        return self.collections.setdefault(name, _Collection())


def _control(**overrides: Any) -> dict[str, Any]:
    control = {
        "seller_id": SELLER,
        "scope": "devoluciones",
        "coverage_mode": "active",
        "fence": 7,
        "coverage_ack_fence": 7,
        "coverage_epoch": 2,
    }
    control.update(overrides)
    return control


def _certificate(date_from: datetime, date_to: datetime, run_id: str) -> dict[str, Any]:
    return {
        "_id": "c-" + run_id,
        "seller_id": SELLER,
        "kind": "quota_run",
        "source_identity": run_id,
        "coverage_epoch": 2,
        "date_from": date_from,
        "date_to": date_to,
    }


def _run(run_id: str, authorization_id: str, **overrides: Any) -> dict[str, Any]:
    run = {
        "_id": run_id,
        "seller_id": SELLER,
        "scope": "devoluciones",
        "authorization_id": authorization_id,
        "state": "completed",
        "expires_at": NOW + timedelta(minutes=10),
        "created_at": NOW - timedelta(minutes=5),
    }
    run.update(overrides)
    return run


def _db(*, certificates: list[dict[str, Any]], runs: list[dict[str, Any]], **control: Any) -> _Db:
    return _Db(
        sheets_devoluciones_operations=[_control(**control)],
        sheets_devoluciones_certificates=certificates,
        sheets_devoluciones_runs=runs,
    )


class _Admission:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.created: list[Any] = []
        admission = self

        async def acquire(**_: Any) -> Any:
            return MagicMock(name="operation")

        async def finish(**_: Any) -> None:
            return None

        class Repository:
            def __init__(self, db: Any) -> None:
                self.db = db

            async def create(self, binding: Any, **_: Any) -> bool:
                admission.created.append(binding)
                return True

        monkeypatch.setattr(runner, "_acquire_onboarding_operation", acquire)
        monkeypatch.setattr(runner, "_finish_onboarding_operation", finish)
        monkeypatch.setattr(runner, "_OnboardingRepository", Repository)


def _yesterday_closed() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return (
        [_certificate(TODAY - timedelta(days=1), TODAY, "tail")],
        [_run("tail", ORDINARY_TAIL_AUTHORIZATION)],
    )


@pytest.mark.asyncio
async def test_the_tail_continues_from_closed_days_not_from_an_intraday_cut(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admission = _Admission(monkeypatch)
    tomorrow = TODAY + timedelta(days=1)
    certificates, runs = _yesterday_closed()
    db = _db(
        certificates=[*certificates, _certificate(TODAY, _at(23), "cut")],
        runs=[*runs, _run("cut", INTRADAY_AUTHORIZATION)],
    )

    run_id = await admit_ordinary_devoluciones_tail(
        db, SELLER, now=lambda: _at(1, 10, day=tomorrow)
    )

    assert run_id is not None
    (binding,) = admission.created
    assert (binding.start, binding.end) == (TODAY, tomorrow)


@pytest.mark.asyncio
async def test_intraday_pass_admits_and_advances_the_current_cut_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admission = _Admission(monkeypatch)
    advanced: list[str] = []

    async def advance(db: Any, run_id: str, *, now: Any = None) -> dict[str, int]:
        advanced.append(run_id)
        return {"advanced": 1, "finalized": 1}

    certificates, runs = _yesterday_closed()
    db = _db(certificates=certificates, runs=runs)
    with capture_logs() as logs:
        assert await advance_intraday_devoluciones(db, SELLER, now=lambda: NOW, advance=advance)

    expected = intraday_binding(SELLER, TODAY, _at(14))
    assert admission.created == [expected]
    assert advanced == [expected.run_id]
    admitted = [log for log in logs if log["event"] == "zelerdata.devoluciones_intraday_admitted"]
    assert admitted == [
        {
            "event": "zelerdata.devoluciones_intraday_admitted",
            "log_level": "info",
            "seller_id": SELLER,
            "run_id": expected.run_id,
            "start": TODAY.isoformat(),
            "end": _at(14).isoformat(),
        }
    ]

    # The cut is done whatever its outcome; the next one is an hour away.
    for state in ("completed", "failed", "expired"):
        db["sheets_devoluciones_runs"].documents = [
            *runs,
            _run(expected.run_id, INTRADAY_AUTHORIZATION, state=state),
        ]
        assert not await advance_intraday_devoluciones(db, SELLER, now=lambda: NOW, advance=advance)
    assert advanced == [expected.run_id]

    # A run left admitted by a restart is resumed, not admitted again.
    db["sheets_devoluciones_runs"].documents = [
        *runs,
        _run(expected.run_id, INTRADAY_AUTHORIZATION, state="authorized"),
    ]
    assert await advance_intraday_devoluciones(db, SELLER, now=lambda: NOW, advance=advance)
    assert advanced == [expected.run_id, expected.run_id]
    assert len(admission.created) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("now", "certificates", "control"),
    [
        # Before the first settled cut of the day.
        (_at(1, 10), None, {}),
        # Closed days stop before yesterday: the tail is still catching up.
        (NOW, [_certificate(TODAY - timedelta(days=12), TODAY - timedelta(days=2), "tail")], {}),
        # No certificate at all, or not in certificate mode.
        (NOW, [], {}),
        (NOW, None, {"coverage_mode": "legacy"}),
        (NOW, None, {"coverage_ack_fence": 6}),
    ],
)
async def test_intraday_pass_serves_only_certificate_sellers_whose_tail_is_current(
    monkeypatch: pytest.MonkeyPatch,
    now: datetime,
    certificates: list[dict[str, Any]] | None,
    control: dict[str, Any],
) -> None:
    admission = _Admission(monkeypatch)

    async def advance(db: Any, run_id: str, *, now: Any = None) -> dict[str, int]:
        raise AssertionError("no source work")

    closed, runs = _yesterday_closed()
    db = _db(certificates=closed if certificates is None else certificates, runs=runs, **control)

    assert not await advance_intraday_devoluciones(db, SELLER, now=lambda: now, advance=advance)
    assert admission.created == []


@pytest.mark.asyncio
async def test_the_regular_pass_never_picks_up_an_intraday_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_renewal(*_: Any, **__: Any) -> bool:
        return False

    monkeypatch.setattr(runner, "renew_devoluciones_marker_if_proven", no_renewal)
    advanced: list[str] = []

    async def advance(*, db: Any, run_id: str, now: Any = None) -> dict[str, int]:
        advanced.append(run_id)
        return {"advanced": 1, "finalized": 0}

    async def no_tail(*_: Any, **__: Any) -> None:
        return None

    pending = _run("cut", INTRADAY_AUTHORIZATION, state="authorized")
    db = _Db(sheets_devoluciones_runs=[pending])
    for history_work_enabled in (True, False):
        assert not await advance_due_devoluciones_run(
            db,
            SELLER,
            now=lambda: NOW,
            advance=advance,
            history_work_enabled=history_work_enabled,
            admit_tail=no_tail,
        )
    assert advanced == []


class _Explorer:
    def __init__(self, *sellers: str) -> None:
        self.sellers = sellers

    async def discover_sellers(self) -> tuple[str, ...]:
        return self.sellers


class _Planner:
    async def plan(self, *, seller_id: str, mode: str = "fast") -> bool:
        return False


def _supervisor(
    sellers: tuple[str, ...], regular: list[str], intraday: list[str], *, due: set[str]
) -> ZelerDataRefreshSupervisor:
    async def advancer(seller_id: str) -> bool:
        regular.append(seller_id)
        return seller_id in due

    async def intraday_advancer(seller_id: str) -> bool:
        intraday.append(seller_id)
        if seller_id == "bad":
            raise RuntimeError("lease busy")
        return True

    return ZelerDataRefreshSupervisor(
        explorer=_Explorer(*sellers),
        planner=_Planner(),
        devoluciones_advancer=advancer,
        devoluciones_intraday_advancer=intraday_advancer,
        interval_seconds=900,
        now=lambda: NOW,
    )


@pytest.mark.asyncio
async def test_intraday_gets_the_cycle_window_only_when_no_tail_or_initial_window_is_due() -> None:
    regular: list[str] = []
    intraday: list[str] = []
    due = {"2"}
    supervisor = _supervisor(("1", "2", "3"), regular, intraday, due=due)

    with capture_logs() as logs:
        # Seller 2 catches up: the regular pass takes the window, intraday waits.
        await supervisor.run_cycle()
        assert (regular, intraday) == (["1", "2"], [])
        due.clear()
        # Nothing regular is due: the sellers take intraday turns, one per cycle.
        for _ in range(4):
            await supervisor.run_cycle()

    assert intraday == ["1", "2", "3", "1"]
    completed = [log for log in logs if log["event"] == "zelerdata.refresh_cycle_completed"]
    assert [log["devoluciones_windows"] for log in completed] == [1, 1, 1, 1, 1]


@pytest.mark.asyncio
async def test_a_failing_intraday_seller_uses_its_turn_and_blocks_no_one() -> None:
    regular: list[str] = []
    intraday: list[str] = []
    supervisor = _supervisor(("bad", "2"), regular, intraday, due=set())

    with capture_logs() as logs:
        for _ in range(3):
            await supervisor.run_cycle()

    assert intraday == ["bad", "2", "bad"]
    failures = [log for log in logs if log["event"] == "zelerdata.devoluciones_intraday_failed"]
    assert [(log["seller_id"], log["error_type"]) for log in failures] == [
        ("bad", "RuntimeError"),
        ("bad", "RuntimeError"),
    ]


async def _refresh_wiring(monkeypatch: pytest.MonkeyPatch, **env: str) -> tuple[Any, list[Any]]:
    from zeler_sheets import consumer
    from zeler_sheets.formulas.recovery import FormulaRecoveryQueue

    captured: list[Any] = []

    async def intraday(db: Any, seller_id: str, **kwargs: Any) -> bool:
        captured.append(seller_id)
        return False

    async def no_indexes(self: Any) -> None:
        return None

    monkeypatch.setattr(consumer, "advance_intraday_devoluciones", intraday)
    monkeypatch.setattr(FormulaRecoveryQueue, "ensure_indexes", no_indexes)
    for name in (
        "ZELERDATA_PRECALCULATED_FORMULAS_ENABLED",
        "ZELERDATA_DLQ_ARCHIVE_ENABLED",
        "ZELERDATA_FRESHNESS_ALERTS_ENABLED",
        "ZELERDATA_HISTORY_ON_LINK_ENABLED",
    ):
        monkeypatch.setenv(name, "false")
    monkeypatch.delenv("ZELERDATA_DEVOLUCIONES_INTRADAY_ENABLED", raising=False)
    monkeypatch.setenv("ZELERDATA_DEVOLUCIONES_ADVANCE_ENABLED", "true")
    monkeypatch.setenv("ZELERDATA_REFRESH_ENABLED", "true")
    monkeypatch.setenv("ZELERDATA_FORMULA_RECOVERY_ENABLED", "true")
    monkeypatch.setenv("ZELERDATA_REFRESH_SELLERS", SELLER)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return await consumer.build_zelerdata_refresh_supervisor(db=MagicMock()), captured


@pytest.mark.asyncio
async def test_intraday_is_on_by_default_with_an_emergency_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    supervisor, captured = await _refresh_wiring(monkeypatch)
    assert supervisor._devoluciones_intraday_advancer is not None
    await supervisor._devoluciones_intraday_advancer(SELLER)
    assert captured == [SELLER]

    for env in (
        {"ZELERDATA_DEVOLUCIONES_INTRADAY_ENABLED": "false"},
        # Source work is off: nothing is acquired at all.
        {"ZELERDATA_DEVOLUCIONES_ADVANCE_ENABLED": "false"},
        # With history on link on the pilot owns its runs, as for the tail.
        {"ZELERDATA_HISTORY_ON_LINK_ENABLED": "true"},
    ):
        supervisor, _ = await _refresh_wiring(monkeypatch, **env)
        assert supervisor._devoluciones_intraday_advancer is None
