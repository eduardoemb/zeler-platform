from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from bson import BSON
from infra.operations.zelerdata_history_pilot import (
    PilotControlError,
    build_parser,
    control_pilot,
    main,
    receipt_bytes,
    receipt_sha256,
)

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


@pytest.mark.asyncio
async def test_default_bson_dates_prepare_then_activate_preserves_entire_plan() -> None:
    db = DB()
    db.collection = BSONCollection(plan())
    receipt = await prepare(db, apply=True)
    before = copy.deepcopy(db.collection.doc)
    assert before["execution_until"].tzinfo is None
    raw = receipt_bytes(receipt)
    await control_pilot(
        db,
        "activate",
        now=NOW,
        prepared_receipt=raw,
        prepared_receipt_sha256=receipt_sha256(raw),
        runtime_controls_verified=True,
        apply=True,
    )
    expected = copy.deepcopy(before)
    expected["state"] = "active"
    assert db.collection.doc == expected
    assert db.collection.writes[-1][1] == {"$set": {"state": "active"}}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure,code",
    [
        ("deadline_drift", "prepared_plan_changed"),
        ("expired", "execution_window_or_limit"),
        ("wrong_day", "execution_window_or_limit"),
        ("active_lease", "active_lease"),
        ("cas_race", "plan_changed"),
    ],
)
async def test_default_bson_date_activation_guards(failure: str, code: str) -> None:
    p = plan()
    if failure == "active_lease":
        p["lease_until"] = NOW + timedelta(minutes=5)
    db = DB()
    db.collection = BSONCollection(p)
    raw = receipt_bytes(await prepare(db, apply=True))
    now = NOW
    if failure == "deadline_drift":
        db.collection.doc["execution_until"] += timedelta(seconds=1)
    elif failure == "expired":
        now += timedelta(minutes=90)
    elif failure == "wrong_day":
        now += timedelta(days=1)
    elif failure == "cas_race":
        db.collection.race = True
    writes = len(db.collection.writes)
    before = copy.deepcopy(db.collection.doc)
    with pytest.raises(PilotControlError, match=code):
        await control_pilot(
            db,
            "activate",
            now=now,
            prepared_receipt=raw,
            prepared_receipt_sha256=receipt_sha256(raw),
            runtime_controls_verified=True,
            apply=True,
        )
    if failure == "cas_race":
        before["budget"]["orders"]["consumed"] += 1
    assert db.collection.doc == before
    assert len(db.collection.writes) == writes + int(failure == "cas_race")


async def prepare(db: DB, **kwargs: Any) -> dict[str, Any]:
    return await control_pilot(db, "prepare", now=NOW, execution_id=EXECUTION, **kwargs)


@pytest.mark.asyncio
async def test_prepare_defaults_to_dry_run_and_preserves_everything() -> None:
    db = DB()
    before = copy.deepcopy(db.collection.doc)
    receipt = await prepare(db)
    assert db.collection.doc == before
    assert db.collection.writes == []
    assert receipt["applied"] is False
    assert receipt["daily_rollover_pending"] is True
    assert receipt["maintenance_remaining"] is None


@pytest.mark.asyncio
async def test_prepare_caps_remaining_and_changes_only_existing_control_fields() -> None:
    db = DB()
    before = copy.deepcopy(db.collection.doc)
    receipt = await prepare(db, apply=True)
    after = db.collection.doc
    assert receipt["applied"] is True and after["state"] == "paused"
    assert after["sources"] == list(SOURCES[:-1])
    assert [after["budget"][s]["physical_attempts"] - 13 for s in SOURCES] == [
        800,
        150,
        250,
        300,
        500,
        0,
    ]
    assert after["total_budget"] == 78 + 2000
    assert after["execution_attempt_limit"] == 7 + 2500
    assert after["execution_until"] == NOW + timedelta(minutes=90)
    assert after["incremental_policy"] == {"max_daily_total": 500, "max_daily_source": 300}
    for key in (
        "cutoff",
        "date_from",
        "date_to",
        "checkpoint_fixture",
        "lease_token",
        "lease_until",
        "total_consumed",
        "execution_consumed",
    ):
        assert after[key] == before[key]
    assert all(after["budget"][s]["consumed"] == before["budget"][s]["consumed"] for s in SOURCES)


@pytest.mark.asyncio
async def test_repeat_prepare_never_expands_window_or_limits() -> None:
    db = DB()
    await prepare(db, apply=True)
    before = copy.deepcopy(db.collection.doc)
    await control_pilot(
        db, "prepare", now=NOW + timedelta(minutes=10), execution_id=EXECUTION, apply=True
    )
    assert db.collection.doc == before


@pytest.mark.asyncio
async def test_exhausted_original_quota_not_raised() -> None:
    p = plan()
    p["budget"]["orders"]["physical_attempts"] = 13
    db = DB(p)
    receipt = await prepare(db, apply=True)
    assert db.collection.doc["budget"]["orders"]["physical_attempts"] == 13
    assert receipt["initial_remaining"]["orders"] == 0


@pytest.mark.asyncio
async def test_current_day_maintenance_caps_remaining_without_reset() -> None:
    p = plan()
    p.update(
        incremental_day=NOW.date().isoformat(),
        incremental_consumed=100,
        incremental_source_consumed={s: i * 20 for i, s in enumerate(SOURCES)},
    )
    db = DB(p)
    await prepare(db, apply=True)
    assert db.collection.doc["incremental_policy"] == {
        "max_daily_total": 600,
        "max_daily_source": 300,
    }
    assert db.collection.doc["incremental_consumed"] == 100
    assert db.collection.doc["incremental_source_consumed"] == p["incremental_source_consumed"]


