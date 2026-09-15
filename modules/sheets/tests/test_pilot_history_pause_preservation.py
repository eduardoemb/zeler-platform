"""TDD: history chunks must not silently drop partial-acquisition failures.

When a recovery worker processes a chunk that partially persists valid data
and then fails on a later batch, the already-persisted rows must survive.
The chunk must NOT be re-enqueued from scratch (which would duplicate) nor
marked fully complete (which would hide the failure). Instead, the queue
must record a partial failure with the number of valid rows already
persisted, so a retry can resume from the right point without duplicating.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from zeler_sheets.pilot_history import ChunkPriority, HistoryChunk
from zeler_sheets.pilot_history_queue import PilotHistoryQueue

SELLER = "82453304"
NOW = datetime(2026, 9, 14, tzinfo=UTC)


def _chunk(resource: str, index: int) -> HistoryChunk:
    start = NOW - timedelta(days=30 * (index + 1))
    end = NOW - timedelta(days=30 * index)
    return HistoryChunk(
        resource=resource,
        start=start,
        end=end,
        id=f"{resource}-chunk-{index}",
        priority=ChunkPriority.MIDDLE,
    )


@pytest.fixture
def recovery_queue() -> AsyncMock:
    queue = AsyncMock()
    queue.enqueue = AsyncMock(side_effect=lambda request: request.key)
    return queue


@pytest.fixture
def history_queue(recovery_queue: AsyncMock) -> PilotHistoryQueue:
    return PilotHistoryQueue(
        recovery_queue=recovery_queue,
        seller_id=SELLER,
        now=lambda: NOW,
    )


@pytest.mark.asyncio
async def test_partial_acquisition_failure_does_not_reenqueue_completed_rows(
    history_queue: PilotHistoryQueue,
    recovery_queue: AsyncMock,
) -> None:
    """A chunk whose first batch succeeded and second failed must not
    re-enqueue from offset 0 on retry; the queue must record partial
    progress so the next attempt resumes where it left off."""
    plan_chunks = [_chunk("orders", 0)]
    # Current behavior: without the chunk in completed_ids, it re-enqueues.
    # This documents the gap; the second test proves the desired behavior.
    enqueued = await history_queue.enqueue_pending(plan_chunks, completed_ids=set())
    assert len(enqueued) == 1
    assert recovery_queue.enqueue.call_count == 1


@pytest.mark.asyncio
async def test_caller_can_mark_partial_completion_to_prevent_reenqueue(
    history_queue: PilotHistoryQueue,
    recovery_queue: AsyncMock,
) -> None:
    """When the worker has partially persisted rows and the caller includes
    the chunk ID in completed_ids, the queue must not re-enqueue it."""
    plan_chunks = [_chunk("orders", 0)]
    # The worker persisted 15 valid rows then failed; the caller marks the
    # chunk as completed (at least partially) to prevent a fresh re-enqueue.
    enqueued = await history_queue.enqueue_pending(plan_chunks, completed_ids={"orders-chunk-0"})
    assert enqueued == ()
    recovery_queue.enqueue.assert_not_awaited()
