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


def _pinned_receipt(raw: bytes | None, pin: str | None, action: str) -> dict[str, Any]:
    if (
        not isinstance(raw, bytes)
        or len(raw) > 1048576
        or not isinstance(pin, str)
        or re.fullmatch("[a-f0-9]{64}", pin) is None
        or receipt_sha256(raw) != pin
    ):
        raise PilotControlError("resume_receipt_pin")
    try:
        receipt = json.loads(raw)
    except (ValueError, UnicodeError):
        raise PilotControlError("resume_receipt_invalid") from None
    if (
        not isinstance(receipt, dict)
        or receipt.get("action") != action
        or receipt.get("applied") is not True
        or receipt.get("seller_id") != SELLER
        or receipt.get("policy_version") != POLICY_VERSION
    ):
        raise PilotControlError("resume_receipt_invalid")
    return receipt


def _resume(
    plan: Mapping[str, Any],
    now: datetime,
    prepared: bytes | None,
    prepare_pin: str | None,
    paused: bytes | None,
    pause_pin: str | None,
    runtime_verified: bool,
    extension_raw: bytes | None = None,
    extension_pin: str | None = None,
    original_paused: bytes | None = None,
    original_pause_pin: str | None = None,
    consumption_raw: bytes | None = None,
    consumption_pin: str | None = None,
    previous_raw: bytes | None = None,
    previous_pin: str | None = None,
    step_paused_raw: bytes | None = None,
    step_paused_pin: str | None = None,
) -> dict[str, Any]:
    """Resume only the original fresh pilot; no new grant, range or clock.

    Older receipts lack absolute starting counters. Bound caps by the original
    remaining amounts instead: conservative rejection is safer than inferring
    historical credit. The current applied pause binds the entire finalized
    snapshot, independently approved after process quiescence.
    """
    if not runtime_verified:
        raise PilotControlError("runtime_controls_unverified")
    original = _pinned_receipt(prepared, prepare_pin, "prepare")
    stopped = _pinned_receipt(paused, pause_pin, "pause")
    execution = plan.get("execution_id")
    if (
        not isinstance(execution, str)
        or re.fullmatch("[a-f0-9]{32}", execution) is None
        or original.get("execution_id") != execution
        or stopped.get("execution_id") != execution
        or (
            (previous_raw is None and (extension_raw is None or original_paused is not None))
            and stopped.get("resulting_plan_sha256") != _plan_hash(plan)
        )
        or plan.get("state") != "paused"
        or plan.get("eligible") is not True
        or plan.get("sources") != list(INITIAL)
    ):
        raise PilotControlError("resume_snapshot_or_identity")
    try:
        started = _utc(datetime.fromisoformat(original["observed_utc"]))
        stopped_at = _utc(datetime.fromisoformat(stopped["observed_utc"]))
    except (KeyError, TypeError, ValueError):
        raise PilotControlError("resume_receipt_clock") from None
    end = min(
        started + timedelta(minutes=90),
        started.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1),
    )
    if previous_raw is not None or previous_pin is not None:
        end = _chain_resume_end(
            plan,
            now,
            original,
            stopped,
            prepare_pin,
            pause_pin,
            extension_raw,
            extension_pin,
            original_paused,
            original_pause_pin,
            previous_raw,
            previous_pin,
            consumption_raw,
            consumption_pin,
            step_paused_raw,
            step_paused_pin,
        )
    elif extension_raw is not None and original_paused is not None:
        end = _extended_repause_end(
            plan,
            now,
            started,
            stopped,
            prepare_pin,
            original_paused,
            original_pause_pin,
            extension_raw,
            extension_pin,
            consumption_raw,
            consumption_pin,
        )
    elif extension_raw is not None:
        end = _extended_resume_end(
            plan, now, started, stopped, prepare_pin, pause_pin, extension_raw, extension_pin
        )
    if (
        not started <= stopped_at <= now < end
        or now.date() != started.date()
        or plan.get("execution_utc_day") != started.date().isoformat()
        or not now < _utc(plan.get("execution_until"), bson_date=True) <= end
        or not history_execution_allowed(plan, now=now)
    ):
        raise PilotControlError("execution_window_or_limit")
    _resume_caps(plan, original, now)
    return {"state": "active"}


