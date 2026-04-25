from __future__ import annotations

from typing import Any

import aio_pika
from fastapi.testclient import TestClient

import zeler_gateway.app as app_module


class FakeMotorClient:
    def __init__(self, uri: str, **kwargs: Any) -> None:
        self.uri = uri
        self.kwargs = kwargs
        self.databases: dict[str, object] = {}

    def __getitem__(self, database_name: str) -> object:
        return self.databases.setdefault(database_name, object())

    def close(self) -> None:
        return None


class FakeRabbitConnection:
    def __init__(self) -> None:
        self.is_open = True
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def test_lifespan_stores_rabbit_marks_ready_and_closes_it(monkeypatch: Any) -> None:
    rabbit = FakeRabbitConnection()
    calls: list[dict[str, Any]] = []

    async def fake_connect_robust(url: str, **kwargs: Any) -> FakeRabbitConnection:
        calls.append({"url": url, **kwargs})
        return rabbit

    monkeypatch.setenv("MONGO_URI", "mongodb://localhost:27017/zeler_platform_test")
    monkeypatch.setenv("MONGO_DB", "zeler_platform_test")
    monkeypatch.setenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
    monkeypatch.setattr(app_module, "AsyncIOMotorClient", FakeMotorClient)
    monkeypatch.setattr(aio_pika, "connect_robust", fake_connect_robust)

    with TestClient(app_module.app):
        assert calls == [{"url": "amqp://guest:guest@localhost:5672/", "heartbeat": 60}]
        assert app_module.app.state.rabbit is rabbit
        assert app_module.app.state.ready is True

    assert rabbit.closed is True
