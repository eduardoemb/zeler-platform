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
from zeler_gateway.routes.health import GATEWAY_REQUIRED_REGISTRY_IDS, REPRICER_SWEEP_JOB_ID


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


class FakeRegistryCollection:
    def __init__(self, documents: dict[str, dict[str, Any]]) -> None:
        self._documents = documents

    async def find_one(self, filter_doc: dict[str, Any]) -> dict[str, Any] | None:
        document = self._documents.get(str(filter_doc["_id"]))
        return dict(document) if document is not None else None


class FakeMongoDb:
    def __init__(self, documents: dict[str, dict[str, Any]]) -> None:
        self._registry = FakeRegistryCollection(documents)

    def __getitem__(self, name: str) -> FakeRegistryCollection:
        assert name == "module_registry"
        return self._registry


class FakeRabbitConnection:
    def __init__(self, *, is_open: bool = True) -> None:
        self.is_open = is_open


class FakeScheduler:
    def __init__(self, *, running: bool = True, has_sweep_job: bool = True) -> None:
        self._running = running
        self._has_sweep_job = has_sweep_job

    @property
    def running(self) -> bool:
        return self._running

    def get_job(self, job_id: str) -> object | None:
        if job_id == REPRICER_SWEEP_JOB_ID and self._has_sweep_job:
            return object()
        return None


def _registry_documents() -> dict[str, dict[str, Any]]:
    return {
        module_id: {"_id": module_id, "status": "enabled"}
        for module_id in GATEWAY_REQUIRED_REGISTRY_IDS
    }


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
    app_module.app.state.mongo_db = FakeMongoDb(_registry_documents())
    app_module.app.state.rabbit = FakeRabbitConnection(is_open=True)
    app_module.app.state.scheduler = FakeScheduler(running=True, has_sweep_job=True)


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
    assert response.json() == {
        "status": "ready",
        "checks": {"mongo": "ok", "registry": "ok"},
        "broker_dependencies": {"rabbitmq": "ok", "repricer_sweep_scheduler": "ok"},
    }


@pytest.mark.asyncio
async def test_ready_returns_503_when_mongo_fails() -> None:
    app_module.app.state.mongo_client = FakeMongoClient(_failing_command)

    async with await _readiness_client() as client:
        response = await client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"mongo": "fail", "registry": "ok"},
        "broker_dependencies": {"rabbitmq": "ok", "repricer_sweep_scheduler": "ok"},
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
        "checks": {"mongo": "ok", "registry": "ok"},
        "broker_dependencies": {"rabbitmq": "fail", "repricer_sweep_scheduler": "ok"},
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
        "checks": {"mongo": "fail", "registry": "ok"},
        "broker_dependencies": {"rabbitmq": "fail", "repricer_sweep_scheduler": "ok"},
    }


@pytest.mark.asyncio
async def test_ready_returns_503_when_registry_entry_is_missing() -> None:
    documents = _registry_documents()
    del documents["sheets"]
    app_module.app.state.mongo_db = FakeMongoDb(documents)

    async with await _readiness_client() as client:
        response = await client.get("/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["registry"] == "fail"


@pytest.mark.asyncio
async def test_ready_returns_503_when_registry_entry_is_disabled() -> None:
    documents = _registry_documents()
    documents["autoreply"] = {"_id": "autoreply", "status": "disabled"}
    app_module.app.state.mongo_db = FakeMongoDb(documents)

    async with await _readiness_client() as client:
        response = await client.get("/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["registry"] == "fail"


@pytest.mark.asyncio
async def test_ready_returns_503_when_scheduler_is_stopped() -> None:
    app_module.app.state.scheduler = FakeScheduler(running=False, has_sweep_job=True)

    async with await _readiness_client() as client:
        response = await client.get("/ready")

    assert response.status_code == 503
    assert response.json()["broker_dependencies"]["repricer_sweep_scheduler"] == "fail"


@pytest.mark.asyncio
async def test_ready_returns_503_when_sweep_job_is_not_scheduled() -> None:
    app_module.app.state.scheduler = FakeScheduler(running=True, has_sweep_job=False)

    async with await _readiness_client() as client:
        response = await client.get("/ready")

    assert response.status_code == 503
    assert response.json()["broker_dependencies"]["repricer_sweep_scheduler"] == "fail"


@pytest.mark.asyncio
async def test_ready_returns_503_when_scheduler_is_unavailable() -> None:
    app_module.app.state.scheduler = None

    async with await _readiness_client() as client:
        response = await client.get("/ready")

    assert response.status_code == 503
    assert response.json()["broker_dependencies"]["repricer_sweep_scheduler"] == "fail"


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
        "checks": {"mongo": "fail", "registry": "ok"},
        "broker_dependencies": {"rabbitmq": "ok", "repricer_sweep_scheduler": "ok"},
    }


@pytest.mark.asyncio
async def test_ready_returns_starting_before_lifespan_is_ready() -> None:
    app_module.app.state.ready = False

    async with await _readiness_client() as client:
        response = await client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"mongo": "starting", "registry": "starting"},
        "broker_dependencies": {
            "rabbitmq": "starting",
            "repricer_sweep_scheduler": "starting",
        },
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
    assert set(body.keys()) == {"status", "checks", "broker_dependencies"}
    assert body == {
        "status": "not_ready",
        "checks": {"mongo": "fail", "registry": "ok"},
        "broker_dependencies": {"rabbitmq": "fail", "repricer_sweep_scheduler": "ok"},
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
    assert response.json() == {
        "status": "ready",
        "checks": {"mongo": "ok", "registry": "ok"},
        "broker_dependencies": {"rabbitmq": "ok", "repricer_sweep_scheduler": "ok"},
    }
    assert calls == 1
    assert app_module.app.state.rabbit is new_rabbit
