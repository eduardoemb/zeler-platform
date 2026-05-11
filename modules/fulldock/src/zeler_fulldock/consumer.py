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
from pathlib import Path
from typing import Any, Protocol, cast

import aio_pika
import httpx
import structlog
from motor.motor_asyncio import AsyncIOMotorClient

from zeler_platform_core.auth.meli_gateway_auth import MeliGatewayAuth
from zeler_platform_core.clients.meli_gateway_client import GatewayRateLimitError, MeliGatewayClient
from zeler_platform_core.events.idempotency import IdempotencyStore as CoreIdempotencyStore
from zeler_platform_core.runtime.manifest import validate_manifest
from zeler_platform_core.runtime.registration import register_module
from zeler_platform_core.runtime.worker_health import WorkerHealthSidecar

MELI_EVENTS_EXCHANGE = "meli.events"
FULLDOCK_EVENTS_QUEUE = "zeler.fulldock.events"
FULLDOCK_EVENTS_DLQ = f"{FULLDOCK_EVENTS_QUEUE}.dlq"
FULLDOCK_EVENTS_DLX = "zeler.fulldock.events.dlx"
FULLDOCK_EVENTS_DEAD_LETTER_ROUTING_KEY = FULLDOCK_EVENTS_DLQ
FULLDOCK_DELIVERY_LIMIT = 5
DEFAULT_PREFETCH_COUNT = 10
FULLDOCK_DEFAULT_ROUTING_KEYS = ("shipments.*", "stock_locations.*")
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


