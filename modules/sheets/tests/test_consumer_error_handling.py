from __future__ import annotations

from typing import Any

import httpx
import pytest

from zeler_platform_core.clients.meli_gateway_client import GatewayRateLimitError
from zeler_platform_core.devoluciones_readiness import DevolucionesLeaseConflictError
from zeler_platform_core.runtime.retry_delay import RETRY_ATTEMPT_HEADER
from zeler_sheets import consumer
from zeler_sheets.consumer import SheetsAmqpConsumerRunner, SheetsEvent
from zeler_sheets.google_errors import GoogleSheetsApiError, RetryableGoogleSheetsApiError


class FakeHandler:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.events: list[SheetsEvent] = []

    async def handle(self, event: SheetsEvent) -> str:
        self.events.append(event)
        if self.error is not None:
            raise self.error
        return "appended"


class FakeMessage:
    def __init__(
        self,
        body: dict[str, Any] | bytes | str,
        *,
        headers: dict[str, Any] | None = None,
    ) -> None:
        import json

        if isinstance(body, dict):
            self.body = json.dumps(body).encode("utf-8")
        elif isinstance(body, str):
            self.body = body.encode("utf-8")
        else:
            self.body = body
        self.headers = headers or {}
        self.acked = False
        self.nacks: list[bool] = []

    async def ack(self) -> None:
        self.acked = True

    async def nack(self, *, requeue: bool = False) -> None:
        self.nacks.append(requeue)


class LogSpy:
    def __init__(self) -> None:
        self.warning_calls: list[tuple[str, dict[str, Any]]] = []
        self.error_calls: list[tuple[str, dict[str, Any]]] = []
        self.info_calls: list[tuple[str, dict[str, Any]]] = []

    def warning(self, event: str, **fields: Any) -> None:
        self.warning_calls.append((event, fields))

    def error(self, event: str, **fields: Any) -> None:
        self.error_calls.append((event, fields))

    def info(self, event: str, **fields: Any) -> None:
        self.info_calls.append((event, fields))


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


@pytest.mark.asyncio
async def test_devoluciones_lease_conflict_is_requeued_instead_of_sent_to_dlq(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_spy = LogSpy()
    monkeypatch.setattr(consumer, "logger", log_spy, raising=False)
    runner = SheetsAmqpConsumerRunner(
        rabbitmq_url="amqp://unit-test",
        handler=FakeHandler(error=DevolucionesLeaseConflictError("lease is owned")),
    )
    message = FakeMessage(_valid_payload(resource="/post-purchase/v1/claims/519988001"))

    await runner.handle_message(message)

    assert message.acked is False
    assert message.nacks == [True]
    assert log_spy.warning_calls[0][0] == "worker.message.requeued"
    assert log_spy.warning_calls[0][1]["error_type"] == "DevolucionesLeaseConflictError"
    assert log_spy.warning_calls[0][1]["dlq_class"] == "transient_timeout"
    assert log_spy.error_calls == []


@pytest.mark.asyncio
async def test_http_404_is_nacked_without_requeue_and_logged_to_dlq(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_spy = LogSpy()
    monkeypatch.setattr(consumer, "logger", log_spy, raising=False)
    handler = FakeHandler(error=_http_status_error(404, path="/items/MLA404"))
    runner = SheetsAmqpConsumerRunner(rabbitmq_url="amqp://unit-test", handler=handler)
    message = FakeMessage(_valid_payload(resource="/items/MLA404"))

    await runner.handle_message(message)

    assert message.acked is False
    assert message.nacks == [False]
    assert log_spy.warning_calls == []
    assert log_spy.error_calls == [
        (
            "worker.message.dlq",
            {
                "event_id": "evt-1",
                "seller_id": 123456789,
                "resource_path": "/items/MLA404",
                "attempts": 1,
                "error_type": "HTTPStatusError",
                "status_code": 404,
                "dlq_class": "http_4xx",
            },
        )
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 403, 422])
async def test_permanent_http_4xx_statuses_are_nacked_without_requeue(
    status_code: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_spy = LogSpy()
    monkeypatch.setattr(consumer, "logger", log_spy, raising=False)
    handler = FakeHandler(error=_http_status_error(status_code))
    runner = SheetsAmqpConsumerRunner(rabbitmq_url="amqp://unit-test", handler=handler)
    message = FakeMessage(_valid_payload())

    await runner.handle_message(message)

    assert message.acked is False
    assert message.nacks == [False]
    assert log_spy.error_calls[0][0] == "worker.message.dlq"
    assert log_spy.error_calls[0][1]["status_code"] == status_code
    assert log_spy.error_calls[0][1]["dlq_class"] == "http_4xx"


@pytest.mark.asyncio
async def test_http_500_is_nacked_with_requeue_and_logs_next_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_spy = LogSpy()
    monkeypatch.setattr(consumer, "logger", log_spy, raising=False)
    handler = FakeHandler(error=_http_status_error(500, path="/items/MLA500"))
    runner = SheetsAmqpConsumerRunner(rabbitmq_url="amqp://unit-test", handler=handler)
    message = FakeMessage(
        _valid_payload(resource="/items/MLA500"),
        headers={"x-death": [{"count": 2, "queue": "zeler.sheets.events"}]},
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
                "resource_path": "/items/MLA500",
                "attempt": 3,
                "error_type": "HTTPStatusError",
                "status_code": 500,
                "dlq_class": "http_5xx",
            },
        )
    ]
    assert log_spy.error_calls == []


