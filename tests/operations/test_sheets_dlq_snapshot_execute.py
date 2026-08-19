from __future__ import annotations

import asyncio
import hashlib
import hmac
import inspect
import json
import os
import re
import signal
import stat
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from urllib.parse import urlsplit

import pytest
from infra.operations import sheets_dlq_snapshot_execute as execute
from infra.operations.sheets_dlq_snapshot_adapter import (
    QueueInspection,
    SnapshotBroker,
    SnapshotDelivery,
)

_WRAPPER_PATH = Path(__file__).resolve().parents[2] / "infra/gce/sheets-dlq-snapshot-execute.sh"
_WRAPPER_DOCKER_MARKER = "SHEETS_DLQ_SNAPSHOT_EXEC_DOCKER_BIN"
_TOKEN_DIRECTORY = "/var/lib/zeler-platform/sheets-dlq-snapshot"  # noqa: S105


def _sandboxed_wrapper(
    tmp_path: Path, *, docker_exit: int = 0, cleanup_failure: bool = False, term: bool = False
) -> tuple[Path, Path, Path, Path]:
    source = _WRAPPER_PATH.read_text()
    assert source.count(_WRAPPER_DOCKER_MARKER) == 1
    assert f"TOKEN_DIRECTORY={_TOKEN_DIRECTORY}" in source
    assert '[[ "$(/usr/bin/id -u)" == "0" ]] || exit "$EXIT_CONFIG"' in source
    assert '"0:700:directory"' in source
    assert '"0:600:regular file:32"' in source
    token_directory = tmp_path / "root-owned-token-directory"
    token_directory.mkdir(mode=0o700)
    fake_docker = tmp_path / "fake-docker"
    argv_file = tmp_path / "docker-argv.bin"
    environment_file = tmp_path / "docker-environment.bin"
    fake_docker.write_text(
        "#!/usr/bin/python3\n"
        "import os\n"
        "import signal\n"
        "import sys\n"
        "from pathlib import Path\n"
        f"argv_file = Path({str(argv_file)!r})\n"
        f"environment_file = Path({str(environment_file)!r})\n"
        "argv_file.write_bytes(b'\\0'.join(arg.encode() for arg in sys.argv[1:]) + b'\\0')\n"
        "environment_file.write_bytes(b'\\0'.join(\n"
        "    f'{name}={value}'.encode() for name, value in os.environ.items()\n"
        ") + b'\\0')\n"
        "token_file = Path(os.environ['SHEETS_DLQ_SNAPSHOT_EXEC_TOKEN_FILE'])\n"
        f"(environment_file.with_name('docker-environment.bin.calls')).write_text('call\\n')\n"
        "(environment_file.with_name('docker-environment.bin.token-metadata')).write_text(\n"
        "    f'{token_file.stat().st_uid}:{token_file.stat().st_mode & 0o777:o}:regular file:'\n"
        "    f'{token_file.stat().st_size}\\n'\n"
        ")\n"
        + ("token_file.unlink()\ntoken_file.mkdir()\n" if cleanup_failure else "")
        + ("os.kill(os.getppid(), signal.SIGTERM)\n" if term else "")
        + f"raise SystemExit({docker_exit})\n"
    )
    fake_docker.chmod(0o700)
    replacement = f"DOCKER_BIN={fake_docker} # {_WRAPPER_DOCKER_MARKER}"
    sandbox = tmp_path / "sheets-dlq-snapshot-execute.sh"
    sandbox_source = (
        source.replace(
            f"TOKEN_DIRECTORY={_TOKEN_DIRECTORY}", f"TOKEN_DIRECTORY={token_directory}", 1
        )
        .replace(
            '[[ "$(/usr/bin/id -u)" == "0" ]] || exit "$EXIT_CONFIG"', ": # sandbox root check", 1
        )
        .replace('"0:700:directory"', f'"{os.geteuid()}:700:directory"', 1)
        .replace('"0:600:regular file:32"', f'"{os.geteuid()}:600:regular file:32"', 1)
    )
    sandbox_source = sandbox_source.replace(
        f"DOCKER_BIN=/usr/bin/docker # {_WRAPPER_DOCKER_MARKER}", replacement, 1
    )
    assert sandbox_source.count(_WRAPPER_DOCKER_MARKER) == 1
    sandbox.write_text(sandbox_source)
    sandbox.chmod(0o700)
    return sandbox, argv_file, environment_file, token_directory


def _null_fields(path: Path) -> list[str]:
    return [field.decode() for field in path.read_bytes().split(b"\0") if field]


def test_wrapper_rejects_arguments_and_stdin_before_the_compose_boundary(tmp_path: Path) -> None:
    sandbox, argv_file, _environment_file, _token_directory = _sandboxed_wrapper(tmp_path)

    assert subprocess.run([sandbox, "--not-allowed"], check=False).returncode == 2  # noqa: S603
    assert not argv_file.exists()
    assert (
        subprocess.run(  # noqa: S603 - executes only the disposable sandbox wrapper.
            [sandbox], input="operator input\n", text=True, check=False
        ).returncode
        == 2
    )
    assert not argv_file.exists()


