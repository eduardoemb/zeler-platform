from __future__ import annotations

from typing import Any, cast

import aio_pika

RETRY_ATTEMPT_HEADER = "x-zeler-retry-attempt"


class RetryDelayPublisher:
    def __init__(self, channel: Any, *, exchange_name: str = "meli.events") -> None:
        self._channel = channel
        self._exchange_name = exchange_name

    async def publish_delay(
        self,
        message_body: bytes,
        queue_name: str,
        *,
        delay_ms: int,
        headers: dict[str, object] | None = None,
    ) -> None:
        exchange = await self._channel.declare_exchange(
            self._exchange_name,
            "topic",
            durable=True,
        )
        message = aio_pika.Message(
            body=message_body,
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            expiration=delay_ms,
            headers=cast(Any, headers),
        )
        await exchange.publish(message, routing_key=f"{queue_name}.delay")
