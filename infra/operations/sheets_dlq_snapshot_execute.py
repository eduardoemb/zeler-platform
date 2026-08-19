"""Per-execution authority primitives for the Sheets DLQ executor.

This module deliberately owns no broker, reporting, signal, or command
authority. Those concerns are added by later execution slices.
"""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import os
import secrets
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from urllib.parse import urlsplit

QUEUE_NAME = "zeler.sheets.events.dlq"
SNAPSHOT_LIMIT = 24
TOKEN_BYTES = 32
TOKEN_FILE_MODE = 0o600
CANONICAL_LOCK_PATH = "/var/lib/zeler-platform/sheets-dlq-snapshot/snapshot.lock"
LOCK_FILE_MODE = 0o600


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