def test_wrapper_uses_a_sanitized_environment_and_exact_bare_compose_authority_argv(
    tmp_path: Path,
) -> None:
    sandbox, argv_file, environment_file, token_directory = _sandboxed_wrapper(tmp_path)
    hostile_environment = os.environ | {
        "RABBITMQ_URL": "amqps://secret.example/vhost",
        "SHEETS_DLQ_SNAPSHOT_EXEC_RUN_ID": "operator-run",
        "SHEETS_DLQ_SNAPSHOT_EXEC_TOKEN_FILE": "/operator/token",
        "SHEETS_DLQ_SNAPSHOT_EXEC_DIGEST": "operator-digest",
        "SHEETS_DLQ_SNAPSHOT_EXEC_DOCKER_BIN": "/operator/docker",
        "UNTRUSTED_OPERATOR_VARIABLE": "must-not-reach-compose",
    }

    completed = subprocess.run(  # noqa: S603 - executes only the disposable sandbox wrapper.
        [sandbox],
        env=hostile_environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0
    compose_argv = _null_fields(argv_file)
    assert compose_argv[:15] == [
        "compose",
        "--project-name",
        "zeler-platform",
        "--project-directory",
        "/opt/zeler-platform",
        "--file",
        "/opt/zeler-platform/docker-compose.yml",
        "exec",
        "-T",
        "--user",
        "0:0",
        "--workdir",
        "/app",
        "-e",
        "SHEETS_DLQ_SNAPSHOT_EXEC_RUN_ID",
    ]
    assert compose_argv[15:] == [
        "-e",
        "SHEETS_DLQ_SNAPSHOT_EXEC_DIGEST",
        "-e",
        "SHEETS_DLQ_SNAPSHOT_EXEC_TOKEN_FILE",
        "sheets-worker",
        "/app/.venv/bin/python",
        "-m",
        "infra.operations.sheets_dlq_snapshot_execute",
    ]
    environment = _null_fields(environment_file)
    environment_names = {field.split("=", 1)[0] for field in environment}
    assert environment_names - {"LC_CTYPE"} == {
        "PATH",
        "HOME",
        "DOCKER_HOST",
        "SHEETS_DLQ_SNAPSHOT_EXEC_RUN_ID",
        "SHEETS_DLQ_SNAPSHOT_EXEC_DIGEST",
        "SHEETS_DLQ_SNAPSHOT_EXEC_TOKEN_FILE",
    }
    assert not any(
        forbidden in "\n".join(environment)
        for forbidden in ("RABBITMQ_URL=", "UNTRUSTED_OPERATOR_VARIABLE=", "operator-digest")
    )
    token_path = next(
        field.split("=", 1)[1]
        for field in environment
        if field.startswith("SHEETS_DLQ_SNAPSHOT_EXEC_TOKEN_FILE=")
    )
    assert token_path.startswith(f"{token_directory}/")
    assert not Path(token_path).exists()
    assert environment_file.with_name("docker-environment.bin.calls").read_text() == "call\n"
    assert environment_file.with_name("docker-environment.bin.token-metadata").read_text() == (
        f"{os.geteuid()}:600:regular file:32\n"
    )
    values = dict(field.split("=", 1) for field in environment)
    assert re.fullmatch(r"[0-9a-f]{32}", values["SHEETS_DLQ_SNAPSHOT_EXEC_RUN_ID"])
    assert re.fullmatch(r"[0-9a-f]{64}", values["SHEETS_DLQ_SNAPSHOT_EXEC_DIGEST"])
    assert "TOKEN" not in environment_names
    assert completed.stdout == b""


@pytest.mark.parametrize(
    ("docker_exit", "cleanup_failure", "term", "expected_exit"),
    [(0, True, False, 75), (9, True, False, 9), (0, False, True, 6)],
    ids=["successful-cleanup-failure", "original-failure-wins", "term-cleans-token"],
)
def test_wrapper_cleanup_and_exit_precedence_are_bounded_to_the_sandboxed_docker_seam(
    tmp_path: Path,
    docker_exit: int,
    cleanup_failure: bool,
    term: bool,
    expected_exit: int,
) -> None:
    sandbox, _argv_file, environment_file, _token_directory = _sandboxed_wrapper(
        tmp_path, docker_exit=docker_exit, cleanup_failure=cleanup_failure, term=term
    )

    completed = subprocess.run(  # noqa: S603 - executes only the disposable sandbox wrapper.
        [sandbox], stdin=subprocess.DEVNULL, check=False
    )

    assert completed.returncode == expected_exit
    token_path = next(
        field.split("=", 1)[1]
        for field in _null_fields(environment_file)
        if field.startswith("SHEETS_DLQ_SNAPSHOT_EXEC_TOKEN_FILE=")
    )
    assert not Path(token_path).is_file()


def _root_owned_regular_token(size: int) -> SimpleNamespace:
    return SimpleNamespace(
        st_mode=stat.S_IFREG | 0o600,
        st_uid=0,
        st_size=size,
    )


def test_token_generation_is_fresh_and_uses_cryptographic_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generated = iter((b"a" * 32, b"b" * 32))
    calls: list[int] = []

    def fake_token_bytes(size: int) -> bytes:
        calls.append(size)
        return next(generated)

    monkeypatch.setattr(execute.secrets, "token_bytes", fake_token_bytes)

    assert execute.generate_execution_token() == b"a" * 32
    assert execute.generate_execution_token() == b"b" * 32
    assert calls == [execute.TOKEN_BYTES, execute.TOKEN_BYTES]


def test_token_file_requires_root_owned_regular_owner_only_file_and_safe_open_flags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token_path = tmp_path / "execution.token"
    token = b"t" * 32
    token_path.write_bytes(token)
    token_path.chmod(0o600)
    flags: list[int] = []
    real_open = os.open

    def record_open(path: str, open_flags: int) -> int:
        flags.append(open_flags)
        return real_open(path, open_flags)

    monkeypatch.setattr(execute.os, "open", record_open)
    monkeypatch.setattr(
        execute.os,
        "fstat",
        lambda _fd: _root_owned_regular_token(len(token)),
    )

    assert execute.read_execution_token(str(token_path)) == token
    assert flags == [os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC]


@pytest.mark.parametrize(
    ("token", "metadata"),
    [
        (b"", _root_owned_regular_token(0)),
        (b"t" * 33, _root_owned_regular_token(33)),
        (b"t" * 32, SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_uid=1, st_size=32)),
        (b"t" * 32, SimpleNamespace(st_mode=stat.S_IFREG | 0o640, st_uid=0, st_size=32)),
    ],
    ids=["empty", "wrong-size", "not-root", "group-readable"],
)
def test_token_file_rejects_noncanonical_format_or_insecure_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    token: bytes,
    metadata: SimpleNamespace,
) -> None:
    token_path = tmp_path / "execution.token"
    token_path.write_bytes(token)
    monkeypatch.setattr(execute.os, "fstat", lambda _fd: metadata)

    assert execute.read_execution_token(str(token_path)) is None
    assert capsys.readouterr().out == ""
    assert capsys.readouterr().err == ""


