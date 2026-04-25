from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

import aio_pika
import httpx
import pytest

import zeler_gateway.app as app_module


class FakeMongoAdmin:
    def __init__(self, command: Callable[[str], Awaitable[object]]) -> None:
        self._command = command
        self.call_count = 0

    async def command(self, name: str) -> object:
        self.call_count += 1
        return await self._command(name)


class FakeMongoClient:
    def __init__(self, command: Callable[[str], Awaitable[object]]) -> None:
        self.admin = FakeMongoAdmin(command)


class FakeRabbitConnection:
    def __init__(self, *, is_open: bool = True) -> None:
        self.is_open = is_open


async def _ok_command(name: str) -> object:
    assert name == "ping"
    return {"ok": 1}


async def _failing_command(name: str) -> object:
    assert name == "ping"
    raise RuntimeError("mongodb://secret-host:27017 leaked stack trace")


async def _readiness_client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app_module.app)
    return httpx.AsyncClient(transport=transport, base_url="http://gateway.test")


@pytest.fixture(autouse=True)
def _reset_readiness_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("READY_MONGO_TIMEOUT_S", "0.2")
    monkeypatch.setenv("READY_RABBITMQ_TIMEOUT_S", "0.2")
    monkeypatch.setenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/")
    app_module.app.state.ready = True
    app_module.app.state.mongo_client = FakeMongoClient(_ok_command)
    app_module.app.state.rabbit = FakeRabbitConnection(is_open=True)


@pytest.mark.asyncio
async def test_health_is_alive_and_does_not_probe_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_module.app.state.mongo_client = FakeMongoClient(_ok_command)
    connect_calls = 0

    async def fake_connect_robust(*_args: Any, **_kwargs: Any) -> FakeRabbitConnection:
        nonlocal connect_calls
        connect_calls += 1
        return FakeRabbitConnection(is_open=True)

    monkeypatch.setattr(aio_pika, "connect_robust", fake_connect_robust)

    async with await _readiness_client() as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}
    assert app_module.app.state.mongo_client.admin.call_count == 0
    assert connect_calls == 0


@pytest.mark.asyncio
async def test_ready_returns_200_when_mongo_and_rabbit_are_ok() -> None:
    async with await _readiness_client() as client:
        response = await client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"mongo": "ok", "rabbitmq": "ok"}}


@pytest.mark.asyncio
async def test_ready_returns_503_when_mongo_fails() -> None:
    app_module.app.state.mongo_client = FakeMongoClient(_failing_command)

    async with await _readiness_client() as client:
        response = await client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"mongo": "fail", "rabbitmq": "ok"},
    }


@pytest.mark.asyncio
async def test_ready_returns_503_when_rabbit_reconnect_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing_connect_robust(*_args: Any, **_kwargs: Any) -> FakeRabbitConnection:
        raise RuntimeError("amqp://guest:guest@secret-rabbit:5672 leaked")

    app_module.app.state.rabbit = FakeRabbitConnection(is_open=False)
    monkeypatch.setattr(aio_pika, "connect_robust", failing_connect_robust)

    async with await _readiness_client() as client:
        response = await client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"mongo": "ok", "rabbitmq": "fail"},
    }


@pytest.mark.asyncio
async def test_ready_returns_503_when_both_dependencies_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing_connect_robust(*_args: Any, **_kwargs: Any) -> FakeRabbitConnection:
        raise RuntimeError("rabbit failed")

    app_module.app.state.mongo_client = FakeMongoClient(_failing_command)
    app_module.app.state.rabbit = FakeRabbitConnection(is_open=False)
    monkeypatch.setattr(aio_pika, "connect_robust", failing_connect_robust)

    async with await _readiness_client() as client:
        response = await client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"mongo": "fail", "rabbitmq": "fail"},
    }


@pytest.mark.asyncio
async def test_ready_times_out_slow_mongo_with_bounded_wall_clock() -> None:
    async def slow_command(name: str) -> object:
        assert name == "ping"
        await asyncio.sleep(1.0)
        return {"ok": 1}

    app_module.app.state.mongo_client = FakeMongoClient(slow_command)

    started_at = time.monotonic()
    async with await _readiness_client() as client:
        response = await client.get("/ready")
    elapsed_s = time.monotonic() - started_at

    assert elapsed_s <= 0.4
    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"mongo": "fail", "rabbitmq": "ok"},
    }


@pytest.mark.asyncio
async def test_ready_returns_starting_before_lifespan_is_ready() -> None:
    app_module.app.state.ready = False

    async with await _readiness_client() as client:
        response = await client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"mongo": "starting", "rabbitmq": "starting"},
    }


@pytest.mark.asyncio
async def test_ready_handles_fifty_concurrent_probes_without_pool_exhaustion() -> None:
    async with await _readiness_client() as client:
        responses = await asyncio.gather(*(client.get("/ready") for _ in range(50)))

    assert {response.status_code for response in responses} <= {200, 503}
    assert app_module.app.state.mongo_client.admin.call_count <= 50


@pytest.mark.asyncio
async def test_ready_failure_body_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    async def failing_connect_robust(*_args: Any, **_kwargs: Any) -> FakeRabbitConnection:
        raise RuntimeError("amqp://guest:guest@secret-rabbit:5672 stack trace")

    app_module.app.state.mongo_client = FakeMongoClient(_failing_command)
    app_module.app.state.rabbit = FakeRabbitConnection(is_open=False)
    monkeypatch.setattr(aio_pika, "connect_robust", failing_connect_robust)

    async with await _readiness_client() as client:
        response = await client.get("/ready")

    body = response.json()
    serialized = json.dumps(body)
    assert response.status_code == 503
    assert set(body.keys()) == {"status", "checks"}
    assert body == {
        "status": "not_ready",
        "checks": {"mongo": "fail", "rabbitmq": "fail"},
    }
    assert "mongodb://" not in serialized
    assert "amqp://" not in serialized
    assert "secret-host" not in serialized
    assert "secret-rabbit" not in serialized
    assert "RuntimeError" not in serialized
    assert "stack trace" not in serialized


@pytest.mark.asyncio
async def test_ready_refreshes_closed_rabbit_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    new_rabbit = FakeRabbitConnection(is_open=True)
    calls = 0

    async def fake_connect_robust(*_args: Any, **_kwargs: Any) -> FakeRabbitConnection:
        nonlocal calls
        calls += 1
        return new_rabbit

    app_module.app.state.rabbit = FakeRabbitConnection(is_open=False)
    monkeypatch.setattr(aio_pika, "connect_robust", fake_connect_robust)

    async with await _readiness_client() as client:
        response = await client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"mongo": "ok", "rabbitmq": "ok"}}
    assert calls == 1
    assert app_module.app.state.rabbit is new_rabbit
