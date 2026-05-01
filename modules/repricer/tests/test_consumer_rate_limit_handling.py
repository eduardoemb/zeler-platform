from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from zeler_platform_core.clients.meli_gateway_client import GatewayRateLimitError
from zeler_repricer import consumer
from zeler_repricer.consumer import RepricerAmqpConsumerRunner, RepricerEvent


class FakeHandler:
    def __init__(self, *, error: Exception) -> None:
        self.error = error
        self.events: list[RepricerEvent] = []

    async def handle(self, event: RepricerEvent) -> str:
        self.events.append(event)
        raise self.error


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


class LogSpy:
    def __init__(self) -> None:
        self.warning_calls: list[tuple[str, dict[str, Any]]] = []

    def warning(self, event: str, **fields: Any) -> None:
        self.warning_calls.append((event, fields))


class FakeRetryDelayPublisher:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def publish_delay(self, message_body: bytes, queue_name: str, *, delay_ms: int) -> None:
        self.calls.append({"body": message_body, "queue_name": queue_name, "delay_ms": delay_ms})


@pytest.mark.asyncio
async def test_gateway_rate_limit_sleeps_then_requeues_with_retry_after_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleep_calls: list[int] = []

    async def fake_sleep(seconds: int) -> None:
        sleep_calls.append(seconds)

    log_spy = LogSpy()
    monkeypatch.setattr(consumer, "logger", log_spy, raising=False)
    monkeypatch.setattr("zeler_repricer.consumer.asyncio.sleep", fake_sleep)
    handler = FakeHandler(error=_rate_limit_error(retry_after_seconds=5))
    publisher = FakeRetryDelayPublisher()
    runner = RepricerAmqpConsumerRunner(
        rabbitmq_url="amqp://unit-test", handler=handler, retry_delay_publisher=publisher
    )
    message = FakeMessage(_valid_payload(resource="/items/MLA429"))

    await runner.handle_message(message)

    assert sleep_calls == []
    assert message.acked is True
    assert message.nacks == []
    assert publisher.calls == [
        {"body": message.body, "queue_name": "zeler.repricer.items", "delay_ms": 5000}
    ]
    assert log_spy.warning_calls == [
        (
            "worker.message.requeued",
            {
                "event_id": "evt-1",
                "seller_id": 123456789,
                "resource_path": "/items/MLA429",
                "attempt": 1,
                "error_type": "GatewayRateLimitError",
                "retry_after": 5,
            },
        )
    ]


def _rate_limit_error(*, retry_after_seconds: int) -> GatewayRateLimitError:
    request = httpx.Request("POST", "http://gateway:8080/proxy/meli/items/MLA429/prices")
    response = httpx.Response(429, request=request)
    return GatewayRateLimitError(retry_after_seconds=retry_after_seconds, response=response)


def _valid_payload(*, resource: str = "items/MLA123") -> dict[str, Any]:
    return {
        "event_id": "evt-1",
        "event_type": "items.price_updated",
        "seller_id": 123456789,
        "resource": resource,
    }
