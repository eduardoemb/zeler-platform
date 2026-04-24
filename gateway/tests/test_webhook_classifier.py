from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from zeler_gateway.webhooks.classifier import (
    UnknownWebhookTopicError,
    build_event_envelope,
    classify_webhook_event,
)
from zeler_gateway.webhooks.publisher import publish_webhook_event


class RecordingPublisher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], dict[str, str]]] = []

    async def publish(
        self, routing_key: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> None:
        self.calls.append((routing_key, payload, headers))


def test_items_topic_classifies_to_items_updated() -> None:
    event = {"_id": "notif-1", "topic": "items", "resource": "/items/MLA123", "user_id": 123456789}

    classified = classify_webhook_event(event)

    assert classified.routing_key == "items.updated"
    assert classified.event_type == "items.updated"
    assert classified.idempotency_key == "items:/items/MLA123:notif-1"


def test_orders_v2_classifies_to_orders_updated() -> None:
    event = {"_id": "notif-2", "topic": "orders_v2", "resource": "/orders/42", "user_id": 123456789}

    classified = classify_webhook_event(event)

    assert classified.routing_key == "orders.updated"
    assert classified.idempotency_key == "orders_v2:/orders/42:notif-2"


def test_unknown_topic_routes_to_dlq_classification() -> None:
    event = {"_id": "notif-3", "topic": "unknown", "resource": "/unknown/1", "user_id": 123456789}

    with pytest.raises(UnknownWebhookTopicError) as exc_info:
        classify_webhook_event(event)

    assert exc_info.value.dlq_routing_key == "webhooks.unknown.dlq"


def test_event_envelope_excludes_full_raw_body() -> None:
    received_at = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)
    event = {
        "_id": "notif-4",
        "topic": "items_prices",
        "resource": "/items/MLA123/prices",
        "user_id": 123456789,
        "received_at": received_at,
        "raw_body": {"large": "payload"},
    }

    envelope = build_event_envelope(event, trace_id="trace-123")

    assert envelope == {
        "event_id": "notif-4",
        "event_type": "items.price_updated",
        "occurred_at": "2026-04-24T12:00:00Z",
        "seller_id": 123456789,
        "resource": "/items/MLA123/prices",
        "trace_id": "trace-123",
        "schema_version": 1,
    }


@pytest.mark.asyncio
async def test_publish_uses_meli_events_exchange_contract() -> None:
    publisher = RecordingPublisher()
    event = {
        "_id": "notif-5",
        "topic": "questions",
        "resource": "/questions/9",
        "user_id": 123456789,
    }

    await publish_webhook_event(event, publisher=publisher, trace_id="trace-456")

    assert publisher.calls == [
        (
            "questions.updated",
            {
                "event_id": "notif-5",
                "event_type": "questions.updated",
                "occurred_at": publisher.calls[0][1]["occurred_at"],
                "seller_id": 123456789,
                "resource": "/questions/9",
                "trace_id": "trace-456",
                "schema_version": 1,
            },
            {"idempotency_key": "questions:/questions/9:notif-5", "exchange": "meli.events"},
        )
    ]
