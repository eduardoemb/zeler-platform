from __future__ import annotations

import inspect
import runpy
import signal
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from zeler_repricer.consumer import (
    MISSING_MONGO_DB_MESSAGE,
    MISSING_MONGO_URI_MESSAGE,
    MISSING_RABBITMQ_URL_MESSAGE,
    RepricerGatewayClient,
    _RepricerIdempotencyAdapter,
    run,
)


class FakeCoreIdempotencyStore:
    def __init__(self) -> None:
        self.duplicate_keys: list[str] = []
        self.marked: list[tuple[str, str]] = []

    async def is_duplicate(self, key: str) -> bool:
        self.duplicate_keys.append(key)
        return False

    async def mark_processed(self, key: str, *, module_id: str) -> bool:
        self.marked.append((key, module_id))
        return True


@pytest.mark.asyncio
async def test_idempotency_adapter_partials_module_id_for_repricer() -> None:
    core_store = FakeCoreIdempotencyStore()
    adapter = _RepricerIdempotencyAdapter(core_store)

    await adapter.mark_processed("idem-1")

    assert core_store.marked == [("idem-1", "repricer")]


@pytest.mark.asyncio
async def test_idempotency_adapter_delegates_duplicate_check_for_repricer() -> None:
    core_store = FakeCoreIdempotencyStore()
    adapter = _RepricerIdempotencyAdapter(core_store)

    assert await adapter.is_duplicate("idem-2") is False

    assert core_store.duplicate_keys == ["idem-2"]


@pytest.mark.asyncio
async def test_repricer_gateway_client_update_price_sends_correct_httpx_request() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(202, json={"status": "accepted"})

    bearer_value = "token-1"
    client = RepricerGatewayClient(
        base_url="https://gateway.test",
        token=bearer_value,
        transport=httpx.MockTransport(handler),
    )

    status_code, latency_ms = await client.update_price(
        seller_id=123456789,
        item_id="MLA123",
        new_price=Decimal("181.50"),
        idempotency_key="idem-1",
    )

    assert status_code == 202
    assert latency_ms >= 0
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert str(request.url) == "https://gateway.test/items/MLA123/prices"
    assert request.headers["x-seller-id"] == "123456789"
    assert request.headers["idempotency-key"] == "idem-1"
    assert request.read() == b'{"price":"181.50"}'


@pytest.mark.asyncio
async def test_repricer_gateway_client_update_price_propagates_auth_header() -> None:
    auth_headers: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        auth_headers.append(request.headers["authorization"])
        return httpx.Response(200, json={"status": "ok"})

    bearer_value = "module-token"
    client = RepricerGatewayClient(
        base_url="https://gateway.test/",
        token=bearer_value,
        transport=httpx.MockTransport(handler),
    )

    await client.update_price(
        seller_id=1,
        item_id="MLA1",
        new_price=Decimal("10.00"),
        idempotency_key="idem-auth",
    )

    assert auth_headers == ["Bearer module-token"]


