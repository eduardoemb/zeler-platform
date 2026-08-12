"""Focused tests for the fixed-scope B1 host adapter and CLI."""

from __future__ import annotations

import base64
import hashlib
import hmac
import subprocess
from pathlib import Path
from typing import Any

import pytest
from infra.gce.operations import zelerdata_smoke_cli as cli


class _Response:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class _Command:
    def __init__(self, secret: str = "broker-secret") -> None:  # noqa: S107 - fake fixture only.
        self.secret = secret
        self.calls: list[dict[str, Any]] = []

    def read_broker_secret(self) -> str:
        self.calls.append({"operation": "read_broker_secret"})
        return self.secret


def test_cli_constants_are_fixed_and_only_platform_user_is_an_argument() -> None:
    parser = cli.build_parser()
    actions = {action.dest for action in parser._actions if action.dest != "help"}
    assert actions == {"platform_user_id"}
    assert cli.PROJECT_ID == "zeler-platform-dev"
    assert cli.BROKER_SECRET_NAME == "zeler-app-broker-secret"  # noqa: S105 - fixed name assertion.
    assert (
        Path("/opt/zeler-platform/zelerdata-smoke/bin/launch_authenticated_smoke")
        == cli.SMOKE_COMMAND
    )


def test_cli_runner_import_resolves_to_the_deployed_package_module() -> None:
    source = Path(cli.__file__).read_text(encoding="utf-8")
    assert "from infra.gce.operations import zelerdata_smoke_runner as runner" in source


def test_help_does_not_construct_or_call_operational_adapters(
    capsys: pytest.CaptureFixture[str],
) -> None:
    command = _Command()
    with pytest.raises(SystemExit) as raised:
        cli.main(["--help"], command_runner=command)
    assert raised.value.code == 0
    assert command.calls == []
    assert "--platform-user-id" in capsys.readouterr().out


def test_invalid_cli_input_has_no_effect_and_does_not_echo_identifier(
    capsys: pytest.CaptureFixture[str],
) -> None:
    command = _Command()
    with pytest.raises(SystemExit) as raised:
        cli.main(["--seller-id", "82453304"], command_runner=command)
    assert raised.value.code == 2
    output = capsys.readouterr()
    assert command.calls == []
    assert "82453304" not in output.out + output.err


def test_valid_cli_only_passes_platform_user_to_fixed_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = _Command()
    captured: dict[str, Any] = {}

    def execute(inputs: Any, seams: Any) -> int:
        captured["inputs"] = inputs
        captured["seams"] = seams
        return 0

    assert (
        cli.main(["--platform-user-id", "user-abc"], command_runner=command, execute=execute) == 0
    )
    inputs = captured["inputs"]
    assert inputs.platform_user_id == "user-abc"
    assert inputs.secret_name == cli.SMOKE_SECRET_NAME
    assert inputs.seller_id == cli.SELLER_ID
    assert inputs.base_url == cli.SHEETS_BASE_URL
    assert command.calls == [{"operation": "read_broker_secret"}]


def test_broker_http_call_uses_compact_hmac_and_required_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def open_url(request: Any, *, timeout: float) -> _Response:
        captured["request"] = request
        captured["timeout"] = timeout
        return _Response(200, b'{"access_token":"jwt"}')

    monkeypatch.setattr(cli, "urlopen", open_url)
    transport = cli.FixedHttpTransport("broker-secret")
    payload = '{"module":"sheets","platform_user_id":"user-abc"}'
    status, body = transport.post("/internal/tokens/issue", payload, {})
    request = captured["request"]
    expected = hmac.new(b"broker-secret", payload.encode(), hashlib.sha256).digest()
    signature = "sha256=" + base64.urlsafe_b64encode(expected).rstrip(b"=").decode("ascii")

    assert status == 200
    assert body == '{"access_token":"jwt"}'
    assert request.full_url == f"{cli.GATEWAY_BASE_URL}/internal/tokens/issue"
    assert request.data == payload.encode()
    assert request.headers["X-zeler-client-id"] == "zeler-app"
    assert request.headers["X-zeler-signature"] == signature
    assert "Authorization" not in request.headers


def test_sheets_http_call_uses_bearer_and_not_gateway_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def open_url(request: Any, *, timeout: float) -> _Response:
        captured["request"] = request
        return _Response(200, b"{}")

    monkeypatch.setattr(cli, "urlopen", open_url)
    transport = cli.FixedHttpTransport("broker-secret")
    status, _body = transport.post(
        "/sheets/formulas:execute",
        "{}",
        {"Authorization": "Bearer extension-token"},
    )
    request = captured["request"]
    assert status == 200
    assert request.full_url == f"{cli.SHEETS_BASE_URL}/sheets/formulas:execute"
    assert request.headers["Authorization"] == "Bearer extension-token"
    assert "X-zeler-signature" not in request.headers
    assert "X-zeler-client-id" not in request.headers


