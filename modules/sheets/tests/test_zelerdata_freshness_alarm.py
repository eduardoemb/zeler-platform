from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from zeler_sheets.zelerdata_freshness_alarm import (
    FreshnessAlarm,
    FreshnessAlarmReporter,
    evaluate_refresh_alarms,
)

NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)


class _Cursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def to_list(self, length: int | None = None) -> list[dict[str, Any]]:
        return self._rows if length is None else self._rows[:length]


class _Collection:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def find(self, query: dict[str, Any], projection: Any = None) -> _Cursor:
        rows = [row for row in self.rows if row.get("seller_id") == query.get("seller_id")]
        return _Cursor(rows)


class _Db:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def __getitem__(self, name: str) -> _Collection:
        assert name == "sheets_read_model_freshness"
        return _Collection(self.rows)


def _marker(read_model: str, *, valid_until: datetime | None, state: str = "reconciled") -> dict:
    return {
        "_id": f"82453304:{read_model}",
        "seller_id": "82453304",
        "read_model": read_model,
        "state": state,
        "fresh_until": NOW - timedelta(minutes=40),
        "valid_until": valid_until,
        "schema_version": 1,
    }


@pytest.mark.asyncio
async def test_no_alarm_when_every_expected_marker_is_still_open() -> None:
    """A healthy cycle must not page anyone: every window is still open."""
    db = _Db(
        [
            _marker("orders", valid_until=NOW + timedelta(minutes=20)),
            _marker("questions", valid_until=NOW + timedelta(minutes=20)),
        ]
    )

    alarms = await evaluate_refresh_alarms(
        db,
        "82453304",
        expected_models=("orders", "questions"),
        now=lambda: NOW,
    )

    assert alarms == ()


@pytest.mark.asyncio
async def test_alarm_when_an_expected_marker_window_expired() -> None:
    """Q21-a: a model that stopped refreshing longer than its interval alarms."""
    db = _Db(
        [
            _marker("orders", valid_until=NOW - timedelta(minutes=5)),
            _marker("questions", valid_until=NOW + timedelta(minutes=20)),
        ]
    )

    alarms = await evaluate_refresh_alarms(
        db,
        "82453304",
        expected_models=("orders", "questions"),
        now=lambda: NOW,
    )

    assert alarms == (
        FreshnessAlarm(
            seller_id="82453304",
            read_model="orders",
            reason="marker_window_expired",
            overdue_seconds=300,
        ),
    )


@pytest.mark.asyncio
async def test_alarm_uses_the_validity_window_when_valid_until_is_absent() -> None:
    """An open claim without ``valid_until`` expires one marker-window later."""
    from zeler_sheets.formulas.refresh import MARKER_VALIDITY

    fresh_until = NOW - MARKER_VALIDITY - timedelta(minutes=10)
    marker = _marker("orders", valid_until=None)
    marker["fresh_until"] = fresh_until
    db = _Db([marker])

    alarms = await evaluate_refresh_alarms(
        db,
        "82453304",
        expected_models=("orders",),
        now=lambda: NOW,
    )

    assert alarms[0].reason == "marker_window_expired"
    assert alarms[0].overdue_seconds == 600


@pytest.mark.asyncio
async def test_a_model_that_was_never_refreshed_is_not_an_alarm() -> None:
    """Absence is not a regression: only a previously productive window alarms."""
    db = _Db([])

    alarms = await evaluate_refresh_alarms(
        db,
        "82453304",
        expected_models=("orders", "catalog_time_metrics"),
        now=lambda: NOW,
    )

    assert alarms == ()


@pytest.mark.asyncio
async def test_a_marker_outside_the_expected_models_is_ignored() -> None:
    """The alarm only speaks for models the refresh loop owns."""
    db = _Db([_marker("claims", valid_until=NOW - timedelta(hours=3))])

    alarms = await evaluate_refresh_alarms(
        db,
        "82453304",
        expected_models=("orders",),
        now=lambda: NOW,
    )

    assert alarms == ()


