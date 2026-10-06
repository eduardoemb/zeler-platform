from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from bson import BSON
from infra.operations.zelerdata_history_pilot import (
    PilotControlError,
    control_pilot,
    receipt_bytes,
    receipt_sha256,
)

# Self-contained fixtures: cross-package pytest collects several packages named
# tests. Never depend on which package was imported first.
NOW = datetime(2026, 10, 4, 12, tzinfo=UTC)
EXECUTION = "a" * 32
SOURCES = ("orders", "questions", "shipments", "messages", "claims_returns", "full_withdrawals")


def plan() -> dict[str, Any]:
    return {
        "_id": "82453304",
        "seller_id": "82453304",
        "policy_version": "history-on-link-v1",
        "authority": {"kind": "account_link_policy"},
        "state": "active",
        "eligible": True,
        "cutoff": NOW - timedelta(days=1),
        "date_from": NOW - timedelta(days=366),
        "date_to": NOW - timedelta(days=1),
        "timezone": "UTC",
        "sources": list(SOURCES),
        "budget": {s: {"physical_attempts": 20000, "consumed": 13} for s in SOURCES},
        "total_budget": 100000,
        "total_consumed": 78,
        "incremental_policy": {"max_daily_total": 2000, "max_daily_source": 1000},
        "checkpoint_fixture": {"kept": True},
        "lease_token": "unchanged-token",
        "lease_until": NOW - timedelta(seconds=1),
        "execution_consumed": 7,
    }


class Collection:
    def __init__(self, document: dict[str, Any]) -> None:
        self.doc = copy.deepcopy(document)
        self.writes: list[tuple[dict[str, Any], dict[str, Any]]] = []
        self.race = False

    async def find_one(self, query: Any) -> Any:
        assert query == {"_id": "82453304"}
        return copy.deepcopy(self.doc)

    async def update_one(self, query: Any, update: Any, *, upsert: bool) -> Any:
        assert upsert is False
        self.writes.append((query, update))
        assert query["_id"] == "82453304"
        assert query["$expr"]["$eq"][0] == "$$ROOT"
        if self.race:
            self.doc["budget"]["orders"]["consumed"] += 1
        matches = self.doc == query["$expr"]["$eq"][1]["$literal"]
        if matches:
            assert set(update) == {"$set"}
            for field, value in update["$set"].items():
                target = self.doc
                parts = field.split(".")
                for part in parts[:-1]:
                    target = target.setdefault(part, {})
                target[parts[-1]] = value
        return type("Result", (), {"matched_count": int(matches)})()


class DB:
    def __init__(self, document: dict[str, Any] | None = None) -> None:
        self.collection = Collection(document or plan())

    def __getitem__(self, name: str) -> Collection:
        assert name == "sheets_history_backfill_plans", "must not access jobs/other collections"
        return self.collection


class BSONCollection(Collection):
    """Materialize dates like the CLI's default tz_aware=False Motor client."""

    def __init__(self, document: dict[str, Any]) -> None:
        super().__init__(BSON(BSON.encode(document)).decode())

    async def update_one(self, query: Any, update: Any, *, upsert: bool) -> Any:
        result = await super().update_one(query, update, upsert=upsert)
        self.doc = BSON(BSON.encode(self.doc)).decode()
        return result


async def prepared() -> tuple[Any, bytes, bytes]:
    p = plan()
    p.update(execution_consumed=0, total_consumed=0)
    for entry in p["budget"].values():
        entry["consumed"] = 0
    db = DB(p)
    first = await control_pilot(db, "prepare", now=NOW, execution_id=EXECUTION, apply=True)
    raw = receipt_bytes(first)
    await control_pilot(
        db,
        "activate",
        now=NOW,
        prepared_receipt=raw,
        prepared_receipt_sha256=receipt_sha256(raw),
        runtime_controls_verified=True,
        apply=True,
    )
    db.collection.doc.update(
        execution_consumed=69,
        execution_sent=67,
        total_consumed=56,
        incremental_day=NOW.date().isoformat(),
        incremental_consumed=13,
        incremental_source_consumed=dict.fromkeys(SOURCES, 0),
    )
    db.collection.doc["budget"]["claims_returns"]["consumed"] = 49
    db.collection.doc["onboarding_sources"] = {"messages": {"checkpoint": {"kept": True}}}
    paused = await control_pilot(db, "pause", now=NOW + timedelta(minutes=1), apply=True)
    db.collection.writes.clear()
    return db, raw, receipt_bytes(paused)


async def resume(db: Any, first: bytes, pause: bytes, **kwargs: Any) -> Any:
    return await control_pilot(
        db,
        "resume",
        now=kwargs.pop("now", NOW + timedelta(minutes=5)),
        prepared_receipt=first,
        prepared_receipt_sha256=kwargs.pop("prepared_receipt_sha256", receipt_sha256(first)),
        paused_receipt=pause,
        paused_receipt_sha256=kwargs.pop("paused_receipt_sha256", receipt_sha256(pause)),
        runtime_controls_verified=kwargs.pop("runtime_controls_verified", True),
        apply=kwargs.pop("apply", True),
        **kwargs,
    )