def _resume_caps(plan: Mapping[str, Any], original: Mapping[str, Any], now: datetime) -> None:
    remaining = original.get("initial_remaining")
    daily = original.get("natural_rollover_limits")
    if (
        not isinstance(remaining, Mapping)
        or set(remaining) != set(INITIAL)
        or original.get("daily_rollover_pending") is not True
        or not isinstance(daily, Mapping)
    ):
        raise PilotControlError("resume_starting_credit_unknown")
    for source, ceiling in INITIAL.items():
        previous = _integer(remaining[source])
        entry = plan["budget"][source]
        limit = _integer(entry["physical_attempts"])
        if previous > ceiling or limit > previous or _integer(entry.get("consumed", 0)) > limit:
            raise PilotControlError("resume_caps_invalid")
    full = plan["budget"]["full_withdrawals"]
    if _integer(full["physical_attempts"]) > _integer(full.get("consumed", 0)):
        raise PilotControlError("resume_caps_invalid")
    total = _integer(plan.get("total_budget"))
    attempts = _integer(plan.get("execution_attempt_limit"))
    consumed = _integer(plan.get("execution_consumed", 0))
    if (
        total > sum(_integer(value) for value in remaining.values())
        or _integer(plan.get("total_consumed", 0)) > total
        or attempts > 2500
        or consumed >= attempts
        or _integer(plan.get("execution_sent", 0)) > consumed
    ):
        raise PilotControlError("resume_caps_invalid")
    limit, source_limit, _, _, _ = _maintenance(plan, now)
    if (
        limit > _integer(daily.get("total"))
        or limit > 500
        or source_limit > _integer(daily.get("per_source"))
        or source_limit > 300
    ):
        raise PilotControlError("resume_caps_invalid")
    if "lease_until" in plan:
        if _utc(plan["lease_until"], bson_date=True) > now:
            raise PilotControlError("active_lease")
    elif plan.get("lease_token"):
        raise PilotControlError("lease_without_expiry")


def _iso(value: Any) -> datetime:
    try:
        if not isinstance(value, str):
            raise ValueError
        return _utc(datetime.fromisoformat(value))
    except (TypeError, ValueError):
        raise PilotControlError("extension_clock_invalid") from None


def _extension_authority(raw: bytes | None, pin: str | None) -> dict[str, Any]:
    if (
        not isinstance(raw, bytes)
        or len(raw) > 1048576
        or not isinstance(pin, str)
        or re.fullmatch("[a-f0-9]{64}", pin) is None
        or receipt_sha256(raw) != pin
    ):
        raise PilotControlError("extension_authority_pin")
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError):
        raise PilotControlError("extension_authority_invalid") from None
    if (
        not isinstance(value, dict)
        or value.get("action") != "authorize_extension"
        or value.get("authorization_received") is not True
        or value.get("seller_id") != SELLER
        or value.get("policy_version") != POLICY_VERSION
        or value.get("no_new_credit") is not True
        or value.get("full_excluded") is not True
        or not isinstance(value.get("user_evidence"), str)
        or not 0 < len(value["user_evidence"]) <= 4096
    ):
        raise PilotControlError("extension_authority_invalid")
    return value


def _extend_paused(
    plan: Mapping[str, Any],
    now: datetime,
    prepared: bytes | None,
    prepare_pin: str | None,
    paused: bytes | None,
    pause_pin: str | None,
    authority_raw: bytes | None,
    authority_pin: str | None,
    runtime_verified: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not runtime_verified:
        raise PilotControlError("runtime_controls_unverified")
    original = _pinned_receipt(prepared, prepare_pin, "prepare")
    stopped = _pinned_receipt(paused, pause_pin, "pause")
    authority = _extension_authority(authority_raw, authority_pin)
    execution = plan.get("execution_id")
    if (
        not isinstance(execution, str)
        or re.fullmatch("[a-f0-9]{32}", execution) is None
        or plan.get("state") != "paused"
        or plan.get("eligible") is not True
        or plan.get("sources") != list(INITIAL)
        or any(v.get("execution_id") != execution for v in (original, stopped, authority))
        or stopped.get("resulting_plan_sha256") != _plan_hash(plan)
        or authority.get("prepared_receipt_sha256") != prepare_pin
        or authority.get("paused_receipt_sha256") != pause_pin
    ):
        raise PilotControlError("extension_snapshot_or_identity")
    started = _iso(original.get("observed_utc"))
    stopped_at = _iso(stopped.get("observed_utc"))
    authorized = _iso(authority.get("authorized_at_utc"))
    previous = _iso(authority.get("original_until_utc"))
    approved = _iso(authority.get("approved_until_utc"))
    duration = _integer(authority.get("max_additional_seconds"))
    original_end = min(
        started + timedelta(minutes=90),
        started.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1),
    )
    if (
        not 0 < duration <= 7200
        or not started <= stopped_at <= authorized <= now < approved
        or not started < previous <= original_end
        or previous != _utc(plan.get("execution_until"), bson_date=True)
        or approved <= previous
        or approved > authorized + timedelta(seconds=duration)
        or now.date() != started.date()
        or approved.date() != started.date()
        or plan.get("execution_utc_day") != started.date().isoformat()
    ):
        raise PilotControlError("extension_window_invalid")
    _resume_caps(plan, original, now)
    lineage = {
        "previous_plan_sha256": _plan_hash(plan),
        "prepared_receipt_sha256": prepare_pin,
        "paused_receipt_sha256": pause_pin,
        "extension_authority_sha256": authority_pin,
        "extension_authorized_at_utc": authorized.isoformat(),
        "extension_max_additional_seconds": duration,
        "previous_until_utc": previous.isoformat(),
        "execution_until_utc": approved.isoformat(),
    }
    # Keep lineage in the exclusive applied receipt, not a new model/schema field.
    return {"execution_until": approved}, lineage


