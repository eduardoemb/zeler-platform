"""Shared disposable-broker harness for broker-level sheets consumer evidence.

Why this module exists
----------------------
Broker-level evidence (tasks 2.1 and 2.2 of ``zelerdata-pilot-reliable-sync``)
needs the **actual** consumer stack: the real ``SheetsAmqpConsumerRunner`` with
the real ``modules/sheets/manifest.yaml`` routing keys, the real handler over a
real disposable MongoDB replica set, and a disposable loopback RabbitMQ broker.
Only the two external providers stay doubled: the Meli gateway client and the
Google Sheets client. No Meli, Google or production endpoint is contacted.

Safety
------
The broker URL must resolve to a loopback host. Any other host aborts the run,
so the harness cannot be pointed at a shared or production broker by mistake.
The Mongo target is the documented disposable replica set on
``127.0.0.1:27028`` (``docs/lessons/README.md`` L-012), and the database name is
unique per run and dropped on teardown.

Both external providers are optional at runtime. When the disposable broker or
Mongo is absent, ``open_harness`` skips explicitly instead of reporting a false
pass.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

import aio_pika
import pytest
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ServerSelectionTimeoutError

from zeler_platform_core.events.claims import EventClaimStore
from zeler_platform_core.events.idempotency import IdempotencyStore as CoreIdempotencyStore
from zeler_sheets.consumer import (
    DEFAULT_PREFETCH_COUNT,
    MELI_EVENTS_EXCHANGE,
    SHEETS_CLAIMS_QUEUE,
    SheetsAmqpConsumerRunner,
    SheetsEvent,
    SheetsEventHandler,
    _SheetsIdempotencyAdapter,
)
from zeler_sheets.event_stage_telemetry import EventStageTelemetry
from zeler_sheets.google_errors import RetryableGoogleSheetsApiError

DEFAULT_BROKER_URL = "amqp://guest:guest@127.0.0.1:5673/"
DEFAULT_MONGO_HOST = "127.0.0.1:27028"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
MANIFEST_PATH = Path(__file__).resolve().parents[1] / "manifest.yaml"
SELLER_ID = 82453304
ITEM_ID = "MLA123"
RESOURCE = f"/items/{ITEM_ID}"
ITEMS_ROUTING_KEY = "items.updated"
# Production parks retries for 30 s (infra/rabbitmq/delay_queues.json). The
# disposable broker shortens the parking window so the proof stays bounded
# while exercising the same publisher, exchange and dead-letter routing.
DELAY_QUEUE_TTL_MS = 2_500
RETRY_AFTER_SECONDS = 2


def loopback_broker_url() -> str:
    url = os.environ.get("ZELER_SHEETS_TEST_BROKER_URL", DEFAULT_BROKER_URL)
    host = urlparse(url).hostname or ""
    if host not in LOOPBACK_HOSTS:
        msg = (
            "broker evidence refuses a non-loopback endpoint; "
            f"resolved host {host!r}. Use a disposable local broker."
        )
        raise RuntimeError(msg)
    return url


def item_resource(*, price: str, last_updated: str) -> dict[str, Any]:
    return {
        "id": ITEM_ID,
        "seller_id": str(SELLER_ID),
        "title": "Broker evidence widget",
        "status": "active",
        "price": price,
        "base_price": price,
        "available_quantity": 3,
        "category_id": "MLA123",
        "currency_id": "ARS",
        "site_id": "MLA",
        "listing_type_id": "gold_special",
        "shipping": {"free_shipping": True, "mode": "me2"},
        "attributes": [{"id": "SELLER_SKU", "value_name": "sku-broker-1"}],
        "date_created": "2026-04-20T12:30:00Z",
        "last_updated": last_updated,
    }


def event_payload(*, event_id: str, idempotency_key: str) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "event_type": "items.updated",
        "seller_id": SELLER_ID,
        "resource": RESOURCE,
        "idempotency_key": idempotency_key,
    }


def decimal_text(value: Any) -> str:
    to_decimal = getattr(value, "to_decimal", None)
    if callable(to_decimal):
        return str(to_decimal())
    return str(value)


class ScriptedGateway:
    """Meli gateway double: returns the scripted payloads in call order."""

    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        default = [item_resource(price="1.00", last_updated="2026-01-01T00:00:00Z")]
        self._payloads = list(payloads) or default
        self.calls: list[str] = []
        self.delay_seconds = 0.0

    def set_script(self, payloads: list[dict[str, Any]]) -> None:
        self._payloads = list(payloads)
        self.calls = []

    async def fetch_resource(self, *, seller_id: int, path: str) -> dict[str, Any]:
        self.calls.append(path)
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        index = min(len(self.calls) - 1, len(self._payloads) - 1)
        return dict(self._payloads[index])


class RecordingSheetsClient:
    """Google Sheets double that records appends and can fail the first one."""

    def __init__(self) -> None:
        self.rows: list[tuple[str, list[str], str]] = []
        self._failures_remaining = 0

    def fail_next_appends(self, count: int = 1) -> None:
        self._failures_remaining = count

    async def append_row(
        self,
        *,
        seller_id: str,
        spreadsheet_id: str,
        worksheet_name: str,
        row: list[str],
        idempotency_key: str,
    ) -> None:
        if self._failures_remaining:
            self._failures_remaining -= 1
            raise RetryableGoogleSheetsApiError(
                "sheets quota", retry_after_seconds=RETRY_AFTER_SECONDS
            )
        self.rows.append((idempotency_key, list(row), worksheet_name))


class RecordingHandler:
    """Wrapper that records every consumer delivery and its outcome."""

    def __init__(self, inner: SheetsEventHandler) -> None:
        self._inner = inner
        self.results: list[tuple[str, str]] = []
        self.failures: list[tuple[str, str]] = []

    async def handle(self, event: SheetsEvent) -> str:
        try:
            result = await self._inner.handle(event)
        except Exception as exc:
            self.failures.append((event.idempotency_key, type(exc).__name__))
            raise
        self.results.append((event.idempotency_key, result))
        return result


def build_handler(
    *,
    db: Any,
    gateway_client: ScriptedGateway,
    sheets_client: RecordingSheetsClient,
    with_stage_telemetry: bool = False,
) -> SheetsEventHandler:
    """Build the real handler over the given disposable db and doubles."""
    return SheetsEventHandler(
        db=db,
        gateway_client=gateway_client,
        sheets_client=sheets_client,
        idempotency_store=_SheetsIdempotencyAdapter(
            CoreIdempotencyStore(cast(Any, db["processed_events"]))
        ),
        event_claim_store=EventClaimStore(
            cast(Any, db["processed_event_claims"]),
            CoreIdempotencyStore(cast(Any, db["processed_events"])),
        ),
        stage_telemetry=EventStageTelemetry(db=db) if with_stage_telemetry else None,
    )


async def _resolve(predicate: Any) -> bool:
    result = predicate()
    if hasattr(result, "__await__"):
        result = await result
    return bool(result)


@dataclass
class Harness:
    db: Any
    runner: SheetsAmqpConsumerRunner
    handler: RecordingHandler
    gateway: ScriptedGateway
    sheets: RecordingSheetsClient
    channel: Any
    probe_channel: Any
    exchange: Any
    queue_name: str
    dlq_name: str
    delay_queue_name: str
    mongo_client: Any
    mongo_db_name: str
    broker_connection: Any
    probe_connection: Any
    broker_url: str
    queue_deletions: list[str] = field(default_factory=list)

    def make_runner(self, handler: RecordingHandler) -> SheetsAmqpConsumerRunner:
        """Build a fresh (unstarted) runner bound to the same queue."""
        return SheetsAmqpConsumerRunner(
            rabbitmq_url=self.broker_url,
            handler=handler,
            manifest_path=MANIFEST_PATH,
            queue_name=self.queue_name,
            prefetch_count=DEFAULT_PREFETCH_COUNT,
        )

    async def publish(self, payload: dict[str, Any], *, routing_key: str) -> None:
        message = aio_pika.Message(
            body=json.dumps(payload).encode("utf-8"),
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        )
        await self.exchange.publish(message, routing_key=routing_key)

    async def depth(self, queue_name: str) -> int:
        # Depth must be read through a plain (non-robust) channel: a robust
        # channel replays the cached declaration result and would report a
        # stale message count.
        declaration = await self.probe_channel.declare_queue(queue_name, passive=True)
        return int(declaration.declaration_result.message_count or 0)

    async def processed_count(self) -> int:
        return int(await self.db["processed_events"].count_documents({}))

    async def claims_count(self) -> int:
        return int(await self.db["processed_event_claims"].count_documents({}))

    async def processed_once(self) -> bool:
        document = await self.db["processed_events"].find_one({})
        return document is not None

    async def wait_until(
        self,
        predicate: Any,
        *,
        timeout: float = 20.0,
        interval: float = 0.05,
    ) -> bool:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            if await _resolve(predicate):
                return True
            await asyncio.sleep(interval)
        return await _resolve(predicate)

    async def deliveries(self) -> int:
        return len(self.handler.results) + len(self.handler.failures)

    async def wait_for_handler_deliveries(self, count: int, *, timeout: float = 20.0) -> bool:
        async def enough() -> bool:
            return await self.deliveries() >= count

        return await self.wait_until(enough, timeout=timeout)

    async def wait_for_appends(self, count: int, *, timeout: float = 20.0) -> bool:
        async def enough() -> bool:
            return len(self.sheets.rows) >= count

        return await self.wait_until(enough, timeout=timeout)

    async def wait_for_queue_drained(self, *, timeout: float = 20.0) -> bool:
        async def drained() -> bool:
            delivery = await self.depth(self.queue_name)
            delay = await self.depth(self.delay_queue_name)
            return delivery == 0 and delay == 0

        return await self.wait_until(drained, timeout=timeout)

    async def wait_for_parked_retry(self, *, timeout: float = 10.0) -> bool:
        async def parked() -> bool:
            return await self.depth(self.delay_queue_name) >= 1

        return await self.wait_until(parked, timeout=timeout, interval=0.02)

    async def wait_for_stage_doc(
        self, event_key: str, *, timeout: float = 10.0
    ) -> dict[str, Any] | None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            document: dict[str, Any] | None = await self.db["sheets_event_stages"].find_one(
                {"_id": event_key}
            )
            if document is not None:
                return document
            await asyncio.sleep(0.05)
        final_document: dict[str, Any] | None = await self.db["sheets_event_stages"].find_one(
            {"_id": event_key}
        )
        return final_document


@asynccontextmanager
async def open_harness(
    *, db_suffix: str, with_stage_telemetry: bool = False
) -> AsyncIterator[Harness]:
    """Open the disposable broker + Mongo harness and clean up on exit."""
    broker_url = loopback_broker_url()

    mongo_client: Any = AsyncIOMotorClient(
        f"mongodb://{DEFAULT_MONGO_HOST}/probe?directConnection=true",
        tz_aware=True,
        serverSelectionTimeoutMS=2000,
    )
    try:
        hello = await mongo_client.admin.command("hello")
    except ServerSelectionTimeoutError:
        mongo_client.close()
        pytest.skip("disposable loopback Mongo replica set on port 27028 is unavailable")
    assert hello["isWritablePrimary"] and hello["setName"] == "rs0"

    try:
        broker_connection: Any = await aio_pika.connect_robust(broker_url, timeout=3)
    except (aio_pika.exceptions.AMQPConnectionError, OSError):
        mongo_client.close()
        pytest.skip("disposable loopback RabbitMQ broker on port 5673 is unavailable")
    try:
        probe_connection: Any = await aio_pika.connect(broker_url, timeout=3)
    except (aio_pika.exceptions.AMQPConnectionError, OSError):
        await broker_connection.close()
        mongo_client.close()
        pytest.skip("disposable loopback RabbitMQ broker on port 5673 is unavailable")
    probe_channel: Any = await probe_connection.channel()

    suffix = uuid.uuid4().hex[:12]
    mongo_db_name = f"zeler_{db_suffix}_{suffix}"
    db = mongo_client[mongo_db_name]
    await db["sheets_exports"].insert_one(
        {
            "_id": f"export-{db_suffix}",
            "seller_id": str(SELLER_ID),
            "spreadsheet_id": f"sheet-{db_suffix}",
            "worksheet_name": "Items",
            "enabled": True,
            "created_at": datetime(2026, 4, 24, 12, 0, tzinfo=UTC),
            "updated_at": datetime(2026, 4, 24, 12, 0, tzinfo=UTC),
            "schema_version": 1,
        }
    )

    channel: Any = await broker_connection.channel()
    exchange = await channel.declare_exchange(
        MELI_EVENTS_EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True
    )
    await channel.declare_queue(SHEETS_CLAIMS_QUEUE, durable=True)
    queue_name = f"zeler.sheets.events.{db_suffix}.{suffix}"
    delay_queue_name = f"{queue_name}.delay"
    delay_queue = await channel.declare_queue(
        delay_queue_name,
        durable=True,
        arguments={
            "x-message-ttl": DELAY_QUEUE_TTL_MS,
            "x-dead-letter-exchange": "",
            "x-dead-letter-routing-key": queue_name,
        },
    )
    await delay_queue.bind(exchange, routing_key=delay_queue_name)

    gateway = ScriptedGateway([item_resource(price="199.99", last_updated="2026-04-25T12:30:00Z")])
    sheets = RecordingSheetsClient()
    handler = RecordingHandler(
        build_handler(
            db=db,
            gateway_client=gateway,
            sheets_client=sheets,
            with_stage_telemetry=with_stage_telemetry,
        )
    )
    runner = SheetsAmqpConsumerRunner(
        rabbitmq_url=broker_url,
        handler=handler,
        manifest_path=MANIFEST_PATH,
        queue_name=queue_name,
        prefetch_count=DEFAULT_PREFETCH_COUNT,
    )
    await runner.start()

    active = Harness(
        db=db,
        runner=runner,
        handler=handler,
        gateway=gateway,
        sheets=sheets,
        channel=channel,
        probe_channel=probe_channel,
        exchange=exchange,
        queue_name=queue_name,
        dlq_name=f"{queue_name}.dlq",
        delay_queue_name=delay_queue_name,
        mongo_client=mongo_client,
        mongo_db_name=mongo_db_name,
        broker_connection=broker_connection,
        probe_connection=probe_connection,
        broker_url=broker_url,
        queue_deletions=[queue_name, f"{queue_name}.dlq", delay_queue_name],
    )
    try:
        yield active
    finally:
        await active.runner.close()
        for name in active.queue_deletions:
            with suppress(aio_pika.exceptions.AMQPChannelError):
                await channel.queue_delete(name)
        await probe_connection.close()
        await broker_connection.close()
        await mongo_client.drop_database(mongo_db_name)
        mongo_client.close()