def test_http_failures_and_unknown_routes_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def open_url(_request: Any, *, timeout: float) -> _Response:
        raise OSError("controlled transport failure")

    monkeypatch.setattr(cli, "urlopen", open_url)
    transport = cli.FixedHttpTransport("broker-secret")
    assert transport.post("/internal/tokens/issue", "{}", {}) == (599, "")
    with pytest.raises(cli.AdapterError):
        transport.post("https://arbitrary.example", "{}", {})


def test_http_invalid_json_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def open_url(_request: Any, *, timeout: float) -> _Response:
        return _Response(200, b"not-json")

    monkeypatch.setattr(cli, "urlopen", open_url)
    assert cli.FixedHttpTransport("broker-secret").post("/internal/tokens/issue", "{}", {}) == (
        599,
        "",
    )


def test_sheets_rejects_non_bearer_authorization_before_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def open_url(_request: Any, *, timeout: float) -> _Response:
        nonlocal called
        called = True
        return _Response(200, b"{}")

    monkeypatch.setattr(cli, "urlopen", open_url)
    with pytest.raises(cli.AdapterError):
        cli.FixedHttpTransport("broker-secret").post(
            cli.SHEETS_FORMULA_EXECUTE_PATH, "{}", {"Authorization": "Basic value"}
        )
    assert called is False


def test_gcloud_command_uses_static_project_and_secret_stays_out_of_argv_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append({"argv": argv, **kwargs})
        return subprocess.CompletedProcess(argv, 0, "broker-secret\n", "")

    monkeypatch.setattr(subprocess, "run", run)
    command = cli.GcloudCommandRunner()
    assert command.read_broker_secret() == "broker-secret"
    call = calls[0]
    assert call["argv"] == [
        str(cli.GCLOUD_COMMAND),
        "secrets",
        "versions",
        "access",
        "latest",
        "--secret=zeler-app-broker-secret",
        "--project=zeler-platform-dev",
    ]
    assert call["shell"] is False
    assert call["input"] == ""
    assert call["env"] == cli.GCLOUD_ENV
    assert "broker-secret" not in call["argv"]
    assert "broker-secret" not in call["env"]


def test_gcloud_adapter_uses_absolute_binary_and_minimal_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append({"argv": argv, **kwargs})
        return subprocess.CompletedProcess(
            argv,
            0,
            f"projects/test-project/secrets/{cli.SMOKE_SECRET_NAME}/versions/42\n",
            "",
        )

    monkeypatch.setattr(subprocess, "run", run)
    result = cli.GcloudCommandRunner().run(
        [
            "gcloud",
            "secrets",
            "versions",
            "add",
            cli.SMOKE_SECRET_NAME,
            "--data-file=-",
            "--format=value(name)",
        ],
        stdin="one-time-token",
        env={},
        timeout=1,
        shell=False,
    )

    assert calls[0]["argv"][0] == str(cli.GCLOUD_COMMAND)
    assert calls[0]["env"] == cli.GCLOUD_ENV
    assert result == (
        0,
        f"projects/test-project/secrets/{cli.SMOKE_SECRET_NAME}/versions/42\n",
        "",
    )


