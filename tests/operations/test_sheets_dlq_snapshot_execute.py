from __future__ import annotations

import asyncio
import hashlib
import inspect
import os
import stat
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
