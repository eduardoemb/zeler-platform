from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from zeler_platform_core.events.idempotency import IdempotencyStore


class FakeInsertOneResult:
    def __init__(self, inserted_id: str) -> None:
        self.inserted_id = inserted_id


class DuplicateKeyError(Exception):
    pass


class FakeProcessedEvents:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}

    async def find_one(self, filter_spec: dict[str, Any]) -> dict[str, Any] | None:
        return self.documents.get(filter_spec["_id"])

    async def insert_one(self, document: dict[str, Any]) -> FakeInsertOneResult:
        if document["_id"] in self.documents:
            raise DuplicateKeyError("duplicate key")
        self.documents[document["_id"]] = document
        return FakeInsertOneResult(inserted_id=document["_id"])


@pytest.mark.asyncio
async def test_first_key_is_not_duplicate_until_marked() -> None:
    collection = FakeProcessedEvents()
    store = IdempotencyStore(collection, now_fn=lambda: datetime(2026, 4, 24, 12, 0, tzinfo=UTC))

    assert await store.is_duplicate("items:/items/MLA1:notif-1") is False

    await store.mark_processed("items:/items/MLA1:notif-1", module_id="repricer")
    stored = await collection.find_one({"_id": "items:/items/MLA1:notif-1"})
    assert stored is not None
    assert stored["module_id"] == "repricer"


@pytest.mark.asyncio
async def test_second_key_is_duplicate_after_mark_processed() -> None:
    collection = FakeProcessedEvents()
    store = IdempotencyStore(collection, now_fn=lambda: datetime(2026, 4, 24, 12, 0, tzinfo=UTC))

    await store.mark_processed("items:/items/MLA1:notif-1", module_id="repricer")

    assert await store.is_duplicate("items:/items/MLA1:notif-1") is True
    assert await store.mark_processed("items:/items/MLA1:notif-1", module_id="repricer") is False


@pytest.mark.asyncio
async def test_expired_key_is_not_duplicate() -> None:
    now = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)
    collection = FakeProcessedEvents()
    collection.documents["old-key"] = {
        "_id": "old-key",
        "module_id": "repricer",
        "processed_at": now - timedelta(hours=49),
        "expires_at": now - timedelta(hours=1),
    }
    store = IdempotencyStore(collection, now_fn=lambda: now)

    assert await store.is_duplicate("old-key") is False
