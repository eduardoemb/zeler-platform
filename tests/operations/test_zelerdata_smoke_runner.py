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

import dataclasses
import json
import os
import stat
import subprocess
import sys
from collections.abc import Mapping
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
    assert body["platform_user_id"] == "user-abc123"
    assert body["module"] == "sheets" and body["scope"] == "admin:sheets"
    assert body["ttl_seconds"] == 300 and body["iat"] == int(NOW.timestamp())


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
    assert argv == ["gcloud", "secrets", "versions", "disable", "42", runner.SECRET_NAME]


def test_destroy_version_operation_argv_is_quiet_and_secret_free() -> None:
    argv = runner.version_operation_argv("destroy", "42")
    assert argv == [
        "gcloud",
        "secrets",
        "versions",
        "destroy",
        "42",
        runner.SECRET_NAME,
        "--quiet",
    ]
    assert "super-secret-token" not in argv
    assert runner.ALLOWED_SELLER not in argv


def test_version_lifecycle_argv_binds_one_captured_id_across_all_operations() -> None:
    access, disable, destroy = runner.version_lifecycle_argv("42")
    assert access == ["gcloud", "secrets", "versions", "access", "42", runner.SECRET_NAME]
    assert disable == ["gcloud", "secrets", "versions", "disable", "42", runner.SECRET_NAME]
    assert destroy == [
        "gcloud",
        "secrets",
        "versions",
        "destroy",
        "42",
        runner.SECRET_NAME,
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
