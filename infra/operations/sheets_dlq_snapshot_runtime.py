"""Authorized, fail-closed Sheets DLQ snapshot runtime adapters (PR 1).

Owns the narrow pipes injected into the inert adapter: a dedicated lazy
non-robust ``aio_pika`` connection/channel (``AioPikaSnapshotBroker``) and a
read-only HTTP worker health probe (``HttpSheetsWorkerRuntime``). No shell,
external-process, Docker, MongoDB, or mutation authority. Coordinator, CLI,
and reporting live later; the adapter ``__main__`` stays inert.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol, cast

import aio_pika
import httpx
from infra.operations.sheets_dlq_snapshot_adapter import (
    QueueInspection,
    SnapshotDelivery,
)

WORKER_HEALTH_URL = "http://sheets-worker:8080/health"
_CONNECT_TIMEOUT = 5.0
_HEARTBEAT = 60
_CLOSE_TIMEOUT = 5.0

ConnectHandle = Callable[..., Awaitable[Any]]


@dataclass(frozen=True)
class _Inspection:
    ready: int
    unacked: int
    consumers: int


async def _default_connect(url: str, timeout: float | None, heartbeat: int | None) -> Any:
    # Non-robust connect: reconnect can invalidate retained delivery tags.
    return await aio_pika.connect(url, timeout=timeout, heartbeat=heartbeat)


class _Nackable(Protocol):
    async def nack(self, *, requeue: bool = True, multiple: bool = False) -> None: ...


class AioPikaSnapshotBroker:
    """Dedicated, lazily-created, non-robust broker satisfying ``SnapshotBroker``."""

    def __init__(self, amqp_url: str, *, connect: ConnectHandle | None = None) -> None:
        self._amqp_url = amqp_url
        self._connect = connect or _default_connect
        self._connection: Any | None = None
        self._channel: Any | None = None

    async def _ensure_channel(self) -> Any:
        if self._channel is None:
            if self._connection is None:
                self._connection = await self._connect(
                    self._amqp_url, timeout=_CONNECT_TIMEOUT, heartbeat=_HEARTBEAT
                )
            self._channel = await self._connection.channel()
        return self._channel

    async def inspect_queue(
        self, queue_name: str, *, timeout: float | None = None
    ) -> QueueInspection | None:
        queue = await (await self._ensure_channel()).declare_queue(
            queue_name, passive=True, timeout=timeout or _CONNECT_TIMEOUT
        )
        decl = queue.declaration_result
        return cast(
            QueueInspection,
            _Inspection(
                int(getattr(decl, "message_count", 0)),
                -1,
                int(getattr(decl, "consumer_count", 0)),
            ),
        )

    async def get_one(self, queue_name: str) -> SnapshotDelivery | None:
        message = await (await self._ensure_channel()).get(queue_name, no_ack=False, fail=False)
        return None if message is None else cast(SnapshotDelivery, message)

    async def nack_requeue(self, delivery: SnapshotDelivery) -> None:
        await cast(_Nackable, delivery).nack(requeue=True, multiple=False)

    async def close_channel(self) -> None:
        channel, self._channel = self._channel, None
        connection, self._connection = self._connection, None
        try:
            if channel is not None:
                await asyncio.wait_for(channel.close(), timeout=_CLOSE_TIMEOUT)
        finally:
            if connection is not None:
                await asyncio.wait_for(connection.close(), timeout=_CLOSE_TIMEOUT)


class HttpSheetsWorkerRuntime:
    """Read-only Sheets worker health probe: fixed GET, no redirects, fail closed."""

    def __init__(
        self,
        *,
        health_url: str = WORKER_HEALTH_URL,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self._health_url = health_url
        self._client_factory = client_factory or (
            lambda: httpx.AsyncClient(timeout=5.0, follow_redirects=False)
        )

    async def worker_is_healthy(self) -> bool:
        try:
            async with self._client_factory() as client:
                response = await client.get(self._health_url)
        except Exception:  # noqa: BLE001 - transport errors fail closed.
            return False
        return response.status_code == 200
