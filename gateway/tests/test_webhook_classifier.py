from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from zeler_gateway.webhooks.classifier import (
    UnknownWebhookTopicError,
    build_event_envelope,
    classify_webhook_event,
)
from zeler_gateway.webhooks.publisher import publish_webhook_event

FIXTURES = Path(__file__).parent / "fixtures" / "post_purchase"


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


def test_questions_topic_classifies_to_questions_new_for_autoreply_bindings() -> None:
    event = {
        "_id": "notif-question",
        "topic": "questions",
        "resource": "/questions/9",
        "user_id": 123456789,
    }

    classified = classify_webhook_event(event)

    assert classified.routing_key == "questions.new"
    assert classified.event_type == "questions.new"
    assert classified.idempotency_key == "questions:/questions/9:notif-question"


def test_user_products_families_classifies_to_user_products_families_updated() -> None:
    event = {
        "_id": "notif-user-products-families",
        "topic": "user-products-families",
        "resource": "/user-products/families/123",
        "user_id": 123456789,
    }

    classified = classify_webhook_event(event)

    assert classified.routing_key == "user_products.families_updated"
    assert classified.event_type == "user_products.families_updated"


def test_stock_locations_classifies_to_stock_locations_updated() -> None:
    event = {
        "_id": "notif-stock-locations",
        "topic": "stock-locations",
        "resource": "/stock-locations/MLA123",
        "user_id": 123456789,
    }

    classified = classify_webhook_event(event)

    assert classified.routing_key == "stock_locations.updated"
    assert classified.event_type == "stock_locations.updated"


def test_price_suggestion_classifies_to_price_suggestion_updated() -> None:
    event = {
        "_id": "notif-price-suggestion",
        "topic": "price_suggestion",
        "resource": "suggestions/items/MLA123/details",
        "user_id": 123456789,
    }

    classified = classify_webhook_event(event)

    assert classified.routing_key == "price_suggestion.updated"
    assert classified.event_type == "price_suggestion.updated"


def test_unknown_topic_routes_to_dlq_classification() -> None:
    event = {"_id": "notif-3", "topic": "unknown", "resource": "/unknown/1", "user_id": 123456789}

    with pytest.raises(UnknownWebhookTopicError) as exc_info:
        classify_webhook_event(event)

    assert exc_info.value.dlq_routing_key == "webhooks.unknown.dlq"


def test_unknown_topic_error_still_raised_by_classifier() -> None:
    event = {
        "_id": "notif-unknown-contract",
        "topic": "future-topic",
        "resource": "/future/1",
        "user_id": 123456789,
    }

    with pytest.raises(UnknownWebhookTopicError) as exc_info:
        classify_webhook_event(event)

    assert exc_info.value.topic == "future-topic"


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
            "questions.new",
            {
                "event_id": "notif-5",
                "event_type": "questions.new",
                "occurred_at": publisher.calls[0][1]["occurred_at"],
                "seller_id": 123456789,
                "resource": "/questions/9",
                "trace_id": "trace-456",
                "schema_version": 1,
            },
            {"idempotency_key": "questions:/questions/9:notif-5", "exchange": "meli.events"},
        )
    ]


@pytest.mark.parametrize(
    ("fixture_name", "claim_id"),
    [("claims.json", "519988001"), ("claims_actions.json", "519988002")],
)
def test_post_purchase_claim_variants_normalize_to_parent_claim(
    fixture_name: str, claim_id: str
) -> None:
    event = json.loads((FIXTURES / fixture_name).read_text(encoding="utf-8"))

    classified = classify_webhook_event(event)
    envelope = build_event_envelope(event, trace_id="replay-contract")

    assert classified.routing_key == "claims.updated"
    assert classified.event_type == "claims.updated"
    assert classified.idempotency_key == (
        f"post_purchase:/post-purchase/v1/claims/{claim_id}:{event['_id']}"
    )
    assert envelope["resource"] == f"/post-purchase/v1/claims/{claim_id}"
    assert envelope["event_type"] == "claims.updated"
    assert not ({"fresh_until", "reconciled_until", "valid_until"} & envelope.keys())


@pytest.mark.parametrize(
    ("fixture_name", "claim_id"),
    [("claims.json", "519988001"), ("claims_actions.json", "519988002")],
)
def test_stored_live_webhook_shape_reads_actions_from_raw_body(
    fixture_name: str, claim_id: str
) -> None:
    payload = json.loads((FIXTURES / fixture_name).read_text(encoding="utf-8"))
    stored_event = {
        "_id": payload["_id"],
        "topic": payload["topic"],
        "resource": payload["resource"],
        "user_id": payload["user_id"],
        "received_at": datetime(2026, 7, 9, tzinfo=UTC),
        "raw_body": payload,
        "schema_version": 1,
    }

    classified = classify_webhook_event(stored_event)

    assert classified.routing_key == "claims.updated"
    assert classified.resource == f"/post-purchase/v1/claims/{claim_id}"


@pytest.mark.parametrize(
    "event",
    [
        {
            "_id": "legacy-claims",
            "topic": "claims",
            "resource": "/claims/519988001",
            "user_id": 82453304,
        },
        {
            "_id": "wrong-action",
            "topic": "post_purchase",
            "resource": "/post-purchase/v1/claims/519988001",
            "actions": ["claims_actions"],
            "user_id": 82453304,
        },
        {
            "_id": "wrong-resource",
            "topic": "post_purchase",
            "resource": "/post-purchase/v1/claims/519988001/detail",
            "actions": ["claims"],
            "user_id": 82453304,
        },
    ],
)
def test_unproven_claim_notification_contracts_are_rejected(event: dict[str, Any]) -> None:
    with pytest.raises(UnknownWebhookTopicError):
        classify_webhook_event(event)
