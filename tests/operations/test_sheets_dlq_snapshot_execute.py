from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import signal
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import cast
from urllib.parse import urlsplit

import pytest
from infra.operations import sheets_dlq_snapshot_execute as execute


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
    tmp_path: pytest.TempPathFactory,
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
    tmp_path: pytest.TempPathFactory,
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
    tmp_path: pytest.TempPathFactory,
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
    real_compare = execute.hmac.compare_digest

    def record_compare(actual: str, supplied: str) -> bool:
        compared.append((actual, supplied))
        return real_compare(actual, supplied)

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


class _CaptureBroker:
    def __init__(self, deliveries: list[_Delivery | None]) -> None:
        self._deliveries = iter(deliveries)
        self.get_calls: list[str] = []
        self.nack_calls: list[int] = []

    async def inspect_queue(self, _queue_name: str) -> None:
        return None

    async def get_one(self, queue_name: str) -> _Delivery | None:
        self.get_calls.append(queue_name)
        return next(self._deliveries)

    async def nack_requeue(self, delivery: _Delivery) -> None:
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
        async def nack_requeue(self, delivery: _Delivery) -> None:
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

    async def inspect_queue(self, queue_name: str) -> SimpleNamespace:
        self.calls.append(f"inspect:{queue_name}")
        return SimpleNamespace(consumers=self.consumers)

    async def get_one(self, queue_name: str) -> _Delivery | None:
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
    monkeypatch.setattr(
        execute,
        "verify_execution_authorization",
        lambda *_args: calls.append("auth") or True,
    )
    monkeypatch.setattr(execute, "execution_lock", lambda: _recording_lock(calls))
    monkeypatch.setattr(
        execute, "read_rabbitmq_url", lambda: calls.append("url") or "amqps://broker"
    )

    status = asyncio.run(
        execute.execute_authorized_capture(
            run_id="run-1",
            token_file=execute.CANONICAL_LOCK_PATH,
            digest="digest",
            broker_factory=lambda url: calls.append(f"broker:{url}") or broker,
            runtime_factory=lambda: (
                calls.append("runtime") or _PreflightRuntime(calls, healthy=True)
            ),
            cleanup_ready=lambda: calls.append("cleanup-ready") or True,
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
    monkeypatch.setattr(execute, "verify_execution_authorization", lambda *_args: authorized)
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

    result = execute.main(
        broker_factory=lambda _url: created.append("broker") or _CaptureBroker([]),
        runtime_factory=lambda: created.append("runtime") or _PreflightRuntime([], healthy=True),
    )

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
    monkeypatch.setattr(execute, "verify_execution_authorization", lambda *_args: True)
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
    monkeypatch.setattr(execute, "verify_execution_authorization", lambda *_args: True)
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
    monkeypatch.setattr(execute, "verify_execution_authorization", lambda *_args: True)
    monkeypatch.setattr(execute, "execution_lock", lambda: _recording_lock(calls))
    monkeypatch.setattr(execute, "read_rabbitmq_url", lambda: "amqps://broker")
    monkeypatch.setattr(
        execute,
        "AioPikaSnapshotBroker",
        lambda url: calls.append(f"aio-pika:{url}") or broker,
    )
    monkeypatch.setattr(
        execute,
        "HttpSheetsWorkerRuntime",
        lambda: calls.append("http-health") or _PreflightRuntime(calls, healthy=True),
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
        async def nack_requeue(self, delivery: _Delivery) -> None:
            self.nack_calls.append(delivery.delivery_tag)

    broker = CancellationBroker([_Delivery(1)])

    def cancel_current_capture(_delivery: _Delivery) -> str:
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
