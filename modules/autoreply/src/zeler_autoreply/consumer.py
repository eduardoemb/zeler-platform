from __future__ import annotations

import asyncio
import json
import os
import re
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
AUTOREPLY_EVENTS_QUEUE = "zeler.autoreply.events"
AUTOREPLY_EVENTS_DLX = "zeler.autoreply.events.dlx"
AUTOREPLY_DELIVERY_LIMIT = 5
DEFAULT_PREFETCH_COUNT = 10
AUTOREPLY_DEFAULT_ROUTING_KEYS = ("questions.new", "messages.new")
MISSING_RABBITMQ_URL_MESSAGE = "error: RABBITMQ_URL is required"
MISSING_MONGO_URI_MESSAGE = "error: MONGO_URI is required"
MISSING_MONGO_DB_MESSAGE = "error: MONGO_DB is required"


@dataclass(frozen=True)
class AutoreplyEvent:
    event_id: str
    event_type: str
    seller_id: int
    resource: str
    idempotency_key: str


class GatewayClient(Protocol):
    async def request(
        self, method: str, path: str, *, seller_id: str, json: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...


class AutoreplyGatewayClient:
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


class AutoreplyEventHandlerLike(Protocol):
    async def handle(self, event: AutoreplyEvent) -> str: ...


@dataclass(frozen=True)
class AutoreplyAmqpConsumerConfig:
    rabbitmq_url: str
    exchange_name: str = MELI_EVENTS_EXCHANGE
    queue_name: str = AUTOREPLY_EVENTS_QUEUE
    dead_letter_exchange: str = AUTOREPLY_EVENTS_DLX
    delivery_limit: int = AUTOREPLY_DELIVERY_LIMIT
    prefetch_count: int = DEFAULT_PREFETCH_COUNT
    routing_keys: tuple[str, ...] = AUTOREPLY_DEFAULT_ROUTING_KEYS


class AutoreplyAmqpConsumerRunner:
    exchange_type_topic = aio_pika.ExchangeType.TOPIC

    def __init__(
        self,
        *,
        rabbitmq_url: str,
        handler: AutoreplyEventHandlerLike,
        manifest_path: str | Path | None = None,
        queue_name: str = AUTOREPLY_EVENTS_QUEUE,
        exchange_name: str = MELI_EVENTS_EXCHANGE,
        dead_letter_exchange: str = AUTOREPLY_EVENTS_DLX,
        delivery_limit: int = AUTOREPLY_DELIVERY_LIMIT,
        prefetch_count: int = DEFAULT_PREFETCH_COUNT,
    ) -> None:
        routing_keys = _autoreply_routing_keys_from_manifest(manifest_path)
        self.config = AutoreplyAmqpConsumerConfig(
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
        death_history = message.headers.get("x-death", []) if message.headers else []
        death_count = death_history[0].get("count", 0) if death_history else 0
        if death_count >= self.config.delivery_limit:
            await message.nack(requeue=False)
            return

        try:
            event = _autoreply_event_from_message(message)
            await self._handler.handle(event)
        except RuntimeError:
            await message.nack(requeue=True)
            return
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
            await message.nack(requeue=False)
            return
        await message.ack()


def _autoreply_routing_keys_from_manifest(manifest_path: str | Path | None) -> tuple[str, ...]:
    if manifest_path is None:
        return AUTOREPLY_DEFAULT_ROUTING_KEYS
    manifest = validate_manifest(manifest_path)
    return tuple(manifest.routing_keys)


def _autoreply_event_from_message(message: Any) -> AutoreplyEvent:
    payload = json.loads(message.body.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("autoreply event payload must be a JSON object")
    return AutoreplyEvent(
        event_id=str(payload["event_id"]),
        event_type=str(payload["event_type"]),
        seller_id=int(payload["seller_id"]),
        resource=str(payload["resource"]),
        idempotency_key=_autoreply_idempotency_key(message, payload),
    )


def _autoreply_idempotency_key(message: Any, payload: dict[str, Any]) -> str:
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


class _AutoreplyIdempotencyAdapter:
    def __init__(self, store: CoreIdempotencyStoreLike) -> None:
        self._store = store

    async def is_duplicate(self, key: str) -> bool:
        return await self._store.is_duplicate(key)

    async def mark_processed(self, key: str) -> None:
        await self._store.mark_processed(key, module_id="autoreply")


class AutoreplyEventHandler:
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

    async def handle(self, event: AutoreplyEvent) -> str:
        if await self._idempotency_store.is_duplicate(event.idempotency_key):
            return "duplicate"

        seller_id = str(event.seller_id)
        resource = await self._gateway_client.request(
            "GET", event.resource, seller_id=seller_id, json=None
        )
        templates = (
            await self._db["autoreply_templates"]
            .find({"seller_id": seller_id, "enabled": True})
            .to_list(length=100)
        )
        matched = select_matching_template(str(resource.get("text", "")), templates)
        resource_type = resource_type_from_event(event.event_type)
        resource_id = resource_id_from_resource(resource)

        if matched is None:
            await self._record_history(
                event=event,
                resource_type=resource_type,
                resource_id=resource_id,
                outcome="no_match",
                template_id=None,
                answer_payload={},
            )
            await self._idempotency_store.mark_processed(event.idempotency_key)
            return "no_match"

        answer_payload = build_answer_payload(
            resource_type=resource_type,
            resource_id=resource_id,
            answer_text=str(matched["answer_text"]),
        )
        await self._gateway_client.request(
            "POST",
            "/answers",
            seller_id=seller_id,
            json=answer_payload,
        )
        await self._record_history(
            event=event,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome="answered",
            template_id=str(matched["_id"]),
            answer_payload=answer_payload,
        )
        await self._idempotency_store.mark_processed(event.idempotency_key)
        return "answered"

    async def _record_history(
        self,
        *,
        event: AutoreplyEvent,
        resource_type: str,
        resource_id: str,
        outcome: str,
        template_id: str | None,
        answer_payload: dict[str, Any],
    ) -> None:
        created_at = self._clock()
        await self._db["autoreply_history"].insert_one(
            {
                "_id": f"autoreply-history-{event.idempotency_key}",
                "seller_id": str(event.seller_id),
                "event_id": event.event_id,
                "idempotency_key": event.idempotency_key,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "outcome": outcome,
                "template_id": template_id,
                "answer_payload": answer_payload,
                "created_at": created_at,
                "schema_version": 1,
            }
        )


def select_matching_template(text: str, templates: list[dict[str, Any]]) -> dict[str, Any] | None:
    for template in templates:
        if template_matches(text, str(template["match_type"]), str(template["pattern"])):
            return template
    return None


def template_matches(text: str, match_type: str, pattern: str) -> bool:
    if match_type == "keyword":
        return pattern.casefold() in text.casefold()
    if match_type == "regex":
        return re.search(pattern, text, flags=re.IGNORECASE) is not None
    return False


def resource_type_from_event(event_type: str) -> str:
    if event_type.startswith("messages."):
        return "message"
    return "question"


def resource_id_from_resource(resource: dict[str, Any]) -> str:
    value = resource.get("id", resource.get("_id"))
    return str(value)


def build_answer_payload(
    *, resource_type: str, resource_id: str, answer_text: str
) -> dict[str, Any]:
    key = "message_id" if resource_type == "message" else "question_id"
    return {key: resource_id, "text": answer_text}


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
    handler = AutoreplyEventHandler(
        db=db,
        gateway_client=AutoreplyGatewayClient(
            base_url=os.environ.get("GATEWAY_BASE_URL", "http://gateway"),
            token=os.environ.get("GATEWAY_TOKEN", ""),
        ),
        idempotency_store=_AutoreplyIdempotencyAdapter(
            CoreIdempotencyStore(cast(Any, db["processed_events"]))
        ),
    )
    runner = AutoreplyAmqpConsumerRunner(
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
