"""Per-execution authority primitives for the Sheets DLQ executor."""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import hmac
import json
import os
import secrets
import signal
import stat
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
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

__all__ = ["SnapshotBroker", "fcntl", "hmac", "os", "secrets", "signal"]

QUEUE_NAME = "zeler.sheets.events.dlq"
SNAPSHOT_LIMIT = 24
TOKEN_BYTES = 32
TOKEN_FILE_MODE = 0o600
CANONICAL_LOCK_PATH = "/var/lib/zeler-platform/sheets-dlq-snapshot/snapshot.lock"
LOCK_FILE_MODE = 0o600
NACK_TIMEOUT_SECONDS = 2.0
CLOSE_TIMEOUT_SECONDS = 5.0

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_CONFIG = 4
EXIT_PREFLIGHT = 5
EXIT_MESSAGE_OR_CANCELLED = 6
EXIT_CLOSE = 7
EXIT_SERIALIZATION = 8
EXIT_INTERNAL = 70
EXIT_TOKEN_CLEANUP_FAIL = 75  # Wrapper-only until S2 owns token-file cleanup.

_RUN_ID_ENV = "SHEETS_DLQ_SNAPSHOT_EXEC_RUN_ID"
_TOKEN_FILE_ENV = "SHEETS_DLQ_SNAPSHOT_EXEC_TOKEN_FILE"  # noqa: S105 - environment variable name.
_DIGEST_ENV = "SHEETS_DLQ_SNAPSHOT_EXEC_DIGEST"


class LockUnavailableError(RuntimeError):
    """The canonical execution lock could not be acquired safely."""


@dataclass(frozen=True)
class ExitResolution:
    """A deterministic, non-sensitive process outcome."""

    exit_code: int
    reason_codes: list[str]


@dataclass(frozen=True)
class TokenValidation:
    """A non-sensitive token-file validation result."""

    token: bytes | None
    failure_class: str | None


_EXIT_RESOLUTIONS = {
    "completed": ExitResolution(EXIT_OK, ["completed"]),
    "usage": ExitResolution(EXIT_USAGE, ["usage"]),
    "invalid_config": ExitResolution(EXIT_CONFIG, ["invalid_config"]),
    "invalid_authorization": ExitResolution(
        EXIT_PREFLIGHT, ["preflight_rejected", "invalid_authorization"]
    ),
    "missing_token": ExitResolution(EXIT_PREFLIGHT, ["preflight_rejected", "missing_token"]),
    "insecure_token": ExitResolution(EXIT_PREFLIGHT, ["preflight_rejected", "insecure_token"]),
    "lock_busy": ExitResolution(EXIT_PREFLIGHT, ["preflight_rejected", "lock_busy"]),
    "unhealthy_worker": ExitResolution(EXIT_PREFLIGHT, ["preflight_rejected", "unhealthy_worker"]),
    "incompatible_consumers": ExitResolution(
        EXIT_PREFLIGHT, ["preflight_rejected", "incompatible_consumers"]
    ),
    "broker_error": ExitResolution(EXIT_PREFLIGHT, ["preflight_rejected", "broker_error"]),
    "unknown_outcome": ExitResolution(
        EXIT_MESSAGE_OR_CANCELLED, ["message_error_or_cancelled", "unknown_outcome"]
    ),
    "cleanup_failure": ExitResolution(EXIT_CLOSE, ["close_error", "cleanup_failure"]),
    "cancellation": ExitResolution(
        EXIT_MESSAGE_OR_CANCELLED, ["message_error_or_cancelled", "cancellation"]
    ),
    "serialization": ExitResolution(EXIT_SERIALIZATION, ["serialization_error"]),
    "internal": ExitResolution(EXIT_INTERNAL, ["sanitized_internal_error"]),
    "token_cleanup_failed": ExitResolution(EXIT_TOKEN_CLEANUP_FAIL, ["token_cleanup_failed"]),
    "queue_not_ready": ExitResolution(EXIT_PREFLIGHT, ["preflight_rejected", "queue_not_ready"]),
    "cleanup_not_ready": ExitResolution(
        EXIT_PREFLIGHT, ["preflight_rejected", "cleanup_not_ready"]
    ),
    "report_not_ready": ExitResolution(EXIT_PREFLIGHT, ["preflight_rejected", "report_not_ready"]),
}
_PREFLIGHT_FAILURE_CLASSES = {
    "authorization": "invalid_authorization",
    "invalid_authorization": "invalid_authorization",
    "missing_token": "missing_token",
    "insecure_token": "insecure_token",
    "binding": "invalid_config",
    "broker": "broker_error",
    "consumers": "incompatible_consumers",
    "queue": "queue_not_ready",
    "cleanup_readiness": "cleanup_not_ready",
    "lock": "lock_busy",
    "report_readiness": "report_not_ready",
    "worker_health": "unhealthy_worker",
}


