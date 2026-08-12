from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import aio_pika
from fastapi.testclient import TestClient

import zeler_gateway.app as app_module
from zeler_gateway.oauth import events as oauth_events
from zeler_gateway.oauth import router as oauth_router
from zeler_gateway.webhooks.publisher import AccountLifecyclePublisherAdapter


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


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: dict[str, Any] = {}
        self.started = False
        self.stopped = False

    def add_job(self, callback: Any, trigger: str, **kwargs: Any) -> None:
        self.jobs[kwargs["id"]] = callback

    def start(self) -> None:
        self.started = True

    def shutdown(self, *, wait: bool) -> None:
        self.stopped = True


class FakeTransport:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def publish_to_exchange(
        self,
        exchange_name: str,
        routing_key: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        self.messages.append(
            {
                "exchange": exchange_name,
                "routing_key": routing_key,
                "payload": payload,
                "headers": headers,
            }
        )


class FakeOAuthStateCollection:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}

    async def find_one_and_delete(self, query: dict[str, Any]) -> dict[str, Any] | None:
        return self.documents.pop(str(query["_id"]), None)


class FakeAccountsCollection:
    def __init__(self) -> None:
        self.documents: dict[tuple[int, str], dict[str, Any]] = {}

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        return self.documents.get((int(query["seller_id"]), str(query["app_id"])))

    async def update_one(
        self, query: dict[str, Any], update: dict[str, Any], *, upsert: bool
    ) -> None:
        assert upsert is True
        key = (int(query["seller_id"]), str(query["app_id"]))
        self.documents[key] = {**update["$setOnInsert"], **update["$set"]}


class FakeBootstrapJobsCollection:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        return next(
            (doc for doc in self.documents.values() if doc["seller_id"] == query["seller_id"]),
            None,
        )

    async def replace_one(
        self, query: dict[str, Any], replacement: dict[str, Any], *, upsert: bool
    ) -> None:
        assert upsert is True
        self.documents[str(query["_id"])] = replacement


class FakeOAuthDatabase:
    def __init__(self) -> None:
        self.oauth_state = FakeOAuthStateCollection()
        self.accounts = FakeAccountsCollection()
        self.bootstrap_jobs = FakeBootstrapJobsCollection()

    def __getitem__(self, collection_name: str) -> Any:
        return {
            "meli_oauth_state": self.oauth_state,
            "meli_accounts": self.accounts,
            "bootstrap_jobs": self.bootstrap_jobs,
        }[collection_name]


class FakeOAuthMotorClient:
    def __init__(self, database: FakeOAuthDatabase) -> None:
        self.database = database

    def __getitem__(self, database_name: str) -> FakeOAuthDatabase:
        assert database_name == "zeler_platform_test"
        return self.database

    def close(self) -> None:
        return None


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz: Any = None) -> datetime:  # type: ignore[override]
        return datetime(2026, 8, 10, 20, 30, tzinfo=UTC)


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


def test_lifespan_reuses_one_transport_and_injects_lifecycle_adapter(monkeypatch: Any) -> None:
    rabbit = FakeRabbitConnection()
    scheduler = FakeScheduler()
    transport = FakeTransport()
    transport_calls: list[dict[str, str]] = []
    repricer_publishers: list[Any] = []
    refresh_publishers: list[Any] = []

    async def fake_connect_robust(url: str, **kwargs: Any) -> FakeRabbitConnection:
        return rabbit

    def fake_transport_factory(*, rabbitmq_url: str, exchange_name: str) -> FakeTransport:
        transport_calls.append({"rabbitmq_url": rabbitmq_url, "exchange_name": exchange_name})
        return transport

    def fake_configure_repricer_sweep_scheduler(*, publisher: Any, **kwargs: Any) -> None:
        repricer_publishers.append(publisher)

    async def fake_refresh_once(db: Any, *, lifecycle_publisher: Any) -> None:
        refresh_publishers.append(lifecycle_publisher)

    monkeypatch.setenv("MONGO_URI", "mongodb://localhost:27017/zeler_platform_test")
    monkeypatch.setenv("MONGO_DB", "zeler_platform_test")
    monkeypatch.setenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
    monkeypatch.setenv("RABBITMQ_EVENTS_EXCHANGE", "meli.events")
    monkeypatch.setattr(app_module, "AsyncIOMotorClient", FakeMotorClient)
    monkeypatch.setattr(app_module, "AsyncIOScheduler", lambda: scheduler)
    monkeypatch.setattr(aio_pika, "connect_robust", fake_connect_robust)
    monkeypatch.setattr(app_module, "AioPikaWebhookPublisher", fake_transport_factory)
    monkeypatch.setattr(
        app_module,
        "configure_repricer_sweep_scheduler",
        fake_configure_repricer_sweep_scheduler,
    )
    monkeypatch.setattr(app_module, "refresh_once", fake_refresh_once)

    with TestClient(app_module.app):
        lifecycle_publisher = app_module.app.state.amqp_publisher
        assert isinstance(lifecycle_publisher, AccountLifecyclePublisherAdapter)
        assert lifecycle_publisher.transport is transport
        assert transport_calls == [
            {
                "rabbitmq_url": "amqp://guest:guest@localhost:5672/",
                "exchange_name": "meli.events",
            }
        ]
        assert repricer_publishers == [transport]
        asyncio.run(scheduler.jobs["meli-token-refresh"]())
        assert refresh_publishers == [lifecycle_publisher]

    assert scheduler.started is True
    assert scheduler.stopped is True


