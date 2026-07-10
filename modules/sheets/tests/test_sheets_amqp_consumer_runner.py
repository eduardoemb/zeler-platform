from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import aio_pika
import httpx
import pytest

from zeler_platform_core.clients.meli_gateway_client import GatewayRateLimitError
from zeler_platform_core.devoluciones_readiness import (
    DevolucionesLeaseConflictError,
    DevolucionesLeaseLostError,
)
from zeler_platform_core.runtime.manifest import validate_manifest
from zeler_platform_core.runtime.retry_delay import RETRY_ATTEMPT_HEADER
from zeler_sheets import consumer
from zeler_sheets.consumer import (
    SHEETS_CLAIMS_QUEUE,
    SHEETS_EVENTS_DLQ,
    SHEETS_EVENTS_DLX,
    SHEETS_EVENTS_QUEUE,
    SHEETS_REPLAY_EXCHANGE,
    SheetsAmqpConsumerRunner,
    SheetsEvent,
    _sheets_event_from_message,
    _sheets_idempotency_key,
)
from zeler_sheets.google_errors import RetryableGoogleSheetsApiError

_FAKES_SPEC = importlib.util.spec_from_file_location(
    "sheets_amqp_fakes", Path(__file__).with_name("_amqp_fakes.py")
)
assert _FAKES_SPEC is not None and _FAKES_SPEC.loader is not None
_FAKES_MODULE = importlib.util.module_from_spec(_FAKES_SPEC)
_FAKES_SPEC.loader.exec_module(_FAKES_MODULE)
FakeConnection = _FAKES_MODULE.FakeConnection
FakeMessage = _FAKES_MODULE.FakeMessage


class FakeHandler:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.events: list[SheetsEvent] = []

    async def handle(self, event: SheetsEvent) -> str:
        self.events.append(event)
        if self.error is not None:
            raise self.error
        return "appended"


class FakeRetryDelayPublisher:
    def __init__(self, _channel: object) -> None:
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


@pytest.mark.asyncio
async def test_sheets_runner_declares_queue_with_dlx_and_binds_manifest_routing_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection()
    calls: list[str] = []

    async def fake_connect(url: str) -> Any:
        calls.append(url)
        return connection

    monkeypatch.setattr("zeler_sheets.consumer.aio_pika.connect_robust", fake_connect)

    runner = SheetsAmqpConsumerRunner(
        rabbitmq_url="amqp://unit-test",
        handler=FakeHandler(),
        manifest_path="modules/sheets/manifest.yaml",
    )

    await runner.start()

    assert calls == ["amqp://unit-test"]
    assert connection.channel_kwargs == [{"on_return_raises": True}]
    channel = connection.channel_obj
    assert channel.qos == [10]
    assert channel.declared_exchanges == [
        ("meli.events", runner.exchange_type_topic, True),
        (SHEETS_REPLAY_EXCHANGE, runner.exchange_type_topic, True),
        (SHEETS_EVENTS_DLX, aio_pika.ExchangeType.DIRECT, True),
    ]
    assert channel.declared_queues == [
        (
            SHEETS_EVENTS_DLQ,
            True,
            {},
        ),
        (
            SHEETS_EVENTS_QUEUE,
            True,
            {
                "x-dead-letter-exchange": SHEETS_EVENTS_DLX,
                "x-dead-letter-routing-key": SHEETS_EVENTS_DLQ,
            },
        ),
    ]
    assert "x-delivery-limit" not in channel.declared_queues[1][2]
    assert channel.queues[SHEETS_EVENTS_DLQ].bindings == [
        (channel.exchanges[SHEETS_EVENTS_DLX], SHEETS_EVENTS_DLQ)
    ]
    assert channel.queues[SHEETS_EVENTS_QUEUE].bindings == [
        (channel.exchanges["meli.events"], "items.*"),
        (channel.exchanges[SHEETS_REPLAY_EXCHANGE], "items.*"),
        (channel.exchanges["meli.events"], "orders.*"),
        (channel.exchanges[SHEETS_REPLAY_EXCHANGE], "orders.*"),
        (channel.exchanges["meli.events"], "shipments.*"),
        (channel.exchanges[SHEETS_REPLAY_EXCHANGE], "shipments.*"),
        (channel.exchanges["meli.events"], "questions.*"),
        (channel.exchanges[SHEETS_REPLAY_EXCHANGE], "questions.*"),
    ]
    assert channel.queues[SHEETS_EVENTS_QUEUE].consumer.__self__ is runner
    assert channel.queues[SHEETS_EVENTS_QUEUE].consumer.__func__ is runner.handle_message.__func__
    assert channel.passive_queues == [SHEETS_CLAIMS_QUEUE]
    assert channel.queues[SHEETS_CLAIMS_QUEUE].bindings == []
    assert channel.queues[SHEETS_CLAIMS_QUEUE].consumer.__self__ is runner
    assert (
        channel.queues[SHEETS_CLAIMS_QUEUE].consumer.__func__
        is runner.handle_claims_message.__func__
    )


