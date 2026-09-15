"""Bridge between the history planner and the existing recovery queue.

Maps a ``HistoryChunk`` for a known resource to the appropriate
``RecoveryRequest`` dataclass accepted by ``FormulaRecoveryQueue.enqueue``.
This keeps the planner (pure interval math) decoupled from the queue
(concrete request types) while ensuring that every history tramo feeds into
the proven, durable recovery pipeline without bypassing any safety controls.
"""

from __future__ import annotations

from zeler_sheets.formulas.recovery import RecoveryRequest
from zeler_sheets.pilot_history import HistoryChunk

__all__ = ["chunk_to_recovery_request"]

# Resource name -> the read model identifier the recovery queue understands.
# Only resources with existing recoverable read models are mapped here.
# Resources that have no recoverable read model (e.g. price/stock/quality
# history) are rejected rather than silently skipped, so the caller must
# handle them through a different acquisition path.
_RESOURCE_TO_READ_MODEL: dict[str, str] = {
    "orders": "orders",
    "questions": "questions",
    "shipments": "shipments",
    "items": "item_formula_rows",
}


def chunk_to_recovery_request(chunk: HistoryChunk, *, seller_id: str) -> RecoveryRequest:
    """Convert a history chunk into a RecoveryRequest for the recovery queue.

    Raises ValueError when the resource has no recoverable read model or
    when the seller identity is empty. This ensures the caller knows
    immediately that a resource cannot be acquired through this bridge
    rather than silently losing work.
    """
    resource = chunk.resource.strip()
    if not resource:
        raise ValueError("chunk resource is required")
    read_model = _RESOURCE_TO_READ_MODEL.get(resource)
    if read_model is None:
        raise ValueError(
            f"resource {resource!r} has no recoverable read model; use a different acquisition path"
        )
    if not seller_id or not seller_id.strip():
        raise ValueError("seller_id is required")
    return RecoveryRequest(
        seller_id=seller_id.strip(),
        read_model=read_model,
        date_from=chunk.start,
        date_to=chunk.end,
    )
