from __future__ import annotations

import hashlib
import os
import stat
from types import SimpleNamespace

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
