"""Authorized, fail-closed Sheets DLQ snapshot runtime adapters (PR 1).

Owns the narrow pipes injected into the inert adapter: a dedicated lazy
non-robust ``aio_pika`` connection/channel (``AioPikaSnapshotBroker``) and a
read-only HTTP worker health probe (``HttpSheetsWorkerRuntime``). No shell,
external-process, Docker, MongoDB, or mutation authority. Coordinator, CLI,
and reporting live later; the adapter ``__main__`` stays inert.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import os
import stat
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, cast

import aio_pika
import httpx
from infra.operations.sheets_dlq_reconcile import classify_and_sanitize_one
from infra.operations.sheets_dlq_snapshot_adapter import (
    DLQ_QUEUE_NAME,
    OUTCOME_REQUEUE_REQUESTED,
    OUTCOME_REQUEUE_SEND_FAILED,
    OUTCOME_UNKNOWN,
    SNAPSHOT_CAP,
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
_NACK_TIMEOUT = 2.0

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


async def _close_owned_pair(channel: Any | None, connection: Any | None) -> None:
    try:
        if channel is not None:
            await channel.close()
    finally:
        if connection is not None:
            await connection.close()


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
        channel = await self._ensure_channel()
        get = getattr(channel, "get", None)
        if get is not None:
            message = await get(queue_name, no_ack=False, fail=False)
        else:
            queue = await channel.get_queue(queue_name)
            message = await queue.get(no_ack=False, fail=False)
        return None if message is None else cast(SnapshotDelivery, message)

    async def nack_requeue(self, delivery: SnapshotDelivery) -> None:
        await cast(_Nackable, delivery).nack(requeue=True, multiple=False)

    async def close_channel(self) -> None:
        channel, self._channel = self._channel, None
        connection, self._connection = self._connection, None
        await asyncio.wait_for(_close_owned_pair(channel, connection), timeout=_CLOSE_TIMEOUT)


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
        await asyncio.wait_for(broker.nack_requeue(delivery), timeout=_NACK_TIMEOUT)
        return OUTCOME_REQUEUE_REQUESTED
    except NackRequeueError:
        return OUTCOME_REQUEUE_SEND_FAILED
    except Exception:  # noqa: BLE001 - timeout/transport/unknown -> outcome_unknown.
        return OUTCOME_UNKNOWN


async def _universal_nack(broker: SnapshotBroker, obtained: list[SnapshotDelivery]) -> list[str]:
    """One nack attempt per delivery in ascending tag order, continuing on failure."""
    outcomes: list[str] = []
    for delivery in sorted(obtained, key=lambda d: d.delivery_tag):
        outcomes.append(await _attempt_nack(broker, delivery))
    return outcomes


async def _safe_close(broker: SnapshotBroker) -> bool:
    try:
        await asyncio.wait_for(broker.close_channel(), timeout=_CLOSE_TIMEOUT)
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
    verdicts: Sequence[dict[str, str | None]] = (),
) -> dict[str, object]:
    return {
        "execution_outcome": outcome,
        "preflight": preflight,
        "close": not close_failed,
        "message_results": [
            {"sequence": index, "outcome": item, **(*verdicts, {})[index - 1]}
            for index, item in enumerate(results, start=1)
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
    verdicts: list[dict[str, str | None]] = []
    preflight = False
    empty = False
    try:
        with same_host_exclusion(lock_path):
            try:
                await run_preflight(
                    broker=broker,
                    runtime=runtime,
                    queue_name=queue_name,
                    offline_consumers=offline_consumers,
                )
            except (ConnectionError, OSError, aio_pika.exceptions.AMQPError) as exc:
                raise PreflightError("broker connectivity unavailable") from exc
            preflight = True
            for _ in range(limit):
                delivery = await broker.get_one(queue_name)
                if delivery is None:
                    empty = not obtained
                    break
                obtained.append(delivery)
                verdicts.append(classify_and_sanitize_one(json.loads(delivery.body), {}))
            results = await _universal_nack(broker, obtained)
    except asyncio.CancelledError:

        async def _cleanup() -> tuple[list[str], bool]:
            outcomes = await _universal_nack(broker, obtained)
            return outcomes, await _safe_close(broker)

        cleanup = asyncio.create_task(_cleanup())
        try:
            results, close_failed = await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            results, close_failed = await cleanup
        return _build_report(
            preflight=preflight,
            close_failed=close_failed,
            results=results,
            verdicts=verdicts,
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
    except Exception:  # noqa: BLE001 - unexpected failure reports honest unknown.
        results = await _universal_nack(broker, obtained)
        results, verdicts = results + [OUTCOME_UNKNOWN], verdicts + [{}]
        close_failed = await _safe_close(broker)
        return _build_report(
            preflight=preflight,
            close_failed=close_failed,
            results=results,
            verdicts=verdicts,
            outcome=EXECUTION_CLOSE_ERROR if close_failed else EXECUTION_MESSAGE_ERROR,
        )
    close_failed = await _safe_close(broker)
    if empty:
        results = results + [MESSAGE_NOT_OBTAINED]
    return _build_report(
        preflight=preflight,
        close_failed=close_failed,
        results=results,
        verdicts=verdicts,
        outcome=_execution_outcome(results, close_failed),
    )


# ===================== PR 2b: authorized runtime CLI =====================

EXIT_USAGE = 2
EXIT_CONFIG = 4
EXIT_SERIALIZATION = 8
EXIT_INTERNAL = 70

MAX_LIMIT = 24
_MAX_TOKEN_BYTES = 4096
QUEUE_ALLOWLIST = frozenset({DLQ_QUEUE_NAME})

_AUTH_SHA256_ENV = "SHEETS_DLQ_SNAPSHOT_AUTH_SHA256"
_AMQP_URL_ENV = "SHEETS_DLQ_SNAPSHOT_AMQP_URL"
_LOCK_PATH_ENV = "SHEETS_DLQ_SNAPSHOT_LOCK_PATH"


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="sheets-dlq-snapshot-runtime",
        description=(
            "Authorized, fail-closed Sheets DLQ snapshot. Requires an owner-only "
            "authorization token file and explicit configuration; emits sanitized JSON only."
        ),
    )
    parser.add_argument(
        "--authorization-token-file",
        help="Owner-only authorization token file",
    )
    parser.add_argument(
        "--queue", default=DLQ_QUEUE_NAME, help=f"DLQ queue (allowlist: {DLQ_QUEUE_NAME})"
    )
    parser.add_argument("--limit", type=int, default=SNAPSHOT_CAP, help="Delivery limit (1..24)")
    return parser.parse_args(argv)


def _read_token(path: str | None) -> bytes | None:
    if path is None:
        return None
    try:
        st = os.stat(path)
    except OSError:
        return None
    if not stat.S_ISREG(st.st_mode) or st.st_mode & 0o077 or st.st_size > _MAX_TOKEN_BYTES:
        return None
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError:
        return None


def _authorized(token_file: str, expected_sha256: str) -> bool:
    token = _read_token(token_file)
    if token is None:
        return False
    actual = hashlib.sha256(token).hexdigest()
    return hmac.compare_digest(actual, expected_sha256)


def _emit_report(report: dict[str, object]) -> int:
    try:
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    except (TypeError, ValueError):
        return EXIT_SERIALIZATION
    return cast(int, report["error_code"])


def main(
    argv: Sequence[str] | None = None,
    *,
    broker: SnapshotBroker | None = None,
    runtime: WorkerRuntime | None = None,
    lock_path: str | None = None,
) -> int:
    """Run the authorized runtime CLI and return the deterministic exit code."""
    args = _parse_args(argv)
    if args.queue not in QUEUE_ALLOWLIST or args.limit < 1 or args.limit > MAX_LIMIT:
        return EXIT_CONFIG
    expected = os.environ.get(_AUTH_SHA256_ENV)
    lock = lock_path if lock_path is not None else os.environ.get(_LOCK_PATH_ENV)
    if expected is None or lock is None:
        return EXIT_CONFIG
    if not _authorized(args.authorization_token_file, expected):
        return _emit_report(
            _build_report(
                preflight=False,
                close_failed=False,
                results=[],
                outcome=EXECUTION_PREFLIGHT_ERROR,
            )
        )
    if broker is None:
        amqp_url = os.environ.get(_AMQP_URL_ENV)
        if not amqp_url or not amqp_url.strip():
            return EXIT_CONFIG
        broker = AioPikaSnapshotBroker(amqp_url)
    if runtime is None:
        runtime = HttpSheetsWorkerRuntime()
    try:
        report = asyncio.run(
            run_snapshot_runtime(
                broker=broker,
                runtime=runtime,
                queue_name=args.queue,
                limit=args.limit,
                lock_path=lock,
            )
        )
    except Exception:  # noqa: BLE001 - internal failure mapped to 70 without leaking.
        return EXIT_INTERNAL
    return _emit_report(report)


if __name__ == "__main__":
    raise SystemExit(main())
