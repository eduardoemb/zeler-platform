from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest

from zeler_publicador.app import build_app

TEST_RABBITMQ_URL = "amqp://guest:guest@broker:5672/"


class FakeRabbitConnection:
    def __init__(self, *, is_open: bool = True) -> None:
        self.is_open = is_open
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeCollection:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}

    async def replace_one(
        self, filter_doc: dict[str, Any], replacement: dict[str, Any], *, upsert: bool
    ) -> None:
        assert upsert is True
        self.documents[str(filter_doc["_id"])] = dict(replacement)

    async def find_one(self, filter_doc: dict[str, Any]) -> dict[str, Any] | None:
        document = self.documents.get(str(filter_doc["_id"]))
        return dict(document) if document is not None else None


class FakeDb:
    def __init__(self) -> None:
        self.module_registry = FakeCollection()

    async def command(self, command: str) -> dict[str, int]:
        assert command == "ping"
        return {"ok": 1}

    def __getitem__(self, name: str) -> FakeCollection:
        assert name == "module_registry"
        return self.module_registry


def _connect_ok() -> Callable[..., Awaitable[FakeRabbitConnection]]:
    async def connect(*_args: Any, **_kwargs: Any) -> FakeRabbitConnection:
        return FakeRabbitConnection(is_open=True)

    return connect


def _connect_unreachable() -> Callable[..., Awaitable[FakeRabbitConnection]]:
    async def connect(*_args: Any, **_kwargs: Any) -> FakeRabbitConnection:
        raise RuntimeError("amqp://guest:guest@secret-broker:5672 leaked")

    return connect


async def _health(app: Any, *, startup: bool = True) -> httpx.Response:
    if startup:
        for handler in app.router.on_startup:
            await handler()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.get("/health")


@pytest.mark.asyncio
async def test_publicador_health_registers_mongo_rabbitmq_and_registry_checks() -> None:
    app = build_app(
        mongo_db=FakeDb(), rabbitmq_url=TEST_RABBITMQ_URL, rabbitmq_connect=_connect_ok()
    )

    response = await _health(app)

    assert response.status_code == 200
    body = response.json()
    assert body["module_id"] == "publicador"
    assert body["ready"] is True
    assert set(body["checks"]) == {"mongo", "rabbitmq", "registry"}


@pytest.mark.asyncio
async def test_publicador_rabbitmq_check_calls_broker_transport() -> None:
    calls = 0
    returned = FakeRabbitConnection(is_open=True)

    async def connect(*_args: Any, **_kwargs: Any) -> FakeRabbitConnection:
        nonlocal calls
        calls += 1
        return returned

    app = build_app(mongo_db=FakeDb(), rabbitmq_url=TEST_RABBITMQ_URL, rabbitmq_connect=connect)

    response = await _health(app)

    assert response.status_code == 200
    assert response.json()["checks"]["rabbitmq"] == {"ok": True, "detail": "rabbitmq_ok"}
    assert calls == 1
    assert returned.closed is True


@pytest.mark.asyncio
async def test_publicador_rabbitmq_check_fails_closed_when_unreachable() -> None:
    app = build_app(
        mongo_db=FakeDb(),
        rabbitmq_url=TEST_RABBITMQ_URL,
        rabbitmq_connect=_connect_unreachable(),
    )

    response = await _health(app)

    assert response.status_code == 503
    assert response.json()["checks"]["rabbitmq"] == {
        "ok": False,
        "detail": "rabbitmq_unreachable",
    }


@pytest.mark.asyncio
async def test_publicador_registry_check_fails_closed_without_startup_registration() -> None:
    app = build_app(
        mongo_db=FakeDb(), rabbitmq_url=TEST_RABBITMQ_URL, rabbitmq_connect=_connect_ok()
    )

    response = await _health(app, startup=False)

    assert response.status_code == 503
    assert response.json()["checks"]["registry"] == {
        "ok": False,
        "detail": "registry_fingerprint_mismatch",
    }
