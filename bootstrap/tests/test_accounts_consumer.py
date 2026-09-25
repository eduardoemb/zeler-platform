from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from zeler_bootstrap.accounts_consumer import BootstrapAccountsConsumer


class FakeDispatcher:
    def __init__(self, result: str = "running", error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def handle_accounts_linked(self, event: dict[str, Any]) -> str:
        self.calls.append(event)
        if self.error is not None:
            raise self.error
        return self.result


class FakeMessage:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.actions: list[str] = []

    async def ack(self) -> None:
        self.actions.append("ack")

    async def nack(self, *, requeue: bool) -> None:
        self.actions.append(f"nack:{requeue}")

    async def reject(self, *, requeue: bool) -> None:
        self.actions.append(f"reject:{requeue}")


@pytest.mark.asyncio
@pytest.mark.parametrize("result", ["running", "skipped"])
async def test_acknowledges_only_durable_dispatch_decisions(result: str) -> None:
    dispatcher = FakeDispatcher(result)
    consumer = BootstrapAccountsConsumer("amqp://test", dispatcher, retry_delay_s=0)
    message = FakeMessage(json.dumps({"seller_id": "123"}).encode())

    await consumer.handle_message(message)

    assert dispatcher.calls == [{"seller_id": "123"}]
    assert message.actions == ["ack"]


@pytest.mark.asyncio
async def test_transient_dispatch_error_requeues_without_ack() -> None:
    consumer = BootstrapAccountsConsumer(
        "amqp://test", FakeDispatcher(error=RuntimeError("Cloud Run unavailable")), retry_delay_s=0
    )
    message = FakeMessage(b'{"seller_id":"123"}')

    await consumer.handle_message(message)

    assert message.actions == ["nack:True"]


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b"not-json", b"{}", b'{"seller_id": "abc"}'])
async def test_invalid_event_is_dead_lettered(body: bytes) -> None:
    dispatcher = FakeDispatcher()
    consumer = BootstrapAccountsConsumer("amqp://test", dispatcher, retry_delay_s=0)
    message = FakeMessage(body)

    await consumer.handle_message(message)

    assert dispatcher.calls == []
    assert message.actions == ["reject:False"]


@pytest.mark.asyncio
async def test_exhausted_dispatch_is_dead_lettered() -> None:
    consumer = BootstrapAccountsConsumer("amqp://test", FakeDispatcher("failed"), retry_delay_s=0)
    message = FakeMessage(b'{"seller_id":"123"}')

    await consumer.handle_message(message)

    assert message.actions == ["reject:False"]


@pytest.mark.asyncio
async def test_start_binds_durable_queue_before_reporting_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Queue:
        def __init__(self) -> None:
            self.bindings: list[tuple[str, str]] = []
            self.consumer: Any = None

        async def bind(self, exchange: Any, *, routing_key: str) -> None:
            self.bindings.append((exchange.name, routing_key))

        async def consume(self, callback: Any) -> None:
            self.consumer = callback

    class Exchange:
        def __init__(self, name: str) -> None:
            self.name = name

    class Channel:
        def __init__(self) -> None:
            self.queues: dict[str, Queue] = {}

        async def set_qos(self, *, prefetch_count: int) -> None:
            assert prefetch_count == 1

        async def declare_exchange(self, name: str, *_args: Any, **_kwargs: Any) -> Exchange:
            return Exchange(name)

        async def declare_queue(self, name: str, **_kwargs: Any) -> Queue:
            self.queues[name] = Queue()
            return self.queues[name]

    class Connection:
        def __init__(self) -> None:
            self.connected = asyncio.Event()
            self.connected.set()
            self.is_closed = False
            self.channel_ref = Channel()

        async def channel(self) -> Channel:
            return self.channel_ref

        async def close(self) -> None:
            self.is_closed = True

    connection = Connection()

    async def connect(_url: str) -> Connection:
        return connection

    monkeypatch.setattr("aio_pika.connect_robust", connect)
    consumer = BootstrapAccountsConsumer("amqp://test", FakeDispatcher())

    await consumer.start()

    queue = connection.channel_ref.queues["zeler.bootstrap.accounts"]
    assert queue.bindings == [("meli.events", "accounts.linked")]
    assert queue.consumer is not None
    assert consumer.is_ready is True
    await consumer.close()
    assert consumer.is_ready is False


@pytest.mark.asyncio
async def test_connection_failure_does_not_expose_broker_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_connection(_url: str) -> None:
        raise RuntimeError("amqp://credential-in-error")

    monkeypatch.setattr("aio_pika.connect_robust", fail_connection)
    consumer = BootstrapAccountsConsumer("amqp://private-connection", FakeDispatcher())

    with pytest.raises(RuntimeError, match="RabbitMQ unavailable") as caught:
        await consumer.start()

    assert "credential" not in str(caught.value)
    assert "private-connection" not in str(caught.value)
