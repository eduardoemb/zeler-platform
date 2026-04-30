from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from bootstrap.tests._h4_fixtures import LogCaptureContext

from zeler_bootstrap.runtime import BootstrapPublishError, _publish_with_retry


class FrozenClock:
    def __init__(self, initial: float = 0.0) -> None:
        self.value = initial

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


@pytest.fixture
def frozen_clock() -> FrozenClock:
    return FrozenClock()


@pytest.fixture
def sleep_recorder(
    frozen_clock: FrozenClock,
) -> tuple[list[float], Callable[[float], Awaitable[None]]]:
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        frozen_clock.advance(seconds)

    return sleeps, sleep


@pytest.mark.asyncio
async def test_first_attempt_publish_succeeds(
    sleep_recorder: tuple[list[float], Callable[[float], Awaitable[None]]],
    frozen_clock: Callable[[], float],
) -> None:
    sleeps, sleep = sleep_recorder
    messages: list[str] = []

    async def publish(message_id: str) -> None:
        messages.append(message_id)

    await _publish_with_retry(
        publish_fn=publish,
        message_id="bootstrap-completed-job-1",
        sleep=sleep,
        monotonic=frozen_clock,
    )

    assert messages == ["bootstrap-completed-job-1"]
    assert sleeps == []


@pytest.mark.asyncio
async def test_one_transient_failure_then_success_sleeps_with_jittered_backoff(
    sleep_recorder: tuple[list[float], Callable[[float], Awaitable[None]]],
    frozen_clock: Callable[[], float],
) -> None:
    sleeps, sleep = sleep_recorder
    attempts: list[str] = []

    async def publish(message_id: str) -> None:
        attempts.append(message_id)
        if len(attempts) == 1:
            raise ConnectionError("broker reset")

    await _publish_with_retry(
        publish_fn=publish,
        message_id="bootstrap-completed-job-1",
        sleep=sleep,
        monotonic=frozen_clock,
        jitter=lambda: 1.0,
    )

    assert attempts == ["bootstrap-completed-job-1", "bootstrap-completed-job-1"]
    assert len(sleeps) == 1
    assert sleeps[0] == pytest.approx(0.6)


@pytest.mark.asyncio
async def test_retry_sleep_honors_injected_per_sleep_cap(
    sleep_recorder: tuple[list[float], Callable[[float], Awaitable[None]]],
    frozen_clock: Callable[[], float],
) -> None:
    sleeps, sleep = sleep_recorder
    attempts = 0

    async def publish(_message_id: str) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ConnectionError("broker reset")

    await _publish_with_retry(
        publish_fn=publish,
        message_id="bootstrap-completed-job-1",
        max_attempts=2,
        base_delay=10.0,
        per_sleep_cap=1.0,
        sleep=sleep,
        monotonic=frozen_clock,
        jitter=lambda: 0.5,
    )

    assert sleeps == [1.0]


@pytest.mark.asyncio
async def test_retry_budget_exhausted_raises_bootstrap_publish_error(
    sleep_recorder: tuple[list[float], Callable[[float], Awaitable[None]]],
    frozen_clock: Callable[[], float],
) -> None:
    sleeps, sleep = sleep_recorder
    failures: list[ConnectionError] = []

    async def publish(_message_id: str) -> None:
        exc = ConnectionError(f"broker down {len(failures) + 1}")
        failures.append(exc)
        raise exc

    with pytest.raises(BootstrapPublishError) as exc_info:
        await _publish_with_retry(
            publish_fn=publish,
            message_id="bootstrap-completed-job-1",
            max_attempts=3,
            base_delay=10.0,
            sleep=sleep,
            monotonic=frozen_clock,
            jitter=lambda: 0.5,
            wall_clock_cap=11.0,
        )

    assert exc_info.value.message_id == "bootstrap-completed-job-1"
    assert exc_info.value.last_attempt == 3
    assert exc_info.value.cause is failures[-1]
    assert sleeps == [5.0, 5.0]
    assert frozen_clock() <= 11.0


