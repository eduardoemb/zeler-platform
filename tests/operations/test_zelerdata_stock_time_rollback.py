from __future__ import annotations

import ast
import builtins
import hashlib
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import pytest
from infra.operations import zelerdata_stock_time_rollback as rollback

from zeler_sheets._stock_time_forward_engine import _ForwardEngineError

OPERATION_ID = "a" * 64
SENTINELS = (OPERATION_ID, "mongodb://secret-host", "seller-private", "error-private")


class Handle:
    def __init__(self, events: list[str]) -> None:
        self.db = object()
        self.events = events
        self.closed = 0

    def close(self) -> None:
        self.events.append("close")
        self.closed += 1


def _argv(operation_id: str = OPERATION_ID, confirmation: str = OPERATION_ID) -> list[str]:
    return [
        "--operation-id",
        operation_id,
        "--confirm-approved-runtime",
        "--confirm-stock-time-rollback-operation-id",
        confirmation,
    ]


def _receipt(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.count("\n") == 1
    receipt = json.loads(captured.out)
    assert isinstance(receipt, dict)
    return receipt


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--operation-id", OPERATION_ID],
        _argv("A" * 64, "A" * 64),
        _argv(OPERATION_ID, "b" * 64),
        [*_argv(), "--unknown", "mongodb://secret-host"],
    ],
)
def test_invalid_requests_do_not_create_a_runtime_db_or_leak_values(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    created = False

    def create() -> Handle:
        nonlocal created
        created = True
        raise AssertionError("must not create DB")

    monkeypatch.setattr(rollback, "create_runtime_db", create)
    assert rollback.main(argv) == 2
    receipt = _receipt(capsys)
    assert created is False
    assert receipt["preflight"] == "not_run"
    assert receipt["outcome"] == "invalid_request"
    assert receipt["operation_id_digest"] in {
        None,
        rollback._receipt(OPERATION_ID, "not_run", "x")["operation_id_digest"],
    }
    assert all(value not in json.dumps(receipt) for value in SENTINELS)


def test_missing_runtime_config_is_sanitized_without_importing_or_creating_a_client(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    attempted_motor_import = False
    import_original = builtins.__import__

    def guarded_import(name: str, *args: Any, **kwargs: Any) -> Any:
        nonlocal attempted_motor_import
        if name == "motor.motor_asyncio":
            attempted_motor_import = True
        return import_original(name, *args, **kwargs)

    monkeypatch.delenv("MONGO_URI", raising=False)
    monkeypatch.delenv("MONGO_DB", raising=False)
    monkeypatch.setattr(builtins, "__import__", guarded_import)

    assert rollback.main(_argv()) == 1
    assert attempted_motor_import is False
    assert _receipt(capsys) == rollback._receipt(OPERATION_ID, "not_run", "rollback_failed")


def test_create_runtime_db_lazily_constructs_an_utc_aware_motor_client(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[tuple[tuple[str, ...], dict[str, bool]]] = []

    class Client:
        def __init__(self, *args: str, **kwargs: bool) -> None:
            calls.append((args, kwargs))

        def __getitem__(self, name: str) -> str:
            return name

        def close(self) -> None:
            pass

    motor = ModuleType("motor")
    motor_asyncio = ModuleType("motor.motor_asyncio")
    cast(Any, motor_asyncio).AsyncIOMotorClient = Client
    monkeypatch.setitem(sys.modules, "motor", motor)
    monkeypatch.setitem(sys.modules, "motor.motor_asyncio", motor_asyncio)
    monkeypatch.setenv("MONGO_URI", "mongodb://runtime-host")
    monkeypatch.setenv("MONGO_DB", "runtime_db")

    handle = rollback.create_runtime_db()

    assert calls == [(("mongodb://runtime-host",), {"tz_aware": True})]
    assert handle.db == "runtime_db"
    assert capsys.readouterr().out == ""


def test_runtime_setup_failure_is_sanitized(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def create() -> Handle:
        raise RuntimeError("mongodb://secret-host")

    monkeypatch.setattr(rollback, "create_runtime_db", create)
    assert rollback.main(_argv()) == 1
    assert _receipt(capsys) == rollback._receipt(OPERATION_ID, "not_run", "rollback_failed")


@pytest.mark.parametrize(
    ("preflight", "rollback_error", "close_error", "expected", "code"),
    [
        (False, None, None, "preflight_blocked", 3),
        (RuntimeError("error-private"), None, None, "preflight_blocked", 3),
        (True, None, None, "rolled_back", 0),
        (True, _ForwardEngineError("ROLLBACK_BLOCKED"), None, "rollback_blocked", 4),
        (True, RuntimeError("error-private"), None, "rollback_failed", 1),
        (True, None, RuntimeError("error-private"), "rollback_failed", 1),
    ],
)
def test_terminal_outcomes_are_sanitized_and_close_once(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    preflight: object,
    rollback_error: Exception | None,
    close_error: Exception | None,
    expected: str,
    code: int,
) -> None:
    events: list[str] = []
    handle = Handle(events)

    def create() -> Handle:
        events.append("create")
        return handle

    def close() -> None:
        events.append("close")
        handle.closed += 1
        if close_error:
            raise close_error

    async def runtime_preflight(_: object) -> object:
        events.append("preflight")
        if isinstance(preflight, Exception):
            raise preflight
        return SimpleNamespace(ready=preflight)

    async def runtime_rollback(_: object, operation_id: str) -> None:
        events.append("rollback")
        assert operation_id == OPERATION_ID
        if rollback_error:
            raise rollback_error

    handle.close = close  # type: ignore[method-assign]
    monkeypatch.setattr(rollback, "create_runtime_db", create)
    monkeypatch.setattr(rollback, "_preflight_stock_time_runtime", runtime_preflight)
    monkeypatch.setattr(rollback, "_rollback_forward_operation", runtime_rollback)

    assert rollback.main(_argv()) == code
    receipt = _receipt(capsys)
    assert handle.closed == 1
    assert events == ["create", "preflight", *(["rollback"] if preflight is True else []), "close"]
    assert receipt == rollback._receipt(
        OPERATION_ID, "passed" if preflight is True else "blocked", expected
    )
    serialized = json.dumps(receipt)
    assert all(value not in serialized for value in SENTINELS[1:])


def test_receipt_is_compact_sorted_ascii_and_domain_separated() -> None:
    receipt = rollback._receipt(OPERATION_ID, "passed", "rolled_back")
    encoded = json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    assert encoded == rollback._encode_receipt(receipt)
    assert (
        receipt["operation_id_digest"]
        == hashlib.sha256(
            b"zeler.stock_time_rollback.operation_id.v1\0" + OPERATION_ID.encode()
        ).hexdigest()
    )
    assert set(receipt) == {
        "schema_version",
        "operation",
        "operation_id_digest",
        "preflight",
        "outcome",
    }


def test_module_uses_only_the_private_runtime_boundary_and_has_main_guard() -> None:
    source = Path(rollback.__file__).read_text()
    tree = ast.parse(source)
    calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert {"_preflight_stock_time_runtime", "_rollback_forward_operation"} <= calls
    forbidden = {
        "_prepare_forward_operation",
        "_execute_forward_operation",
        "create_runtime_historical_meli_gateways",
        "formula",
        "meli",
    }
    assert not calls & forbidden
    assert all(name not in source.lower() for name in forbidden)
    assert "zelerdata_read_model_reconcile" not in source
    assert 'if __name__ == "__main__":' in source