def test_sheets_manifest_registers_claims_as_externally_bound_passive_consumer() -> None:
    manifest = validate_manifest("modules/sheets/manifest.yaml")

    assert manifest.routing_keys == ["items.*", "orders.*", "shipments.*", "questions.*"]
    assert [consumer.model_dump() for consumer in manifest.passive_consumers] == [
        {
            "queue_name": SHEETS_CLAIMS_QUEUE,
            "routing_keys": ["claims.updated"],
            "externally_bound": True,
        }
    ]


def test_sheets_manifest_subscribes_to_questions_and_allows_question_fetch_scope() -> None:
    manifest = validate_manifest("modules/sheets/manifest.yaml")

    assert "questions.*" in manifest.routing_keys
    assert "GET /questions/*" in manifest.allowed_meli_scopes


@pytest.mark.asyncio
async def test_sheets_runner_start_wires_default_retry_delay_publisher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection()

    async def fake_connect(_url: str) -> Any:
        return connection

    monkeypatch.setattr("zeler_sheets.consumer.aio_pika.connect_robust", fake_connect)
    monkeypatch.setattr(consumer, "RetryDelayPublisher", FakeRetryDelayPublisher, raising=False)
    runner = SheetsAmqpConsumerRunner(
        rabbitmq_url="amqp://unit-test",
        handler=FakeHandler(
            error=RetryableGoogleSheetsApiError("quota exceeded", retry_after_seconds=9)
        ),
    )
    message = FakeMessage(_valid_payload())

    await runner.start()
    await runner.handle_message(message)
    retry_delay_publisher = runner._retry_delay_publisher  # noqa: SLF001 - asserts runtime wiring
    assert retry_delay_publisher is not None

    assert message.acked is True
    assert message.nacks == []
    assert retry_delay_publisher.calls == [
        {
            "body": message.body,
            "queue_name": "zeler.sheets.events",
            "delay_ms": 9000,
            "headers": {RETRY_ATTEMPT_HEADER: 1},
        }
    ]


@pytest.mark.asyncio
async def test_claims_consumer_publishes_transient_failure_to_dedicated_retry_ladder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection()

    async def fake_connect(_url: str) -> Any:
        return connection

    response = httpx.Response(429, request=httpx.Request("GET", "https://example.test"))
    handler = FakeHandler(error=GatewayRateLimitError(retry_after_seconds=7, response=response))
    monkeypatch.setattr("zeler_sheets.consumer.aio_pika.connect_robust", fake_connect)
    runner = SheetsAmqpConsumerRunner(rabbitmq_url="amqp://unit-test", handler=handler)
    message = FakeMessage(
        {
            "event_id": "claim-event-1",
            "event_type": "claims.updated",
            "seller_id": 123456789,
            "resource": "/post-purchase/v1/claims/claim-1",
        }
    )

    await runner.start()
    await runner.handle_claims_message(message)

    assert message.acked is True
    assert message.nacks == []
    assert len(connection.channel_obj.default_exchange.published) == 1
    outgoing, routing_key, mandatory = connection.channel_obj.default_exchange.published[0]
    assert outgoing.body == message.body
    assert outgoing.headers == {RETRY_ATTEMPT_HEADER: 1}
    assert routing_key == "zeler.sheets.claims.retry.30s"
    assert mandatory is True


@pytest.mark.asyncio
async def test_unroutable_mandatory_claims_retry_never_acks_source_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection()

    async def fake_connect(_url: str) -> Any:
        return connection

    response = httpx.Response(429, request=httpx.Request("GET", "https://example.test"))
    handler = FakeHandler(error=GatewayRateLimitError(retry_after_seconds=7, response=response))
    monkeypatch.setattr("zeler_sheets.consumer.aio_pika.connect_robust", fake_connect)
    runner = SheetsAmqpConsumerRunner(rabbitmq_url="amqp://unit-test", handler=handler)
    message = FakeMessage(_valid_claim_payload())

    await runner.start()
    connection.channel_obj.default_exchange.publish_error = RuntimeError(
        "unroutable mandatory retry"
    )
    await runner.handle_claims_message(message)

    assert message.acked is False
    assert message.nacks == [True]
    assert connection.channel_obj.default_exchange.published[0][2] is True


