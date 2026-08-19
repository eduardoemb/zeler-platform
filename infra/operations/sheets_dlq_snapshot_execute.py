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

from infra.operations.sheets_dlq_snapshot_adapter import SnapshotBroker, SnapshotDelivery

QUEUE_NAME = "zeler.sheets.events.dlq"
SNAPSHOT_LIMIT = 24
TOKEN_BYTES = 32
TOKEN_FILE_MODE = 0o600
CANONICAL_LOCK_PATH = "/var/lib/zeler-platform/sheets-dlq-snapshot/snapshot.lock"
LOCK_FILE_MODE = 0o600
NACK_TIMEOUT_SECONDS = 2.0


class LockUnavailableError(RuntimeError):
    """The canonical execution lock could not be acquired safely."""


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
