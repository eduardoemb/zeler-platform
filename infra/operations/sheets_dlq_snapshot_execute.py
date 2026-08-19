"""Per-execution authority primitives for the Sheets DLQ executor.

This module deliberately owns no broker connection, reporting, signal, or
command authority. It composes the archived narrow broker port for one bounded
capture pass only; later execution slices add the remaining authority.
"""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import hmac
import os
import secrets
import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from urllib.parse import urlsplit

from infra.operations.sheets_dlq_snapshot_adapter import (
    SnapshotBroker,
    SnapshotDelivery,
    WorkerRuntime,
)
from infra.operations.sheets_dlq_snapshot_runtime import (
    AioPikaSnapshotBroker,
    HttpSheetsWorkerRuntime,
)

QUEUE_NAME = "zeler.sheets.events.dlq"
SNAPSHOT_LIMIT = 24
TOKEN_BYTES = 32
TOKEN_FILE_MODE = 0o600
CANONICAL_LOCK_PATH = "/var/lib/zeler-platform/sheets-dlq-snapshot/snapshot.lock"
LOCK_FILE_MODE = 0o600
NACK_TIMEOUT_SECONDS = 2.0
CLOSE_TIMEOUT_SECONDS = 5.0

EXIT_OK = 0
EXIT_PREFLIGHT = 5
EXIT_MESSAGE_OR_CANCELLED = 6
EXIT_CLOSE = 7

_RUN_ID_ENV = "SHEETS_DLQ_SNAPSHOT_EXEC_RUN_ID"
_TOKEN_FILE_ENV = "SHEETS_DLQ_SNAPSHOT_EXEC_TOKEN_FILE"  # noqa: S105 - environment variable name.
_DIGEST_ENV = "SHEETS_DLQ_SNAPSHOT_EXEC_DIGEST"


class LockUnavailableError(RuntimeError):
    """The canonical execution lock could not be acquired safely."""


@dataclass(frozen=True)
class ExecutionStatus:
    first_preflight_failure: str | None
    capture: CapturePass | None
    capture_failed: bool
    close_failed: bool

    @property
    def exit_code(self) -> int:
        if self.first_preflight_failure is not None:
            return EXIT_PREFLIGHT
        if self.capture_failed:
            return EXIT_MESSAGE_OR_CANCELLED
        if self.close_failed:
            return EXIT_CLOSE
        return EXIT_OK


def generate_execution_token() -> bytes:
    """Return one fresh cryptographically secure token for an execution."""
    return secrets.token_bytes(TOKEN_BYTES)


def read_execution_token(token_file: str) -> bytes | None:
    """Read only a root-owned, regular, owner-only token file without following links."""
    try:
        descriptor = os.open(token_file, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        return None
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != 0
            or stat.S_IMODE(metadata.st_mode) != TOKEN_FILE_MODE
            or metadata.st_size != TOKEN_BYTES
        ):
            return None
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            token = handle.read(TOKEN_BYTES + 1)
        return token if len(token) == TOKEN_BYTES else None
    except OSError:
        return None
    finally:
        os.close(descriptor)


def execution_digest(run_id: str, token: bytes) -> str:
    """Bind the fixed execution scope to a token without exposing that token."""
    token_sha256 = hashlib.sha256(token).hexdigest()
    fields = (run_id, token_sha256, QUEUE_NAME, str(SNAPSHOT_LIMIT))
    return hashlib.sha256("\n".join(fields).encode("utf-8")).hexdigest()


def verify_execution_authorization(token_file: str, run_id: str, supplied_digest: str) -> bool:
    """Fail closed unless the supplied digest matches the safe token file."""
    token = read_execution_token(token_file)
    if token is None:
        return False
    expected_digest = execution_digest(run_id, token)
    return hmac.compare_digest(expected_digest, supplied_digest)


@contextmanager
def execution_lock() -> Iterator[None]:
    """Hold the root-owned canonical lock for one authority execution."""
    try:
        descriptor = os.open(
            CANONICAL_LOCK_PATH,
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
            LOCK_FILE_MODE,
        )
    except OSError as exc:
        raise LockUnavailableError("canonical lock cannot be opened") from exc

    locked = False
    try:
        try:
            metadata = os.fstat(descriptor)
        except OSError as exc:
            raise LockUnavailableError("canonical lock cannot be verified") from exc
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != 0
            or stat.S_IMODE(metadata.st_mode) != LOCK_FILE_MODE
        ):
            raise LockUnavailableError("canonical lock has insecure metadata")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise LockUnavailableError("canonical lock is unavailable") from exc
        locked = True
        yield
    finally:
        try:
            if locked:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def read_rabbitmq_url() -> str | None:
    """Return the valid RabbitMQ URL inherited from the container environment."""
    rabbitmq_url = os.environ.get("RABBITMQ_URL")
    if not rabbitmq_url or not rabbitmq_url.strip():
        return None
    try:
        parsed_url = urlsplit(rabbitmq_url)
    except ValueError:
        return None
    if parsed_url.scheme not in {"amqp", "amqps"} or not parsed_url.netloc:
        return None
    return rabbitmq_url


@dataclass(frozen=True)
class CapturePass:
    """Counts and classifications from one bounded requeue-only capture pass."""

    classifications: list[object]
    messages_obtained: int
    classification_errors: int
    unknown_outcomes: int


def validate_capture_scope(queue_name: str, limit: int) -> None:
    """Reject every queue and limit except the fixed narrow-authority scope."""
    if queue_name != QUEUE_NAME:
        raise ValueError("queue is not authorized for the capture")
    if not 1 <= limit <= SNAPSHOT_LIMIT:
        raise ValueError("capture limit must be within 1..24")