def test_digest_binds_canonical_newline_fields_and_compare_digest_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    token = b"x" * 32
    run_id = "run-123"
    token_path = tmp_path / "execution.token"
    token_path.write_bytes(token)
    monkeypatch.setattr(
        execute.os,
        "fstat",
        lambda _fd: _root_owned_regular_token(len(token)),
    )
    expected = hashlib.sha256(
        f"{run_id}\n{hashlib.sha256(token).hexdigest()}\nzeler.sheets.events.dlq\n24".encode()
    ).hexdigest()
    compared: list[tuple[str, str]] = []
    real_compare = hmac.compare_digest

    def record_compare(actual: str, supplied: str) -> bool:
        compared.append((actual, supplied))
        return bool(real_compare(actual, supplied))

    monkeypatch.setattr(execute.hmac, "compare_digest", record_compare)

    assert execute.execution_digest(run_id, token) == expected
    assert execute.verify_execution_authorization(str(token_path), run_id, expected)
    assert not execute.verify_execution_authorization(str(token_path), run_id, "0" * 64)
    assert compared == [(expected, expected), (expected, "0" * 64)]
    assert capsys.readouterr().out == ""
    assert capsys.readouterr().err == ""


def test_execution_lock_uses_canonical_root_only_file_and_nonblocking_exclusive_flock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[tuple[str, int, int]] = []
    flock_calls: list[tuple[int, int]] = []
    closed: list[int] = []

    def record_open(path: str, flags: int, mode: int) -> int:
        opened.append((path, flags, mode))
        return 17

    monkeypatch.setattr(execute.os, "open", record_open)
    monkeypatch.setattr(execute.os, "fstat", lambda _fd: _root_owned_regular_token(0))
    monkeypatch.setattr(
        execute.fcntl,
        "flock",
        lambda descriptor, operation: flock_calls.append((descriptor, operation)),
    )
    monkeypatch.setattr(execute.os, "close", lambda descriptor: closed.append(descriptor))

    with execute.execution_lock():
        pass

    assert opened == [
        (
            "/var/lib/zeler-platform/sheets-dlq-snapshot/snapshot.lock",
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
        )
    ]
    assert flock_calls == [
        (17, execute.fcntl.LOCK_EX | execute.fcntl.LOCK_NB),
        (17, execute.fcntl.LOCK_UN),
    ]
    assert closed == [17]


def test_execution_lock_releases_and_closes_when_its_body_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flock_calls: list[tuple[int, int]] = []
    closed: list[int] = []
    monkeypatch.setattr(execute.os, "open", lambda *_args: 19)
    monkeypatch.setattr(execute.os, "fstat", lambda _fd: _root_owned_regular_token(0))
    monkeypatch.setattr(
        execute.fcntl,
        "flock",
        lambda descriptor, operation: flock_calls.append((descriptor, operation)),
    )
    monkeypatch.setattr(execute.os, "close", lambda descriptor: closed.append(descriptor))

    with pytest.raises(RuntimeError, match="boom"), execute.execution_lock():
        raise RuntimeError("boom")

    assert flock_calls[-1] == (19, execute.fcntl.LOCK_UN)
    assert closed == [19]


