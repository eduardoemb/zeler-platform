from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest

from zeler_repricer.consumer import RepricerAmqpConsumerRunner, RepricerEvent


class FakeHandler:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.events: list[RepricerEvent] = []

    async def handle(self, event: RepricerEvent) -> str:
        self.events.append(event)
        if self.error is not None:
            raise self.error
        return "set_price"


class FakeMessage:
    def __init__(
        self,
        body: dict[str, Any] | bytes,
        *,
        headers: dict[str, object] | None = None,
    ) -> None:
        self.body = json.dumps(body).encode("utf-8") if isinstance(body, dict) else body
        self.headers = headers or {}
        self.acked = False
        self.nacks: list[bool] = []

    async def ack(self) -> None:
        self.acked = True

    async def nack(self, *, requeue: bool = False) -> None:
        self.nacks.append(requeue)


class FakeExchange:
    def __init__(self) -> None:
        self.bindings: list[tuple[FakeQueue, str]] = []


class FakeQueue:
    def __init__(self) -> None:
        self.bindings: list[tuple[FakeExchange, str]] = []
        self.consumer: Any = None

    async def bind(self, exchange: FakeExchange, routing_key: str) -> None:
        self.bindings.append((exchange, routing_key))

    async def consume(self, callback: Any) -> None:
        self.consumer = callback


class FakeChannel:
    def __init__(self) -> None:
        self.qos: list[int] = []
        self.exchange = FakeExchange()
        self.queue = FakeQueue()
        self.declared_exchanges: list[tuple[str, Any, bool]] = []
        self.declared_queues: list[tuple[str, bool, dict[str, object]]] = []

    async def set_qos(self, *, prefetch_count: int) -> None:
        self.qos.append(prefetch_count)

    async def declare_exchange(
        self, name: str, exchange_type: Any, *, durable: bool
    ) -> FakeExchange:
        self.declared_exchanges.append((name, exchange_type, durable))
        return self.exchange

    async def declare_queue(
        self, name: str, *, durable: bool, arguments: dict[str, object]
    ) -> FakeQueue:
        self.declared_queues.append((name, durable, arguments))
        return self.queue


class FakeConnection:
    def __init__(self) -> None:
        self.channel_obj = FakeChannel()
        self.closed = False

    async def channel(self) -> FakeChannel:
        return self.channel_obj

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_runner_declares_queue_and_binds_manifest_routing_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection()
    calls: list[str] = []

    async def fake_connect(url: str) -> FakeConnection:
        calls.append(url)
        return connection

    monkeypatch.setattr("zeler_repricer.consumer.aio_pika.connect_robust", fake_connect)

    runner = RepricerAmqpConsumerRunner(
        rabbitmq_url="amqp://unit-test",
        handler=FakeHandler(),
        manifest_path="modules/repricer/manifest.yaml",
    )

    await runner.start()

    assert calls == ["amqp://unit-test"]
    channel = connection.channel_obj
    assert channel.qos == [10]
    assert channel.declared_exchanges == [("meli.events", runner.exchange_type_topic, True)]
    assert channel.declared_queues == [
        (
            "zeler.repricer.items",
            True,
            {"x-dead-letter-exchange": "zeler.repricer.items.dlx"},
        )
    ]
    assert "x-delivery-limit" not in channel.declared_queues[0][2]
    assert [routing_key for _, routing_key in channel.queue.bindings] == [
        "items.*",
        "items.price_updated",
    ]
    assert channel.queue.consumer.__self__ is runner
    assert channel.queue.consumer.__func__ is runner.handle_message.__func__


@pytest.mark.asyncio
async def test_runner_passes_message_body_and_idempotency_header_to_handler() -> None:
    handler = FakeHandler()
    runner = RepricerAmqpConsumerRunner(rabbitmq_url="amqp://unit-test", handler=handler)
    message = FakeMessage(
        {
            "event_id": "evt-1",
            "event_type": "items.price_updated",
            "seller_id": 123456789,
            "resource": "items/MLA123/prices",
            "buybox_price": "181.50",
        },
        headers={"idempotency_key": "idem-header"},
    )

    await runner.handle_message(message)

    assert message.acked is True
    assert message.nacks == []
    assert handler.events == [
        RepricerEvent(
            event_id="evt-1",
            event_type="items.price_updated",
            seller_id=123456789,
            resource="items/MLA123/prices",
            idempotency_key="idem-header",
            buybox_price=Decimal("181.50"),
        )
    ]


@pytest.mark.asyncio
async def test_runner_requeues_retryable_handler_failures() -> None:
    runner = RepricerAmqpConsumerRunner(
        rabbitmq_url="amqp://unit-test",
        handler=FakeHandler(error=RuntimeError("gateway_backpressure")),
    )
    message = FakeMessage(_valid_payload(), headers={"idempotency_key": "idem-1"})

    await runner.handle_message(message)

    assert message.acked is False
    assert message.nacks == [True]


@pytest.mark.asyncio
async def test_handle_message_nacks_poison_message_without_requeue() -> None:
    handler = FakeHandler()
    runner = RepricerAmqpConsumerRunner(rabbitmq_url="amqp://unit-test", handler=handler)
    message = FakeMessage(
        _valid_payload(),
        headers={"idempotency_key": "idem-1", "x-death": [{"count": 5}]},
    )

    await runner.handle_message(message)

    assert message.acked is False
    assert message.nacks == [False]
    assert handler.events == []


@pytest.mark.asyncio
async def test_runner_dead_letters_terminal_decode_failures_without_handler_call() -> None:
    handler = FakeHandler()
    runner = RepricerAmqpConsumerRunner(rabbitmq_url="amqp://unit-test", handler=handler)
    message = FakeMessage(b"not-json", headers={"idempotency_key": "idem-1"})

    await runner.handle_message(message)

    assert handler.events == []
    assert message.acked is False
    assert message.nacks == [False]


def _valid_payload() -> dict[str, Any]:
    return {
        "event_id": "evt-1",
        "event_type": "items.price_updated",
        "seller_id": 123456789,
        "resource": "items/MLA123/prices",
    }