class FulldockMeliGatewayClient:
    def __init__(
        self,
        *,
        base_url: str,
        auth: MeliGatewayAuth,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._client = MeliGatewayClient(base_url, auth, http_client=http_client)

    async def request(
        self, method: str, path: str, *, seller_id: str, json: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        response = await self._client.request(
            method=method,
            seller_id=int(seller_id),  # type: ignore[arg-type]
            path=path,
            json=json,
        )
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("gateway response must be a JSON object")
        return payload


def make_meli_gateway_client(
    *,
    module_id: str = "fulldock",
    base_url: str = DEFAULT_GATEWAY_BASE_URL,
    kms_client: Any,
) -> FulldockMeliGatewayClient:
    return FulldockMeliGatewayClient(
        base_url=base_url,
        auth=MeliGatewayAuth(module_id, kms_client),
    )


class IdempotencyStore(Protocol):
    async def is_duplicate(self, key: str) -> bool: ...

    async def mark_processed(self, key: str) -> None: ...


class FulldockEventHandlerLike(Protocol):
    async def handle(self, event: FulldockEvent) -> str: ...


AccountStatusSource = Callable[[int], Any]


@dataclass(frozen=True)
class FulldockAmqpConsumerConfig:
    rabbitmq_url: str
    exchange_name: str = MELI_EVENTS_EXCHANGE
    queue_name: str = FULLDOCK_EVENTS_QUEUE
    dead_letter_queue: str = FULLDOCK_EVENTS_DLQ
    dead_letter_exchange: str = FULLDOCK_EVENTS_DLX
    dead_letter_routing_key: str = FULLDOCK_EVENTS_DEAD_LETTER_ROUTING_KEY
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
        dead_letter_queue: str = FULLDOCK_EVENTS_DLQ,
        exchange_name: str = MELI_EVENTS_EXCHANGE,
        dead_letter_exchange: str = FULLDOCK_EVENTS_DLX,
        dead_letter_routing_key: str = FULLDOCK_EVENTS_DEAD_LETTER_ROUTING_KEY,
        delivery_limit: int = FULLDOCK_DELIVERY_LIMIT,
        prefetch_count: int = DEFAULT_PREFETCH_COUNT,
        retry_delay_publisher: Any | None = None,
        account_status_source: AccountStatusSource | None = None,
    ) -> None:
        routing_keys = _fulldock_routing_keys_from_manifest(manifest_path)
        self.config = FulldockAmqpConsumerConfig(
            rabbitmq_url=rabbitmq_url,
            exchange_name=exchange_name,
            queue_name=queue_name,
            dead_letter_queue=dead_letter_queue,
            dead_letter_exchange=dead_letter_exchange,
            dead_letter_routing_key=dead_letter_routing_key,
            delivery_limit=delivery_limit,
            prefetch_count=prefetch_count,
            routing_keys=routing_keys,
        )
        self._handler = handler
        self._retry_delay_publisher = retry_delay_publisher
        self._account_status_source = account_status_source
        self._account_status_cache: dict[int, tuple[str | None, float]] = {}
        self._connection: Any | None = None
        self.is_ready = False
        self.last_heartbeat_at: datetime | None = None

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
        dead_letter_exchange = await channel.declare_exchange(
            self.config.dead_letter_exchange,
            aio_pika.ExchangeType.DIRECT,
            durable=True,
        )
        dead_letter_queue = await channel.declare_queue(
            self.config.dead_letter_queue,
            durable=True,
            arguments={},
        )
        await dead_letter_queue.bind(
            dead_letter_exchange,
            routing_key=self.config.dead_letter_routing_key,
        )
        queue = await channel.declare_queue(
            self.config.queue_name,
            durable=True,
            arguments={
                "x-dead-letter-exchange": self.config.dead_letter_exchange,
                "x-dead-letter-routing-key": self.config.dead_letter_routing_key,
            },
        )
        for routing_key in self.config.routing_keys:
            await queue.bind(exchange, routing_key=routing_key)
        await queue.consume(self.handle_message)
        self.is_ready = True

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None
        self.is_ready = False

    async def handle_message(self, message: Any) -> None:
        self.last_heartbeat_at = datetime.now(UTC)
        death_count = _x_death_count(message, queue_name=self.config.queue_name)
        event: FulldockEvent | None = None
        if death_count >= self.config.delivery_limit:
            event = _event_context_from_message(message)
            _log_message_dlq(event, death_count, RetryLimitExceededError())
            await message.nack(requeue=False)
            return

        try:
            event = _fulldock_event_from_message(message)
            if not _is_supported_fulldock_event(event):
                _log_message_skipped_unsupported(event)
                await message.ack()
                return
            if await self._account_is_paused(event.seller_id):
                _log_message_skipped_paused(event)
                await message.ack()
                return
            await self._handler.handle(event)
        except GatewayRateLimitError as exc:
            _log_message_requeued(
                event,
                death_count + 1,
                exc,
                retry_after=exc.retry_after_seconds,
            )
            if self._retry_delay_publisher is None:
                await message.nack(requeue=True)
                return
            await self._retry_delay_publisher.publish_delay(
                message.body,
                self.config.queue_name,
                delay_ms=exc.retry_after_seconds * 1000,
            )
            await message.ack()
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
            if str(exc) == "gateway_backpressure":
                _log_message_requeued(event, death_count + 1, exc)
                await message.nack(requeue=True)
                return
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

    async def _account_is_paused(self, seller_id: int) -> bool:
        if self._account_status_source is None:
            return False
        status, cached_at = self._account_status_cache.get(seller_id, (None, 0.0))
        now = time.monotonic()
        if status is not None and now - cached_at <= 30:
            return status == "paused"
        maybe_status = self._account_status_source(seller_id)
        if hasattr(maybe_status, "__await__"):
            maybe_status = await maybe_status
        status = str(maybe_status) if maybe_status is not None else None
        self._account_status_cache[seller_id] = (status, now)
        return status == "paused"


def _log_message_dlq(
    event: FulldockEvent | None,
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
    event: FulldockEvent | None,
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


def _log_message_ack(event: FulldockEvent | None, attempt: int) -> None:
    logger.info(
        "worker.message.ack",
        event_id=event.event_id if event is not None else None,
        seller_id=event.seller_id if event is not None else None,
        resource_path=event.resource if event is not None else None,
        attempt=attempt,
    )


def _log_message_skipped_paused(event: FulldockEvent) -> None:
    logger.info(
        "worker.message.skipped.paused",
        event_id=event.event_id,
        seller_id=event.seller_id,
        resource_path=event.resource,
        module="fulldock",
    )


def _log_message_skipped_unsupported(event: FulldockEvent) -> None:
    logger.info(
        "worker.message.skipped.unsupported_event",
        event_id=event.event_id,
        event_type=event.event_type,
        seller_id=event.seller_id,
        resource_path=event.resource,
        module="fulldock",
    )


def _is_supported_fulldock_event(event: FulldockEvent) -> bool:
    return event.event_type.startswith(("shipments.", "stock_locations."))


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


def _event_context_from_message(message: Any) -> FulldockEvent | None:
    try:
        return _fulldock_event_from_message(message)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None


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

        if event.event_type.startswith("stock_locations."):
            return await self._handle_stock_location_event(event)

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

    async def _handle_stock_location_event(self, event: FulldockEvent) -> str:
        user_product_id = parse_user_product_stock_resource(event.resource)
        if user_product_id is None:
            return await self._record_noop(
                event=event,
                item_id="unknown",
                outcome="malformed_resource",
            )

        seller_id = str(event.seller_id)
        try:
            stock_payload = await self._gateway_client.request(
                "GET", event.resource, seller_id=seller_id, json=None
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return await self._record_noop(
                    event=event,
                    item_id="unknown",
                    outcome="resource_not_found",
                )
            raise

        item_id, current_locations = stock_item_id_and_locations_from_payload(stock_payload)
        if item_id is None or current_locations is None:
            return await self._record_noop(
                event=event,
                item_id=item_id or "unknown",
                outcome="missing_mapping",
            )

        rules = await self._rules_for_items(seller_id=seller_id, item_ids=[item_id])
        if not rules:
            return await self._record_noop(
                event=event,
                item_id=item_id,
                outcome="missing_mapping",
            )

        rule = rules[0]
        desired_locations = normalize_stock_locations(rule.get("stock_locations", []))
        if current_locations == desired_locations:
            return await self._record_noop(
                event=event,
                item_id=item_id,
                outcome="no_drift",
                rule_id=str(rule["_id"]),
                stock_locations=desired_locations,
            )

        await self._gateway_client.request(
            "PUT",
            f"/items/{item_id}/stock_locations",
            seller_id=seller_id,
            json={"locations": desired_locations},
        )
        await self._record_history(
            event=event,
            item_id=item_id,
            outcome="updated",
            rule_id=str(rule["_id"]),
            stock_locations=desired_locations,
        )
        await self._idempotency_store.mark_processed(event.idempotency_key)
        return "updated"

    async def _record_noop(
        self,
        *,
        event: FulldockEvent,
        item_id: str,
        outcome: str,
        rule_id: str | None = None,
        stock_locations: list[dict[str, Any]] | None = None,
    ) -> str:
        await self._record_history(
            event=event,
            item_id=item_id,
            outcome=outcome,
            rule_id=rule_id,
            stock_locations=stock_locations or [],
        )
        await self._idempotency_store.mark_processed(event.idempotency_key)
        return outcome

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


def parse_user_product_stock_resource(resource_path: str) -> str | None:
    normalized = resource_path.rstrip("/")
    parts = normalized.split("/")
    if len(parts) != 4:
        return None
    if parts[0] != "" or parts[1] != "user-products" or parts[3] != "stock":
        return None
    user_product_id = parts[2]
    return user_product_id or None


def stock_item_id_and_locations_from_payload(
    payload: dict[str, Any],
) -> tuple[str | None, list[dict[str, Any]] | None]:
    for candidate in _stock_payload_candidates(payload):
        item_id = _stock_item_id_from_payload(candidate)
        raw_locations = candidate.get("stock_locations", candidate.get("locations"))
        if item_id is not None and isinstance(raw_locations, list):
            current_locations = normalize_proven_stock_locations(raw_locations)
            if current_locations is None:
                return item_id, None
            return item_id, current_locations
    return None, None


def _stock_payload_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = [payload]
    for key in ("items", "results"):
        nested_items = payload.get(key)
        if isinstance(nested_items, list):
            candidates.extend(item for item in nested_items if isinstance(item, dict))
    return candidates


def _stock_item_id_from_payload(payload: dict[str, Any]) -> str | None:
    value = payload.get("item_id")
    if value is not None:
        return str(value)
    nested_item = payload.get("item")
    if isinstance(nested_item, dict):
        value = nested_item.get("id") or nested_item.get("item_id")
        if value is not None:
            return str(value)
    return None


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
        if isinstance(location, dict) and "location_id" in location and "quantity" in location:
            locations.append(
                {
                    "location_id": str(location["location_id"]),
                    "quantity": int(location["quantity"]),
                }
            )
    return sorted(locations, key=lambda location: location["location_id"])


def normalize_proven_stock_locations(raw_locations: Any) -> list[dict[str, Any]] | None:
    if not isinstance(raw_locations, list):
        return None
    locations: list[dict[str, Any]] = []
    for location in raw_locations:
        if not isinstance(location, dict):
            return None
        if "location_id" not in location or "quantity" not in location:
            return None
        locations.append(
            {
                "location_id": str(location["location_id"]),
                "quantity": int(location["quantity"]),
            }
        )
    return sorted(locations, key=lambda location: location["location_id"])


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
    await register_module(validate_manifest(manifest_path), db)
    from google.cloud import kms

    kms_client = kms.KeyManagementServiceClient()
    handler = FulldockEventHandler(
        db=db,
        gateway_client=make_meli_gateway_client(
            base_url=os.environ.get("GATEWAY_BASE_URL", DEFAULT_GATEWAY_BASE_URL),
            kms_client=kms_client,
        ),
        idempotency_store=_FulldockIdempotencyAdapter(
            CoreIdempotencyStore(cast(Any, db["processed_events"]))
        ),
    )
    runner = FulldockAmqpConsumerRunner(
        rabbitmq_url=rabbitmq_url,
        handler=handler,
        manifest_path=manifest_path,
        account_status_source=_account_status_source_from_db(db),
    )
    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, shutdown_event.set)

    sidecar = WorkerHealthSidecar(runner, port=int(os.environ.get("WORKER_HEALTH_PORT", "8080")))
    await sidecar.start()
    await runner.start()
    try:
        await shutdown_event.wait()
    finally:
        await sidecar.stop()
        await runner.close()
        mongo_client.close()


def _account_status_source_from_db(db: Any) -> AccountStatusSource:
    async def source(seller_id: int) -> str | None:
        doc = await db["meli_accounts"].find_one({"seller_id": str(seller_id)})
        if doc is None:
            doc = await db["meli_accounts"].find_one({"seller_id": seller_id})
        return cast(str | None, doc.get("status") if doc else None)

    return source
