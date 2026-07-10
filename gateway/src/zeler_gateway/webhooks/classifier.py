from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

MELI_EVENTS_EXCHANGE = "meli.events"

TOPIC_ROUTING_KEYS = {
    "items": "items.updated",
    "orders_v2": "orders.updated",
    "shipments": "shipments.updated",
    "questions": "questions.new",
    "messages": "messages.new",
    "items_prices": "items.price_updated",
    "catalog_item_competition_status": "catalog_item_competition_status.updated",
    "user-products-families": "user_products.families_updated",
    "stock-locations": "stock_locations.updated",
    "price_suggestion": "price_suggestion.updated",
}


@dataclass(frozen=True)
class ClassifiedWebhookEvent:
    routing_key: str
    event_type: str
    idempotency_key: str
    resource: str


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


def classify_webhook_topic(topic: str, resource: str) -> WebhookTopicClassification:
    if topic == "post_purchase" and _post_purchase_claim_resource(resource) is not None:
        return WebhookTopicClassification(routing_key="claims.updated")
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
    resource = str(event.get("resource", ""))
    normalized_resource = resource
    routing_key: str | None
    if topic == "post_purchase":
        normalized_resource = _normalize_post_purchase_claim_event(event)
        routing_key = "claims.updated"
    else:
        routing_key = TOPIC_ROUTING_KEYS.get(topic)
    if routing_key is None:
        raise UnknownWebhookTopicError(topic)
    notification_id = _event_id(event)
    return ClassifiedWebhookEvent(
        routing_key=routing_key,
        event_type=routing_key,
        idempotency_key=f"{topic}:{normalized_resource}:{notification_id}",
        resource=normalized_resource,
    )


_CLAIM_RESOURCE = re.compile(r"^/post-purchase/v1/claims/(?P<claim_id>[0-9]+)$")
_CLAIM_ACTIONS_RESOURCE = re.compile(
    r"^/post-purchase/v1/claims/(?P<claim_id>[0-9]+)/actions-history$"
)


def _post_purchase_claim_resource(resource: str) -> str | None:
    match = _CLAIM_RESOURCE.fullmatch(resource) or _CLAIM_ACTIONS_RESOURCE.fullmatch(resource)
    if match is None:
        return None
    return f"/post-purchase/v1/claims/{match.group('claim_id')}"


def _normalize_post_purchase_claim_event(event: dict[str, Any]) -> str:
    resource = str(event.get("resource", ""))
    raw_body = event.get("raw_body")
    actions = event.get("actions")
    if actions is None and isinstance(raw_body, dict):
        actions = raw_body.get("actions")
    if _CLAIM_RESOURCE.fullmatch(resource) and actions == ["claims"]:
        return resource
    match = _CLAIM_ACTIONS_RESOURCE.fullmatch(resource)
    if match is not None and actions == ["claims_actions"]:
        return f"/post-purchase/v1/claims/{match.group('claim_id')}"
    raise UnknownWebhookTopicError("post_purchase")


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
        "resource": classified.resource,
        "trace_id": trace_id or "",
        "schema_version": 1,
    }
