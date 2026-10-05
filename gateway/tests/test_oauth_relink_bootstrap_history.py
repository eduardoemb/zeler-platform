"""Historical terminal jobs must not mask an eligible OAuth bootstrap record."""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from gateway.tests.test_history_admission_controls import BSONHistoryPlans
from gateway.tests.test_oauth_emit_accounts_linked import FakePublisher

from zeler_gateway.oauth import events

SELLER = "82453304"
NOW = datetime(2026, 10, 5, 17, 30, tzinfo=UTC)
CUTOFF = datetime(2026, 9, 24, 5, 36, 28, tzinfo=UTC)
CREATED = NOW - timedelta(days=157)


class BootstrapHistory:
    def __init__(self, rows: list[dict[str, Any]], trace: list[str]) -> None:
        self.docs = {row["_id"]: copy.deepcopy(row) for row in rows}
        self.queries: list[dict[str, Any]] = []
        self.replacements: list[dict[str, Any]] = []
        self.trace = trace

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        self.trace.append("bootstrap_read")
        self.queries.append(copy.deepcopy(query))
        for doc in self.docs.values():
            if all(
                doc.get(key) in value["$in"]
                if isinstance(value, dict) and "$in" in value
                else doc.get(key) == value
                for key, value in query.items()
            ):
                return copy.deepcopy(doc)
        return None

    async def replace_one(
        self, query: dict[str, Any], replacement: dict[str, Any], *, upsert: bool
    ) -> None:
        assert upsert is True
        self.replacements.append(copy.deepcopy(replacement))
        self.docs[query["_id"]] = copy.deepcopy(replacement)


class TracedPlans(BSONHistoryPlans):
    def __init__(self, document: dict[str, Any], trace: list[str]) -> None:
        super().__init__(document)
        self.trace = trace

    async def update_one(
        self, query: dict[str, Any], update: dict[str, Any], *, upsert: bool = False
    ) -> None:
        self.trace.append("history_admission")
        await super().update_one(query, update, upsert=upsert)


class HistoryDb:
    def __init__(self, rows: list[dict[str, Any]], *, legacy: bool = False) -> None:
        self.trace: list[str] = []
        self.bootstrap_jobs = BootstrapHistory(rows, self.trace)
        plan: dict[str, Any] = {
            "_id": SELLER,
            "seller_id": SELLER,
            "cutoff": CUTOFF,
            "progress": {"orders": {"completed": 9}},
            "checkpoints": {"retained": True},
            "lease": {"owner": "retained-owner", "until": NOW + timedelta(minutes=3)},
        }
        if not legacy:
            plan.update(
                policy_version="history-on-link-v1",
                budget={"orders": {"physical_attempts": 500, "consumed": 42}},
                total_budget=900,
                total_consumed=42,
            )
        self.plans = TracedPlans(plan, self.trace)

    def __getitem__(self, name: str) -> Any:
        if name == "bootstrap_jobs":
            return self.bootstrap_jobs
        assert name == "sheets_history_backfill_plans"
        return self.plans


def job(identity: str, state: str, *, seller: str = SELLER) -> dict[str, Any]:
    return {
        "_id": identity,
        "seller_id": seller,
        "state": state,
        "created_at": CREATED,
        "checkpoints": {"kept": identity},
    }


def history(state: str) -> list[dict[str, Any]]:
    return [job(f"historic-failed-{i}", "failed") for i in range(12)] + [
        job("historic-eligible", state)
    ]


@pytest.fixture(autouse=True)
def admission_open_for_pilot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZELERDATA_HISTORY_ON_LINK_ADMISSION_HOLD", "false")
    monkeypatch.setenv("ZELERDATA_HISTORY_ON_LINK_ADMISSION_SELLERS", SELLER)


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["succeeded", "pending", "running"])
@pytest.mark.parametrize("legacy", [False, True])
async def test_thirteen_jobs_skip_bootstrap_but_still_admit_history(
    state: str, legacy: bool
) -> None:
    rows = history(state) + [job("foreign-success", "succeeded", seller="other-seller")]
    db, publisher = HistoryDb(rows, legacy=legacy), FakePublisher()
    before_jobs = copy.deepcopy(db.bootstrap_jobs.docs)
    before_plan = copy.deepcopy(db.plans.document)
    await events.emit_accounts_linked(
        SELLER, "synthetic-user", mongo_db=db, amqp_publisher=publisher, clock=lambda: NOW
    )
    assert db.bootstrap_jobs.docs == before_jobs
    assert db.bootstrap_jobs.replacements == []
    assert publisher.messages == []
    assert db.bootstrap_jobs.queries == [
        {"seller_id": SELLER, "state": {"$in": ["pending", "running", "succeeded"]}}
    ]
    assert db.trace.index("history_admission") < db.trace.index("bootstrap_read")
    assert before_plan is not None and db.plans.document is not None
    for field in ("cutoff", "progress", "checkpoints", "lease"):
        assert db.plans.document[field] == before_plan[field]
    assert db.plans.document["policy_version"] == "history-on-link-v1"
    assert db.plans.document["last_linked_at"] == NOW.replace(tzinfo=None)
    if not legacy:
        for field in ("budget", "total_budget", "total_consumed"):
            assert db.plans.document[field] == before_plan[field]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["none", "all-failed", "other-seller-only"])
async def test_no_eligible_record_keeps_original_new_or_retry_semantics(mode: str) -> None:
    rows = history("failed") if mode == "all-failed" else []
    rows.append(job("foreign-success", "succeeded", seller="other-seller"))
    db, publisher = HistoryDb(rows), FakePublisher()
    before = copy.deepcopy(db.bootstrap_jobs.docs)
    await events.emit_accounts_linked(
        SELLER, "synthetic-user", mongo_db=db, amqp_publisher=publisher, clock=lambda: NOW
    )
    assert len(db.bootstrap_jobs.replacements) == 1
    created = db.bootstrap_jobs.replacements[0]
    assert created["_id"] == f"bootstrap-{SELLER}-oauth"
    assert created["state"] == "pending"
    assert created["created_at"] == (CREATED if mode == "all-failed" else NOW)
    assert created["triggered_by"] == "oauth_callback"
    assert created["dispatch_attempts"] == 0
    for identity, value in before.items():
        assert db.bootstrap_jobs.docs[identity] == value
    assert publisher.messages[0]["payload"]["idempotency_key"] == f"accounts-linked-{SELLER}-oauth"
    assert db.bootstrap_jobs.queries == [
        {"seller_id": SELLER, "state": {"$in": ["pending", "running", "succeeded"]}},
        {"seller_id": SELLER},
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["succeeded", "pending", "failed"])
async def test_force_preserves_original_seller_only_read_and_created_at(state: str) -> None:
    db, publisher = HistoryDb(history(state)), FakePublisher()
    before = copy.deepcopy(db.bootstrap_jobs.docs)
    await events.emit_accounts_linked(
        SELLER,
        "synthetic-user",
        mongo_db=db,
        amqp_publisher=publisher,
        force=True,
        clock=lambda: NOW,
    )
    assert db.bootstrap_jobs.queries == [{"seller_id": SELLER}]
    created = db.bootstrap_jobs.replacements[0]
    assert created["created_at"] == CREATED
    assert created["triggered_by"] == "oauth_callback_force"
    assert publisher.messages[0]["payload"]["idempotency_key"] == f"accounts-linked-{SELLER}-force"
    for identity, value in before.items():
        assert db.bootstrap_jobs.docs[identity] == value
