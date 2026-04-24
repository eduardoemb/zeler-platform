from __future__ import annotations

import json
from typing import Any, Protocol, cast

from zeler_gateway.webhooks.classifier import (
    MELI_EVENTS_EXCHANGE,
    build_event_envelope,
    classify_webhook_event,
)


class WebhookPublisher(Protocol):
    async def publish(
        self, routing_key: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> None: ...


class AioPikaWebhookPublisher:
    def __init__(self, *, rabbitmq_url: str, exchange_name: str = MELI_EVENTS_EXCHANGE) -> None:
        self.rabbitmq_url = rabbitmq_url
        self.exchange_name = exchange_name

    async def publish(
        self, routing_key: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> None:
        import aio_pika

        connection = await aio_pika.connect_robust(self.rabbitmq_url)
        async with connection:
            channel = await connection.channel(publisher_confirms=True)
            exchange = await channel.declare_exchange(
                self.exchange_name,
                aio_pika.ExchangeType.TOPIC,
                durable=True,
            )
            message = aio_pika.Message(
                body=json.dumps(payload).encode("utf-8"),
                content_type="application/json",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                headers=cast(Any, headers),
                message_id=str(payload["event_id"]),
            )
            await exchange.publish(message, routing_key=routing_key)


async def publish_webhook_event(
    event: dict[str, Any], *, publisher: WebhookPublisher, trace_id: str | None = None
) -> None:
    classified = classify_webhook_event(event)
    envelope = build_event_envelope(event, trace_id=trace_id)
    await publisher.publish(
        classified.routing_key,
        envelope,
        {"idempotency_key": classified.idempotency_key, "exchange": MELI_EVENTS_EXCHANGE},
    )
