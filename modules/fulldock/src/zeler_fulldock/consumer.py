from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast

import aio_pika
import httpx
from motor.motor_asyncio import AsyncIOMotorClient

from zeler_platform_core.events.idempotency import IdempotencyStore as CoreIdempotencyStore
from zeler_platform_core.runtime.manifest import validate_manifest

MELI_EVENTS_EXCHANGE = "meli.events"
FULLDOCK_EVENTS_QUEUE = "zeler.fulldock.events"
FULLDOCK_EVENTS_DLX = "zeler.fulldock.events.dlx"
FULLDOCK_DELIVERY_LIMIT = 5
DEFAULT_PREFETCH_COUNT = 10
FULLDOCK_DEFAULT_ROUTING_KEYS = ("items.*", "shipments.*")
MISSING_RABBITMQ_URL_MESSAGE = "error: RABBITMQ_URL is required"
MISSING_MONGO_URI_MESSAGE = "error: MONGO_URI is required"
MISSING_MONGO_DB_MESSAGE = "error: MONGO_DB is required"


@dataclass(frozen=True)
class FulldockEvent:
    event_id: str
    event_type: str
    seller_id: int
    resource: str
    idempotency_key: str


class GatewayClient(Protocol):
    async def request(
        self, method: str, path: str, *, seller_id: str, json: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...


class FulldockGatewayClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._transport = transport

    async def request(
        self, method: str, path: str, *, seller_id: str, json: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        normalized_path = path if path.startswith("/") else f"/{path}"
        async with httpx.AsyncClient(transport=self._transport) as client:
            response = await client.request(
                method,
                f"{self._base_url}{normalized_path}",
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "X-Seller-Id": seller_id,
                },
                json=json,
            )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("gateway response must be a JSON object")
        return payload


class IdempotencyStore(Protocol):
    async def is_duplicate(self, key: str) -> bool: ...

    async def mark_processed(self, key: str) -> None: ...


class FulldockEventHandlerLike(Protocol):
    async def handle(self, event: FulldockEvent) -> str: ...


@dataclass(frozen=True)
class FulldockAmqpConsumerConfig:
    rabbitmq_url: str
    exchange_name: str = MELI_EVENTS_EXCHANGE
    queue_name: str = FULLDOCK_EVENTS_QUEUE
    dead_letter_exchange: str = FULLDOCK_EVENTS_DLX
    delivery_limit: int = FULLDOCK_DELIVERY_LIMIT
    prefetch_count: int = DEFAULT_PREFETCH_COUNT
    routing_keys: tuple[str, ...] = FULLDOCK_DEFAULT_ROUTING_KEYS


class FulldockAmqpConsumerRunner:
    exchange_type_topic = aio_pika.ExchangeType.TOPIC

    def __init__(
        self,
        *,
        rabbitmq_url: str,
        handler: FulldockEventHandlerLike,
        manifest_path: str | Path | None = None,
        queue_name: str = FULLDOCK_EVENTS_QUEUE,
        exchange_name: str = MELI_EVENTS_EXCHANGE,
        dead_letter_exchange: str = FULLDOCK_EVENTS_DLX,
        delivery_limit: int = FULLDOCK_DELIVERY_LIMIT,
        prefetch_count: int = DEFAULT_PREFETCH_COUNT,
    ) -> None:
        routing_keys = _fulldock_routing_keys_from_manifest(manifest_path)
        self.config = FulldockAmqpConsumerConfig(
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
            event = _fulldock_event_from_message(message)
            await self._handler.handle(event)
        except RuntimeError:
            await message.nack(requeue=True)
            return
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
            await message.nack(requeue=False)
            return
        await message.ack()


def _fulldock_routing_keys_from_manifest(manifest_path: str | Path | None) -> tuple[str, ...]:
    if manifest_path is None:
        return FULLDOCK_DEFAULT_ROUTING_KEYS
    manifest = validate_manifest(manifest_path)
    return tuple(manifest.routing_keys)


def _fulldock_event_from_message(message: Any) -> FulldockEvent:
    payload = json.loads(message.body.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("fulldock event payload must be a JSON object")
    return FulldockEvent(
        event_id=str(payload["event_id"]),
        event_type=str(payload["event_type"]),
        seller_id=int(payload["seller_id"]),
        resource=str(payload["resource"]),
        idempotency_key=_fulldock_idempotency_key(message, payload),
    )


def _fulldock_idempotency_key(message: Any, payload: dict[str, Any]) -> str:
    headers = getattr(message, "headers", None)
    if isinstance(headers, dict):
        header_value = headers.get("idempotency_key")
        if header_value is not None:
            return str(header_value)
    payload_value = payload.get("idempotency_key")
    if payload_value is not None:
        return str(payload_value)
    return str(payload["event_id"])


class CoreIdempotencyStoreLike(Protocol):
    async def is_duplicate(self, key: str) -> bool: ...

    async def mark_processed(self, key: str, *, module_id: str) -> bool: ...


class _FulldockIdempotencyAdapter:
    def __init__(self, store: CoreIdempotencyStoreLike) -> None:
        self._store = store

    async def is_duplicate(self, key: str) -> bool:
        return await self._store.is_duplicate(key)

    async def mark_processed(self, key: str) -> None:
        await self._store.mark_processed(key, module_id="fulldock")


class FulldockEventHandler:
    def __init__(
        self,
        *,
        db: Any,
        gateway_client: GatewayClient,
        idempotency_store: IdempotencyStore,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db
        self._gateway_client = gateway_client
        self._idempotency_store = idempotency_store
        self._clock = clock or (lambda: datetime.now(UTC))

    async def handle(self, event: FulldockEvent) -> str:
        if await self._idempotency_store.is_duplicate(event.idempotency_key):
            return "duplicate"

        seller_id = str(event.seller_id)
        resource = await self._gateway_client.request(
            "GET", event.resource, seller_id=seller_id, json=None
        )
        item_ids = item_ids_from_event_resource(event.event_type, event.resource, resource)
        rules = await self._rules_for_items(seller_id=seller_id, item_ids=item_ids)

        if not rules:
            await self._record_history(
                event=event,
                item_id=item_ids[0] if item_ids else "unknown",
                outcome="no_rule",
                rule_id=None,
                stock_locations=[],
            )
            await self._idempotency_store.mark_processed(event.idempotency_key)
            return "no_rule"

        for rule in rules:
            item_id = str(rule["item_id"])
            stock_locations = normalize_stock_locations(rule.get("stock_locations", []))
            await self._gateway_client.request(
                "PUT",
                f"/items/{item_id}/stock_locations",
                seller_id=seller_id,
                json={"locations": stock_locations},
            )
            await self._record_history(
                event=event,
                item_id=item_id,
                outcome="updated",
                rule_id=str(rule["_id"]),
                stock_locations=stock_locations,
            )

        await self._idempotency_store.mark_processed(event.idempotency_key)
        return "updated"

    async def _rules_for_items(
        self, *, seller_id: str, item_ids: list[str]
    ) -> list[dict[str, Any]]:
        rules: list[dict[str, Any]] = []
        for item_id in item_ids:
            found = (
                await self._db["fulldock_inventory_rules"]
                .find({"seller_id": seller_id, "item_id": item_id, "enabled": True})
                .to_list(length=100)
            )
            rules.extend(found)
        return rules

    async def _record_history(
        self,
        *,
        event: FulldockEvent,
        item_id: str,
        outcome: str,
        rule_id: str | None,
        stock_locations: list[dict[str, Any]],
    ) -> None:
        created_at = self._clock()
        await self._db["fulldock_history"].insert_one(
            {
                "_id": f"fulldock-history-{event.idempotency_key}-{item_id}",
                "seller_id": str(event.seller_id),
                "event_id": event.event_id,
                "idempotency_key": event.idempotency_key,
                "event_type": event.event_type,
                "item_id": item_id,
                "outcome": outcome,
                "rule_id": rule_id,
                "stock_locations": stock_locations,
                "created_at": created_at,
                "schema_version": 1,
            }
        )


def item_ids_from_event_resource(
    event_type: str, resource_path: str, resource: dict[str, Any]
) -> list[str]:
    if event_type.startswith("shipments."):
        raw_items = resource.get("items", resource.get("order_items", []))
        if isinstance(raw_items, list):
            return [item_id for item in raw_items if (item_id := item_id_from_payload(item))]
        return []
    item_id = item_id_from_payload(resource) or resource_path.rstrip("/").split("/")[-1]
    return [item_id]


def item_id_from_payload(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("item_id", "id"):
        value = payload.get(key)
        if value is not None:
            return str(value)
    nested_item = payload.get("item")
    if isinstance(nested_item, dict):
        value = nested_item.get("id") or nested_item.get("item_id")
        if value is not None:
            return str(value)
    return None


def normalize_stock_locations(raw_locations: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_locations, list):
        return []
    locations: list[dict[str, Any]] = []
    for location in raw_locations:
        if isinstance(location, dict):
            locations.append(
                {
                    "location_id": str(location["location_id"]),
                    "quantity": int(location["quantity"]),
                }
            )
    return locations


async def run() -> None:
    rabbitmq_url = os.environ.get("RABBITMQ_URL")
    mongo_uri = os.environ.get("MONGO_URI")
    mongo_db = os.environ.get("MONGO_DB")
    for value, message in (
        (rabbitmq_url, MISSING_RABBITMQ_URL_MESSAGE),
        (mongo_uri, MISSING_MONGO_URI_MESSAGE),
        (mongo_db, MISSING_MONGO_DB_MESSAGE),
    ):
        if not value:
            print(message, file=sys.stderr)
            sys.exit(2)
    if rabbitmq_url is None or mongo_uri is None or mongo_db is None:
        raise RuntimeError("environment validation failed")

    mongo_client: AsyncIOMotorClient[Any] = AsyncIOMotorClient(
        mongo_uri,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
        socketTimeoutMS=30000,
    )
    db = mongo_client[mongo_db]
    manifest_path = Path(__file__).resolve().parents[2] / "manifest.yaml"
    handler = FulldockEventHandler(
        db=db,
        gateway_client=FulldockGatewayClient(
            base_url=os.environ.get("GATEWAY_BASE_URL", "http://gateway"),
            token=os.environ.get("GATEWAY_TOKEN", ""),
        ),
        idempotency_store=_FulldockIdempotencyAdapter(
            CoreIdempotencyStore(cast(Any, db["processed_events"]))
        ),
    )
    runner = FulldockAmqpConsumerRunner(
        rabbitmq_url=rabbitmq_url,
        handler=handler,
        manifest_path=manifest_path,
    )
    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, shutdown_event.set)

    await runner.start()
    try:
        await shutdown_event.wait()
    finally:
        await runner.close()
        mongo_client.close()
