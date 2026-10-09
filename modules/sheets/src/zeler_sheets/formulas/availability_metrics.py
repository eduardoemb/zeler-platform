"""Read-time availability metrics over `sheets_item_availability_transitions`.

The log holds only changes, so a series' state at an instant is the newest row
at or before it. Time before a series' first row is unknown: it is reported as
missing history, never filled with the current state. Ranges are local days in
the seller's time zone and never extend past now.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from zeler_sheets.formulas.output_normalization import NA_VALUE

if TYPE_CHECKING:
    from zeler_sheets.formulas.read_models import FormulaReadModelRepository

NO_HISTORY = "Sin histórico"
WITH_STOCK = "Con stock"
WITHOUT_STOCK = "Sin stock"
_HUNDREDTHS = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class AvailabilityWindow:
    """A requested range of local days, as UTC instants; `end` is clipped to now."""

    start: datetime
    range_end: datetime
    now: datetime
    timezone: tzinfo

    @classmethod
    def from_arguments(
        cls, first_day: Any, last_day: Any, *, timezone: tzinfo, now: datetime
    ) -> AvailabilityWindow:
        return cls(
            start=_local_midnight(_local_date(first_day, timezone), timezone),
            range_end=_local_midnight(
                _local_date(last_day, timezone) + timedelta(days=1), timezone
            ),
            now=_utc(now),
            timezone=timezone,
        )

    @property
    def end(self) -> datetime:
        return max(self.start, min(self.range_end, self.now))

    @property
    def local_dates(self) -> tuple[date, date]:
        return (
            self.start.astimezone(self.timezone).date(),
            (self.range_end - timedelta(days=1)).astimezone(self.timezone).date(),
        )

    def week_window_start(self, weeks: Sequence[IsoWeek]) -> datetime:
        if not weeks:
            return self.start
        return min(self.start, _local_midnight(weeks[0].start, self.timezone))


@dataclass(frozen=True, slots=True)
class IsoWeek:
    iso_year: int
    iso_week: int
    start: date

    @property
    def header(self) -> str:
        return f"{self.iso_year} - {self.iso_week}"


@dataclass(slots=True)
class SeriesHistory:
    """What one series' rows say about a window, kept small while streaming.

    `opening` is the state at the window start (newest row at or before it) and
    `changes` are the rows inside the window. Rows at or after the window end
    only update the first observation and the newest SKU.
    """

    first_observed_at: datetime | None = None
    opening: tuple[datetime, bool] | None = None
    changes: list[tuple[datetime, bool]] = field(default_factory=list)
    sku: str | None = None
    _sku_at: datetime | None = None

    def observe(
        self,
        observed_at: datetime,
        available: bool,
        sku: str | None,
        *,
        window_start: datetime,
        window_end: datetime,
    ) -> None:
        observed_at = _utc(observed_at)
        if self.first_observed_at is None or observed_at < self.first_observed_at:
            self.first_observed_at = observed_at
        if self._sku_at is None or observed_at >= self._sku_at:
            self.sku = sku
            self._sku_at = observed_at
        if observed_at <= window_start:
            if self.opening is None or observed_at > self.opening[0]:
                self.opening = (observed_at, available)
        elif observed_at < window_end:
            self.changes.append((observed_at, available))

    def available_seconds(self, start: datetime, end: datetime) -> float | None:
        """Seconds available in [start, end), or None if history starts later."""
        if self.first_observed_at is None or self.first_observed_at > start:
            return None
        state = self.opening[1] if self.opening is not None else False
        cursor = start
        total = 0.0
        for observed_at, available in sorted(self.changes):
            if observed_at >= end:
                break
            if observed_at > start:
                if state:
                    total += (observed_at - cursor).total_seconds()
                cursor = observed_at
            state = available
        if state and end > cursor:
            total += (end - cursor).total_seconds()
        return total

    def state_before(self, instant: datetime) -> bool | None:
        """State in effect just before `instant`, or None if nothing is known."""
        state = self.opening[1] if self.opening is not None and self.opening[0] < instant else None
        for observed_at, available in sorted(self.changes):
            if observed_at >= instant:
                break
            state = available
        return state


@dataclass(frozen=True, slots=True)
class AvailabilitySeries:
    """One output row: a current publication, or one of its variations."""

    item_id: str
    variation_id: str | None
    title: Any = None
    url: Any = None


async def load_availability(
    repository: FormulaReadModelRepository,
    *,
    seller_id: str,
    item_ids: Sequence[str] | None,
    window_start: datetime,
    window_end: datetime,
) -> list[tuple[AvailabilitySeries, SeriesHistory | None]]:
    """Pair each current series with what the log says about the window.

    Requested IDs the seller does not have are kept as rows without history.
    """
    series: list[AvailabilitySeries] = []
    found: set[str] = set()
    async for item in repository.iter_item_availability_identities(
        seller_id=seller_id, item_ids=item_ids
    ):
        item_id = str(item["_id"])
        found.add(item_id)
        raw_variations = item.get("variations")
        variation_ids: list[str | None] = [
            variation_id
            for variation in (raw_variations if isinstance(raw_variations, list) else [])
            if isinstance(variation, Mapping)
            and (variation_id := _identity(variation.get("id"))) is not None
        ]
        series.extend(
            AvailabilitySeries(
                item_id=item_id,
                variation_id=variation_id,
                title=item.get("title"),
                url=item.get("permalink"),
            )
            for variation_id in (variation_ids or [None])
        )
    for item_id in item_ids or ():
        if item_id not in found:
            found.add(item_id)
            series.append(AvailabilitySeries(item_id=item_id, variation_id=None))
    histories: dict[tuple[str, str | None], SeriesHistory] = {}
    async for row in repository.iter_item_availability_transitions(
        seller_id=seller_id, item_ids=item_ids
    ):
        observed_at = row.get("observed_at")
        if not isinstance(observed_at, datetime):
            continue
        key = (str(row.get("item_id") or ""), _identity(row.get("variation_id")))
        histories.setdefault(key, SeriesHistory()).observe(
            observed_at,
            row.get("available") is True,
            row.get("sku"),
            window_start=window_start,
            window_end=window_end,
        )
    return [(entry, histories.get((entry.item_id, entry.variation_id))) for entry in series]


def lacks_history(history: SeriesHistory | None, *, since: datetime) -> bool:
    return history is None or history.first_observed_at is None or history.first_observed_at > since


def tiempo_stock_activo_row(
    series: AvailabilitySeries, history: SeriesHistory | None, *, window: AvailabilityWindow
) -> list[Any]:
    identity = [series.item_id, _cell(history.sku if history else None)]
    described = [*identity, _cell(series.title), _cell(series.url)]
    seconds = history.available_seconds(window.start, window.end) if history else None
    if seconds is None:
        return [*described, coverage_message(history, timezone=window.timezone), NA_VALUE, NA_VALUE]
    total = (window.end - window.start).total_seconds()
    share = percent(seconds, total)
    return [
        *described,
        _number(hours(seconds)),
        _number(hours(total)),
        NA_VALUE if share is None else _number(share),
    ]


def semanas_con_stock_row(
    series: AvailabilitySeries,
    history: SeriesHistory | None,
    *,
    weeks: Sequence[IsoWeek],
    window: AvailabilityWindow,
) -> list[Any]:
    return [
        series.item_id,
        _cell(history.sku if history else None),
        _cell(series.title),
        *[week_cell(history, week, window=window, timezone=window.timezone) for week in weeks],
    ]


def seller_timezone(value: Any) -> tzinfo:
    if not isinstance(value, str) or not value.strip():
        return UTC
    try:
        return ZoneInfo(value.strip())
    except ZoneInfoNotFoundError:
        return UTC


def coverage_message(history: SeriesHistory | None, *, timezone: tzinfo) -> str:
    if history is None or history.first_observed_at is None:
        return NO_HISTORY
    # Same wording and precision as CATALOGOTIEMPO, so a range starting that
    # day can still be uncovered and the hour tells why.
    first_seen = history.first_observed_at.astimezone(timezone)
    return f"{NO_HISTORY} antes de {first_seen:%Y-%m-%d %H:%M}"


def iso_weeks(first_day: date, last_day: date) -> list[IsoWeek]:
    weeks: list[IsoWeek] = []
    current = first_day - timedelta(days=first_day.isoweekday() - 1)
    while current <= last_day:
        iso_year, iso_week, _ = current.isocalendar()
        weeks.append(IsoWeek(iso_year=iso_year, iso_week=iso_week, start=current))
        current += timedelta(days=7)
    return weeks


def week_cell(
    history: SeriesHistory | None,
    week: IsoWeek,
    *,
    window: AvailabilityWindow,
    timezone: tzinfo,
) -> str:
    week_start = _local_midnight(week.start, timezone)
    if week_start >= window.now:
        return NA_VALUE
    week_end = _local_midnight(week.start + timedelta(days=7), timezone)
    state = (
        history.state_before(min(week_end, window.range_end, window.now))
        if history is not None
        else None
    )
    if state is None:
        return coverage_message(history, timezone=timezone)
    return WITH_STOCK if state else WITHOUT_STOCK


def hours(seconds: float) -> Decimal:
    return (Decimal(str(seconds)) / Decimal(3600)).quantize(_HUNDREDTHS, rounding=ROUND_HALF_UP)


def percent(part: float, whole: float) -> Decimal | None:
    if whole <= 0:
        return None
    return (Decimal(str(part)) * 100 / Decimal(str(whole))).quantize(
        _HUNDREDTHS, rounding=ROUND_HALF_UP
    )


def _number(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


def _cell(value: Any) -> Any:
    return value if value is not None and str(value).strip() else NA_VALUE


def _identity(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    normalized = str(value).strip()
    return normalized or None


def _local_date(value: Any, timezone: tzinfo) -> date:
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=timezone)
        return aware.astimezone(timezone).date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        if len(text) == 10:
            return date.fromisoformat(text)
        return _local_date(datetime.fromisoformat(text.replace("Z", "+00:00")), timezone)
    msg = "expected date/datetime or ISO date string"
    raise TypeError(msg)


def _local_midnight(day: date, timezone: tzinfo) -> datetime:
    return datetime.combine(day, time.min, tzinfo=timezone).astimezone(UTC)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
