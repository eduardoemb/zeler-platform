from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable
from typing import Any

import aio_pika

HealthCheckResult = tuple[bool, str]
HealthCheckCoroutine = Callable[[], Awaitable[HealthCheckResult]]


def mongo_check_factory(
    motor_client: Any,
    *,
    ttl_seconds: float = 5,
    timeout_seconds: float = 5,
    clock: Callable[[], float] | None = None,
) -> HealthCheckCoroutine:
    now = clock or time.monotonic
    last_at: float | None = None
    last_result: HealthCheckResult | None = None
    lock = asyncio.Lock()

    async def mongo_check() -> HealthCheckResult:
        nonlocal last_at, last_result
        current = now()
        if last_at is not None and last_result is not None and current - last_at < ttl_seconds:
            return last_result
        async with lock:
            current = now()
            if last_at is not None and last_result is not None and current - last_at < ttl_seconds:
                return last_result
            try:
                client = getattr(motor_client, "client", motor_client)
                command_owner = getattr(client, "admin", client)
                if not hasattr(command_owner, "command"):
                    fallback_result = (True, "connected")
                    last_at = current
                    last_result = fallback_result
                    return fallback_result
                await asyncio.wait_for(command_owner.command("ping"), timeout=timeout_seconds)
                result: HealthCheckResult = (True, "mongo_ok")
            except Exception as exc:  # noqa: BLE001 - health probes must never raise.
                result = (False, f"mongo_unreachable: {exc}")
            last_at = current
            last_result = result
            return result

    return mongo_check


async def _close_amqp_connection(connection: Any) -> None:
    """Close a broker connection produced by a probe, tolerating sync closers."""
    closer = getattr(connection, "close", None)
    if closer is None:
        return
    result = closer()
    if inspect.isawaitable(result):
        await result


def rabbitmq_check_factory(
    url_source: Callable[[], str | None],
    *,
    ttl_seconds: float = 5,
    timeout_seconds: float = 5,
    clock: Callable[[], float] | None = None,
    connect: Callable[..., Awaitable[Any]] | None = None,
    close: Callable[[Any], Awaitable[None]] | None = None,
) -> HealthCheckCoroutine:
    """Build a real broker probe that connects, verifies, and disconnects.

    ``url_source`` returns the configured broker URL (``None`` means
    unconfigured and fails closed). ``connect`` is injectable so tests use a
    fake transport; the default is ``aio_pika.connect_robust``. Results are
    cached for ``ttl_seconds`` so probes do not hammer the broker. Failure
    details are fixed strings: AMQP exception text may embed the connection
    URL and credentials and must never reach a health response body.
    """
    now = clock or time.monotonic
    last_at: float | None = None
    last_result: HealthCheckResult | None = None
    lock = asyncio.Lock()
    broker_connect = connect or aio_pika.connect_robust
    broker_close = close or _close_amqp_connection

    async def rabbitmq_check() -> HealthCheckResult:
        url = url_source()
        if not url:
            return (False, "rabbitmq_url_unconfigured")
        nonlocal last_at, last_result
        current = now()
        if last_at is not None and last_result is not None and current - last_at < ttl_seconds:
            return last_result
        async with lock:
            current = now()
            if last_at is not None and last_result is not None and current - last_at < ttl_seconds:
                return last_result
            try:
                connection = await asyncio.wait_for(
                    broker_connect(url, heartbeat=60), timeout=timeout_seconds
                )
            except Exception:  # noqa: BLE001 - health probes must never raise or leak.
                result: HealthCheckResult = (False, "rabbitmq_unreachable")
            else:
                try:
                    is_open = bool(getattr(connection, "is_open", True))
                    result = (True, "rabbitmq_ok") if is_open else (False, "rabbitmq_unreachable")
                finally:
                    await broker_close(connection)
            last_at = current
            last_result = result
            return result

    return rabbitmq_check
