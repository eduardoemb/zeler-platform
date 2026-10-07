"""Ordinary events must not depend on a paused history pilot.

Incident 2026-10-07: with history on link disabled, a persisted pilot plan still
routed every ordinary webhook through the pilot budget. Each one raised a policy
WAIT and was republished every 5 seconds forever, exhausting the broker's
monthly message quota.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from zeler_platform_core.history_work_intent import HistoryWorkWaitError
from zeler_platform_core.runtime.retry_delay import RETRY_ATTEMPT_HEADER
from zeler_sheets import consumer
from zeler_sheets.consumer import (
    POLICY_WAIT_HEADER,
    SheetsAmqpConsumerRunner,
    SheetsEvent,
    SheetsEventHandler,
)
from zeler_sheets.formulas.pacing import HistoryPolicyWaitError

SELLER = "82453304"


class Plans:
    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        assert query == {"_id": SELLER}
        return {"_id": SELLER, "execution_id": "a" * 32}


def _handler(**kwargs: Any) -> SheetsEventHandler:
    return SheetsEventHandler(
        db={"sheets_history_backfill_plans": Plans()},
        gateway_client=MagicMock(name="ordinary-gateway"),
        sheets_client=MagicMock(),
        idempotency_store=MagicMock(),
        **kwargs,
    )


def _event() -> SheetsEvent:
    return SheetsEvent("event", "orders_v2", int(SELLER), "/orders/2000018837474638", "key")


@pytest.mark.asyncio
async def test_history_off_uses_ordinary_gateway_despite_persisted_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def resolve(db: Any, **kwargs: Any) -> Any:
        raise AssertionError("history work authority must not be resolved")

    monkeypatch.setattr(consumer, "resolve_history_work_intent", resolve)
    handler = _handler(history_work_enabled=False)

    gateway = await handler._gateway_for_event(_event(), MagicMock(), job_identity=None)

    assert gateway is handler._gateway_client


@pytest.mark.asyncio
async def test_history_on_keeps_routing_plan_sellers_through_work_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    async def resolve(db: Any, **kwargs: Any) -> Any:
        calls.append(kwargs)
        raise HistoryWorkWaitError("no durable authority")

    monkeypatch.setattr(consumer, "resolve_history_work_intent", resolve)
    handler = _handler()

    with pytest.raises(HistoryPolicyWaitError):
        await handler._gateway_for_event(_event(), MagicMock(), job_identity=None)
    assert len(calls) == 1


class WaitingHandler:
    async def handle(self, event: SheetsEvent) -> str:
        raise HistoryPolicyWaitError("gateway history execution is held")


class FakeMessage:
    def __init__(self, headers: dict[str, Any]) -> None:
        self.body = json.dumps(
            {
                "event_id": "evt-1",
                "event_type": "orders_v2",
                "seller_id": int(SELLER),
                "resource": "/orders/2000018837474638",
            }
        ).encode("utf-8")
        self.headers = headers
        self.acked = False
        self.nacks: list[bool] = []

    async def ack(self) -> None:
        self.acked = True

    async def nack(self, *, requeue: bool = False) -> None:
        self.nacks.append(requeue)


async def _wait_once(headers: dict[str, Any]) -> tuple[FakeMessage, dict[str, Any]]:
    runner = SheetsAmqpConsumerRunner(rabbitmq_url="amqp://unit-test", handler=WaitingHandler())
    published: list[dict[str, Any]] = []

    async def publish(body: bytes, **kwargs: Any) -> None:
        published.append(kwargs)

    runner._publish_retry_delay = publish  # type: ignore[method-assign,assignment]
    message = FakeMessage(headers)
    await runner.handle_message(message)
    assert len(published) == 1
    return message, published[0]


@pytest.mark.asyncio
async def test_policy_wait_counts_waits_and_keeps_the_short_delay_at_first() -> None:
    message, published = await _wait_once({})

    assert message.acked is True and message.nacks == []
    assert published["delay_ms"] == 5_000
    assert published["mandatory"] is True
    assert published["headers"][POLICY_WAIT_HEADER] == 1
    assert published["headers"][RETRY_ATTEMPT_HEADER] == 0


@pytest.mark.asyncio
async def test_policy_wait_backs_off_to_ten_minutes_after_one_minute_of_waits() -> None:
    _, published = await _wait_once({POLICY_WAIT_HEADER: 12, RETRY_ATTEMPT_HEADER: 2})

    assert published["delay_ms"] == 600_000
    assert published["headers"][POLICY_WAIT_HEADER] == 13
    # Policy waits are not provider failures: the attempt count is preserved.
    assert published["headers"][RETRY_ATTEMPT_HEADER] == 2


@pytest.mark.asyncio
async def test_malformed_policy_wait_header_restarts_the_count() -> None:
    _, published = await _wait_once({POLICY_WAIT_HEADER: "many"})

    assert published["delay_ms"] == 5_000
    assert published["headers"][POLICY_WAIT_HEADER] == 1
