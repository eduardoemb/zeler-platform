"""Five-hour explicit opt-in and a genuine pre-authorization PAUSED witness, offline."""

from __future__ import annotations

import copy
import importlib.util
import json
import socket
import sys
from datetime import UTC, datetime, timedelta
from importlib.machinery import ModuleSpec, SourceFileLoader
from pathlib import Path
from typing import Any, cast

import pytest
from infra.operations import zelerdata_history_pilot as ops

spec = cast(
    ModuleSpec,
    importlib.util.spec_from_file_location(
        "_five_hour_chain_fixtures",
        Path(__file__).with_name("test_zelerdata_history_pilot_extension_chain.py"),
    ),
)
f = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = f
cast(SourceFileLoader, spec.loader).exec_module(f)
# Synthetic fixtures use the reception/ceiling instants to test arithmetic only;
# these dictionaries are NOT the human's real authorization artifact or pins.
RECEIVED = datetime(2026, 10, 6, 15, 32, 58, tzinfo=UTC)
APPROVED = RECEIVED + timedelta(seconds=18000)
NOW = RECEIVED + timedelta(minutes=25)
HISTORICAL = RECEIVED - timedelta(minutes=10)
FRESH = RECEIVED + timedelta(minutes=10)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("five hour tests forbid sockets")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


async def setup(fresh: bool = False) -> tuple[Any, dict[str, Any], dict[str, Any], bytes]:
    db, args, authority, parent = await f.setup()
    historical = f.f.receipt("pause", db, observed=HISTORICAL)
    current = f.f.receipt("pause", db, observed=FRESH if fresh else HISTORICAL)
    args["paused_receipt"] = current
    args["paused_receipt_sha256"] = ops.receipt_sha256(current)
    baseline = json.loads(f.f.receipt("pause", db, observed=HISTORICAL - timedelta(seconds=1)))
    consumption = json.loads(args["consumption_receipt"])
    consumption["reader"]["receipt"] = baseline
    consumption["reader"]["receipt_sha256"] = ops.receipt_sha256(ops.receipt_bytes(baseline))
    consumption["ended_utc"] = (HISTORICAL - timedelta(milliseconds=500)).isoformat()
    f.pinned(args, "consumption_receipt", consumption)
    if fresh:
        args["pre_authorization_paused_receipt"] = historical
        args["pre_authorization_paused_receipt_sha256"] = ops.receipt_sha256(historical)
    authority.update(
        authorized_at_utc=RECEIVED.isoformat(),
        approved_until_utc=APPROVED.isoformat(),
        max_additional_seconds=18000,
        five_hour_extension_authorized=True,
        paused_receipt_sha256=args["paused_receipt_sha256"],
        user_evidence="SYNTHETIC OFFLINE AUTHORITY FIXTURE, NOT PRODUCTION APPROVAL",
    )
    return db, args, authority, historical