@pytest.mark.asyncio
async def test_http_429_is_nacked_with_requeue_and_logged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleep_calls: list[int] = []

    async def fake_sleep(seconds: int) -> None:
        sleep_calls.append(seconds)

    log_spy = LogSpy()
    monkeypatch.setattr(consumer, "logger", log_spy, raising=False)
    monkeypatch.setattr("zeler_sheets.consumer.asyncio.sleep", fake_sleep)
    handler = FakeHandler(error=_rate_limit_error(retry_after_seconds=5, path="/items/MLA429"))
    runner = SheetsAmqpConsumerRunner(rabbitmq_url="amqp://unit-test", handler=handler)
    message = FakeMessage(_valid_payload(resource="/items/MLA429"))

    await runner.handle_message(message)

    assert sleep_calls == []
    assert message.acked is False
    assert message.nacks == [True]
    assert log_spy.warning_calls[0][0] == "worker.message.requeued"
    assert log_spy.warning_calls[0][1]["error_type"] == "GatewayRateLimitError"
    assert log_spy.warning_calls[0][1]["retry_after"] == 5
    assert log_spy.warning_calls[0][1]["status_code"] == 429
    assert log_spy.warning_calls[0][1]["dlq_class"] == "http_4xx"


@pytest.mark.asyncio
async def test_http_408_is_requeued_with_status_code_and_http_4xx_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_spy = LogSpy()
    monkeypatch.setattr(consumer, "logger", log_spy, raising=False)
    handler = FakeHandler(error=_http_status_error(408, path="/items/MLA408"))
    runner = SheetsAmqpConsumerRunner(rabbitmq_url="amqp://unit-test", handler=handler)
    message = FakeMessage(_valid_payload(resource="/items/MLA408"))

    await runner.handle_message(message)

    assert message.acked is False
    assert message.nacks == [True]
    assert log_spy.warning_calls == [
        (
            "worker.message.requeued",
            {
                "event_id": "evt-1",
                "seller_id": 123456789,
                "resource_path": "/items/MLA408",
                "attempt": 1,
                "error_type": "HTTPStatusError",
                "status_code": 408,
                "dlq_class": "http_4xx",
            },
        )
    ]
    assert log_spy.error_calls == []


