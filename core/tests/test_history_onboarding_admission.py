"""Legacy admission preserves BSON state and initializes only prospective missing leaves."""

from __future__ import annotations

import asyncio
import copy
import socket
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from bson import BSON
from pymongo.results import UpdateResult

from zeler_platform_core.history_onboarding import SOURCES, admit_history_onboarding

SELLER = "82453304"
NOW = datetime(2026, 10, 6, 2, 30, tzinfo=UTC)
CUTOFF = datetime(2026, 9, 24, 5, 36, 28, 789000, tzinfo=UTC)
INITIAL = dict(zip(SOURCES[:-1], (800, 150, 250, 300, 500), strict=True))
MISSING = object()


def bson(value: dict[str, Any]) -> dict[str, Any]:
    return dict(BSON(BSON.encode(value)).decode())


def leaf(document: dict[str, Any], path: str) -> Any:
    value: Any = document
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return MISSING
        value = value[part]
    return value


def put(document: dict[str, Any], path: str, value: Any) -> None:
    target = document
    parts = path.split(".")
    for part in parts[:-1]:
        if part not in target:
            target[part] = {}
        assert isinstance(target[part], dict), "Mongo cannot write a leaf through scalar/null"
        target = target[part]
    target[parts[-1]] = copy.deepcopy(value)


def expr(document: dict[str, Any], value: Any) -> Any:
    if value == "$$ROOT":
        return document
    if isinstance(value, dict) and set(value) == {"$literal"}:
        return value["$literal"]
    if isinstance(value, dict) and set(value) == {"$eq"}:
        left, right = (expr(document, item) for item in value["$eq"])
        return BSON.encode({"v": left}) == BSON.encode({"v": right})
    raise AssertionError("unsupported fake expression; do not pretend it matched")


def matches(document: dict[str, Any], query: dict[str, Any]) -> bool:
    for key, expected in query.items():
        if key == "$expr":
            if not expr(document, expected):
                return False
        elif key in {"$and", "$or"}:
            values = [matches(document, child) for child in expected]
            if not (all(values) if key == "$and" else any(values)):
                return False
        else:
            actual = leaf(document, key)
            if isinstance(expected, dict):
                for operator, operand in expected.items():
                    if operator == "$exists":
                        valid = (actual is not MISSING) is operand
                    elif operator == "$in":
                        valid = actual in operand
                    elif operator == "$ne":
                        valid = actual != operand
                    else:
                        raise AssertionError("unsupported fake query operator")
                    if not valid:
                        return False
            elif actual is MISSING or BSON.encode({"v": actual}) != BSON.encode({"v": expected}):
                return False
    return True


class Plans:
    def __init__(self, document: dict[str, Any] | None) -> None:
        self.document = bson(document) if document is not None else None
        self.calls: list[tuple[dict[str, Any], dict[str, Any], bool]] = []
        self.drift_after_read: dict[str, Any] | None = None
        self.armed = False

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        result = (
            copy.deepcopy(self.document)
            if self.document and matches(self.document, query)
            else None
        )
        self.armed = True
        await asyncio.sleep(0)
        return result

    async def update_one(
        self, query: dict[str, Any], update: dict[str, Any], *, upsert: bool = False
    ) -> UpdateResult:
        self.calls.append((copy.deepcopy(query), copy.deepcopy(update), upsert))
        if self.armed and self.drift_after_read is not None and self.document is not None:
            for path, value in self.drift_after_read.items():
                put(self.document, path, value)
            self.document = bson(self.document)
            self.drift_after_read = None
        self.armed = False
        inserted = self.document is None and upsert
        if inserted:
            assert set(query) == {"_id"}, "upsert cannot manufacture a snapshot identity"
            self.document = {"_id": query["_id"]}
        if self.document is None or not (inserted or matches(self.document, query)):
            return UpdateResult({"n": 0, "nModified": 0}, True)
        before = BSON.encode(self.document)
        assert set(update) <= {"$setOnInsert", "$set", "$max"}, "admission may not reset/unset"
        for path, value in update.get("$setOnInsert", {}).items() if inserted else ():
            put(self.document, path, value)
        for path, value in update.get("$set", {}).items():
            put(self.document, path, value)
        for path, value in update.get("$max", {}).items():
            current = leaf(self.document, path)
            incoming = bson({"v": value})["v"]
            if current is MISSING or current < incoming:
                put(self.document, path, incoming)
        self.document = bson(self.document)
        raw = {"n": 1, "nModified": int(before != BSON.encode(self.document))}
        if inserted:
            raw["upserted"] = self.document["_id"]
        return UpdateResult(raw, True)


class Db:
    def __init__(self, document: dict[str, Any] | None) -> None:
        self.plans = Plans(document)

    def __getitem__(self, name: str) -> Plans:
        assert name == "sheets_history_backfill_plans", "admission must not mutate jobs/data"
        return self.plans


