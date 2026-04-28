from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from zeler_fulldock import consumer
from zeler_fulldock.consumer import FulldockAmqpConsumerRunner, FulldockEvent
from zeler_platform_core.clients.meli_gateway_client import GatewayRateLimitError


class FakeHandler:
    def __init__(self, *, error: Exception) -> None:
        self.error = error
        self.events: list[FulldockEvent] = []

    async def handle(self, event: FulldockEvent) -> str:
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


@pytest.mark.asyncio
async def test_gateway_rate_limit_sleeps_then_requeues_with_retry_after_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleep_calls: list[int] = []

    async def fake_sleep(seconds: int) -> None:
        sleep_calls.append(seconds)

    log_spy = LogSpy()
    monkeypatch.setattr(consumer, "logger", log_spy, raising=False)
    monkeypatch.setattr("zeler_fulldock.consumer.asyncio.sleep", fake_sleep)
    handler = FakeHandler(error=_rate_limit_error(retry_after_seconds=5))
    runner = FulldockAmqpConsumerRunner(rabbitmq_url="amqp://unit-test", handler=handler)
    message = FakeMessage(_valid_payload(resource="/shipments/429"))

    await runner.handle_message(message)

    assert sleep_calls == [5]
    assert message.acked is False
    assert message.nacks == [True]
    assert log_spy.warning_calls == [
        (
            "worker.message.requeued",
            {
                "event_id": "evt-1",
                "seller_id": 123456789,
                "resource_path": "/shipments/429",
                "attempt": 1,
                "error_type": "GatewayRateLimitError",
                "retry_after": 5,
            },
        )
    ]


def _rate_limit_error(*, retry_after_seconds: int) -> GatewayRateLimitError:
    request = httpx.Request("GET", "http://gateway:8080/proxy/meli/shipments/429")
    response = httpx.Response(429, request=request)
    return GatewayRateLimitError(retry_after_seconds=retry_after_seconds, response=response)


def _valid_payload(*, resource: str = "shipments/123") -> dict[str, Any]:
    return {
        "event_id": "evt-1",
        "event_type": "shipments.updated",
        "seller_id": 123456789,
        "resource": resource,
    }
