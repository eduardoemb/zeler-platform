from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from zeler_sheets.app import build_app
from zeler_sheets.sheets_config import SheetsSettings

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
        self.sheets_formula_audit = FakeCollection()

    async def command(self, command: str) -> dict[str, int]:
        assert command == "ping"
        return {"ok": 1}

    def __getitem__(self, name: str) -> FakeCollection:
        assert name in {"module_registry", "sheets_formula_audit"}
        return self.module_registry if name == "module_registry" else self.sheets_formula_audit


def _connect_ok() -> Callable[..., Awaitable[FakeRabbitConnection]]:
    async def connect(*_args: Any, **_kwargs: Any) -> FakeRabbitConnection:
        return FakeRabbitConnection(is_open=True)

    return connect


def _connect_unreachable() -> Callable[..., Awaitable[FakeRabbitConnection]]:
    async def connect(*_args: Any, **_kwargs: Any) -> FakeRabbitConnection:
        raise RuntimeError("amqp://guest:guest@secret-broker:5672 leaked")

    return connect


def _settings(*, threshold: int = 2) -> SheetsSettings:
    return SheetsSettings(
        google_oauth_client_id="unit-test",
        google_oauth_client_secret=SecretStr("unit-test-secret"),  # noqa: S106
        google_oauth_redirect_uri="https://sheets.test/oauth/google/callback",
        kms_project_id="zeler-dev",
        sheets_claims_dlq_threshold=threshold,
    )


def _state_source(ready: int, unacked: int) -> Callable[[], Awaitable[tuple[int, int]]]:
    async def source() -> tuple[int, int]:
        return (ready, unacked)

    return source


async def _unavailable_source() -> None:
    return None


async def _raising_source() -> tuple[int, int]:
    raise RuntimeError("broker unreachable")


async def _health(app: Any) -> httpx.Response:
    for handler in app.router.on_startup:
        await handler()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.get("/health")


async def _health_without_startup(app: Any) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.get("/health")


@pytest.mark.asyncio
async def test_health_without_claims_source_has_no_dlq_budget_check() -> None:
    app = build_app(
        mongo_db=FakeDb(), rabbitmq_url=TEST_RABBITMQ_URL, rabbitmq_connect=_connect_ok()
    )

    response = await _health(app)

    assert response.status_code == 200
    assert "claims_dlq_within_budget" not in response.json()["checks"]


@pytest.mark.asyncio
async def test_claims_dlq_within_budget_ok_below_threshold() -> None:
    app = build_app(
        mongo_db=FakeDb(),
        rabbitmq_url=TEST_RABBITMQ_URL,
        rabbitmq_connect=_connect_ok(),
        settings=_settings(threshold=3),
        claims_dlq_state=_state_source(1, 1),
    )

    response = await _health(app)

    assert response.status_code == 200
    assert response.json()["checks"]["claims_dlq_within_budget"] == {
        "ok": True,
        "detail": "claims_dlq_within_budget:ready=1,unacked=1",
    }


@pytest.mark.asyncio
async def test_claims_dlq_not_ok_when_ready_at_threshold() -> None:
    app = build_app(
        mongo_db=FakeDb(),
        rabbitmq_url=TEST_RABBITMQ_URL,
        rabbitmq_connect=_connect_ok(),
        settings=_settings(threshold=2),
        claims_dlq_state=_state_source(2, 0),
    )

    response = await _health(app)

    assert response.status_code == 503
    assert response.json()["ready"] is False
    assert response.json()["checks"]["claims_dlq_within_budget"] == {
        "ok": False,
        "detail": "claims_dlq_ready_over_budget:ready=2,threshold=2",
    }


@pytest.mark.asyncio
async def test_claims_dlq_not_ok_when_unacked_at_threshold() -> None:
    app = build_app(
        mongo_db=FakeDb(),
        rabbitmq_url=TEST_RABBITMQ_URL,
        rabbitmq_connect=_connect_ok(),
        settings=_settings(threshold=2),
        claims_dlq_state=_state_source(1, 2),
    )

    response = await _health(app)

    assert response.status_code == 503
    assert response.json()["checks"]["claims_dlq_within_budget"] == {
        "ok": False,
        "detail": "claims_dlq_unacked_over_budget:unacked=2,threshold=2",
    }


@pytest.mark.asyncio
async def test_claims_dlq_fails_closed_on_unavailable_queue_state() -> None:
    app = build_app(
        mongo_db=FakeDb(),
        rabbitmq_url=TEST_RABBITMQ_URL,
        rabbitmq_connect=_connect_ok(),
        claims_dlq_state=_unavailable_source,
    )

    response = await _health(app)

    assert response.status_code == 503
    assert response.json()["checks"]["claims_dlq_within_budget"] == {
        "ok": False,
        "detail": "claims_dlq_state_unavailable",
    }


@pytest.mark.asyncio
async def test_claims_dlq_fails_closed_when_state_source_raises() -> None:
    app = build_app(
        mongo_db=FakeDb(),
        rabbitmq_url=TEST_RABBITMQ_URL,
        rabbitmq_connect=_connect_ok(),
        claims_dlq_state=_raising_source,
    )

    response = await _health(app)

    assert response.status_code == 503
    assert response.json()["checks"]["claims_dlq_within_budget"] == {
        "ok": False,
        "detail": "claims_dlq_state_unavailable",
    }


@pytest.mark.asyncio
async def test_claims_dlq_threshold_is_configurable_via_settings() -> None:
    app = build_app(
        mongo_db=FakeDb(),
        rabbitmq_url=TEST_RABBITMQ_URL,
        rabbitmq_connect=_connect_ok(),
        settings=_settings(threshold=1),
        claims_dlq_state=_state_source(1, 0),
    )

    response = await _health(app)

    assert response.status_code == 503
    assert response.json()["checks"]["claims_dlq_within_budget"]["ok"] is False


@pytest.mark.asyncio
async def test_health_registers_mongo_rabbitmq_and_registry_checks() -> None:
    app = build_app(
        mongo_db=FakeDb(), rabbitmq_url=TEST_RABBITMQ_URL, rabbitmq_connect=_connect_ok()
    )

    response = await _health(app)

    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert set(body["checks"].keys()) == {"mongo", "rabbitmq", "registry"}


@pytest.mark.asyncio
async def test_rabbitmq_check_calls_broker_transport() -> None:
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
async def test_rabbitmq_check_fails_when_broker_unreachable() -> None:
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
async def test_rabbitmq_check_fails_closed_without_url() -> None:
    app = build_app(mongo_db=FakeDb())

    response = await _health(app)

    assert response.status_code == 503
    assert response.json()["checks"]["rabbitmq"] == {
        "ok": False,
        "detail": "rabbitmq_url_unconfigured",
    }


@pytest.mark.asyncio
async def test_registry_check_ok_after_startup_registration() -> None:
    app = build_app(
        mongo_db=FakeDb(), rabbitmq_url=TEST_RABBITMQ_URL, rabbitmq_connect=_connect_ok()
    )

    response = await _health(app)

    assert response.status_code == 200
    assert response.json()["checks"]["registry"] == {
        "ok": True,
        "detail": "registry_fingerprint_match",
    }


@pytest.mark.asyncio
async def test_registry_check_fails_closed_when_entry_missing() -> None:
    app = build_app(
        mongo_db=FakeDb(), rabbitmq_url=TEST_RABBITMQ_URL, rabbitmq_connect=_connect_ok()
    )

    response = await _health_without_startup(app)

    assert response.status_code == 503
    assert response.json()["checks"]["registry"] == {
        "ok": False,
        "detail": "registry_fingerprint_mismatch",
    }