@pytest.mark.asyncio
async def test_repricer_gateway_client_raises_on_timeout() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    bearer_value = "token-1"
    client = RepricerGatewayClient(
        base_url="https://gateway.test",
        token=bearer_value,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(RuntimeError, match="gateway request timed out"):
        await client.update_price(
            seller_id=1,
            item_id="MLA1",
            new_price=Decimal("10.00"),
            idempotency_key="idem-timeout",
        )


@pytest.mark.asyncio
async def test_repricer_run_exits_2_with_stderr_when_rabbitmq_url_missing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("RABBITMQ_URL", raising=False)
    monkeypatch.setenv("MONGO_URI", "mongodb://unit-test")
    monkeypatch.setenv("MONGO_DB", "zeler")

    with pytest.raises(SystemExit) as exc_info:
        await run()

    assert exc_info.value.code == 2
    assert capsys.readouterr().err.strip() == MISSING_RABBITMQ_URL_MESSAGE


@pytest.mark.asyncio
async def test_repricer_run_exits_2_with_stderr_when_mongo_uri_missing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("RABBITMQ_URL", "amqp://unit-test")
    monkeypatch.delenv("MONGO_URI", raising=False)
    monkeypatch.setenv("MONGO_DB", "zeler")

    with pytest.raises(SystemExit) as exc_info:
        await run()

    assert exc_info.value.code == 2
    assert capsys.readouterr().err.strip() == MISSING_MONGO_URI_MESSAGE


@pytest.mark.asyncio
async def test_repricer_run_exits_2_with_stderr_when_mongo_db_missing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("RABBITMQ_URL", "amqp://unit-test")
    monkeypatch.setenv("MONGO_URI", "mongodb://unit-test")
    monkeypatch.delenv("MONGO_DB", raising=False)

    with pytest.raises(SystemExit) as exc_info:
        await run()

    assert exc_info.value.code == 2
    assert capsys.readouterr().err.strip() == MISSING_MONGO_DB_MESSAGE


@pytest.mark.asyncio
async def test_repricer_run_happy_path_starts_runner_and_awaits_shutdown_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = await _exercise_run(monkeypatch)

    assert state.runner_started is True
    assert state.event_waited is True


@pytest.mark.asyncio
async def test_repricer_run_calls_runner_close_and_mongo_close_in_finally_after_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = await _exercise_run(monkeypatch)

    assert state.runner_closed is True
    assert state.mongo_closed is True


@pytest.mark.asyncio
async def test_repricer_run_registers_sigterm_handler_that_sets_shutdown_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = await _exercise_run(monkeypatch)

    assert signal.SIGTERM in state.signal_handlers
    assert signal.SIGINT in state.signal_handlers
    assert state.event_set is True


def test_repricer_main_module_imports_cleanly_without_broker_connection() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import zeler_repricer.__main__"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_repricer_main_passes_run_coroutine_to_asyncio_run() -> None:
    with patch("asyncio.run") as asyncio_run:
        runpy.run_module("zeler_repricer", run_name="__main__")

    coroutine = asyncio_run.call_args.args[0]
    assert inspect.iscoroutine(coroutine)
    assert coroutine.cr_code is run.__code__
    coroutine.close()


class _RunState:
    def __init__(self) -> None:
        self.runner_started = False
        self.runner_closed = False
        self.mongo_closed = False
        self.event_waited = False
        self.event_set = False
        self.signal_handlers: dict[signal.Signals, Any] = {}


class _FakeLoop:
    def __init__(self, state: _RunState) -> None:
        self._state = state

    def add_signal_handler(self, sig: signal.Signals, callback: Any) -> None:
        self._state.signal_handlers[sig] = callback


class _FakeShutdownEvent:
    def __init__(self, state: _RunState) -> None:
        self._state = state

    def set(self) -> None:
        self._state.event_set = True

    async def wait(self) -> None:
        self._state.event_waited = True
        self._state.signal_handlers[signal.SIGTERM]()


async def _exercise_run(monkeypatch: pytest.MonkeyPatch) -> _RunState:
    state = _RunState()
    monkeypatch.setenv("RABBITMQ_URL", "amqp://unit-test")
    monkeypatch.setenv("MONGO_URI", "mongodb://unit-test")
    monkeypatch.setenv("MONGO_DB", "zeler")
    monkeypatch.setenv("GATEWAY_BASE_URL", "https://gateway.test/proxy/meli")
    monkeypatch.setenv("GATEWAY_TOKEN", "token")

    class FakeMongoClient:
        def __init__(self, uri: str, **kwargs: Any) -> None:
            self.uri = uri
            self.kwargs = kwargs

        def __getitem__(self, name: str) -> Any:
            return _FakeDatabase(name)

        def close(self) -> None:
            state.mongo_closed = True

    class FakeRunner:
        def __init__(self, **kwargs: Any) -> None:
            assert kwargs["rabbitmq_url"] == "amqp://unit-test"
            assert Path(kwargs["manifest_path"]).name == "manifest.yaml"

        async def start(self) -> None:
            state.runner_started = True

        async def close(self) -> None:
            state.runner_closed = True

    monkeypatch.setattr("zeler_repricer.consumer.AsyncIOMotorClient", FakeMongoClient)
    monkeypatch.setattr("zeler_repricer.consumer.RepricerAmqpConsumerRunner", FakeRunner)
    monkeypatch.setattr(
        "zeler_repricer.consumer.asyncio.get_running_loop", lambda: _FakeLoop(state)
    )
    monkeypatch.setattr("zeler_repricer.consumer.asyncio.Event", lambda: _FakeShutdownEvent(state))

    await run()
    return state


class _FakeDatabase:
    def __init__(self, name: str) -> None:
        self.name = name

    def __getitem__(self, collection_name: str) -> dict[str, str]:
        return {"collection": collection_name}