@pytest.mark.asyncio
async def test_per_attempt_timeout_is_retryable(
    sleep_recorder: tuple[list[float], Callable[[float], Awaitable[None]]],
    frozen_clock: Callable[[], float],
) -> None:
    sleeps, sleep = sleep_recorder
    attempts = 0

    async def publish(_message_id: str) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            await asyncio.Future()

    await _publish_with_retry(
        publish_fn=publish,
        message_id="bootstrap-completed-job-1",
        max_attempts=2,
        per_attempt_timeout=0.001,
        sleep=sleep,
        monotonic=frozen_clock,
        jitter=lambda: 0.5,
    )

    assert attempts == 2
    assert sleeps == [0.5]


@pytest.mark.asyncio
async def test_terminal_exception_is_wrapped_without_retry(
    sleep_recorder: tuple[list[float], Callable[[float], Awaitable[None]]],
    frozen_clock: Callable[[], float],
) -> None:
    sleeps, sleep = sleep_recorder
    terminal = ValueError("malformed message")
    attempts = 0

    async def publish(_message_id: str) -> None:
        nonlocal attempts
        attempts += 1
        raise terminal

    with pytest.raises(BootstrapPublishError) as exc_info:
        await _publish_with_retry(
            publish_fn=publish,
            message_id="bootstrap-completed-job-1",
            sleep=sleep,
            monotonic=frozen_clock,
        )

    assert exc_info.value.cause is terminal
    assert exc_info.value.last_attempt == 1
    assert attempts == 1
    assert sleeps == []


@pytest.mark.asyncio
async def test_publish_with_retry_wraps_terminal_exceptions_too(
    sleep_recorder: tuple[list[float], Callable[[float], Awaitable[None]]],
    frozen_clock: Callable[[], float],
) -> None:
    sleeps, sleep = sleep_recorder
    terminal = ValueError("malformed message")
    attempts = 0

    async def publish(_message_id: str) -> None:
        nonlocal attempts
        attempts += 1
        raise terminal

    with pytest.raises(BootstrapPublishError) as exc_info:
        await _publish_with_retry(
            publish_fn=publish,
            message_id="bootstrap-completed-job-1",
            sleep=sleep,
            monotonic=frozen_clock,
        )

    assert exc_info.value.message_id == "bootstrap-completed-job-1"
    assert exc_info.value.last_attempt == 1
    assert exc_info.value.cause is terminal
    assert attempts == 1
    assert sleeps == []


@pytest.mark.asyncio
async def test_publish_call_site_preserves_publisher_confirms_and_message_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    from types import SimpleNamespace

    from zeler_bootstrap.runtime import AioPikaBootstrapPublisher

    records: dict[str, Any] = {"confirms": [], "message_ids": []}

    class FakeMessage:
        def __init__(self, *, message_id: str, **_: Any) -> None:
            self.message_id = message_id

    class FakeExchange:
        async def publish(self, message: FakeMessage, *, routing_key: str) -> None:
            assert routing_key == "bootstrap.completed"
            records["message_ids"].append(message.message_id)

    class FakeChannel:
        async def declare_exchange(self, *_args: Any, **_kwargs: Any) -> FakeExchange:
            return FakeExchange()

    class FakeConnection:
        async def __aenter__(self) -> FakeConnection:
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def channel(self, *, publisher_confirms: bool) -> FakeChannel:
            records["confirms"].append(publisher_confirms)
            return FakeChannel()

    async def connect_robust(_url: str) -> FakeConnection:
        return FakeConnection()

    monkeypatch.setitem(
        sys.modules,
        "aio_pika",
        SimpleNamespace(
            connect_robust=connect_robust,
            ExchangeType=SimpleNamespace(TOPIC="topic"),
            DeliveryMode=SimpleNamespace(PERSISTENT=2),
            Message=FakeMessage,
        ),
    )

    publisher = AioPikaBootstrapPublisher(rabbitmq_url="amqp://rabbitmq/")

    await publisher.publish_bootstrap_completed({"_id": "job-1", "seller_id": "123"})

    assert records == {
        "confirms": [True],
        "message_ids": ["bootstrap-completed-job-1"],
    }


