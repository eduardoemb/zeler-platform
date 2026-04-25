from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

import aio_pika

from zeler_platform_core.models import Item, RepricerRule
from zeler_platform_core.runtime.manifest import validate_manifest
from zeler_repricer.engine import SetPrice, evaluate_rule

MELI_EVENTS_EXCHANGE = "meli.events"
REPRICER_ITEMS_QUEUE = "zeler.repricer.items"
REPRICER_ITEMS_DLX = "zeler.repricer.items.dlx"
REPRICER_DELIVERY_LIMIT = 5
DEFAULT_PREFETCH_COUNT = 10


@dataclass(frozen=True)
class RepricerEvent:
    event_id: str
    event_type: str
    seller_id: int
    resource: str
    idempotency_key: str
    buybox_price: Decimal | None = None


class GatewayPriceClient(Protocol):
    async def update_price(
        self, *, seller_id: int, item_id: str, new_price: Decimal, idempotency_key: str
    ) -> tuple[int, int]: ...


class IdempotencyStoreLike(Protocol):
    async def is_duplicate(self, key: str) -> bool: ...

    async def mark_processed(self, key: str) -> None: ...


class RepricerEventHandlerLike(Protocol):
    async def handle(self, event: RepricerEvent) -> str: ...


class RepricerEventHandler:
    def __init__(
        self,
        *,
        db: Any,
        gateway_client: GatewayPriceClient,
        idempotency_store: IdempotencyStoreLike,
    ) -> None:
        self._db = db
        self._gateway = gateway_client
        self._idempotency = idempotency_store

    async def handle(self, event: RepricerEvent) -> str:
        if await self._idempotency.is_duplicate(event.idempotency_key):
            return "duplicate"

        item_id = _item_id_from_resource(event.resource)
        item_doc = await self._db["items"].find_one(
            {"_id": item_id, "seller_id": str(event.seller_id)}
        )
        if item_doc is None:
            return "item_missing"
        item = Item.model_validate(item_doc)
        rule_doc = await self._db["repricer_rules"].find_one(
            {"seller_id": str(event.seller_id), "item_id": item.id, "active": True}
        )
        if rule_doc is None:
            return "rule_missing"
        rule = RepricerRule.model_validate(rule_doc)
        decision = evaluate_rule(rule, current_price=item.price, buybox_price=event.buybox_price)

        if isinstance(decision, SetPrice):
            gateway_status, latency_ms = await self._gateway.update_price(
                seller_id=event.seller_id,
                item_id=item.id,
                new_price=decision.new_price,
                idempotency_key=event.idempotency_key,
            )
            if gateway_status == 429:
                raise RuntimeError("gateway_backpressure")
            await self._write_history(
                event=event,
                item=item,
                new_price=decision.new_price,
                reason=decision.reason,
                gateway_status=gateway_status,
                latency_ms=latency_ms,
            )
            await self._idempotency.mark_processed(event.idempotency_key)
            return "set_price"

        reason = decision.reason
        await self._write_history(
            event=event,
            item=item,
            new_price=item.price,
            reason=reason,
            gateway_status=None,
            latency_ms=None,
        )
        await self._idempotency.mark_processed(event.idempotency_key)
        return "no_action"

    async def _write_history(
        self,
        *,
        event: RepricerEvent,
        item: Item,
        new_price: Decimal,
        reason: str,
        gateway_status: int | None,
        latency_ms: int | None,
    ) -> None:
        await self._db["repricer_history"].insert_one(
            {
                "seller_id": str(event.seller_id),
                "item_id": item.id,
                "old_price": item.price,
                "new_price": new_price,
                "reason": reason,
                "applied_at": datetime.now(UTC),
                "gateway_status": gateway_status,
                "gateway_latency_ms": latency_ms,
                "event_id": event.event_id,
                "schema_version": 1,
            }
        )