@pytest.mark.asyncio
async def test_resume_only_changes_state_preserves_all_existing_consumption_and_checkpoint() -> (
    None
):
    db, first, pause = await prepared()
    before = copy.deepcopy(db.collection.doc)
    receipt = await resume(db, first, pause)
    before["state"] = "active"
    assert db.collection.doc == before
    assert db.collection.writes[0][1] == {"$set": {"state": "active"}}
    assert receipt["action"] == "resume" and receipt["applied"]
    assert receipt["execution_id"] == EXECUTION


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        "runtime",
        "prepare_pin",
        "pause_pin",
        "changed_snapshot",
        "expired",
        "day",
        "lease",
        "scope",
        "wider_deadline",
        "wider_limit",
        "counter",
        "unapplied_pause",
    ],
)
async def test_resume_fail_closed_without_writes(bad: str) -> None:
    db, first, pause = await prepared()
    kwargs: dict[str, Any] = {}
    if bad == "runtime":
        kwargs["runtime_controls_verified"] = False
    elif bad == "prepare_pin":
        kwargs["prepared_receipt_sha256"] = "0" * 64
    elif bad == "pause_pin":
        kwargs["paused_receipt_sha256"] = "0" * 64
    elif bad == "changed_snapshot":
        db.collection.doc["unknown_added"] = True
    elif bad == "expired":
        kwargs["now"] = NOW + timedelta(hours=2)
    elif bad == "day":
        kwargs["now"] = NOW + timedelta(days=1)
    elif bad == "lease":
        db.collection.doc["lease_until"] = NOW + timedelta(minutes=6)
    elif bad == "scope":
        db.collection.doc["sources"].append("full_withdrawals")
    elif bad == "wider_deadline":
        db.collection.doc["execution_until"] = NOW + timedelta(hours=2)
    elif bad == "wider_limit":
        db.collection.doc["budget"]["orders"]["physical_attempts"] += 1
    elif bad == "counter":
        db.collection.doc["execution_consumed"] = True
    else:
        import json

        data = json.loads(pause)
        data["applied"] = False
        pause = receipt_bytes(data)
    if bad in {"lease", "scope", "wider_deadline", "wider_limit", "counter"}:
        # A newly approved pause snapshot still cannot enlarge original authority.
        refreshed = await control_pilot(db, "pause", now=NOW + timedelta(minutes=2), apply=True)
        pause = receipt_bytes(refreshed)
        db.collection.writes.clear()
    before = copy.deepcopy(db.collection.doc)
    with pytest.raises(PilotControlError):
        await resume(db, first, pause, **kwargs)
    assert not db.collection.writes and db.collection.doc == before


@pytest.mark.asyncio
async def test_resume_cas_race_has_no_retry() -> None:
    db, first, pause = await prepared()
    db.collection.race = True
    with pytest.raises(PilotControlError, match="plan_changed"):
        await resume(db, first, pause)
    assert len(db.collection.writes) == 1
    assert db.collection.doc["state"] == "paused"


@pytest.mark.asyncio
async def test_resume_default_bson_precision_preserves_original_until() -> None:

    db, first, pause = await prepared()
    db.collection = BSONCollection(db.collection.doc)
    pause = receipt_bytes(
        await control_pilot(db, "pause", now=NOW + timedelta(minutes=2), apply=True)
    )
    before = copy.deepcopy(db.collection.doc)
    await resume(db, first, pause)
    before["state"] = "active"
    assert db.collection.doc == before


@pytest.mark.asyncio
async def test_resume_dry_run_does_not_write_or_make_a_new_window() -> None:
    db, first, pause = await prepared()
    before = copy.deepcopy(db.collection.doc)
    result = await resume(db, first, pause, apply=False)
    assert result["applied"] is False and result["action"] == "resume"
    assert db.collection.doc == before and not db.collection.writes


@pytest.mark.asyncio
async def test_resume_rejects_unsupported_previous_daily_receipt() -> None:
    import json

    db, first, pause = await prepared()
    previous = json.loads(first)
    previous["daily_rollover_pending"] = False
    previous["natural_rollover_limits"] = None
    with pytest.raises(PilotControlError, match="resume_starting_credit_unknown"):
        await resume(db, receipt_bytes(previous), pause)
    assert not db.collection.writes


@pytest.mark.asyncio
async def test_resume_rejects_expanded_caps_even_in_current_pause_hash() -> None:
    db, first, pause = await prepared()
    db.collection.doc["execution_attempt_limit"] = 2501
    pause = receipt_bytes(
        await control_pilot(db, "pause", now=NOW + timedelta(minutes=2), apply=True)
    )
    db.collection.writes.clear()
    with pytest.raises(PilotControlError, match="resume_caps_invalid"):
        await resume(db, first, pause)
    assert not db.collection.writes
