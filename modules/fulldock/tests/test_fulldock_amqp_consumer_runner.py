from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest
from aio_pika import ExchangeType

from zeler_fulldock.consumer import (
    FulldockAmqpConsumerRunner,
    FulldockEvent,
    _fulldock_event_from_message,
    _fulldock_idempotency_key,
)

_FAKES_SPEC = importlib.util.spec_from_file_location(
    "fulldock_amqp_fakes", Path(__file__).with_name("_amqp_fakes.py")
)
assert _FAKES_SPEC is not None and _FAKES_SPEC.loader is not None
_FAKES_MODULE = importlib.util.module_from_spec(_FAKES_SPEC)
_FAKES_SPEC.loader.exec_module(_FAKES_MODULE)
FakeConnection = _FAKES_MODULE.FakeConnection
FakeMessage = _FAKES_MODULE.FakeMessage


class FakeHandler:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.events: list[FulldockEvent] = []

    async def handle(self, event: FulldockEvent) -> str:
        self.events.append(event)
        if self.error is not None:
            raise self.error
        return "updated"


@pytest.mark.asyncio
async def test_fulldock_runner_declares_queue_with_dlx_and_binds_manifest_routing_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection()
    calls: list[str] = []

    async def fake_connect(url: str) -> Any:
        calls.append(url)
        return connection

    monkeypatch.setattr("zeler_fulldock.consumer.aio_pika.connect_robust", fake_connect)
    runner = FulldockAmqpConsumerRunner(
        rabbitmq_url="amqp://unit-test",
        handler=FakeHandler(),
        manifest_path="modules/fulldock/manifest.yaml",
    )

    await runner.start()

    assert calls == ["amqp://unit-test"]
    channel = connection.channel_obj
    assert channel.qos == [10]
    assert channel.declared_exchanges == [
        ("meli.events", runner.exchange_type_topic, True),
        ("zeler.fulldock.events.dlx", ExchangeType.DIRECT, True),
    ]
    assert channel.declared_queues == [
        (
            "zeler.fulldock.events.dlq",
            True,
            {},
        ),
        (
            "zeler.fulldock.events",
            True,
            {
                "x-dead-letter-exchange": "zeler.fulldock.events.dlx",
                "x-dead-letter-routing-key": "zeler.fulldock.events.dlq",
            },
        ),
    ]
    assert "x-delivery-limit" not in channel.declared_queues[1][2]
    fulldock_dlq = channel.queues_by_name["zeler.fulldock.events.dlq"]
    assert [routing_key for _, routing_key in fulldock_dlq.bindings] == [
        "zeler.fulldock.events.dlq",
    ]
    assert [routing_key for _, routing_key in channel.queue.bindings] == [
        "shipments.*",
        "stock_locations.*",
    ]
    assert channel.queue.consumer.__self__ is runner
    assert channel.queue.consumer.__func__ is runner.handle_message.__func__


@pytest.mark.asyncio
async def test_fulldock_runner_acks_message_on_successful_handler_return() -> None:
    handler = FakeHandler()
    runner = FulldockAmqpConsumerRunner(rabbitmq_url="amqp://unit-test", handler=handler)
    message = FakeMessage(_valid_payload(), headers={"idempotency_key": "idem-header"})

    await runner.handle_message(message)

    assert message.acked is True
    assert message.nacks == []
    assert handler.events == [
        FulldockEvent(
            event_id="evt-1",
            event_type="shipments.updated",
            seller_id=123456789,
            resource="/shipments/ship-1",
            idempotency_key="idem-header",
        )
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("event_type", "resource"),
    [
        ("items.updated", "/items/MLM1400005413"),
        ("items.price_updated", "/items/MLM3889269870/prices"),
    ],
)
async def test_fulldock_runner_acks_unsupported_item_events_without_handler(
    event_type: str,
    resource: str,
) -> None:
    handler = FakeHandler()
    runner = FulldockAmqpConsumerRunner(rabbitmq_url="amqp://unit-test", handler=handler)
    message = FakeMessage(
        {
            "event_id": "evt-unsupported-item",
            "event_type": event_type,
            "seller_id": 82453304,
            "resource": resource,
        },
        headers={"idempotency_key": "idem-unsupported-item"},
    )

    await runner.handle_message(message)

    assert message.acked is True
    assert message.nacks == []
    assert handler.events == []