def legacy(**changes: Any) -> dict[str, Any]:
    return {
        "_id": SELLER,
        "seller_id": SELLER,
        "cutoff": CUTOFF,
        "schema_version": 1,
        "progress": {"orders": {"completed": 9, "chunks": [{"attempts": 4}]}},
        "checkpoints": {"kept": {"offset": 19}},
        "collector_checkpoints": {"messages": {"offset": 27}},
        "unrelated": {"keep": True},
        **changes,
    }


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("admission tests must not open sockets")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


def test_fake_dotted_snapshot_and_max_are_faithful() -> None:
    db = Db(legacy(total_consumed=17, last_linked_at=NOW))
    snapshot = copy.deepcopy(db.plans.document)
    assert snapshot is not None
    assert db.plans.document is not None
    assert matches(snapshot, {"$expr": {"$eq": ["$$ROOT", {"$literal": snapshot}]}})
    db.plans.document["added"] = True
    result = asyncio.run(
        db.plans.update_one(
            {"$expr": {"$eq": ["$$ROOT", {"$literal": snapshot}]}}, {"$set": {"total_consumed": 0}}
        )
    )
    assert db.plans.document is not None
    assert result.matched_count == 0 and db.plans.document["total_consumed"] == 17
    result = asyncio.run(
        db.plans.update_one(
            {"_id": SELLER},
            {
                "$set": {"budget.orders.consumed": 3},
                "$max": {"last_linked_at": NOW - timedelta(days=1)},
            },
        )
    )
    assert db.plans.document is not None
    assert result.matched_count == 1
    assert db.plans.document["budget"] == {"orders": {"consumed": 3}}
    assert db.plans.document["last_linked_at"] == NOW.replace(tzinfo=None)


@pytest.mark.asyncio
async def test_pilot_missing_counters_are_new_prospective_paused_not_history_credit() -> None:
    db = Db(legacy())
    before = copy.deepcopy(db.plans.document)
    await admit_history_onboarding(db, SELLER, now=NOW, pilot_seed=True)
    plan = db.plans.document
    assert before is not None and plan is not None
    for key, value in before.items():
        assert plan[key] == value
    assert plan["state"] == "paused" and plan["sources"] == list(INITIAL)
    assert plan["authority"] == {"kind": "account_link_policy"}
    assert plan["date_from"] == datetime(2025, 9, 24, 5, 36, 28, 789000)
    assert plan["date_to"] == before["cutoff"]
    assert plan["total_budget"] == 2000 and plan["total_consumed"] == 0
    assert plan["incremental_policy"] == {"max_daily_total": 500, "max_daily_source": 300}
    assert plan["budget"] == {
        source: {"physical_attempts": INITIAL.get(source, 0), "consumed": 0} for source in SOURCES
    }
    assert not {
        "execution_id",
        "execution_utc_day",
        "execution_until",
        "execution_attempt_limit",
    }.intersection(plan)


@pytest.mark.asyncio
async def test_legacy_partial_nonzero_fields_preserved_before_any_policy_exists() -> None:
    db = Db(
        legacy(
            budget={
                "orders": {"physical_attempts": 33, "consumed": 17, "held": 2},
                "messages": {"consumed": 9},
            },
            total_consumed=26,
            source_cursor=8,
            state="paused",
            eligible=False,
            onboarding_status="running",
            incremental_day="2026-10-05",
            incremental_consumed=4,
            incremental_source_consumed={"orders": 4},
        )
    )
    before = copy.deepcopy(db.plans.document)
    await admit_history_onboarding(db, SELLER, now=NOW)
    plan = db.plans.document
    assert before is not None and plan is not None
    for key, value in before.items():
        if key == "budget":
            for source, entry in value.items():
                for field, item in entry.items():
                    assert plan[key][source][field] == item
        else:
            assert plan[key] == value


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"total_consumed": None},
        {"total_consumed": True},
        {"total_consumed": -1},
        {"budget": None},
        {"budget": {"orders": {"consumed": "17"}}},
    ],
)
async def test_present_malformed_counters_are_not_missing(change: dict[str, Any]) -> None:
    db = Db(legacy(**change))
    before = copy.deepcopy(db.plans.document)
    with pytest.raises(ValueError):
        await admit_history_onboarding(db, SELLER, now=NOW)
    assert db.plans.document == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"lease_until": NOW + timedelta(minutes=2), "lease_token": "fixture-owner"},
        {"lease_token": "fixture-owner"},
        {"lease_until": None},
        {"lease": {"owner": "fixture-owner", "until": NOW + timedelta(minutes=2)}},
    ],
)
async def test_live_or_malformed_lease_cannot_upgrade(change: dict[str, Any]) -> None:
    db = Db(legacy(**change))
    before = copy.deepcopy(db.plans.document)
    with pytest.raises(ValueError):
        await admit_history_onboarding(db, SELLER, now=NOW)
    assert db.plans.document == before


