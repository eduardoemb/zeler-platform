"""Tests for the fixed-secret ZelerData smoke runner prerequisite gates.

Slice 1 covers tasks 1.1-1.6: injectable clock/HTTP/command/lock/state/process
seams with no import effects, the runner skeleton, and the four gates
(required inputs, seller/formula authorization, documentation-like command
paths, broker contract). Fakes only; ``run`` records zero seam calls.

Slice 2A covers tasks 2.1-2.2: the ``versions add`` command with stdin-only
token transport, strict explicit version-ID capture that never accepts
``latest``, and access/disable/destroy argv that target exactly the captured
version ID. Fakes only; no subprocess/network/GCP calls.

Slice 2B covers task 2.3: the smoke child invocation through a
``ProcessSeam``-based boundary — exactly one invocation, static argv with no
credentials, and a child environment equal to a scrubbed baseline plus exactly
the three inline smoke keys (hostile ``ZELERDATA_SMOKE_*``, broker/JWT/token
inherited values excluded). Fakes only; no subprocess/network/GCP calls.

Slice 2D covers task 2.6: fail-closed validation and handling for
metacharacters, malformed command results, nonzero outcomes, and timeouts.
``invoke_smoke_checked`` rejects metacharacter command paths and base URLs
before any process is started; access/disable/destroy results are validated
against canonical gcloud output; nonzero exits, malformed output, and seam
timeouts fail closed with redaction-safe diagnostics. Fakes only; no
subprocess/network/GCP calls.

Slice 2E covers tasks 2.7-2.8: process-group control and interrupt
semantics. ``terminate_descendant`` sends TERM to the forked descendant's
process group and escalates to a bounded KILL only when a member survives,
never leaving a survivor — proven both with a fake process seam and with a
controlled local subprocess harness using real process-group signals (no
external command, network, or GCP). ``CleanupRequest``/``interrupt_exit``
prove that SIGINT/SIGTERM cause exactly one cleanup-request transition and a
fail-closed non-success result, while SIGKILL/VM loss leaves the active
state in place for recovery without any cleanup claim.

Slice 2F covers task 2.9: the fake-testable cleanup transaction and failure
injection. ``CleanupPlan``/``run_cleanup_plan`` attempt eligible
disable/destroy/re-broker/revoke steps in canonical order with injected
callables (revoke needs a successful fresh re-broker; an add failure leaves
no version) and never report success when an eligible step fails;
``finalize_result`` composes the run result with the cleanup outcome so a
failed run or cleanup can never yield a success exit. Fakes only; no signal
handlers, no ``run`` wiring; the active state is never removed (2.10).
"""

from __future__ import annotations

import contextlib  # B1 process-group cleanup
import dataclasses
import json
import os
import signal  # B1 signal tests
import stat
import subprocess
import sys
import time  # B1 process polling
from collections.abc import Callable, Mapping  # B1 seam typing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from infra.gce.operations import zelerdata_smoke_runner as runner

NOW = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)


class _FakeSeam:
    def __init__(self) -> None:
        self.calls: list[str] = []


def _inputs(**overrides: Any) -> runner.RunnerInputs:
    values: dict[str, Any] = {
        "secret_name": runner.SECRET_NAME,
        "base_url": "https://sheets.zeler.ai",
        "seller_id": runner.ALLOWED_SELLER,
        "formula_scope": runner.FORMULA_SCOPE,
        "platform_user_id": "user-abc123",
        "smoke_command": Path("/usr/local/bin/authenticated_smoke"),
        "is_executable": lambda path: False,
    }
    values.update(overrides)
    return runner.RunnerInputs(**values)


def _seams() -> tuple[runner.Seams, list[Any]]:
    fakes: list[Any] = [_FakeSeam() for _ in range(6)]
    seams = runner.Seams(
        clock=fakes[0],
        http=fakes[1],
        command=fakes[2],
        lock=fakes[3],
        state=fakes[4],
        process=fakes[5],
    )
    return seams, fakes