def test_execution_lock_rejects_contention_and_closes_before_broker_interaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed: list[int] = []
    monkeypatch.setattr(execute.os, "open", lambda *_args: 23)
    monkeypatch.setattr(execute.os, "fstat", lambda _fd: _root_owned_regular_token(0))
    monkeypatch.setattr(execute.os, "close", lambda descriptor: closed.append(descriptor))
    monkeypatch.setattr(
        execute.fcntl,
        "flock",
        lambda _descriptor, _operation: (_ for _ in ()).throw(BlockingIOError()),
    )

    with pytest.raises(execute.LockUnavailableError), execute.execution_lock():
        pytest.fail("a contended lock must not enter the execution body")

    assert closed == [23]


def test_execution_lock_rejects_non_root_lock_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(execute.os, "open", lambda *_args: 29)
    monkeypatch.setattr(
        execute.os,
        "fstat",
        lambda _fd: SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_uid=1, st_size=0),
    )
    closed: list[int] = []
    monkeypatch.setattr(execute.os, "close", lambda descriptor: closed.append(descriptor))

    with pytest.raises(execute.LockUnavailableError), execute.execution_lock():
        pytest.fail("an insecure lock file must not enter the execution body")

    assert closed == [29]


@pytest.mark.parametrize("url", ["amqp://broker.example/vhost", "amqps://broker.example/vhost"])
def test_rabbitmq_url_reader_accepts_only_inherited_amqp_bindings(
    monkeypatch: pytest.MonkeyPatch,
    url: str,
) -> None:
    monkeypatch.setenv("RABBITMQ_URL", url)

    assert execute.read_rabbitmq_url() == url
    assert urlsplit(execute.read_rabbitmq_url() or "").netloc == "broker.example"


@pytest.mark.parametrize(
    "value",
    [None, "", "  \t", "http://broker.example", "amqp:///missing-host"],
    ids=["missing", "empty", "whitespace", "insecure-scheme", "missing-netloc"],
)
def test_rabbitmq_url_reader_rejects_missing_blank_or_invalid_config_without_leaking_uri(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    value: str | None,
) -> None:
    if value is None:
        monkeypatch.delenv("RABBITMQ_URL", raising=False)
    else:
        monkeypatch.setenv("RABBITMQ_URL", value)

    assert execute.read_rabbitmq_url() is None
    assert capsys.readouterr().out == ""
    assert capsys.readouterr().err == ""


class _Delivery:
    def __init__(self, tag: int) -> None:
        self.delivery_tag = tag
        self.body = b""


@dataclass(frozen=True)
class _QueueInspection:
    ready: int = 0
    unacked: int = 0
    consumers: int = 0


class _CaptureBroker:
    def __init__(self, deliveries: list[_Delivery | None]) -> None:
        self._deliveries = iter(deliveries)
        self.get_calls: list[str] = []
        self.nack_calls: list[int] = []

    async def inspect_queue(
        self, _queue_name: str, *, timeout: float | None = None
    ) -> QueueInspection | None:
        del timeout
        return None

    async def get_one(self, queue_name: str) -> SnapshotDelivery | None:
        self.get_calls.append(queue_name)
        return next(self._deliveries)

    async def nack_requeue(self, delivery: SnapshotDelivery) -> None:
        self.nack_calls.append(delivery.delivery_tag)

    async def close_channel(self) -> None:
        return None


def test_broker_protocol_exposes_only_the_restricted_requeue_surface() -> None:
    members = {
        name
        for name, value in inspect.getmembers(execute.SnapshotBroker)
        if not name.startswith("_") and callable(value)
    }

    assert members == {"inspect_queue", "get_one", "nack_requeue", "close_channel"}


@pytest.mark.parametrize(
    ("queue_name", "limit"),
    [
        ("other.queue", 1),
        (execute.QUEUE_NAME, 0),
        (execute.QUEUE_NAME, 25),
    ],
)
def test_capture_scope_rejects_noncanonical_queue_and_limits_outside_one_to_twenty_four(
    queue_name: str,
    limit: int,
) -> None:
    with pytest.raises(ValueError):
        execute.validate_capture_scope(queue_name, limit)


def test_capture_uses_fixed_queue_single_pass_and_nacks_each_obtained_delivery_once() -> None:
    broker = _CaptureBroker([_Delivery(1), _Delivery(2), _Delivery(3), None])

    result = asyncio.run(
        execute.capture_once(
            cast(execute.SnapshotBroker, broker),
            classify=lambda delivery: f"classified-{delivery.delivery_tag}",
            limit=2,
        )
    )

    assert broker.get_calls == [execute.QUEUE_NAME, execute.QUEUE_NAME]
    assert broker.nack_calls == [1, 2]
    assert result.classifications == ["classified-1", "classified-2"]
    assert result.unknown_outcomes == 0


