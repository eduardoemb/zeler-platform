from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from zeler_gateway.routes.health import _check_rabbit


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_silent_amqp_handshake_releases_real_tcp_transport(cancel: bool) -> None:
    baseline = asyncio.all_tasks()
    received = asyncio.Event()
    eof = asyncio.Event()
    peers: list[asyncio.StreamWriter] = []
    handlers: list[asyncio.Task[None]] = []

    async def silent_peer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peers.append(writer)
        task = asyncio.current_task()
        assert task is not None
        handlers.append(task)
        try:
            await reader.readexactly(8)
            received.set()
            assert await reader.read() == b""
            eof.set()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(silent_peer, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    state = SimpleNamespace(rabbit=None)
    probe = asyncio.create_task(_check_rabbit(state, 0.05, f"amqp://127.0.0.1:{port}/"))
    try:
        await asyncio.wait_for(received.wait(), timeout=1)
        if cancel:
            probe.cancel()
            with pytest.raises(asyncio.CancelledError):
                await probe
        else:
            assert await probe == "fail"
        assert state.rabbit is None
        await asyncio.wait_for(eof.wait(), timeout=0.2)
    finally:
        if not probe.done():
            probe.cancel()
        await asyncio.gather(probe, return_exceptions=True)
        server.close()
        await server.wait_closed()
        for peer in peers:
            peer.close()
        for handler in handlers:
            if not handler.done():
                handler.cancel()
        await asyncio.gather(*handlers, return_exceptions=True)
    assert asyncio.all_tasks() == baseline
