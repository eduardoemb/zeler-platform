from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Protocol, cast

import structlog

from zeler_gateway.webhooks.classifier import (
    MELI_EVENTS_EXCHANGE,
    UnknownWebhookTopicError,
    build_event_envelope,
    classify_webhook_event,
)

logger = structlog.get_logger(__name__)


class WebhookPublisher(Protocol):
    async def publish(
        self, routing_key: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> None: ...


class ExchangePublisher(Protocol):
    async def publish_to_exchange(
        self,
        exchange_name: str,
        routing_key: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> None: ...


class WebhookPublishError(RuntimeError):
    pass


class WebhookPublishReturnedError(WebhookPublishError):
    pass


class WebhookPublishRejectedError(WebhookPublishError):
    pass


def _is_returned_publish_result(publish_result: Any) -> bool:
    delivery = getattr(publish_result, "delivery", None)
    return publish_result.__class__.__name__ == "DeliveredMessage" or (
        delivery is not None
        and (
            delivery.__class__.__name__ == "Return"
            or (hasattr(delivery, "reply_code") and hasattr(delivery, "reply_text"))
        )
    )


def _raise_for_publish_result(publish_result: Any, *, exchange_name: str, routing_key: str) -> None:
    if publish_result is None:
        return
    result_name = publish_result.__class__.__name__
    if result_name in {"Nack", "Reject"}:
        raise WebhookPublishRejectedError(
            f"RabbitMQ rejected webhook publish to {exchange_name!r} "
            f"with routing key {routing_key!r}"
        )
    if _is_returned_publish_result(publish_result):
        raise WebhookPublishReturnedError(
            f"RabbitMQ returned mandatory webhook publish to {exchange_name!r} "
            f"with routing key {routing_key!r}"
        )


class AioPikaWebhookPublisher:
    def __init__(self, *, rabbitmq_url: str, exchange_name: str = MELI_EVENTS_EXCHANGE) -> None:
        self.rabbitmq_url = rabbitmq_url
        self.exchange_name = exchange_name

    async def publish(
        self, routing_key: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> None:
        await self._publish_to_exchange(self.exchange_name, routing_key, payload, headers)

    async def publish_to_exchange(
        self,
        exchange_name: str,
        routing_key: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        await self._publish_to_exchange(exchange_name, routing_key, payload, headers)

    async def _publish_to_exchange(
        self,
        exchange_name: str,
        routing_key: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        import aio_pika

        connection = await aio_pika.connect_robust(self.rabbitmq_url)
        async with connection:
            channel = await connection.channel(
                publisher_confirms=True,
                on_return_raises=True,
            )
            exchange = await channel.declare_exchange(
                exchange_name,
                aio_pika.ExchangeType.TOPIC,
                durable=True,
            )
            message = aio_pika.Message(
                body=json.dumps(payload).encode("utf-8"),
                content_type="application/json",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                headers=cast(Any, headers),
                message_id=str(payload.get("event_id") or payload["idempotency_key"]),
            )
            publish_result = await exchange.publish(
                message, routing_key=routing_key, mandatory=True
            )
            _raise_for_publish_result(
                publish_result,
                exchange_name=exchange_name,
                routing_key=routing_key,
            )


class AccountLifecyclePublisherAdapter:
    def __init__(self, transport: ExchangePublisher) -> None:
        self.transport = transport

    async def publish(self, *, exchange: str, routing_key: str, payload: dict[str, Any]) -> None:
        await self.transport.publish_to_exchange(
            exchange,
            routing_key,
            payload,
            {"idempotency_key": str(payload["idempotency_key"])},
        )


def _fallback_event_id(event: dict[str, Any]) -> str:
    return str(event.get("_id") or event.get("notification_id") or event.get("id") or "")


def _fallback_occurred_at(event: dict[str, Any]) -> str:
    received_at = event.get("received_at")
    timestamp = (
        received_at.astimezone(UTC) if isinstance(received_at, datetime) else datetime.now(UTC)
    )
    return timestamp.isoformat().replace("+00:00", "Z")


def _build_unknown_envelope(
    event: dict[str, Any], *, trace_id: str | None = None
) -> dict[str, Any]:
    return {
        "event_id": _fallback_event_id(event),
        "event_type": "webhooks.unknown",
        "occurred_at": _fallback_occurred_at(event),
        "seller_id": event.get("user_id"),
        "resource": str(event.get("resource", "")),
        "trace_id": trace_id or "",
        "schema_version": 1,
    }


async def publish_webhook_event(
    event: dict[str, Any], *, publisher: WebhookPublisher, trace_id: str | None = None
) -> None:
    try:
        classified = classify_webhook_event(event)
        envelope = build_event_envelope(event, trace_id=trace_id)
        await publisher.publish(
            classified.routing_key,
            envelope,
            {"idempotency_key": classified.idempotency_key, "exchange": MELI_EVENTS_EXCHANGE},
        )
    except UnknownWebhookTopicError as exc:
        event_id = _fallback_event_id(event)
        original_topic = str(event.get("topic", ""))
        envelope = _build_unknown_envelope(event, trace_id=trace_id)
        await publisher.publish(
            exc.dlq_routing_key,
            envelope,
            {
                "idempotency_key": f"unknown:{original_topic}:{event_id}",
                "exchange": MELI_EVENTS_EXCHANGE,
                "original_topic": original_topic,
            },
        )
        logger.warning(
            "webhook.unknown_topic_fallback",
            topic=exc.topic,
            original_topic=original_topic,
            event_id=event_id,
            seller_id=event.get("user_id"),
        )
