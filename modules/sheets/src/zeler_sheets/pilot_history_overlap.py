"""Controlled overlap for reconciling recent changes to old data.

The 12-month history chunks are non-overlapping. A modification to an old
operation lands inside a chunk that has already completed, so it would
never be re-fetched. This module produces a bounded overlap request that
re-reads the most recent tail of a completed chunk through the existing
recovery queue, using a distinct request key so it never collides with or
resets the base chunk.

The overlap window is 24 hours by default, clamped to the chunk start for
short chunks. It is caller's responsibility to only invoke it for chunks
that have completed (the planner's ``resume`` already separates pending
from completed work).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from zeler_sheets.formulas.recovery import RecoveryRequest
from zeler_sheets.pilot_history import HistoryChunk

__all__ = ["overlap_request", "overlap_window"]

DEFAULT_OVERLAP = timedelta(hours=24)


def overlap_window(
    chunk: HistoryChunk,
    *,
    now: datetime,
    overlap: timedelta = DEFAULT_OVERLAP,
) -> tuple[datetime, datetime]:
    """Return the bounded overlap interval for a completed chunk.

    The end is the chunk's own end; the start is the end minus the overlap
    duration, clamped to the chunk start so it never reaches before the
    chunk's basis.
    """
    end = chunk.end.replace(tzinfo=UTC) if chunk.end.tzinfo != UTC else chunk.end
    candidate_start = end - overlap
    start = max(chunk.start, candidate_start)
    return start, end


def overlap_request(
    *,
    chunk: HistoryChunk,
    seller_id: str,
    now: datetime,
    overlap: timedelta = DEFAULT_OVERLAP,
) -> RecoveryRequest | None:
    """Build a RecoveryRequest for the overlap tail, or None if unmappable."""
    if not seller_id or not seller_id.strip():
        return None
    start, end = overlap_window(chunk, now=now, overlap=overlap)
    if start >= end:
        return None
    if chunk.resource not in {"orders", "questions"}:
        # Only resources that accept range requests through the recovery
        # queue can use this overlap; others need explicit IDs.
        return None
    return RecoveryRequest(
        seller_id=seller_id.strip(),
        read_model=chunk.resource,
        date_from=start,
        date_to=end,
    )
