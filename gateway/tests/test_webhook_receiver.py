from __future__ import annotations

import hmac
import json
import logging
from collections.abc import Callable, Generator
from datetime import UTC, datetime
from hashlib import sha256
from time import monotonic
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from zeler_gateway.app import app
from zeler_gateway.config import Settings
from zeler_gateway.webhooks.router import verify_hmac_signature

HMAC_TEST_KEY = "abc"
HMAC_TEST_VALUE = "x"


class FakeUpdateResult:
    def __init__(self, *, upserted_id: str | None, matched_count: int) -> None:
        self.upserted_id = upserted_id
        self.matched_count = matched_count
        self.modified_count = 0


class FakeWebhookEvents:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}

    async def update_one(
        self, filter_spec: dict[str, Any], update_spec: dict[str, Any], *, upsert: bool
    ) -> FakeUpdateResult:
        assert upsert is True
        event_id = filter_spec["_id"]
        if event_id in self.documents:
            return FakeUpdateResult(upserted_id=None, matched_count=1)
        self.documents[event_id] = update_spec["$setOnInsert"]
        return FakeUpdateResult(upserted_id=event_id, matched_count=0)

    async def find_one(self, filter_spec: dict[str, Any]) -> dict[str, Any] | None:
        return self.documents.get(filter_spec["_id"])


class FakeDatabase:
    def __init__(self) -> None:
        self.webhook_events = FakeWebhookEvents()

    def __getitem__(self, collection_name: str) -> FakeWebhookEvents:
        assert collection_name == "webhook_events"
        return self.webhook_events


