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
from zeler_platform_core.runtime.retry_delay import RETRY_ATTEMPT_HEADER, RetryDelayPublisher
from zeler_platform_core.runtime.worker_health import WorkerHealthSidecar
from zeler_sheets.event_persistence import SheetsEventPersistence, StatusObservationContentionError
from zeler_sheets.google_errors import RetryableGoogleSheetsApiError
from zeler_sheets.google_sheets_client import make_sheets_client
from zeler_sheets.sheets_config import SheetsSettings
from zeler_sheets.sheetseller_backfill import run_item_detail_enrichment, run_sheetseller_backfill

MELI_EVENTS_EXCHANGE = "meli.events"
SHEETS_EVENTS_QUEUE = "zeler.sheets.events"
SHEETS_EVENTS_DLX = "zeler.sheets.events.dlx"
SHEETS_EVENTS_DLQ = f"{SHEETS_EVENTS_QUEUE}.dlq"
SHEETS_DELIVERY_LIMIT = 5
DEFAULT_PREFETCH_COUNT = 10
SHEETS_DEFAULT_ROUTING_KEYS = ("items.*", "orders.*", "shipments.*")
MISSING_RABBITMQ_URL_MESSAGE = "error: RABBITMQ_URL is required"
MISSING_MONGO_URI_MESSAGE = "error: MONGO_URI is required"
MISSING_MONGO_DB_MESSAGE = "error: MONGO_DB is required"
PERMANENT_HTTP_STATUS_CODES = {401, 403, 404, 422}
RETRIABLE_HTTP_STATUS_CODES = {408, 429}
DEFAULT_GATEWAY_BASE_URL = "http://gateway:8080/proxy/meli"
DEFAULT_STATUS_CONTENTION_RETRY_DELAY_MS = 1000

logger = structlog.get_logger(__name__)


class RetryLimitExceededError(Exception):
    """Raised internally to describe exhausted broker retry budget."""


@dataclass(frozen=True)
class SheetsEvent:
    event_id: str
    event_type: str
    seller_id: int
    resource: str
    idempotency_key: str


class GatewayResourceClient(Protocol):
    async def fetch_resource(self, *, seller_id: Any, path: str) -> dict[str, Any]: ...


class SheetsGatewayClient:
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

    async def fetch_resource(self, *, seller_id: int, path: str) -> dict[str, Any]:
        normalized_path = path if path.startswith("/") else f"/{path}"
        async with httpx.AsyncClient(transport=self._transport) as client:
            response = await client.get(
                f"{self._base_url}{normalized_path}",
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "X-Seller-Id": str(seller_id),
                },
            )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("gateway resource response must be a JSON object")
        return payload


def make_meli_gateway_client(
    *,
    module_id: str = "sheets",
    base_url: str = DEFAULT_GATEWAY_BASE_URL,
    kms_client: Any,
) -> MeliGatewayClient:
    return MeliGatewayClient(
        base_url,
        MeliGatewayAuth(module_id, kms_client),
    )


class GoogleSheetsClient(Protocol):
    async def append_row(
        self,
        *,
        seller_id: str,
        spreadsheet_id: str,
        worksheet_name: str,
        row: list[str],
        idempotency_key: str,
    ) -> None: ...


class _NotImplementedSheetsClient:
    async def append_row(self, **kwargs: Any) -> None:
        raise NotImplementedError("GoogleSheetsClient not implemented — see TODO")


class IdempotencyStore(Protocol):
    async def is_duplicate(self, key: str) -> bool: ...

    async def mark_processed(self, key: str) -> None: ...


class SheetsEventHandlerLike(Protocol):
    async def handle(self, event: SheetsEvent) -> str: ...


AccountStatusSource = Callable[[int], Any]


@dataclass(frozen=True)
class SheetsAmqpConsumerConfig:
    rabbitmq_url: str
    exchange_name: str = MELI_EVENTS_EXCHANGE
    queue_name: str = SHEETS_EVENTS_QUEUE
    dead_letter_exchange: str = SHEETS_EVENTS_DLX
    delivery_limit: int = SHEETS_DELIVERY_LIMIT
    prefetch_count: int = DEFAULT_PREFETCH_COUNT
    routing_keys: tuple[str, ...] = SHEETS_DEFAULT_ROUTING_KEYS


