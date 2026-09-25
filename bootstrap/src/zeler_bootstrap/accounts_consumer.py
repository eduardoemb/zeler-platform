from __future__ import annotations

import asyncio
import json
from typing import Any, Protocol

import aio_pika
import structlog

logger = structlog.get_logger(__name__)

ACCOUNTS_QUEUE = "zeler.bootstrap.accounts"
ACCOUNTS_DLQ = f"{ACCOUNTS_QUEUE}.dlq"
ACCOUNTS_DLX = f"{ACCOUNTS_QUEUE}.dlx"
ACCOUNTS_ROUTING_KEY = "accounts.linked"
EVENTS_EXCHANGE = "meli.events"


class AccountsLinkedDispatcher(Protocol):
    async def handle_accounts_linked(self, event: dict[str, Any]) -> str: ...


class BootstrapAccountsConsumer:
    def __init__(
        self,
        rabbitmq_url: str,
        dispatcher: AccountsLinkedDispatcher,
        *,
        retry_delay_s: float = 2.0,
    ) -> None:
        self._rabbitmq_url = rabbitmq_url
        self._dispatcher = dispatcher
        self._retry_delay_s = retry_delay_s
        self._connection: Any | None = None
        self._channel: Any | None = None
        self._consumer_registered = False

    @property
    def is_ready(self) -> bool:
        connection = self._connection
        channel = self._channel
        return bool(
            self._consumer_registered
            and connection is not None
            and not connection.is_closed
            and connection.connected.is_set()
            and channel is not None
            and not getattr(channel, "is_closed", False)
        )

    async def start(self) -> None:
        try:
            connection = await aio_pika.connect_robust(self._rabbitmq_url)
        except Exception as exc:  # noqa: BLE001 - hide connection details in startup errors.
            logger.error(
                "bootstrap.accounts_linked.broker_unavailable", error_class=type(exc).__name__
            )
            raise RuntimeError("bootstrap dispatcher RabbitMQ unavailable") from None
        self._connection = connection
        try:
            channel = await connection.channel()
            self._channel = channel
            await channel.set_qos(prefetch_count=1)
            exchange = await channel.declare_exchange(
                EVENTS_EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True
            )
            dead_letter_exchange = await channel.declare_exchange(
                ACCOUNTS_DLX, aio_pika.ExchangeType.DIRECT, durable=True
            )
            dead_letter_queue = await channel.declare_queue(ACCOUNTS_DLQ, durable=True)
            await dead_letter_queue.bind(dead_letter_exchange, routing_key=ACCOUNTS_DLQ)
            queue = await channel.declare_queue(
                ACCOUNTS_QUEUE,
                durable=True,
                arguments={
                    "x-dead-letter-exchange": ACCOUNTS_DLX,
                    "x-dead-letter-routing-key": ACCOUNTS_DLQ,
                },
            )
            await queue.bind(exchange, routing_key=ACCOUNTS_ROUTING_KEY)
            await queue.consume(self.handle_message)
            self._consumer_registered = True
        except Exception:
            await self.close()
            raise

    async def close(self) -> None:
        self._consumer_registered = False
        if self._connection is not None:
            await self._connection.close()
            self._connection = None
        self._channel = None

    async def handle_message(self, message: Any) -> None:
        try:
            event = self._parse_event(message.body)
        except (ValueError, UnicodeDecodeError):
            logger.warning("bootstrap.accounts_linked.invalid_event")
            await message.reject(requeue=False)
            return

        seller_id = event["seller_id"]
        try:
            result = await self._dispatcher.handle_accounts_linked(event)
        except Exception as exc:  # noqa: BLE001 - retry any broker/API dispatch failure.
            logger.warning(
                "bootstrap.accounts_linked.dispatch_retry",
                seller_id=seller_id,
                error_class=type(exc).__name__,
            )
            await self._retry(message)
            return

        if result in {"running", "skipped"}:
            await message.ack()
        elif result == "failed":
            await message.reject(requeue=False)
        elif result == "backpressure":
            await self._retry(message)
        else:
            logger.error("bootstrap.accounts_linked.unknown_result", result=result)
            await message.reject(requeue=False)

    async def _retry(self, message: Any) -> None:
        if self._retry_delay_s:
            await asyncio.sleep(self._retry_delay_s)
        await message.nack(requeue=True)

    @staticmethod
    def _parse_event(body: bytes) -> dict[str, Any]:
        event = json.loads(body.decode("utf-8"))
        if not isinstance(event, dict):
            raise ValueError("account-link event must be an object")
        raw_seller_id = event.get("seller_id")
        seller_id = str(raw_seller_id) if raw_seller_id is not None else ""
        if not seller_id.isascii() or not seller_id.isdecimal() or int(seller_id) <= 0:
            raise ValueError("account-link event has invalid seller ID")
        return {**event, "seller_id": seller_id}
