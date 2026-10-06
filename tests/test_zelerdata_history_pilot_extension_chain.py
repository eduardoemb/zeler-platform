"""Prospective explicit-authority chain: no production approval, new grant or prepare."""

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

from zeler_platform_core.history_onboarding import POLICY_VERSION

spec = cast(
    ModuleSpec,
    importlib.util.spec_from_file_location(
        "_chain_fixtures", Path(__file__).with_name("test_zelerdata_history_pilot_extension.py")
    ),
)
f = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = f
cast(SourceFileLoader, spec.loader).exec_module(f)
RECEIVED = datetime(
    2026, 10, 6, 10, tzinfo=UTC
)  # Synthetic future evidence, NOT actual permission.
NOW = RECEIVED + timedelta(minutes=1)
APPROVED = RECEIVED + timedelta(hours=2)
STOPPED = RECEIVED - timedelta(minutes=2)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("chain tests forbid sockets")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


async def setup() -> tuple[Any, dict[str, Any], dict[str, Any], dict[str, Any]]:
    db = f.DB()
    original, _ = f.inputs(db)
    previous = await f.extend(db)
    previous_raw = ops.receipt_bytes(previous)
    db.collection.doc["execution_consumed"] = 81
    db.collection.doc["execution_sent"] = 79
    db.collection.doc["total_consumed"] = 57
    db.collection.doc["budget"]["questions"]["consumed"] = 4
    db.collection.doc["incremental_consumed"] = 24
    db.collection.doc["incremental_source_consumed"].update(orders=13, questions=3, messages=8)
    pause = f.receipt("pause", db, observed=STOPPED)
    baseline = json.loads(f.receipt("pause", db, observed=STOPPED - timedelta(seconds=1)))
    consumption = {
        "status": "pass",
        "ended_utc": (STOPPED - timedelta(milliseconds=500)).isoformat(),
        "reader": {
            "status": "pass",
            "cleanup": "closed",
            "no_refund_or_reset": True,
            "charged": 81,
            "sent": 79,
            "maintenance": 24,
            "receipt": baseline,
            "receipt_sha256": ops.receipt_sha256(ops.receipt_bytes(baseline)),
        },
    }
    consumption_raw = ops.receipt_bytes(consumption)
    args = {
        **original,
        "paused_receipt": pause,
        "paused_receipt_sha256": ops.receipt_sha256(pause),
        "original_paused_receipt": original["paused_receipt"],
        "original_paused_receipt_sha256": original["paused_receipt_sha256"],
        "previous_extension_receipt": previous_raw,
        "previous_extension_receipt_sha256": ops.receipt_sha256(previous_raw),
        "consumption_receipt": consumption_raw,
        "consumption_receipt_sha256": ops.receipt_sha256(consumption_raw),
    }
    authority = {
        "action": "authorize_extension",
        "authorization_received": True,
        "seller_id": ops.SELLER,
        "policy_version": original_policy(),
        "execution_id": f.EXECUTION,
        "authorized_at_utc": RECEIVED.isoformat(),
        "original_until_utc": f.NEW_END.isoformat(),
        "approved_until_utc": APPROVED.isoformat(),
        "max_additional_seconds": 7200,
        "prepared_receipt_sha256": args["prepared_receipt_sha256"],
        "paused_receipt_sha256": args["paused_receipt_sha256"],
        "previous_extension_receipt_sha256": args["previous_extension_receipt_sha256"],
        "no_new_credit": True,
        "full_excluded": True,
        "user_evidence": "SYNTHETIC FUTURE APPROVAL FOR OFFLINE TEST ONLY",
    }
    return db, args, authority, previous


def original_policy() -> str:
    return POLICY_VERSION


def pinned(args: dict[str, Any], key: str, value: dict[str, Any]) -> None:
    args[key] = ops.receipt_bytes(value)
    args[key + "_sha256"] = ops.receipt_sha256(args[key])