def test_capture_stops_after_unknown_nack_without_retry() -> None:
    class UnknownNackBroker(_CaptureBroker):
        async def nack_requeue(self, delivery: SnapshotDelivery) -> None:
            self.nack_calls.append(delivery.delivery_tag)
            raise TimeoutError("unverifiable nack")

    broker = UnknownNackBroker([_Delivery(1), _Delivery(2)])

    result = asyncio.run(
        execute.capture_once(
            cast(execute.SnapshotBroker, broker),
            classify=lambda _delivery: (_ for _ in ()).throw(ValueError("classification failed")),
        )
    )

    assert broker.get_calls == [execute.QUEUE_NAME]
    assert broker.nack_calls == [1]
    assert result.classification_errors == 1
    assert result.unknown_outcomes == 1


class _PreflightBroker(_CaptureBroker):
    def __init__(
        self,
        calls: list[str],
        *,
        consumers: int = 0,
        deliveries: list[_Delivery | None] | None = None,
        close_error: Exception | None = None,
    ) -> None:
        super().__init__(deliveries or [None])
        self.calls = calls
        self.consumers = consumers
        self.close_error = close_error

    async def inspect_queue(
        self, queue_name: str, *, timeout: float | None = None
    ) -> QueueInspection | None:
        del timeout
        self.calls.append(f"inspect:{queue_name}")
        return cast(QueueInspection, _QueueInspection(consumers=self.consumers))

    async def get_one(self, queue_name: str) -> SnapshotDelivery | None:
        self.calls.append(f"get:{queue_name}")
        return await super().get_one(queue_name)

    async def close_channel(self) -> None:
        if self.close_error is not None:
            raise self.close_error
        self.calls.append("close")


class _PreflightRuntime:
    def __init__(self, calls: list[str], *, healthy: bool) -> None:
        self.calls = calls
        self.healthy = healthy

    async def worker_is_healthy(self) -> bool:
        self.calls.append("health")
        return self.healthy


@contextmanager
def _recording_lock(calls: list[str]) -> Iterator[None]:
    calls.append("lock")
    yield


@contextmanager
def _ordered_lock(calls: list[str]) -> Iterator[None]:
    calls.append("lock-enter")
    try:
        yield
    finally:
        calls.append("lock-exit")


def test_preflight_completes_every_gate_before_the_first_get_and_closes_after_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    broker = _PreflightBroker(calls, deliveries=[_Delivery(1), None])

    def authorized(*_args: object) -> None:
        calls.append("auth")

    def rabbitmq_url() -> str:
        calls.append("url")
        return "amqps://broker"

    def broker_factory(url: str) -> SnapshotBroker:
        calls.append(f"broker:{url}")
        return broker

    def runtime_factory() -> _PreflightRuntime:
        calls.append("runtime")
        return _PreflightRuntime(calls, healthy=True)

    def cleanup_ready() -> bool:
        calls.append("cleanup-ready")
        return True

    monkeypatch.setattr(
        execute,
        "validate_execution_authorization",
        authorized,
    )
    monkeypatch.setattr(execute, "execution_lock", lambda: _recording_lock(calls))
    monkeypatch.setattr(execute, "read_rabbitmq_url", rabbitmq_url)

    status = asyncio.run(
        execute.execute_authorized_capture(
            run_id="run-1",
            token_file=execute.CANONICAL_LOCK_PATH,
            digest="digest",
            broker_factory=broker_factory,
            runtime_factory=runtime_factory,
            cleanup_ready=cleanup_ready,
            classify=lambda _delivery: "classified",
        )
    )

    assert status.first_preflight_failure is None
    assert status.capture is not None
    assert calls == [
        "auth",
        "lock",
        "url",
        "broker:amqps://broker",
        "inspect:zeler.sheets.events.dlq",
        "runtime",
        "health",
        "cleanup-ready",
        "get:zeler.sheets.events.dlq",
        "get:zeler.sheets.events.dlq",
        "close",
    ]


def test_preflight_rejects_report_readiness_before_the_first_get_and_reports_the_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    broker = _PreflightBroker(calls, deliveries=[_Delivery(1)])
    monkeypatch.setattr(execute, "validate_execution_authorization", lambda *_args: None)
    monkeypatch.setattr(execute, "execution_lock", lambda: _recording_lock(calls))
    monkeypatch.setattr(execute, "read_rabbitmq_url", lambda: "amqp://broker")

    def report_ready() -> bool:
        calls.append("report-ready")
        return False

    status = asyncio.run(
        execute.execute_authorized_capture(
            run_id="run-1",
            token_file=execute.CANONICAL_LOCK_PATH,
            digest="digest",
            broker_factory=lambda _url: broker,
            runtime_factory=lambda: _PreflightRuntime(calls, healthy=True),
            cleanup_ready=lambda: True,
            report_ready=report_ready,
            classify=lambda _delivery: "classified",
        )
    )

    report = execute.build_sanitized_report(status)
    assert status.first_preflight_failure == "report_readiness"
    assert not any(call.startswith("get:") for call in calls)
    assert report["preflight_errors"] == ["report_not_ready"]
    assert report["reason_codes"] == ["preflight_rejected", "report_not_ready"]


