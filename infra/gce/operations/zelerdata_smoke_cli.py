"""Fixed-scope host adapters for the authorized ZelerData B1 smoke runner.

This module has no import-time I/O. The CLI accepts only a platform user ID;
all operational paths, resources, and commands are constants in this module.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import hmac
import json
import os
import re
import signal
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from infra.gce.operations import zelerdata_smoke_runner as runner

urlopen = urllib.request.urlopen

PROJECT_ID = "zeler-platform-dev"
GCLOUD_COMMAND = Path("/snap/bin/gcloud")
GCLOUD_ENV: Mapping[str, str] = {
    "HOME": str(Path.home()),
    "PATH": "/snap/bin:/usr/bin:/bin",
}
BROKER_SECRET_NAME = "zeler-app-broker-secret"  # noqa: S105 - fixed resource name.
SMOKE_SECRET_NAME = runner.SECRET_NAME
SELLER_ID = runner.ALLOWED_SELLER
FORMULA_SCOPE = runner.FORMULA_SCOPE
GATEWAY_BASE_URL = "https://gateway.zeler.ai"
SHEETS_BASE_URL = "https://sheets.zeler.ai"
SHEETS_FORMULA_EXECUTE_PATH = "/sheets/formulas:execute"
SMOKE_COMMAND = Path("/opt/zeler-platform/zelerdata-smoke/bin/launch_authenticated_smoke")
COMMAND_TIMEOUT_SECONDS = runner.GCLOUD_TIMEOUT_SECONDS
HTTP_TIMEOUT_SECONDS = 30.0
PROCESS_TERM_GRACE_SECONDS = runner.TERM_GRACE_SECONDS
PROCESS_KILL_GRACE_SECONDS = runner.KILL_GRACE_SECONDS
PROCESS_POLL_SECONDS = runner.TERM_POLL_SECONDS
_SHEETS_EXTENSION_TOKEN_REVOKE = re.compile(
    rf"^{re.escape(runner.EXTENSION_TOKEN_URL)}/sheets-ext-token-[0-9a-f]{{20}}:revoke$"
)


class AdapterError(RuntimeError):
    """Raised when a fixed adapter cannot safely complete its operation."""


class SecretReader(Protocol):
    def read_broker_secret(self) -> str: ...


class CommandAdapter(SecretReader, Protocol):
    def run(
        self,
        argv: list[str],
        *,
        stdin: str,
        env: Mapping[str, str],
        timeout: float,
        shell: bool,
    ) -> tuple[int, str, str]: ...


class SafeArgumentParser(argparse.ArgumentParser):
    """Do not echo arbitrary rejected arguments into operator output."""

    def error(self, _message: str) -> Any:
        self.exit(2, "invalid fixed-scope invocation\n")


def build_parser() -> argparse.ArgumentParser:
    parser = SafeArgumentParser(
        prog="zelerdata-smoke",
        description="Run the fixed-scope ZelerData B1 authenticated smoke.",
    )
    parser.add_argument(
        "--platform-user-id",
        required=True,
        help="Approved platform user identity used in the signed broker request.",
    )
    return parser


def _json_object(body: bytes) -> str:
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdapterError("invalid HTTP response") from exc
    if not isinstance(value, dict):
        raise AdapterError("invalid HTTP response")
    return body.decode("utf-8")


class FixedHttpTransport:
    """Route only the fixed gateway and Sheets paths without leaking failures."""

    def __init__(self, broker_secret: str) -> None:
        if not broker_secret:
            raise AdapterError("broker secret unavailable")
        self._broker_secret = broker_secret

    def post(self, url: str, payload: str, headers: Mapping[str, str]) -> tuple[int, str]:
        if url == runner.BROKER_TOKEN_URL:
            base_url = GATEWAY_BASE_URL
            body = payload.encode("utf-8")
            digest = hmac.new(self._broker_secret.encode("utf-8"), body, hashlib.sha256).digest()
            request_headers = {
                "Content-Type": "application/json",
                "X-Zeler-Client-Id": "zeler-app",
                "X-Zeler-Signature": "sha256="
                + base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii"),
            }
        elif (
            url == runner.EXTENSION_TOKEN_URL
            or url == SHEETS_FORMULA_EXECUTE_PATH
            or _SHEETS_EXTENSION_TOKEN_REVOKE.fullmatch(url) is not None
        ):
            authorization = headers.get("Authorization")
            if authorization is None or not authorization.startswith("Bearer "):
                raise AdapterError("invalid Sheets authorization")
            base_url = SHEETS_BASE_URL
            request_headers = {
                key: value
                for key, value in headers.items()
                if key.lower() in {"authorization", "content-type"}
            }
        else:
            raise AdapterError("HTTP route is outside the fixed B1 contract")
        request = urllib.request.Request(  # noqa: S310 - URL is selected from fixed routes.
            f"{base_url}{url}", data=payload.encode("utf-8"), headers=request_headers, method="POST"
        )
        try:
            with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:  # noqa: S310
                body = response.read()
                return response.status, _json_object(body)
        except urllib.error.HTTPError as exc:
            return exc.code, ""
        except (OSError, TimeoutError, AdapterError):
            return 599, ""


class GcloudCommandRunner:
    """Run only the runner's fixed Secret Manager version commands."""

    def read_broker_secret(self) -> str:
        argv = [
            str(GCLOUD_COMMAND),
            "secrets",
            "versions",
            "access",
            "latest",
            f"--secret={BROKER_SECRET_NAME}",
            f"--project={PROJECT_ID}",
        ]
        result = self._run(argv, stdin="", timeout=COMMAND_TIMEOUT_SECONDS)
        secret = result.stdout.strip()
        if result.returncode != 0 or not secret:
            raise AdapterError("broker secret unavailable")
        return secret

    def run(
        self,
        argv: list[str],
        *,
        stdin: str,
        env: Mapping[str, str],
        timeout: float,
        shell: bool,
    ) -> tuple[int, str, str]:
        if shell or env:
            raise AdapterError("unsafe command boundary")
        if not _approved_version_argv(argv):
            raise AdapterError("command is outside the fixed B1 contract")
        fixed_argv = [str(GCLOUD_COMMAND), *argv[1:], f"--project={PROJECT_ID}"]
        result = self._run(fixed_argv, stdin=stdin, timeout=timeout)
        return result.returncode, result.stdout, ""

    @staticmethod
    def _run(argv: list[str], *, stdin: str, timeout: float) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(  # noqa: S603 - argv is built from fixed contract values.
                argv,
                input=stdin,
                capture_output=True,
                text=True,
                env=dict(GCLOUD_ENV),
                shell=False,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("command timed out") from exc
        except OSError as exc:
            raise AdapterError("command unavailable") from exc


def _approved_version_argv(argv: Sequence[str]) -> bool:
    if len(argv) < 4 or tuple(argv[:3]) != ("gcloud", "secrets", "versions"):
        return False
    operation = argv[3]
    if operation == "add":
        return list(argv) == runner.add_version_argv()
    if operation not in {"access", "disable", "destroy"} or len(argv) < 6:
        return False
    try:
        return list(argv) == runner.version_operation_argv(operation, argv[4])
    except (ValueError, runner.VersionIdError):
        return False


class LocalProcessRunner:
    """Run the fixed launcher in an isolated process group."""

    def __init__(self) -> None:
        self._process: subprocess.Popen[str] | None = None

    @property
    def active_pid(self) -> int | None:
        return None if self._process is None else self._process.pid

    def run_smoke(
        self,
        argv: list[str],
        *,
        env: Mapping[str, str],
        timeout: float,
        shell: bool,
    ) -> tuple[int, str, str]:
        if shell or argv != [str(SMOKE_COMMAND)]:
            raise AdapterError("smoke command is outside the fixed B1 contract")
        try:
            self._process = subprocess.Popen(  # noqa: S603 - fixed launcher argv, no shell.
                argv,
                env=dict(env),
                shell=False,
                start_new_session=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            stdout, stderr = self._process.communicate(timeout=timeout)
            return self._process.returncode or 0, stdout, stderr
        except subprocess.TimeoutExpired as exc:
            pid = self._process.pid if self._process is not None else 0
            if not self._terminate_after_timeout(pid):
                raise AdapterError("smoke process group survived TERM and KILL") from exc
            raise TimeoutError("smoke timed out") from exc
        except OSError as exc:
            raise AdapterError("smoke launcher unavailable") from exc
        finally:
            self._process = None

    def terminate_tree(self, pid: int) -> None:
        if pid > 0:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(pid, signal.SIGTERM)

    def kill_tree(self, pid: int) -> None:
        if pid > 0:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(pid, signal.SIGKILL)

    def tree_alive(self, pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError as exc:
            raise AdapterError("unable to confirm smoke process termination") from exc
        return True

    def _terminate_after_timeout(self, pid: int) -> bool:
        if pid <= 0:
            return False
        self.terminate_tree(pid)
        if self._wait_for_tree_exit(pid, PROCESS_TERM_GRACE_SECONDS):
            return True
        self.kill_tree(pid)
        return self._wait_for_tree_exit(pid, PROCESS_KILL_GRACE_SECONDS)

    def _wait_for_tree_exit(self, pid: int, grace: float) -> bool:
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline:
            if not self.tree_alive(pid):
                return True
            time.sleep(PROCESS_POLL_SECONDS)
        return not self.tree_alive(pid)


def _build_inputs(platform_user_id: str) -> runner.RunnerInputs:
    return runner.RunnerInputs(
        secret_name=SMOKE_SECRET_NAME,
        base_url=SHEETS_BASE_URL,
        seller_id=SELLER_ID,
        formula_scope=FORMULA_SCOPE,
        platform_user_id=platform_user_id,
        smoke_command=SMOKE_COMMAND,
        is_executable=lambda path: path.is_file() and os.access(path, os.X_OK),
    )


def _build_seams(command: GcloudCommandRunner, broker_secret: str) -> runner.Seams:
    return runner.Seams(
        clock=_SystemClock(),
        http=FixedHttpTransport(broker_secret),
        command=command,
        lock=runner.FlockLock(runner.LOCK_PATH),
        state=runner.AtomicStateStore(runner.ACTIVE_STATE_PATH),
        process=LocalProcessRunner(),
    )


def _execute(platform_user_id: str, command: GcloudCommandRunner) -> int:
    broker_secret = command.read_broker_secret()
    return runner.run(_build_inputs(platform_user_id), _build_seams(command, broker_secret))


class _SystemClock:
    def utcnow(self) -> Any:
        from datetime import UTC, datetime

        return datetime.now(UTC)


def main(
    argv: Sequence[str] | None = None,
    *,
    command_runner: Any | None = None,
    execute: Callable[[Any, Any], int] | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    platform_user_id = args.platform_user_id.strip()
    if not platform_user_id:
        print("invalid fixed-scope invocation")
        return runner.EXIT_REQUIRED_INPUT
    command = command_runner or GcloudCommandRunner()
    try:
        if execute is None:
            return _execute(platform_user_id, command)
        broker_secret = command.read_broker_secret()
        return execute(_build_inputs(platform_user_id), _build_seams(command, broker_secret))
    except Exception:  # noqa: BLE001 - the CLI must fail closed without details.
        print("B1 smoke failed closed")
        return runner.EXIT_PROCESS_BOUNDARY_REJECTED


if __name__ == "__main__":
    raise SystemExit(main())
