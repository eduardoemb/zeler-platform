"""Pinned extension remains usable after a genuine later canonical pause, never new credit."""

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
        "_extension_repause_fixtures",
        Path(__file__).with_name("test_zelerdata_history_pilot_extension.py"),
    ),
)
fixture = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = fixture
cast(SourceFileLoader, spec.loader).exec_module(fixture)
STOPPED = datetime(2026, 10, 6, 7, 23, tzinfo=UTC)
NOW = STOPPED + timedelta(minutes=2)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("repause tests forbid sockets")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


async def setup() -> tuple[Any, dict[str, Any], dict[str, Any]]:
    db = fixture.DB()
    original, _ = fixture.inputs(db)
    extension = await fixture.extend(db)
    raw = ops.receipt_bytes(extension)
    db.collection.doc["execution_consumed"] = 75
    db.collection.doc["execution_sent"] = 73
    db.collection.doc["incremental_consumed"] = 19
    db.collection.doc["incremental_source_consumed"]["messages"] = 8
    db.collection.doc["execution_charged"][fixture.EXECUTION]["messages"]["maintenance"] = 8
    current = fixture.receipt("pause", db, observed=STOPPED)
    args = {
        **original,
        "paused_receipt": current,
        "paused_receipt_sha256": ops.receipt_sha256(current),
        "original_paused_receipt": original["paused_receipt"],
        "original_paused_receipt_sha256": original["paused_receipt_sha256"],
        "extension_receipt": raw,
        "extension_receipt_sha256": ops.receipt_sha256(raw),
    }
    baseline = json.loads(fixture.receipt("pause", db, observed=STOPPED - timedelta(seconds=1)))
    consumption = {
        "status": "pass",
        "ended_utc": (STOPPED - timedelta(milliseconds=500)).isoformat(),
        "reader": {
            "status": "pass",
            "no_refund_or_reset": True,
            "same_until": True,
            "charged": 75,
            "sent": 73,
            "maintenance": 19,
            "cleanup": "closed",
            "receipt": baseline,
            "receipt_sha256": ops.receipt_sha256(ops.receipt_bytes(baseline)),
        },
    }
    args["consumption_receipt"] = ops.receipt_bytes(consumption)
    args["consumption_receipt_sha256"] = ops.receipt_sha256(args["consumption_receipt"])
    return db, args, extension


def repin(args: dict[str, Any], key: str, change: dict[str, Any]) -> None:
    value = json.loads(args[key])
    value.update(change)
    args[key] = ops.receipt_bytes(value)
    args[key + "_sha256"] = ops.receipt_sha256(args[key])


@pytest.mark.asyncio
async def test_parentless_repause_cannot_reuse_original_extension_as_current_pause() -> None:
    db, args, _ = await setup()
    args.pop("original_paused_receipt")
    args.pop("original_paused_receipt_sha256")
    args.pop("consumption_receipt")
    args.pop("consumption_receipt_sha256")
    with pytest.raises(ops.PilotControlError):
        await ops.control_pilot(db, "resume", now=NOW, apply=False, **args)


