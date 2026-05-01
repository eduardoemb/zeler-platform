from __future__ import annotations

from typing import Any

import pytest

from zeler_autoreply.consumer import AutoreplyAmqpConsumerRunner
from zeler_fulldock.consumer import FulldockAmqpConsumerRunner
from zeler_repricer.consumer import RepricerAmqpConsumerRunner
from zeler_sheets.consumer import SheetsAmqpConsumerRunner


class DummyHandler:
    async def handle(self, event: Any) -> None:
        return None


class FakeMessage:
    body = b"not-json"
    headers: dict[str, Any] = {}

    def __init__(self) -> None:
        self.nacked = False

    async def nack(self, *, requeue: bool) -> None:
        self.nacked = True


class FakeQueue:
    def __init__(self) -> None:
        self.consumer: Any = None

    async def bind(self, exchange: Any, *, routing_key: str) -> None:
        return None

    async def consume(self, callback: Any) -> str:
        self.consumer = callback
        return "consumer-tag"


class FakeChannel:
    def __init__(self, queue: FakeQueue) -> None:
        self.queue = queue

    async def set_qos(self, *, prefetch_count: int) -> None:
        return None

    async def declare_exchange(self, *args: Any, **kwargs: Any) -> object:
        return object()

    async def declare_queue(self, *args: Any, **kwargs: Any) -> FakeQueue:
        return self.queue


class FakeConnection:
    def __init__(self, queue: FakeQueue) -> None:
        self.queue = queue
        self.closed = False

    async def channel(self) -> FakeChannel:
        return FakeChannel(self.queue)

    async def close(self) -> None:
        self.closed = True


RUNNERS = (
    ("zeler_repricer.consumer", RepricerAmqpConsumerRunner),
    ("zeler_sheets.consumer", SheetsAmqpConsumerRunner),
    ("zeler_autoreply.consumer", AutoreplyAmqpConsumerRunner),
    ("zeler_fulldock.consumer", FulldockAmqpConsumerRunner),
)


@pytest.mark.asyncio
@pytest.mark.parametrize(("module_name", "runner_cls"), RUNNERS)
async def test_consumer_sets_is_ready_after_consume_starts(
    monkeypatch: pytest.MonkeyPatch, module_name: str, runner_cls: type[Any]
) -> None:
    queue = FakeQueue()

    async def connect_robust(url: str) -> FakeConnection:
        return FakeConnection(queue)

    module = __import__(module_name, fromlist=["aio_pika"])
    monkeypatch.setattr(module.aio_pika, "connect_robust", connect_robust)
    runner = runner_cls(rabbitmq_url="amqp://test", handler=DummyHandler())

    await runner.start()

    assert runner.is_ready is True
    assert queue.consumer == runner.handle_message
    await runner.close()
    assert runner.is_ready is False


@pytest.mark.asyncio
@pytest.mark.parametrize(("module_name", "runner_cls"), RUNNERS)
async def test_heartbeat_advances_per_message(module_name: str, runner_cls: type[Any]) -> None:
    runner = runner_cls(rabbitmq_url="amqp://test", handler=DummyHandler())
    message = FakeMessage()

    await runner.handle_message(message)

    assert runner.last_heartbeat_at is not None
    assert message.nacked is True
