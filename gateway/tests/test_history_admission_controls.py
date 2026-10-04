"""History admission hold is independent from OAuth and bootstrap behavior."""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from bson import BSON
from gateway.tests.test_oauth_emit_accounts_linked import FakeDb, FakePublisher

from zeler_gateway.oauth import events
from zeler_platform_core.history_onboarding import admit_history_onboarding


@pytest.mark.asyncio
@pytest.mark.parametrize("relink", [False, True])
async def test_hold_skips_new_history_intent_but_preserves_account_link_bootstrap(
    monkeypatch: pytest.MonkeyPatch,
    relink: bool,
) -> None:
    monkeypatch.setenv("ZELERDATA_HISTORY_ON_LINK_ADMISSION_HOLD", "true")
    db, publisher = FakeDb(), FakePublisher()
    called: list[str] = []

    async def admission(_: Any, seller: str, **kwargs: Any) -> None:
        called.append(seller)

    monkeypatch.setattr(events, "admit_history_onboarding", admission)
    if relink:
        db.bootstrap_jobs.docs["bootstrap-82453304-oauth"] = {
            "_id": "bootstrap-82453304-oauth",
            "seller_id": "82453304",
            "state": "succeeded",
            "checkpoints": {"orders": 1},
        }
    await events.emit_accounts_linked(
        "82453304",
        "user",
        mongo_db=db,
        amqp_publisher=publisher,
        clock=lambda: datetime(2026, 10, 3, tzinfo=UTC),
    )
    assert called == []
    assert db.bootstrap_jobs.docs["bootstrap-82453304-oauth"]["state"] == (
        "succeeded" if relink else "pending"
    )
    assert len(publisher.messages) == (0 if relink else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scope", "seller", "admitted"),
    [
        ("82453304", "82453304", True),
        ("82453304", "456", False),
        ("", "82453304", False),
        ("*", "82453304", False),
        ("082453304", "82453304", False),
        (None, "456", True),
    ],
)
async def test_admission_scope_fences_nonpilot_without_disabling_oauth(
    monkeypatch: pytest.MonkeyPatch,
    scope: str | None,
    seller: str,
    admitted: bool,
) -> None:
    monkeypatch.delenv("ZELERDATA_HISTORY_ON_LINK_ADMISSION_HOLD", raising=False)
    if scope is None:
        monkeypatch.delenv("ZELERDATA_HISTORY_ON_LINK_ADMISSION_SELLERS", raising=False)
    else:
        monkeypatch.setenv("ZELERDATA_HISTORY_ON_LINK_ADMISSION_SELLERS", scope)
    called: list[str] = []

    async def admission(_: Any, value: str, **kwargs: Any) -> None:
        called.append(value)

    monkeypatch.setattr(events, "admit_history_onboarding", admission)
    db, publisher = FakeDb(), FakePublisher()
    await events.emit_accounts_linked(seller, "user", mongo_db=db, amqp_publisher=publisher)
    assert called == ([seller] if admitted else [])
    assert len(publisher.messages) == 1


class BSONHistoryPlans:
    """Default gateway Motor codec: persisted BSON dates read as naive UTC."""

    def __init__(self, document: dict[str, Any] | None = None) -> None:
        self.document = BSON(BSON.encode(document)).decode() if document is not None else None

    def matches(self, query: dict[str, Any]) -> bool:
        if self.document is None:
            return False
        return all(
            (key in self.document) == value["$exists"]
            if isinstance(value, dict) and "$exists" in value
            else self.document.get(key) == value
            for key, value in query.items()
        )

    async def update_one(
        self, query: dict[str, Any], update: dict[str, Any], *, upsert: bool = False
    ) -> None:
        if self.document is None and upsert:
            self.document = {**query, **update["$setOnInsert"]}
        elif self.matches(query):
            assert self.document is not None
            self.document.update(update.get("$set", {}))
        if self.document is not None:
            self.document = BSON(BSON.encode(self.document)).decode()

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        return copy.deepcopy(self.document) if self.matches(query) else None


class BSONHistoryDb(FakeDb):
    def __init__(self, document: dict[str, Any] | None = None) -> None:
        super().__init__()
        self.plans = BSONHistoryPlans(document)

    def __getitem__(self, name: str) -> Any:
        return self.plans if name == "sheets_history_backfill_plans" else super().__getitem__(name)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["new", "legacy", "policy"])
async def test_gateway_default_bson_cutoff_admission_and_relink_preserve_state(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    monkeypatch.delenv("ZELERDATA_HISTORY_ON_LINK_ADMISSION_HOLD", raising=False)
    monkeypatch.setenv("ZELERDATA_HISTORY_ON_LINK_ADMISSION_SELLERS", "82453304")
    cutoff = datetime(2024, 2, 29, 12, tzinfo=UTC)
    existing: dict[str, Any] | None = None
    if mode != "new":
        existing = {
            "_id": "82453304",
            "seller_id": "82453304",
            "cutoff": cutoff,
            "progress": {"orders": {"completed": 9}},
            "checkpoints": {"retained": True},
        }
        if mode == "policy":
            existing.update(
                policy_version="history-on-link-v1",
                budget={"orders": {"physical_attempts": 500, "consumed": 42}},
                total_budget=900,
                total_consumed=42,
            )
    db, publisher = BSONHistoryDb(existing), FakePublisher()
    before = copy.deepcopy(db.plans.document)
    await events.emit_accounts_linked(
        "82453304", "unit-user", mongo_db=db, amqp_publisher=publisher, clock=lambda: cutoff
    )
    admitted = db.plans.document
    assert admitted is not None
    assert admitted["cutoff"] == cutoff.replace(tzinfo=None)
    assert admitted["policy_version"] == "history-on-link-v1"
    if mode != "policy":
        assert admitted["date_from"] == datetime(2023, 2, 28, 12)
        assert admitted["date_to"] == cutoff.replace(tzinfo=None)
    if before is not None:
        for field in ("cutoff", "progress", "checkpoints"):
            assert admitted[field] == before[field]
        if mode == "policy":
            for field in ("budget", "total_budget", "total_consumed"):
                assert admitted[field] == before[field]
    admitted["budget"]["orders"]["consumed"] += 1
    state = copy.deepcopy(admitted)
    await events.emit_accounts_linked(
        "82453304",
        "unit-user",
        mongo_db=db,
        amqp_publisher=publisher,
        clock=lambda: cutoff + timedelta(days=3),
    )
    expected = {**state, "last_linked_at": (cutoff + timedelta(days=3)).replace(tzinfo=None)}
    assert db.plans.document == expected
    assert len(publisher.messages) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("cutoff", [None, "invalid", 123])
async def test_gateway_bson_invalid_cutoff_fails_closed(cutoff: Any) -> None:
    document = {"_id": "82453304", "seller_id": "82453304"}
    if cutoff is not None:
        document["cutoff"] = cutoff
    db = BSONHistoryDb(document)
    before = copy.deepcopy(db.plans.document)
    with pytest.raises(ValueError, match="invalid identity or cutoff"):
        await admit_history_onboarding(db, "82453304", now=datetime(2026, 10, 4, tzinfo=UTC))
    assert db.plans.document == before