def _extended_resume_end(
    plan: Mapping[str, Any],
    now: datetime,
    started: datetime,
    stopped: Mapping[str, Any],
    prepare_pin: str | None,
    pause_pin: str | None,
    raw: bytes | None,
    pin: str | None,
) -> datetime:
    extension = _pinned_receipt(raw, pin, "extend-paused")
    if (
        extension.get("execution_id") != plan.get("execution_id")
        or extension.get("state") != "paused"
        or extension.get("previous_plan_sha256") != stopped.get("resulting_plan_sha256")
        or extension.get("resulting_plan_sha256") != _plan_hash(plan)
        or extension.get("prepared_receipt_sha256") != prepare_pin
        or extension.get("paused_receipt_sha256") != pause_pin
        or not isinstance(extension.get("extension_authority_sha256"), str)
        or re.fullmatch("[a-f0-9]{64}", extension["extension_authority_sha256"]) is None
    ):
        raise PilotControlError("extension_receipt_lineage")
    previous = _iso(extension.get("previous_until_utc"))
    authorized = _iso(extension.get("extension_authorized_at_utc"))
    observed = _iso(extension.get("observed_utc"))
    approved = _iso(extension.get("execution_until_utc"))
    duration = _integer(extension.get("extension_max_additional_seconds"))
    if (
        not 0 < duration <= 7200
        or not started < previous <= started + timedelta(minutes=90)
        or not _iso(stopped.get("observed_utc")) <= authorized <= observed <= now < approved
        or approved <= previous
        or approved > authorized + timedelta(seconds=duration)
        or approved != _utc(plan.get("execution_until"), bson_date=True)
        or approved.date() != started.date()
    ):
        raise PilotControlError("extension_window_invalid")
    return approved


