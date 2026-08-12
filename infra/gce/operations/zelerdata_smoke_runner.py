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
import signal
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
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