@pytest.mark.asyncio
async def test_claims_lease_retry_ladder_advances_then_exhausts_to_dlq(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection()

    async def fake_connect(_url: str) -> Any:
        return connection

    handler = FakeHandler(error=DevolucionesLeaseConflictError("lease busy"))
    monkeypatch.setattr("zeler_sheets.consumer.aio_pika.connect_robust", fake_connect)
    runner = SheetsAmqpConsumerRunner(rabbitmq_url="amqp://unit-test", handler=handler)
    await runner.start()

    expected_routes = [
        "zeler.sheets.claims.retry.1s",
        "zeler.sheets.claims.retry.5s",
        "zeler.sheets.claims.retry.30s",
        "zeler.sheets.claims.retry.2m",
        "zeler.sheets.claims.retry.10m",
    ]
    for attempt, expected_route in enumerate(expected_routes):
        headers = {RETRY_ATTEMPT_HEADER: attempt} if attempt else None
        message = FakeMessage(_valid_claim_payload(), headers=headers)

        await runner.handle_claims_message(message)

        assert message.acked is True
        assert message.nacks == []
        outgoing, routing_key, mandatory = connection.channel_obj.default_exchange.published[-1]
        assert outgoing.headers == {RETRY_ATTEMPT_HEADER: attempt + 1}
        assert routing_key == expected_route
        assert mandatory is True

    published_before_exhaustion = len(connection.channel_obj.default_exchange.published)
    handled_before_exhaustion = len(handler.events)
    exhausted = FakeMessage(
        _valid_claim_payload(),
        headers={RETRY_ATTEMPT_HEADER: len(expected_routes)},
    )

    await runner.handle_claims_message(exhausted)

    assert exhausted.acked is False
    assert exhausted.nacks == [False]
    assert len(connection.channel_obj.default_exchange.published) == published_before_exhaustion
    assert len(handler.events) == handled_before_exhaustion


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        DevolucionesLeaseLostError("lease lost"),
        httpx.HTTPStatusError(
            "upstream unavailable",
            request=httpx.Request("GET", "https://example.test"),
            response=httpx.Response(
                503,
                request=httpx.Request("GET", "https://example.test"),
            ),
        ),
        httpx.ConnectError(
            "gateway unavailable",
            request=httpx.Request("GET", "https://example.test"),
        ),
    ],
)
async def test_claims_transient_failures_never_direct_requeue_on_first_attempt(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    connection = FakeConnection()

    async def fake_connect(_url: str) -> Any:
        return connection

    monkeypatch.setattr("zeler_sheets.consumer.aio_pika.connect_robust", fake_connect)
    runner = SheetsAmqpConsumerRunner(
        rabbitmq_url="amqp://unit-test",
        handler=FakeHandler(error=error),
    )
    message = FakeMessage(_valid_claim_payload())

    await runner.start()
    await runner.handle_claims_message(message)

    assert message.acked is True
    assert message.nacks == []
    outgoing, routing_key, mandatory = connection.channel_obj.default_exchange.published[0]
    assert outgoing.headers == {RETRY_ATTEMPT_HEADER: 1}
    assert routing_key == "zeler.sheets.claims.retry.1s"
    assert mandatory is True


@pytest.mark.asyncio
async def test_claims_x_death_advances_dedicated_retry_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection()

    async def fake_connect(_url: str) -> Any:
        return connection

    monkeypatch.setattr("zeler_sheets.consumer.aio_pika.connect_robust", fake_connect)
    runner = SheetsAmqpConsumerRunner(
        rabbitmq_url="amqp://unit-test",
        handler=FakeHandler(error=DevolucionesLeaseLostError("lease lost")),
    )
    message = FakeMessage(
        _valid_claim_payload(),
        headers={"x-death": [{"queue": SHEETS_CLAIMS_QUEUE, "count": 2}]},
    )

    await runner.start()
    await runner.handle_claims_message(message)

    outgoing, routing_key, _mandatory = connection.channel_obj.default_exchange.published[0]
    assert outgoing.headers == {RETRY_ATTEMPT_HEADER: 3}
    assert routing_key == "zeler.sheets.claims.retry.30s"
    assert message.acked is True
    assert message.nacks == []


@pytest.mark.asyncio
async def test_sheets_runner_acks_message_on_successful_handler_return() -> None:
    handler = FakeHandler()
    runner = SheetsAmqpConsumerRunner(rabbitmq_url="amqp://unit-test", handler=handler)
    message = FakeMessage(_valid_payload(), headers={"idempotency_key": "idem-header"})

    await runner.handle_message(message)

    assert message.acked is True
    assert message.nacks == []
    assert handler.events == [
        SheetsEvent(
            event_id="evt-1",
            event_type="items.updated",
            seller_id=123456789,
            resource="items/MLA123",
            idempotency_key="idem-header",
        )
    ]


@pytest.mark.asyncio
async def test_sheets_runner_nacks_without_requeue_on_runtime_error() -> None:
    runner = SheetsAmqpConsumerRunner(
        rabbitmq_url="amqp://unit-test",
        handler=FakeHandler(error=RuntimeError("gateway_backpressure")),
    )
    message = FakeMessage(_valid_payload(), headers={"idempotency_key": "idem-1"})

    await runner.handle_message(message)

    assert message.acked is False
    assert message.nacks == [False]


@pytest.mark.asyncio
async def test_sheets_runner_nacks_poison_message_without_requeue() -> None:
    handler = FakeHandler()
    runner = SheetsAmqpConsumerRunner(rabbitmq_url="amqp://unit-test", handler=handler)
    message = FakeMessage(
        _valid_payload(),
        headers={"idempotency_key": "idem-1", "x-death": [{"count": 5}]},
    )

    await runner.handle_message(message)

    assert message.acked is False
    assert message.nacks == [False]
    assert handler.events == []


@pytest.mark.asyncio
async def test_sheets_runner_nacks_without_requeue_on_decode_error() -> None:
    handler = FakeHandler()
    runner = SheetsAmqpConsumerRunner(rabbitmq_url="amqp://unit-test", handler=handler)
    message = FakeMessage(b"not-json", headers={"idempotency_key": "idem-1"})

    await runner.handle_message(message)

    assert handler.events == []
    assert message.acked is False
    assert message.nacks == [False]


@pytest.mark.asyncio
async def test_sheets_runner_close_is_idempotent_when_called_twice(
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
    monkeypatch.setattr("zeler_sheets.consumer.aio_pika.connect_robust", fake_connect)
    runner = SheetsAmqpConsumerRunner(rabbitmq_url="amqp://unit-test", handler=FakeHandler())

    await runner.start()
    await runner.close()
    await runner.close()

    assert connection.closed is True
    assert close_calls == 1


def _valid_payload() -> dict[str, Any]:
    return {
        "event_id": "evt-1",
        "event_type": "items.updated",
        "seller_id": 123456789,
        "resource": "items/MLA123",
    }


def _valid_claim_payload() -> dict[str, Any]:
    return {
        "event_id": "claim-event-1",
        "event_type": "claims.updated",
        "seller_id": 123456789,
        "resource": "/post-purchase/v1/claims/claim-1",
    }


def test_sheets_event_from_message_decodes_valid_payload_into_sheets_event() -> None:
    message = FakeMessage(
        {
            "event_id": "evt-sheets-1",
            "event_type": "orders.updated",
            "seller_id": "123456789",
            "resource": "/orders/order-1",
            "idempotency_key": "payload-key",
        }
    )

    event = _sheets_event_from_message(message)

    assert event == SheetsEvent(
        event_id="evt-sheets-1",
        event_type="orders.updated",
        seller_id=123456789,
        resource="/orders/order-1",
        idempotency_key="payload-key",
    )


def test_sheets_idempotency_key_prefers_header_over_payload_over_event_id() -> None:
    payload = {"event_id": "evt-fallback", "idempotency_key": "payload-key"}

    assert (
        _sheets_idempotency_key(
            FakeMessage(payload, headers={"idempotency_key": "header-key"}), payload
        )
        == "header-key"
    )
    assert _sheets_idempotency_key(FakeMessage(payload), payload) == "payload-key"
    assert (
        _sheets_idempotency_key(
            FakeMessage({"event_id": "evt-fallback"}), {"event_id": "evt-fallback"}
        )
        == "evt-fallback"
    )