def _extended_repause_end(
    plan: Mapping[str, Any],
    now: datetime,
    started: datetime,
    stopped: Mapping[str, Any],
    prepare_pin: str | None,
    original_paused: bytes | None,
    original_pause_pin: str | None,
    extension_raw: bytes | None,
    extension_pin: str | None,
    consumption_raw: bytes | None,
    consumption_pin: str | None,
) -> datetime:
    origin = _pinned_receipt(original_paused, original_pause_pin, "pause")
    extension = _pinned_receipt(extension_raw, extension_pin, "extend-paused")
    execution = plan.get("execution_id")
    if (
        origin.get("execution_id") != execution
        or extension.get("execution_id") != execution
        or extension.get("state") != "paused"
        or extension.get("previous_plan_sha256") != origin.get("resulting_plan_sha256")
        or extension.get("prepared_receipt_sha256") != prepare_pin
        or extension.get("paused_receipt_sha256") != original_pause_pin
        or stopped.get("resulting_plan_sha256") != _plan_hash(plan)
        or not isinstance(extension.get("extension_authority_sha256"), str)
        or re.fullmatch("[a-f0-9]{64}", extension["extension_authority_sha256"]) is None
    ):
        raise PilotControlError("extension_repause_lineage")
    previous = _iso(extension.get("previous_until_utc"))
    authorized = _iso(extension.get("extension_authorized_at_utc"))
    extended_at = _iso(extension.get("observed_utc"))
    stopped_at = _iso(stopped.get("observed_utc"))
    approved = _iso(extension.get("execution_until_utc"))
    duration = _integer(extension.get("extension_max_additional_seconds"))
    if (
        not 0 < duration <= 7200
        or not started < previous <= started + timedelta(minutes=90)
        or not _iso(origin.get("observed_utc"))
        <= authorized
        <= extended_at
        <= stopped_at
        <= now
        < approved
        or approved <= previous
        or approved > authorized + timedelta(seconds=duration)
        or approved != _utc(plan.get("execution_until"), bson_date=True)
        or approved.date() != started.date()
    ):
        raise PilotControlError("extension_window_invalid")
    current = _summary(plan, now)
    if current["daily_rollover_pending"] or extension.get("daily_rollover_pending") is not False:
        raise PilotControlError("extension_credit_unknown")
    for field in ("initial_remaining", "maintenance_source_remaining"):
        prior = extension.get(field)
        if not isinstance(prior, Mapping) or set(prior) != set(INITIAL):
            raise PilotControlError("extension_credit_unknown")
        if any(_integer(current[field][source]) > _integer(prior[source]) for source in INITIAL):
            raise PilotControlError("extension_credit_increased")
    if _integer(current["maintenance_remaining"]) > _integer(
        extension.get("maintenance_remaining")
    ):
        raise PilotControlError("extension_credit_increased")
    # Absolute counters were not in the old extension receipt. Require genuine
    # independently pinned paused readback instead of inventing starting credit.
    if (
        not isinstance(consumption_raw, bytes)
        or len(consumption_raw) > 1048576
        or not isinstance(consumption_pin, str)
        or re.fullmatch("[a-f0-9]{64}", consumption_pin) is None
        or receipt_sha256(consumption_raw) != consumption_pin
    ):
        raise PilotControlError("consumption_receipt_pin")
    try:
        observation = json.loads(consumption_raw)
    except (ValueError, UnicodeError):
        raise PilotControlError("consumption_receipt_invalid") from None
    if not isinstance(observation, Mapping) or observation.get("status") != "pass":
        raise PilotControlError("consumption_receipt_invalid")
    reader = observation.get("reader")
    if (
        not isinstance(reader, Mapping)
        or reader.get("status") != "pass"
        or reader.get("no_refund_or_reset") is not True
        or reader.get("cleanup") != "closed"
        or not isinstance(reader.get("receipt"), Mapping)
    ):
        raise PilotControlError("consumption_receipt_invalid")
    baseline = _pinned_receipt(
        receipt_bytes(reader["receipt"]), reader.get("receipt_sha256"), "pause"
    )
    if (
        baseline.get("execution_id") != execution
        or baseline.get("resulting_plan_sha256") != _plan_hash(plan)
        or not extended_at
        <= _iso(baseline.get("observed_utc"))
        <= _iso(observation.get("ended_utc"))
        <= stopped_at
    ):
        raise PilotControlError("consumption_snapshot_invalid")
    for field, source in (
        ("execution_consumed", "charged"),
        ("execution_sent", "sent"),
        ("incremental_consumed", "maintenance"),
    ):
        if _integer(plan.get(field)) < _integer(reader.get(source)):
            raise PilotControlError("consumption_counter_decreased")
    if _integer(reader.get("sent")) > _integer(reader.get("charged")):
        raise PilotControlError("consumption_receipt_invalid")
    return approved