async def extend(
    db: Any, args: dict[str, Any], authority: dict[str, Any], *, apply: bool = False
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
async def test_second_extension_without_parent_is_rejected_not_fake_first_extension() -> None:
    db, args, authority, previous = await setup()
    args.pop("previous_extension_receipt")
    args.pop("previous_extension_receipt_sha256")
    before = copy.deepcopy(db.collection.doc)
    with pytest.raises(ops.PilotControlError):
        await extend(db, args, authority)
    assert db.collection.doc == before


@pytest.mark.asyncio
@pytest.mark.parametrize("apply", [False, True])
async def test_two_applied_extensions_form_chain_and_second_changes_deadline_only(
    apply: bool,
) -> None:
    db, args, authority, previous = await setup()
    before = copy.deepcopy(db.collection.doc)
    result = await extend(db, args, authority, apply=apply)
    assert result["applied"] is apply and result["state"] == "paused"
    assert result["previous_extension_receipt_sha256"] == args["previous_extension_receipt_sha256"]
    assert result["prepared_receipt_sha256"] == args["prepared_receipt_sha256"]
    assert result["previous_until_utc"] == f.NEW_END.isoformat()
    assert result["previous_plan_sha256"] == ops._plan_hash(before)
    assert result["original_paused_receipt_sha256"] == args["original_paused_receipt_sha256"]
    assert previous["previous_until_utc"] == f.OLD_END.isoformat()
    assert db.collection.doc == (
        {**before, "execution_until": APPROVED.replace(tzinfo=None)} if apply else before
    )
    if apply:
        assert db.collection.writes[-1][1] == {"$set": {"execution_until": APPROVED}}
    assert (
        db.collection.doc["execution_consumed"] == 81
        and db.collection.doc["execution_sent"] == 79
        and db.collection.doc["incremental_consumed"] == 24
    )
    if apply:
        # First resume of this new chained extension uses its genuine pre-apply
        # pause plus the deadline-only result hash bridge, not a fabricated pause.
        resumed = await ops.control_pilot(
            db,
            "resume",
            now=NOW,
            apply=True,
            **args,
            extension_receipt=ops.receipt_bytes(result),
            extension_receipt_sha256=ops.receipt_sha256(ops.receipt_bytes(result)),
        )
        assert resumed["state"] == "active"
        assert db.collection.doc["execution_until"] == APPROVED.replace(tzinfo=None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "guard",
    [
        "previous_pin",
        "previous_unapplied",
        "previous_clock",
        "previous_eid",
        "original_pause_pin",
        "current_pause_pin",
        "not_received",
        "duration_bool",
        "duration_large",
        "future_received",
        "overday",
        "new_eid",
        "scope_full",
        "initial_refund",
        "daily_refund",
        "sent_refund",
        "source_refund",
        "consumption_pin",
        "live_lease",
        "cas_drift",
    ],
)
async def test_chain_parent_authority_clock_credit_scope_and_cas_guards(guard: str) -> None:
    db, args, authority, previous = await setup()
    if guard == "previous_pin":
        args["previous_extension_receipt_sha256"] = "0" * 64
    elif guard == "previous_unapplied":
        previous["applied"] = False
        pinned(args, "previous_extension_receipt", previous)
    elif guard == "previous_clock":
        previous["observed_utc"] = (NOW + timedelta(seconds=1)).isoformat()
        pinned(args, "previous_extension_receipt", previous)
    elif guard == "previous_eid":
        previous["execution_id"] = "b" * 32
        pinned(args, "previous_extension_receipt", previous)
    elif guard == "original_pause_pin":
        args["original_paused_receipt_sha256"] = "0" * 64
    elif guard == "current_pause_pin":
        args["paused_receipt_sha256"] = "0" * 64
    elif guard == "not_received":
        authority["authorization_received"] = False
    elif guard == "duration_bool":
        authority["max_additional_seconds"] = True
    elif guard == "duration_large":
        authority["max_additional_seconds"] = 7201
    elif guard == "future_received":
        authority["authorized_at_utc"] = (NOW + timedelta(seconds=1)).isoformat()
    elif guard == "overday":
        authority["approved_until_utc"] = datetime(2026, 10, 7, 0, tzinfo=UTC).isoformat()
    elif guard == "new_eid":
        authority["execution_id"] = "b" * 32
    elif guard == "scope_full":
        db.collection.doc["sources"].append("full_withdrawals")
    elif guard == "initial_refund":
        db.collection.doc["budget"]["claims_returns"]["consumed"] = 48
    elif guard == "daily_refund":
        db.collection.doc["incremental_consumed"] = 0
    elif guard == "sent_refund":
        db.collection.doc["execution_sent"] = 78
    elif guard == "source_refund":
        db.collection.doc["incremental_source_consumed"]["orders"] = 0
    elif guard == "consumption_pin":
        args["consumption_receipt_sha256"] = "0" * 64
    elif guard == "live_lease":
        db.collection.doc["lease_until"] = (NOW + timedelta(minutes=1)).replace(tzinfo=None)
    else:
        db.collection.drift = True
    if guard in {
        "scope_full",
        "initial_refund",
        "daily_refund",
        "sent_refund",
        "source_refund",
        "live_lease",
    }:
        pause = f.receipt("pause", db, observed=STOPPED)
        args["paused_receipt"] = pause
        args["paused_receipt_sha256"] = ops.receipt_sha256(pause)
        authority["paused_receipt_sha256"] = args["paused_receipt_sha256"]
        consumption = json.loads(args["consumption_receipt"])
        consumption["reader"]["receipt"]["resulting_plan_sha256"] = ops._plan_hash(
            db.collection.doc
        )
        consumption["reader"]["receipt_sha256"] = ops.receipt_sha256(
            ops.receipt_bytes(consumption["reader"]["receipt"])
        )
        pinned(args, "consumption_receipt", consumption)
    if guard.startswith("previous_"):
        authority["previous_extension_receipt_sha256"] = args["previous_extension_receipt_sha256"]
    before = copy.deepcopy(db.collection.doc)
    with pytest.raises(ops.PilotControlError):
        await extend(db, args, authority, apply=True)
    if guard == "cas_drift":
        assert (
            db.collection.doc["execution_consumed"] == 82
            and db.collection.doc["execution_until"] == before["execution_until"]
        )
    else:
        assert db.collection.doc == before and len(db.collection.writes) == 1


def test_chain_cli_inputs_are_additive_and_dry_run_by_default() -> None:
    args = ops.build_parser().parse_args(
        [
            "extend-paused",
            "--previous-extension-receipt-in",
            "parent-applied.json",
            "--previous-extension-receipt-sha256",
            "a" * 64,
        ]
    )
    assert args.apply is False and str(args.previous_extension_receipt_in) == "parent-applied.json"
    assert args.previous_extension_receipt_sha256 == "a" * 64


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper", [False, True])
async def test_chain_resume_after_genuine_metadata_readmission_pause(tamper: bool) -> None:
    db, args, authority, _ = await setup()
    latest = await extend(db, args, authority, apply=True)
    step_pause, step_pin = args["paused_receipt"], args["paused_receipt_sha256"]
    # Actual readmission adds a metadata fence, not a new credit or expiry.
    db.collection.doc["history_readmission_revision"] = 1
    stopped_at = NOW + timedelta(seconds=2)
    args["paused_receipt"] = f.receipt("pause", db, observed=stopped_at)
    args["paused_receipt_sha256"] = ops.receipt_sha256(args["paused_receipt"])
    baseline = json.loads(f.receipt("pause", db, observed=NOW + timedelta(seconds=1)))
    consumption = {
        "status": "pass",
        "ended_utc": (NOW + timedelta(seconds=1)).isoformat(),
        "reader": {
            "status": "pass",
            "cleanup": "closed",
            "no_refund_or_reset": True,
            "charged": 81,
            "sent": 79,
            "maintenance": 24,
            "receipt": baseline,
            "receipt_sha256": ops.receipt_sha256(ops.receipt_bytes(baseline)),
        },
    }
    pinned(args, "consumption_receipt", consumption)
    before = copy.deepcopy(db.collection.doc)
    kwargs = {
        **args,
        "extension_receipt": ops.receipt_bytes(latest),
        "extension_receipt_sha256": ops.receipt_sha256(ops.receipt_bytes(latest)),
        "extension_paused_receipt": step_pause,
        "extension_paused_receipt_sha256": "0" * 64 if tamper else step_pin,
    }
    if tamper:
        with pytest.raises(ops.PilotControlError):
            await ops.control_pilot(db, "resume", now=stopped_at, apply=True, **kwargs)
        assert db.collection.doc == before
    else:
        result = await ops.control_pilot(db, "resume", now=stopped_at, apply=True, **kwargs)
        assert result["state"] == "active"
        assert db.collection.doc == {**before, "state": "active"}
