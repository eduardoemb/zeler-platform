"""Pilot seed comes from trusted configured seller scope, not a request label."""

from __future__ import annotations

import copy
import socket
from typing import Any

import pytest
from core.tests.test_history_onboarding_admission import CUTOFF, NOW, SELLER, Plans, legacy

from zeler_gateway.oauth import events


class Bootstrap:
    def __init__(self) -> None:
        self.rows = [
            {
                "_id": f"fixture-failed-{i}",
                "seller_id": SELLER,
                "state": "failed",
                "dispatch_attempts": 3,
                "checkpoints": {"kept": i},
            }
            for i in range(12)
        ] + [
            {
                "_id": "fixture-succeeded",
                "seller_id": SELLER,
                "state": "succeeded",
                "checkpoints": {"kept": 7},
            }
        ]
        self.replacements = 0

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        for row in self.rows:
            if row["seller_id"] != query["seller_id"]:
                continue
            if "state" in query and row["state"] not in query["state"]["$in"]:
                continue
            return copy.deepcopy(row)
        return None

    async def replace_one(self, *args: Any, **kwargs: Any) -> None:
        self.replacements += 1
        raise AssertionError("protected thirteen jobs may not be replaced")


class Publisher:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def publish(self, **kwargs: Any) -> None:
        self.messages.append(kwargs)


class Database:
    def __init__(self) -> None:
        self.bootstrap = Bootstrap()
        self.plans = Plans(legacy())

    def __getitem__(self, name: str) -> Any:
        if name == "bootstrap_jobs":
            return self.bootstrap
        assert name == "sheets_history_backfill_plans"
        return self.plans


@pytest.fixture(autouse=True)
def isolated_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZELERDATA_HISTORY_ON_LINK_ADMISSION_HOLD", "false")
    monkeypatch.setenv("ZELERDATA_HISTORY_ON_LINK_ADMISSION_SELLERS", SELLER)
    monkeypatch.delenv("ZELERDATA_HISTORY_PILOT_GET_BUDGET_SELLERS", raising=False)

    def denied(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("pilot admission fakes forbid sockets")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


@pytest.mark.asyncio
@pytest.mark.parametrize(("scope", "expected"), [(SELLER, True), ("456", False), (None, False)])
async def test_pilot_seed_only_when_trusted_settings_scope_selects_seller(
    monkeypatch: pytest.MonkeyPatch, scope: str | None, expected: bool
) -> None:
    if scope is not None:
        monkeypatch.setenv("ZELERDATA_HISTORY_PILOT_GET_BUDGET_SELLERS", scope)
    calls: list[dict[str, Any]] = []

    async def admission(db: Any, seller: str, **kwargs: Any) -> None:
        calls.append({"seller": seller, **kwargs})

    monkeypatch.setattr(events, "admit_history_onboarding", admission)
    db, publisher = Database(), Publisher()
    before = copy.deepcopy(db.bootstrap.rows)
    await events.emit_accounts_linked(
        SELLER, "fixture-user", mongo_db=db, amqp_publisher=publisher, clock=lambda: NOW
    )
    assert len(calls) == 1 and calls[0].get("pilot_seed", False) is expected
    assert db.bootstrap.rows == before and not publisher.messages


@pytest.mark.asyncio
async def test_admission_hold_never_calls_seed_or_recreates_protected_bootstrap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ZELERDATA_HISTORY_PILOT_GET_BUDGET_SELLERS", SELLER)
    monkeypatch.setenv("ZELERDATA_HISTORY_ON_LINK_ADMISSION_HOLD", "true")

    async def denied(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("hold blocks admission")

    monkeypatch.setattr(events, "admit_history_onboarding", denied)
    db, publisher = Database(), Publisher()
    before = copy.deepcopy(db.bootstrap.rows)
    await events.emit_accounts_linked(
        SELLER, "fixture-user", mongo_db=db, amqp_publisher=publisher, clock=lambda: NOW
    )
    assert db.bootstrap.rows == before and not publisher.messages


@pytest.mark.asyncio
async def test_actual_pilot_seed_preserves_bootstrap_and_cutoff_without_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ZELERDATA_HISTORY_PILOT_GET_BUDGET_SELLERS", SELLER)
    db, publisher = Database(), Publisher()
    before = copy.deepcopy(db.bootstrap.rows)
    await events.emit_accounts_linked(
        SELLER, "fixture-user", mongo_db=db, amqp_publisher=publisher, clock=lambda: NOW
    )
    assert db.bootstrap.rows == before and db.bootstrap.replacements == 0
    assert not publisher.messages
    plan = db.plans.document
    assert plan is not None
    assert plan["cutoff"] == CUTOFF.replace(tzinfo=None) and plan["state"] == "paused"
    assert len(plan["sources"]) == 5 and "full_withdrawals" not in plan["sources"]
    assert not {
        "execution_id",
        "execution_utc_day",
        "execution_until",
        "execution_attempt_limit",
    }.intersection(plan)
