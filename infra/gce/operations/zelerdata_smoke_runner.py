"""Host-side fixed-secret ZelerData smoke runner (SDD Lane B1, slices 1-2G).

Slice 1 establishes injectable seams and prerequisite gates only; importing
this module has no effects. Slice 2A adds the ``versions add`` command with
stdin-only token transport and strict explicit version-ID capture, plus
access/disable/destroy argv builders that target exactly the captured ID.
Slice 2B adds the isolated smoke child invocation: a ``ProcessSeam``-based
process boundary that runs the smoke exactly once with a child environment
equal to a scrubbed baseline plus exactly three inline smoke keys (hostile
inherited ``ZELERDATA_SMOKE_*``, broker/JWT/token values are excluded).
Slice 2C adds redaction-safe diagnostics (token/version/seller never reach
argv, files, output, or raised diagnostics) and the non-blocking ``flock``
plus atomic mode-0600 ``/var/run/zelerdata-smoke.active`` state contract
(concurrent invocation yields the exact ``CONCURRENT_RUN_REJECTED`` result;
stale/partial/unsafe state fails closed). Slice 2D adds fail-closed command
outcome handling: metacharacter values are rejected before any effect,
access/disable/destroy results must match the canonical gcloud output for the
exact captured version ID, nonzero exits and malformed results fail closed,
and a command-seam ``TimeoutError`` (a real adapter would translate
``subprocess.TimeoutExpired``) fails closed with a redaction-safe diagnostic.
Slice 2E adds process-group control and interrupt semantics: a forked
descendant's group receives TERM and, only if a member survives, a bounded
KILL — never leaving a survivor — and SIGINT/SIGTERM drive exactly one
cleanup-request transition with a fail-closed non-success result while
SIGKILL/VM loss leaves the active state in place for recovery.
Slice 2F adds the fake-testable cleanup transaction: ``CleanupPlan`` and
``run_cleanup_plan`` attempt eligible disable/destroy/re-broker/revoke steps
in canonical order (revoke needs a successful fresh re-broker; an add
failure leaves no version) and never report success when an eligible step
fails; ``finalize_result`` composes the run result with the cleanup outcome
so a failed run or cleanup can never yield a success exit. Lifecycle
orchestration and remaining stages land in later slices.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

SECRET_NAME = "zelerdata-smoke-pilot"  # noqa: S105 - resource name, not a credential.
ALLOWED_SELLER = "82453304"
FORMULA_SCOPE = "formulas:execute"
BROKER_MODULE = "sheets"
BROKER_SCOPE = "admin:sheets"
BROKER_TTL_SECONDS = 300
BROKER_TOKEN_URL = "/internal/tokens/issue"  # noqa: S105 - endpoint, not a credential.
EXTENSION_TOKEN_URL = "/sheets/extension-tokens"  # noqa: S105 - endpoint, not a credential.
EXTENSION_TOKEN_TTL_SECONDS = 3600
GCLOUD_TIMEOUT_SECONDS = 60.0
SMOKE_TIMEOUT_SECONDS = 600.0
SMOKE_ENV_KEYS = (
    "ZELERDATA_SMOKE_BASE_URL",
    "ZELERDATA_SMOKE_TOKEN",
    "ZELERDATA_SMOKE_SELLER",
)
# Inherited environment keys that must never reach the smoke child.
_HOSTILE_ENV_MARKERS = ("JWT", "TOKEN", "BROKER", "SECRET")
EXIT_SUCCESS = 0
EXIT_REQUIRED_INPUT = 2
EXIT_AUTHORIZATION_REJECTED = 3
EXIT_COMMAND_PATH_REJECTED = 4
EXIT_BROKER_CONTRACT_REJECTED = 5
EXIT_ADD_VERSION_REJECTED = 6
EXIT_CONCURRENT_RUN_REJECTED = 7
EXIT_ACTIVE_STATE_REJECTED = 8
EXIT_VERSION_OPERATION_REJECTED = 10
EXIT_SMOKE_FAILED = 11
EXIT_PROCESS_BOUNDARY_REJECTED = 12
# Exact rejection message mandated by the concurrency lock spec scenario.
CONCURRENT_RUN_REJECTED = "CONCURRENT_RUN_REJECTED"
ACTIVE_STATE_REJECTED = "ACTIVE_STATE_REJECTED"
# Fixed host path for the non-blocking flock + atomic mode-0600 active state.
ACTIVE_STATE_PATH = Path("/var/run/zelerdata-smoke.active")
STATE_KEYS = ("phase", "timestamp", "version_id")
REDACTION_PLACEHOLDER = "<redacted>"


class Clock(Protocol):
    def utcnow(self) -> datetime: ...


class HttpTransport(Protocol):
    def post(self, url: str, payload: str, headers: Mapping[str, str]) -> tuple[int, str]: ...


class CommandRunner(Protocol):
    def run(
        self,
        argv: list[str],
        *,
        stdin: str,
        env: Mapping[str, str],
        timeout: float,
        shell: bool,
    ) -> tuple[int, str, str]: ...


class LockSeam(Protocol):
    def acquire(self) -> bool: ...

    def release(self) -> None: ...


class StateStore(Protocol):
    def read(self) -> Mapping[str, Any]: ...

    def write(self, state: Mapping[str, Any]) -> None: ...

    def remove(self) -> None: ...


class ProcessSeam(Protocol):
    @property
    def active_pid(self) -> int | None: ...

    def run_smoke(
        self,
        argv: list[str],
        *,
        env: Mapping[str, str],
        timeout: float,
        shell: bool,
    ) -> tuple[int, str, str]: ...

    def terminate_tree(self, pid: int) -> None: ...

    def kill_tree(self, pid: int) -> None: ...

    def tree_alive(self, pid: int) -> bool: ...


@dataclass(frozen=True)
class Seams:
    clock: Clock
    http: HttpTransport
    command: CommandRunner
    lock: LockSeam
    state: StateStore
    process: ProcessSeam


@dataclass(frozen=True)
class RunnerInputs:
    secret_name: str
    base_url: str
    seller_id: str
    formula_scope: str
    platform_user_id: str
    smoke_command: Path
    is_executable: Callable[[Path], bool]


def required_input_errors(*, secret_name: str, base_url: str) -> list[str]:
    errors: list[str] = []
    if not secret_name or not secret_name.strip():
        errors.append("secret_name is required")
    elif secret_name != SECRET_NAME:
        errors.append(f"secret_name must be {SECRET_NAME!r}")
    if not base_url or not base_url.strip():
        errors.append("base_url is required")
    return errors


def authorization_error(*, seller_id: str, formula_scope: str) -> str | None:
    if seller_id != ALLOWED_SELLER:
        return f"seller_id must be {ALLOWED_SELLER!r}"
    if formula_scope != FORMULA_SCOPE:
        return f"formula_scope must be {FORMULA_SCOPE!r}"
    return None


def documentation_like_reason(
    command: Path,
    *,
    is_executable: Callable[[Path], bool],
) -> str | None:
    if command.name in {"requirements.txt", "CMakeLists.txt", "README.sh"}:
        return f"command name {command.name!r} is documentation-like"
    if command.suffix.lower() in {".md", ".mdx"} and is_executable(command):
        return f"command name {command.name!r} is an executable documentation file"
    return None


@dataclass(frozen=True)
class BrokerSigningRequest:
    platform_user_id: str
    module: str
    scope: str
    ttl_seconds: int
    issued_at: datetime


class BrokerContractError(ValueError): ...


def broker_payload_error(
    *,
    platform_user_id: str,
    module: str,
    scope: str,
    ttl_seconds: int,
) -> str | None:
    errors: list[str] = []
    if not platform_user_id or not platform_user_id.strip():
        errors.append("platform_user_id must be a non-empty server-derived value")
    if module != BROKER_MODULE:
        errors.append(f"module must be {BROKER_MODULE!r}")
    if scope != BROKER_SCOPE:
        errors.append(f"scope must be {BROKER_SCOPE!r}")
    if not 1 <= ttl_seconds <= BROKER_TTL_SECONDS:
        errors.append(f"ttl_seconds must be in 1..{BROKER_TTL_SECONDS}")
    return "; ".join(errors) if errors else None


def build_broker_payload(request: BrokerSigningRequest) -> str:
    error = broker_payload_error(
        platform_user_id=request.platform_user_id,
        module=request.module,
        scope=request.scope,
        ttl_seconds=request.ttl_seconds,
    )
    if error is not None:
        raise BrokerContractError(error)
    return json.dumps(
        {
            "platform_user_id": request.platform_user_id,
            "module": request.module,
            "scope": request.scope,
            "ttl_seconds": request.ttl_seconds,
            "iat": int(request.issued_at.timestamp()),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


# Keep the prerequisite-only runner available until the full lifecycle slice.
def run(inputs: RunnerInputs, seams: Seams) -> int:
    if required_input_errors(secret_name=inputs.secret_name, base_url=inputs.base_url):
        return EXIT_REQUIRED_INPUT
    if authorization_error(seller_id=inputs.seller_id, formula_scope=inputs.formula_scope):
        return EXIT_AUTHORIZATION_REJECTED
    if documentation_like_reason(inputs.smoke_command, is_executable=inputs.is_executable):
        return EXIT_COMMAND_PATH_REJECTED
    if broker_payload_error(
        platform_user_id=inputs.platform_user_id,
        module=BROKER_MODULE,
        scope=BROKER_SCOPE,
        ttl_seconds=BROKER_TTL_SECONDS,
    ):
        return EXIT_BROKER_CONTRACT_REJECTED
    return EXIT_SUCCESS


class VersionIdError(ValueError): ...


def version_id_error(version_id: str) -> str | None:
    """Validate an explicit Secret Manager version ID.

    Only explicit ASCII decimal IDs are valid; the ``latest`` alias, blank
    values, and any malformed or non-ASCII ID are rejected.
    """
    if not version_id or not version_id.strip():
        return "version_id must be an explicit numeric version ID"
    if version_id.strip().lower() == "latest":
        return "version_id must not be the 'latest' alias"
    if not (version_id.isascii() and version_id.isdecimal()):
        return f"version_id must be an explicit numeric version ID, got {version_id!r}"
    return None


_ADD_VERSION_OUTPUT_RE = re.compile(
    r"Created version \[(\d+)\] of the secret \[" + re.escape(SECRET_NAME) + r"\]\.?"
)


def parse_add_version_id(stdout: str) -> str:
    """Extract the strict explicit version ID from ``versions add`` output.

    The whole output must be exactly the canonical gcloud line for the fixed
    secret; anything else (``latest``, another secret, trailing text, garbage)
    raises ``VersionIdError``.
    """
    match = _ADD_VERSION_OUTPUT_RE.fullmatch(stdout)
    if match is None:
        raise VersionIdError("could not parse an explicit version ID from 'versions add' output")
    version_id = match.group(1)
    error = version_id_error(version_id)
    if error is not None:
        raise VersionIdError(error)
    return version_id


def add_version_argv() -> list[str]:
    """Static argv for adding one version; token arrives via stdin (--data-file=-)."""
    return ["gcloud", "secrets", "versions", "add", SECRET_NAME, "--data-file=-"]


def add_version(seams: Seams, token: str) -> tuple[int, str]:
    """Add exactly one version; the token travels only via stdin and memory.

    Returns ``(exit_code, version_id)``; ``version_id`` is empty when the add
    is rejected (empty token, nonzero result, malformed/``latest`` output, or
    a command-seam timeout).
    """
    if not token:
        return EXIT_ADD_VERSION_REJECTED, ""
    try:
        returncode, stdout, _stderr = seams.command.run(
            add_version_argv(), stdin=token, env={}, timeout=GCLOUD_TIMEOUT_SECONDS, shell=False
        )
    except TimeoutError:
        return EXIT_ADD_VERSION_REJECTED, ""
    if returncode != 0:
        return EXIT_ADD_VERSION_REJECTED, ""
    try:
        version_id = parse_add_version_id(stdout)
    except VersionIdError:
        return EXIT_ADD_VERSION_REJECTED, ""
    return EXIT_SUCCESS, version_id


VERSION_OPERATIONS = ("access", "disable", "destroy")


def version_operation_argv(operation: str, version_id: str) -> list[str]:
    """Static argv for one version operation on the fixed secret.

    Only the lifecycle operations ``access``, ``disable``, and ``destroy`` are
    supported; the secret itself is never created or deleted. The version ID
    must be the strict explicit ID captured from ``versions add``.
    """
    if operation not in VERSION_OPERATIONS:
        raise ValueError(f"unsupported version operation {operation!r}")
    error = version_id_error(version_id)
    if error is not None:
        raise VersionIdError(error)
    argv = ["gcloud", "secrets", "versions", operation, version_id, SECRET_NAME]
    if operation == "destroy":
        argv.append("--quiet")
    return argv


def version_lifecycle_argv(
    version_id: str,
) -> tuple[list[str], list[str], list[str]]:
    """Bind one captured version ID to access, disable, and destroy argv.

    All three commands target the exact same explicit version ID; ``latest``
    or any other ID is rejected before any command is built.
    """
    error = version_id_error(version_id)
    if error is not None:
        raise VersionIdError(error)
    return (
        version_operation_argv("access", version_id),
        version_operation_argv("disable", version_id),
        version_operation_argv("destroy", version_id),
    )


def hostile_env_key(key: str) -> bool:
    """True when an inherited environment key must never reach the smoke child.

    Hostile keys are any ``ZELERDATA_SMOKE_*`` variable (smoke inputs must come
    only from the inline injection below) and any broker/JWT/token/secret key
    that could carry credentials into the child environment.
    """
    upper = key.upper()
    if upper.startswith("ZELERDATA_SMOKE_"):
        return True
    return any(marker in upper for marker in _HOSTILE_ENV_MARKERS)


def smoke_child_env(
    *,
    baseline: Mapping[str, str],
    base_url: str,
    token: str,
    seller_id: str,
) -> dict[str, str]:
    """Build the smoke child environment: scrubbed baseline plus three keys.

    Inherited hostile keys (``ZELERDATA_SMOKE_*`` and broker/JWT/token/secret
    values) are excluded, then exactly the three inline smoke keys are added
    with the provided values. The baseline mapping is never mutated.
    """
    child = {key: value for key, value in baseline.items() if not hostile_env_key(key)}
    child["ZELERDATA_SMOKE_BASE_URL"] = base_url
    child["ZELERDATA_SMOKE_TOKEN"] = token
    child["ZELERDATA_SMOKE_SELLER"] = seller_id
    return child


def smoke_argv(smoke_command: Path) -> list[str]:
    """Static argv for the env-only smoke child: command path only, no shell."""
    return [str(smoke_command)]


def invoke_smoke(
    seams: Seams,
    *,
    smoke_command: Path,
    baseline_env: Mapping[str, str],
    base_url: str,
    token: str,
    seller_id: str,
) -> tuple[int, str, str]:
    """Invoke the smoke child exactly once through the process seam.

    The child argv is static (command path only), the child environment is the
    scrubbed baseline plus exactly the three inline smoke keys, and the bounded
    timeout is fixed. No token/version/seller value ever appears in argv.
    Returns the child's ``(returncode, stdout, stderr)``; orchestration and
    exit mapping land in a later slice.
    """
    return seams.process.run_smoke(
        smoke_argv(smoke_command),
        env=smoke_child_env(
            baseline=baseline_env,
            base_url=base_url,
            token=token,
            seller_id=seller_id,
        ),
        timeout=SMOKE_TIMEOUT_SECONDS,
        shell=False,
    )


# --- Slice 2C, task 2.4: redaction-safe diagnostics ---


class RedactionError(ValueError): ...


def redact_sensitive(text: str, *, token: str, version_id: str, seller_id: str) -> str:
    """Replace every occurrence of token/version/seller with a placeholder.

    Sensitive values are replaced longest-first so a shorter value cannot
    partially consume a longer one (for example a numeric version ID inside a
    token). Empty values are ignored.
    """
    redacted = text
    for value in sorted((token, version_id, seller_id), key=len, reverse=True):
        if value:
            redacted = redacted.replace(value, REDACTION_PLACEHOLDER)
    return redacted


def redacted_diagnostic(message: str, *, token: str, version_id: str, seller_id: str) -> str:
    """Build a diagnostic line that is guaranteed free of sensitive values.

    Raises ``RedactionError`` when a sensitive value would still survive in the
    output (for example when a value equals the placeholder itself), so a
    dangerous diagnostic can never be emitted.
    """
    redacted = redact_sensitive(message, token=token, version_id=version_id, seller_id=seller_id)
    survivors = [value for value in (token, version_id, seller_id) if value and value in redacted]
    if survivors:
        raise RedactionError(
            "redaction could not guarantee a safe diagnostic for: "
            + ", ".join(repr(value) for value in survivors)
        )
    return redacted


# --- Slice 2C, task 2.5: non-blocking flock + atomic mode-0600 active state ---


class ActiveStateError(ValueError): ...


def active_state_error(state: Mapping[str, Any]) -> str | None:
    """Validate active-state content: exactly phase/timestamp/version_id.

    Partial state (missing keys), unsafe state (unexpected keys such as a
    token or seller), blank values, and non-explicit version IDs are rejected
    fail-closed.
    """
    errors: list[str] = []
    if not isinstance(state, Mapping):
        return "active state must be a JSON object"
    if set(state) != set(STATE_KEYS):
        unexpected = sorted(set(state) - set(STATE_KEYS))
        missing = sorted(set(STATE_KEYS) - set(state))
        if missing:
            errors.append("missing active state keys: " + ", ".join(missing))
        if unexpected:
            errors.append("unexpected active state keys: " + ", ".join(unexpected))
    for key in STATE_KEYS:
        value = state.get(key)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"active state key {key!r} must be a non-empty string")
    version_id = state.get("version_id")
    if isinstance(version_id, str) and version_id.strip():
        version_error = version_id_error(version_id)
        if version_error is not None:
            errors.append(version_error)
    return "; ".join(errors) if errors else None


def build_active_state(*, phase: str, timestamp: str, version_id: str) -> dict[str, str]:
    """Build the only allowed active-state payload: phase, timestamp, version_id."""
    state = {"phase": phase, "timestamp": timestamp, "version_id": version_id}
    error = active_state_error(state)
    if error is not None:
        raise ActiveStateError(error)
    return state


def encode_active_state(state: Mapping[str, Any]) -> str:
    """Serialize active state as compact deterministic JSON (validated)."""
    error = active_state_error(state)
    if error is not None:
        raise ActiveStateError(error)
    return json.dumps(state, sort_keys=True, separators=(",", ":"))


def parse_active_state(text: str) -> dict[str, Any]:
    """Strictly parse active-state content; any deviation fails closed."""
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ActiveStateError("active state is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ActiveStateError("active state must be a JSON object")
    error = active_state_error(parsed)
    if error is not None:
        raise ActiveStateError(error)
    return parsed


def lock_and_state_gate(*, lock_acquired: bool, state: Mapping[str, Any]) -> tuple[int, str]:
    """Fail-closed gate before any effect: concurrent lock or leftover state.

    Returns ``(exit_code, message)``; a successful gate returns
    ``(EXIT_SUCCESS, "")``. A second concurrent invocation yields the exact
    ``CONCURRENT_RUN_REJECTED`` result; any active state (stale/partial/unsafe
    leftovers) yields ``ACTIVE_STATE_REJECTED``.
    """
    if not lock_acquired:
        return EXIT_CONCURRENT_RUN_REJECTED, CONCURRENT_RUN_REJECTED
    if state:
        return EXIT_ACTIVE_STATE_REJECTED, ACTIVE_STATE_REJECTED
    return EXIT_SUCCESS, ""


class FlockLock:
    """Non-blocking exclusive ``flock`` adapter over the active-state file."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._fd: int | None = None

    def acquire(self) -> bool:
        if self._fd is not None:
            return True
        try:
            fd = os.open(self._path, os.O_RDWR | os.O_CREAT, 0o600)
        except OSError:
            return False
        try:
            os.fchmod(fd, 0o600)  # noqa: S103 - explicit mode-0600 contract.
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        self._fd = fd
        return True

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)
            self._fd = None


class AtomicStateStore:
    """Atomic mode-0600 JSON state file at a fixed host path."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def read(self) -> Mapping[str, Any]:
        if not self._path.exists():
            return {}
        try:
            text = self._path.read_text(encoding="utf-8")
        except OSError:
            return {}
        return parse_active_state(text)

    def write(self, state: Mapping[str, Any]) -> None:
        error = active_state_error(state)
        if error is not None:
            raise ActiveStateError(error)
        text = encode_active_state(state) + "\n"
        temp = self._path.with_name(self._path.name + ".tmp")
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)  # noqa: S103 - explicit mode-0600 contract.
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, self._path)

    def remove(self) -> None:
        self._path.unlink(missing_ok=True)
