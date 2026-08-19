from __future__ import annotations

import hashlib
import os
import stat
from types import SimpleNamespace
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
