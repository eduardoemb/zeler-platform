"""A pinned explicit extension changes deadline/lineage only, never grants new credit."""

from __future__ import annotations

import copy
import json
import socket
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from bson import BSON
from infra.operations import zelerdata_history_pilot as ops
from pymongo.results import UpdateResult

from zeler_platform_core.history_onboarding import POLICY_VERSION, SOURCES

EXECUTION = "868b413e20184befb7e8358e0051924f"
START = datetime(2026, 10, 6, 4, 22, 57, 845386, tzinfo=UTC)
OLD_END = datetime(2026, 10, 6, 5, 52, 57, 845000, tzinfo=UTC)
AUTHORIZED = datetime(2026, 10, 6, 6, 17, 23, tzinfo=UTC)
NEW_END = datetime(2026, 10, 6, 8, 17, 23, tzinfo=UTC)
NOW = AUTHORIZED + timedelta(minutes=1)


class Collection:
    def __init__(self, document: dict[str, Any]) -> None:
        self.doc = dict(BSON(BSON.encode(document)).decode())
        self.writes: list[tuple[dict[str, Any], dict[str, Any]]] = []
        self.drift = False

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any]:
        assert query == {"_id": ops.SELLER}
        return copy.deepcopy(self.doc)

    async def update_one(
        self, query: dict[str, Any], update: dict[str, Any], *, upsert: bool
    ) -> UpdateResult:
        assert upsert is False and query["_id"] == ops.SELLER
        assert query["$expr"]["$eq"][0] == "$$ROOT"
        if self.drift:
            self.doc["execution_consumed"] += 1
        expected = query["$expr"]["$eq"][1]["$literal"]
        matches = BSON.encode(self.doc) == BSON.encode(expected)
        self.writes.append((copy.deepcopy(query), copy.deepcopy(update)))
        if matches:
            assert set(update) == {"$set"}
            for field, value in update["$set"].items():
                target = self.doc
                parts = field.split(".")
                for part in parts[:-1]:
                    target = target.setdefault(part, {})
                target[parts[-1]] = copy.deepcopy(value)
            self.doc = dict(BSON(BSON.encode(self.doc)).decode())
        return UpdateResult({"n": int(matches), "nModified": int(matches)}, True)


class DB:
    def __init__(self) -> None:
        self.collection = Collection(plan())

    def __getitem__(self, name: str) -> Collection:
        assert name == "sheets_history_backfill_plans", "extension may not touch any jobs/data"
        return self.collection


def plan() -> dict[str, Any]:
    initial = dict(ops.INITIAL)
    used = dict(zip(initial, (0, 3, 2, 2, 49), strict=True))
    return {
        "_id": ops.SELLER,
        "seller_id": ops.SELLER,
        "policy_version": POLICY_VERSION,
        "authority": {"kind": "account_link_policy"},
        "state": "paused",
        "eligible": True,
        "sources": list(initial),
        "cutoff": datetime(2026, 9, 24, 5, 36, 28, tzinfo=UTC),
        "date_from": datetime(2025, 9, 24, 5, 36, 28, tzinfo=UTC),
        "date_to": datetime(2026, 9, 24, 5, 36, 28, tzinfo=UTC),
        "execution_id": EXECUTION,
        "execution_utc_day": "2026-10-06",
        "execution_until": OLD_END,
        "execution_attempt_limit": 2500,
        "execution_consumed": 69,
        "execution_sent": 67,
        "total_budget": 2000,
        "total_consumed": 56,
        "budget": {
            s: {"physical_attempts": initial.get(s, 0), "consumed": used.get(s, 0)} for s in SOURCES
        },
        "incremental_policy": {"max_daily_total": 500, "max_daily_source": 300},
        "incremental_day": "2026-10-06",
        "incremental_consumed": 13,
        "incremental_source_consumed": dict(zip(SOURCES, (9, 2, 0, 2, 0, 0), strict=True)),
        "execution_charged": {EXECUTION: {"messages": {"maintenance": 2}}},
        "checkpoint_fixture": {"kept": 17},
        "progress": {"orders": {"completed": 12}},
        "lease_until": AUTHORIZED - timedelta(minutes=5),
        "lease_token": "fixture-expired",
    }


def receipt(action: str, db: DB, *, observed: datetime) -> bytes:
    value: dict[str, Any] = {
        "action": action,
        "applied": True,
        "seller_id": ops.SELLER,
        "policy_version": POLICY_VERSION,
        "execution_id": EXECUTION,
        "observed_utc": observed.isoformat(),
        "resulting_plan_sha256": ops._plan_hash(db.collection.doc),
        "state": "paused",
    }
    if action == "prepare":
        value.update(
            initial_remaining=dict(ops.INITIAL),
            daily_rollover_pending=True,
            natural_rollover_limits={"total": 500, "per_source": 300},
        )
    return ops.receipt_bytes(value)