@pytest.mark.parametrize("operation", ["create", "delete"])
def test_gcloud_command_rejects_unapproved_operations_before_subprocess(
    monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    called = False

    def run(*_args: Any, **_kwargs: Any) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(cli.AdapterError):
        cli.GcloudCommandRunner().run(
            ["gcloud", "secrets", operation, "zeler-app-broker-secret"],
            stdin="",
            env={},
            timeout=1,
            shell=False,
        )
    assert called is False


@pytest.mark.parametrize("operation", ["access", "disable"])
def test_gcloud_command_rejects_extra_flags_for_access_and_disable_before_subprocess(
    monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    called = False

    def run(*_args: Any, **_kwargs: Any) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(cli.AdapterError):
        cli.GcloudCommandRunner().run(
            [
                "gcloud",
                "secrets",
                "versions",
                operation,
                "42",
                f"--secret={cli.SMOKE_SECRET_NAME}",
                "--quiet",
            ],
            stdin="",
            env={},
            timeout=1,
            shell=False,
        )
    assert called is False


def test_http_rejects_arbitrary_revoke_path_before_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def open_url(_request: Any, *, timeout: float) -> _Response:
        nonlocal called
        called = True
        return _Response(200, b"{}")

    monkeypatch.setattr(cli, "urlopen", open_url)
    with pytest.raises(cli.AdapterError):
        cli.FixedHttpTransport("broker-secret").post(
            "/arbitrary-resource/anything:revoke",
            "{}",
            {"Authorization": "Bearer extension-token"},
        )
    assert called is False


class _TimedOutProcess:
    pid = 4242

    def communicate(self, timeout: float) -> tuple[str, str]:
        raise subprocess.TimeoutExpired([str(cli.SMOKE_COMMAND)], timeout)


def _run_timed_out_process(
    monkeypatch: pytest.MonkeyPatch,
    alive_results: list[bool],
) -> tuple[cli.LocalProcessRunner, list[str]]:
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: _TimedOutProcess())
    monkeypatch.setattr(cli, "PROCESS_TERM_GRACE_SECONDS", 0.0)
    monkeypatch.setattr(cli, "PROCESS_KILL_GRACE_SECONDS", 0.0)
    process = cli.LocalProcessRunner()
    calls: list[str] = []
    monkeypatch.setattr(process, "terminate_tree", lambda pid: calls.append("term"))
    monkeypatch.setattr(process, "kill_tree", lambda pid: calls.append("kill"))
    results = iter(alive_results)
    monkeypatch.setattr(process, "tree_alive", lambda pid: next(results))
    return process, calls


def test_process_timeout_confirms_term_termination_before_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process, calls = _run_timed_out_process(monkeypatch, [False])

    with pytest.raises(TimeoutError, match="smoke timed out"):
        process.run_smoke([str(cli.SMOKE_COMMAND)], env={}, timeout=1, shell=False)

    assert calls == ["term"]


def test_process_timeout_escalates_to_kill_and_confirms_termination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process, calls = _run_timed_out_process(monkeypatch, [True, False])

    with pytest.raises(TimeoutError, match="smoke timed out"):
        process.run_smoke([str(cli.SMOKE_COMMAND)], env={}, timeout=1, shell=False)

    assert calls == ["term", "kill"]


def test_process_timeout_fails_closed_when_survivor_cannot_be_confirmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process, calls = _run_timed_out_process(monkeypatch, [True, True])

    with pytest.raises(cli.AdapterError, match="survived TERM and KILL"):
        process.run_smoke([str(cli.SMOKE_COMMAND)], env={}, timeout=1, shell=False)

    assert calls == ["term", "kill"]


def test_process_adapter_uses_new_session_and_static_process_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeProcess:
        pid = 4242

        def communicate(self, timeout: float) -> tuple[str, str]:
            assert timeout == 3
            return "out", "err"

        returncode = 0

    captured: dict[str, Any] = {}

    def popen(argv: list[str], **kwargs: Any) -> FakeProcess:
        captured["argv"] = argv
        captured.update(kwargs)
        return FakeProcess()

    monkeypatch.setattr(subprocess, "Popen", popen)
    process = cli.LocalProcessRunner()
    result = process.run_smoke(
        [str(cli.SMOKE_COMMAND)], env={"PATH": "/bin"}, timeout=3, shell=False
    )
    assert result == (0, "out", "err")
    assert captured["start_new_session"] is True
    assert captured["shell"] is False
    assert captured["env"] == {"PATH": "/bin"}


def test_bundle_launcher_is_fixed_and_does_not_contain_secret_values() -> None:
    launcher = (
        Path(__file__).parents[2]
        / "infra/gce/operations/zelerdata_smoke_bundle/launch_authenticated_smoke"
    )
    content = launcher.read_text(encoding="utf-8")
    assert "/opt/zeler-platform/zelerdata-smoke/.venv/bin/python" in content
    assert "/opt/zeler-platform/zelerdata-smoke/.venv/bin/python" in content
    assert "/opt/zeler-platform/zelerdata-smoke/authenticated_smoke.py" in content
    assert "zeler-app-broker-secret" not in content
    assert "ZELER_APP_BROKER_SECRET" not in content


def test_bundle_uses_repository_package_layout_for_runner_and_cli() -> None:
    root = Path(__file__).parents[2]
    cli_source = (root / "infra/gce/operations/zelerdata_smoke_cli.py").read_text(encoding="utf-8")
    readme = (root / "infra/gce/operations/zelerdata_smoke_bundle/README.md").read_text(
        encoding="utf-8"
    )
    launcher = (
        root / "infra/gce/operations/zelerdata_smoke_bundle/launch_authenticated_smoke"
    ).read_text(encoding="utf-8")

    assert "from infra.gce.operations import zelerdata_smoke_runner" in cli_source
    assert "/opt/zeler-platform/infra/gce/operations/zelerdata_smoke_cli.py" in readme
    assert "-m infra.gce.operations.zelerdata_smoke_cli" in readme
    assert "/opt/zeler-platform/zelerdata-smoke/authenticated_smoke.py" in launcher
