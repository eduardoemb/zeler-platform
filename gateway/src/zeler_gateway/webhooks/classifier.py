from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

MELI_EVENTS_EXCHANGE = "meli.events"

TOPIC_ROUTING_KEYS = {
    "items": "items.updated",
    "orders_v2": "orders.updated",
    "shipments": "shipments.updated",
    "questions": "questions.updated",
    "messages": "messages.new",
    "claims": "claims.updated",
    "post_purchase": "post_purchase.updated",
    "items_prices": "items.price_updated",
    "catalog_item_competition_status": "catalog_item_competition_status.updated",
}


@dataclass(frozen=True)
class ClassifiedWebhookEvent:
    routing_key: str
    event_type: str
    idempotency_key: str


class UnknownWebhookTopicError(ValueError):
    def __init__(self, topic: str) -> None:
        super().__init__(f"unsupported Meli webhook topic: {topic}")
        self.topic = topic
        self.dlq_routing_key = "webhooks.unknown.dlq"


@dataclass(frozen=True)
class WebhookTopicClassification:
    routing_key: str

    def idempotency_key(self, notification_id: str) -> str:
        return f"{self.routing_key}:{notification_id}"


def classify_webhook_topic(topic: str, _resource: str) -> WebhookTopicClassification:
    routing_key = TOPIC_ROUTING_KEYS.get(topic)
    if routing_key is None:
        raise UnknownWebhookTopicError(topic)
    return WebhookTopicClassification(routing_key=routing_key)


def _event_id(event: dict[str, Any]) -> str:
    value = event.get("_id") or event.get("notification_id") or event.get("id")
    if value is None:
        raise ValueError("webhook event is missing _id/notification_id")
    return str(value)


def classify_webhook_event(event: dict[str, Any]) -> ClassifiedWebhookEvent:
    topic = str(event.get("topic", ""))
    routing_key = TOPIC_ROUTING_KEYS.get(topic)
    if routing_key is None:
        raise UnknownWebhookTopicError(topic)
    resource = str(event.get("resource", ""))
    notification_id = _event_id(event)
    return ClassifiedWebhookEvent(
        routing_key=routing_key,
        event_type=routing_key,
        idempotency_key=f"{topic}:{resource}:{notification_id}",
    )


def _format_occurred_at(value: Any) -> str:
    timestamp = value.astimezone(UTC) if isinstance(value, datetime) else datetime.now(UTC)
    return timestamp.isoformat().replace("+00:00", "Z")


def build_event_envelope(event: dict[str, Any], *, trace_id: str | None = None) -> dict[str, Any]:
    classified = classify_webhook_event(event)
    return {
        "event_id": _event_id(event),
        "event_type": classified.event_type,
        "occurred_at": _format_occurred_at(event.get("received_at")),
        "seller_id": int(event["user_id"]),
        "resource": str(event["resource"]),
        "trace_id": trace_id or "",
        "schema_version": 1,
    }