@pytest.mark.asyncio
async def test_expired_execution_identity_and_lease_preserved_never_reopened() -> None:
    fields = {
        "execution_id": "a" * 32,
        "execution_utc_day": "2026-09-24",
        "execution_until": CUTOFF + timedelta(minutes=90),
        "execution_attempt_limit": 300,
        "execution_consumed": 17,
        "lease_until": NOW - timedelta(minutes=2),
        "lease_token": "fixture-old-owner",
    }
    db = Db(legacy(**fields))
    await admit_history_onboarding(db, SELLER, now=NOW, pilot_seed=True)
    assert db.plans.document is not None
    for key, value in bson(fields).items():
        assert db.plans.document[key] == value
    assert db.plans.document["state"] == "paused"


@pytest.mark.asyncio
async def test_cas_added_field_and_counter_drift_is_not_overwritten() -> None:
    db = Db(legacy(total_consumed=17))
    db.plans.drift_after_read = {"total_consumed": 18, "concurrent_field": True}
    with pytest.raises(ValueError):
        await admit_history_onboarding(db, SELLER, now=NOW)
    assert db.plans.document is not None
    assert (
        db.plans.document["total_consumed"] == 18 and db.plans.document["concurrent_field"] is True
    )
    assert "policy_version" not in db.plans.document


@pytest.mark.asyncio
async def test_two_concurrent_links_idempotent_fixed_cutoff_and_latest_link() -> None:
    db = Db(legacy(total_consumed=17))
    await asyncio.gather(
        admit_history_onboarding(db, SELLER, now=NOW + timedelta(minutes=1)),
        admit_history_onboarding(db, SELLER, now=NOW),
    )
    assert db.plans.document is not None
    assert db.plans.document["cutoff"] == CUTOFF.replace(tzinfo=None)
    assert db.plans.document["total_consumed"] == 17
    assert db.plans.document["last_linked_at"] == (NOW + timedelta(minutes=1)).replace(tzinfo=None)


@pytest.mark.asyncio
async def test_policy_relink_only_monotonic_link_timestamp() -> None:
    db = Db(
        legacy(
            policy_version="history-on-link-v1",
            authority={"kind": "account_link_policy"},
            state="paused",
            last_linked_at=NOW + timedelta(minutes=1),
            total_consumed=17,
        )
    )
    before = copy.deepcopy(db.plans.document)
    await admit_history_onboarding(db, SELLER, now=NOW)
    assert db.plans.document == before


@pytest.mark.asyncio
async def test_existing_full_consumption_preserved_but_never_selected() -> None:
    db = Db(legacy(budget={"full_withdrawals": {"physical_attempts": 100, "consumed": 7}}))
    await admit_history_onboarding(db, SELLER, now=NOW, pilot_seed=True)
    assert db.plans.document is not None
    assert db.plans.document["budget"]["full_withdrawals"] == {
        "physical_attempts": 100,
        "consumed": 7,
    }
    assert "full_withdrawals" not in db.plans.document["sources"]


@pytest.mark.asyncio
async def test_unknown_ledger_is_not_new_zero_counter_authority() -> None:
    db = Db(legacy(execution_charged={"unknown-execution": {"orders": {"initial": 7}}}))
    before = copy.deepcopy(db.plans.document)
    with pytest.raises(ValueError):
        await admit_history_onboarding(db, SELLER, now=NOW)
    assert db.plans.document == before


@pytest.mark.asyncio
async def test_pilot_active_legacy_cannot_receive_new_authority_without_pause() -> None:
    db = Db(legacy(state="active"))
    before = copy.deepcopy(db.plans.document)
    with pytest.raises(ValueError):
        await admit_history_onboarding(db, SELLER, now=NOW, pilot_seed=True)
    assert db.plans.document == before


@pytest.mark.asyncio
async def test_cas_incomplete_winner_is_not_idempotent_authority_success() -> None:
    db = Db(legacy())
    before = copy.deepcopy(db.plans.document)
    db.plans.drift_after_read = {"policy_version": "history-on-link-v1"}
    with pytest.raises(ValueError):
        await admit_history_onboarding(db, SELLER, now=NOW, pilot_seed=True)
    assert before is not None
    assert db.plans.document == {**before, "policy_version": "history-on-link-v1"}


@pytest.mark.asyncio
async def test_missing_cap_below_existing_consumed_must_wait_before_grant() -> None:
    db = Db(legacy(budget={"orders": {"consumed": 801}}, total_consumed=801))
    before = copy.deepcopy(db.plans.document)
    with pytest.raises(ValueError):
        await admit_history_onboarding(db, SELLER, now=NOW, pilot_seed=True)
    assert db.plans.document == before
