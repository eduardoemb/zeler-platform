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
    OUTCOME_REQUEUE_REQUESTED,
    OUTCOME_REQUEUE_SEND_FAILED,
    OUTCOME_UNKNOWN,
    NackRequeueError,
    PreflightError,
    QueueInspection,
    SameHostExclusionError,
    SnapshotBroker,
    SnapshotDelivery,
    WorkerRuntime,
    run_preflight,
    same_host_exclusion,
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


# ===================== PR 2: runtime coordinator + reporter =====================

MESSAGE_NOT_OBTAINED = "message_not_obtained"
EXECUTION_COMPLETED = "completed"
EXECUTION_MESSAGE_ERROR = "message_error"
EXECUTION_CANCELLED = "cancelled"
EXECUTION_PREFLIGHT_ERROR = "preflight_error"
EXECUTION_CLOSE_ERROR = "close_error"

EXIT_OK = 0
EXIT_PREFLIGHT = 5
EXIT_MESSAGE_OR_CANCELLED = 6
EXIT_CLOSE = 7

_EXECUTION_EXIT = {
    EXECUTION_COMPLETED: EXIT_OK,
    EXECUTION_MESSAGE_ERROR: EXIT_MESSAGE_OR_CANCELLED,
    EXECUTION_CANCELLED: EXIT_MESSAGE_OR_CANCELLED,
    EXECUTION_PREFLIGHT_ERROR: EXIT_PREFLIGHT,
    EXECUTION_CLOSE_ERROR: EXIT_CLOSE,
}


async def _attempt_nack(broker: SnapshotBroker, delivery: SnapshotDelivery) -> str:
    try:
        await broker.nack_requeue(delivery)
        return OUTCOME_REQUEUE_REQUESTED
    except NackRequeueError:
        return OUTCOME_REQUEUE_SEND_FAILED
    except Exception:  # noqa: BLE001 - transport/unknown stays outcome_unknown.
        return OUTCOME_UNKNOWN


async def _universal_nack(broker: SnapshotBroker, obtained: list[SnapshotDelivery]) -> list[str]:
    """One nack attempt per delivery in ascending tag order, continuing on failure."""
    outcomes: list[str] = []
    for delivery in sorted(obtained, key=lambda d: d.delivery_tag):
        outcomes.append(await _attempt_nack(broker, delivery))
    return outcomes


async def _safe_close(broker: SnapshotBroker) -> bool:
    try:
        await broker.close_channel()
        return False
    except Exception:  # noqa: BLE001 - close failure must not mask the cause.
        return True


def _execution_outcome(results: list[str], close_failed: bool) -> str:
    if close_failed:
        return EXECUTION_CLOSE_ERROR
    if any(outcome in (OUTCOME_REQUEUE_SEND_FAILED, OUTCOME_UNKNOWN) for outcome in results):
        return EXECUTION_MESSAGE_ERROR
    return EXECUTION_COMPLETED


def _build_report(
    *,
    preflight: bool,
    close_failed: bool,
    results: list[str],
    outcome: str,
) -> dict[str, object]:
    return {
        "execution_outcome": outcome,
        "preflight": preflight,
        "close": not close_failed,
        "message_results": [
            {"sequence": index, "outcome": item} for index, item in enumerate(results, start=1)
        ],
        "error_code": _EXECUTION_EXIT[outcome],
        "requeue_confirmation": "unavailable",
    }


async def run_snapshot_runtime(
    *,
    broker: SnapshotBroker,
    runtime: WorkerRuntime,
    queue_name: str,
    limit: int,
    lock_path: str,
    offline_consumers: int = 0,
) -> dict[str, object]:
    """Run the fail-closed snapshot and emit a sanitized outcome report.

    Order: exclusive lock -> preflight (connectivity, zero consumers, worker
    health) -> get up to limit -> one explicit nack per delivery -> close.
    On cancellation every obtained delivery is still nacked once.
    """
    obtained: list[SnapshotDelivery] = []
    preflight = False
    empty = False
    try:
        with same_host_exclusion(lock_path):
            await run_preflight(
                broker=broker,
                runtime=runtime,
                queue_name=queue_name,
                offline_consumers=offline_consumers,
            )
            preflight = True
            for _ in range(limit):
                delivery = await broker.get_one(queue_name)
                if delivery is None:
                    empty = not obtained
                    break
                obtained.append(delivery)
            results = await _universal_nack(broker, obtained)
    except asyncio.CancelledError:
        results = await _universal_nack(broker, obtained)
        close_failed = await _safe_close(broker)
        return _build_report(
            preflight=preflight,
            close_failed=close_failed,
            results=results,
            outcome=EXECUTION_CLOSE_ERROR if close_failed else EXECUTION_CANCELLED,
        )
    except (PreflightError, SameHostExclusionError):
        close_failed = await _safe_close(broker)
        return _build_report(
            preflight=False,
            close_failed=close_failed,
            results=[],
            outcome=EXECUTION_CLOSE_ERROR if close_failed else EXECUTION_PREFLIGHT_ERROR,
        )
    except Exception:  # noqa: BLE001 - unexpected get failure -> honest report.
        results = await _universal_nack(broker, obtained)
        close_failed = await _safe_close(broker)
        return _build_report(
            preflight=preflight,
            close_failed=close_failed,
            results=results,
            outcome=EXECUTION_CLOSE_ERROR if close_failed else EXECUTION_MESSAGE_ERROR,
        )
    close_failed = await _safe_close(broker)
    if empty:
        results = results + [MESSAGE_NOT_OBTAINED]
    return _build_report(
        preflight=preflight,
        close_failed=close_failed,
        results=results,
        outcome=_execution_outcome(results, close_failed),
    )
