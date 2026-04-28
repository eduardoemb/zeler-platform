from __future__ import annotations

from typing import Any

import pytest
from structlog.testing import capture_logs

from zeler_gateway.webhooks.publisher import publish_webhook_event


class RecordingPublisher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], dict[str, str]]] = []

    async def publish(
        self, routing_key: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> None:
        self.calls.append((routing_key, payload, headers))


@pytest.mark.asyncio
async def test_unknown_topic_publishes_to_dlq_routing_key() -> None:
    publisher = RecordingPublisher()
    event = {
        "_id": "notif-unknown-topic",
        "topic": "future-topic",
        "resource": "/future/1",
        "user_id": 123456789,
    }

    with capture_logs() as logs:
        await publish_webhook_event(event, publisher=publisher, trace_id="trace-unknown")

    assert len(publisher.calls) == 1
    routing_key, payload, headers = publisher.calls[0]
    assert routing_key == "webhooks.unknown.dlq"
    assert payload["event_type"] == "webhooks.unknown"
    assert payload["event_id"] == "notif-unknown-topic"
    assert payload["resource"] == "/future/1"
    assert payload["trace_id"] == "trace-unknown"
    assert headers["exchange"] == "meli.events"
    assert headers["original_topic"] == "future-topic"
    assert headers["idempotency_key"] == "unknown:future-topic:notif-unknown-topic"
    assert all(entry["event"] != "webhook.publish_failed" for entry in logs)


@pytest.mark.asyncio
async def test_unknown_topic_emits_warning_log() -> None:
    publisher = RecordingPublisher()
    event = {
        "_id": "notif-unknown-log",
        "topic": "new-future-topic",
        "resource": "/future/2",
        "user_id": 987654321,
    }

    with capture_logs() as logs:
        await publish_webhook_event(event, publisher=publisher, trace_id="trace-log")

    assert {
        "event": "webhook.unknown_topic_fallback",
        "log_level": "warning",
        "topic": "new-future-topic",
        "original_topic": "new-future-topic",
        "event_id": "notif-unknown-log",
        "seller_id": 987654321,
    } in logs