@pytest.mark.asyncio
async def test_fulldock_runner_nacks_with_requeue_on_runtime_error() -> None:
    runner = FulldockAmqpConsumerRunner(
        rabbitmq_url="amqp://unit-test",
        handler=FakeHandler(error=RuntimeError("gateway_backpressure")),
    )
    message = FakeMessage(_valid_payload(), headers={"idempotency_key": "idem-1"})

    await runner.handle_message(message)

    assert message.acked is False
    assert message.nacks == [True]


@pytest.mark.asyncio
async def test_fulldock_runner_nacks_poison_message_without_requeue() -> None:
    handler = FakeHandler()
    runner = FulldockAmqpConsumerRunner(rabbitmq_url="amqp://unit-test", handler=handler)
    message = FakeMessage(
        _valid_payload(),
        headers={"idempotency_key": "idem-1", "x-death": [{"count": 5}]},
    )

    await runner.handle_message(message)

    assert message.acked is False
    assert message.nacks == [False]
    assert handler.events == []


@pytest.mark.asyncio
async def test_fulldock_runner_nacks_without_requeue_on_decode_error() -> None:
    handler = FakeHandler()
    runner = FulldockAmqpConsumerRunner(rabbitmq_url="amqp://unit-test", handler=handler)
    message = FakeMessage(b"not-json", headers={"idempotency_key": "idem-1"})

    await runner.handle_message(message)

    assert handler.events == []
    assert message.acked is False
    assert message.nacks == [False]


@pytest.mark.asyncio
async def test_fulldock_runner_close_is_idempotent_when_called_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection()
    close_calls = 0

    async def close_once() -> None:
        nonlocal close_calls
        close_calls += 1
        connection.closed = True

    async def fake_connect(url: str) -> Any:
        return connection

    connection.close = close_once
    monkeypatch.setattr("zeler_fulldock.consumer.aio_pika.connect_robust", fake_connect)
    runner = FulldockAmqpConsumerRunner(rabbitmq_url="amqp://unit-test", handler=FakeHandler())

    await runner.start()
    await runner.close()
    await runner.close()

    assert connection.closed is True
    assert close_calls == 1


def _valid_payload() -> dict[str, Any]:
    return {
        "event_id": "evt-1",
        "event_type": "shipments.updated",
        "seller_id": 123456789,
        "resource": "/shipments/ship-1",
    }


def test_fulldock_event_from_message_decodes_valid_payload_into_fulldock_event() -> None:
    message = FakeMessage(
        {
            "event_id": "evt-fulldock-1",
            "event_type": "items.updated",
            "seller_id": "123456789",
            "resource": "/items/MLA123",
            "idempotency_key": "payload-key",
        }
    )

    event = _fulldock_event_from_message(message)

    assert event == FulldockEvent(
        event_id="evt-fulldock-1",
        event_type="items.updated",
        seller_id=123456789,
        resource="/items/MLA123",
        idempotency_key="payload-key",
    )


def test_fulldock_idempotency_key_prefers_header_over_payload_over_event_id() -> None:
    payload = {"event_id": "evt-fallback", "idempotency_key": "payload-key"}

    assert (
        _fulldock_idempotency_key(
            FakeMessage(payload, headers={"idempotency_key": "header-key"}), payload
        )
        == "header-key"
    )
    assert _fulldock_idempotency_key(FakeMessage(payload), payload) == "payload-key"
    assert (
        _fulldock_idempotency_key(
            FakeMessage({"event_id": "evt-fallback"}), {"event_id": "evt-fallback"}
        )
        == "evt-fallback"
    )
