from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol, cast

import aio_pika
import httpx
import structlog
from motor.motor_asyncio import AsyncIOMotorClient

from zeler_platform_core.auth.meli_gateway_auth import MeliGatewayAuth
from zeler_platform_core.clients.meli_gateway_client import GatewayRateLimitError, MeliGatewayClient
from zeler_platform_core.events.idempotency import IdempotencyStore as CoreIdempotencyStore
from zeler_platform_core.models import Item, RepricerRule
from zeler_platform_core.runtime.manifest import validate_manifest
from zeler_repricer.engine import SetPrice, evaluate_rule

MELI_EVENTS_EXCHANGE = "meli.events"
REPRICER_ITEMS_QUEUE = "zeler.repricer.items"
REPRICER_ITEMS_DLX = "zeler.repricer.items.dlx"
REPRICER_DELIVERY_LIMIT = 5
DEFAULT_PREFETCH_COUNT = 10
MISSING_RABBITMQ_URL_MESSAGE = "error: RABBITMQ_URL is required"
MISSING_MONGO_URI_MESSAGE = "error: MONGO_URI is required"
MISSING_MONGO_DB_MESSAGE = "error: MONGO_DB is required"
DEFAULT_GATEWAY_BASE_URL = "http://gateway:8080/proxy/meli"
PERMANENT_HTTP_STATUS_CODES = {401, 403, 404, 422}
RETRIABLE_HTTP_STATUS_CODES = {408, 429}

logger = structlog.get_logger(__name__)


class RetryLimitExceededError(Exception):
    """Raised internally to describe exhausted broker retry budget."""


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


class RepricerGatewayClient:
    # DEPRECATED: see core/clients/meli_gateway_client.py
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

    async def update_price(
        self, *, seller_id: int, item_id: str, new_price: Decimal, idempotency_key: str
    ) -> tuple[int, int]:
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(transport=self._transport) as client:
                response = await client.post(
                    f"{self._base_url}/items/{item_id}/prices",
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "X-Seller-Id": str(seller_id),
                        "Idempotency-Key": idempotency_key,
                    },
                    json={"price": str(new_price)},
                )
        except httpx.TimeoutException as exc:
            msg = "gateway request timed out"
            raise RuntimeError(msg) from exc
        latency_ms = int((time.perf_counter() - started) * 1000)
        return response.status_code, latency_ms


