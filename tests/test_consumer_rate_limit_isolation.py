from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from zeler_platform_core.clients.meli_gateway_client import GatewayRateLimitError


class FakeRetryDelayPublisher:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def publish_delay(
        self,
        message_body: bytes,
        queue_name: str,
        *,
        delay_ms: int,
        headers: dict[str, object] | None = None,
    ) -> None:
        self.calls.append(
            {
                "body": message_body,
                "queue_name": queue_name,
                "delay_ms": delay_ms,
                "headers": headers,
            }
        )


class FakeMessage:
    def __init__(self, body: dict[str, Any]) -> None:
        self.body = json.dumps(body).encode("utf-8")
        self.headers: dict[str, Any] = {}
        self.acked = False
        self.nacks: list[bool] = []

    async def ack(self) -> None:
        self.acked = True

    async def nack(self, *, requeue: bool = False) -> None:
        self.nacks.append(requeue)


class RateLimitThenOkHandler:
    def __init__(self) -> None:
        self.calls = 0

    async def handle(self, _event: object) -> str:
        self.calls += 1
        if self.calls == 1:
            raise _rate_limit_error(retry_after_seconds=7)
        return "ok"


@pytest.mark.parametrize(
    ("runner_type", "payload", "queue_name"),
    [
        pytest.param(
            "zeler_repricer.consumer.RepricerAmqpConsumerRunner",
            {
                "event_id": "evt-1",
                "event_type": "items.price_updated",
                "seller_id": 123,
                "resource": "/items/1",
            },
            "zeler.repricer.items",
            id="repricer",
        ),
        pytest.param(
            "zeler_sheets.consumer.SheetsAmqpConsumerRunner",
            {
                "event_id": "evt-1",
                "event_type": "items.updated",
                "seller_id": 123,
                "resource": "/items/1",
            },
            "zeler.sheets.events",
            id="sheets",
        ),
        pytest.param(
            "zeler_autoreply.consumer.AutoreplyAmqpConsumerRunner",
            {
                "event_id": "evt-1",
                "event_type": "questions.new",
                "seller_id": 123,
                "resource": "/questions/1",
            },
            "zeler.autoreply.events",
            id="autoreply",
        ),
        pytest.param(
            "zeler_fulldock.consumer.FulldockAmqpConsumerRunner",
            {
                "event_id": "evt-1",
                "event_type": "items.updated",
                "seller_id": 123,
                "resource": "/items/1",
            },
            "zeler.fulldock.events",
            id="fulldock",
        ),
    ],
)
@pytest.mark.asyncio
async def test_429_publishes_to_delay_queue_and_acks(
    runner_type: str,
    payload: dict[str, object],
    queue_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module_name, class_name = runner_type.rsplit(".", 1)
    module = __import__(module_name, fromlist=[class_name])
    runner_class = getattr(module, class_name)
    sleep_called = False

    async def fail_sleep(_seconds: int) -> None:
        nonlocal sleep_called
        sleep_called = True
        raise AssertionError("429 path must not sleep")

    monkeypatch.setattr(f"{module_name}.asyncio.sleep", fail_sleep)
    publisher = FakeRetryDelayPublisher()
    runner = runner_class(
        rabbitmq_url="amqp://unit-test",
        handler=RateLimitThenOkHandler(),
        retry_delay_publisher=publisher,
    )
    message = FakeMessage(payload)

    await runner.handle_message(message)

    assert sleep_called is False
    assert message.acked is True
    assert message.nacks == []
    expected_headers = {"x-zeler-retry-attempt": 1} if queue_name == "zeler.sheets.events" else None
    assert publisher.calls == [
        {
            "body": message.body,
            "queue_name": queue_name,
            "delay_ms": 7000,
            "headers": expected_headers,
        }
    ]


@pytest.mark.asyncio
async def test_other_messages_not_blocked_by_429() -> None:
    from zeler_repricer.consumer import RepricerAmqpConsumerRunner

    publisher = FakeRetryDelayPublisher()
    handler = RateLimitThenOkHandler()
    runner = RepricerAmqpConsumerRunner(
        rabbitmq_url="amqp://unit-test",
        handler=handler,
        retry_delay_publisher=publisher,
    )
    first = FakeMessage(
        {
            "event_id": "evt-1",
            "event_type": "items.price_updated",
            "seller_id": 123,
            "resource": "/items/1",
        }
    )
    second = FakeMessage(
        {
            "event_id": "evt-2",
            "event_type": "items.price_updated",
            "seller_id": 456,
            "resource": "/items/2",
        }
    )

    await runner.handle_message(first)
    await runner.handle_message(second)

    assert first.acked is True
    assert second.acked is True
    assert handler.calls == 2


def _rate_limit_error(*, retry_after_seconds: int) -> GatewayRateLimitError:
    request = httpx.Request("GET", "http://gateway/proxy/meli/items/1")
    response = httpx.Response(429, request=request)
    return GatewayRateLimitError(retry_after_seconds=retry_after_seconds, response=response)
