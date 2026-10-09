from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from zeler_sheets.formulas.availability_metrics import (
    AvailabilityWindow,
    SeriesHistory,
    coverage_message,
    iso_weeks,
    week_cell,
)

MEXICO = ZoneInfo("America/Mexico_City")  # UTC-6, no DST since 2022


def _history(
    rows: list[tuple[datetime, bool]], *, start: datetime, end: datetime, sku: str = "SKU"
) -> SeriesHistory:
    history = SeriesHistory()
    for observed_at, available in rows:
        history.observe(observed_at, available, sku, window_start=start, window_end=end)
    return history


def test_window_uses_seller_days_and_stops_at_now() -> None:
    now = datetime(2026, 10, 9, 21, 15, tzinfo=UTC)  # 15:15 in Mexico City

    window = AvailabilityWindow.from_arguments("2026-10-01", "2026-10-09", timezone=MEXICO, now=now)
    past = AvailabilityWindow.from_arguments(
        date(2026, 9, 1), "2026-09-30T23:00:00-06:00", timezone=MEXICO, now=now
    )

    assert window.start == datetime(2026, 10, 1, 6, 0, tzinfo=UTC)
    assert window.range_end == datetime(2026, 10, 10, 6, 0, tzinfo=UTC)
    assert window.end == now
    assert past.start == datetime(2026, 9, 1, 6, 0, tzinfo=UTC)
    assert past.end == datetime(2026, 10, 1, 6, 0, tzinfo=UTC)


def test_available_time_integrates_changes_inside_the_range() -> None:
    start = datetime(2026, 10, 1, tzinfo=UTC)
    end = start + timedelta(hours=24)
    history = _history(
        [
            (start - timedelta(days=3), False),
            (start - timedelta(days=1), True),  # opening state: available
            (start + timedelta(hours=10), False),
            (start + timedelta(hours=20), True),
            (end + timedelta(hours=1), False),  # after the range: ignored
        ],
        start=start,
        end=end,
    )

    assert history.available_seconds(start, end) == 14 * 3600
    assert history.first_observed_at == start - timedelta(days=3)
    assert history.available_seconds(start, start) == 0


def test_range_before_the_first_observation_is_not_covered() -> None:
    start = datetime(2026, 10, 1, tzinfo=UTC)
    end = start + timedelta(days=10)
    first = datetime(2026, 10, 5, 3, 0, tzinfo=UTC)  # 2026-10-04 21:00 in Mexico City
    history = _history([(first, True)], start=start, end=end)

    assert history.available_seconds(start, end) is None
    assert coverage_message(history, timezone=MEXICO) == "Sin histórico antes de 2026-10-04 21:00"
    assert coverage_message(SeriesHistory(), timezone=MEXICO) == "Sin histórico"


def test_newest_sku_wins_whatever_the_row_order() -> None:
    start = datetime(2026, 10, 1, tzinfo=UTC)
    history = SeriesHistory()
    history.observe(start + timedelta(hours=2), True, "NEW", window_start=start, window_end=start)
    history.observe(start + timedelta(hours=1), False, "OLD", window_start=start, window_end=start)

    assert history.sku == "NEW"
    assert history.first_observed_at == start + timedelta(hours=1)


def test_weeks_follow_iso_numbering_in_the_seller_zone() -> None:
    weeks = iso_weeks(date(2025, 12, 27), date(2026, 1, 6))

    assert [(week.iso_year, week.iso_week) for week in weeks] == [
        (2025, 52),
        (2026, 1),
        (2026, 2),
    ]
    assert [week.header for week in weeks] == ["2025 - 52", "2026 - 1", "2026 - 2"]
    assert weeks[0].start == date(2025, 12, 22)


def test_week_cells_use_the_state_at_each_week_end() -> None:
    now = datetime(2026, 10, 9, 21, 15, tzinfo=UTC)
    window = AvailabilityWindow.from_arguments("2026-09-21", "2026-10-18", timezone=MEXICO, now=now)
    weeks = iso_weeks(*window.local_dates)
    first_week_start = window.week_window_start(weeks)
    history = _history(
        [
            (datetime(2026, 9, 30, 18, 0, tzinfo=UTC), True),  # week 40, Wednesday
            (datetime(2026, 10, 2, 18, 0, tzinfo=UTC), False),  # week 40, Friday
            (datetime(2026, 10, 6, 18, 0, tzinfo=UTC), True),  # week 41 (current)
        ],
        start=first_week_start,
        end=window.end,
    )

    cells = [week_cell(history, week, window=window, timezone=MEXICO) for week in weeks]

    assert [week.header for week in weeks] == [
        "2026 - 39",
        "2026 - 40",
        "2026 - 41",
        "2026 - 42",
    ]
    assert cells == [
        "Sin histórico antes de 2026-09-30 12:00",
        "Sin stock",  # last change of week 40
        "Con stock",  # state now, the week has not ended
        "NA",  # week 42 has not started
    ]