class SheetsAmqpConsumerRunner:
    exchange_type_topic = aio_pika.ExchangeType.TOPIC

    def __init__(
        self,
        *,
        rabbitmq_url: str,
        handler: SheetsEventHandlerLike,
        manifest_path: str | Path | None = None,
        queue_name: str = SHEETS_EVENTS_QUEUE,
        exchange_name: str = MELI_EVENTS_EXCHANGE,
        dead_letter_exchange: str = SHEETS_EVENTS_DLX,
        delivery_limit: int = SHEETS_DELIVERY_LIMIT,
        prefetch_count: int = DEFAULT_PREFETCH_COUNT,
        retry_delay_publisher: Any | None = None,
        account_status_source: AccountStatusSource | None = None,
    ) -> None:
        routing_keys = _sheets_routing_keys_from_manifest(manifest_path)
        self.config = SheetsAmqpConsumerConfig(
            rabbitmq_url=rabbitmq_url,
            exchange_name=exchange_name,
            queue_name=queue_name,
            dead_letter_exchange=dead_letter_exchange,
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
        dead_letter_queue_name = f"{self.config.queue_name}.dlq"
        dead_letter_queue = await channel.declare_queue(
            dead_letter_queue_name,
            durable=True,
            arguments={},
        )
        await dead_letter_queue.bind(dead_letter_exchange, routing_key=dead_letter_queue_name)
        queue = await channel.declare_queue(
            self.config.queue_name,
            durable=True,
            arguments={
                "x-dead-letter-exchange": self.config.dead_letter_exchange,
                "x-dead-letter-routing-key": dead_letter_queue_name,
            },
        )
        for routing_key in self.config.routing_keys:
            await queue.bind(exchange, routing_key=routing_key)
        if self._retry_delay_publisher is None:
            self._retry_delay_publisher = RetryDelayPublisher(channel)
        await queue.consume(self.handle_message)
        self.is_ready = True

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None
        self.is_ready = False

    async def handle_message(self, message: Any) -> None:
        self.last_heartbeat_at = datetime.now(UTC)
        death_count = _delivery_attempt_count(message, queue_name=self.config.queue_name)
        event: SheetsEvent | None = None
        if death_count >= self.config.delivery_limit:
            event = _event_context_from_message(message)
            _log_message_dlq(event, death_count, RetryLimitExceededError())
            await message.nack(requeue=False)
            return

        try:
            event = _sheets_event_from_message(message)
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
                headers=_retry_headers(message, attempt=death_count + 1),
            )
            await message.ack()
            return
        except RetryableGoogleSheetsApiError as exc:
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
                headers=_retry_headers(message, attempt=death_count + 1),
            )
            await message.ack()
            return
        except StatusObservationContentionError as exc:
            _log_message_requeued(event, death_count + 1, exc)
            if self._retry_delay_publisher is None:
                await message.nack(requeue=True)
                return
            await self._retry_delay_publisher.publish_delay(
                message.body,
                self.config.queue_name,
                delay_ms=DEFAULT_STATUS_CONTENTION_RETRY_DELAY_MS,
                headers=_retry_headers(message, attempt=death_count + 1),
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
                _log_message_requeued(
                    event,
                    death_count + 1,
                    exc,
                    status_code=status_code,
                )
                await message.nack(requeue=True)
                return
            raise
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            _log_message_requeued(event, death_count + 1, exc)
            await message.nack(requeue=True)
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
    event: SheetsEvent | None,
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
    event: SheetsEvent | None,
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


def _log_message_ack(event: SheetsEvent | None, attempt: int) -> None:
    logger.info(
        "worker.message.ack",
        event_id=event.event_id if event is not None else None,
        seller_id=event.seller_id if event is not None else None,
        resource_path=event.resource if event is not None else None,
        attempt=attempt,
    )


def _log_message_skipped_paused(event: SheetsEvent) -> None:
    logger.info(
        "worker.message.skipped.paused",
        event_id=event.event_id,
        seller_id=event.seller_id,
        resource_path=event.resource,
        module="sheets",
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


def _delivery_attempt_count(message: Any, *, queue_name: str) -> int:
    return max(
        _x_death_count(message, queue_name=queue_name),
        _retry_attempt_header_count(message),
    )


def _retry_attempt_header_count(message: Any) -> int:
    headers = getattr(message, "headers", None)
    if not isinstance(headers, dict):
        return 0
    value = headers.get(RETRY_ATTEMPT_HEADER)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _retry_headers(message: Any, *, attempt: int) -> dict[str, object]:
    headers = getattr(message, "headers", None)
    retry_headers: dict[str, object] = dict(headers) if isinstance(headers, dict) else {}
    retry_headers.pop("x-death", None)
    retry_headers[RETRY_ATTEMPT_HEADER] = attempt
    return retry_headers


def _event_context_from_message(message: Any) -> SheetsEvent | None:
    try:
        return _sheets_event_from_message(message)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _sheets_routing_keys_from_manifest(manifest_path: str | Path | None) -> tuple[str, ...]:
    if manifest_path is None:
        return SHEETS_DEFAULT_ROUTING_KEYS
    manifest = validate_manifest(manifest_path)
    return tuple(manifest.routing_keys)


def _sheets_event_from_message(message: Any) -> SheetsEvent:
    payload = json.loads(message.body.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("sheets event payload must be a JSON object")
    return SheetsEvent(
        event_id=str(payload["event_id"]),
        event_type=str(payload["event_type"]),
        seller_id=int(payload["seller_id"]),
        resource=str(payload["resource"]),
        idempotency_key=_sheets_idempotency_key(message, payload),
    )


def _sheets_idempotency_key(message: Any, payload: dict[str, Any]) -> str:
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


class _SheetsIdempotencyAdapter:
    def __init__(self, store: CoreIdempotencyStoreLike) -> None:
        self._store = store

    async def is_duplicate(self, key: str) -> bool:
        return await self._store.is_duplicate(key)

    async def mark_processed(self, key: str) -> None:
        await self._store.mark_processed(key, module_id="sheets")


class SheetsEventHandler:
    def __init__(
        self,
        *,
        db: Any,
        gateway_client: GatewayResourceClient,
        sheets_client: GoogleSheetsClient,
        idempotency_store: IdempotencyStore,
        event_persistence: Any | None = None,
        zelerdata_enrichment_enabled: bool = False,
        sale_price_enabled: bool = False,
        listing_fixed_fee_enabled: bool = False,
    ) -> None:
        self._db = db
        self._gateway_client = gateway_client
        self._sheets_client = sheets_client
        self._idempotency_store = idempotency_store
        self._event_persistence = event_persistence or SheetsEventPersistence(db=db)
        self._zelerdata_enrichment_enabled = zelerdata_enrichment_enabled
        self._sale_price_enabled = sale_price_enabled
        self._listing_fixed_fee_enabled = listing_fixed_fee_enabled

    async def handle(self, event: SheetsEvent) -> str:
        if await self._idempotency_store.is_duplicate(event.idempotency_key):
            return "duplicate"

        resource = await self._gateway_client.fetch_resource(
            seller_id=event.seller_id,
            path=event.resource,
        )
        await self._event_persistence.persist(
            event_type=event.event_type,
            seller_id=event.seller_id,
            resource=resource,
        )
        await self._refresh_zelerdata_enrichment_if_enabled(event)
        export_config = await self._db["sheets_exports"].find_one(
            {"seller_id": str(event.seller_id), "enabled": True}
        )
        if export_config is None:
            await self._idempotency_store.mark_processed(event.idempotency_key)
            return "no_export"

        row = format_resource_row(event.event_type, resource)
        await self._sheets_client.append_row(
            seller_id=str(event.seller_id),
            spreadsheet_id=str(export_config["spreadsheet_id"]),
            worksheet_name=str(export_config.get("worksheet_name", "Events")),
            row=row,
            idempotency_key=event.idempotency_key,
        )
        await self._idempotency_store.mark_processed(event.idempotency_key)
        return "appended"

    async def _refresh_zelerdata_enrichment_if_enabled(self, event: SheetsEvent) -> None:
        if not self._zelerdata_enrichment_enabled or not event.event_type.startswith("items."):
            return
        item_id = _item_id_from_resource_path(event.resource)
        if item_id is None:
            return
        seller_id = str(event.seller_id)
        await run_item_detail_enrichment(
            db=self._db,
            gateway=self._gateway_client,
            seller_id=seller_id,
            dry_run=False,
            item_ids=(item_id,),
            sale_price_enabled=self._sale_price_enabled,
            listing_fixed_fee_enabled=self._listing_fixed_fee_enabled,
        )
        await run_sheetseller_backfill(
            db=self._db,
            seller_id=seller_id,
            dry_run=False,
            item_ids=(item_id,),
        )


def format_resource_row(event_type: str, resource: dict[str, Any]) -> list[str]:
    resource_id = _first_string(resource, "id", "_id", "order_id", "shipment_id")
    title = _first_string(resource, "title", "description", "status_detail")
    status = _first_string(resource, "status")
    price = _first_string(resource, "price", "total_amount")
    quantity = _first_string(resource, "available_quantity", "quantity")
    return [event_type, resource_id, title, status, price, quantity]


def _item_id_from_resource_path(resource: str) -> str | None:
    parts = [part for part in resource.split("?")[0].split("/") if part]
    if len(parts) >= 2 and parts[-2] == "items":
        item_id = parts[-1].strip()
        return item_id or None
    return None


def _first_string(resource: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = resource.get(key)
        if value is not None:
            return str(value)
    return ""


async def run() -> None:
    """Boot the sheets AMQP worker with the real Google Sheets client."""
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
    from google.cloud import kms

    sheets_settings = SheetsSettings()  # type: ignore[call-arg]
    kms_client = kms.KeyManagementServiceClient()
    manifest_path = Path(__file__).resolve().parents[2] / "manifest.yaml"
    handler = SheetsEventHandler(
        db=db,
        gateway_client=make_meli_gateway_client(
            base_url=os.environ.get("GATEWAY_BASE_URL", DEFAULT_GATEWAY_BASE_URL),
            kms_client=kms_client,
        ),
        sheets_client=make_sheets_client(db, kms_client, sheets_settings),
        idempotency_store=_SheetsIdempotencyAdapter(
            CoreIdempotencyStore(cast(Any, db["processed_events"]))
        ),
        zelerdata_enrichment_enabled=_env_flag_enabled("ZELERDATA_ENRICHMENT_ENABLED"),
        sale_price_enabled=_env_flag_enabled("ZELERDATA_SALE_PRICE_ENABLED"),
        listing_fixed_fee_enabled=_env_flag_enabled("ZELERDATA_LISTING_FIXED_FEE_ENABLED"),
    )
    runner = SheetsAmqpConsumerRunner(
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


def _env_flag_enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}
