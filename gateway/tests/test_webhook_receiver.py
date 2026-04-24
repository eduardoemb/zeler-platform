from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from time import monotonic
from typing import Any

import httpx
import pytest

from zeler_gateway.app import app


class FakeUpdateResult:
    def __init__(self, *, upserted_id: str | None, matched_count: int) -> None:
        self.upserted_id = upserted_id
        self.matched_count = matched_count
        self.modified_count = 0


class FakeWebhookEvents:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}

    async def update_one(
        self, filter_spec: dict[str, Any], update_spec: dict[str, Any], *, upsert: bool
    ) -> FakeUpdateResult:
        assert upsert is True
        event_id = filter_spec["_id"]
        if event_id in self.documents:
            return FakeUpdateResult(upserted_id=None, matched_count=1)
        self.documents[event_id] = update_spec["$setOnInsert"]
        return FakeUpdateResult(upserted_id=event_id, matched_count=0)

    async def find_one(self, filter_spec: dict[str, Any]) -> dict[str, Any] | None:
        return self.documents.get(filter_spec["_id"])


class FakeDatabase:
    def __init__(self) -> None:
        self.webhook_events = FakeWebhookEvents()

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


@pytest.fixture
def webhook_test_app(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[tuple[FakeDatabase, RecordingPublisher]]:
    db = FakeDatabase()
    publisher = RecordingPublisher()
    app.state.mongo_db = db
    app.state.webhook_publisher = publisher
    monkeypatch.setenv("MELI_ALLOWED_IPS", "10.0.0.0/24,200.1.2.3")
    yield db, publisher
    if hasattr(app.state, "webhook_publisher"):
        del app.state.webhook_publisher


@pytest.mark.asyncio
async def test_valid_ip_webhook_returns_200_within_500ms(
    webhook_test_app: tuple[FakeDatabase, RecordingPublisher],
) -> None:
    _, publisher = webhook_test_app
    transport = httpx.ASGITransport(app=app)
    payload = {
        "_id": "notif-1",
        "topic": "items",
        "resource": "/items/MLA123",
        "user_id": 123456789,
    }

    async with httpx.AsyncClient(transport=transport, base_url="http://gateway.test") as client:
        started = monotonic()
        response = await client.post(
            "/webhooks/meli", json=payload, headers={"X-Forwarded-For": "10.0.0.5"}
        )
        elapsed_ms = (monotonic() - started) * 1000

    assert response.status_code == 200
    assert response.json() == {"status": "accepted", "duplicate": False}
    assert elapsed_ms < 500
    assert publisher.calls[0][0] == "items.updated"


@pytest.mark.asyncio
async def test_invalid_ip_returns_401(
    webhook_test_app: tuple[FakeDatabase, RecordingPublisher],
) -> None:
    db, publisher = webhook_test_app
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://gateway.test") as client:
        response = await client.post(
            "/webhooks/meli",
            json={
                "_id": "notif-bad",
                "topic": "items",
                "resource": "/items/MLA123",
                "user_id": 123456789,
            },
            headers={"X-Forwarded-For": "203.0.113.10"},
        )

    assert response.status_code == 401
    assert db.webhook_events.documents == {}
    assert publisher.calls == []


@pytest.mark.asyncio
async def test_duplicate_notification_returns_200_no_publish(
    webhook_test_app: tuple[FakeDatabase, RecordingPublisher],
) -> None:
    db, publisher = webhook_test_app
    db.webhook_events.documents["notif-dup"] = {
        "_id": "notif-dup",
        "topic": "items",
        "resource": "/items/MLA123",
        "user_id": 123456789,
        "received_at": datetime.now(UTC),
    }
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://gateway.test") as client:
        response = await client.post(
            "/webhooks/meli",
            json={
                "_id": "notif-dup",
                "topic": "items",
                "resource": "/items/MLA123",
                "user_id": 123456789,
            },
            headers={"X-Forwarded-For": "10.0.0.6"},
        )

    assert response.status_code == 200
    assert response.json() == {"status": "accepted", "duplicate": True}
    assert len(db.webhook_events.documents) == 1
    assert publisher.calls == []


@pytest.mark.asyncio
async def test_payload_persisted_to_webhook_events(
    webhook_test_app: tuple[FakeDatabase, RecordingPublisher],
) -> None:
    db, _ = webhook_test_app
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://gateway.test") as client:
        await client.post(
            "/webhooks/meli",
            json={
                "_id": "notif-persisted",
                "topic": "orders_v2",
                "resource": "/orders/42",
                "user_id": 123456789,
            },
            headers={"X-Forwarded-For": "200.1.2.3"},
        )

    stored = await db.webhook_events.find_one({"_id": "notif-persisted"})
    assert stored is not None
    assert stored["topic"] == "orders_v2"
    assert stored["user_id"] == 123456789
    assert stored["resource"] == "/orders/42"
    assert stored["raw_body"]["_id"] == "notif-persisted"
    assert stored["source_ip"] == "200.1.2.3"
    assert isinstance(stored["received_at"], datetime)