def _chain_credit(
    plan: Mapping[str, Any],
    now: datetime,
    stopped: Mapping[str, Any],
    extension: Mapping[str, Any],
    extended_at: datetime,
    consumption_raw: bytes | None,
    consumption_pin: str | None,
) -> None:
    execution = plan.get("execution_id")
    stopped_at = _iso(stopped.get("observed_utc"))
    current = _summary(plan, now)
    if current["daily_rollover_pending"] or extension.get("daily_rollover_pending") is not False:
        raise PilotControlError("extension_credit_unknown")
    for field in ("initial_remaining", "maintenance_source_remaining"):
        prior = extension.get(field)
        if not isinstance(prior, Mapping) or set(prior) != set(INITIAL):
            raise PilotControlError("extension_credit_unknown")
        if any(_integer(current[field][source]) > _integer(prior[source]) for source in INITIAL):
            raise PilotControlError("extension_credit_increased")
    if _integer(current["maintenance_remaining"]) > _integer(
        extension.get("maintenance_remaining")
    ):
        raise PilotControlError("extension_credit_increased")
    # Absolute counters were not in the old extension receipt. Require genuine
    # independently pinned paused readback instead of inventing starting credit.
    if (
        not isinstance(consumption_raw, bytes)
        or len(consumption_raw) > 1048576
        or not isinstance(consumption_pin, str)
        or re.fullmatch("[a-f0-9]{64}", consumption_pin) is None
        or receipt_sha256(consumption_raw) != consumption_pin
    ):
        raise PilotControlError("consumption_receipt_pin")
    try:
        observation = json.loads(consumption_raw)
    except (ValueError, UnicodeError):
        raise PilotControlError("consumption_receipt_invalid") from None
    if not isinstance(observation, Mapping) or observation.get("status") != "pass":
        raise PilotControlError("consumption_receipt_invalid")
    reader = observation.get("reader")
    if (
        not isinstance(reader, Mapping)
        or reader.get("status") != "pass"
        or reader.get("no_refund_or_reset") is not True
        or reader.get("cleanup") != "closed"
        or not isinstance(reader.get("receipt"), Mapping)
    ):
        raise PilotControlError("consumption_receipt_invalid")
    baseline = _pinned_receipt(
        receipt_bytes(reader["receipt"]), reader.get("receipt_sha256"), "pause"
    )
    if (
        baseline.get("execution_id") != execution
        or baseline.get("resulting_plan_sha256") != _plan_hash(plan)
        or not extended_at
        <= _iso(baseline.get("observed_utc"))
        <= _iso(observation.get("ended_utc"))
        <= stopped_at
    ):
        raise PilotControlError("consumption_snapshot_invalid")
    for field, source in (
        ("execution_consumed", "charged"),
        ("execution_sent", "sent"),
        ("incremental_consumed", "maintenance"),
    ):
        if _integer(plan.get(field)) < _integer(reader.get(source)):
            raise PilotControlError("consumption_counter_decreased")
    if _integer(reader.get("sent")) > _integer(reader.get("charged")):
        raise PilotControlError("consumption_receipt_invalid")


def _chain_parent(
    plan: Mapping[str, Any],
    original: Mapping[str, Any],
    stopped: Mapping[str, Any],
    prepare_pin: str | None,
    origin_raw: bytes | None,
    origin_pin: str | None,
    parent_raw: bytes | None,
    parent_pin: str | None,
    now: datetime,
    consumption_raw: bytes | None,
    consumption_pin: str | None,
    allow_later_until: bool = False,
) -> tuple[Mapping[str, Any], datetime]:
    origin = _pinned_receipt(origin_raw, origin_pin, "pause")
    parent = _pinned_receipt(parent_raw, parent_pin, "extend-paused")
    execution = plan.get("execution_id")
    started = _iso(original.get("observed_utc"))
    old = _iso(parent.get("previous_until_utc"))
    authorized = _iso(parent.get("extension_authorized_at_utc"))
    observed = _iso(parent.get("observed_utc"))
    approved = _iso(parent.get("execution_until_utc"))
    duration = _integer(parent.get("extension_max_additional_seconds"))
    if (
        any(v.get("execution_id") != execution for v in (original, origin, parent, stopped))
        or parent.get("previous_extension_receipt_sha256") is not None
        or parent.get("prepared_receipt_sha256") != prepare_pin
        or parent.get("paused_receipt_sha256") != origin_pin
        or parent.get("previous_plan_sha256") != origin.get("resulting_plan_sha256")
        or parent.get("state") != "paused"
        or not isinstance(parent.get("extension_authority_sha256"), str)
        or re.fullmatch("[a-f0-9]{64}", parent["extension_authority_sha256"]) is None
        or not 0 < duration <= 7200
        or not started
        < old
        <= min(
            started + timedelta(minutes=90),
            started.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1),
        )
        or not started
        <= _iso(origin.get("observed_utc"))
        <= authorized
        <= observed
        <= _iso(stopped.get("observed_utc"))
        <= now
        or not old < approved <= authorized + timedelta(seconds=duration)
        or approved.date() != started.date()
        or stopped.get("resulting_plan_sha256") != _plan_hash(plan)
        or (not allow_later_until and _utc(plan.get("execution_until"), bson_date=True) != approved)
        or plan.get("state") != "paused"
        or plan.get("eligible") is not True
        or plan.get("sources") != list(INITIAL)
        or plan.get("execution_utc_day") != started.date().isoformat()
        or now.date() != started.date()
    ):
        raise PilotControlError("extension_chain_parent_invalid")
    full = plan["budget"]["full_withdrawals"]
    if _integer(full["physical_attempts"]) != 0 or _integer(full.get("consumed", 0)) != 0:
        raise PilotControlError("extension_chain_full_excluded")
    _resume_caps(plan, original, now)
    _chain_credit(plan, now, stopped, parent, observed, consumption_raw, consumption_pin)
    return parent, approved


