"""Durable per-event stage telemetry for the ZelerData pilot.

Records four timestamps per event in a dedicated Mongo collection so that
the pilot can measure received→visible latency across worker restarts.

Stage semantics (from the pilot design):
- ``received``: event passed dedup and entered the handler.
- ``fetched``: resource response received from the gateway.
- ``persisted``: source write and projection update completed.
- ``visible``: a later read/refresh proves the formula-cell result; an event
  export append does not provide this evidence.

``received_at`` records the earliest delivery so re-queued events do not
inflate the latency measurement. Other stages record the most recent
successful observation, which is correct for sequential event processing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

__all__ = ["EventStageTelemetry"]

_STAGE_FIELD = {
    "received": "received_at",
    "fetched": "fetched_at",
    "persisted": "persisted_at",
    "visible": "visible_at",
}


class EventStageTelemetry:
    """Persist stage timestamps for events in ``sheets_event_stages``."""

    def __init__(self, *, db: Any) -> None:
        self._collection = db["sheets_event_stages"]

    async def record(self, *, event_key: str, stage: str, timestamp: datetime) -> None:
        """Record a stage timestamp for an event.

        ``received`` uses a min-update so re-delivery keeps the earliest.
        Other stages use a normal set because processing is sequential.
        """
        field = _STAGE_FIELD.get(stage)
        if field is None:
            raise ValueError(f"unknown stage {stage!r}")
        if not event_key.strip():
            raise ValueError("event_key is required")

        if field == "received_at":
            # Keep the earliest received timestamp: min-update pattern.
            await self._collection.update_one(
                {"_id": event_key},
                {"$min": {field: timestamp}},
                upsert=True,
            )
        else:
            await self._collection.update_one(
                {"_id": event_key},
                {"$set": {field: timestamp}},
                upsert=True,
            )

    async def get_stage(self, *, event_key: str) -> dict[str, Any] | None:
        """Return the stage document, or None if the event was never recorded."""
        result: dict[str, Any] | None = await self._collection.find_one({"_id": event_key})
        return result