async def capture_once(
    broker: SnapshotBroker,
    *,
    classify: Callable[[SnapshotDelivery], object],
    limit: int = SNAPSHOT_LIMIT,
) -> CapturePass:
    """Classify and nack-requeue at most ``limit`` fixed-queue deliveries once.

    A delivery is nacked exactly once even if classification fails. A failed or
    timed-out nack is necessarily unverifiable, so the pass stops immediately
    without retrying the nack or acquiring another delivery.
    """
    validate_capture_scope(QUEUE_NAME, limit)
    classifications: list[object] = []
    messages_obtained = 0
    classification_errors = 0
    unknown_outcomes = 0

    for _ in range(limit):
        delivery = await broker.get_one(QUEUE_NAME)
        if delivery is None:
            break
        messages_obtained += 1
        try:
            classifications.append(classify(delivery))
        except Exception:  # noqa: BLE001 - classification failure must still requeue.
            classification_errors += 1
        try:
            await asyncio.wait_for(broker.nack_requeue(delivery), timeout=NACK_TIMEOUT_SECONDS)
        except Exception:  # noqa: BLE001 - a failed nack cannot prove a requeue outcome.
            unknown_outcomes += 1
            break

    return CapturePass(
        classifications=classifications,
        messages_obtained=messages_obtained,
        classification_errors=classification_errors,
        unknown_outcomes=unknown_outcomes,
    )


async def _close_bounded(broker: SnapshotBroker) -> bool:
    try:
        await asyncio.wait_for(broker.close_channel(), timeout=CLOSE_TIMEOUT_SECONDS)
        return True
    except Exception:  # noqa: BLE001 - the status retains the original failure.
        return False


async def execute_authorized_capture(
    *,
    run_id: str,
    token_file: str,
    digest: str,
    broker_factory: Callable[[str], SnapshotBroker] | None = None,
    runtime_factory: Callable[[], WorkerRuntime] | None = None,
    cleanup_ready: Callable[[], bool] = lambda: True,
    classify: Callable[[SnapshotDelivery], object],
) -> ExecutionStatus:
    if not verify_execution_authorization(token_file, run_id, digest):
        return ExecutionStatus("authorization", None, False, False)
    broker_factory = broker_factory or AioPikaSnapshotBroker
    runtime_factory = runtime_factory or HttpSheetsWorkerRuntime
    broker: SnapshotBroker | None = None
    inspection = None
    rabbitmq_url: str | None = None
    preflight_failure: str | None = None
    capture: CapturePass | None = None
    capture_failed = close_failed = False
    try:
        with execution_lock():
            try:
                try:
                    validate_capture_scope(QUEUE_NAME, SNAPSHOT_LIMIT)
                except ValueError:
                    preflight_failure = "scope"
                if preflight_failure is None:
                    rabbitmq_url = read_rabbitmq_url()
                    if rabbitmq_url is None:
                        preflight_failure = "binding"
                if preflight_failure is None and rabbitmq_url is not None:
                    try:
                        broker = broker_factory(rabbitmq_url)
                        inspection = await broker.inspect_queue(QUEUE_NAME)
                    except Exception:  # noqa: BLE001 - connection/inspection fails closed.
                        preflight_failure = "broker"
                if preflight_failure is None and inspection is None:
                    preflight_failure = "queue"
                if (
                    preflight_failure is None
                    and inspection is not None
                    and inspection.consumers != 0
                ):
                    preflight_failure = "consumers"
                if preflight_failure is None:
                    try:
                        healthy = await runtime_factory().worker_is_healthy()
                    except Exception:  # noqa: BLE001 - health transport errors fail closed.
                        healthy = False
                    if not healthy:
                        preflight_failure = "worker_health"
                if preflight_failure is None:
                    try:
                        ready_for_cleanup = cleanup_ready()
                    except Exception:  # noqa: BLE001 - unavailable cleanup readiness fails closed.
                        ready_for_cleanup = False
                    if not ready_for_cleanup:
                        preflight_failure = "cleanup_readiness"
                if preflight_failure is None and broker is not None:
                    try:
                        capture = await capture_once(broker, classify=classify)
                    except Exception:  # noqa: BLE001 - exit mapping is finalized in S1d-2.
                        capture_failed = True
            finally:
                if broker is not None:
                    close_failed = not await _close_bounded(broker)
    except LockUnavailableError:
        preflight_failure = "lock"
    return ExecutionStatus(preflight_failure, capture, capture_failed, close_failed)


def _authority_environment() -> tuple[str, str, str] | None:
    values = tuple(os.environ.get(name) for name in (_RUN_ID_ENV, _TOKEN_FILE_ENV, _DIGEST_ENV))
    if any(value is None or not value.strip() for value in values):
        return None
    return values  # type: ignore[return-value]


def main(
    *,
    broker_factory: Callable[[str], SnapshotBroker] | None = None,
    runtime_factory: Callable[[], WorkerRuntime] | None = None,
    cleanup_ready: Callable[[], bool] = lambda: True,
    classify: Callable[[SnapshotDelivery], object] = lambda _delivery: "captured",
) -> int:
    authority = _authority_environment()
    if authority is None:
        return EXIT_PREFLIGHT
    run_id, token_file, digest = authority
    return asyncio.run(
        execute_authorized_capture(
            run_id=run_id,
            token_file=token_file,
            digest=digest,
            broker_factory=broker_factory,
            runtime_factory=runtime_factory,
            cleanup_ready=cleanup_ready,
            classify=classify,
        )
    ).exit_code


if __name__ == "__main__":
    raise SystemExit(main())
