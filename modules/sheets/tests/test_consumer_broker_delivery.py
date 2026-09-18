"""Broker-level evidence for task 2.1 of ``zelerdata-pilot-reliable-sync``.

Why this file exists
--------------------
Task 2.1 asks for proof of duplicate, reordered and unfinished event handling
through the **actual** consumer. The rest of the suite drives
``SheetsAmqpConsumerRunner`` with in-process AMQP doubles
(``modules/sheets/tests/_amqp_fakes.py``) and the handler over in-memory
collections, so it cannot show broker redelivery, arrival order or retry
parking.

The disposable broker/Mongo harness lives in the shared non-test module
``modules/sheets/tests/_broker_harness.py`` (also used by the task 2.2
measured-stage evidence in ``test_consumer_stage_telemetry_broker.py``):

* a disposable loopback RabbitMQ broker, never production and never shared;
* the real ``SheetsAmqpConsumerRunner`` with the real ``modules/sheets/manifest.yaml``
  routing keys and the real ``zeler.sheets.claims`` passive consumer;
* the real ``SheetsEventHandler`` over a disposable loopback MongoDB replica
  set, using the real ``processed_events`` idempotency store and the real
  ``SheetsEventPersistence`` freshness guards.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from _broker_harness import (
    ITEM_ID,
    ITEMS_ROUTING_KEY,
    RESOURCE,
    SELLER_ID,
    Harness,
    decimal_text,
    event_payload,
    item_resource,
    open_harness,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def harness() -> AsyncIterator[Harness]:
    async with open_harness(db_suffix="task21") as active:
        yield active


async def test_duplicate_delivery_through_real_broker_appends_once(harness: Harness) -> None:
    payload = event_payload(
        event_id="evt-dup-1",
        idempotency_key=f"items:{RESOURCE}:evt-dup-1",
    )

    await harness.publish(payload, routing_key=ITEMS_ROUTING_KEY)
    assert await harness.wait_for_appends(1), "the first delivery must append exactly one row"
    assert await harness.wait_until(harness.processed_once), "the first delivery must be marked"

    await harness.publish(payload, routing_key=ITEMS_ROUTING_KEY)
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


async def test_out_of_order_delivery_keeps_newest_persisted_state(harness: Harness) -> None:
    harness.gateway.set_script(
        [
            item_resource(price="199.99", last_updated="2026-04-25T12:30:00Z"),
            item_resource(price="149.99", last_updated="2026-04-20T12:30:00Z"),
        ]
    )
    newer = event_payload(
        event_id="evt-order-2",
        idempotency_key=f"items:{RESOURCE}:evt-order-2",
    )
    older = event_payload(
        event_id="evt-order-1",
        idempotency_key=f"items:{RESOURCE}:evt-order-1",
    )

    await harness.publish(newer, routing_key=ITEMS_ROUTING_KEY)
    assert await harness.wait_for_handler_deliveries(1), "the newer delivery must be processed"

    await harness.publish(older, routing_key=ITEMS_ROUTING_KEY)
    assert await harness.wait_for_handler_deliveries(2), "the older delivery must be processed"
    assert await harness.wait_for_queue_drained()

    document = await harness.db["items"].find_one({"_id": ITEM_ID, "seller_id": str(SELLER_ID)})
    assert document is not None
    assert decimal_text(document["price"]) == "199.99", (
        "an older observation must not regress state"
    )
    assert document["last_updated"] == datetime(2026, 4, 25, 12, 30, tzinfo=UTC)
    assert await harness.processed_count() == 2
    assert await harness.depth(harness.dlq_name) == 0


async def test_unfinished_event_parks_in_retry_delay_and_completes_once(harness: Harness) -> None:
    harness.sheets.fail_next_appends()
    payload = event_payload(
        event_id="evt-retry-1",
        idempotency_key=f"items:{RESOURCE}:evt-retry-1",
    )

    await harness.publish(payload, routing_key=ITEMS_ROUTING_KEY)
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


async def test_concurrent_duplicate_deliveries_do_not_double_apply(harness: Harness) -> None:
    """Boundary probe: production prefetch keeps several deliveries in flight.

    The gateway double holds each fetch so both copies of the same event are
    inside the handler at the same time. The idempotency contract still allows
    exactly one append and one processed marker.
    """
    harness.gateway.delay_seconds = 0.25
    payload = event_payload(
        event_id="evt-dup-concurrent",
        idempotency_key=f"items:{RESOURCE}:evt-dup-concurrent",
    )

    await harness.publish(payload, routing_key=ITEMS_ROUTING_KEY)
    await harness.publish(payload, routing_key=ITEMS_ROUTING_KEY)
    assert await harness.wait_for_handler_deliveries(2)
    assert await harness.wait_for_queue_drained()

    assert sorted(result for _, result in harness.handler.results) == ["appended", "duplicate"], (
        "the concurrent loser must wait and then observe the completed marker"
    )
    assert await harness.processed_count() == 1
    assert len(harness.sheets.rows) == 1, "concurrent duplicates must not double-append"
    assert await harness.claims_count() == 0, "a completed delivery must leave no lease behind"
    assert await harness.depth(harness.dlq_name) == 0