class RepricerMeliGatewayPriceClient:
    def __init__(
        self,
        *,
        base_url: str,
        auth: MeliGatewayAuth,
        http_client: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._client = MeliGatewayClient(base_url, auth, http_client=http_client)
        self._clock = clock

    async def update_price(
        self, *, seller_id: int, item_id: str, new_price: Decimal, idempotency_key: str
    ) -> tuple[int, int]:
        started = self._clock()
        response = await self._client.request(
            method="POST",
            seller_id=seller_id,  # type: ignore[arg-type]
            path=f"/items/{item_id}/prices",
            json={"price": str(new_price)},
        )
        latency_ms = int((self._clock() - started) * 1000)
        return response.status_code, latency_ms


def make_meli_gateway_price_client(
    *,
    module_id: str = "repricer",
    base_url: str = DEFAULT_GATEWAY_BASE_URL,
    kms_client: Any,
) -> RepricerMeliGatewayPriceClient:
    return RepricerMeliGatewayPriceClient(
        base_url=base_url,
        auth=MeliGatewayAuth(module_id, kms_client),
    )


class IdempotencyStoreLike(Protocol):
    async def is_duplicate(self, key: str) -> bool: ...

    async def mark_processed(self, key: str) -> None: ...


class CoreIdempotencyStoreLike(Protocol):
    async def is_duplicate(self, key: str) -> bool: ...

    async def mark_processed(self, key: str, *, module_id: str) -> bool: ...


class _RepricerIdempotencyAdapter:
    def __init__(self, store: CoreIdempotencyStoreLike) -> None:
        self._store = store

    async def is_duplicate(self, key: str) -> bool:
        return await self._store.is_duplicate(key)

    async def mark_processed(self, key: str) -> None:
        await self._store.mark_processed(key, module_id="repricer")


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
        death_count = _x_death_count(message, queue_name=self.config.queue_name)
        event: RepricerEvent | None = None
        if death_count >= self.config.delivery_limit:
            event = _event_context_from_message(message)
            _log_message_dlq(event, death_count, RetryLimitExceededError())
            await message.nack(requeue=False)
            return

        try:
            event = _event_from_message(message)
            await self._handler.handle(event)
        except GatewayRateLimitError as exc:
            _log_message_requeued(
                event,
                death_count + 1,
                exc,
                retry_after=exc.retry_after_seconds,
            )
            await asyncio.sleep(exc.retry_after_seconds)
            await message.nack(requeue=True)
            return
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code in PERMANENT_HTTP_STATUS_CODES:
                _log_message_dlq(event, death_count + 1, exc, status_code=status_code)
                await message.nack(requeue=False)
                return
            if status_code >= 500 or status_code in RETRIABLE_HTTP_STATUS_CODES:
                _log_message_requeued(event, death_count + 1, exc, status_code=status_code)
                await message.nack(requeue=True)
                return
            raise
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            _log_message_requeued(event, death_count + 1, exc)
            await message.nack(requeue=True)
            return
        except RuntimeError as exc:
            _log_message_dlq(event, death_count + 1, exc, exc_info=True)
            await message.nack(requeue=False)
            return
        except json.JSONDecodeError as exc:
            _log_message_dlq(event, death_count + 1, exc)
            await message.nack(requeue=False)
            return
        except (KeyError, TypeError, ValueError, UnicodeDecodeError) as exc:
            _log_message_dlq(event, death_count + 1, exc)
            await message.nack(requeue=False)
            return
        except Exception as exc:  # noqa: BLE001 - final AMQP safety net required by spec.
            _log_message_dlq(event, death_count + 1, exc, exc_info=True)
            await message.nack(requeue=False)
            return
        _log_message_ack(event, death_count + 1)
        await message.ack()


def _log_message_dlq(
    event: RepricerEvent | None,
    attempts: int,
    error: BaseException,
    *,
    status_code: int | None = None,
    exc_info: bool = False,
) -> None:
    fields: dict[str, Any] = {
        "event_id": event.event_id if event is not None else None,
        "seller_id": event.seller_id if event is not None else None,
        "resource_path": event.resource if event is not None else None,
        "attempts": attempts,
        "error_type": type(error).__name__,
    }
    if status_code is not None:
        fields["status_code"] = status_code
    if exc_info:
        fields["exc_info"] = True
    logger.error("worker.message.dlq", **fields)


def _log_message_requeued(
    event: RepricerEvent | None,
    attempt: int,
    error: BaseException,
    *,
    status_code: int | None = None,
    retry_after: int | None = None,
) -> None:
    fields: dict[str, Any] = {
        "event_id": event.event_id if event is not None else None,
        "seller_id": event.seller_id if event is not None else None,
        "resource_path": event.resource if event is not None else None,
        "attempt": attempt,
        "error_type": type(error).__name__,
    }
    if status_code is not None:
        fields["status_code"] = status_code
    if retry_after is not None:
        fields["retry_after"] = retry_after
    logger.warning("worker.message.requeued", **fields)


def _log_message_ack(event: RepricerEvent | None, attempt: int) -> None:
    logger.info(
        "worker.message.ack",
        event_id=event.event_id if event is not None else None,
        seller_id=event.seller_id if event is not None else None,
        resource_path=event.resource if event is not None else None,
        attempt=attempt,
    )


def _x_death_count(message: Any, *, queue_name: str) -> int:
    death_history = message.headers.get("x-death", []) if message.headers else []
    if not isinstance(death_history, list):
        return 0
    for death in death_history:
        if not isinstance(death, dict):
            continue
        if death.get("queue") in (queue_name, None):
            count = death.get("count", 0)
            return int(count) if isinstance(count, int) else 0
    return 0


def _event_context_from_message(message: Any) -> RepricerEvent | None:
    try:
        return _event_from_message(message)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _item_id_from_resource(resource: str) -> str:
    parts = [part for part in resource.split("/") if part]
    for index, part in enumerate(parts):
        if part == "items" and index + 1 < len(parts):
            return parts[index + 1]
    msg = f"unsupported repricer resource: {resource}"
    raise ValueError(msg)


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
    from google.cloud import kms

    kms_client = kms.KeyManagementServiceClient()
    gateway_client = make_meli_gateway_price_client(
        base_url=os.environ.get("GATEWAY_BASE_URL", DEFAULT_GATEWAY_BASE_URL),
        kms_client=kms_client,
    )
    idempotency_store = _RepricerIdempotencyAdapter(
        CoreIdempotencyStore(cast(Any, db["processed_events"]))
    )
    handler = RepricerEventHandler(
        db=db,
        gateway_client=gateway_client,
        idempotency_store=idempotency_store,
    )
    runner = RepricerAmqpConsumerRunner(
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