def resolve_exit(failure_class: str) -> ExitResolution:
    """Return the sole allowed exit/reason pair for a known outcome."""
    return _EXIT_RESOLUTIONS.get(failure_class, _EXIT_RESOLUTIONS["internal"])


@dataclass(frozen=True)
class ExecutionStatus:
    first_preflight_failure: str | None
    capture: CapturePass | None
    capture_failed: bool
    close_failed: bool

    @property
    def exit_code(self) -> int:
        return resolve_exit(_status_failure_class(self)).exit_code


def _status_failure_class(status: ExecutionStatus) -> str:
    if status.first_preflight_failure is not None:
        return _PREFLIGHT_FAILURE_CLASSES.get(
            status.first_preflight_failure, "invalid_authorization"
        )
    if status.capture is not None and status.capture.unknown_outcomes:
        return "unknown_outcome"
    if status.capture_failed:
        return "unknown_outcome"
    if status.close_failed:
        return "cleanup_failure"
    return "completed"


def generate_execution_token() -> bytes:
    """Return one fresh cryptographically secure token for an execution."""
    return secrets.token_bytes(TOKEN_BYTES)


def validate_execution_token(token_file: str) -> TokenValidation:
    """Read a token file while preserving only safe failure classes."""
    try:
        descriptor = os.open(token_file, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        return TokenValidation(None, "missing_token")
    except OSError:
        return TokenValidation(None, "insecure_token")
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != 0
            or stat.S_IMODE(metadata.st_mode) != TOKEN_FILE_MODE
            or metadata.st_size != TOKEN_BYTES
        ):
            return TokenValidation(None, "insecure_token")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            token = handle.read(TOKEN_BYTES + 1)
        if len(token) == TOKEN_BYTES:
            return TokenValidation(token, None)
        return TokenValidation(None, "insecure_token")
    except OSError:
        return TokenValidation(None, "insecure_token")
    finally:
        os.close(descriptor)


def read_execution_token(token_file: str) -> bytes | None:
    """Read only a root-owned, regular, owner-only token file without following links."""
    return validate_execution_token(token_file).token


def execution_digest(run_id: str, token: bytes) -> str:
    """Bind the fixed execution scope to a token without exposing that token."""
    token_sha256 = hashlib.sha256(token).hexdigest()
    fields = (run_id, token_sha256, QUEUE_NAME, str(SNAPSHOT_LIMIT))
    return hashlib.sha256("\n".join(fields).encode("utf-8")).hexdigest()


def verify_execution_authorization(token_file: str, run_id: str, supplied_digest: str) -> bool:
    """Fail closed unless the supplied digest matches the safe token file."""
    return validate_execution_authorization(token_file, run_id, supplied_digest) is None


def validate_execution_authorization(
    token_file: str, run_id: str, supplied_digest: str
) -> str | None:
    """Return the safe first authorization failure, if any."""
    validation = validate_execution_token(token_file)
    if validation.failure_class is not None or validation.token is None:
        return validation.failure_class or "insecure_token"
    expected_digest = execution_digest(run_id, validation.token)
    if hmac.compare_digest(expected_digest, supplied_digest):
        return None
    return "invalid_authorization"


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
        cancelled = False
        try:
            classifications.append(classify(delivery))
            await asyncio.sleep(0)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:  # noqa: BLE001 - classification failure must still requeue.
            classification_errors += 1
        try:
            await asyncio.wait_for(broker.nack_requeue(delivery), timeout=NACK_TIMEOUT_SECONDS)
        except asyncio.CancelledError:
            cancelled = True
            unknown_outcomes += 1
        except Exception:  # noqa: BLE001 - a failed nack cannot prove a requeue outcome.
            unknown_outcomes += 1
            break
        if cancelled:
            raise asyncio.CancelledError

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
    report_ready: Callable[[], bool] = lambda: True,
    classify: Callable[[SnapshotDelivery], object],
) -> ExecutionStatus:
    authorization_failure = validate_execution_authorization(token_file, run_id, digest)
    if authorization_failure is not None:
        return ExecutionStatus(authorization_failure, None, False, False)
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
                if preflight_failure is None:
                    try:
                        ready_for_report = report_ready()
                    except Exception:  # noqa: BLE001 - unavailable report readiness fails closed.
                        ready_for_report = False
                    if not ready_for_report:
                        preflight_failure = "report_readiness"
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