async def extend(
    db: Any, args: dict[str, Any], authority: dict[str, Any], apply: bool = False
) -> dict[str, Any]:
    raw = ops.receipt_bytes(authority)
    return await ops.control_pilot(
        db,
        "extend-paused",
        now=NOW,
        apply=apply,
        **args,
        extension_authority=raw,
        extension_authority_sha256=ops.receipt_sha256(raw),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("fresh", [False, True])
@pytest.mark.parametrize("apply", [False, True])
async def test_explicit_five_hour_deadline_only_preserves_every_counter_and_identity(
    fresh: bool, apply: bool
) -> None:
    db, args, authority, historical = await setup(fresh)
    before = copy.deepcopy(db.collection.doc)
    result = await extend(db, args, authority, apply)
    assert result["extension_duration_ceiling_seconds"] == 18000
    assert result["execution_until_utc"] == APPROVED.isoformat()
    assert result["state"] == "paused" and result["applied"] is apply
    assert db.collection.doc == (
        {**before, "execution_until": APPROVED.replace(tzinfo=None)} if apply else before
    )
    assert (
        db.collection.doc["execution_consumed"],
        db.collection.doc["execution_sent"],
        db.collection.doc["incremental_consumed"],
    ) == (81, 79, 24)
    if fresh:
        assert result["pre_authorization_paused_receipt_sha256"] == ops.receipt_sha256(historical)
    if apply:
        assert db.collection.writes[-1][1] == {"$set": {"execution_until": APPROVED}}


async def applied_fixture(fresh: bool = False) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    db, args, authority, historical = await setup(fresh)
    before = copy.deepcopy(db.collection.doc)
    db.collection.doc["execution_until"] = APPROVED.replace(tzinfo=None)
    result = {
        "action": "extend-paused",
        "applied": True,
        "seller_id": ops.SELLER,
        "policy_version": f.original_policy(),
        "execution_id": f.f.EXECUTION,
        "state": "paused",
        "observed_utc": NOW.isoformat(),
        "prepared_receipt_sha256": args["prepared_receipt_sha256"],
        "paused_receipt_sha256": args["paused_receipt_sha256"],
        "previous_extension_receipt_sha256": args["previous_extension_receipt_sha256"],
        "original_paused_receipt_sha256": args["original_paused_receipt_sha256"],
        "previous_plan_sha256": ops._plan_hash(before),
        "resulting_plan_sha256": ops._plan_hash(db.collection.doc),
        "previous_until_utc": f.f.NEW_END.isoformat(),
        "execution_until_utc": APPROVED.isoformat(),
        "extension_authorized_at_utc": RECEIVED.isoformat(),
        "extension_authority_sha256": ops.receipt_sha256(ops.receipt_bytes(authority)),
        "extension_max_additional_seconds": 18000,
        "extension_duration_ceiling_seconds": 18000,
        **ops._summary(db.collection.doc, NOW),
    }
    if fresh:
        result["pre_authorization_paused_receipt_sha256"] = ops.receipt_sha256(historical)
    f.pinned(args, "extension_receipt", result)
    return db, args, result


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["pre", "fresh", "post_fence"])
async def test_latest_five_hour_resume_and_post_fence_repause_use_pinned_witness(mode: str) -> None:
    db, args, result = await applied_fixture(mode != "pre")
    if mode == "post_fence":
        step = args["paused_receipt"]
        step_pin = args["paused_receipt_sha256"]
        db.collection.doc["history_readmission_revision"] = 1
        current = f.f.receipt("pause", db, observed=NOW + timedelta(seconds=2))
        args["paused_receipt"] = current
        args["paused_receipt_sha256"] = ops.receipt_sha256(current)
        args["extension_paused_receipt"] = step
        args["extension_paused_receipt_sha256"] = step_pin
        consumption = json.loads(args["consumption_receipt"])
        baseline = json.loads(f.f.receipt("pause", db, observed=NOW + timedelta(seconds=1)))
        consumption["reader"]["receipt"] = baseline
        consumption["reader"]["receipt_sha256"] = ops.receipt_sha256(ops.receipt_bytes(baseline))
        consumption["ended_utc"] = (NOW + timedelta(milliseconds=1500)).isoformat()
        f.pinned(args, "consumption_receipt", consumption)
    before = copy.deepcopy(db.collection.doc)
    resumed = await ops.control_pilot(
        db, "resume", now=NOW + timedelta(seconds=3), apply=True, **args
    )
    assert resumed["state"] == "active" and db.collection.doc == {**before, "state": "active"}
    assert db.collection.doc["execution_until"] == APPROVED.replace(tzinfo=None)