@pytest.mark.parametrize(
    ("failed_gate", "expected_reason"),
    [
        ("queue", "queue_not_ready"),
        ("cleanup_readiness", "cleanup_not_ready"),
    ],
)
def test_preflight_reports_queue_and_cleanup_readiness_as_the_first_safe_failure(
    monkeypatch: pytest.MonkeyPatch,
    failed_gate: str,
    expected_reason: str,
) -> None:
    calls: list[str] = []
    broker = _PreflightBroker(calls, deliveries=[_Delivery(1)])
    monkeypatch.setattr(execute, "validate_execution_authorization", lambda *_args: None)
    monkeypatch.setattr(execute, "execution_lock", lambda: _recording_lock(calls))
    monkeypatch.setattr(execute, "read_rabbitmq_url", lambda: "amqp://broker")
    if failed_gate == "queue":

        async def no_queue(_queue_name: str) -> None:
            calls.append("inspect:missing")

        monkeypatch.setattr(broker, "inspect_queue", no_queue)

    status = asyncio.run(
        execute.execute_authorized_capture(
            run_id="run-1",
            token_file=execute.CANONICAL_LOCK_PATH,
            digest="digest",
            broker_factory=lambda _url: broker,
            runtime_factory=lambda: _PreflightRuntime(calls, healthy=True),
            cleanup_ready=lambda: failed_gate != "cleanup_readiness",
            classify=lambda _delivery: "classified",
        )
    )

    report = execute.build_sanitized_report(status)
    assert status.first_preflight_failure == failed_gate
    assert not any(call.startswith("get:") for call in calls)
    assert report["preflight_errors"] == [expected_reason]
    assert report["reason_codes"] == ["preflight_rejected", expected_reason]


@pytest.mark.parametrize(
    ("fixture_name", "supplied_digest", "expected_failure"),
    [
        ("missing.token", "digest", "missing_token"),
        ("insecure.token", "digest", "insecure_token"),
        ("digest.token", "0" * 64, "invalid_authorization"),
    ],
)
def test_entry_reports_distinct_token_validation_failure_classes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fixture_name: str,
    supplied_digest: str,
    expected_failure: str,
) -> None:
    path = tmp_path / fixture_name
    if fixture_name != "missing.token":
        path.write_bytes(b"x")
    monkeypatch.setenv("SHEETS_DLQ_SNAPSHOT_EXEC_RUN_ID", "run-1")
    monkeypatch.setenv("SHEETS_DLQ_SNAPSHOT_EXEC_TOKEN_FILE", str(path))
    monkeypatch.setenv("SHEETS_DLQ_SNAPSHOT_EXEC_DIGEST", supplied_digest)
    if fixture_name == "digest.token":
        monkeypatch.setattr(
            execute,
            "validate_execution_token",
            lambda _path: execute.TokenValidation(b"x" * 32, None),
        )

    assert execute.main() == execute.EXIT_PREFLIGHT
    report = json.loads(capsys.readouterr().out)
    assert report["preflight_errors"] == [expected_failure]
    assert report["reason_codes"] == ["preflight_rejected", expected_failure]


@pytest.mark.parametrize(
    ("authorized", "consumers", "healthy", "expected_gate"),
    [
        (False, 0, True, "authorization"),
        (True, 1, True, "consumers"),
        (True, 0, False, "worker_health"),
    ],
)
def test_preflight_records_its_first_failure_and_never_gets_a_delivery(
    monkeypatch: pytest.MonkeyPatch,
    authorized: bool,
    consumers: int,
    healthy: bool,
    expected_gate: str,
) -> None:
    calls: list[str] = []
    broker = _PreflightBroker(calls, consumers=consumers, deliveries=[_Delivery(1)])
    monkeypatch.setattr(
        execute,
        "validate_execution_authorization",
        lambda *_args: None if authorized else "authorization",
    )
    monkeypatch.setattr(execute, "execution_lock", lambda: _recording_lock(calls))
    monkeypatch.setattr(execute, "read_rabbitmq_url", lambda: "amqp://broker")

    status = asyncio.run(
        execute.execute_authorized_capture(
            run_id="run-1",
            token_file=execute.CANONICAL_LOCK_PATH,
            digest="digest",
            broker_factory=lambda _url: broker,
            runtime_factory=lambda: _PreflightRuntime(calls, healthy=healthy),
            cleanup_ready=lambda: True,
            classify=lambda _delivery: "classified",
        )
    )

    assert status.first_preflight_failure == expected_gate
    assert status.capture is None
    assert not any(call.startswith("get:") for call in calls)
    assert calls.count("close") == int(authorized)