def build_sanitized_report(
    status: ExecutionStatus,
    *,
    safe_revision: str = "unavailable",
    failure_class: str | None = None,
) -> dict[str, object]:
    """Build the fixed report allowlist without copying any runtime values."""
    capture = status.capture
    classifications = {"captured": 0, "other": 0, "classification_error": 0}
    for classification in capture.classifications if capture is not None else ():
        classifications["captured" if classification == "captured" else "other"] += 1
    if capture is not None:
        classifications["classification_error"] = capture.classification_errors
    outcome = resolve_exit(failure_class or _status_failure_class(status))
    preflight_class = _PREFLIGHT_FAILURE_CLASSES.get(status.first_preflight_failure or "")
    unknown_outcomes = capture.unknown_outcomes if capture is not None else 0
    lock_status = "busy" if status.first_preflight_failure == "lock" else "released"
    cleanup_status = "failed" if status.close_failed else "complete"
    if status.first_preflight_failure in {
        "authorization",
        "invalid_authorization",
        "missing_token",
        "insecure_token",
    }:
        lock_status = "not_attempted"
        cleanup_status = "not_started"
    return {
        "schema_version": "zeler.sheets_dlq_snapshot_report/v1",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "safe_revision": safe_revision if safe_revision.isalnum() else "unavailable",
        "requested_limit": SNAPSHOT_LIMIT,
        "messages_obtained": capture.messages_obtained if capture is not None else 0,
        "classifications": classifications,
        "requeue_requested_count": capture.messages_obtained if capture is not None else 0,
        "requeue_failed_count": unknown_outcomes,
        "unknown_outcomes_count": unknown_outcomes,
        "preflight_errors": [preflight_class] if preflight_class is not None else [],
        "close_errors": int(status.close_failed),
        "lock_status": lock_status,
        "cleanup_status": cleanup_status,
        "exit_code": outcome.exit_code,
        "reason_codes": outcome.reason_codes,
    }


@contextmanager
def cancellation_signal_handlers() -> Iterator[None]:
    """Translate TERM/INT into cleanup-driving KeyboardInterrupt and restore handlers."""
    previous = {signum: signal.getsignal(signum) for signum in (signal.SIGTERM, signal.SIGINT)}

    def cancel(_signum: int, _frame: object) -> None:
        raise KeyboardInterrupt

    try:
        for signum in previous:
            signal.signal(signum, cancel)
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def _emit_report(status: ExecutionStatus, failure_class: str | None = None) -> int:
    outcome = resolve_exit(failure_class or _status_failure_class(status))
    report = build_sanitized_report(status, failure_class=failure_class)
    try:
        sys.stdout.write(json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n")
    except (TypeError, ValueError):
        return EXIT_SERIALIZATION
    return outcome.exit_code


def main(
    *,
    broker_factory: Callable[[str], SnapshotBroker] | None = None,
    runtime_factory: Callable[[], WorkerRuntime] | None = None,
    cleanup_ready: Callable[[], bool] = lambda: True,
    report_ready: Callable[[], bool] = lambda: True,
    classify: Callable[[SnapshotDelivery], object] = lambda _delivery: "captured",
) -> int:
    status = ExecutionStatus(None, None, False, False)
    failure_class: str | None = None
    try:
        with cancellation_signal_handlers():
            authority = _authority_environment()
            if authority is None:
                failure_class = "missing_token"
            else:
                run_id, token_file, digest = authority
                status = asyncio.run(
                    execute_authorized_capture(
                        run_id=run_id,
                        token_file=token_file,
                        digest=digest,
                        broker_factory=broker_factory,
                        runtime_factory=runtime_factory,
                        cleanup_ready=cleanup_ready,
                        report_ready=report_ready,
                        classify=classify,
                    )
                )
    except (KeyboardInterrupt, asyncio.CancelledError):
        failure_class = "cancellation"
    except Exception:  # noqa: BLE001 - reports must not disclose exception detail.
        failure_class = "internal"
    return _emit_report(status, failure_class)


if __name__ == "__main__":
    raise SystemExit(main())