@pytest.mark.asyncio
async def test_a_non_productive_marker_state_is_an_alarm_with_its_own_reason() -> None:
    """An operator-invalidated marker must be visible, not silently skipped."""
    db = _Db([_marker("devoluciones", valid_until=None, state="stale")])

    alarms = await evaluate_refresh_alarms(
        db,
        "82453304",
        expected_models=("devoluciones",),
        now=lambda: NOW,
    )

    assert alarms == (
        FreshnessAlarm(
            seller_id="82453304",
            read_model="devoluciones",
            reason="marker_not_productive",
            overdue_seconds=0,
        ),
    )


class _LogSpy:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def error(self, event: str, **fields: Any) -> None:
        self.events.append((event, fields))

    def warning(self, event: str, **fields: Any) -> None:
        self.events.append((event, fields))


def test_emit_reports_each_alarm_once_per_dedup_window() -> None:
    """An expired marker alarms on transition, not on every 15-minute cycle."""
    logger = _LogSpy()
    reporter = FreshnessAlarmReporter(logger=logger)
    clock = [NOW]
    alarms = (
        FreshnessAlarm(
            seller_id="82453304",
            read_model="orders",
            reason="marker_window_expired",
            overdue_seconds=300,
        ),
    )

    first = reporter.emit(alarms, now=lambda: clock[0])
    clock[0] = NOW + timedelta(minutes=16)
    second = reporter.emit(alarms, now=lambda: clock[0])
    clock[0] = NOW + timedelta(minutes=61)
    third = reporter.emit(alarms, now=lambda: clock[0])

    assert first == ("orders",)
    assert second == ()
    assert third == ("orders",)
    assert [event for event, _ in logger.events] == ["zelerdata.freshness_alarm"] * 2
    event, fields = logger.events[0]
    assert fields["reason"] == "marker_window_expired"
    assert fields["read_model"] == "orders"
    assert fields["overdue_seconds"] == 300
    assert "cuenta" not in fields


def test_emit_reports_a_repeated_refresh_failure_as_its_own_reason() -> None:
    """Q21-a also covers the loop failing repeatedly, not just a slow model."""
    logger = _LogSpy()
    reporter = FreshnessAlarmReporter(logger=logger)

    reporter.emit((), now=lambda: NOW, refresh_failure_attempts=3)

    assert logger.events == [
        (
            "zelerdata.freshness_alarm",
            {"reason": "refresh_cycle_failed", "attempts": 3},
        )
    ]


def test_emit_dedupes_an_unchanged_refresh_failure_but_reports_a_new_count() -> None:
    """A failure that keeps deepening is new information; a flat one is not."""
    logger = _LogSpy()
    reporter = FreshnessAlarmReporter(logger=logger)
    clock = [NOW]

    reporter.emit((), now=lambda: clock[0], refresh_failure_attempts=3)
    clock[0] = NOW + timedelta(minutes=1)
    reporter.emit((), now=lambda: clock[0], refresh_failure_attempts=3)
    clock[0] = NOW + timedelta(minutes=2)
    reporter.emit((), now=lambda: clock[0], refresh_failure_attempts=4)

    assert [fields["attempts"] for _, fields in logger.events] == [3, 4]


def test_default_emit_helper_uses_a_process_wide_reporter() -> None:
    """The process-wide reporter keeps dedup state across cycles."""
    from zeler_sheets import zelerdata_freshness_alarm as module
    from zeler_sheets.zelerdata_freshness_alarm import emit_freshness_alarms

    logger = _LogSpy()
    reporter = FreshnessAlarmReporter(logger=logger)
    alarms = (
        FreshnessAlarm(
            seller_id="82453304",
            read_model="questions",
            reason="marker_window_expired",
            overdue_seconds=60,
        ),
    )

    module._default_reporter = reporter
    try:
        assert emit_freshness_alarms(alarms, now=lambda: NOW) == ("questions",)
        assert emit_freshness_alarms(alarms, now=lambda: NOW) == ()
    finally:
        module._default_reporter = reporter
