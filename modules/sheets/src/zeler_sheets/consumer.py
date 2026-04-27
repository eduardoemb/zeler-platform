from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

import aio_pika
import httpx
from motor.motor_asyncio import AsyncIOMotorClient

from zeler_platform_core.events.idempotency import IdempotencyStore as CoreIdempotencyStore
from zeler_platform_core.runtime.manifest import validate_manifest
from zeler_sheets.google_sheets_client import make_sheets_client
from zeler_sheets.sheets_config import SheetsSettings

MELI_EVENTS_EXCHANGE = "meli.events"
SHEETS_EVENTS_QUEUE = "zeler.sheets.events"
SHEETS_EVENTS_DLX = "zeler.sheets.events.dlx"
SHEETS_DELIVERY_LIMIT = 5
DEFAULT_PREFETCH_COUNT = 10
SHEETS_DEFAULT_ROUTING_KEYS = ("items.*", "orders.*", "shipments.*")
MISSING_RABBITMQ_URL_MESSAGE = "error: RABBITMQ_URL is required"
MISSING_MONGO_URI_MESSAGE = "error: MONGO_URI is required"
MISSING_MONGO_DB_MESSAGE = "error: MONGO_DB is required"


@dataclass(frozen=True)
class SheetsEvent:
    event_id: str
    event_type: str
    seller_id: int
    resource: str
    idempotency_key: str


class GatewayResourceClient(Protocol):
    async def fetch_resource(self, *, seller_id: int, path: str) -> dict[str, Any]: ...


class SheetsGatewayClient:
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
            event = _sheets_event_from_message(message)
            await self._handler.handle(event)
        except RuntimeError:
            await message.nack(requeue=True)
            return
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
            await message.nack(requeue=False)
            return
        await message.ack()


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
    ) -> None:
        self._db = db
        self._gateway_client = gateway_client
        self._sheets_client = sheets_client
        self._idempotency_store = idempotency_store

    async def handle(self, event: SheetsEvent) -> str:
        if await self._idempotency_store.is_duplicate(event.idempotency_key):
            return "duplicate"

        export_config = await self._db["sheets_exports"].find_one(
            {"seller_id": str(event.seller_id), "enabled": True}
        )
        if export_config is None:
            await self._idempotency_store.mark_processed(event.idempotency_key)
            return "no_export"

        resource = await self._gateway_client.fetch_resource(
            seller_id=event.seller_id,
            path=event.resource,
        )
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


def format_resource_row(event_type: str, resource: dict[str, Any]) -> list[str]:
    resource_id = _first_string(resource, "id", "_id", "order_id", "shipment_id")
    title = _first_string(resource, "title", "description", "status_detail")
    status = _first_string(resource, "status")
    price = _first_string(resource, "price", "total_amount")
    quantity = _first_string(resource, "available_quantity", "quantity")
    return [event_type, resource_id, title, status, price, quantity]


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
        gateway_client=SheetsGatewayClient(
            base_url=os.environ.get("GATEWAY_BASE_URL", "http://gateway"),
            token=os.environ.get("GATEWAY_TOKEN", ""),
        ),
        sheets_client=make_sheets_client(db, kms_client, sheets_settings),
        idempotency_store=_SheetsIdempotencyAdapter(
            CoreIdempotencyStore(cast(Any, db["processed_events"]))
        ),
    )
    runner = SheetsAmqpConsumerRunner(
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
