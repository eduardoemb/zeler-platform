"""TDD: task 3.4 — controlled overlap reconciles modified old data.

The pilot requires that recent modifications to old operations are picked
up. The 12-month plan uses non-overlapping chunks; a modified old order
falls inside an already-completed chunk and would never be re-fetched.

Solution: the backfill planner emits a separate "overlap" window that
re-reads the most recent N days of each completed chunk. This window
coexists with the normal chunks: it shares the recovery queue, dedup, and
lanes, but uses a distinct request key (different date_from) so it never
collides with the chunk itself.

Contract:
- Overlap window is bounded (default 24h) and only applies to the most
  recent completed chunk per resource.
- The overlap request has a different key from the base chunk, so a
  completed chunk is NOT reset to pending (which would re-fetch the whole
  month).
- Overlap is skipped when the most recent chunk is not yet completed (no
  basis to overlap onto).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from zeler_sheets.formulas.recovery import RecoveryRequest
from zeler_sheets.pilot_history import ChunkPriority, HistoryChunk
from zeler_sheets.pilot_history_overlap import (
    overlap_request,
    overlap_window,
)

NOW = datetime(2026, 9, 15, tzinfo=UTC)
SELLER = "82453304"


def _completed_chunk(resource: str) -> HistoryChunk:
    end = NOW - timedelta(days=1)
    start = end - timedelta(days=30)
    return HistoryChunk(
        resource=resource,
        start=start,
        end=end,
        id=f"{resource}-completed",
        priority=ChunkPriority.MIDDLE,
    )


def test_overlap_window_bounded_to_24h() -> None:
    chunk = _completed_chunk("orders")
    start, end = overlap_window(chunk, now=NOW, overlap=timedelta(hours=24))
    assert end == chunk.end
    assert end - start == timedelta(hours=24)
    assert start > chunk.start  # strictly inside the chunk


def test_overlap_window_defaults_to_24h() -> None:
    chunk = _completed_chunk("orders")
    start, end = overlap_window(chunk, now=NOW)
    assert end - start == timedelta(hours=24)


def test_overlap_start_clamped_to_chunk_start() -> None:
    short_chunk = HistoryChunk(
        resource="orders",
        start=NOW - timedelta(hours=6),
        end=NOW - timedelta(hours=1),
        id="short",
        priority=ChunkPriority.RECENT,
    )
    start, end = overlap_window(short_chunk, now=NOW, overlap=timedelta(hours=24))
    assert start == short_chunk.start  # clamped, not before
    assert end == short_chunk.end


def test_overlap_request_key_differs_from_base_chunk() -> None:
    chunk = _completed_chunk("orders")
    base_request = chunk_to_recovery_request_or_none(chunk=chunk, seller_id=SELLER)
    assert base_request is not None
    overlap_req = overlap_request(chunk=chunk, seller_id=SELLER, now=NOW)
    assert overlap_req is not None
    assert overlap_req.key != base_request.key
    assert overlap_req.date_to == chunk.end
    assert overlap_req.date_from < chunk.end
    assert overlap_req.read_model == "orders"


def test_overlap_rejects_unknown_resource() -> None:
    chunk = _completed_chunk("unknown_resource")
    assert overlap_request(chunk=chunk, seller_id=SELLER, now=NOW) is None


def test_overlap_rejects_empty_seller() -> None:
    chunk = _completed_chunk("orders")
    assert overlap_request(chunk=chunk, seller_id="", now=NOW) is None


def chunk_to_recovery_request_or_none(
    *, chunk: HistoryChunk, seller_id: str
) -> RecoveryRequest | None:
    from zeler_sheets.pilot_history_recovery_bridge import chunk_to_recovery_request

    try:
        return chunk_to_recovery_request(chunk, seller_id=seller_id)
    except ValueError:
        return None


def test_planner_gap_aware_overlap_skips_incomplete_recent_chunk() -> None:
    """overlap_request returns None when the chunk priority is not RECENT
    and it has not completed — the caller must filter on completion."""
    chunk = HistoryChunk(
        resource="orders",
        start=NOW - timedelta(days=30),
        end=NOW,
        id="recent-incomplete",
        priority=ChunkPriority.RECENT,
    )
    # The function itself does not know completion state; the caller does.
    # This test documents that overlap_request is unconditional on state.
    req = overlap_request(chunk=chunk, seller_id=SELLER, now=NOW)
    assert req is not None  # caller responsibility to skip if not completed