@pytest.mark.asyncio
async def test_midnight_bounds_same_utc_day() -> None:
    db = DB()
    now = NOW.replace(hour=23, minute=45)
    await control_pilot(db, "prepare", now=now, execution_id=EXECUTION, apply=True)
    assert db.collection.doc["execution_until"] == now.replace(hour=0, minute=0) + timedelta(days=1)


@pytest.mark.asyncio
async def test_pause_updates_only_state_even_with_active_lease() -> None:
    p = plan()
    p["lease_until"] = NOW + timedelta(minutes=5)
    db = DB(p)
    await control_pilot(db, "pause", now=NOW, apply=True)
    expected = copy.deepcopy(p)
    expected["state"] = "paused"
    assert db.collection.doc == expected
    assert db.collection.writes[0][1] == {"$set": {"state": "paused"}}


@pytest.mark.asyncio
async def test_cas_drift_fails_without_retry_or_takeover() -> None:
    db = DB()
    lease = db.collection.doc["lease_token"]
    db.collection.race = True
    with pytest.raises(PilotControlError, match="plan_changed"):
        await prepare(db, apply=True)
    assert len(db.collection.writes) == 1
    assert db.collection.doc["state"] == "active"
    assert db.collection.doc["lease_token"] == lease


@pytest.mark.asyncio
async def test_activate_requires_pinned_applied_receipt_and_runtime_confirmation() -> None:
    db = DB()
    receipt = await prepare(db, apply=True)
    raw = receipt_bytes(receipt)
    before = copy.deepcopy(db.collection.doc)
    with pytest.raises(PilotControlError, match="runtime_controls_unverified"):
        await control_pilot(
            db,
            "activate",
            now=NOW,
            prepared_receipt=raw,
            prepared_receipt_sha256=receipt_sha256(raw),
            apply=True,
        )
    assert db.collection.doc == before
    await control_pilot(
        db,
        "activate",
        now=NOW,
        prepared_receipt=raw,
        prepared_receipt_sha256=receipt_sha256(raw),
        runtime_controls_verified=True,
        apply=True,
    )
    expected = copy.deepcopy(before)
    expected["state"] = "active"
    assert db.collection.doc == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", ["receipt_hash", "dry_receipt", "drift", "expired", "active_lease"]
)
async def test_activate_guards(failure: str) -> None:
    db = DB()
    receipt = await prepare(db, apply=failure != "dry_receipt")
    raw = receipt_bytes(receipt)
    pin = receipt_sha256(raw)
    now = NOW
    if failure == "receipt_hash":
        pin = "0" * 64
    elif failure == "drift":
        db.collection.doc["checkpoint_fixture"]["added"] = True
    elif failure == "expired":
        now += timedelta(minutes=90)
    elif failure == "active_lease":
        db.collection.doc["lease_until"] = NOW + timedelta(minutes=5)
    writes = len(db.collection.writes)
    with pytest.raises(PilotControlError):
        await control_pilot(
            db,
            "activate",
            now=now,
            prepared_receipt=raw,
            prepared_receipt_sha256=pin,
            runtime_controls_verified=True,
            apply=True,
        )
    assert len(db.collection.writes) == writes


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("seller_id", "1"),
        ("policy_version", "legacy"),
        ("authority", {"kind": "operator"}),
        ("eligible", False),
    ],
)
async def test_identity_and_authority_guard(field: str, value: Any) -> None:
    p = plan()
    p[field] = value
    db = DB(p)
    with pytest.raises(PilotControlError):
        await prepare(db, apply=True)
    assert not db.collection.writes


def test_cli_default_dryrun_and_no_credential_arguments() -> None:
    args = build_parser().parse_args(["prepare", "--execution-id", EXECUTION])
    assert args.apply is False
    assert not hasattr(args, "mongo_uri")
    assert json.loads(receipt_bytes({"safe": True})) == {"safe": True}


@pytest.mark.asyncio
async def test_legacy_plan_without_policy_version_is_not_upgraded() -> None:
    # The legitimate OAuth admission flow, not this operator, owns conversion.
    p = plan()
    del p["policy_version"]
    db = DB(p)
    with pytest.raises(PilotControlError, match="policy_identity_mismatch"):
        await prepare(db, apply=True)
    assert db.collection.doc == p
    assert db.collection.writes == []


@pytest.mark.asyncio
async def test_previous_day_counters_preserved_and_not_advertised_as_available() -> None:
    p = plan()
    p.update(
        incremental_day=(NOW - timedelta(days=1)).date().isoformat(),
        incremental_consumed=999,
        incremental_source_consumed={s: 400 for s in SOURCES},
    )
    db = DB(p)
    receipt = await prepare(db, apply=True)
    assert receipt["daily_rollover_pending"] is True
    assert receipt["maintenance_remaining"] is None
    assert receipt["maintenance_source_remaining"] is None
    assert receipt["natural_rollover_limits"] == {"total": 500, "per_source": 300}
    for field in ("incremental_day", "incremental_consumed", "incremental_source_consumed"):
        assert db.collection.doc[field] == p[field]


def test_cli_apply_requires_confirmation_before_runtime_access(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("MONGO_URI", raising=False)
    monkeypatch.delenv("MONGO_DB", raising=False)
    assert main(["prepare", "--execution-id", EXECUTION, "--apply"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["code"] == "explicit_apply_confirmation_and_receipt_required"
    assert result["no_retry"] is True


def test_cli_invalid_arguments_redacted(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["prepare", "--unknown-credential", "sensitive-fixture"]) == 2
    output = capsys.readouterr()
    assert output.err == ""
    assert "sensitive-fixture" not in output.out
    assert json.loads(output.out)["code"] == "invalid_arguments"
