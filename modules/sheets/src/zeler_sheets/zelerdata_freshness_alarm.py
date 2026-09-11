"""Decide when ZelerData freshness deserves an operator alert (Q21-a).

The agreed trigger is "a model went longer than its interval without
refreshing, or the refresh failed repeatedly". A log line nobody reads was the
old answer; this evaluator turns the durable freshness markers into explicit,
deduplicated alarm decisions that the alert transport can deliver.

Two rules keep it honest:

* Absence is not a regression. A model that was never productive has no marker,
  so there is nothing to alert about; only a window that *was* claimed and then
  closed is a freshness failure.
* A non-productive marker is its own reason. An operator-invalidated model shows
  up as ``marker_not_productive`` instead of being silently skipped.

The evaluator is pure with respect to time (it takes a clock) and reads Mongo
only; it never writes, never acquires from Mercado Libre and never raises for a
single malformed marker.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from zeler_sheets.formulas.refresh import MARKER_VALIDITY

logger = structlog.get_logger(__name__)

READ_MODEL_FRESHNESS_COLLECTION = "sheets_read_model_freshness"
PRODUCTIVE_MARKER_STATES = frozenset({"fresh", "reconciled"})
REASON_MARKER_WINDOW_EXPIRED = "marker_window_expired"
REASON_MARKER_NOT_PRODUCTIVE = "marker_not_productive"
REASON_REFRESH_CYCLE_FAILED = "refresh_cycle_failed"
# Devoluciones is a first-class freshness owner as well (Q2-b/Q7-a).
DEVOLUCIONES_READ_MODEL = "devoluciones"

# A still-broken model must not page once every 15 minutes forever. One alert per
# hour per (seller, model, reason) keeps the signal visible without becoming
# noise the operator learns to ignore.
ALARM_DEDUP_WINDOW = timedelta(minutes=60)

__all__ = [
    "ALARM_DEDUP_WINDOW",
    "DEVOLUCIONES_READ_MODEL",
    "FreshnessAlarm",
    "REASON_MARKER_NOT_PRODUCTIVE",
    "REASON_MARKER_WINDOW_EXPIRED",
    "REASON_REFRESH_CYCLE_FAILED",
    "FreshnessAlarmReporter",
    "emit_freshness_alarms",
    "evaluate_refresh_alarms",
    "refresh_owned_read_models",
]


class FreshnessAlarmReporter:
    """Emit deduplicated freshness alerts with per-instance state.

    State lives on the instance, so the worker holds one reporter for its whole
    life and tests never share dedup state across cases.
    """

    def __init__(self, *, logger: Any = None, dedup_window: timedelta = ALARM_DEDUP_WINDOW) -> None:
        self._logger = logger or structlog.get_logger(__name__)
        self._dedup_window = dedup_window
        self._last_emitted: dict[tuple[str, str, str], datetime] = {}
        self._last_failure: datetime | None = None
        self._failure_attempts = 0

    def emit(
        self,
        alarms: Iterable[FreshnessAlarm],
        *,
        now: Callable[[], datetime] | None = None,
        refresh_failure_attempts: int = 0,
    ) -> tuple[str, ...]:
        """Emit fresh alarms and return the read models reported this call."""
        current = _utc((now or (lambda: datetime.now(UTC)))())
        reported: list[str] = []
        for alarm in alarms:
            key = (alarm.seller_id, alarm.read_model, alarm.reason)
            previous = self._last_emitted.get(key)
            if previous is not None and current - previous < self._dedup_window:
                continue
            self._last_emitted[key] = current
            reported.append(alarm.read_model)
            self._logger.error(
                "zelerdata.freshness_alarm",
                read_model=alarm.read_model,
                reason=alarm.reason,
                overdue_seconds=alarm.overdue_seconds,
            )
        if refresh_failure_attempts > 0:
            previous_failure = self._last_failure
            if (
                previous_failure is None
                or current - previous_failure >= self._dedup_window
                or refresh_failure_attempts != self._failure_attempts
            ):
                self._last_failure = current
                self._failure_attempts = refresh_failure_attempts
                self._logger.error(
                    "zelerdata.freshness_alarm",
                    reason=REASON_REFRESH_CYCLE_FAILED,
                    attempts=refresh_failure_attempts,
                )
        return tuple(reported)


def refresh_owned_read_models(
    *,
    observed_models: Iterable[str] = (),
    devoluciones_enabled: bool = False,
) -> tuple[str, ...]:
    """Everything one refresh cycle promises to keep fresh for a seller.

    Built from the live wiring rather than a hand-written list, so a model that
    is planned or heartbeat-published by the loop is never silently absent from
    the alerting contract.
    """
    from zeler_sheets.formulas.refresh import IMPLEMENTED_REFRESH_MODELS

    models = set(IMPLEMENTED_REFRESH_MODELS)
    models.update(str(model) for model in observed_models)
    if devoluciones_enabled:
        models.add(DEVOLUCIONES_READ_MODEL)
    return tuple(sorted(models))


@dataclass(frozen=True)
class FreshnessAlarm:
    """One seller-scoped read model that failed its freshness expectation."""

    seller_id: str
    read_model: str
    reason: str
    overdue_seconds: int


async def evaluate_refresh_alarms(
    db: Any,
    seller_id: str,
    *,
    expected_models: Iterable[str],
    now: Callable[[], datetime] | None = None,
) -> tuple[FreshnessAlarm, ...]:
    """Return the freshness alarms for one seller, newest failure first.

    ``expected_models`` is the set the refresh loop promised to keep fresh. Any
    other marker in the collection belongs to a different owner and is ignored.
    """
    seller = str(seller_id)
    current = _utc((now or (lambda: datetime.now(UTC)))())
    expected = frozenset(str(model) for model in expected_models)
    if not expected:
        return ()
    rows = (
        await db[READ_MODEL_FRESHNESS_COLLECTION]
        .find(
            {"seller_id": seller},
            {
                "read_model": 1,
                "state": 1,
                "valid_until": 1,
                "fresh_until": 1,
                "reconciled_until": 1,
            },
        )
        .to_list(None)
    )
    alarms: list[FreshnessAlarm] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        read_model = str(row.get("read_model") or "").strip()
        if read_model not in expected or read_model in seen:
            continue
        state = str(row.get("state") or "").strip().casefold()
        if state not in PRODUCTIVE_MARKER_STATES:
            seen.add(read_model)
            alarms.append(
                FreshnessAlarm(
                    seller_id=seller,
                    read_model=read_model,
                    reason=REASON_MARKER_NOT_PRODUCTIVE,
                    overdue_seconds=0,
                )
            )
            continue
        expiry = _claim_expiry(row)
        if expiry is None or expiry > current:
            continue
        seen.add(read_model)
        alarms.append(
            FreshnessAlarm(
                seller_id=seller,
                read_model=read_model,
                reason=REASON_MARKER_WINDOW_EXPIRED,
                overdue_seconds=max(0, int((current - expiry).total_seconds())),
            )
        )
    return tuple(sorted(alarms, key=lambda alarm: (-alarm.overdue_seconds, alarm.read_model)))


def _claim_expiry(row: Mapping[str, Any]) -> datetime | None:
    """When the claim stops certifying data, or ``None`` when it never expires.

    The reader extends a still-open claim by one marker window measured from the
    coverage edge, so a claim without ``valid_until`` expires one window after
    the latest coverage it proved.
    """
    valid_until = _utc_or_none(row.get("valid_until"))
    if valid_until is not None:
        return valid_until
    coverage = _utc_or_none(row.get("fresh_until")) or _utc_or_none(row.get("reconciled_until"))
    if coverage is None:
        return None
    return coverage + MARKER_VALIDITY


def _utc_or_none(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _utc(value)
    if isinstance(value, str):
        try:
            return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


_default_reporter = FreshnessAlarmReporter()


def emit_freshness_alarms(
    alarms: Iterable[FreshnessAlarm],
    *,
    logger: Any = None,
    now: Callable[[], datetime] | None = None,
    refresh_failure_attempts: int = 0,
    reporter: FreshnessAlarmReporter | None = None,
) -> tuple[str, ...]:
    """Emit deduplicated operator alerts through the process-wide reporter.

    Two independent signals feed the agreed trigger (Q21-a): one alarm per read
    model whose freshness window closed, and one alert when the refresh cycle
    itself failed repeatedly. Only bounded, server-owned fields are logged:
    never token, cuenta or payload.
    """
    active = (
        reporter
        if reporter is not None
        else _default_reporter
        if logger is None
        else FreshnessAlarmReporter(logger=logger)
    )
    return active.emit(alarms, now=now, refresh_failure_attempts=refresh_failure_attempts)
