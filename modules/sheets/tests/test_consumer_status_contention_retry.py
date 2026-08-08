from __future__ import annotations

import importlib
import json
import sys
import types
from collections.abc import Iterator
from typing import Any, cast

import pytest

import zeler_sheets
from zeler_sheets.event_persistence import StatusObservationContentionError


@pytest.fixture
def consumer_module(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    _install_optional_runtime_stubs(monkeypatch)
    previous_consumer_module = sys.modules.pop("zeler_sheets.consumer", None)
    previous_package_consumer = getattr(zeler_sheets, "consumer", None)
    module = importlib.import_module("zeler_sheets.consumer")
    yield module
    sys.modules.pop("zeler_sheets.consumer", None)
    if previous_consumer_module is not None:
        sys.modules["zeler_sheets.consumer"] = previous_consumer_module
    if previous_package_consumer is not None:
        cast(Any, zeler_sheets).consumer = previous_package_consumer
    elif hasattr(zeler_sheets, "consumer"):
        delattr(zeler_sheets, "consumer")


def _install_optional_runtime_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    sheets_config = types.ModuleType("zeler_sheets.sheets_config")

    class SheetsSettings:
        pass

    cast(Any, sheets_config).SheetsSettings = SheetsSettings
    monkeypatch.setitem(sys.modules, "zeler_sheets.sheets_config", sheets_config)

    google_sheets_client = types.ModuleType("zeler_sheets.google_sheets_client")
    cast(Any, google_sheets_client).make_sheets_client = lambda *_args, **_kwargs: object()
    monkeypatch.setitem(sys.modules, "zeler_sheets.google_sheets_client", google_sheets_client)

    aio_pika = types.ModuleType("aio_pika")
    aio_pika_any = cast(Any, aio_pika)
    aio_pika_any.ExchangeType = types.SimpleNamespace(TOPIC="topic")
    aio_pika_any.DeliveryMode = types.SimpleNamespace(PERSISTENT=2)
    aio_pika_any.Message = lambda **_kwargs: object()
    aio_pika_any.connect_robust = None
    monkeypatch.setitem(sys.modules, "aio_pika", aio_pika)

    structlog = types.ModuleType("structlog")

    class _Logger:
        def info(self, *_args: Any, **_kwargs: Any) -> None: ...

        def warning(self, *_args: Any, **_kwargs: Any) -> None: ...

        def error(self, *_args: Any, **_kwargs: Any) -> None: ...

    cast(Any, structlog).get_logger = lambda _name=None: _Logger()
    monkeypatch.setitem(sys.modules, "structlog", structlog)

    motor = types.ModuleType("motor")
    motor_asyncio = types.ModuleType("motor.motor_asyncio")

    class AsyncIOMotorClient:
        pass

    cast(Any, motor_asyncio).AsyncIOMotorClient = AsyncIOMotorClient
    cast(Any, motor).motor_asyncio = motor_asyncio
    monkeypatch.setitem(sys.modules, "motor", motor)
    monkeypatch.setitem(sys.modules, "motor.motor_asyncio", motor_asyncio)


class FakeHandler:
    def __init__(self, *, error: Exception) -> None:
        self.error = error
        self.events: list[Any] = []

    async def handle(self, event: Any) -> str:
        self.events.append(event)
        raise self.error


class FakeMessage:
    def __init__(self, body: dict[str, Any], *, headers: dict[str, Any] | None = None) -> None:
        self.body = json.dumps(body).encode("utf-8")
        self.headers = headers or {}
        self.acked = False
        self.nacks: list[bool] = []

    async def ack(self) -> None:
        self.acked = True

    async def nack(self, *, requeue: bool = False) -> None:
        self.nacks.append(requeue)


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


class LogSpy:
    def __init__(self) -> None:
        self.warning_calls: list[tuple[str, dict[str, Any]]] = []
        self.error_calls: list[tuple[str, dict[str, Any]]] = []

    def warning(self, event: str, **fields: Any) -> None:
        self.warning_calls.append((event, fields))

    def error(self, event: str, **fields: Any) -> None:
        self.error_calls.append((event, fields))

    def info(self, _event: str, **_fields: Any) -> None:
        raise AssertionError("contention retry path must not ack as success")


@pytest.mark.asyncio
async def test_status_observation_contention_is_delayed_and_acked_without_dlq(
    consumer_module: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_spy = LogSpy()
    monkeypatch.setattr(consumer_module, "logger", log_spy, raising=False)
    handler = FakeHandler(error=StatusObservationContentionError("state CAS contention"))
    publisher = FakeRetryDelayPublisher()
    runner = consumer_module.SheetsAmqpConsumerRunner(
        rabbitmq_url="amqp://unit-test",
        handler=handler,
        retry_delay_publisher=publisher,
    )
    message = FakeMessage(_valid_payload(resource="/items/MLA-CONTENDED"))

    await runner.handle_message(message)

    assert message.acked is True
    assert message.nacks == []
    assert publisher.calls == [
        {
            "body": message.body,
            "queue_name": "zeler.sheets.events",
            "delay_ms": 1000,
            "headers": {consumer_module.RETRY_ATTEMPT_HEADER: 1},
        }
    ]
    assert log_spy.warning_calls == [
        (
            "worker.message.requeued",
            {
                "event_id": "evt-1",
                "seller_id": 123456789,
                "resource_path": "/items/MLA-CONTENDED",
                "attempt": 1,
                "error_type": "StatusObservationContentionError",
                "dlq_class": "transient_timeout",
            },
        )
    ]
    assert log_spy.error_calls == []


@pytest.mark.asyncio
async def test_status_observation_contention_requeues_when_delay_publisher_unavailable(
    consumer_module: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_spy = LogSpy()
    monkeypatch.setattr(consumer_module, "logger", log_spy, raising=False)
    handler = FakeHandler(error=StatusObservationContentionError("state CAS contention"))
    runner = consumer_module.SheetsAmqpConsumerRunner(
        rabbitmq_url="amqp://unit-test", handler=handler
    )
    message = FakeMessage(
        _valid_payload(resource="/items/MLA-CONTENDED"),
        headers={consumer_module.RETRY_ATTEMPT_HEADER: 2},
    )

    await runner.handle_message(message)

    assert message.acked is False
    assert message.nacks == [True]
    assert log_spy.warning_calls == [
        (
            "worker.message.requeued",
            {
                "event_id": "evt-1",
                "seller_id": 123456789,
                "resource_path": "/items/MLA-CONTENDED",
                "attempt": 3,
                "error_type": "StatusObservationContentionError",
                "dlq_class": "transient_timeout",
            },
        )
    ]
    assert log_spy.error_calls == []


def _valid_payload(*, resource: str = "items/MLA123") -> dict[str, Any]:
    return {
        "event_id": "evt-1",
        "event_type": "items.updated",
        "seller_id": 123456789,
        "resource": resource,
    }