@pytest.mark.asyncio
async def test_google_sheets_429_is_delayed_and_acked_without_dlq(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_spy = LogSpy()
    monkeypatch.setattr(consumer, "logger", log_spy, raising=False)
    handler = FakeHandler(
        error=RetryableGoogleSheetsApiError(
            "Google Sheets write quota exceeded", retry_after_seconds=12
        )
    )
    publisher = FakeRetryDelayPublisher()
    runner = SheetsAmqpConsumerRunner(
        rabbitmq_url="amqp://unit-test",
        handler=handler,
        retry_delay_publisher=publisher,
    )
    message = FakeMessage(_valid_payload(resource="/items/MLA-GOOGLE-429"))

    await runner.handle_message(message)

    assert message.acked is True
    assert message.nacks == []
    assert publisher.calls == [
        {
            "body": message.body,
            "queue_name": "zeler.sheets.events",
            "delay_ms": 12000,
            "headers": {RETRY_ATTEMPT_HEADER: 1},
        }
    ]
    assert log_spy.warning_calls == [
        (
            "worker.message.requeued",
            {
                "event_id": "evt-1",
                "seller_id": 123456789,
                "resource_path": "/items/MLA-GOOGLE-429",
                "attempt": 1,
                "error_type": "RetryableGoogleSheetsApiError",
                "retry_after": 12,
                "dlq_class": "http_4xx",
            },
        )
    ]
    assert log_spy.error_calls == []


@pytest.mark.asyncio
async def test_google_sheets_retry_attempt_header_exhausts_delivery_limit_without_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_spy = LogSpy()
    monkeypatch.setattr(consumer, "logger", log_spy, raising=False)
    handler = FakeHandler(
        error=RetryableGoogleSheetsApiError(
            "Google Sheets write quota exceeded", retry_after_seconds=12
        )
    )
    publisher = FakeRetryDelayPublisher()
    runner = SheetsAmqpConsumerRunner(
        rabbitmq_url="amqp://unit-test",
        handler=handler,
        retry_delay_publisher=publisher,
    )
    message = FakeMessage(
        _valid_payload(resource="/items/MLA-GOOGLE-429"),
        headers={RETRY_ATTEMPT_HEADER: 5},
    )

    await runner.handle_message(message)

    assert handler.events == []
    assert message.acked is False
    assert message.nacks == [False]
    assert publisher.calls == []
    assert log_spy.warning_calls == []
    assert log_spy.error_calls[0][0] == "worker.message.dlq"
    assert log_spy.error_calls[0][1]["attempts"] == 5
    assert log_spy.error_calls[0][1]["error_type"] == "RetryLimitExceededError"
    assert log_spy.error_calls[0][1]["dlq_class"] == "transient_timeout"


@pytest.mark.asyncio
async def test_non_retryable_google_sheets_api_error_is_nacked_without_requeue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_spy = LogSpy()
    monkeypatch.setattr(consumer, "logger", log_spy, raising=False)
    handler = FakeHandler(error=GoogleSheetsApiError("Google Sheets API returned 400"))
    runner = SheetsAmqpConsumerRunner(rabbitmq_url="amqp://unit-test", handler=handler)
    message = FakeMessage(_valid_payload(resource="/items/MLA-GOOGLE-400"))

    await runner.handle_message(message)

    assert message.acked is False
    assert message.nacks == [False]
    assert log_spy.warning_calls == []
    assert log_spy.error_calls[0][0] == "worker.message.dlq"
    assert log_spy.error_calls[0][1]["error_type"] == "GoogleSheetsApiError"
    assert log_spy.error_calls[0][1]["dlq_class"] == "http_4xx"


@pytest.mark.asyncio
async def test_retry_budget_exhausted_nacks_without_requeue_and_logs_dlq(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_spy = LogSpy()
    monkeypatch.setattr(consumer, "logger", log_spy, raising=False)
    handler = FakeHandler(error=_http_status_error(500, path="/items/MLA500"))
    runner = SheetsAmqpConsumerRunner(rabbitmq_url="amqp://unit-test", handler=handler)
    message = FakeMessage(
        _valid_payload(resource="/items/MLA500"),
        headers={"x-death": [{"count": 5, "queue": "zeler.sheets.events"}]},
    )

    await runner.handle_message(message)

    assert message.acked is False
    assert message.nacks == [False]
    assert handler.events == []
    assert log_spy.warning_calls == []
    assert log_spy.error_calls == [
        (
            "worker.message.dlq",
            {
                "event_id": "evt-1",
                "seller_id": 123456789,
                "resource_path": "/items/MLA500",
                "attempts": 5,
                "error_type": "RetryLimitExceededError",
                "dlq_class": "transient_timeout",
            },
        )
    ]


@pytest.mark.asyncio
async def test_connect_error_is_nacked_with_requeue_and_logged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_spy = LogSpy()
    monkeypatch.setattr(consumer, "logger", log_spy, raising=False)
    handler = FakeHandler(error=httpx.ConnectError("connection refused"))
    runner = SheetsAmqpConsumerRunner(rabbitmq_url="amqp://unit-test", handler=handler)
    message = FakeMessage(_valid_payload(resource="/items/MLA-CONNECT"))

    await runner.handle_message(message)

    assert message.acked is False
    assert message.nacks == [True]
    assert log_spy.warning_calls == [
        (
            "worker.message.requeued",
            {
                "event_id": "evt-1",
                "seller_id": 123456789,
                "resource_path": "/items/MLA-CONNECT",
                "attempt": 1,
                "error_type": "ConnectError",
                "dlq_class": "transient_timeout",
            },
        )
    ]
    assert log_spy.error_calls == []


@pytest.mark.asyncio
async def test_timeout_error_is_nacked_with_requeue_and_logged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_spy = LogSpy()
    monkeypatch.setattr(consumer, "logger", log_spy, raising=False)
    handler = FakeHandler(error=httpx.TimeoutException("gateway timeout"))
    runner = SheetsAmqpConsumerRunner(rabbitmq_url="amqp://unit-test", handler=handler)
    message = FakeMessage(
        _valid_payload(resource="/items/MLA-TIMEOUT"),
        headers={"x-death": [{"count": 1, "queue": "zeler.sheets.events"}]},
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
                "resource_path": "/items/MLA-TIMEOUT",
                "attempt": 2,
                "error_type": "TimeoutException",
                "dlq_class": "transient_timeout",
            },
        )
    ]
    assert log_spy.error_calls == []


