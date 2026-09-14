from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import aio_pika
from aiormq.connection import TCPTransportFactory, TLSTransportFactory, TransportFactory
from yarl import URL

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


class OwnedAmqpTransport(TransportFactory):
    """Retain sockets during handshake, before aio-pika attaches its transport.

    Each owner belongs to one connection; it never changes global library state.
    The normal TLS factory still owns certificate and SSL-context handling.
    """

    def __init__(self, url: URL) -> None:
        self._factory = TLSTransportFactory() if url.scheme == "amqps" else TCPTransportFactory()
        self._writers: list[asyncio.StreamWriter] = []

    async def create(
        self, url: URL, **kwargs: Any
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        reader, writer = await self._factory.create(url, **kwargs)
        self._writers = [owned for owned in self._writers if not owned.is_closing()]
        self._writers.append(writer)
        return reader, writer

    def abort(self) -> None:
        """Release any socket left by a failed handshake or bounded close."""
        for writer in self._writers:
            writer.close()
            writer.transport.abort()
        self._writers.clear()


async def _finish_probe_close(
    connection: Any, closer: Callable[[Any], Awaitable[None]], timeout_seconds: float
) -> None:
    # Shield only the bounded cleanup task, and join it even if the caller is
    # cancelled again. No detached cleanup/reconnect tasks survive this scope.
    task = asyncio.create_task(asyncio.wait_for(closer(connection), timeout=timeout_seconds))
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:  # noqa: BLE001 - re-raised by task.result below.
            break
    if cancelled:
        # Retrieve a cleanup error before propagating the caller's cancellation.
        if not task.cancelled():
            task.exception()
        raise asyncio.CancelledError
    task.result()


@asynccontextmanager
async def amqp_probe_connection(
    url: str,
    *,
    timeout_seconds: float,
    connect: Callable[..., Awaitable[Any]] | None = None,
    close: Callable[[Any], Awaitable[None]] | None = None,
) -> AsyncIterator[Any]:
    """Own one probe through connect/use and a separate bounded cleanup.

    The operation gets ``timeout_seconds``; cleanup adds at most
    ``min(timeout_seconds, 5)``. Injected connectors retain their legacy API
    and must own resources until they return a connection.
    """
    connection: Any = None
    transport: OwnedAmqpTransport | None = None
    try:
        async with asyncio.timeout(timeout_seconds):
            if connect is None:
                connection = aio_pika.Connection(URL(url).update_query(heartbeat=60))
                transport = OwnedAmqpTransport(connection.url)
                connection.kwargs["transport_factory"] = transport
                await connection.connect(timeout=timeout_seconds)
            else:
                connection = await connect(url, heartbeat=60)
            yield connection
    finally:
        try:
            if connection is not None:
                await _finish_probe_close(
                    connection, close or _close_amqp_connection, min(timeout_seconds, 5.0)
                )
        finally:
            if transport is not None:
                transport.abort()


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
    fake transport; the default is an owned one-shot ``aio_pika.Connection``. Results are
    cached for ``ttl_seconds`` so probes do not hammer the broker. Failure
    details are fixed strings: AMQP exception text may embed the connection
    URL and credentials and must never reach a health response body.
    """
    now = clock or time.monotonic
    last_at: float | None = None
    last_result: HealthCheckResult | None = None
    lock = asyncio.Lock()

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
                async with amqp_probe_connection(
                    url, timeout_seconds=timeout_seconds, connect=connect, close=close
                ) as connection:
                    if hasattr(connection, "is_closed"):
                        is_open = not connection.is_closed and connection.connected.is_set()
                    else:
                        # Compatibility for existing injected test transports.
                        is_open = bool(getattr(connection, "is_open", False))
                    result: HealthCheckResult = (
                        (True, "rabbitmq_ok") if is_open else (False, "rabbitmq_unreachable")
                    )
            except Exception:  # noqa: BLE001 - never expose broker URLs or cleanup errors.
                result = (False, "rabbitmq_unreachable")
            last_at = now()
            last_result = result
            return result

    return rabbitmq_check