@pytest.mark.asyncio
async def test_publish_call_site_retries_transient_aio_pika_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    from types import SimpleNamespace

    from zeler_bootstrap.runtime import AioPikaBootstrapPublisher

    records: dict[str, Any] = {"confirms": [], "message_ids": []}

    class FakeMessage:
        def __init__(self, *, message_id: str, **_: Any) -> None:
            self.message_id = message_id

    class FakeExchange:
        async def publish(self, message: FakeMessage, *, routing_key: str) -> None:
            assert routing_key == "bootstrap.completed"
            records["message_ids"].append(message.message_id)
            if len(records["message_ids"]) == 1:
                raise ConnectionError("broker reset")

    class FakeChannel:
        async def declare_exchange(self, *_args: Any, **_kwargs: Any) -> FakeExchange:
            return FakeExchange()

    class FakeConnection:
        async def __aenter__(self) -> FakeConnection:
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def channel(self, *, publisher_confirms: bool) -> FakeChannel:
            records["confirms"].append(publisher_confirms)
            return FakeChannel()

    async def connect_robust(_url: str) -> FakeConnection:
        return FakeConnection()

    monkeypatch.setitem(
        sys.modules,
        "aio_pika",
        SimpleNamespace(
            connect_robust=connect_robust,
            ExchangeType=SimpleNamespace(TOPIC="topic"),
            DeliveryMode=SimpleNamespace(PERSISTENT=2),
            Message=FakeMessage,
        ),
    )

    publisher = AioPikaBootstrapPublisher(rabbitmq_url="amqp://rabbitmq/")

    await publisher.publish_bootstrap_completed({"_id": "job-1", "seller_id": "123"})

    assert records == {
        "confirms": [True, True],
        "message_ids": ["bootstrap-completed-job-1", "bootstrap-completed-job-1"],
    }


@pytest.mark.asyncio
async def test_publish_skipped_on_failed_state(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    from types import SimpleNamespace

    from zeler_bootstrap.runtime import AioPikaBootstrapPublisher

    async def connect_robust(_url: str) -> Any:
        raise AssertionError("aio-pika must not be called for failed bootstrap jobs")

    monkeypatch.setitem(sys.modules, "aio_pika", SimpleNamespace(connect_robust=connect_robust))
    publisher = AioPikaBootstrapPublisher(rabbitmq_url="amqp://rabbitmq/")

    with LogCaptureContext() as capture:
        await publisher.publish_bootstrap_completed(
            {"_id": "job-1", "seller_id": "123", "state": "failed"}
        )

    skipped_events = [
        entry for entry in capture.entries if entry["event"] == "bootstrap.amqp.publish_skipped"
    ]
    assert skipped_events == [
        {
            "event": "bootstrap.amqp.publish_skipped",
            "job_id": "job-1",
            "state": "failed",
            "reason": "job_already_failed",
            "log_level": "info",
        }
    ]


@pytest.mark.asyncio
async def test_publish_attempt_event_fields(
    sleep_recorder: tuple[list[float], Callable[[float], Awaitable[None]]],
    frozen_clock: Callable[[], float],
) -> None:
    _sleeps, sleep = sleep_recorder
    attempts = 0

    async def publish(_message_id: str) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ConnectionError("broker reset")

    with LogCaptureContext() as capture:
        await _publish_with_retry(
            publish_fn=publish,
            message_id="bootstrap-completed-job-1",
            max_attempts=2,
            sleep=sleep,
            monotonic=frozen_clock,
            jitter=lambda: 0.5,
        )

    events = [
        entry for entry in capture.entries if entry["event"] == "bootstrap.amqp.publish_attempt"
    ]
    assert [event["attempt"] for event in events] == [1, 2]
    assert dict(events[0]) | {"log_level": "warning"} == {
        "event": "bootstrap.amqp.publish_attempt",
        "attempt": 1,
        "max_attempts": 2,
        "result": "error",
        "elapsed_ms": 0,
        "error_class": "ConnectionError",
        "log_level": "warning",
    }
    assert dict(events[1]) | {"log_level": "info"} == {
        "event": "bootstrap.amqp.publish_attempt",
        "attempt": 2,
        "max_attempts": 2,
        "result": "ok",
        "elapsed_ms": 500,
        "log_level": "info",
    }
