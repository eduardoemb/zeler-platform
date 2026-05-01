from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from zeler_gateway.oauth.events import emit_accounts_linked


class FakeBootstrapJobs:
    def __init__(self) -> None:
        self.docs: dict[str, dict[str, Any]] = {}

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        return next((doc for doc in self.docs.values() if _matches(doc, query)), None)

    async def replace_one(
        self, filter_doc: dict[str, Any], replacement: dict[str, Any], *, upsert: bool
    ) -> None:
        assert upsert is True
        self.docs[str(filter_doc["_id"])] = replacement


class FakeDb:
    def __init__(self) -> None:
        self.bootstrap_jobs = FakeBootstrapJobs()

    def __getitem__(self, name: str) -> FakeBootstrapJobs:
        assert name == "bootstrap_jobs"
        return self.bootstrap_jobs


class FakePublisher:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def publish(self, *, exchange: str, routing_key: str, payload: dict[str, Any]) -> None:
        self.messages.append({"exchange": exchange, "routing_key": routing_key, "payload": payload})


NOW = datetime(2026, 4, 30, 12, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_emit_upserts_bootstrap_job_and_publishes_amqp() -> None:
    db = FakeDb()
    publisher = FakePublisher()

    await emit_accounts_linked("S5", "U5", mongo_db=db, amqp_publisher=publisher, clock=lambda: NOW)

    assert db.bootstrap_jobs.docs["bootstrap-S5-oauth"] == {
        "_id": "bootstrap-S5-oauth",
        "state": "pending",
        "seller_id": "S5",
        "triggered_by": "oauth_callback",
        "dispatch_attempts": 0,
        "created_at": NOW,
        "updated_at": NOW,
    }
    assert publisher.messages == [
        {
            "exchange": "meli.events",
            "routing_key": "accounts.linked",
            "payload": {
                "seller_id": "S5",
                "platform_user_id": "U5",
                "occurred_at": NOW.isoformat(),
                "idempotency_key": "accounts-linked-S5-oauth",
            },
        }
    ]


@pytest.mark.asyncio
async def test_relink_no_force_skips_when_pending_exists() -> None:
    db = FakeDb()
    db.bootstrap_jobs.docs["bootstrap-S6-oauth"] = {
        "_id": "bootstrap-S6-oauth",
        "state": "pending",
        "seller_id": "S6",
    }
    publisher = FakePublisher()

    await emit_accounts_linked("S6", "U6", mongo_db=db, amqp_publisher=publisher, clock=lambda: NOW)

    assert db.bootstrap_jobs.docs["bootstrap-S6-oauth"]["state"] == "pending"
    assert publisher.messages == []


@pytest.mark.asyncio
async def test_relink_with_force_creates_new_job() -> None:
    db = FakeDb()
    db.bootstrap_jobs.docs["bootstrap-S6-oauth"] = {
        "_id": "bootstrap-S6-oauth",
        "state": "succeeded",
        "seller_id": "S6",
        "created_at": NOW - timedelta(days=1),
    }
    publisher = FakePublisher()

    await emit_accounts_linked(
        "S6", "U6", mongo_db=db, amqp_publisher=publisher, force=True, clock=lambda: NOW
    )

    assert db.bootstrap_jobs.docs["bootstrap-S6-oauth"]["state"] == "pending"
    assert db.bootstrap_jobs.docs["bootstrap-S6-oauth"]["triggered_by"] == "oauth_callback_force"
    assert publisher.messages[0]["payload"]["idempotency_key"] == "accounts-linked-S6-force"


def _matches(doc: dict[str, Any], query: dict[str, Any]) -> bool:
    return all(doc.get(key) == value for key, value in query.items())
