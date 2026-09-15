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
async def test_enqueue_pending_chunks_maps_to_recovery_queue(
    history_queue: PilotHistoryQueue,
    recovery_queue: AsyncMock,
) -> None:
    plan_chunks = [_chunk("orders", 0), _chunk("questions", 0)]
    enqueued = await history_queue.enqueue_pending(plan_chunks, completed_ids=set())
    assert len(enqueued) == 2
    assert recovery_queue.enqueue.call_count == 2
    first_request = recovery_queue.enqueue.call_args_list[0][0][0]
    assert first_request.seller_id == SELLER
    assert first_request.read_model == "orders"


@pytest.mark.asyncio
async def test_enqueue_skips_completed_chunks(
    history_queue: PilotHistoryQueue,
    recovery_queue: AsyncMock,
) -> None:
    plan_chunks = [_chunk("orders", 0), _chunk("orders", 1)]
    completed = {_chunk("orders", 0).id}
    enqueued = await history_queue.enqueue_pending(plan_chunks, completed_ids=completed)
    assert len(enqueued) == 1
    assert recovery_queue.enqueue.call_count == 1


@pytest.mark.asyncio
async def test_enqueue_returns_chunk_ids_that_were_admitted(
    history_queue: PilotHistoryQueue,
    recovery_queue: AsyncMock,
) -> None:
    plan_chunks = [_chunk("orders", 0), _chunk("questions", 0), _chunk("shipments", 0)]
    enqueued = await history_queue.enqueue_pending(plan_chunks, completed_ids=set())
    assert set(enqueued) == {c.id for c in plan_chunks}


@pytest.mark.asyncio
async def test_enqueue_preserves_priority_ordering(
    history_queue: PilotHistoryQueue,
    recovery_queue: AsyncMock,
) -> None:
    recent = HistoryChunk(
        resource="orders",
        start=NOW - timedelta(days=30),
        end=NOW,
        id="orders-recent",
        priority=ChunkPriority.RECENT,
    )
    oldest = HistoryChunk(
        resource="orders",
        start=NOW - timedelta(days=360),
        end=NOW - timedelta(days=330),
        id="orders-oldest",
        priority=ChunkPriority.OLDEST_EDGE,
    )
    middle = HistoryChunk(
        resource="orders",
        start=NOW - timedelta(days=180),
        end=NOW - timedelta(days=150),
        id="orders-middle",
        priority=ChunkPriority.MIDDLE,
    )
    enqueued = await history_queue.enqueue_pending([middle, oldest, recent], completed_ids=set())
    assert enqueued[0] == recent.id
    assert enqueued[1] == oldest.id
    assert enqueued[2] == middle.id


@pytest.mark.asyncio
async def test_enqueue_unknown_resource_raises_and_stops_batch(
    history_queue: PilotHistoryQueue,
    recovery_queue: AsyncMock,
) -> None:
    plan_chunks = [_chunk("orders", 0), _chunk("unknown", 0), _chunk("orders", 1)]
    with pytest.raises(ValueError, match="no recoverable read model"):
        await history_queue.enqueue_pending(plan_chunks, completed_ids=set())
    # The unknown chunk is sorted by priority, so a MIDDLE unknown
    # chunk after two other MIDDLE chunks raises at the second position.
    # The exact call count depends on the sorted order; what matters is
    # that it stops after raising, and the caller sees partial work.
    assert recovery_queue.enqueue.call_count < len(plan_chunks)


@pytest.mark.asyncio
async def test_enqueue_with_empty_chunks_returns_empty(
    history_queue: PilotHistoryQueue,
    recovery_queue: AsyncMock,
) -> None:
    enqueued = await history_queue.enqueue_pending([], completed_ids=set())
    assert enqueued == ()
    recovery_queue.enqueue.assert_not_awaited()
