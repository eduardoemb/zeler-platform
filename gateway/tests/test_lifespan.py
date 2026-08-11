from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

import zeler_gateway.app as app_module


class FakeMotorClient:
    def __init__(self, uri: str, **kwargs: Any) -> None:
        self.uri = uri
        self.kwargs = kwargs
        self.closed = False
        self.databases: dict[str, object] = {}

    def __getitem__(self, database_name: str) -> object:
        return self.databases.setdefault(database_name, object())

    def close(self) -> None:
        self.closed = True


def test_lifespan_connects_and_disconnects_mongo(monkeypatch: Any) -> None:
    created_clients: list[FakeMotorClient] = []

    def fake_client(uri: str, **kwargs: Any) -> FakeMotorClient:
        client = FakeMotorClient(uri, **kwargs)
        created_clients.append(client)
        return client

    monkeypatch.setenv("MONGO_URI", "mongodb://localhost:27017/zeler_platform_test")
    monkeypatch.setenv("MONGO_DB", "zeler_platform_test")
    monkeypatch.delenv("RABBITMQ_URL", raising=False)
    monkeypatch.setattr(app_module, "AsyncIOMotorClient", fake_client)

    with TestClient(app_module.app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert created_clients[0].uri == "mongodb://localhost:27017/zeler_platform_test"
        assert created_clients[0].kwargs["serverSelectionTimeoutMS"] == 5000
        assert created_clients[0].kwargs["connectTimeoutMS"] == 5000
        assert created_clients[0].kwargs["socketTimeoutMS"] == 30000
        assert app_module.app.state.mongo_client is created_clients[0]
        assert app_module.app.state.mongo_db is created_clients[0]["zeler_platform_test"]
        assert app_module.app.state.amqp_publisher is None

    assert created_clients[0].closed is True