class _RecordingCommandRunner:
    """Fake CommandRunner implementing the extended stdin-aware contract."""

    def __init__(
        self,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
        *,
        raise_timeout: bool = False,
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.raise_timeout = raise_timeout
        self.calls: list[dict[str, Any]] = []

    def run(
        self,
        argv: list[str],
        *,
        stdin: str,
        env: Mapping[str, str],
        timeout: float,
        shell: bool = False,
    ) -> tuple[int, str, str]:
        self.calls.append({"argv": argv, "stdin": stdin, "env": env, "timeout": timeout})
        if self.raise_timeout:
            raise TimeoutError("command timed out")
        return self.returncode, self.stdout, self.stderr


def _seams_with_command(command: _RecordingCommandRunner) -> runner.Seams:
    fakes: list[Any] = [_FakeSeam() for _ in range(5)]
    return runner.Seams(
        clock=fakes[0],
        http=fakes[1],
        command=command,
        lock=fakes[2],
        state=fakes[3],
        process=fakes[4],
    )


def test_seams_require_injected_adapters_with_no_defaults() -> None:
    with pytest.raises(TypeError):
        runner.Seams()  # type: ignore[call-arg]
    assert {field.name for field in dataclasses.fields(runner.Seams)} == {
        "clock",
        "http",
        "command",
        "lock",
        "state",
        "process",
    }
    assert all(field.default is dataclasses.MISSING for field in dataclasses.fields(runner.Seams))
    assert not any(
        "override" in field.name or field.name.startswith("allow")
        for field in dataclasses.fields(runner.RunnerInputs)
    )
    seams, fakes = _seams()
    assert [seams.clock, seams.http, seams.command, seams.lock, seams.state, seams.process] == fakes
    with pytest.raises(dataclasses.FrozenInstanceError):
        seams.clock = object()  # type: ignore[misc, assignment]


def test_module_import_pulls_no_network_dependencies() -> None:
    probe = (
        "import sys\n"
        "from infra.gce.operations import zelerdata_smoke_runner\n"
        "bad = [n for n in sys.modules if n == 'httpx' or n == 'google'\n"
        "        or n.startswith('google.')]\n"
        "print(','.join(bad))\n"
    )
    root = Path(__file__).resolve().parents[2]
    pythonpath = os.pathsep.join([str(root), os.environ.get("PYTHONPATH", "")])
    result = subprocess.run(  # noqa: S603 - static argv: interpreter plus a fixed probe.
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": pythonpath},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""


@pytest.mark.parametrize(
    "secret_name,base_url",
    [
        ("", "https://sheets.zeler.ai"),
        ("   ", "https://sheets.zeler.ai"),
        (runner.SECRET_NAME, ""),
        (runner.SECRET_NAME, "   "),
        ("zelerdata-smoke-other", "https://sheets.zeler.ai"),
    ],
)
def test_missing_or_wrong_secret_and_missing_base_url_are_rejected(
    secret_name: str, base_url: str
) -> None:
    assert runner.required_input_errors(secret_name=secret_name, base_url=base_url) != []


@pytest.mark.parametrize(
    "seller_id,formula_scope",
    [
        ("99999999", runner.FORMULA_SCOPE),
        (runner.ALLOWED_SELLER, "formulas:read"),
    ],
)
def test_wrong_seller_or_formula_scope_is_rejected(seller_id: str, formula_scope: str) -> None:
    assert runner.authorization_error(seller_id=seller_id, formula_scope=formula_scope) is not None


@pytest.mark.parametrize(
    "name",
    ["requirements.txt", "CMakeLists.txt", "README.sh"],
)
def test_documentation_like_command_names_are_rejected(name: str) -> None:
    assert (
        runner.documentation_like_reason(Path("/opt/scripts") / name, is_executable=lambda p: True)
        is not None
    )


@pytest.mark.parametrize("suffix", [".md", ".mdx"])
def test_executable_markdown_command_paths_are_rejected(suffix: str) -> None:
    assert (
        runner.documentation_like_reason(
            Path(f"/opt/scripts/run{suffix}"), is_executable=lambda p: True
        )
        is not None
    )


def test_non_executable_markdown_and_real_command_paths_are_allowed() -> None:
    assert (
        runner.documentation_like_reason(Path("/opt/notes.md"), is_executable=lambda p: False)
        is None
    )
    assert (
        runner.documentation_like_reason(Path("/opt/smoke"), is_executable=lambda p: True) is None
    )


def test_broker_payload_is_compact_json_with_server_derived_user() -> None:
    payload = runner.build_broker_payload(
        runner.BrokerSigningRequest("user-abc123", "sheets", "admin:sheets", 300, NOW)
    )
    assert " " not in payload
    body = json.loads(payload)
    assert body == {
        "platform_user_id": "user-abc123",
        "scopes": ["admin:sheets"],
        "seller_id": 82453304,
        "target_module_id": "sheets",
        "token_kind": "module_admin",
        "ttl_s": 300,
    }


@pytest.mark.parametrize("ttl_seconds", [301, 0])
def test_broker_ttl_outside_one_to_300_seconds_is_rejected(ttl_seconds: int) -> None:
    assert (
        runner.broker_payload_error(
            platform_user_id="user-abc123",
            module=runner.BROKER_MODULE,
            scope=runner.BROKER_SCOPE,
            ttl_seconds=ttl_seconds,
        )
        is not None
    )


@pytest.mark.parametrize(
    "platform_user_id,module,scope",
    [
        ("", runner.BROKER_MODULE, runner.BROKER_SCOPE),
        ("user-abc123", "publicador", runner.BROKER_SCOPE),
        ("user-abc123", runner.BROKER_MODULE, "admin:repricer"),
    ],
)
def test_broker_contract_rejects_absent_user_or_wrong_identity(
    platform_user_id: str, module: str, scope: str
) -> None:
    assert (
        runner.broker_payload_error(
            platform_user_id=platform_user_id, module=module, scope=scope, ttl_seconds=300
        )
        is not None
    )


@pytest.mark.parametrize(
    "override",
    [
        {"secret_name": ""},
        {"seller_id": "99999999"},
        {"smoke_command": Path("/opt/requirements.txt")},
        {"platform_user_id": ""},
    ],
)
def test_run_rejects_invalid_gate_inputs_before_any_effect(override: dict[str, Any]) -> None:
    seams, fakes = _seams()
    assert runner.run(_inputs(**override), seams) != 0
    for fake in fakes:
        assert fake.calls == []


def test_run_accepts_valid_inputs_without_any_effect_in_this_slice() -> None:
    inputs = _inputs()
    assert (
        runner.required_input_errors(secret_name=inputs.secret_name, base_url=inputs.base_url) == []
    )
    assert (
        runner.authorization_error(seller_id=inputs.seller_id, formula_scope=inputs.formula_scope)
        is None
    )
    assert (
        runner.documentation_like_reason(inputs.smoke_command, is_executable=inputs.is_executable)
        is None
    )
    assert (
        runner.broker_payload_error(
            platform_user_id=inputs.platform_user_id,
            module=runner.BROKER_MODULE,
            scope=runner.BROKER_SCOPE,
            ttl_seconds=runner.BROKER_TTL_SECONDS,
        )
        is None
    )


# --- Slice 2A, task 2.1: versions add, stdin-only token, strict version capture ---

# Real ``gcloud secrets versions add`` output ends with a period.
ADD_OUTPUT = "Created version [{version}] of the secret [{secret}]."


def test_add_version_argv_is_static_with_stdin_data_file() -> None:
    argv = runner.add_version_argv()
    assert argv == [
        "gcloud",
        "secrets",
        "versions",
        "add",
        runner.SECRET_NAME,
        "--data-file=-",
    ]
    # A fresh list per call so callers cannot mutate a shared constant.
    assert runner.add_version_argv() is not argv


def test_add_version_passes_token_only_via_stdin() -> None:
    command = _RecordingCommandRunner(
        stdout=ADD_OUTPUT.format(version="42", secret=runner.SECRET_NAME)
    )
    seams = _seams_with_command(command)
    exit_code, version_id = runner.add_version(
        seams,
        token="super-secret-token",  # noqa: S106 - fake token, tests only
    )
    assert exit_code == runner.EXIT_SUCCESS
    assert version_id == "42"
    assert len(command.calls) == 1
    call = command.calls[0]
    assert call["stdin"] == "super-secret-token"
    assert "super-secret-token" not in call["argv"]
    assert "super-secret-token" not in call["env"]
    assert call["argv"] == runner.add_version_argv()
    assert call["timeout"] == runner.GCLOUD_TIMEOUT_SECONDS


def test_add_version_captures_explicit_version_id_from_result() -> None:
    command = _RecordingCommandRunner(
        stdout=ADD_OUTPUT.format(version="7", secret=runner.SECRET_NAME)
    )
    seams = _seams_with_command(command)
    exit_code, version_id = runner.add_version(
        seams,
        token="t",  # noqa: S106 - fake token, tests only
    )
    assert exit_code == runner.EXIT_SUCCESS
    assert version_id == "7"


@pytest.mark.parametrize(
    "stdout",
    [
        ADD_OUTPUT.format(version="latest", secret=runner.SECRET_NAME),
        ADD_OUTPUT.format(version="", secret=runner.SECRET_NAME),
        ADD_OUTPUT.format(version="4.2", secret=runner.SECRET_NAME),
        ADD_OUTPUT.format(version="42", secret="another-secret"),  # noqa: S106 - fixture, tests only
        "garbage output",
        "",
        "Created version [42] of the secret [zelerdata-smoke-pilot]\nnote",
    ],
)
def test_parse_add_version_id_rejects_latest_and_malformed_output(stdout: str) -> None:
    with pytest.raises(runner.VersionIdError):
        runner.parse_add_version_id(stdout)


@pytest.mark.parametrize(
    "returncode,stdout",
    [
        (1, ADD_OUTPUT.format(version="42", secret=runner.SECRET_NAME)),
        (0, ADD_OUTPUT.format(version="latest", secret=runner.SECRET_NAME)),
        (0, "error: could not parse"),
    ],
)
def test_add_version_rejects_failed_or_malformed_add(returncode: int, stdout: str) -> None:
    command = _RecordingCommandRunner(returncode=returncode, stdout=stdout)
    seams = _seams_with_command(command)
    exit_code, version_id = runner.add_version(
        seams,
        token="t",  # noqa: S106 - fake token, tests only
    )
    assert exit_code == runner.EXIT_ADD_VERSION_REJECTED
    assert version_id == ""


def test_add_version_rejects_empty_token_without_command_call() -> None:
    command = _RecordingCommandRunner()
    seams = _seams_with_command(command)
    exit_code, version_id = runner.add_version(seams, token="")
    assert exit_code == runner.EXIT_ADD_VERSION_REJECTED
    assert version_id == ""
    assert command.calls == []


@pytest.mark.parametrize(
    "version_id",
    ["latest", "Latest", "LATEST", "", "   ", "4.2", "-1", "42abc", "42 43", "٤٢", "²"],
)
def test_version_id_error_rejects_non_explicit_ids(version_id: str) -> None:
    assert runner.version_id_error(version_id) is not None


def test_version_id_error_accepts_explicit_decimal_ids() -> None:
    assert runner.version_id_error("0") is None
    assert runner.version_id_error("42") is None


# --- Slice 2A, task 2.2: access/disable/destroy target exactly the captured ID ---


def test_version_operation_argv_targets_exact_captured_id() -> None:
    argv = runner.version_operation_argv("disable", "42")
    assert argv == [
        "gcloud",
        "secrets",
        "versions",
        "disable",
        "42",
        f"--secret={runner.SECRET_NAME}",
    ]


def test_destroy_version_operation_argv_is_quiet_and_secret_free() -> None:
    argv = runner.version_operation_argv("destroy", "42")
    assert argv == [
        "gcloud",
        "secrets",
        "versions",
        "destroy",
        "42",
        f"--secret={runner.SECRET_NAME}",
        "--quiet",
    ]
    assert "super-secret-token" not in argv
    assert runner.ALLOWED_SELLER not in argv


def test_version_lifecycle_argv_binds_one_captured_id_across_all_operations() -> None:
    access, disable, destroy = runner.version_lifecycle_argv("42")
    assert access == [
        "gcloud",
        "secrets",
        "versions",
        "access",
        "42",
        f"--secret={runner.SECRET_NAME}",
    ]
    assert disable == [
        "gcloud",
        "secrets",
        "versions",
        "disable",
        "42",
        f"--secret={runner.SECRET_NAME}",
    ]
    assert destroy == [
        "gcloud",
        "secrets",
        "versions",
        "destroy",
        "42",
        f"--secret={runner.SECRET_NAME}",
        "--quiet",
    ]
    for operation in (access, disable, destroy):
        assert operation[4] == "42"
        assert "latest" not in operation
    # Version-level operations only; the fixed secret is never created or deleted.
    flat = " ".join(" ".join(op) for op in (access, disable, destroy))
    assert "create" not in flat
    assert "delete" not in flat


@pytest.mark.parametrize("version_id", ["latest", "", "   ", "4.2", "-1", "42abc", "٤٢", "²"])
def test_version_lifecycle_argv_rejects_latest_and_malformed_ids(version_id: str) -> None:
    with pytest.raises(runner.VersionIdError):
        runner.version_lifecycle_argv(version_id)


@pytest.mark.parametrize("operation", ["create", "delete", "recreate", "enable"])
def test_version_operation_argv_rejects_non_lifecycle_operations(operation: str) -> None:
    with pytest.raises(ValueError):
        runner.version_operation_argv(operation, "42")


def test_captured_id_flows_into_all_lifecycle_operations() -> None:
    for version_number in ("42", "99"):
        command = _RecordingCommandRunner(
            stdout=ADD_OUTPUT.format(version=version_number, secret=runner.SECRET_NAME)
        )
        seams = _seams_with_command(command)
        exit_code, captured = runner.add_version(
            seams,
            token="t",  # noqa: S106 - fake token, tests only
        )
        assert exit_code == runner.EXIT_SUCCESS
        assert captured == version_number
        for operation in runner.version_lifecycle_argv(captured):
            assert operation[4] == version_number


# --- Slice 2B, task 2.3: exactly one isolated smoke; child env = scrubbed baseline + 3 keys ---

# A preseeded host environment mixing safe keys with hostile smoke/broker/JWT/token values.
HOSTILE_BASELINE = {
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    "LANG": "en_US.UTF-8",
    "HOME": "/root",
    "ZELERDATA_SMOKE_TOKEN": "inherited-hostile-token",
    "ZELERDATA_SMOKE_BASE_URL": "https://evil.example",
    "ZELER_APP_BROKER_SECRET": "broker-secret",
    "SHEETS_EXTENSION_TOKEN": "extension-token",
    "JWT_SECRET": "jwt-secret",
    "GCLOUD_ACCESS_TOKEN": "gcloud-token",
}

SMOKE_TOKEN = "smoke-token-abc"  # noqa: S105 - fake token value, tests only
SMOKE_BASE_URL = "https://sheets.zeler.ai"
SMOKE_COMMAND = Path("/usr/local/bin/authenticated_smoke")


def test_smoke_env_keys_are_exactly_the_three_required_keys() -> None:
    assert runner.SMOKE_ENV_KEYS == (
        "ZELERDATA_SMOKE_BASE_URL",
        "ZELERDATA_SMOKE_TOKEN",
        "ZELERDATA_SMOKE_SELLER",
    )


@pytest.mark.parametrize(
    "key",
    [
        "ZELERDATA_SMOKE_TOKEN",
        "ZELERDATA_SMOKE_BASE_URL",
        "ZELERDATA_SMOKE_SELLER",
        "zelerdata_smoke_token",
        "ZELER_APP_BROKER_SECRET",
        "JWT_SECRET",
        "SHEETS_EXTENSION_TOKEN",
        "GCLOUD_ACCESS_TOKEN",
        "BROKER_JWT",
    ],
)
def test_hostile_env_key_detects_smoke_broker_jwt_and_token_keys(key: str) -> None:
    assert runner.hostile_env_key(key) is True


@pytest.mark.parametrize("key", ["PATH", "LANG", "HOME", "PYTHONPATH", "TZ", "ZELERDATA_SMOKE"])
def test_hostile_env_key_allows_safe_baseline_keys(key: str) -> None:
    assert runner.hostile_env_key(key) is False


def test_smoke_child_env_scrubs_hostile_keys_and_injects_exactly_three() -> None:
    child = runner.smoke_child_env(
        baseline=HOSTILE_BASELINE,
        base_url=SMOKE_BASE_URL,
        token=SMOKE_TOKEN,
        seller_id=runner.ALLOWED_SELLER,
    )
    assert child["PATH"] == "/usr/local/bin:/usr/bin:/bin"
    assert child["LANG"] == "en_US.UTF-8"
    assert child["HOME"] == "/root"
    assert child["ZELERDATA_SMOKE_BASE_URL"] == SMOKE_BASE_URL
    assert child["ZELERDATA_SMOKE_TOKEN"] == SMOKE_TOKEN
    assert child["ZELERDATA_SMOKE_SELLER"] == runner.ALLOWED_SELLER
    for hostile in (
        "ZELER_APP_BROKER_SECRET",
        "SHEETS_EXTENSION_TOKEN",
        "JWT_SECRET",
        "GCLOUD_ACCESS_TOKEN",
        "inherited-hostile-token",
        "https://evil.example",
    ):
        assert hostile not in child
    smoke_keys = sorted(k for k in child if k.startswith("ZELERDATA_SMOKE_"))
    assert smoke_keys == sorted(runner.SMOKE_ENV_KEYS)


def test_smoke_child_env_injected_values_override_inherited_hostile_values() -> None:
    baseline = {"ZELERDATA_SMOKE_TOKEN": "inherited-hostile", "PATH": "/bin"}
    child = runner.smoke_child_env(
        baseline=baseline,
        base_url=SMOKE_BASE_URL,
        token=SMOKE_TOKEN,
        seller_id=runner.ALLOWED_SELLER,
    )
    assert child["ZELERDATA_SMOKE_TOKEN"] == SMOKE_TOKEN
    assert child["PATH"] == "/bin"
    assert "inherited-hostile" not in child.values()


def test_smoke_child_env_is_a_fresh_dict_and_does_not_mutate_baseline() -> None:
    baseline = dict(HOSTILE_BASELINE)
    child = runner.smoke_child_env(
        baseline=baseline,
        base_url=SMOKE_BASE_URL,
        token=SMOKE_TOKEN,
        seller_id=runner.ALLOWED_SELLER,
    )
    assert child is not baseline
    # The baseline input is untouched: hostile keys stay there, none are added.
    assert baseline == HOSTILE_BASELINE


def test_smoke_argv_is_static_path_only_without_credentials() -> None:
    argv = runner.smoke_argv(SMOKE_COMMAND)
    assert argv == ["/usr/local/bin/authenticated_smoke"]
    assert runner.smoke_argv(SMOKE_COMMAND) is not argv
    for secretish in (SMOKE_TOKEN, runner.ALLOWED_SELLER, "42", "latest"):
        assert secretish not in argv


class _RecordingProcessRunner:
    """Fake ProcessSeam implementing the extended run-smoke contract."""

    def __init__(
        self,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
        *,
        raise_timeout: bool = False,
        survival: str = "term",
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.raise_timeout = raise_timeout
        self.active_pid: int | None = None
        # Process-group survival semantics for terminate_descendant tests:
        # "term" dies on TERM, "kill" survives TERM and dies on KILL, and
        # "never" survives both signals.
        self.survival = survival
        self.killed = False
        self.calls: list[dict[str, Any]] = []

    def run_smoke(
        self,
        argv: list[str],
        *,
        env: Mapping[str, str],
        timeout: float,
        shell: bool = False,
    ) -> tuple[int, str, str]:
        self.calls.append({"argv": argv, "env": env, "timeout": timeout})
        if self.raise_timeout:
            raise TimeoutError("smoke timed out")
        return self.returncode, self.stdout, self.stderr

    def terminate_tree(self, pid: int) -> None:
        self.calls.append({"terminate_tree": pid})

    def kill_tree(self, pid: int) -> None:
        self.calls.append({"kill_tree": pid})
        self.killed = True

    def tree_alive(self, pid: int) -> bool:
        self.calls.append({"tree_alive": pid})
        if self.survival == "never":
            return True
        if self.survival == "kill":
            return not self.killed
        return False


def _seams_with_process(process: _RecordingProcessRunner) -> runner.Seams:
    fakes: list[Any] = [_FakeSeam() for _ in range(5)]
    return runner.Seams(
        clock=fakes[0],
        http=fakes[1],
        command=fakes[2],
        lock=fakes[3],
        state=fakes[4],
        process=process,
    )


def test_invoke_smoke_calls_process_seam_exactly_once_and_returns_result() -> None:
    process = _RecordingProcessRunner(returncode=3, stdout="out", stderr="err")
    seams = _seams_with_process(process)
    result = runner.invoke_smoke(
        seams,
        smoke_command=SMOKE_COMMAND,
        baseline_env=HOSTILE_BASELINE,
        base_url=SMOKE_BASE_URL,
        token=SMOKE_TOKEN,
        seller_id=runner.ALLOWED_SELLER,
    )
    assert result == (3, "out", "err")
    assert len(process.calls) == 1
    call = process.calls[0]
    assert call["argv"] == ["/usr/local/bin/authenticated_smoke"]
    assert call["timeout"] == runner.SMOKE_TIMEOUT_SECONDS
    assert "terminate_tree" not in call


def test_invoke_smoke_passes_scrubbed_env_with_exactly_three_smoke_keys() -> None:
    process = _RecordingProcessRunner()
    seams = _seams_with_process(process)
    runner.invoke_smoke(
        seams,
        smoke_command=SMOKE_COMMAND,
        baseline_env=HOSTILE_BASELINE,
        base_url=SMOKE_BASE_URL,
        token=SMOKE_TOKEN,
        seller_id=runner.ALLOWED_SELLER,
    )
    env = process.calls[0]["env"]
    assert env["ZELERDATA_SMOKE_BASE_URL"] == SMOKE_BASE_URL
    assert env["ZELERDATA_SMOKE_TOKEN"] == SMOKE_TOKEN
    assert env["ZELERDATA_SMOKE_SELLER"] == runner.ALLOWED_SELLER
    assert env["PATH"] == "/usr/local/bin:/usr/bin:/bin"
    smoke_keys = sorted(k for k in env if k.startswith("ZELERDATA_SMOKE_"))
    assert smoke_keys == sorted(runner.SMOKE_ENV_KEYS)
    for hostile in (
        "ZELER_APP_BROKER_SECRET",
        "JWT_SECRET",
        "SHEETS_EXTENSION_TOKEN",
        "GCLOUD_ACCESS_TOKEN",
    ):
        assert hostile not in env
    assert "inherited-hostile-token" not in env.values()
    assert "broker-secret" not in env.values()
    # The injected token appears exactly once, as the value of its own key.
    assert list(env.values()).count(SMOKE_TOKEN) == 1


# --- Slice 2C, task 2.4: sentinel/token/version/seller absent from argv, files, output ---


def test_smoke_child_env_contains_only_baseline_plus_exactly_three_smoke_keys() -> None:
    process = _RecordingProcessRunner()
    seams = _seams_with_process(process)
    runner.invoke_smoke(
        seams,
        smoke_command=SMOKE_COMMAND,
        baseline_env=HOSTILE_BASELINE,
        base_url=SMOKE_BASE_URL,
        token=SMOKE_TOKEN,
        seller_id=runner.ALLOWED_SELLER,
    )
    env = process.calls[0]["env"]
    expected = (
        set(HOSTILE_BASELINE)
        - {
            "ZELERDATA_SMOKE_TOKEN",
            "ZELERDATA_SMOKE_BASE_URL",
            "ZELER_APP_BROKER_SECRET",
            "SHEETS_EXTENSION_TOKEN",
            "JWT_SECRET",
            "GCLOUD_ACCESS_TOKEN",
        }
    ) | set(runner.SMOKE_ENV_KEYS)
    assert set(env) == expected


def test_argv_builders_never_contain_token_or_seller() -> None:
    all_argv = [
        runner.add_version_argv(),
        *runner.version_lifecycle_argv("42"),
        runner.smoke_argv(SMOKE_COMMAND),
    ]
    for argv in all_argv:
        assert SMOKE_TOKEN not in argv
        assert SMOKE_TOKEN not in " ".join(argv)
        assert runner.ALLOWED_SELLER not in argv
        assert runner.ALLOWED_SELLER not in " ".join(argv)


def test_redact_sensitive_replaces_token_version_and_seller() -> None:
    message = f"failed: token={SMOKE_TOKEN} seller={runner.ALLOWED_SELLER} version=42"
    redacted = runner.redact_sensitive(
        message, token=SMOKE_TOKEN, version_id="42", seller_id=runner.ALLOWED_SELLER
    )
    assert SMOKE_TOKEN not in redacted
    assert runner.ALLOWED_SELLER not in redacted
    assert "42" not in redacted
    assert redacted == "failed: token=<redacted> seller=<redacted> version=<redacted>"


def test_redact_sensitive_preserves_clean_text_and_empty_values() -> None:
    message = "clean diagnostic line"
    assert runner.redact_sensitive(message, token="", version_id="", seller_id="") == message
    # Values absent from the text leave it unchanged.
    assert (
        runner.redact_sensitive(
            message,
            token="abc",  # noqa: S106 - fake values, tests only
            version_id="123",
            seller_id="987",
        )
        == message
    )


def test_redacted_diagnostic_builds_safe_error_lines() -> None:
    line = runner.redacted_diagnostic(
        f"secret access error: token={SMOKE_TOKEN} seller={runner.ALLOWED_SELLER} version=42",
        token=SMOKE_TOKEN,
        version_id="42",
        seller_id=runner.ALLOWED_SELLER,
    )
    assert SMOKE_TOKEN not in line
    assert runner.ALLOWED_SELLER not in line
    assert "42" not in line
    assert line.startswith("secret access error: token=<redacted>")


def test_redacted_diagnostic_raises_when_redaction_cannot_guarantee_safety() -> None:
    # A sensitive value equal to the placeholder cannot be redacted away; the
    # diagnostic must fail closed instead of emitting an unsafe line.
    with pytest.raises(runner.RedactionError):
        runner.redacted_diagnostic(
            "value <redacted>",
            token=runner.REDACTION_PLACEHOLDER,
            version_id="42",
            seller_id="1",
        )


def test_state_file_content_never_contains_token_or_seller() -> None:
    # The active state file holds only phase/timestamp/version_id; even a fake
    # token or seller value must never reach its serialized content.
    state = runner.build_active_state(
        phase="smoke", timestamp="2026-08-11T12:00:00+00:00", version_id="42"
    )
    content = runner.encode_active_state(state)
    assert SMOKE_TOKEN not in content
    assert runner.ALLOWED_SELLER not in content


# --- Slice 2C, task 2.5: non-blocking flock + atomic mode-0600 active state ---


def test_lock_acquire_false_when_exclusive_flock_already_held(tmp_path: Path) -> None:
    path = tmp_path / "zelerdata-smoke.active"
    first = runner.FlockLock(path)
    second = runner.FlockLock(path)
    assert first.acquire() is True
    # Non-blocking: a second acquire on the same file must fail immediately.
    assert second.acquire() is False
    first.release()
    # After release the lock is reacquirable.
    assert second.acquire() is True
    second.release()


def test_lock_creates_state_file_with_mode_0600(tmp_path: Path) -> None:
    path = tmp_path / "zelerdata-smoke.active"
    lock = runner.FlockLock(path)
    assert lock.acquire() is True
    assert path.exists()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    lock.release()


def test_lock_and_active_state_use_distinct_files_in_one_runtime_directory() -> None:
    assert runner.LOCK_PATH.parent == runner.RUNTIME_DIR
    assert runner.ACTIVE_STATE_PATH.parent == runner.RUNTIME_DIR
    assert runner.LOCK_PATH != runner.ACTIVE_STATE_PATH


def test_lock_file_does_not_materialize_active_state(tmp_path: Path) -> None:
    lock_path = tmp_path / "runner.lock"
    active_path = tmp_path / "active.json"
    lock = runner.FlockLock(lock_path)
    store = runner.AtomicStateStore(active_path)

    assert lock.acquire() is True
    assert store.read() == {}
    assert lock_path.exists()
    assert not active_path.exists()
    lock.release()


def test_concurrent_lock_yields_exact_concurrent_rejection() -> None:
    exit_code, message = runner.lock_and_state_gate(lock_acquired=False, state={})
    assert exit_code == runner.EXIT_CONCURRENT_RUN_REJECTED
    assert message == runner.CONCURRENT_RUN_REJECTED
    assert message == "CONCURRENT_RUN_REJECTED"


def test_stale_or_partial_state_rejects_fail_closed() -> None:
    stale = {
        "phase": "smoke",
        "timestamp": "2026-08-11T12:00:00+00:00",
        "version_id": "42",
    }
    exit_code, message = runner.lock_and_state_gate(lock_acquired=True, state=stale)
    assert exit_code == runner.EXIT_ACTIVE_STATE_REJECTED
    assert message == runner.ACTIVE_STATE_REJECTED


def test_state_file_written_atomically_with_mode_0600(tmp_path: Path) -> None:
    path = tmp_path / "zelerdata-smoke.active"
    store = runner.AtomicStateStore(path)
    store.write({"phase": "smoke", "timestamp": "2026-08-11T12:00:00+00:00", "version_id": "42"})
    assert path.exists()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert store.read() == {
        "phase": "smoke",
        "timestamp": "2026-08-11T12:00:00+00:00",
        "version_id": "42",
    }


def test_state_write_rejects_unsafe_keys_and_preserves_nothing(tmp_path: Path) -> None:
    path = tmp_path / "zelerdata-smoke.active"
    store = runner.AtomicStateStore(path)
    with pytest.raises(runner.ActiveStateError):
        store.write(
            {
                "phase": "smoke",
                "timestamp": "2026-08-11T12:00:00+00:00",
                "version_id": "42",
                "token": SMOKE_TOKEN,
            }
        )
    assert not path.exists()


def test_state_read_rejects_partial_or_malformed_content(tmp_path: Path) -> None:
    path = tmp_path / "zelerdata-smoke.active"
    path.write_text('{"phase": "smoke"}', encoding="utf-8")
    store = runner.AtomicStateStore(path)
    with pytest.raises(runner.ActiveStateError):
        store.read()
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(runner.ActiveStateError):
        store.read()


def test_state_read_returns_empty_when_file_absent(tmp_path: Path) -> None:
    store = runner.AtomicStateStore(tmp_path / "missing.active")
    assert store.read() == {}


# --- Slice 2D, task 2.6: metacharacters, nonzero, malformed, timeout -> fail closed ---

DISABLE_OUTPUT = "Disabled version [{version}] of the secret [{secret}]."
DESTROY_OUTPUT = "Destroyed version [{version}] of the secret [{secret}]."
BOUND_VERSION = "42"


def _smoke_check(seams: runner.Seams, **overrides: Any) -> tuple[int, str]:
    values: dict[str, Any] = {
        "smoke_command": SMOKE_COMMAND,
        "baseline_env": HOSTILE_BASELINE,
        "base_url": SMOKE_BASE_URL,
        "token": SMOKE_TOKEN,
        "seller_id": runner.ALLOWED_SELLER,
        "version_id": BOUND_VERSION,
    }
    values.update(overrides)
    return runner.invoke_smoke_checked(seams, **values)


def _version_op(
    seams: runner.Seams,
    operation: str,
    *,
    version_id: str = BOUND_VERSION,
    **overrides: Any,
) -> tuple[int, str]:
    values: dict[str, Any] = {"token": SMOKE_TOKEN, "seller_id": runner.ALLOWED_SELLER}
    values.update(overrides)
    return runner.version_operation(seams, operation, version_id, **values)


def test_metacharacter_error_rejects_shell_metacharacters() -> None:
    for value in (
        "a;b",
        "a&b",
        "a|b",
        "$HOME",
        "`id`",
        "$(id)",
        'a"b',
        "a(b)",
        "a*b",
        "a!b",
        "a\nb",
        "a\\b",
    ):
        assert runner.metacharacter_error(value) is not None


def test_metacharacter_error_accepts_clean_values() -> None:
    for value in (
        "",
        "https://sheets.zeler.ai",
        "/usr/local/bin/authenticated_smoke",
        "user-abc123",
        "42",
    ):
        assert runner.metacharacter_error(value) is None


def test_invoke_smoke_checked_rejects_metacharacter_values_before_effects() -> None:
    for kwargs in (
        {"smoke_command": Path("/opt/smoke;rm -rf /")},
        {"base_url": "https://evil.example/$(id)"},
    ):
        process = _RecordingProcessRunner()
        seams = _seams_with_process(process)
        exit_code, diagnostic = _smoke_check(seams, **kwargs)
        assert exit_code == runner.EXIT_PROCESS_BOUNDARY_REJECTED
        assert "metacharacter" in diagnostic
        assert process.calls == []


def test_invoke_smoke_checked_success_returns_success() -> None:
    process = _RecordingProcessRunner()
    seams = _seams_with_process(process)
    exit_code, diagnostic = _smoke_check(seams)
    assert exit_code == runner.EXIT_SUCCESS
    assert diagnostic == ""
    assert len(process.calls) == 1


def test_invoke_smoke_checked_nonzero_fails_closed_with_redacted_stderr() -> None:
    process = _RecordingProcessRunner(
        returncode=3, stderr=f"token={SMOKE_TOKEN} seller={runner.ALLOWED_SELLER}"
    )
    seams = _seams_with_process(process)
    exit_code, diagnostic = _smoke_check(seams)
    assert exit_code == runner.EXIT_SMOKE_FAILED
    assert SMOKE_TOKEN not in diagnostic
    assert runner.ALLOWED_SELLER not in diagnostic
    assert diagnostic.startswith("smoke exited with code 3:")


def test_invoke_smoke_checked_timeout_fails_closed() -> None:
    process = _RecordingProcessRunner(raise_timeout=True)
    seams = _seams_with_process(process)
    exit_code, diagnostic = _smoke_check(seams)
    assert exit_code == runner.EXIT_SMOKE_FAILED
    assert "timed out" in diagnostic
    assert SMOKE_TOKEN not in diagnostic
    assert len(process.calls) == 1


def test_version_operation_access_returns_stripped_payload() -> None:
    command = _RecordingCommandRunner(stdout=SMOKE_TOKEN + "\n")
    seams = _seams_with_command(command)
    exit_code, payload = _version_op(seams, "access")
    assert exit_code == runner.EXIT_SUCCESS
    assert payload == SMOKE_TOKEN
    assert command.calls[0]["argv"] == runner.version_operation_argv("access", BOUND_VERSION)
    assert command.calls[0]["stdin"] == ""


def test_version_operation_access_rejects_failed_outcomes() -> None:
    command = _RecordingCommandRunner(returncode=1)
    seams = _seams_with_command(command)
    exit_code, diagnostic = _version_op(seams, "access")
    assert exit_code == runner.EXIT_VERSION_OPERATION_REJECTED
    assert diagnostic.startswith("access exited with code 1")
    assert SMOKE_TOKEN not in diagnostic
    assert runner.ALLOWED_SELLER not in diagnostic
    assert BOUND_VERSION not in diagnostic
    command = _RecordingCommandRunner(stdout="   \n")
    seams = _seams_with_command(command)
    exit_code, diagnostic = _version_op(seams, "access")
    assert exit_code == runner.EXIT_VERSION_OPERATION_REJECTED
    assert "empty secret payload" in diagnostic
    command = _RecordingCommandRunner(raise_timeout=True)
    seams = _seams_with_command(command)
    exit_code, diagnostic = _version_op(seams, "access")
    assert exit_code == runner.EXIT_VERSION_OPERATION_REJECTED
    assert "timed out" in diagnostic
    assert SMOKE_TOKEN not in diagnostic
    assert len(command.calls) == 1


def test_version_operation_disable_destroy_success_on_canonical_output() -> None:
    for operation, output in (("disable", DISABLE_OUTPUT), ("destroy", DESTROY_OUTPUT)):
        command = _RecordingCommandRunner(
            stdout=output.format(version=BOUND_VERSION, secret=runner.SECRET_NAME)
        )
        seams = _seams_with_command(command)
        exit_code, payload = _version_op(seams, operation)
        assert exit_code == runner.EXIT_SUCCESS
        assert payload == ""
        assert command.calls[0]["argv"] == runner.version_operation_argv(operation, BOUND_VERSION)


def test_version_operation_disable_rejects_failed_outcomes() -> None:
    for stdout in (
        "garbage",
        DISABLE_OUTPUT.format(version="7", secret=runner.SECRET_NAME),
        DISABLE_OUTPUT.format(version=BOUND_VERSION, secret="another-secret"),  # noqa: S106 - fixture, tests only
        "Disabled version [42] of the secret [zelerdata-smoke-pilot]\nnote",
    ):
        command = _RecordingCommandRunner(stdout=stdout)
        seams = _seams_with_command(command)
        exit_code, diagnostic = _version_op(seams, "disable")
        assert exit_code == runner.EXIT_VERSION_OPERATION_REJECTED
        assert "malformed" in diagnostic
        assert BOUND_VERSION not in diagnostic
    seams = _seams_with_command(_RecordingCommandRunner(returncode=1))
    exit_code, diagnostic = _version_op(seams, "disable")
    assert exit_code == runner.EXIT_VERSION_OPERATION_REJECTED
    assert diagnostic.startswith("disable exited with code 1")


def test_version_operation_destroy_rejects_malformed_and_timeout() -> None:
    command = _RecordingCommandRunner(stdout="garbage")
    seams = _seams_with_command(command)
    exit_code, diagnostic = _version_op(seams, "destroy")
    assert exit_code == runner.EXIT_VERSION_OPERATION_REJECTED
    assert "malformed" in diagnostic
    command = _RecordingCommandRunner(raise_timeout=True)
    seams = _seams_with_command(command)
    exit_code, diagnostic = _version_op(seams, "destroy")
    assert exit_code == runner.EXIT_VERSION_OPERATION_REJECTED
    assert "timed out" in diagnostic


def test_version_operation_rejects_metacharacter_version_id_before_effects() -> None:
    command = _RecordingCommandRunner()
    seams = _seams_with_command(command)
    with pytest.raises(runner.VersionIdError):
        _version_op(seams, "disable", version_id="42;rm -rf")
    assert command.calls == []


def test_add_version_timeout_fails_closed() -> None:
    command = _RecordingCommandRunner(raise_timeout=True)
    seams = _seams_with_command(command)
    exit_code, version_id = runner.add_version(seams, token=SMOKE_TOKEN)
    assert exit_code == runner.EXIT_ADD_VERSION_REJECTED
    assert version_id == ""
    assert len(command.calls) == 1


# --- Slice 2E, task 2.7: forked descendant TERM + bounded KILL; no survivor ---


class _FakeClock:
    """Deterministic monotonic clock: ``sleep`` advances the current time."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class _RealProcessGroup:
    """Real local process-group harness: TERM/KILL via killpg, zombie-aware."""

    active_pid: int | None = None

    def run_smoke(
        self,
        argv: list[str],
        *,
        env: Mapping[str, str],
        timeout: float,
        shell: bool = False,
    ) -> tuple[int, str, str]:
        raise AssertionError("run_smoke is not used by the termination harness")

    def terminate_tree(self, pid: int) -> None:
        os.killpg(pid, signal.SIGTERM)

    def kill_tree(self, pid: int) -> None:
        os.killpg(pid, signal.SIGKILL)

    def tree_alive(self, pid: int) -> bool:
        # Reap the direct child if it exited so a zombie never counts as a
        # survivor; then probe the remaining process group.
        with contextlib.suppress(ChildProcessError):
            os.waitpid(-pid, os.WNOHANG)
        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True


def _terminate(process: _RecordingProcessRunner, pid: int = 4242) -> tuple[int, str]:
    clock = _FakeClock()
    fakes: list[Any] = [_FakeSeam() for _ in range(5)]
    seams = runner.Seams(
        clock=fakes[0],
        http=fakes[1],
        command=fakes[2],
        lock=fakes[3],
        state=fakes[4],
        process=process,
    )
    return runner.terminate_descendant(
        seams,
        pid,
        term_grace=5.0,
        kill_grace=5.0,
        poll_interval=0.1,
        monotonic=clock,
        sleep=clock.sleep,
    )


def _call_kinds(process: _RecordingProcessRunner) -> list[str]:
    return [next(iter(call)) for call in process.calls]


def test_terminate_descendant_terms_group_when_it_exits() -> None:
    process = _RecordingProcessRunner(survival="term")
    exit_code, diagnostic = _terminate(process)
    assert exit_code == runner.EXIT_SUCCESS
    assert diagnostic == ""
    kinds = _call_kinds(process)
    assert kinds.count("terminate_tree") == 1
    assert "kill_tree" not in kinds
    assert kinds.count("tree_alive") >= 1


def test_terminate_descendant_escalates_to_kill_when_term_ignored() -> None:
    process = _RecordingProcessRunner(survival="kill")
    exit_code, diagnostic = _terminate(process)
    assert exit_code == runner.EXIT_SUCCESS
    assert diagnostic == ""
    kinds = _call_kinds(process)
    assert kinds.index("terminate_tree") < kinds.index("kill_tree")
    assert "tree_alive" in kinds


def test_terminate_descendant_survivor_fails_closed() -> None:
    process = _RecordingProcessRunner(survival="never")
    exit_code, diagnostic = _terminate(process)
    assert exit_code == runner.EXIT_PROCESS_BOUNDARY_REJECTED
    assert "survived TERM and KILL" in diagnostic
    kinds = _call_kinds(process)
    assert kinds.index("terminate_tree") < kinds.index("kill_tree")
    assert kinds.count("tree_alive") >= 2


_GROUP_CODE = (
    "import subprocess, sys, time\n"
    "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
    "print(p.pid, flush=True)\n"
    "time.sleep(60)\n"
)
_GROUP_IGNORES_TERM_CODE = (
    "import signal, subprocess, sys, time\n"
    "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
    "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
    "print(p.pid, flush=True)\n"
    "time.sleep(60)\n"
)


def _terminate_real_group(code: str) -> tuple[subprocess.Popen[str], int, tuple[int, str]]:
    leader = subprocess.Popen(  # noqa: S603 - static argv: interpreter plus fixed harness code.
        [sys.executable, "-c", code],
        start_new_session=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    assert leader.stdout is not None
    descendant_pid = int(leader.stdout.readline().strip())
    try:
        fakes: list[Any] = [_FakeSeam() for _ in range(5)]
        seams = runner.Seams(
            clock=fakes[0],
            http=fakes[1],
            command=fakes[2],
            lock=fakes[3],
            state=fakes[4],
            process=_RealProcessGroup(),
        )
        result = runner.terminate_descendant(
            seams, leader.pid, term_grace=2.0, kill_grace=2.0, poll_interval=0.05
        )
        return leader, descendant_pid, result
    except BaseException:
        _kill_group(leader)
        raise


def _wait_gone(probe: Callable[[], None], *, timeout: float = 2.0) -> None:
    # A dead child lingers as a zombie until reaped; wait (bounded) for that.
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            probe()
        except ProcessLookupError:
            return
        time.sleep(0.05)
    raise AssertionError("process still present after the bounded wait")


def _kill_group(leader: subprocess.Popen[str]) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(leader.pid, signal.SIGKILL)
    with contextlib.suppress(subprocess.TimeoutExpired):
        leader.wait(timeout=2.0)


@pytest.mark.parametrize(
    "code", [_GROUP_CODE, _GROUP_IGNORES_TERM_CODE], ids=["term", "kill-escalation"]
)
def test_terminate_descendant_real_group_leaves_no_survivor(code: str) -> None:
    # Controlled local harness: a python leader starts in its own process
    # group, forks a python descendant, and both sleep. The second variant's
    # leader ignores SIGTERM, so only the bounded KILL escalation can take the
    # group down. TERM then bounded KILL must leave no survivor; no external
    # command, network, or GCP is involved.
    leader, descendant_pid, (exit_code, diagnostic) = _terminate_real_group(code)
    assert exit_code == runner.EXIT_SUCCESS
    assert diagnostic == ""
    _wait_gone(lambda: os.killpg(leader.pid, 0))
    _wait_gone(lambda: os.kill(descendant_pid, 0))
    _kill_group(leader)


# --- Slice 2E, task 2.8: SIGINT/SIGTERM one cleanup transition; SIGKILL recovery state ---


def test_cleanup_request_transitions_exactly_once() -> None:
    cleanup = runner.CleanupRequest()
    assert cleanup.requested is False
    assert cleanup.request() is True
    assert cleanup.request() is False
    assert cleanup.request() is False
    assert cleanup.requested is True


@pytest.mark.parametrize("signal_number", [signal.SIGINT, signal.SIGTERM])
def test_interrupt_exit_requests_cleanup_once_and_fails_closed(signal_number: int) -> None:
    cleanup = runner.CleanupRequest()
    exit_code, diagnostic = runner.interrupt_exit(
        cleanup,
        signal_number=signal_number,
        token=SMOKE_TOKEN,
        version_id=BOUND_VERSION,
        seller_id=runner.ALLOWED_SELLER,
    )
    assert exit_code == runner.EXIT_INTERRUPTED
    assert exit_code != runner.EXIT_SUCCESS  # never a false success
    assert f"interrupted by signal {signal_number}" in diagnostic
    assert SMOKE_TOKEN not in diagnostic
    assert BOUND_VERSION not in diagnostic
    assert runner.ALLOWED_SELLER not in diagnostic
    assert cleanup.requested is True
    assert cleanup.request() is False  # exactly one cleanup-request transition


@pytest.mark.parametrize("signal_number", [signal.SIGKILL, signal.SIGHUP, 0])
def test_interrupt_exit_rejects_non_handled_signals(signal_number: int) -> None:
    with pytest.raises(ValueError):
        runner.interrupt_exit(
            runner.CleanupRequest(),
            signal_number=signal_number,
            token=SMOKE_TOKEN,
            version_id=BOUND_VERSION,
            seller_id=runner.ALLOWED_SELLER,
        )


def test_interrupt_and_sigkill_preserve_recovery_state_without_cleanup_claims(
    tmp_path: Path,
) -> None:
    # Interrupted (SIGINT/SIGTERM) and SIGKILLed/VM-lost runs leave the active
    # state untouched and never claim cleanup: no version operation or revoke
    # command is attempted and the state remains readable.
    path = tmp_path / "zelerdata-smoke.active"
    store = runner.AtomicStateStore(path)
    state = {
        "phase": "smoke",
        "timestamp": "2026-08-11T12:00:00+00:00",
        "version_id": BOUND_VERSION,
    }
    store.write(state)
    command = _RecordingCommandRunner()
    _seams_with_command(command)
    exit_code, diagnostic = runner.interrupt_exit(
        runner.CleanupRequest(),
        signal_number=signal.SIGTERM,
        token=SMOKE_TOKEN,
        version_id=BOUND_VERSION,
        seller_id=runner.ALLOWED_SELLER,
    )
    assert exit_code == runner.EXIT_INTERRUPTED
    assert SMOKE_TOKEN not in diagnostic
    assert store.read() == state  # fail-closed state preserved, not removed
    assert command.calls == []  # no cleanup claim (disable/destroy/revoke)
    # SIGKILL/VM loss means no handler ever runs: a later run still fails
    # closed on the leftover recovery state.
    assert runner.lock_and_state_gate(lock_acquired=True, state=store.read()) == (
        runner.EXIT_ACTIVE_STATE_REJECTED,
        runner.ACTIVE_STATE_REJECTED,
    )


# --- Slice 2F, task 2.9: fake-testable cleanup transaction; ordered, no false success ---


class _FakeCleanupStep:
    """Injected cleanup step: records every invocation and returns its result."""

    def __init__(self, result: tuple[int, str] = (runner.EXIT_SUCCESS, "")) -> None:
        self.result = result
        self.calls: list[tuple[int, str]] = []

    def __call__(self) -> tuple[int, str]:
        self.calls.append(self.result)
        return self.result


def _plan_with(
    failures: dict[str, tuple[int, str]] | None = None,
) -> tuple[runner.CleanupPlan, dict[str, _FakeCleanupStep]]:
    failures = failures or {}
    steps = {
        name: _FakeCleanupStep(failures.get(name, (runner.EXIT_SUCCESS, "")))
        for name in runner.CLEANUP_STEP_NAMES
    }
    return (
        runner.CleanupPlan(
            disable=steps["disable"],
            destroy=steps["destroy"],
            re_broker=steps["re-broker"],
            revoke=steps["revoke"],
        ),
        steps,
    )


def _sensitive() -> tuple[str, str, str]:
    return (SMOKE_TOKEN, BOUND_VERSION, runner.ALLOWED_SELLER)


@pytest.mark.parametrize(
    "version_eligible,token_eligible,expected_attempted,expected_removable",
    [
        (True, True, runner.CLEANUP_STEP_NAMES, True),
        (False, True, ("re-broker", "revoke"), False),
        (True, False, ("disable", "destroy"), False),
        (False, False, (), False),
    ],
)
def test_cleanup_plan_runs_eligible_steps_in_canonical_order(
    version_eligible: bool,
    token_eligible: bool,
    expected_attempted: tuple[str, ...],
    expected_removable: bool,
) -> None:
    plan, steps = _plan_with()
    outcome = runner.run_cleanup_plan(
        plan,
        version_eligible=version_eligible,
        token_eligible=token_eligible,
        sensitive=_sensitive(),
    )
    assert outcome.exit_code == runner.EXIT_SUCCESS
    assert outcome.attempted == expected_attempted
    assert outcome.failed == () and outcome.diagnostic == ""
    assert outcome.state_removable is expected_removable
    assert {name: len(step.calls) for name, step in steps.items()} == {
        name: (1 if name in expected_attempted else 0) for name in runner.CLEANUP_STEP_NAMES
    }


@pytest.mark.parametrize(
    "failing_step,expected_removable",
    [("disable", True), ("destroy", False), ("revoke", False)],
)
def test_cleanup_plan_step_failure_fails_closed_keeps_order_and_redacts(
    failing_step: str, expected_removable: bool
) -> None:
    leaking = f"{failing_step} failed for token={SMOKE_TOKEN} version={BOUND_VERSION}"
    plan, steps = _plan_with(failures={failing_step: (7, leaking)})
    outcome = runner.run_cleanup_plan(
        plan, version_eligible=True, token_eligible=True, sensitive=_sensitive()
    )
    assert outcome.exit_code == runner.EXIT_CLEANUP_REJECTED  # never a false success
    assert outcome.attempted == runner.CLEANUP_STEP_NAMES  # ordered all-attempt
    assert outcome.failed == (failing_step,)
    assert failing_step in outcome.diagnostic
    assert all(sensitive not in outcome.diagnostic for sensitive in _sensitive())
    assert outcome.state_removable is expected_removable
    # Every eligible step runs exactly once, including after the failure.
    assert all(len(step.calls) == 1 for step in steps.values())


def test_cleanup_plan_re_broker_failure_skips_revoke_and_fails_closed() -> None:
    plan, steps = _plan_with(failures={"re-broker": (1, f"re-broker rejected token={SMOKE_TOKEN}")})
    outcome = runner.run_cleanup_plan(
        plan, version_eligible=True, token_eligible=True, sensitive=_sensitive()
    )
    assert outcome.exit_code == runner.EXIT_CLEANUP_REJECTED != runner.EXIT_SUCCESS
    assert outcome.attempted == ("disable", "destroy", "re-broker")
    assert outcome.failed == ("re-broker",) and steps["revoke"].calls == []
    assert SMOKE_TOKEN not in outcome.diagnostic
    assert outcome.state_removable is False


def _fail_stage(stage: str) -> tuple[int, str]:
    """Real stage outcome for a failing run phase, via existing runner functions."""
    if stage == "add":
        return runner.add_version(
            _seams_with_command(_RecordingCommandRunner(returncode=1)), token=SMOKE_TOKEN
        )
    if stage == "access":
        seams = _seams_with_command(_RecordingCommandRunner(returncode=1))
        return runner.version_operation(
            seams, "access", BOUND_VERSION, token=SMOKE_TOKEN, seller_id=runner.ALLOWED_SELLER
        )
    seams = _seams_with_process(
        _RecordingProcessRunner(returncode=3, stderr=f"token={SMOKE_TOKEN}")
    )
    return runner.invoke_smoke_checked(
        seams,
        smoke_command=SMOKE_COMMAND,
        baseline_env=HOSTILE_BASELINE,
        base_url=SMOKE_BASE_URL,
        token=SMOKE_TOKEN,
        seller_id=runner.ALLOWED_SELLER,
        version_id=BOUND_VERSION,
    )


@pytest.mark.parametrize(
    "stage,version_eligible,expected_attempted",
    [
        ("add", False, ("re-broker", "revoke")),
        ("access", True, runner.CLEANUP_STEP_NAMES),
        ("smoke", True, runner.CLEANUP_STEP_NAMES),
    ],
    ids=["add", "access", "smoke"],
)
def test_run_failure_at_stage_keeps_eligible_cleanup_and_never_succeeds(
    stage: str, version_eligible: bool, expected_attempted: tuple[str, ...]
) -> None:
    stage_result = _fail_stage(stage)
    assert stage_result[0] != runner.EXIT_SUCCESS
    plan, steps = _plan_with()
    cleanup = runner.run_cleanup_plan(
        plan, version_eligible=version_eligible, token_eligible=True, sensitive=_sensitive()
    )
    assert cleanup.exit_code == runner.EXIT_SUCCESS
    assert cleanup.attempted == expected_attempted
    final = runner.finalize_result(stage_result, cleanup, sensitive=_sensitive())
    # The run failure is preserved: cleanup success never turns it into success.
    assert final[0] == stage_result[0] != runner.EXIT_SUCCESS
    assert all(sensitive not in final[1] for sensitive in _sensitive())
    assert {name: len(step.calls) for name, step in steps.items()} == {
        name: (1 if name in expected_attempted else 0) for name in runner.CLEANUP_STEP_NAMES
    }


class _CleanupCommandRunner:
    """Command fake returning canonical gcloud output per version operation."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def run(
        self,
        argv: list[str],
        *,
        stdin: str,
        env: Mapping[str, str],
        timeout: float,
        shell: bool = False,
    ) -> tuple[int, str, str]:
        self.calls.append({"argv": argv, "stdin": stdin, "env": env, "timeout": timeout})
        operation = argv[3]
        template = {"disable": DISABLE_OUTPUT, "destroy": DESTROY_OUTPUT}[operation]
        return 0, template.format(version=BOUND_VERSION, secret=runner.SECRET_NAME), ""


def test_cleanup_plan_wires_disable_destroy_to_captured_version_operation() -> None:
    command = _CleanupCommandRunner()
    fakes: list[Any] = [_FakeSeam() for _ in range(5)]
    seams = runner.Seams(
        clock=fakes[0],
        http=fakes[1],
        command=command,
        lock=fakes[2],
        state=fakes[3],
        process=fakes[4],
    )

    def op(operation: str) -> Callable[[], tuple[int, str]]:
        return lambda: runner.version_operation(
            seams, operation, BOUND_VERSION, token=SMOKE_TOKEN, seller_id=runner.ALLOWED_SELLER
        )

    plan = runner.CleanupPlan(
        disable=op("disable"),
        destroy=op("destroy"),
        re_broker=lambda: (runner.EXIT_SUCCESS, ""),
        revoke=lambda: (runner.EXIT_SUCCESS, ""),
    )
    outcome = runner.run_cleanup_plan(
        plan, version_eligible=True, token_eligible=True, sensitive=_sensitive()
    )
    assert outcome.exit_code == runner.EXIT_SUCCESS
    assert outcome.attempted == runner.CLEANUP_STEP_NAMES
    argv_order = [call["argv"] for call in command.calls]
    assert [argv[3] for argv in argv_order] == ["disable", "destroy"]
    # The captured explicit version ID flows into both operations, never latest.
    assert all(
        argv[4] == BOUND_VERSION
        and "latest" not in argv
        and argv[5] == f"--secret={runner.SECRET_NAME}"
        for argv in argv_order
    )


def test_finalize_result_success_only_when_run_and_cleanup_succeed() -> None:
    ok = runner.CleanupOutcome(runner.CLEANUP_STEP_NAMES, (), runner.EXIT_SUCCESS, "")
    failed = runner.CleanupOutcome(
        ("disable", "destroy"),
        ("destroy",),
        runner.EXIT_CLEANUP_REJECTED,
        "cleanup failed for: destroy: destroy rejected",
    )
    failed_run = (runner.EXIT_ADD_VERSION_REJECTED, "")
    result = runner.finalize_result((runner.EXIT_SUCCESS, ""), ok, sensitive=_sensitive())
    assert result == (runner.EXIT_SUCCESS, "")
    result = runner.finalize_result((runner.EXIT_SUCCESS, ""), failed, sensitive=_sensitive())
    assert result == (runner.EXIT_CLEANUP_REJECTED, failed.diagnostic)
    assert runner.finalize_result(failed_run, ok, sensitive=_sensitive()) == failed_run


def test_finalize_result_combines_run_and_cleanup_failures_redaction_safe() -> None:
    run_result = (runner.EXIT_SMOKE_FAILED, f"smoke leaked token={SMOKE_TOKEN}")
    cleanup = runner.CleanupOutcome(
        runner.CLEANUP_STEP_NAMES,
        ("revoke",),
        runner.EXIT_CLEANUP_REJECTED,
        f"revoke failed seller={runner.ALLOWED_SELLER}",
    )
    final = runner.finalize_result(run_result, cleanup, sensitive=_sensitive())
    assert final[0] == runner.EXIT_SMOKE_FAILED  # primary failure code preserved
    assert "smoke leaked token=<redacted>" in final[1]
    assert "revoke failed seller=<redacted>" in final[1]
    assert all(sensitive not in final[1] for sensitive in _sensitive())


# --- Slice 2G, task 2.10: final lifecycle orchestration ---


class _LifecycleFake:
    def __init__(self, *, smoke_returncode: int = 0, cleanup_failure: str | None = None) -> None:
        self.calls: list[str] = []
        self.command_calls: list[dict[str, Any]] = []
        self.http_calls: list[dict[str, Any]] = []
        self.state: dict[str, str] = {}
        self.smoke_returncode = smoke_returncode
        self.cleanup_failure = cleanup_failure
        self.active_pid: int | None = None

    def utcnow(self) -> datetime:
        return NOW

    def post(self, url: str, payload: str, headers: Mapping[str, str]) -> tuple[int, str]:
        self.http_calls.append({"url": url, "payload": payload, "headers": headers})
        self.calls.append("broker" if url == runner.BROKER_TOKEN_URL else "http:" + url)
        if url == runner.BROKER_TOKEN_URL:
            return 200, json.dumps({"access_token": "broker-jwt"})
        if url == runner.EXTENSION_TOKEN_URL:
            return 201, json.dumps({"id": "token-id", "token_once": SMOKE_TOKEN})
        if url.endswith(":revoke"):
            if self.cleanup_failure == "revoke":
                return 500, "revoke failed"
            return 200, "{}"
        raise AssertionError(f"unexpected URL: {url}")

    def run(
        self,
        argv: list[str],
        *,
        stdin: str,
        env: Mapping[str, str],
        timeout: float,
        shell: bool,
    ) -> tuple[int, str, str]:
        operation = argv[3]
        self.command_calls.append({"argv": argv, "stdin": stdin, "env": env, "shell": shell})
        if operation == "add":
            self.calls.append("add")
            return 0, ADD_OUTPUT.format(version=BOUND_VERSION, secret=runner.SECRET_NAME), ""
        self.calls.append(operation)
        if operation == "access":
            return 0, SMOKE_TOKEN, ""
        if operation == self.cleanup_failure:
            return 1, "cleanup failed", ""
        output = {"disable": DISABLE_OUTPUT, "destroy": DESTROY_OUTPUT}[operation]
        return 0, output.format(version=BOUND_VERSION, secret=runner.SECRET_NAME), ""

    def acquire(self) -> bool:
        self.calls.append("acquire")
        return True

    def release(self) -> None:
        self.calls.append("release")

    def read(self) -> Mapping[str, Any]:
        return self.state

    def write(self, state: Mapping[str, Any]) -> None:
        self.state = dict(state)
        self.calls.append("state:write")

    def remove(self) -> None:
        self.state = {}
        self.calls.append("state:remove")

    def run_smoke(
        self,
        argv: list[str],
        *,
        env: Mapping[str, str],
        timeout: float,
        shell: bool,
    ) -> tuple[int, str, str]:
        self.calls.append("smoke")
        return self.smoke_returncode, "", "smoke failed" if self.smoke_returncode else ""

    def terminate_tree(self, pid: int) -> None:
        raise AssertionError("termination is not expected in this fake")

    def kill_tree(self, pid: int) -> None:
        raise AssertionError("termination is not expected in this fake")

    def tree_alive(self, pid: int) -> bool:
        return False


class _InterruptingLifecycleFake(_LifecycleFake):
    def __init__(self, *, termination_signal: signal.Signals = signal.SIGTERM) -> None:
        super().__init__()
        self.active_pid = 4242
        self.termination_signal = termination_signal
        self.installed_handlers: dict[signal.Signals, Callable[..., None]] = {}

    def run_smoke(
        self,
        argv: list[str],
        *,
        env: Mapping[str, str],
        timeout: float,
        shell: bool,
    ) -> tuple[int, str, str]:
        self.calls.append("smoke")
        self.installed_handlers[self.termination_signal](self.termination_signal, None)
        return 0, "", ""


def _lifecycle_seams(fake: _LifecycleFake) -> runner.Seams:
    return runner.Seams(
        clock=fake,
        http=fake,
        command=fake,
        lock=fake,
        state=fake,
        process=fake,
    )


def _install_signal_fakes(
    monkeypatch: pytest.MonkeyPatch, fake: _InterruptingLifecycleFake
) -> None:
    monkeypatch.setattr(signal, "getsignal", lambda _signal_number: None)

    def install(signal_number: signal.Signals, handler: Callable[..., None]) -> None:
        fake.installed_handlers[signal_number] = handler

    monkeypatch.setattr(signal, "signal", install)


@pytest.mark.parametrize("termination_signal", [signal.SIGINT, signal.SIGTERM])
def test_run_terminates_active_smoke_group_before_requesting_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    termination_signal: signal.Signals,
) -> None:
    fake = _InterruptingLifecycleFake(termination_signal=termination_signal)
    _install_signal_fakes(monkeypatch, fake)
    events: list[str] = []
    original_interrupt_exit = runner.interrupt_exit

    def terminate(*args: Any, **kwargs: Any) -> tuple[int, str]:
        events.append("terminate")
        assert args[1] == fake.active_pid
        return runner.EXIT_SUCCESS, ""

    def interrupt(*args: Any, **kwargs: Any) -> tuple[int, str]:
        events.append("interrupt")
        return original_interrupt_exit(*args, **kwargs)

    monkeypatch.setattr(runner, "terminate_descendant", terminate)
    monkeypatch.setattr(runner, "interrupt_exit", interrupt)
    monkeypatch.setattr(os, "environ", {"PATH": "/bin"})

    result = runner.run(_inputs(), _lifecycle_seams(fake))

    assert result == runner.EXIT_INTERRUPTED
    assert events == ["terminate", "interrupt"]
    assert fake.calls.index("disable") > fake.calls.index("smoke")


def test_run_fails_closed_and_preserves_state_when_group_termination_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _InterruptingLifecycleFake()
    _install_signal_fakes(monkeypatch, fake)
    monkeypatch.setattr(
        runner,
        "terminate_descendant",
        lambda *args, **kwargs: (runner.EXIT_PROCESS_BOUNDARY_REJECTED, "survivor"),
    )
    monkeypatch.setattr(os, "environ", {"PATH": "/bin"})

    result = runner.run(_inputs(), _lifecycle_seams(fake))

    assert result == runner.EXIT_PROCESS_BOUNDARY_REJECTED
    assert fake.state["version_id"] == BOUND_VERSION
    assert "disable" not in fake.calls
    assert "destroy" not in fake.calls
    assert "state:remove" not in fake.calls


def test_run_orchestrates_lifecycle_order_ttls_shell_boundary_and_removes_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _LifecycleFake()
    monkeypatch.setattr(os, "environ", {"PATH": "/bin"})
    result = runner.run(_inputs(), _lifecycle_seams(fake))

    assert result == runner.EXIT_SUCCESS
    assert fake.calls == [
        "acquire",
        "broker",
        "http:/sheets/extension-tokens",
        "add",
        "state:write",
        "access",
        "smoke",
        "disable",
        "destroy",
        "broker",
        "http:/sheets/extension-tokens/token-id:revoke",
        "state:remove",
        "release",
    ]
    assert all(call["shell"] is False for call in fake.command_calls)
    broker_bodies = [
        json.loads(call["payload"])
        for call in fake.http_calls
        if call["url"] == runner.BROKER_TOKEN_URL
    ]
    assert len(broker_bodies) == 2
    assert all(
        body["ttl_s"] <= 300
        and body["token_kind"] == "module_admin"  # noqa: S105 - token kind discriminator.
        and body["target_module_id"] == "sheets"
        and body["scopes"] == ["admin:sheets"]
        for body in broker_bodies
    )
    extension_body = json.loads(
        next(
            call["payload"] for call in fake.http_calls if call["url"] == runner.EXTENSION_TOKEN_URL
        )
    )
    expires_at = datetime.fromisoformat(extension_body["expires_at"])
    assert (expires_at - NOW).total_seconds() <= 3600
    assert fake.state == {}


@pytest.mark.parametrize("failure", ["smoke", "destroy", "revoke"])
def test_run_preserves_failure_and_active_state_on_incomplete_cleanup(
    failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _LifecycleFake(
        smoke_returncode=3 if failure == "smoke" else 0,
        cleanup_failure=None if failure == "smoke" else failure,
    )
    monkeypatch.setattr(os, "environ", {"PATH": "/bin"})
    result = runner.run(_inputs(), _lifecycle_seams(fake))

    assert result != runner.EXIT_SUCCESS
    assert fake.calls[-1] == "release"
    assert fake.state if failure in {"destroy", "revoke"} else fake.state == {}
    if failure == "smoke":
        assert fake.state == {}
    else:
        assert fake.state["version_id"] == BOUND_VERSION
