"""Orchestrates resumable history chunks into the existing recovery queue.

Receives a plan's chunks (optionally with prior completed IDs), filters out
completed work, sorts by priority, maps each chunk to a RecoveryRequest,
and enqueues it through the existing durable FormulaRecoveryQueue. This is
the bridge between the pure planner and the production acquisition worker:
it does not call Mercado Libre, does not bypass leases, and does not
weaken any recovery safety control.
"""

from __future__ import annotations

from typing import Any

from zeler_sheets.pilot_history import ChunkPriority, HistoryChunk

__all__ = ["PilotHistoryQueue"]


class PilotHistoryQueue:
    """Feeds resumable history chunks into the existing recovery pipeline."""

    def __init__(
        self,
        *,
        recovery_queue: Any,
        seller_id: str,
        now: Any = None,
    ) -> None:
        self._recovery_queue = recovery_queue
        self._seller_id = seller_id
        self._now = now

    async def enqueue_pending(
        self,
        chunks: list[HistoryChunk] | tuple[HistoryChunk, ...],
        *,
        completed_ids: set[str],
    ) -> tuple[str, ...]:
        """Enqueue incomplete chunks in priority order and return admitted IDs.

        Chunks are sorted: RECENT first (pilot utility now), then
        OLDEST_EDGE (retention risk), then MIDDLE (oldest start first).
        Completed IDs are filtered out. Unknown resources raise ValueError,
        which stops the batch after the last valid admission; the caller
        can resume from the returned IDs.
        """
        if not chunks:
            return ()
        priority_order = {
            ChunkPriority.RECENT: 0,
            ChunkPriority.OLDEST_EDGE: 1,
            ChunkPriority.MIDDLE: 2,
        }
        pending = [chunk for chunk in chunks if chunk.id not in completed_ids]
        pending.sort(key=lambda c: (priority_order[c.priority], c.start))
        admitted: list[str] = []
        for chunk in pending:
            request = chunk_to_recovery_request(chunk, seller_id=self._seller_id)
            await self._recovery_queue.enqueue(request)
            admitted.append(chunk.id)
        return tuple(admitted)


from zeler_sheets.pilot_history_recovery_bridge import chunk_to_recovery_request  # noqa: E402
