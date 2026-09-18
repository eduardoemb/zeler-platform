"""Measured event-stage evidence for task 2.2 of ``zelerdata-pilot-reliable-sync``.

What this file proves
---------------------
Task 2.2 asks for measured, real evidence of the event stages through the
**actual** consumer (real ``SheetsAmqpConsumerRunner``, real
``SheetsEventHandler``, real ``EventStageTelemetry`` over a disposable Mongo
replica set and disposable loopback RabbitMQ, via the shared harness in
``_broker_harness.py``).

The measurable pilot stage chain is ``received -> fetched -> persisted``. The
``visible`` stage — the formula-cell result actually readable in the Google
Sheet — is intentionally NOT claimed here: an export append into the Sheets
double proves only that the worker sent the row. ``received -> visible``
requires Sheets-side evidence that is still pending in tasks 5.1/5.3. Every
test below therefore asserts that the append happened while ``visible_at``
stays absent, making the distinction explicit.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest
import pytest_asyncio
from _broker_harness import (
    ITEMS_ROUTING_KEY,
    RESOURCE,
    Harness,
    RecordingHandler,
    RecordingSheetsClient,
    build_handler,
    event_payload,
    open_harness,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def harness() -> AsyncIterator[Harness]:
    async with open_harness(db_suffix="task22", with_stage_telemetry=True) as active:
        yield active


def _assert_utc_tz_aware(stage: dict[str, Any], field: str) -> None:
    timestamp = stage[field]
    assert timestamp.tzinfo is not None, f"{field} must be timezone-aware"
    assert timestamp.utcoffset() == timedelta(0), f"{field} must be UTC"


async def test_stages_recorded_in_order_without_visibility_claim(harness: Harness) -> None:
    """One real delivery records received <= fetched <= persisted; visible absent."""
    payload = event_payload(
        event_id="evt-stage-1",
        idempotency_key=f"items:{RESOURCE}:evt-stage-1",
    )

    await harness.publish(payload, routing_key=ITEMS_ROUTING_KEY)
    assert await harness.wait_for_appends(1), "the delivery must append before asserting stages"
    stage = await harness.wait_for_stage_doc(payload["idempotency_key"])
    assert stage is not None, "the consumer must persist a sheets_event_stages document"

    assert stage["received_at"] <= stage["fetched_at"] <= stage["persisted_at"], (
        "the recorded stages must be ordered received <= fetched <= persisted"
    )
    _assert_utc_tz_aware(stage, "received_at")
    _assert_utc_tz_aware(stage, "fetched_at")
    _assert_utc_tz_aware(stage, "persisted_at")
    assert "visible_at" not in stage, "an export append must never claim formula-cell visibility"
    # The append DID happen: the point is precise — the append is present while
    # visibility is not claimed.
    assert len(harness.sheets.rows) == 1
    assert harness.sheets.rows[0][0] == payload["idempotency_key"]


async def test_measured_received_to_persisted_latency_is_positive(harness: Harness) -> None:
    """Measure ``persisted_at - received_at`` from the stored document.

    This is the measurable part of the pilot objective: the per-event latency
    from worker receipt to source persistence, measured through the real
    consumer and recorded durably in Mongo. The ``received -> visible`` leg
    requires the Sheets-side evidence still pending in tasks 5.1/5.3.
    """
    payload = event_payload(
        event_id="evt-stage-latency",
        idempotency_key=f"items:{RESOURCE}:evt-stage-latency",
    )

    await harness.publish(payload, routing_key=ITEMS_ROUTING_KEY)
    assert await harness.wait_for_appends(1)
    stage = await harness.wait_for_stage_doc(payload["idempotency_key"])
    assert stage is not None

    latency = stage["persisted_at"] - stage["received_at"]
    assert latency > timedelta(0), "persistence must complete strictly after receipt"
    # Real measured number for the evidence file; printed so the run output
    # carries the observed value.
    measured_ms = latency.total_seconds() * 1000
    print(
        f"measured received->fetched->persisted latency: {measured_ms:.1f} ms "
        f"(received_at={stage['received_at'].isoformat()}, "
        f"fetched_at={stage['fetched_at'].isoformat()}, "
        f"persisted_at={stage['persisted_at'].isoformat()})"
    )


async def test_stage_measurement_survives_worker_restart(harness: Harness) -> None:
    """A fresh runner on the same queue/db sees the first worker's measurements.

    The duplicate re-delivery is suppressed and leaves ``received_at`` and the
    ``fetched``/``persisted`` timestamps recorded by the first worker intact,
    proving the measurement is durable in Mongo, not in process memory. (A
    fully suppressed duplicate short-circuits before telemetry; the real
    min-update re-processing path is exercised by the retry test below.)
    """
    payload = event_payload(
        event_id="evt-stage-restart",
        idempotency_key=f"items:{RESOURCE}:evt-stage-restart",
    )

    await harness.publish(payload, routing_key=ITEMS_ROUTING_KEY)
    assert await harness.wait_for_appends(1)
    stage_before = await harness.wait_for_stage_doc(payload["idempotency_key"])
    assert stage_before is not None, "the first worker must record its stage timestamps"

    await harness.runner.close()

    fresh_sheets = RecordingSheetsClient()
    fresh_handler = RecordingHandler(
        build_handler(
            db=harness.db,
            gateway_client=harness.gateway,
            sheets_client=fresh_sheets,
            with_stage_telemetry=True,
        )
    )
    fresh_runner = harness.make_runner(fresh_handler)
    await fresh_runner.start()
    # Teardown must close the active runner; the wait helpers must observe the
    # active handler.
    harness.runner = fresh_runner
    harness.handler = fresh_handler

    await harness.publish(payload, routing_key=ITEMS_ROUTING_KEY)
    assert await harness.wait_for_handler_deliveries(1), "the fresh runner must consume"
    assert await harness.wait_for_queue_drained(), "no pending delivery may remain"
    # The phase-1 append can be observed before its broker ack lands; closing the
    # first runner in that window makes RabbitMQ requeue the (already applied)
    # message, so the fresh runner may legitimately see it once more. Either way
    # every delivery must be suppressed as a duplicate: the durable marker is
    # what proves suppression, not the delivery count.
    assert fresh_handler.failures == [], "no delivery may fail after the restart"
    assert all(result == "duplicate" for _, result in fresh_handler.results), (
        "every re-delivered copy must be suppressed by the durable marker"
    )
    assert fresh_sheets.rows == [], "a suppressed duplicate must not append again"

    stage_after = await harness.db["sheets_event_stages"].find_one(
        {"_id": payload["idempotency_key"]}
    )
    assert stage_after is not None
    assert stage_after["received_at"] == stage_before["received_at"], (
        "the first receipt must survive the worker restart"
    )
    assert stage_after["fetched_at"] == stage_before["fetched_at"]
    assert stage_after["persisted_at"] == stage_before["persisted_at"]
    assert "visible_at" not in stage_after


async def test_unfinished_event_keeps_first_received_receipt(harness: Harness) -> None:
    """A retried event keeps the earliest ``received_at`` via the min-update.

    NOTE on scope: the task text expected ``persisted_at`` to appear only after
    the successful attempt, but the real handler persists the source document
    (and records ``persisted``) *before* the export append — the append failure
    never un-persists. The test therefore asserts the honest sequence: the
    first (failed) attempt already records ``persisted_at``, which is itself
    evidence that the persisted stage is not evidence of Sheets visibility.
    """
    harness.sheets.fail_next_appends()
    payload = event_payload(
        event_id="evt-stage-retry",
        idempotency_key=f"items:{RESOURCE}:evt-stage-retry",
    )

    await harness.publish(payload, routing_key=ITEMS_ROUTING_KEY)
    assert await harness.wait_for_parked_retry(), "the failed delivery must park in the retry queue"

    stage_first = await harness.wait_for_stage_doc(payload["idempotency_key"])
    assert stage_first is not None, "the first attempt must record its stage timestamps"
    received_first = stage_first["received_at"]
    assert "persisted_at" in stage_first, (
        "the source write completes before the export append, so the failed "
        "first attempt already records the persisted stage"
    )

    assert await harness.wait_for_appends(1, timeout=30.0), "the retried event must append"
    assert await harness.wait_for_queue_drained(timeout=30.0)

    stage_final = await harness.db["sheets_event_stages"].find_one(
        {"_id": payload["idempotency_key"]}
    )
    assert stage_final is not None
    assert stage_final["received_at"] == received_first, (
        "the min-update must keep the first delivery's received_at, not the retry's"
    )
    assert stage_final["persisted_at"] >= stage_first["persisted_at"], (
        "the successful attempt re-records persistence without regressing it"
    )
    assert len(harness.sheets.rows) == 1
    assert "visible_at" not in stage_final
