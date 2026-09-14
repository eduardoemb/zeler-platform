from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import aio_pika
import pytest

from zeler_platform_core.runtime.checks import rabbitmq_check_factory
from zeler_sheets.consumer import claims_queue_state


@pytest.mark.asyncio
@pytest.mark.parametrize("probe", ["core", "claims"])
async def test_probe_closes_socket_when_broker_never_starts_handshake(probe: str) -> None:
    eof = asyncio.Event()
    peers: list[asyncio.StreamWriter] = []
    handlers: list[asyncio.Task[Any]] = []

    async def accept(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        assert task is not None
        handlers.append(task)
        peers.append(writer)
        try:
            await reader.read()
            eof.set()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(accept, "127.0.0.1", 0)
    url = f"amqp://guest:guest@127.0.0.1:{server.sockets[0].getsockname()[1]}/"
    try:
        if probe == "core":
            result = await rabbitmq_check_factory(lambda: url, timeout_seconds=0.02)()
            assert result == (False, "rabbitmq_unreachable")
        else:
            assert await claims_queue_state(rabbitmq_url=url, timeout_seconds=0.02) is None
        await asyncio.wait_for(eof.wait(), 0.1)
        assert peers and all(writer.is_closing() for writer in peers)
    finally:
        for writer in peers:
            writer.close()
            await writer.wait_closed()
        server.close()
        await server.wait_closed()
        await asyncio.gather(*handlers, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("closed, connected", [(True, False), (False, False), (False, True)])
async def test_core_uses_real_connection_state(closed: bool, connected: bool) -> None:
    event = asyncio.Event()
    if connected:
        event.set()
    close_calls = []

    async def close() -> None:
        close_calls.append(True)

    async def connect(*args: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(is_closed=closed, connected=event, close=close)

    result = await rabbitmq_check_factory(lambda: "amqp://unused/", connect=connect)()
    expected = not closed and connected
    assert result == (expected, "rabbitmq_ok" if expected else "rabbitmq_unreachable")
    assert close_calls == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["connect", "channel", "declare", "success", "cancel"])
async def test_claims_probe_owns_full_operation_and_closes(
    monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    entered = asyncio.Event()
    closed = asyncio.Event()

    async def stall() -> None:
        entered.set()
        await asyncio.Event().wait()

    async def connect(self: Any, *args: Any, **kwargs: Any) -> None:
        if stage == "connect":
            await stall()
        self.connected.set()

    async def close(self: Any, *args: Any, **kwargs: Any) -> None:
        closed.set()

    async def declare(*args: Any, **kwargs: Any) -> Any:
        assert kwargs == {"passive": True}
        if stage == "declare":
            await stall()
        return SimpleNamespace(declaration_result=SimpleNamespace(message_count=7))

    async def channel(self: Any, *args: Any, **kwargs: Any) -> Any:
        if stage in {"channel", "cancel"}:
            await stall()
        return SimpleNamespace(declare_queue=declare)

    monkeypatch.setattr(aio_pika.Connection, "connect", connect)
    monkeypatch.setattr(aio_pika.Connection, "close", close)
    monkeypatch.setattr(aio_pika.Connection, "channel", channel)
    # Both old robust and new ordinary connections use these base methods.
    task = asyncio.create_task(
        claims_queue_state(rabbitmq_url="amqp://unused/", timeout_seconds=0.02)
    )
    try:
        if stage == "cancel":
            await asyncio.wait_for(entered.wait(), 0.1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            result = await asyncio.wait_for(task, 0.15)
            assert result == ((7, 0) if stage == "success" else None)
        assert closed.is_set()
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["hang", "error", "cancel"])
async def test_core_cleanup_is_bounded_sanitized_and_joins_cancellation(mode: str) -> None:
    close_started = asyncio.Event()
    close_finished = asyncio.Event()

    async def close() -> None:
        close_started.set()
        try:
            if mode == "error":
                raise RuntimeError("amqp://secret/")
            await asyncio.Event().wait()
        finally:
            close_finished.set()

    async def connect(*args: Any, **kwargs: Any) -> Any:
        event = asyncio.Event()
        event.set()
        return SimpleNamespace(is_closed=False, connected=event, close=close)

    check = rabbitmq_check_factory(lambda: "amqp://unused/", connect=connect, timeout_seconds=0.02)
    task = asyncio.ensure_future(check())
    if mode == "cancel":
        await close_started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 0.15)
    else:
        assert await asyncio.wait_for(task, 0.15) == (False, "rabbitmq_unreachable")
    assert close_finished.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("scheme", ["amqp", "amqps"])
async def test_owned_transport_preserves_plain_and_tls_factories(
    monkeypatch: pytest.MonkeyPatch, scheme: str
) -> None:
    from aiormq.connection import TCPTransportFactory, TLSTransportFactory
    from yarl import URL

    from zeler_platform_core.runtime import checks

    selected = []
    writer: Any = SimpleNamespace(
        is_closing=lambda: False,
        close=lambda: selected.append("close"),
        transport=SimpleNamespace(abort=lambda: selected.append("abort")),
    )

    async def create(self: Any, url: Any, **kwargs: Any) -> Any:
        selected.append(type(self).__name__)
        assert kwargs["ssl_context_provider"] is marker
        return object(), writer

    marker = object()
    monkeypatch.setattr(TCPTransportFactory, "create", create)
    monkeypatch.setattr(TLSTransportFactory, "create", create)
    owner = checks.OwnedAmqpTransport(URL(f"{scheme}://unused/"))
    _, observed = await owner.create(URL(f"{scheme}://unused/"), ssl_context_provider=marker)
    assert observed is writer
    owner.abort()
    assert selected == [
        "TLSTransportFactory" if scheme == "amqps" else "TCPTransportFactory",
        "close",
        "abort",
    ]


@pytest.mark.asyncio
async def test_slow_failed_probe_is_cached_for_concurrent_waiters() -> None:
    now = 0.0
    calls = 0

    async def connect(*args: Any, **kwargs: Any) -> Any:
        nonlocal now, calls
        calls += 1
        await asyncio.sleep(0)
        now += 6.0
        raise OSError("sanitized")

    check = rabbitmq_check_factory(
        lambda: "amqp://unused/", connect=connect, clock=lambda: now, ttl_seconds=5.0
    )
    assert (
        await asyncio.gather(*(check() for _ in range(10)))
        == [(False, "rabbitmq_unreachable")] * 10
    )
    assert calls == 1
    now += 5.0
    assert await check() == (False, "rabbitmq_unreachable")
    assert calls == 2
