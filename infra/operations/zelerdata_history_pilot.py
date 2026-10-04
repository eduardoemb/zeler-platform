"""Scoped pilot controls; dry-run by default, one CAS and no job/lease mutation.

Run only from the approved VM/runtime with its existing Mongo configuration.
Preparation pauses the plan. Activation needs its applied receipt pinned by SHA
and explicit confirmation of the independently verified runtime gates. A pause
blocks subsequent authority checks; it is not proof of process quiescence.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, NoReturn

from bson import json_util

from zeler_platform_core.history_onboarding import (
    PLAN_COLLECTION,
    POLICY_VERSION,
    SOURCES,
    history_execution_allowed,
)

SELLER = "82453304"
INITIAL = dict(zip(SOURCES[:-1], (800, 150, 250, 300, 500), strict=True))


class PilotControlError(RuntimeError):
    """Fixed diagnostic codes only; no database values or connection strings."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise PilotControlError("invalid_arguments")


def receipt_bytes(receipt: Mapping[str, Any]) -> bytes:
    return (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode()


def receipt_sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _plan_hash(plan: Mapping[str, Any]) -> str:
    raw = json_util.dumps(
        dict(plan),
        json_options=json_util.CANONICAL_JSON_OPTIONS,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return receipt_sha256(raw)


def _integer(value: Any) -> int:
    if type(value) is not int or value < 0:
        raise PilotControlError("invalid_counter_or_limit")
    return value


def _utc(value: Any, *, bson_date: bool = False) -> datetime:
    if not isinstance(value, datetime):
        raise PilotControlError("invalid_datetime")
    if value.tzinfo is None:
        if not bson_date:
            raise PilotControlError("utc_clock_required")
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _identity(plan: Mapping[str, Any]) -> None:
    if (
        plan.get("_id") != SELLER
        or plan.get("seller_id") != SELLER
        or plan.get("policy_version") != POLICY_VERSION
        or not isinstance(plan.get("authority"), Mapping)
        or plan["authority"].get("kind") != "account_link_policy"
        or plan.get("state") not in {"active", "paused"}
    ):
        raise PilotControlError("policy_identity_mismatch")


def _maintenance(
    plan: Mapping[str, Any], now: datetime
) -> tuple[int, int, bool, int, dict[str, int]]:
    policy = plan.get("incremental_policy")
    if not isinstance(policy, Mapping):
        raise PilotControlError("incremental_policy_missing")
    limit = _integer(policy.get("max_daily_total"))
    source_limit = _integer(policy.get("max_daily_source"))
    day = plan.get("incremental_day")
    if day is not None:
        try:
            parsed = datetime.strptime(day, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            raise PilotControlError("invalid_incremental_day") from None
        if parsed.isoformat() != day or parsed > now.date():
            raise PilotControlError("invalid_incremental_day")
    pending = day != now.date().isoformat()
    consumed = _integer(plan.get("incremental_consumed", 0))
    counters = plan.get("incremental_source_consumed", {})
    if not isinstance(counters, Mapping) or not pending and set(counters) != set(SOURCES):
        raise PilotControlError("invalid_incremental_counters")
    source_consumed = {s: _integer(counters.get(s, 0)) for s in SOURCES}
    return limit, source_limit, pending, consumed, source_consumed


def _prepare(plan: Mapping[str, Any], now: datetime, execution_id: str | None) -> dict[str, Any]:
    if plan.get("eligible") is not True:
        raise PilotControlError("seller_not_eligible")
    if not isinstance(execution_id, str) or re.fullmatch("[a-f0-9]{32}", execution_id) is None:
        raise PilotControlError("execution_id_required")
    if "execution_id" in plan and plan["execution_id"] != execution_id:
        raise PilotControlError("execution_identity_changed")
    if "execution_utc_day" in plan and plan["execution_utc_day"] != now.date().isoformat():
        raise PilotControlError("execution_day_changed")
    for field in ("cutoff", "date_from", "date_to"):
        _utc(plan.get(field), bson_date=True)
    sources = plan.get("sources")
    if (
        not isinstance(sources, list)
        or any(s not in SOURCES for s in sources)
        or len(sources) != len(set(sources))
    ):
        raise PilotControlError("invalid_source_scope")
    scoped = [s for s in INITIAL if s in sources]
    if not scoped:
        raise PilotControlError("empty_source_scope")
    until = min(
        now + timedelta(minutes=90),
        now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1),
    )
    if "execution_until" in plan:
        until = min(until, _utc(plan["execution_until"], bson_date=True))
    if until <= now:
        raise PilotControlError("execution_window_expired")
    total_consumed = _integer(plan.get("total_consumed", 0))
    execution_consumed = _integer(plan.get("execution_consumed", 0))
    patch: dict[str, Any] = {
        "state": "paused",
        "sources": scoped,
        "execution_id": execution_id,
        "execution_until": until,
        "execution_utc_day": now.date().isoformat(),
        "total_budget": min(_integer(plan.get("total_budget")), total_consumed + 2000),
        "execution_attempt_limit": min(
            _integer(plan.get("execution_attempt_limit", execution_consumed + 2500)),
            execution_consumed + 2500,
        ),
    }
    budget = plan.get("budget")
    if not isinstance(budget, Mapping):
        raise PilotControlError("budget_missing")
    for source in SOURCES:
        entry = budget.get(source)
        if not isinstance(entry, Mapping):
            raise PilotControlError("source_budget_missing")
        patch[f"budget.{source}.physical_attempts"] = min(
            _integer(entry.get("physical_attempts")),
            _integer(entry.get("consumed", 0)) + INITIAL.get(source, 0),
        )
    limit, source_limit, pending, consumed, counters = _maintenance(plan, now)
    patch["incremental_policy.max_daily_total"] = min(limit, (0 if pending else consumed) + 500)
    patch["incremental_policy.max_daily_source"] = min(
        source_limit,
        min((0 if pending else counters[s]) + 300 for s in scoped),
    )
    return patch


def _patched(plan: Mapping[str, Any], patch: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(plan))
    for field, value in patch.items():
        target = result
        parts = field.split(".")
        for part in parts[:-1]:
            target = target[part]
        target[parts[-1]] = value
    return result


def _summary(plan: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    initial = {
        s: max(
            0,
            _integer(plan["budget"][s]["physical_attempts"])
            - _integer(plan["budget"][s].get("consumed", 0)),
        )
        for s in INITIAL
    }
    limit, source_limit, pending, consumed, counters = _maintenance(plan, now)
    return {
        "initial_remaining": initial,
        "daily_rollover_pending": pending,
        "maintenance_remaining": None if pending else max(0, limit - consumed),
        "maintenance_source_remaining": None
        if pending
        else {s: max(0, source_limit - counters[s]) for s in INITIAL},
        "natural_rollover_limits": {"total": limit, "per_source": source_limit}
        if pending
        else None,
    }


def _activate(
    plan: Mapping[str, Any],
    now: datetime,
    raw: bytes | None,
    pin: str | None,
    runtime_verified: bool,
) -> dict[str, Any]:
    if not runtime_verified:
        raise PilotControlError("runtime_controls_unverified")
    if (
        not isinstance(raw, bytes)
        or len(raw) > 1048576
        or not isinstance(pin, str)
        or re.fullmatch("[a-f0-9]{64}", pin) is None
        or receipt_sha256(raw) != pin
    ):
        raise PilotControlError("prepared_receipt_pin")
    try:
        receipt = json.loads(raw)
    except (ValueError, UnicodeError):
        raise PilotControlError("prepared_receipt_invalid") from None
    if (
        not isinstance(receipt, dict)
        or receipt.get("action") != "prepare"
        or receipt.get("applied") is not True
        or receipt.get("seller_id") != SELLER
        or receipt.get("execution_id") != plan.get("execution_id")
        or receipt.get("resulting_plan_sha256") != _plan_hash(plan)
    ):
        raise PilotControlError("prepared_plan_changed")
    if plan.get("state") != "paused" or plan.get("eligible") is not True:
        raise PilotControlError("prepared_plan_not_paused")
    if plan.get("execution_utc_day") != now.date().isoformat() or not history_execution_allowed(
        plan, now=now
    ):
        raise PilotControlError("execution_window_or_limit")
    if "lease_until" in plan:
        if _utc(plan["lease_until"], bson_date=True) > now:
            raise PilotControlError("active_lease")
    elif plan.get("lease_token"):
        raise PilotControlError("lease_without_expiry")
    expected = _prepare(plan, now, plan.get("execution_id"))
    # A prepared receipt cannot activate relaxed limits or a wider source scope.
    for field, value in expected.items():
        if field == "state":
            continue
        current: Any = plan
        for part in field.split("."):
            current = current[part]
        if field == "execution_until":
            # The runtime client's default BSON decode returns naive UTC dates.
            current = _utc(current, bson_date=True)
        if current != value:
            raise PilotControlError("prepared_caps_invalid")
    return {"state": "active"}


async def control_pilot(
    db: Any,
    action: str,
    *,
    now: datetime,
    execution_id: str | None = None,
    apply: bool = False,
    prepared_receipt: bytes | None = None,
    prepared_receipt_sha256: str | None = None,
    runtime_controls_verified: bool = False,
) -> dict[str, Any]:
    now = _utc(now)
    collection = db[PLAN_COLLECTION]
    plan = await collection.find_one({"_id": SELLER})
    if not isinstance(plan, Mapping):
        raise PilotControlError("plan_missing")
    _identity(plan)
    if action == "prepare":
        patch = _prepare(plan, now, execution_id)
    elif action == "pause":
        if execution_id is not None and plan.get("execution_id") != execution_id:
            raise PilotControlError("execution_identity_changed")
        patch = {"state": "paused"}
    elif action == "activate":
        patch = _activate(
            plan, now, prepared_receipt, prepared_receipt_sha256, runtime_controls_verified
        )
    else:
        raise PilotControlError("invalid_action")
    resulting = _patched(plan, patch)
    if apply:
        # Whole-document CAS catches additions as well as counters/leases changing.
        result = await collection.update_one(
            {"_id": SELLER, "$expr": {"$eq": ["$$ROOT", {"$literal": dict(plan)}]}},
            {"$set": patch},
            upsert=False,
        )
        if result.matched_count != 1:
            raise PilotControlError("plan_changed")
        readback = await collection.find_one({"_id": SELLER})
        if not isinstance(readback, Mapping) or _plan_hash(readback) != _plan_hash(resulting):
            raise PilotControlError("applied_readback_changed")
    receipt = {
        "action": action,
        "applied": apply,
        "seller_id": SELLER,
        "policy_version": POLICY_VERSION,
        "execution_id": resulting.get("execution_id"),
        "observed_utc": now.isoformat(),
        "resulting_plan_sha256": _plan_hash(resulting),
        "state": resulting["state"],
        "no_retry": True,
        "pause_is_not_process_quiescence": True,
    }
    if action != "pause":
        receipt.update(_summary(resulting, now))
    return receipt


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "pause", "activate"))
    parser.add_argument("--execution-id")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-approved-runtime", action="store_true")
    parser.add_argument("--confirm-pilot-authorization", action="store_true")
    parser.add_argument("--runtime-controls-verified", action="store_true")
    parser.add_argument("--receipt-in", type=Path)
    parser.add_argument("--receipt-sha256")
    parser.add_argument("--receipt-out", type=Path)
    return parser


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    if args.apply and (
        not args.confirm_approved_runtime
        or not args.confirm_pilot_authorization
        or args.receipt_out is None
    ):
        raise PilotControlError("explicit_apply_confirmation_and_receipt_required")
    if not args.apply and args.receipt_out is not None:
        raise PilotControlError("dry_run_cannot_write_receipt")
    raw = None
    if args.receipt_in is not None:
        if args.receipt_in.is_symlink() or args.receipt_in.stat().st_size > 1048576:
            raise PilotControlError("receipt_path_invalid")
        raw = args.receipt_in.read_bytes()
    if not os.environ.get("MONGO_URI") or not os.environ.get("MONGO_DB"):
        raise PilotControlError("runtime_configuration_required")
    from infra.operations.zelerdata_read_model_reconcile import create_runtime_db

    stream = None
    runtime = None
    try:
        if args.apply:
            stream = args.receipt_out.open("xb")
            os.fchmod(stream.fileno(), 0o600)
        runtime = create_runtime_db()
        receipt = await control_pilot(
            runtime.db,
            args.action,
            now=datetime.now(UTC),
            execution_id=args.execution_id,
            apply=args.apply,
            prepared_receipt=raw,
            prepared_receipt_sha256=args.receipt_sha256,
            runtime_controls_verified=args.runtime_controls_verified,
        )
        if stream is not None:
            stream.write(receipt_bytes(receipt))
            stream.flush()
            os.fsync(stream.fileno())
        return receipt
    finally:
        if runtime is not None:
            runtime.client.close()
        if stream is not None:
            stream.close()


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        print(json.dumps(asyncio.run(_run(args)), sort_keys=True))
        return 0
    except PilotControlError as exc:
        print(json.dumps({"ok": False, "code": str(exc), "no_retry": True}))
        return 2
    except Exception:  # noqa: BLE001 - redact all driver/runtime exceptions at the CLI boundary.
        print(
            json.dumps(
                {"ok": False, "code": "operation_failed_inspect_before_repeat", "no_retry": True}
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