class RecordingPublisher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], dict[str, str]]] = []

    async def publish(
        self, routing_key: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> None:
        self.calls.append((routing_key, payload, headers))


def build_hmac_signature(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, sha256).hexdigest()


@pytest.fixture
def webhook_test_app(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[tuple[FakeDatabase, RecordingPublisher]]:
    db = FakeDatabase()
    publisher = RecordingPublisher()
    app.state.mongo_db = db
    app.state.webhook_publisher = publisher
    monkeypatch.setenv("MELI_ALLOWED_IPS", "10.0.0.0/24,200.1.2.3")
    yield db, publisher
    if hasattr(app.state, "webhook_publisher"):
        del app.state.webhook_publisher


@pytest.fixture
def webhook_hmac_app(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[Callable[[bool, str], tuple[FakeDatabase, RecordingPublisher]]]:
    def configure(
        require_signature: bool, hmac_secret: str
    ) -> tuple[FakeDatabase, RecordingPublisher]:
        db = FakeDatabase()
        publisher = RecordingPublisher()
        app.state.mongo_db = db
        app.state.webhook_publisher = publisher
        monkeypatch.setenv("MELI_ALLOWED_IPS", "10.0.0.0/24,200.1.2.3")
        monkeypatch.setenv("MELI_WEBHOOK_REQUIRE_SIGNATURE", str(require_signature).lower())
        monkeypatch.setenv("MELI_WEBHOOK_HMAC_SECRET", hmac_secret)
        return db, publisher

    yield configure
    if hasattr(app.state, "webhook_publisher"):
        del app.state.webhook_publisher


def _webhook_body(notification_id: str) -> bytes:
    return json.dumps(
        {
            "_id": notification_id,
            "topic": "items",
            "resource": "/items/MLA123",
            "user_id": 123456789,
        },
        separators=(",", ":"),
    ).encode("utf-8")


async def _post_webhook(body: bytes, headers: dict[str, str] | None = None) -> httpx.Response:
    request_headers = {"X-Forwarded-For": "10.0.0.5", "Content-Type": "application/json"}
    if headers is not None:
        request_headers.update(headers)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway.test") as client:
        return await client.post("/webhooks/meli", content=body, headers=request_headers)


def _settings_for_hmac_policy(*, require_signature: bool, hmac_value: str) -> Settings:
    return Settings(
        MELI_WEBHOOK_REQUIRE_SIGNATURE=require_signature,
        MELI_WEBHOOK_HMAC_SECRET=SecretStr(hmac_value),
    )


def _assert_single_log(caplog: pytest.LogCaptureFixture, *, level: int, message: str) -> None:
    matching_records = [record for record in caplog.records if message in record.getMessage()]
    assert len(matching_records) == 1
    assert matching_records[0].levelno == level


def test_verify_hmac_valid_signature() -> None:
    body = b'{"_id":"notif-valid"}'

    assert (
        verify_hmac_signature(body, build_hmac_signature(body, HMAC_TEST_KEY), HMAC_TEST_KEY)
        is True
    )


def test_verify_hmac_wrong_signature() -> None:
    body = b'{"_id":"notif-wrong"}'

    assert verify_hmac_signature(body, "sha256=bad", HMAC_TEST_KEY) is False


def test_verify_hmac_missing_signature() -> None:
    body = b'{"_id":"notif-missing"}'

    assert verify_hmac_signature(body, None, HMAC_TEST_KEY) is False


@pytest.mark.asyncio
async def test_hmac_require_false_secret_empty_accepts(
    webhook_hmac_app: Callable[[bool, str], tuple[FakeDatabase, RecordingPublisher]],
) -> None:
    _, publisher = webhook_hmac_app(False, "")

    response = await _post_webhook(_webhook_body("notif-hmac-skip-empty"))

    assert response.status_code == 200
    assert response.json() == {"status": "accepted", "duplicate": False}
    assert publisher.calls[0][0] == "items.updated"


@pytest.mark.asyncio
async def test_hmac_require_false_secret_empty_with_signature_accepts(
    webhook_hmac_app: Callable[[bool, str], tuple[FakeDatabase, RecordingPublisher]],
) -> None:
    _, publisher = webhook_hmac_app(False, "")

    response = await _post_webhook(
        _webhook_body("notif-hmac-skip-empty-with-signature"),
        {"X-Meli-Signature": "sha256=ignored"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "accepted", "duplicate": False}
    assert publisher.calls[0][0] == "items.updated"


@pytest.mark.asyncio
async def test_hmac_require_false_secret_set_accepts(
    webhook_hmac_app: Callable[[bool, str], tuple[FakeDatabase, RecordingPublisher]],
) -> None:
    _, publisher = webhook_hmac_app(False, HMAC_TEST_KEY)

    response = await _post_webhook(
        _webhook_body("notif-hmac-skip-set"), {"X-Meli-Signature": "sha256=ignored"}
    )

    assert response.status_code == 200
    assert response.json() == {"status": "accepted", "duplicate": False}
    assert publisher.calls[0][0] == "items.updated"


@pytest.mark.asyncio
async def test_hmac_require_false_secret_set_missing_header_accepts(
    webhook_hmac_app: Callable[[bool, str], tuple[FakeDatabase, RecordingPublisher]],
) -> None:
    _, publisher = webhook_hmac_app(False, HMAC_TEST_KEY)

    response = await _post_webhook(_webhook_body("notif-hmac-skip-set-missing-header"))

    assert response.status_code == 200
    assert response.json() == {"status": "accepted", "duplicate": False}
    assert publisher.calls[0][0] == "items.updated"


@pytest.mark.asyncio
async def test_hmac_require_true_secret_empty_returns_503(
    webhook_hmac_app: Callable[[bool, str], tuple[FakeDatabase, RecordingPublisher]],
) -> None:
    db, publisher = webhook_hmac_app(True, "")

    response = await _post_webhook(_webhook_body("notif-hmac-missing-secret"))

    assert response.status_code == 503
    assert response.json() == {"detail": "HMAC validation required but secret not configured"}
    assert db.webhook_events.documents == {}
    assert publisher.calls == []


@pytest.mark.asyncio
async def test_hmac_require_true_secret_set_missing_header_returns_401(
    webhook_hmac_app: Callable[[bool, str], tuple[FakeDatabase, RecordingPublisher]],
) -> None:
    db, publisher = webhook_hmac_app(True, HMAC_TEST_KEY)

    response = await _post_webhook(_webhook_body("notif-hmac-missing-header"))

    assert response.status_code == 401
    assert response.json() == {"detail": "invalid webhook signature"}
    assert db.webhook_events.documents == {}
    assert publisher.calls == []


@pytest.mark.asyncio
async def test_hmac_require_true_secret_set_wrong_header_returns_401(
    webhook_hmac_app: Callable[[bool, str], tuple[FakeDatabase, RecordingPublisher]],
) -> None:
    db, publisher = webhook_hmac_app(True, HMAC_TEST_KEY)

    response = await _post_webhook(
        _webhook_body("notif-hmac-wrong-header"), {"X-Meli-Signature": "sha256=bad"}
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "invalid webhook signature"}
    assert db.webhook_events.documents == {}
    assert publisher.calls == []


@pytest.mark.asyncio
async def test_hmac_require_true_secret_set_valid_header_returns_200(
    webhook_hmac_app: Callable[[bool, str], tuple[FakeDatabase, RecordingPublisher]],
) -> None:
    _, publisher = webhook_hmac_app(True, HMAC_TEST_KEY)
    body = _webhook_body("notif-hmac-valid-header")

    response = await _post_webhook(
        body, {"X-Meli-Signature": build_hmac_signature(body, HMAC_TEST_KEY)}
    )

    assert response.status_code == 200
    assert response.json() == {"status": "accepted", "duplicate": False}
    assert publisher.calls[0][0] == "items.updated"


def test_startup_warning_secret_set_flag_false(caplog: pytest.LogCaptureFixture) -> None:
    from zeler_gateway.app import _log_hmac_policy

    caplog.set_level("INFO")
    _log_hmac_policy(_settings_for_hmac_policy(require_signature=False, hmac_value=HMAC_TEST_VALUE))

    _assert_single_log(
        caplog,
        level=logging.WARNING,
        message="MELI_WEBHOOK_REQUIRE_SIGNATURE=False",
    )


def test_startup_info_hmac_disabled(caplog: pytest.LogCaptureFixture) -> None:
    from zeler_gateway.app import _log_hmac_policy

    caplog.set_level("INFO")
    _log_hmac_policy(_settings_for_hmac_policy(require_signature=False, hmac_value=""))

    _assert_single_log(caplog, level=logging.INFO, message="HMAC validation disabled")


def test_startup_info_hmac_required(caplog: pytest.LogCaptureFixture) -> None:
    from zeler_gateway.app import _log_hmac_policy

    caplog.set_level("INFO")
    _log_hmac_policy(_settings_for_hmac_policy(require_signature=True, hmac_value=HMAC_TEST_VALUE))

    _assert_single_log(caplog, level=logging.INFO, message="HMAC validation enforced")


def test_startup_error_hmac_required_no_secret(caplog: pytest.LogCaptureFixture) -> None:
    from zeler_gateway.app import _log_hmac_policy

    caplog.set_level("INFO")
    _log_hmac_policy(_settings_for_hmac_policy(require_signature=True, hmac_value=""))

    _assert_single_log(
        caplog,
        level=logging.ERROR,
        message="HMAC validation required but secret not configured",
    )


@pytest.mark.asyncio
async def test_valid_ip_webhook_returns_200_within_500ms(
    webhook_test_app: tuple[FakeDatabase, RecordingPublisher],
) -> None:
    _, publisher = webhook_test_app
    transport = httpx.ASGITransport(app=app)
    payload = {
        "_id": "notif-1",
        "topic": "items",
        "resource": "/items/MLA123",
        "user_id": 123456789,
    }

    async with httpx.AsyncClient(transport=transport, base_url="http://gateway.test") as client:
        started = monotonic()
        response = await client.post(
            "/webhooks/meli", json=payload, headers={"X-Forwarded-For": "10.0.0.5"}
        )
        elapsed_ms = (monotonic() - started) * 1000

    assert response.status_code == 200
    assert response.json() == {"status": "accepted", "duplicate": False}
    assert elapsed_ms < 500
    assert publisher.calls[0][0] == "items.updated"


@pytest.mark.asyncio
async def test_invalid_ip_returns_401(
    webhook_test_app: tuple[FakeDatabase, RecordingPublisher],
) -> None:
    db, publisher = webhook_test_app
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://gateway.test") as client:
        response = await client.post(
            "/webhooks/meli",
            json={
                "_id": "notif-bad",
                "topic": "items",
                "resource": "/items/MLA123",
                "user_id": 123456789,
            },
            headers={"X-Forwarded-For": "203.0.113.10"},
        )

    assert response.status_code == 401
    assert db.webhook_events.documents == {}
    assert publisher.calls == []


@pytest.mark.asyncio
async def test_duplicate_notification_returns_200_no_publish(
    webhook_test_app: tuple[FakeDatabase, RecordingPublisher],
) -> None:
    db, publisher = webhook_test_app
    db.webhook_events.documents["notif-dup"] = {
        "_id": "notif-dup",
        "topic": "items",
        "resource": "/items/MLA123",
        "user_id": 123456789,
        "received_at": datetime.now(UTC),
    }
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://gateway.test") as client:
        response = await client.post(
            "/webhooks/meli",
            json={
                "_id": "notif-dup",
                "topic": "items",
                "resource": "/items/MLA123",
                "user_id": 123456789,
            },
            headers={"X-Forwarded-For": "10.0.0.6"},
        )

    assert response.status_code == 200
    assert response.json() == {"status": "accepted", "duplicate": True}
    assert len(db.webhook_events.documents) == 1
    assert publisher.calls == []


@pytest.mark.asyncio
async def test_payload_persisted_to_webhook_events(
    webhook_test_app: tuple[FakeDatabase, RecordingPublisher],
) -> None:
    db, _ = webhook_test_app
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://gateway.test") as client:
        await client.post(
            "/webhooks/meli",
            json={
                "_id": "notif-persisted",
                "topic": "orders_v2",
                "resource": "/orders/42",
                "user_id": 123456789,
            },
            headers={"X-Forwarded-For": "200.1.2.3"},
        )

    stored = await db.webhook_events.find_one({"_id": "notif-persisted"})
    assert stored is not None
    assert stored["topic"] == "orders_v2"
    assert stored["user_id"] == 123456789
    assert stored["resource"] == "/orders/42"
    assert stored["raw_body"]["_id"] == "notif-persisted"
    assert stored["source_ip"] == "200.1.2.3"
    assert isinstance(stored["received_at"], datetime)
