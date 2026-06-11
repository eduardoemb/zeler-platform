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

    async def is_duplicate(
        self,
        idempotency_key: str,
        *,
        module_id: str | None = None,
        consumer_id: str | None = None,
    ) -> bool:
        if module_id is None:
            document = await self._collection.find_one({"_id": idempotency_key})
            if self._document_is_active(document):
                return True
            scoped_document = await self._collection.find_one({"idempotency_key": idempotency_key})
            return self._document_is_active(scoped_document)

        scope_id = consumer_id or module_id
        scoped_document = await self._collection.find_one(
            {"_id": _scoped_processed_event_id(idempotency_key, scope_id)}
        )
        if self._document_is_active(scoped_document):
            return True

        legacy_document = await self._collection.find_one({"_id": idempotency_key})
        if legacy_document is None or legacy_document.get("module_id") != module_id:
            return False
        if (
            consumer_id is not None
            and "consumer_id" in legacy_document
            and legacy_document.get("consumer_id") != consumer_id
        ):
            return False
        return self._document_is_active(legacy_document)

    async def mark_processed(
        self, idempotency_key: str, *, module_id: str, consumer_id: str | None = None
    ) -> bool:
        now = self._now_fn()
        scope_id = consumer_id or module_id
        try:
            await self._collection.insert_one(
                {
                    "_id": _scoped_processed_event_id(idempotency_key, scope_id),
                    "idempotency_key": idempotency_key,
                    "module_id": module_id,
                    "consumer_id": scope_id,
                    "processed_at": now,
                    "expires_at": now + self._retention,
                    "schema_version": 2,
                }
            )
        except Exception as exc:
            if "duplicate" in str(exc).lower():
                return False
            raise
        return True

    def _document_is_active(self, document: dict[str, Any] | None) -> bool:
        if document is None:
            return False
        expires_at = document.get("expires_at")
        return isinstance(expires_at, datetime) and expires_at > self._now_fn()


def _scoped_processed_event_id(idempotency_key: str, scope_id: str) -> str:
    return f"{scope_id}:{idempotency_key}"