@pytest.mark.asyncio
async def test_legacy_and_historical_parent_remain_7200_without_new_ceiling() -> None:
    db, args, authority, parent = await f.setup()
    raw = ops.receipt_bytes(authority)
    result = await ops.control_pilot(
        db,
        "extend-paused",
        now=f.NOW,
        apply=False,
        **args,
        extension_authority=raw,
        extension_authority_sha256=ops.receipt_sha256(raw),
    )
    assert "extension_duration_ceiling_seconds" not in result
    parent["extension_max_additional_seconds"] = 18000
    parent["extension_duration_ceiling_seconds"] = 18000
    f.pinned(args, "previous_extension_receipt", parent)
    authority["previous_extension_receipt_sha256"] = args["previous_extension_receipt_sha256"]
    raw = ops.receipt_bytes(authority)
    with pytest.raises(ops.PilotControlError):
        await ops.control_pilot(
            db,
            "extend-paused",
            now=f.NOW,
            **args,
            extension_authority=raw,
            extension_authority_sha256=ops.receipt_sha256(raw),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "guard",
    [
        "absent",
        "false",
        "flag_int",
        "duration_bool",
        "too_long",
        "deadline_plus_one",
        "overday",
        "witness_missing",
        "witness_drift",
        "witness_future",
        "witness_pin",
    ],
)
async def test_optin_duration_day_and_post_approval_witness_guards(guard: str) -> None:
    witness = guard.startswith("witness_")
    db, args, authority, historical = await setup(witness)
    if guard == "absent":
        authority.pop("five_hour_extension_authorized")
    elif guard == "false":
        authority["five_hour_extension_authorized"] = False
    elif guard == "flag_int":
        authority["five_hour_extension_authorized"] = 1
    elif guard == "duration_bool":
        authority["max_additional_seconds"] = True
    elif guard == "too_long":
        authority["max_additional_seconds"] = 18001
    elif guard == "deadline_plus_one":
        authority["approved_until_utc"] = (APPROVED + timedelta(seconds=1)).isoformat()
    elif guard == "overday":
        authority["approved_until_utc"] = datetime(2026, 10, 7, 0, tzinfo=UTC).isoformat()
    elif guard == "witness_missing":
        args.pop("pre_authorization_paused_receipt")
        args.pop("pre_authorization_paused_receipt_sha256")
    elif guard == "witness_pin":
        args["pre_authorization_paused_receipt_sha256"] = "0" * 64
    else:
        prior = json.loads(historical)
        if guard == "witness_drift":
            prior["resulting_plan_sha256"] = "0" * 64
        else:
            prior["observed_utc"] = (RECEIVED + timedelta(seconds=1)).isoformat()
        f.pinned(args, "pre_authorization_paused_receipt", prior)
    before = copy.deepcopy(db.collection.doc)
    with pytest.raises(ops.PilotControlError):
        await extend(db, args, authority, True)
    assert db.collection.doc == before and len(db.collection.writes) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "guard", ["ceiling_missing", "ceiling_bool", "ceiling_large", "ceiling_legacy"]
)
async def test_forged_latest_receipt_cannot_widen_resume(guard: str) -> None:
    db, args, result = await applied_fixture()
    if guard == "ceiling_missing":
        result.pop("extension_duration_ceiling_seconds")
    else:
        result["extension_duration_ceiling_seconds"] = {
            "ceiling_bool": True,
            "ceiling_large": 18001,
            "ceiling_legacy": 7200,
        }[guard]
    f.pinned(args, "extension_receipt", result)
    before = copy.deepcopy(db.collection.doc)
    with pytest.raises(ops.PilotControlError):
        await ops.control_pilot(db, "resume", now=NOW, apply=True, **args)
    assert db.collection.doc == before


@pytest.mark.asyncio
async def test_five_hour_authority_never_refunds_current_sent_or_daily_credit() -> None:
    db, args, authority, historical = await setup()
    db.collection.doc["execution_sent"] = 78
    pause = f.f.receipt("pause", db, observed=HISTORICAL)
    args["paused_receipt"] = pause
    args["paused_receipt_sha256"] = ops.receipt_sha256(pause)
    authority["paused_receipt_sha256"] = args["paused_receipt_sha256"]
    consumption = json.loads(args["consumption_receipt"])
    consumption["reader"]["receipt"]["resulting_plan_sha256"] = ops._plan_hash(db.collection.doc)
    consumption["reader"]["receipt_sha256"] = ops.receipt_sha256(
        ops.receipt_bytes(consumption["reader"]["receipt"])
    )
    f.pinned(args, "consumption_receipt", consumption)
    before = copy.deepcopy(db.collection.doc)
    with pytest.raises(ops.PilotControlError):
        await extend(db, args, authority, True)
    assert db.collection.doc == before


@pytest.mark.asyncio
@pytest.mark.parametrize("binding", ["missing", "mismatch"])
async def test_latest_late_pause_receipt_requires_its_own_witness_pin(binding: str) -> None:
    db, args, result = await applied_fixture(True)
    if binding == "missing":
        result.pop("pre_authorization_paused_receipt_sha256")
    else:
        result["pre_authorization_paused_receipt_sha256"] = "0" * 64
    f.pinned(args, "extension_receipt", result)
    before = copy.deepcopy(db.collection.doc)
    with pytest.raises(ops.PilotControlError):
        await ops.control_pilot(db, "resume", now=NOW, apply=True, **args)
    assert db.collection.doc == before
