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
        for document in self.documents.values():
            if all(document.get(key) == value for key, value in filter_spec.items()):
                return document
        return None

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
    stored = await collection.find_one({"_id": "repricer:items:/items/MLA1:notif-1"})
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
async def test_fanout_modules_process_same_idempotency_key_independently() -> None:
    collection = FakeProcessedEvents()
    store = IdempotencyStore(collection, now_fn=lambda: datetime(2026, 4, 24, 12, 0, tzinfo=UTC))
    idempotency_key = "items:/items/MLA1:notif-1"

    assert await store.is_duplicate(idempotency_key, module_id="repricer") is False
    assert await store.mark_processed(idempotency_key, module_id="repricer") is True

    assert await store.is_duplicate(idempotency_key, module_id="sheets") is False
    assert await store.mark_processed(idempotency_key, module_id="sheets") is True

    assert await store.is_duplicate(idempotency_key, module_id="repricer") is True
    assert await store.is_duplicate(idempotency_key, module_id="sheets") is True
    assert sorted(collection.documents) == [
        "repricer:items:/items/MLA1:notif-1",
        "sheets:items:/items/MLA1:notif-1",
    ]


@pytest.mark.asyncio
async def test_same_module_fanout_consumers_process_same_idempotency_key_independently() -> None:
    collection = FakeProcessedEvents()
    store = IdempotencyStore(collection, now_fn=lambda: datetime(2026, 4, 24, 12, 0, tzinfo=UTC))
    idempotency_key = "items_prices:/items/MLA1/prices:notif-1"

    assert (
        await store.is_duplicate(
            idempotency_key,
            module_id="repricer",
            consumer_id="zeler.repricer.items",
        )
        is False
    )
    assert (
        await store.mark_processed(
            idempotency_key,
            module_id="repricer",
            consumer_id="zeler.repricer.items",
        )
        is True
    )

    assert (
        await store.is_duplicate(
            idempotency_key,
            module_id="repricer",
            consumer_id="zeler.repricer.items_prices",
        )
        is False
    )
    assert (
        await store.mark_processed(
            idempotency_key,
            module_id="repricer",
            consumer_id="zeler.repricer.items_prices",
        )
        is True
    )

    assert (
        await store.is_duplicate(
            idempotency_key,
            module_id="repricer",
            consumer_id="zeler.repricer.items",
        )
        is True
    )
    assert sorted(collection.documents) == [
        "zeler.repricer.items:items_prices:/items/MLA1/prices:notif-1",
        "zeler.repricer.items_prices:items_prices:/items/MLA1/prices:notif-1",
    ]


@pytest.mark.asyncio
async def test_legacy_unscoped_processed_event_only_suppresses_matching_module() -> None:
    now = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)
    collection = FakeProcessedEvents()
    collection.documents["items:/items/MLA1:notif-1"] = {
        "_id": "items:/items/MLA1:notif-1",
        "module_id": "repricer",
        "processed_at": now,
        "expires_at": now + timedelta(hours=1),
    }
    store = IdempotencyStore(collection, now_fn=lambda: now)

    assert await store.is_duplicate("items:/items/MLA1:notif-1", module_id="repricer") is True
    assert await store.is_duplicate("items:/items/MLA1:notif-1", module_id="sheets") is False


@pytest.mark.asyncio
async def test_legacy_unscoped_processed_event_suppresses_new_consumer_specific_check() -> None:
    now = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)
    collection = FakeProcessedEvents()
    collection.documents["items:/items/MLA1:notif-1"] = {
        "_id": "items:/items/MLA1:notif-1",
        "module_id": "sheets",
        "processed_at": now,
        "expires_at": now + timedelta(hours=1),
        "schema_version": 1,
    }
    store = IdempotencyStore(collection, now_fn=lambda: now)

    assert (
        await store.is_duplicate(
            "items:/items/MLA1:notif-1",
            module_id="sheets",
            consumer_id="zeler.sheets.events",
        )
        is True
    )


@pytest.mark.asyncio
async def test_consumer_specific_processed_events_remain_independent_without_legacy_doc() -> None:
    collection = FakeProcessedEvents()
    store = IdempotencyStore(collection, now_fn=lambda: datetime(2026, 4, 24, 12, 0, tzinfo=UTC))
    idempotency_key = "questions:/questions/Q1:notif-1"

    assert (
        await store.mark_processed(
            idempotency_key,
            module_id="sheets",
            consumer_id="zeler.sheets.events",
        )
        is True
    )

    assert (
        await store.is_duplicate(
            idempotency_key,
            module_id="sheets",
            consumer_id="zeler.sheets.events",
        )
        is True
    )
    assert (
        await store.is_duplicate(
            idempotency_key,
            module_id="sheets",
            consumer_id="zeler.sheets.replay.audit",
        )
        is False
    )


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
