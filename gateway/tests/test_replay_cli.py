from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from zeler_gateway.cli.replay_events import replay_events


class FakeCursor:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.documents = documents

    def sort(self, _field: str, _direction: int) -> FakeCursor:
        return self

    def limit(self, limit: int) -> FakeCursor:
        self.documents = self.documents[:limit]
        return self

    def __aiter__(self) -> FakeCursor:
        return self

    async def __anext__(self) -> dict[str, Any]:
        if not self.documents:
            raise StopAsyncIteration
        return self.documents.pop(0)


class FakeWebhookEvents:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.documents = documents
        self.last_query: dict[str, Any] | None = None

    def find(self, query: dict[str, Any]) -> FakeCursor:
        self.last_query = query
        return FakeCursor(list(self.documents))


class FakeDatabase:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.webhook_events = FakeWebhookEvents(documents)

    def __getitem__(self, collection_name: str) -> FakeWebhookEvents:
        assert collection_name == "webhook_events"
        return self.webhook_events


class RecordingPublisher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], dict[str, str]]] = []

    async def publish(
        self, routing_key: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> None:
        self.calls.append((routing_key, payload, headers))


def _event(event_id: str, seller_id: int = 123456789) -> dict[str, Any]:
    return {
        "_id": event_id,
        "topic": "items",
        "resource": f"/items/{event_id}",
        "user_id": seller_id,
        "received_at": datetime(2026, 4, 24, 12, 0, tzinfo=UTC),
    }


@pytest.mark.asyncio
async def test_replay_dry_run_lists_without_republishing() -> None:
    database = FakeDatabase([_event("MLA1"), _event("MLA2")])
    publisher = RecordingPublisher()

    result = await replay_events(
        database, publisher=publisher, topic="items", dry_run=True, limit=10
    )

    assert result.replayed == 0
    assert result.candidates == ["MLA1", "MLA2"]
    assert publisher.calls == []


@pytest.mark.asyncio
async def test_replay_respects_limit_and_seller_filter() -> None:
    database = FakeDatabase([_event("MLA1", seller_id=123), _event("MLA2", seller_id=123)])
    publisher = RecordingPublisher()

    result = await replay_events(
        database, publisher=publisher, topic="items", seller_id=123, dry_run=False, limit=1
    )

    assert result.replayed == 1
    assert len(publisher.calls) == 1
    assert publisher.calls[0][0] == "items.updated"
    assert database.webhook_events.last_query == {"topic": "items", "user_id": 123}