@pytest.mark.asyncio
async def test_json_decode_error_is_nacked_without_requeue_and_logged_to_dlq(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_spy = LogSpy()
    monkeypatch.setattr(consumer, "logger", log_spy, raising=False)
    handler = FakeHandler()
    runner = SheetsAmqpConsumerRunner(rabbitmq_url="amqp://unit-test", handler=handler)
    message = FakeMessage(b"not-json")

    await runner.handle_message(message)

    assert handler.events == []
    assert message.acked is False
    assert message.nacks == [False]
    assert log_spy.warning_calls == []
    assert log_spy.error_calls == [
        (
            "worker.message.dlq",
            {
                "event_id": None,
                "seller_id": None,
                "resource_path": None,
                "attempts": 1,
                "error_type": "JSONDecodeError",
                "dlq_class": "attribution_missing",
            },
        )
    ]


@pytest.mark.asyncio
async def test_runtime_error_is_nacked_without_requeue_and_logged_to_dlq(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_spy = LogSpy()
    monkeypatch.setattr(consumer, "logger", log_spy, raising=False)
    handler = FakeHandler(error=RuntimeError("unexpected bug"))
    runner = SheetsAmqpConsumerRunner(rabbitmq_url="amqp://unit-test", handler=handler)
    message = FakeMessage(_valid_payload(resource="/items/MLA-RUNTIME"))

    await runner.handle_message(message)

    assert message.acked is False
    assert message.nacks == [False]
    assert log_spy.warning_calls == []
    assert log_spy.error_calls == [
        (
            "worker.message.dlq",
            {
                "event_id": "evt-1",
                "seller_id": 123456789,
                "resource_path": "/items/MLA-RUNTIME",
                "attempts": 1,
                "error_type": "RuntimeError",
                "exc_info": True,
                "dlq_class": "http_5xx",
            },
        )
    ]


@pytest.mark.asyncio
async def test_unexpected_exception_is_nacked_without_requeue_and_logged_to_dlq(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_spy = LogSpy()
    monkeypatch.setattr(consumer, "logger", log_spy, raising=False)
    handler = FakeHandler(error=Exception("boom"))
    runner = SheetsAmqpConsumerRunner(rabbitmq_url="amqp://unit-test", handler=handler)
    message = FakeMessage(_valid_payload(resource="/items/MLA-BOOM"))

    await runner.handle_message(message)

    assert message.acked is False
    assert message.nacks == [False]
    assert log_spy.error_calls[0] == (
        "worker.message.dlq",
        {
            "event_id": "evt-1",
            "seller_id": 123456789,
            "resource_path": "/items/MLA-BOOM",
            "attempts": 1,
            "error_type": "Exception",
            "exc_info": True,
            "dlq_class": "http_5xx",
        },
    )


def test_dlq_log_attribution_when_event_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_spy = LogSpy()
    monkeypatch.setattr(consumer, "logger", log_spy, raising=False)

    consumer._log_message_dlq(None, 1, ValueError("malformed payload"))

    assert log_spy.error_calls == [
        (
            "worker.message.dlq",
            {
                "event_id": None,
                "seller_id": None,
                "resource_path": None,
                "attempts": 1,
                "error_type": "ValueError",
                "dlq_class": "attribution_missing",
            },
        )
    ]


def test_requeue_log_includes_status_code_and_http_4xx_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_spy = LogSpy()
    monkeypatch.setattr(consumer, "logger", log_spy, raising=False)
    event = consumer.SheetsEvent(
        event_id="evt-1",
        event_type="items.updated",
        seller_id=123456789,
        resource="/items/MLA429",
        idempotency_key="key-1",
    )

    consumer._log_message_requeued(event, 2, ValueError("transient"), status_code=429)

    assert log_spy.warning_calls == [
        (
            "worker.message.requeued",
            {
                "event_id": "evt-1",
                "seller_id": 123456789,
                "resource_path": "/items/MLA429",
                "attempt": 2,
                "error_type": "ValueError",
                "status_code": 429,
                "dlq_class": "http_4xx",
            },
        )
    ]


def test_dlq_classifier_covers_remaining_taxonomy_branches() -> None:
    from zeler_sheets.google_errors import SellerNotConnectedError

    event = consumer.SheetsEvent(
        event_id="evt-1",
        event_type="items.updated",
        seller_id=123456789,
        resource="/items/MLA1",
        idempotency_key="key-1",
    )
    request = httpx.Request("GET", "http://gateway:8080/proxy/meli/items/MLA1")
    server_error = httpx.HTTPStatusError(
        "500 response", request=request, response=httpx.Response(500, request=request)
    )

    assert (
        consumer._dlq_class(event=event, error=SellerNotConnectedError("not connected"))
        == "claims_unbound"
    )
    assert consumer._dlq_class(event=event, error=ValueError("bad field")) == "deserialization"
    assert consumer._dlq_class(event=event, error=server_error) == "http_5xx"
    assert consumer._dlq_class(event=event, error=RuntimeError("unexpected")) == "http_5xx"


@pytest.mark.asyncio
async def test_successful_message_ack_is_logged_with_structured_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_spy = LogSpy()
    monkeypatch.setattr(consumer, "logger", log_spy, raising=False)
    handler = FakeHandler()
    runner = SheetsAmqpConsumerRunner(rabbitmq_url="amqp://unit-test", handler=handler)
    message = FakeMessage(_valid_payload(resource="/items/MLA-OK"))

    await runner.handle_message(message)

    assert message.acked is True
    assert message.nacks == []
    assert log_spy.info_calls == [
        (
            "worker.message.ack",
            {
                "event_id": "evt-1",
                "seller_id": 123456789,
                "resource_path": "/items/MLA-OK",
                "attempt": 1,
            },
        )
    ]
    assert log_spy.warning_calls == []
    assert log_spy.error_calls == []


def _http_status_error(status_code: int, *, path: str = "/items/MLA123") -> httpx.HTTPStatusError:
    request = httpx.Request("GET", f"http://gateway:8080/proxy/meli{path}")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError(
        f"{status_code} response",
        request=request,
        response=response,
    )


def _rate_limit_error(
    *, retry_after_seconds: int, path: str = "/items/MLA123"
) -> GatewayRateLimitError:
    request = httpx.Request("GET", f"http://gateway:8080/proxy/meli{path}")
    response = httpx.Response(429, request=request)
    return GatewayRateLimitError(retry_after_seconds=retry_after_seconds, response=response)


def _valid_payload(*, resource: str = "items/MLA123") -> dict[str, Any]:
    return {
        "event_id": "evt-1",
        "event_type": "items.updated",
        "seller_id": 123456789,
        "resource": resource,
    }