def test_successful_oauth_callback_publishes_through_lifespan_adapter(monkeypatch: Any) -> None:
    rabbit = FakeRabbitConnection()
    scheduler = FakeScheduler()
    transport = FakeTransport()
    database = FakeOAuthDatabase()

    async def fake_connect_robust(url: str, **kwargs: Any) -> FakeRabbitConnection:
        return rabbit

    async def fake_exchange_authorization_code(
        code: str, *, code_verifier: str, settings: Any
    ) -> dict[str, Any]:
        assert code == "valid-code"
        assert code_verifier == "deterministic-verifier"
        return {
            "access_token": "access-value",
            "refresh_token": "refresh-value",
            "user_id": 123,
            "expires_in": 21600,
            "scope": "read write",
        }

    async def fake_fetch_user_metadata(*, access_token: str, seller_id: int) -> dict[str, Any]:
        assert access_token == "access-value"  # noqa: S105 - deterministic test token
        assert seller_id == 123
        return {"nickname": "TEST_SELLER", "site_id": "MLM"}

    database.oauth_state.documents["state-1"] = {
        "_id": "state-1",
        "platform_user_id": "user-1",
        "code_verifier": "deterministic-verifier",
    }
    monkeypatch.setenv("MONGO_URI", "mongodb://localhost:27017/zeler_platform_test")
    monkeypatch.setenv("MONGO_DB", "zeler_platform_test")
    monkeypatch.setenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
    monkeypatch.setenv("RABBITMQ_EVENTS_EXCHANGE", "meli.events")
    monkeypatch.setenv("MELI_CLIENT_ID", "meli-client-id-test")
    monkeypatch.setenv("MELI_CLIENT_SECRET", "meli-client-secret-test")
    monkeypatch.setenv("OAUTH_SUCCESS_URL", "https://app.zeler.test/accounts/linked")
    monkeypatch.setattr(
        app_module,
        "AsyncIOMotorClient",
        lambda *args, **kwargs: FakeOAuthMotorClient(database),
    )
    monkeypatch.setattr(app_module, "AsyncIOScheduler", lambda: scheduler)
    monkeypatch.setattr(aio_pika, "connect_robust", fake_connect_robust)
    monkeypatch.setattr(app_module, "AioPikaWebhookPublisher", lambda **kwargs: transport)
    monkeypatch.setattr(
        oauth_router, "_exchange_authorization_code", fake_exchange_authorization_code
    )
    monkeypatch.setattr(oauth_router, "_fetch_user_metadata", fake_fetch_user_metadata)
    monkeypatch.setattr(
        oauth_router,
        "encrypt_token",
        lambda token, *, account_id: SimpleNamespace(
            ciphertext=f"encrypted:{token}",
            dek_wrapped="wrapped",
            nonce="nonce",
            kms_key_version="key-version-1",
        ),
    )
    monkeypatch.setattr(oauth_events, "datetime", FrozenDateTime)

    with TestClient(app_module.app) as client:
        lifecycle_publisher = app_module.app.state.amqp_publisher
        response = client.get(
            "/oauth/callback",
            params={"code": "valid-code", "state": "state-1"},
            follow_redirects=False,
        )

        assert isinstance(lifecycle_publisher, AccountLifecyclePublisherAdapter)
        assert lifecycle_publisher.transport is transport
        assert response.status_code == 302
        assert response.headers["location"] == "https://app.zeler.test/accounts/linked"
        assert transport.messages == [
            {
                "exchange": "meli.events",
                "routing_key": "accounts.linked",
                "payload": {
                    "seller_id": "123",
                    "platform_user_id": "user-1",
                    "occurred_at": "2026-08-10T20:30:00+00:00",
                    "idempotency_key": "accounts-linked-123-oauth",
                },
                "headers": {"idempotency_key": "accounts-linked-123-oauth"},
            }
        ]
        assert database.bootstrap_jobs.documents["bootstrap-123-oauth"]["state"] == "pending"

    assert rabbit.closed is True