def inputs(db: DB) -> tuple[dict[str, Any], dict[str, Any]]:
    prepared, paused = (
        receipt("prepare", db, observed=START),
        receipt("pause", db, observed=AUTHORIZED - timedelta(minutes=2)),
    )
    common = {
        "prepared_receipt": prepared,
        "prepared_receipt_sha256": ops.receipt_sha256(prepared),
        "paused_receipt": paused,
        "paused_receipt_sha256": ops.receipt_sha256(paused),
        "runtime_controls_verified": True,
        "execution_id": EXECUTION,
    }
    authority = {
        "action": "authorize_extension",
        "authorization_received": True,
        "seller_id": ops.SELLER,
        "policy_version": POLICY_VERSION,
        "execution_id": EXECUTION,
        "authorized_at_utc": AUTHORIZED.isoformat(),
        "original_until_utc": OLD_END.isoformat(),
        "approved_until_utc": NEW_END.isoformat(),
        "max_additional_seconds": 7200,
        "prepared_receipt_sha256": common["prepared_receipt_sha256"],
        "paused_receipt_sha256": common["paused_receipt_sha256"],
        "user_evidence": "explicit synthetic user extension",
        "no_new_credit": True,
        "full_excluded": True,
    }
    return common, authority


async def extend(
    db: DB, *, apply: bool = True, change: dict[str, Any] | None = None, bad_pin: bool = False
) -> dict[str, Any]:
    common, authority = inputs(db)
    authority.update(change or {})
    raw = ops.receipt_bytes(authority)
    return await ops.control_pilot(
        db,
        "extend-paused",
        now=NOW,
        apply=apply,
        **common,
        extension_authority=raw,
        extension_authority_sha256="0" * 64 if bad_pin else ops.receipt_sha256(raw),
    )


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("extension tests forbid sockets")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


@pytest.mark.asyncio
@pytest.mark.parametrize("apply", [False, True])
async def test_explicit_extension_changes_only_deadline_and_external_pinned_lineage(
    apply: bool,
) -> None:
    db = DB()
    before = copy.deepcopy(db.collection.doc)
    result = await extend(db, apply=apply)
    assert result["applied"] is apply and result["state"] == "paused"
    if apply:
        assert db.collection.doc["execution_until"] == NEW_END.replace(tzinfo=None)
        assert set(db.collection.doc) == set(before)
        for field, value in before.items():
            if field != "execution_until":
                assert db.collection.doc[field] == value
        assert set(db.collection.writes[0][1]["$set"]) == {"execution_until"}
    else:
        assert db.collection.doc == before and db.collection.writes == []
    common, authority = inputs(DB())
    assert result["previous_plan_sha256"] == ops._plan_hash(before)
    assert result["prepared_receipt_sha256"] == common["prepared_receipt_sha256"]
    assert result["paused_receipt_sha256"] == common["paused_receipt_sha256"]
    assert result["extension_authority_sha256"] == ops.receipt_sha256(ops.receipt_bytes(authority))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"authorization_received": False},
        {"execution_id": "b" * 32},
        {"no_new_credit": False},
        {"full_excluded": False},
        {"approved_until_utc": (NEW_END + timedelta(seconds=1)).isoformat()},
    ],
)
async def test_unpinned_or_out_of_scope_authority_never_changes_plan(
    change: dict[str, Any],
) -> None:
    db = DB()
    before = copy.deepcopy(db.collection.doc)
    with pytest.raises(ops.PilotControlError):
        await extend(db, change=change)
    assert db.collection.doc == before and db.collection.writes == []


@pytest.mark.asyncio
async def test_wrong_authority_pin_fails_without_write() -> None:
    db = DB()
    with pytest.raises(ops.PilotControlError):
        await extend(db, bad_pin=True)
    assert db.collection.writes == []


@pytest.mark.asyncio
async def test_live_lease_and_cas_counter_drift_cannot_extend() -> None:
    db = DB()
    db.collection.doc["lease_until"] = (NOW + timedelta(minutes=1)).replace(tzinfo=None)
    with pytest.raises(ops.PilotControlError):
        await extend(db)
    assert db.collection.writes == []
    db = DB()
    db.collection.drift = True
    with pytest.raises(ops.PilotControlError, match="plan_changed"):
        await extend(db)
    assert db.collection.doc["execution_consumed"] == 70
    assert db.collection.doc["execution_until"] == OLD_END.replace(tzinfo=None)