def test_entry_fails_closed_without_wrapper_authority_and_does_not_create_adapters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[str] = []
    monkeypatch.delenv("SHEETS_DLQ_SNAPSHOT_EXEC_RUN_ID", raising=False)
    monkeypatch.delenv("SHEETS_DLQ_SNAPSHOT_EXEC_TOKEN_FILE", raising=False)
    monkeypatch.delenv("SHEETS_DLQ_SNAPSHOT_EXEC_DIGEST", raising=False)

    def broker_factory(_url: str) -> SnapshotBroker:
        created.append("broker")
        return _CaptureBroker([])

    def runtime_factory() -> _PreflightRuntime:
        created.append("runtime")
        return _PreflightRuntime([], healthy=True)

    result = execute.main(broker_factory=broker_factory, runtime_factory=runtime_factory)

    assert result == execute.EXIT_PREFLIGHT
    assert created == []


def test_entry_closes_on_capture_failure_without_masking_the_preflight_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    broker = _PreflightBroker(calls, deliveries=[_Delivery(1)])
    monkeypatch.setenv("SHEETS_DLQ_SNAPSHOT_EXEC_RUN_ID", "run-1")
    monkeypatch.setenv("SHEETS_DLQ_SNAPSHOT_EXEC_TOKEN_FILE", "/safe/token")
    monkeypatch.setenv("SHEETS_DLQ_SNAPSHOT_EXEC_DIGEST", "digest")
    monkeypatch.setattr(execute, "validate_execution_authorization", lambda *_args: None)
    monkeypatch.setattr(execute, "execution_lock", lambda: _recording_lock(calls))
    monkeypatch.setattr(execute, "read_rabbitmq_url", lambda: "amqp://broker")

    result = execute.main(
        broker_factory=lambda _url: broker,
        runtime_factory=lambda: _PreflightRuntime(calls, healthy=True),
        cleanup_ready=lambda: True,
        classify=lambda _delivery: (_ for _ in ()).throw(RuntimeError("capture failed")),
    )

    assert result == execute.EXIT_MESSAGE_OR_CANCELLED
    assert calls[-1] == "close"


def test_capture_close_finishes_before_the_execution_lock_releases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    broker = _PreflightBroker(calls, deliveries=[_Delivery(1)])
    monkeypatch.setattr(execute, "validate_execution_authorization", lambda *_args: None)
    monkeypatch.setattr(execute, "execution_lock", lambda: _ordered_lock(calls))
    monkeypatch.setattr(execute, "read_rabbitmq_url", lambda: "amqp://broker")

    status = asyncio.run(
        execute.execute_authorized_capture(
            run_id="run-1",
            token_file=execute.CANONICAL_LOCK_PATH,
            digest="digest",
            broker_factory=lambda _url: broker,
            runtime_factory=lambda: _PreflightRuntime(calls, healthy=True),
            classify=lambda _delivery: (_ for _ in ()).throw(RuntimeError("capture failed")),
        )
    )

    assert status.capture_failed
    assert calls.index("close") < calls.index("lock-exit")


