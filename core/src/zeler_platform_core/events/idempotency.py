from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol


class ProcessedEventsCollection(Protocol):
    async def find_one(self, filter_spec: dict[str, Any]) -> dict[str, Any] | None: ...

    async def insert_one(self, document: dict[str, Any]) -> Any: ...


class IdempotencyStore:
    def __init__(
        self,
        collection: ProcessedEventsCollection,
        *,
        retention: timedelta = timedelta(hours=48),
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._collection = collection
        self._retention = retention
        self._now_fn = now_fn or (lambda: datetime.now(UTC))

    async def is_duplicate(self, idempotency_key: str) -> bool:
        document = await self._collection.find_one({"_id": idempotency_key})
        if document is None:
            return False
        expires_at = document.get("expires_at")
        return isinstance(expires_at, datetime) and expires_at > self._now_fn()

    async def mark_processed(self, idempotency_key: str, *, module_id: str) -> bool:
        now = self._now_fn()
        try:
            await self._collection.insert_one(
                {
                    "_id": idempotency_key,
                    "module_id": module_id,
                    "processed_at": now,
                    "expires_at": now + self._retention,
                    "schema_version": 1,
                }
            )
        except Exception as exc:
            if "duplicate" in str(exc).lower():
                return False
            raise
        return True