@pytest.mark.asyncio
@pytest.mark.parametrize("apply", [False, True])
async def test_parent_pause_and_current_pause_resume_state_only_without_rewriting_extension(
    apply: bool,
) -> None:
    db, args, extension = await setup()
    before = copy.deepcopy(db.collection.doc)
    result = await ops.control_pilot(db, "resume", now=NOW, apply=apply, **args)
    assert result["applied"] is apply and result["state"] == "active"
    assert db.collection.doc == ({**before, "state": "active"} if apply else before)
    assert db.collection.doc["execution_consumed"] == 75
    assert db.collection.doc["execution_sent"] == 73
    assert db.collection.doc["incremental_consumed"] == 19
    assert db.collection.doc["execution_until"] == fixture.NEW_END.replace(tzinfo=None)
    assert db.collection.doc["execution_id"] == fixture.EXECUTION
    assert extension["initial_remaining"] == ops._summary(before, NOW)["initial_remaining"]
    if apply:
        assert db.collection.writes[-1][1] == {"$set": {"state": "active"}}
    assert "execution_consumed" not in extension and "execution_sent" not in extension


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "guard",
    [
        "parent_pin",
        "parent_unapplied",
        "parent_identity",
        "current_snapshot",
        "current_pin",
        "extension_unapplied",
        "extension_parent",
        "extension_future",
        "pause_before_extension",
        "initial_refund",
        "daily_refund",
        "source_refund",
        "boolean_credit",
        "active_lease",
        "consumption_pin",
        "consumption_missing",
        "consumption_invalid",
        "consumption_snapshot",
        "sent_decrease",
        "charged_decrease",
        "consumption_reader_fail",
        "consumption_refund",
        "consumption_inner_pin",
        "consumption_future",
    ],
)
async def test_repause_lineage_and_no_new_remaining_credit_fail_closed(guard: str) -> None:
    db, args, _ = await setup()
    if guard == "parent_pin":
        args["original_paused_receipt_sha256"] = "0" * 64
    elif guard == "parent_unapplied":
        repin(args, "original_paused_receipt", {"applied": False})
    elif guard == "parent_identity":
        repin(args, "original_paused_receipt", {"execution_id": "b" * 32})
    elif guard == "current_snapshot":
        db.collection.doc["progress"]["unrelated_drift"] = 1
    elif guard == "current_pin":
        args["paused_receipt_sha256"] = "0" * 64
    elif guard == "extension_unapplied":
        repin(args, "extension_receipt", {"applied": False})
    elif guard == "extension_parent":
        repin(args, "extension_receipt", {"previous_plan_sha256": "0" * 64})
    elif guard == "extension_future":
        repin(args, "extension_receipt", {"observed_utc": (NOW + timedelta(seconds=1)).isoformat()})
    elif guard == "pause_before_extension":
        repin(
            args,
            "paused_receipt",
            {"observed_utc": (fixture.AUTHORIZED - timedelta(seconds=1)).isoformat()},
        )
    elif guard == "initial_refund":
        db.collection.doc["budget"]["claims_returns"]["consumed"] = 48
    elif guard == "daily_refund":
        db.collection.doc["incremental_consumed"] = 0
    elif guard == "source_refund":
        db.collection.doc["incremental_source_consumed"]["orders"] = 0
    elif guard == "boolean_credit":
        db.collection.doc["incremental_consumed"] = True
    elif guard == "active_lease":
        db.collection.doc["lease_until"] = (NOW + timedelta(minutes=1)).replace(tzinfo=None)
    elif guard == "consumption_pin":
        args["consumption_receipt_sha256"] = "0" * 64
    elif guard == "consumption_missing":
        args["consumption_receipt"] = None
    elif guard == "consumption_invalid":
        repin(args, "consumption_receipt", {"status": "stop"})
    elif guard == "consumption_snapshot":
        consumption = json.loads(args["consumption_receipt"])
        consumption["reader"]["receipt"]["resulting_plan_sha256"] = "0" * 64
        consumption["reader"]["receipt_sha256"] = ops.receipt_sha256(
            ops.receipt_bytes(consumption["reader"]["receipt"])
        )
        args["consumption_receipt"] = ops.receipt_bytes(consumption)
        args["consumption_receipt_sha256"] = ops.receipt_sha256(args["consumption_receipt"])
    elif guard == "sent_decrease":
        db.collection.doc["execution_sent"] = 72
    elif guard == "charged_decrease":
        db.collection.doc["execution_consumed"] = 74
    else:
        consumption = json.loads(args["consumption_receipt"])
        if guard == "consumption_reader_fail":
            consumption["reader"]["status"] = "stop"
        elif guard == "consumption_refund":
            consumption["reader"]["no_refund_or_reset"] = False
        elif guard == "consumption_inner_pin":
            consumption["reader"]["receipt_sha256"] = "0" * 64
        else:
            consumption["reader"]["receipt"]["observed_utc"] = (
                NOW + timedelta(seconds=1)
            ).isoformat()
            consumption["reader"]["receipt_sha256"] = ops.receipt_sha256(
                ops.receipt_bytes(consumption["reader"]["receipt"])
            )
        args["consumption_receipt"] = ops.receipt_bytes(consumption)
        args["consumption_receipt_sha256"] = ops.receipt_sha256(args["consumption_receipt"])
    # A genuine newly pinned current pause does not grant extra credit even if
    # metadata changed; do not let its hash mismatch accidentally cover caps.
    if guard in {
        "initial_refund",
        "daily_refund",
        "source_refund",
        "boolean_credit",
        "active_lease",
        "sent_decrease",
        "charged_decrease",
    }:
        current = fixture.receipt("pause", db, observed=STOPPED)
        args["paused_receipt"] = current
        args["paused_receipt_sha256"] = ops.receipt_sha256(current)
        # Bind the synthetic baseline hash to the changed current snapshot, but
        # retain75/73/19 metadata. Explicit counter guards—not accidental hash
        # mismatch—must reject refunded credit/sent monotonicity violations.
        consumption = json.loads(args["consumption_receipt"])
        consumption["reader"]["receipt"]["resulting_plan_sha256"] = ops._plan_hash(
            db.collection.doc
        )
        consumption["reader"]["receipt_sha256"] = ops.receipt_sha256(
            ops.receipt_bytes(consumption["reader"]["receipt"])
        )
        args["consumption_receipt"] = ops.receipt_bytes(consumption)
        args["consumption_receipt_sha256"] = ops.receipt_sha256(args["consumption_receipt"])
    before = copy.deepcopy(db.collection.doc)
    with pytest.raises(ops.PilotControlError):
        await ops.control_pilot(db, "resume", now=NOW, apply=True, **args)
    assert db.collection.doc == before and len(db.collection.writes) == 1


def test_cli_parent_pause_is_explicit_pinned_input_not_fake_new_extension() -> None:
    args = ops.build_parser().parse_args(
        [
            "resume",
            "--original-paused-receipt-in",
            "original-pause.json",
            "--original-paused-receipt-sha256",
            "a" * 64,
            "--consumption-receipt-in",
            "actual-consumption.json",
            "--consumption-receipt-sha256",
            "b" * 64,
        ]
    )
    assert str(args.original_paused_receipt_in) == "original-pause.json"
    assert args.original_paused_receipt_sha256 == "a" * 64 and args.apply is False
    assert str(args.consumption_receipt_in) == "actual-consumption.json"
    assert args.consumption_receipt_sha256 == "b" * 64