def test_preflight_default_factories_compose_archived_broker_and_worker_health_seams(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    broker = _PreflightBroker(calls, deliveries=[None])
    monkeypatch.setattr(execute, "validate_execution_authorization", lambda *_args: None)
    monkeypatch.setattr(execute, "execution_lock", lambda: _recording_lock(calls))
    monkeypatch.setattr(execute, "read_rabbitmq_url", lambda: "amqps://broker")

    def broker_factory(url: str) -> SnapshotBroker:
        calls.append(f"aio-pika:{url}")
        return broker

    def runtime_factory() -> _PreflightRuntime:
        calls.append("http-health")
        return _PreflightRuntime(calls, healthy=True)

    monkeypatch.setattr(
        execute,
        "AioPikaSnapshotBroker",
        broker_factory,
    )
    monkeypatch.setattr(
        execute,
        "HttpSheetsWorkerRuntime",
        runtime_factory,
    )

    status = asyncio.run(
        execute.execute_authorized_capture(
            run_id="run-1",
            token_file=execute.CANONICAL_LOCK_PATH,
            digest="digest",
            broker_factory=None,
            runtime_factory=None,
            cleanup_ready=lambda: True,
            classify=lambda _delivery: "classified",
        )
    )

    assert status.first_preflight_failure is None
    assert calls == [
        "lock",
        "aio-pika:amqps://broker",
        "inspect:zeler.sheets.events.dlq",
        "http-health",
        "health",
        "get:zeler.sheets.events.dlq",
        "close",
    ]


def test_sanitized_report_has_exact_allowlist_and_never_serializes_sensitive_classifications() -> (
    None
):
    report = execute.build_sanitized_report(
        execute.ExecutionStatus(
            first_preflight_failure=None,
            capture=execute.CapturePass(
                classifications=["captured", "seller-82453304:token=secret"],
                messages_obtained=2,
                classification_errors=1,
                unknown_outcomes=0,
            ),
            capture_failed=False,
            close_failed=False,
        ),
        safe_revision="f603987e",
    )

    assert set(report) == {
        "schema_version",
        "timestamp_utc",
        "safe_revision",
        "requested_limit",
        "messages_obtained",
        "classifications",
        "requeue_requested_count",
        "requeue_failed_count",
        "unknown_outcomes_count",
        "preflight_errors",
        "close_errors",
        "lock_status",
        "cleanup_status",
        "exit_code",
        "reason_codes",
    }
    assert report["classifications"] == {"captured": 1, "other": 1, "classification_error": 1}
    assert report["reason_codes"] == ["completed"]
    serialized = json.dumps(report, sort_keys=True)
    assert "seller-82453304" not in serialized
    assert "secret" not in serialized
    assert "token=" not in serialized


def test_sanitized_report_distinguishes_preflight_before_lock_from_completed_cleanup() -> None:
    report = execute.build_sanitized_report(
        execute.ExecutionStatus("authorization", None, False, False)
    )

    assert report["lock_status"] == "not_attempted"
    assert report["cleanup_status"] == "not_started"
    assert report["preflight_errors"] == ["invalid_authorization"]


@pytest.mark.parametrize(
    ("failure_class", "expected_exit", "expected_reasons"),
    [
        ("completed", 0, ["completed"]),
        ("usage", 2, ["usage"]),
        ("invalid_config", 4, ["invalid_config"]),
        ("invalid_authorization", 5, ["preflight_rejected", "invalid_authorization"]),
        ("missing_token", 5, ["preflight_rejected", "missing_token"]),
        ("insecure_token", 5, ["preflight_rejected", "insecure_token"]),
        ("lock_busy", 5, ["preflight_rejected", "lock_busy"]),
        ("unhealthy_worker", 5, ["preflight_rejected", "unhealthy_worker"]),
        ("incompatible_consumers", 5, ["preflight_rejected", "incompatible_consumers"]),
        ("broker_error", 5, ["preflight_rejected", "broker_error"]),
        ("unknown_outcome", 6, ["message_error_or_cancelled", "unknown_outcome"]),
        ("cleanup_failure", 7, ["close_error", "cleanup_failure"]),
        ("cancellation", 6, ["message_error_or_cancelled", "cancellation"]),
        ("serialization", 8, ["serialization_error"]),
        ("internal", 70, ["sanitized_internal_error"]),
        ("token_cleanup_failed", 75, ["token_cleanup_failed"]),
    ],
)
def test_exit_reason_map_is_deterministic_for_every_contract_failure_class(
    failure_class: str,
    expected_exit: int,
    expected_reasons: list[str],
) -> None:
    resolution = execute.resolve_exit(failure_class)

    assert resolution.exit_code == expected_exit
    assert resolution.reason_codes == expected_reasons


def test_capture_attempts_exactly_one_nack_when_cancellation_arrives_after_obtaining_delivery() -> (
    None
):
    class CancellationBroker(_CaptureBroker):
        async def nack_requeue(self, delivery: SnapshotDelivery) -> None:
            self.nack_calls.append(delivery.delivery_tag)

    broker = CancellationBroker([_Delivery(1)])

    def cancel_current_capture(_delivery: SnapshotDelivery) -> str:
        asyncio.current_task().cancel()  # type: ignore[union-attr]
        return "captured"

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            execute.capture_once(
                cast(execute.SnapshotBroker, broker), classify=cancel_current_capture
            )
        )

    assert broker.nack_calls == [1]


def test_cancellation_signal_handlers_restore_prior_handlers_and_raise_keyboard_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_term = object()
    original_int = object()
    installed: dict[signal.Signals, object] = {}
    monkeypatch.setattr(
        execute.signal,
        "getsignal",
        lambda signum: {signal.SIGTERM: original_term, signal.SIGINT: original_int}[signum],
    )
    monkeypatch.setattr(
        execute.signal,
        "signal",
        lambda signum, handler: installed.__setitem__(signum, handler),
    )

    with execute.cancellation_signal_handlers(), pytest.raises(KeyboardInterrupt):
        installed[signal.SIGTERM](signal.SIGTERM, None)  # type: ignore[operator]

    assert installed[signal.SIGTERM] is original_term
    assert installed[signal.SIGINT] is original_int


def test_main_emits_one_sanitized_json_report_and_returns_its_real_exit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SHEETS_DLQ_SNAPSHOT_EXEC_RUN_ID", "run-1")
    monkeypatch.setenv("SHEETS_DLQ_SNAPSHOT_EXEC_TOKEN_FILE", "/safe/token")
    monkeypatch.setenv("SHEETS_DLQ_SNAPSHOT_EXEC_DIGEST", "digest")

    async def successful_execution(**_kwargs: object) -> execute.ExecutionStatus:
        return execute.ExecutionStatus(None, None, False, False)

    monkeypatch.setattr(execute, "execute_authorized_capture", successful_execution)

    assert execute.main() == execute.EXIT_OK
    reports = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(reports) == 1
    assert reports[0]["exit_code"] == execute.EXIT_OK
    assert reports[0]["reason_codes"] == ["completed"]