@pytest.mark.asyncio
async def test_resume_requires_applied_extension_receipt_and_preserves_everything_else() -> None:
    db = DB()
    common, _ = inputs(db)
    extension = await extend(db)
    raw = ops.receipt_bytes(extension)
    before = copy.deepcopy(db.collection.doc)
    with pytest.raises(ops.PilotControlError):
        await ops.control_pilot(db, "resume", now=NOW, **common)
    result = await ops.control_pilot(
        db,
        "resume",
        now=NOW,
        apply=True,
        **common,
        extension_receipt=raw,
        extension_receipt_sha256=ops.receipt_sha256(raw),
    )
    assert result["state"] == "active" and db.collection.doc == {**before, "state": "active"}


@pytest.mark.asyncio
async def test_extension_receipt_from_preview_cannot_resume() -> None:
    db = DB()
    common, _ = inputs(db)
    preview = await extend(db, apply=False)
    raw = ops.receipt_bytes(preview)
    with pytest.raises(ops.PilotControlError):
        await ops.control_pilot(
            db,
            "resume",
            now=NOW,
            **common,
            extension_receipt=raw,
            extension_receipt_sha256=ops.receipt_sha256(raw),
        )
    assert db.collection.doc["state"] == "paused" and db.collection.writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "guard",
    [
        "authority_future",
        "duration_bool",
        "duration_large",
        "old_until",
        "parent_pin",
        "pause_unapplied",
        "pause_pin",
        "runtime",
    ],
)
async def test_authority_clock_duration_parent_and_runtime_guards(guard: str) -> None:
    db = DB()
    common, authority = inputs(db)
    if guard == "authority_future":
        authority["authorized_at_utc"] = (NOW + timedelta(seconds=1)).isoformat()
    elif guard == "duration_bool":
        authority["max_additional_seconds"] = True
    elif guard == "duration_large":
        authority["max_additional_seconds"] = 7201
    elif guard == "old_until":
        authority["original_until_utc"] = (OLD_END - timedelta(seconds=1)).isoformat()
    elif guard == "parent_pin":
        authority["prepared_receipt_sha256"] = "0" * 64
    elif guard == "pause_unapplied":
        paused = json.loads(common["paused_receipt"])
        paused["applied"] = False
        common["paused_receipt"] = ops.receipt_bytes(paused)
        common["paused_receipt_sha256"] = ops.receipt_sha256(common["paused_receipt"])
        authority["paused_receipt_sha256"] = common["paused_receipt_sha256"]
    elif guard == "pause_pin":
        common["paused_receipt_sha256"] = "0" * 64
        authority["paused_receipt_sha256"] = "0" * 64
    else:
        common["runtime_controls_verified"] = False
    before = copy.deepcopy(db.collection.doc)
    raw = ops.receipt_bytes(authority)
    with pytest.raises(ops.PilotControlError):
        await ops.control_pilot(
            db,
            "extend-paused",
            now=NOW,
            apply=True,
            **common,
            extension_authority=raw,
            extension_authority_sha256=ops.receipt_sha256(raw),
        )
    assert db.collection.doc == before and db.collection.writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["resulting_plan_sha256", "previous_plan_sha256", "state"])
async def test_repinning_forged_extension_receipt_cannot_resume(field: str) -> None:
    db = DB()
    common, _ = inputs(db)
    extension = await extend(db)
    extension[field] = "active" if field == "state" else "0" * 64
    raw = ops.receipt_bytes(extension)
    before = copy.deepcopy(db.collection.doc)
    with pytest.raises(ops.PilotControlError):
        await ops.control_pilot(
            db,
            "resume",
            now=NOW,
            apply=True,
            **common,
            extension_receipt=raw,
            extension_receipt_sha256=ops.receipt_sha256(raw),
        )
    assert db.collection.doc == before and len(db.collection.writes) == 1


def test_cli_new_extension_flags_are_explicit_inputs_and_default_dryrun() -> None:
    parsed = ops.build_parser().parse_args(
        [
            "extend-paused",
            "--extension-authority-in",
            "fixture-authority.json",
            "--extension-authority-sha256",
            "a" * 64,
        ]
    )
    assert parsed.action == "extend-paused" and parsed.apply is False
    assert str(parsed.extension_authority_in) == "fixture-authority.json"
    resumed = ops.build_parser().parse_args(
        [
            "resume",
            "--extension-receipt-in",
            "fixture-extension.json",
            "--extension-receipt-sha256",
            "b" * 64,
        ]
    )
    assert resumed.apply is False and str(resumed.extension_receipt_in) == "fixture-extension.json"