@dataclass(frozen=True)
class RepricerAmqpConsumerConfig:
    rabbitmq_url: str
    exchange_name: str = MELI_EVENTS_EXCHANGE
    queue_name: str = REPRICER_ITEMS_QUEUE
    dead_letter_exchange: str = REPRICER_ITEMS_DLX
    delivery_limit: int = REPRICER_DELIVERY_LIMIT
    prefetch_count: int = DEFAULT_PREFETCH_COUNT
    routing_keys: tuple[str, ...] = ("items.*", "items.price_updated")


class RepricerAmqpConsumerRunner:
    """Transport wrapper that feeds RabbitMQ messages into RepricerEventHandler.

    The deterministic handler owns business behavior; this runner owns AMQP topology,
    envelope decoding, and ack/nack semantics.
    """

    exchange_type_topic = aio_pika.ExchangeType.TOPIC

    def __init__(
        self,
        *,
        rabbitmq_url: str,
        handler: RepricerEventHandlerLike,
        manifest_path: str | Path | None = None,
        queue_name: str = REPRICER_ITEMS_QUEUE,
        exchange_name: str = MELI_EVENTS_EXCHANGE,
        dead_letter_exchange: str = REPRICER_ITEMS_DLX,
        delivery_limit: int = REPRICER_DELIVERY_LIMIT,
        prefetch_count: int = DEFAULT_PREFETCH_COUNT,
    ) -> None:
        routing_keys = _routing_keys_from_manifest(manifest_path)
        self.config = RepricerAmqpConsumerConfig(
            rabbitmq_url=rabbitmq_url,
            exchange_name=exchange_name,
            queue_name=queue_name,
            dead_letter_exchange=dead_letter_exchange,
            delivery_limit=delivery_limit,
            prefetch_count=prefetch_count,
            routing_keys=routing_keys,
        )
        self._handler = handler
        self._connection: Any | None = None

    async def start(self) -> None:
        connection = await aio_pika.connect_robust(self.config.rabbitmq_url)
        self._connection = connection
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=self.config.prefetch_count)
        exchange = await channel.declare_exchange(
            self.config.exchange_name,
            aio_pika.ExchangeType.TOPIC,
            durable=True,
        )
        queue = await channel.declare_queue(
            self.config.queue_name,
            durable=True,
            arguments={
                "x-dead-letter-exchange": self.config.dead_letter_exchange,
                "x-delivery-limit": self.config.delivery_limit,
            },
        )
        for routing_key in self.config.routing_keys:
            await queue.bind(exchange, routing_key=routing_key)
        await queue.consume(self.handle_message)

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None

    async def handle_message(self, message: Any) -> None:
        try:
            event = _event_from_message(message)
            await self._handler.handle(event)
        except RuntimeError:
            await message.nack(requeue=True)
            return
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
            await message.nack(requeue=False)
            return
        await message.ack()


def _item_id_from_resource(resource: str) -> str:
    parts = [part for part in resource.split("/") if part]
    if len(parts) < 2 or parts[0] != "items":
        msg = f"unsupported repricer resource: {resource}"
        raise ValueError(msg)
    return parts[1]


def _routing_keys_from_manifest(manifest_path: str | Path | None) -> tuple[str, ...]:
    if manifest_path is None:
        return ("items.*", "items.price_updated")
    manifest = validate_manifest(manifest_path)
    return tuple(manifest.routing_keys)


def _event_from_message(message: Any) -> RepricerEvent:
    payload = json.loads(message.body.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("repricer event payload must be a JSON object")
    idempotency_key = _idempotency_key(message, payload)
    buybox_price = payload.get("buybox_price")
    return RepricerEvent(
        event_id=str(payload["event_id"]),
        event_type=str(payload["event_type"]),
        seller_id=int(payload["seller_id"]),
        resource=str(payload["resource"]),
        idempotency_key=idempotency_key,
        buybox_price=Decimal(str(buybox_price)) if buybox_price is not None else None,
    )


def _idempotency_key(message: Any, payload: dict[str, Any]) -> str:
    headers = getattr(message, "headers", None)
    if isinstance(headers, dict):
        header_value = headers.get("idempotency_key")
        if header_value is not None:
            return str(header_value)
    payload_value = payload.get("idempotency_key")
    if payload_value is not None:
        return str(payload_value)
    return str(payload["event_id"])
