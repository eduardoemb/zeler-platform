"""Broker-level evidence for task 2.1 of ``zelerdata-pilot-reliable-sync``.

Why this file exists
--------------------
Task 2.1 asks for proof of duplicate, reordered and unfinished event handling
through the **actual** consumer. The rest of the suite drives
``SheetsAmqpConsumerRunner`` with in-process AMQP doubles
(``modules/sheets/tests/_amqp_fakes.py``) and the handler over in-memory
collections, so it cannot show broker redelivery, arrival order or retry
parking.

This file adds the missing layer:

* a disposable loopback RabbitMQ broker, never production and never shared;
* the real ``SheetsAmqpConsumerRunner`` with the real ``modules/sheets/manifest.yaml``
  routing keys and the real ``zeler.sheets.claims`` passive consumer;
* the real ``SheetsEventHandler`` over a disposable loopback MongoDB replica
  set, using the real ``processed_events`` idempotency store and the real
  ``SheetsEventPersistence`` freshness guards.

Only the two external providers stay doubled: the Meli gateway client and the
Google Sheets client. No Meli, Google or production endpoint is contacted.

Safety
------
The broker URL must resolve to a loopback host. Any other host aborts the run,
so the test cannot be pointed at a shared or production broker by mistake. The
Mongo target is the documented disposable replica set on ``127.0.0.1:27028``
(``docs/lessons/README.md`` L-012), and the database name is unique per test.

Both harnesses are optional. When the disposable broker or Mongo is absent the
tests skip explicitly instead of reporting a false pass.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

import aio_pika
import pytest
import pytest_asyncio
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
from zeler_sheets.google_errors import RetryableGoogleSheetsApiError

pytestmark = pytest.mark.asyncio

_DEFAULT_BROKER_URL = "amqp://guest:guest@127.0.0.1:5673/"
_DEFAULT_MONGO_HOST = "127.0.0.1:27028"
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_MANIFEST_PATH = Path(__file__).resolve().parents[1] / "manifest.yaml"
_SELLER_ID = 82453304
_ITEM_ID = "MLA123"
_RESOURCE = f"/items/{_ITEM_ID}"
_ITEMS_ROUTING_KEY = "items.updated"
# Production parks retries for 30 s (infra/rabbitmq/delay_queues.json). The
# disposable broker shortens the parking window to 5 s so the proof stays bounded
# while exercising the same publisher, exchange and dead-letter routing.
_DELAY_QUEUE_TTL_MS = 2_500
_RETRY_AFTER_SECONDS = 2


def _loopback_broker_url() -> str:
    url = os.environ.get("ZELER_SHEETS_TEST_BROKER_URL", _DEFAULT_BROKER_URL)
    host = urlparse(url).hostname or ""
    if host not in _LOOPBACK_HOSTS:
        msg = (
            "task 2.1 broker evidence refuses a non-loopback endpoint; "
            f"resolved host {host!r}. Use a disposable local broker."
        )
        raise RuntimeError(msg)
    return url


def _item_resource(*, price: str, last_updated: str) -> dict[str, Any]:
    return {
        "id": _ITEM_ID,
        "seller_id": str(_SELLER_ID),
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


def _event_payload(*, event_id: str, idempotency_key: str) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "event_type": "items.updated",
        "seller_id": _SELLER_ID,
        "resource": _RESOURCE,
        "idempotency_key": idempotency_key,
    }


def _decimal_text(value: Any) -> str:
    to_decimal = getattr(value, "to_decimal", None)
    if callable(to_decimal):
        return str(to_decimal())
    return str(value)


class _ScriptedGateway:
    """Meli gateway double: returns the scripted payloads in call order."""

    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        default = [_item_resource(price="1.00", last_updated="2026-01-01T00:00:00Z")]
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


class _RecordingSheetsClient:
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
                "sheets quota", retry_after_seconds=_RETRY_AFTER_SECONDS
            )
        self.rows.append((idempotency_key, list(row), worksheet_name))


class _RecordingHandler:
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


@dataclass
class _Harness:
    db: Any
    runner: SheetsAmqpConsumerRunner
    handler: _RecordingHandler
    gateway: _ScriptedGateway
    sheets: _RecordingSheetsClient
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
    queue_deletions: list[str] = field(default_factory=list)

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


async def _resolve(predicate: Any) -> bool:
    result = predicate()
    if hasattr(result, "__await__"):
        result = await result
    return bool(result)


@pytest_asyncio.fixture
async def harness() -> AsyncIterator[_Harness]:
    broker_url = _loopback_broker_url()

    mongo_client: Any = AsyncIOMotorClient(
        f"mongodb://{_DEFAULT_MONGO_HOST}/probe?directConnection=true",
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
    mongo_db_name = f"zeler_task21_{suffix}"
    db = mongo_client[mongo_db_name]
    await db["sheets_exports"].insert_one(
        {
            "_id": "export-task21",
            "seller_id": str(_SELLER_ID),
            "spreadsheet_id": "sheet-task21",
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
    queue_name = f"zeler.sheets.events.task21.{suffix}"
    delay_queue_name = f"{queue_name}.delay"
    delay_queue = await channel.declare_queue(
        delay_queue_name,
        durable=True,
        arguments={
            "x-message-ttl": _DELAY_QUEUE_TTL_MS,
            "x-dead-letter-exchange": "",
            "x-dead-letter-routing-key": queue_name,
        },
    )
    await delay_queue.bind(exchange, routing_key=delay_queue_name)

    gateway = _ScriptedGateway(
        [_item_resource(price="199.99", last_updated="2026-04-25T12:30:00Z")]
    )
    sheets = _RecordingSheetsClient()
    handler = _RecordingHandler(
        SheetsEventHandler(
            db=db,
            gateway_client=gateway,
            sheets_client=sheets,
            idempotency_store=_SheetsIdempotencyAdapter(
                CoreIdempotencyStore(cast(Any, db["processed_events"]))
            ),
            event_claim_store=EventClaimStore(
                cast(Any, db["processed_event_claims"]),
                CoreIdempotencyStore(cast(Any, db["processed_events"])),
            ),
        )
    )
    runner = SheetsAmqpConsumerRunner(
        rabbitmq_url=broker_url,
        handler=handler,
        manifest_path=_MANIFEST_PATH,
        queue_name=queue_name,
        prefetch_count=DEFAULT_PREFETCH_COUNT,
    )
    await runner.start()

    active = _Harness(
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
        queue_deletions=[queue_name, f"{queue_name}.dlq", delay_queue_name],
    )
    try:
        yield active
    finally:
        await runner.close()
        for name in active.queue_deletions:
            with suppress(aio_pika.exceptions.AMQPChannelError):
                await channel.queue_delete(name)
        await probe_connection.close()
        await broker_connection.close()
        await mongo_client.drop_database(mongo_db_name)
        mongo_client.close()


async def test_duplicate_delivery_through_real_broker_appends_once(harness: _Harness) -> None:
    payload = _event_payload(
        event_id="evt-dup-1",
        idempotency_key=f"items:{_RESOURCE}:evt-dup-1",
    )

    await harness.publish(payload, routing_key=_ITEMS_ROUTING_KEY)
    assert await harness.wait_for_appends(1), "the first delivery must append exactly one row"
    assert await harness.wait_until(harness.processed_once), "the first delivery must be marked"

    await harness.publish(payload, routing_key=_ITEMS_ROUTING_KEY)
    assert await harness.wait_for_handler_deliveries(2), "the broker must redeliver the duplicate"
    assert await harness.wait_for_queue_drained(), "the broker must have no pending delivery left"

    # The completed marker lands before the first handler returns (the lease
    # cleanup follows the marker write), so the recording order of the two
    # outcomes is not stable. The multiset is the invariant.
    assert sorted(result for _, result in harness.handler.results) == ["appended", "duplicate"]
    assert len(harness.sheets.rows) == 1
    assert len(harness.gateway.calls) == 1
    assert await harness.processed_count() == 1
    assert await harness.claims_count() == 0
    assert await harness.depth(harness.dlq_name) == 0


async def test_out_of_order_delivery_keeps_newest_persisted_state(harness: _Harness) -> None:
    harness.gateway.set_script(
        [
            _item_resource(price="199.99", last_updated="2026-04-25T12:30:00Z"),
            _item_resource(price="149.99", last_updated="2026-04-20T12:30:00Z"),
        ]
    )
    newer = _event_payload(
        event_id="evt-order-2",
        idempotency_key=f"items:{_RESOURCE}:evt-order-2",
    )
    older = _event_payload(
        event_id="evt-order-1",
        idempotency_key=f"items:{_RESOURCE}:evt-order-1",
    )

    await harness.publish(newer, routing_key=_ITEMS_ROUTING_KEY)
    assert await harness.wait_for_handler_deliveries(1), "the newer delivery must be processed"

    await harness.publish(older, routing_key=_ITEMS_ROUTING_KEY)
    assert await harness.wait_for_handler_deliveries(2), "the older delivery must be processed"
    assert await harness.wait_for_queue_drained()

    document = await harness.db["items"].find_one({"_id": _ITEM_ID, "seller_id": str(_SELLER_ID)})
    assert document is not None
    assert _decimal_text(document["price"]) == "199.99", (
        "an older observation must not regress state"
    )
    assert document["last_updated"] == datetime(2026, 4, 25, 12, 30, tzinfo=UTC)
    assert await harness.processed_count() == 2
    assert await harness.depth(harness.dlq_name) == 0


async def test_unfinished_event_parks_in_retry_delay_and_completes_once(harness: _Harness) -> None:
    harness.sheets.fail_next_appends()
    payload = _event_payload(
        event_id="evt-retry-1",
        idempotency_key=f"items:{_RESOURCE}:evt-retry-1",
    )

    await harness.publish(payload, routing_key=_ITEMS_ROUTING_KEY)
    assert await harness.wait_for_parked_retry(), "the failed delivery must park in the retry queue"
    assert harness.sheets.rows == [], "the failed first attempt must not append"
    assert await harness.depth(harness.queue_name) == 0

    assert await harness.wait_for_handler_deliveries(2, timeout=30.0), (
        "the parked event must return"
    )
    assert await harness.wait_for_appends(1, timeout=30.0)
    assert await harness.wait_for_queue_drained(timeout=30.0)

    assert harness.handler.failures == [
        (payload["idempotency_key"], "RetryableGoogleSheetsApiError")
    ]
    assert harness.handler.results == [(payload["idempotency_key"], "appended")]
    assert len(harness.sheets.rows) == 1
    assert await harness.processed_count() == 1
    assert await harness.depth(harness.dlq_name) == 0


async def test_concurrent_duplicate_deliveries_do_not_double_apply(harness: _Harness) -> None:
    """Boundary probe: production prefetch keeps several deliveries in flight.

    The gateway double holds each fetch so both copies of the same event are
    inside the handler at the same time. The idempotency contract still allows
    exactly one append and one processed marker.
    """
    harness.gateway.delay_seconds = 0.25
    payload = _event_payload(
        event_id="evt-dup-concurrent",
        idempotency_key=f"items:{_RESOURCE}:evt-dup-concurrent",
    )

    await harness.publish(payload, routing_key=_ITEMS_ROUTING_KEY)
    await harness.publish(payload, routing_key=_ITEMS_ROUTING_KEY)
    assert await harness.wait_for_handler_deliveries(2)
    assert await harness.wait_for_queue_drained()

    assert sorted(result for _, result in harness.handler.results) == ["appended", "duplicate"], (
        "the concurrent loser must wait and then observe the completed marker"
    )
    assert await harness.processed_count() == 1
    assert len(harness.sheets.rows) == 1, "concurrent duplicates must not double-append"
    assert await harness.claims_count() == 0, "a completed delivery must leave no lease behind"
    assert await harness.depth(harness.dlq_name) == 0