def _extend_chain(
    plan: Mapping[str, Any],
    now: datetime,
    prepared: bytes | None,
    prepare_pin: str | None,
    paused: bytes | None,
    pause_pin: str | None,
    authority_raw: bytes | None,
    authority_pin: str | None,
    runtime_verified: bool,
    origin_raw: bytes | None,
    origin_pin: str | None,
    parent_raw: bytes | None,
    parent_pin: str | None,
    consumption_raw: bytes | None,
    consumption_pin: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not runtime_verified:
        raise PilotControlError("runtime_controls_unverified")
    original = _pinned_receipt(prepared, prepare_pin, "prepare")
    stopped = _pinned_receipt(paused, pause_pin, "pause")
    _, previous = _chain_parent(
        plan,
        original,
        stopped,
        prepare_pin,
        origin_raw,
        origin_pin,
        parent_raw,
        parent_pin,
        now,
        consumption_raw,
        consumption_pin,
    )
    authority = _extension_authority(authority_raw, authority_pin)
    authorized = _iso(authority.get("authorized_at_utc"))
    approved = _iso(authority.get("approved_until_utc"))
    duration = _integer(authority.get("max_additional_seconds"))
    if (
        authority.get("execution_id") != plan.get("execution_id")
        or authority.get("prepared_receipt_sha256") != prepare_pin
        or authority.get("paused_receipt_sha256") != pause_pin
        or authority.get("previous_extension_receipt_sha256") != parent_pin
        or _iso(authority.get("original_until_utc")) != previous
        or not 0 < duration <= 7200
        or not _iso(stopped.get("observed_utc")) <= authorized <= now < approved
        or not previous < approved <= authorized + timedelta(seconds=duration)
        or approved.date() != now.date()
    ):
        raise PilotControlError("extension_chain_authority_invalid")
    lineage = {
        "previous_plan_sha256": _plan_hash(plan),
        "prepared_receipt_sha256": prepare_pin,
        "paused_receipt_sha256": pause_pin,
        "extension_authority_sha256": authority_pin,
        "extension_authorized_at_utc": authorized.isoformat(),
        "extension_max_additional_seconds": duration,
        "previous_until_utc": previous.isoformat(),
        "execution_until_utc": approved.isoformat(),
        "previous_extension_receipt_sha256": parent_pin,
        "original_paused_receipt_sha256": origin_pin,
    }
    return {"execution_until": approved}, lineage


def _chain_resume_end(
    plan: Mapping[str, Any],
    now: datetime,
    original: Mapping[str, Any],
    stopped: Mapping[str, Any],
    prepare_pin: str | None,
    pause_pin: str | None,
    latest_raw: bytes | None,
    latest_pin: str | None,
    origin_raw: bytes | None,
    origin_pin: str | None,
    parent_raw: bytes | None,
    parent_pin: str | None,
    consumption_raw: bytes | None,
    consumption_pin: str | None,
    step_paused_raw: bytes | None = None,
    step_paused_pin: str | None = None,
) -> datetime:
    latest = _pinned_receipt(latest_raw, latest_pin, "extend-paused")
    parent = _pinned_receipt(parent_raw, parent_pin, "extend-paused")
    previous = _iso(parent.get("execution_until_utc"))
    if step_paused_raw is not None or step_paused_pin is not None:
        step = _pinned_receipt(step_paused_raw, step_paused_pin, "pause")
        _chain_parent(
            plan,
            original,
            stopped,
            prepare_pin,
            origin_raw,
            origin_pin,
            parent_raw,
            parent_pin,
            now,
            consumption_raw,
            consumption_pin,
            allow_later_until=True,
        )
        approved = _iso(latest.get("execution_until_utc"))
        authorized = _iso(latest.get("extension_authorized_at_utc"))
        observed = _iso(latest.get("observed_utc"))
        duration = _integer(latest.get("extension_max_additional_seconds"))
        if (
            step.get("execution_id") != plan.get("execution_id")
            or latest.get("execution_id") != plan.get("execution_id")
            or latest.get("state") != "paused"
            or latest.get("prepared_receipt_sha256") != prepare_pin
            or latest.get("paused_receipt_sha256") != step_paused_pin
            or latest.get("original_paused_receipt_sha256") != origin_pin
            or latest.get("previous_extension_receipt_sha256") != parent_pin
            or latest.get("previous_plan_sha256") != step.get("resulting_plan_sha256")
            or not isinstance(latest.get("extension_authority_sha256"), str)
            or re.fullmatch("[a-f0-9]{64}", latest["extension_authority_sha256"]) is None
            or _iso(latest.get("previous_until_utc")) != previous
            or not 0 < duration <= 7200
            or not _iso(parent.get("observed_utc"))
            <= _iso(step.get("observed_utc"))
            <= authorized
            <= observed
            <= _iso(stopped.get("observed_utc"))
            <= now
            < approved
            or not previous < approved <= authorized + timedelta(seconds=duration)
            or approved != _utc(plan.get("execution_until"), bson_date=True)
            or approved.date() != now.date()
        ):
            raise PilotControlError("extension_chain_repause_invalid")
        _chain_credit(plan, now, stopped, latest, observed, consumption_raw, consumption_pin)
        return approved
    # The genuine pre-apply pause is bridged by the pinned deadline-only result.
    before = {**dict(plan), "execution_until": previous}
    _chain_parent(
        before,
        original,
        stopped,
        prepare_pin,
        origin_raw,
        origin_pin,
        parent_raw,
        parent_pin,
        now,
        consumption_raw,
        consumption_pin,
    )
    approved = _iso(latest.get("execution_until_utc"))
    authorized = _iso(latest.get("extension_authorized_at_utc"))
    observed = _iso(latest.get("observed_utc"))
    duration = _integer(latest.get("extension_max_additional_seconds"))
    if (
        latest.get("execution_id") != plan.get("execution_id")
        or latest.get("state") != "paused"
        or latest.get("prepared_receipt_sha256") != prepare_pin
        or latest.get("paused_receipt_sha256") != pause_pin
        or latest.get("original_paused_receipt_sha256") != origin_pin
        or latest.get("previous_extension_receipt_sha256") != parent_pin
        or latest.get("previous_plan_sha256") != _plan_hash(before)
        or latest.get("resulting_plan_sha256") != _plan_hash(plan)
        or not isinstance(latest.get("extension_authority_sha256"), str)
        or re.fullmatch("[a-f0-9]{64}", latest["extension_authority_sha256"]) is None
        or _iso(latest.get("previous_until_utc")) != previous
        or not 0 < duration <= 7200
        or not _iso(stopped.get("observed_utc")) <= authorized <= observed <= now < approved
        or not previous < approved <= authorized + timedelta(seconds=duration)
        or approved != _utc(plan.get("execution_until"), bson_date=True)
        or approved.date() != now.date()
    ):
        raise PilotControlError("extension_chain_resume_invalid")
    return approved


async def control_pilot(
    db: Any,
    action: str,
    *,
    now: datetime,
    execution_id: str | None = None,
    apply: bool = False,
    prepared_receipt: bytes | None = None,
    prepared_receipt_sha256: str | None = None,
    paused_receipt: bytes | None = None,
    paused_receipt_sha256: str | None = None,
    runtime_controls_verified: bool = False,
    extension_authority: bytes | None = None,
    extension_authority_sha256: str | None = None,
    extension_receipt: bytes | None = None,
    extension_receipt_sha256: str | None = None,
    original_paused_receipt: bytes | None = None,
    original_paused_receipt_sha256: str | None = None,
    consumption_receipt: bytes | None = None,
    consumption_receipt_sha256: str | None = None,
    previous_extension_receipt: bytes | None = None,
    previous_extension_receipt_sha256: str | None = None,
    extension_paused_receipt: bytes | None = None,
    extension_paused_receipt_sha256: str | None = None,
) -> dict[str, Any]:
    now = _utc(now)
    collection = db[PLAN_COLLECTION]
    plan = await collection.find_one({"_id": SELLER})
    if not isinstance(plan, Mapping):
        raise PilotControlError("plan_missing")
    _identity(plan)
    lineage: dict[str, Any] = {}
    if (
        execution_id is not None
        and action in {"resume", "extend-paused"}
        and plan.get("execution_id") != execution_id
    ):
        raise PilotControlError("execution_identity_changed")
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
    elif action == "resume":
        patch = _resume(
            plan,
            now,
            prepared_receipt,
            prepared_receipt_sha256,
            paused_receipt,
            paused_receipt_sha256,
            runtime_controls_verified,
            extension_receipt,
            extension_receipt_sha256,
            original_paused_receipt,
            original_paused_receipt_sha256,
            consumption_receipt,
            consumption_receipt_sha256,
            previous_extension_receipt,
            previous_extension_receipt_sha256,
            extension_paused_receipt,
            extension_paused_receipt_sha256,
        )
    elif action == "extend-paused" and (
        previous_extension_receipt is not None or previous_extension_receipt_sha256 is not None
    ):
        patch, lineage = _extend_chain(
            plan,
            now,
            prepared_receipt,
            prepared_receipt_sha256,
            paused_receipt,
            paused_receipt_sha256,
            extension_authority,
            extension_authority_sha256,
            runtime_controls_verified,
            original_paused_receipt,
            original_paused_receipt_sha256,
            previous_extension_receipt,
            previous_extension_receipt_sha256,
            consumption_receipt,
            consumption_receipt_sha256,
        )
    elif action == "extend-paused":
        patch, lineage = _extend_paused(
            plan,
            now,
            prepared_receipt,
            prepared_receipt_sha256,
            paused_receipt,
            paused_receipt_sha256,
            extension_authority,
            extension_authority_sha256,
            runtime_controls_verified,
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
    receipt.update(lineage)
    if action != "pause":
        receipt.update(_summary(resulting, now))
    return receipt


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(description=__doc__)
    parser.add_argument(
        "action", choices=("prepare", "pause", "activate", "resume", "extend-paused")
    )
    parser.add_argument("--execution-id")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-approved-runtime", action="store_true")
    parser.add_argument("--confirm-pilot-authorization", action="store_true")
    parser.add_argument("--runtime-controls-verified", action="store_true")
    parser.add_argument("--receipt-in", type=Path)
    parser.add_argument("--receipt-sha256")
    parser.add_argument("--paused-receipt-in", type=Path)
    parser.add_argument("--paused-receipt-sha256")
    parser.add_argument("--extension-authority-in", type=Path)
    parser.add_argument("--extension-authority-sha256")
    parser.add_argument("--extension-receipt-in", type=Path)
    parser.add_argument("--extension-receipt-sha256")
    parser.add_argument("--original-paused-receipt-in", type=Path)
    parser.add_argument("--original-paused-receipt-sha256")
    parser.add_argument("--consumption-receipt-in", type=Path)
    parser.add_argument("--consumption-receipt-sha256")
    parser.add_argument("--previous-extension-receipt-in", type=Path)
    parser.add_argument("--previous-extension-receipt-sha256")
    parser.add_argument("--extension-paused-receipt-in", type=Path)
    parser.add_argument("--extension-paused-receipt-sha256")
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
    paused_raw = None
    if args.paused_receipt_in is not None:
        if args.paused_receipt_in.is_symlink() or args.paused_receipt_in.stat().st_size > 1048576:
            raise PilotControlError("receipt_path_invalid")
        paused_raw = args.paused_receipt_in.read_bytes()
    extension_inputs = {}
    for field in (
        "extension_authority",
        "extension_receipt",
        "original_paused_receipt",
        "consumption_receipt",
        "previous_extension_receipt",
        "extension_paused_receipt",
    ):
        path = getattr(args, field + "_in")
        if path is not None:
            if path.is_symlink() or path.stat().st_size > 1048576:
                raise PilotControlError("receipt_path_invalid")
            extension_inputs[field] = path.read_bytes()
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
            paused_receipt=paused_raw,
            paused_receipt_sha256=args.paused_receipt_sha256,
            runtime_controls_verified=args.runtime_controls_verified,
            extension_authority_sha256=args.extension_authority_sha256,
            extension_receipt_sha256=args.extension_receipt_sha256,
            original_paused_receipt_sha256=args.original_paused_receipt_sha256,
            consumption_receipt_sha256=args.consumption_receipt_sha256,
            previous_extension_receipt_sha256=args.previous_extension_receipt_sha256,
            extension_paused_receipt_sha256=args.extension_paused_receipt_sha256,
            **extension_inputs,
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
