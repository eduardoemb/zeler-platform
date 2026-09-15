"""Resumable 12-month history planner for the ZelerData pilot.

The pilot requires recoverable history over the last twelve months per
resource. This planner produces deterministic, non-overlapping calendar
chunks (at most 90 days each) that tile the full window. It preserves the
cutoff day across year boundaries and assigns acquisition priorities so the
most recent data is available immediately while the oldest recoverable edge
(the one closest to falling out of Mercado Libre's retention) is protected
from the start.

Chunks are pure data: they carry no acquisition state. The caller persists
per-resource/chunk progress and passes completed chunk IDs back to
``plan.resume()`` to get the remaining work in priority order.
"""

from __future__ import annotations

import calendar
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

__all__ = [
    "ChunkPriority",
    "HistoryChunk",
    "HistoryPlanner",
    "ResourceHistoryPlan",
]


class ChunkPriority(Enum):
    """Acquisition ordering for a history chunk.

    RECENT: the newest chunk; served first for immediate pilot utility.
    OLDEST_EDGE: the chunk whose start is closest to the 12-month boundary;
    must be acquired before the source loses it.
    MIDDLE: everything between the two edges.
    """

    OLDEST_EDGE = "oldest_edge"
    RECENT = "recent"
    MIDDLE = "middle"


@dataclass(frozen=True, slots=True)
class HistoryChunk:
    """One resumable, bounded interval of a resource's recoverable history."""

    resource: str
    start: datetime
    end: datetime
    id: str
    priority: ChunkPriority

    @property
    def duration_days(self) -> int:
        return (self.end - self.start).days


@dataclass(frozen=True, slots=True)
class ResourceHistoryPlan:
    """The full set of chunks for one resource over the planning window."""

    resource: str
    cutoff: datetime
    chunks: tuple[HistoryChunk, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.cutoff.tzinfo != UTC:
            raise ValueError("cutoff must be timezone-aware UTC")

    def resume(self, *, completed_ids: Iterable[str]) -> tuple[HistoryChunk, ...]:
        """Return incomplete chunks in acquisition-priority order.

        Order: RECENT first (pilot works now), then OLDEST_EDGE (retention
        risk), then MIDDLE chunks oldest-first. Completed IDs that do not
        belong to this plan are silently ignored.
        """
        completed = set(completed_ids)
        pending = [chunk for chunk in self.chunks if chunk.id not in completed]
        priority_order = {
            ChunkPriority.RECENT: 0,
            ChunkPriority.OLDEST_EDGE: 1,
            ChunkPriority.MIDDLE: 2,
        }
        pending.sort(key=lambda chunk: (priority_order[chunk.priority], chunk.start))
        return tuple(pending)


class HistoryPlanner:
    """Build resumable history plans from a fixed cutoff.

    The cutoff is the user-authorized initial date. ``months`` must be a
    positive integer; twelve months is the pilot target. Chunks tile the
    window by calendar month boundaries anchored on the cutoff day, which
    keeps each one at most 31 days (inside the 90-day recovery limit) and
    produces stable IDs that survive replanning.
    """

    def __init__(self, *, cutoff: datetime, months: int) -> None:
        if cutoff.tzinfo != UTC:
            raise ValueError("cutoff must be timezone-aware UTC")
        if not isinstance(months, int) or isinstance(months, bool) or months < 1:
            raise ValueError("months must be a positive integer")
        self._cutoff = cutoff
        self._months = months

    def plan_for(self, resource: str) -> ResourceHistoryPlan:
        """Produce the deterministic chunk plan for one resource."""
        if not resource or not resource.strip():
            raise ValueError("resource is required")
        window_start = _subtract_calendar_months(self._cutoff, self._months)
        boundaries = _calendar_month_boundaries(window_start, self._cutoff, self._months)
        chunk_specs = list(zip(boundaries, boundaries[1:], strict=False))
        chunks = tuple(
            HistoryChunk(
                resource=resource,
                start=start,
                end=end,
                id=_chunk_id(resource, start, end),
                priority=_priority(index, len(chunk_specs)),
            )
            for index, (start, end) in enumerate(chunk_specs)
        )
        return ResourceHistoryPlan(resource=resource, cutoff=self._cutoff, chunks=chunks)


def _subtract_calendar_months(cutoff: datetime, months: int) -> datetime:
    """Return exactly ``months`` calendar months before ``cutoff``.

    Preserves the day of month; clamps to the last valid day when the
    target month is shorter (e.g. Feb 30 becomes Feb 28).
    """
    target_month = cutoff.month - months
    target_year = cutoff.year
    while target_month <= 0:
        target_month += 12
        target_year -= 1
    max_day = calendar.monthrange(target_year, target_month)[1]
    day = min(cutoff.day, max_day)
    return datetime(
        target_year, target_month, day, cutoff.hour, cutoff.minute, cutoff.second, tzinfo=UTC
    )  # noqa: E501


def _calendar_month_boundaries(
    window_start: datetime, cutoff: datetime, months: int
) -> tuple[datetime, ...]:
    """Return the ``months + 1`` calendar boundaries from window_start to cutoff.

    Each boundary is exactly one calendar month after the previous one,
    anchored on the cutoff day. The final boundary is always the cutoff.
    """
    boundaries = [window_start]
    for i in range(months):
        candidate = _add_calendar_months(window_start, i + 1)
        if candidate >= cutoff:
            break
        boundaries.append(candidate)
    boundaries.append(cutoff)
    return tuple(boundaries)


def _add_calendar_months(anchor: datetime, count: int) -> datetime:
    """Return ``count`` calendar months after ``anchor``, clamping the day."""
    target_month = anchor.month + count
    target_year = anchor.year
    while target_month > 12:
        target_month -= 12
        target_year += 1
    max_day = calendar.monthrange(target_year, target_month)[1]
    day = min(anchor.day, max_day)
    return datetime(
        target_year, target_month, day, anchor.hour, anchor.minute, anchor.second, tzinfo=UTC
    )  # noqa: E501


def _priority(index: int, total: int) -> ChunkPriority:
    """Classify a chunk by its position in the plan.

    The first chunk (index 0) starts at the oldest recoverable edge. The
    last chunk (index ``total - 1``) ends at the cutoff and is the most
    recent. With only one chunk it is both oldest and recent; RECENT wins
    so the pilot gets data immediately.
    """
    if total == 1 or index == total - 1:
        return ChunkPriority.RECENT
    if index == 0:
        return ChunkPriority.OLDEST_EDGE
    return ChunkPriority.MIDDLE


def _chunk_id(resource: str, start: datetime, end: datetime) -> str:
    """Stable, collision-free ID for a resource's time interval."""
    resource_part = resource.strip().lower().replace(" ", "-")
    return f"{resource_part}:{start.strftime('%Y%m%d')}:{end.strftime('%Y%m%d')}"
