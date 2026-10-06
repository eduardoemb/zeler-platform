"""Durable account-link intent. Admission performs no provider acquisition."""

from __future__ import annotations

import calendar
import copy
import re
from collections.abc import Mapping
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from pymongo.errors import DuplicateKeyError

PLAN_COLLECTION = "sheets_history_backfill_plans"
POLICY_VERSION = "history-on-link-v1"
SOURCES = ("orders", "questions", "shipments", "messages", "claims_returns", "full_withdrawals")


def calendar_history_start(cutoff: datetime) -> datetime:
    if cutoff.tzinfo is None:
        raise ValueError("history cutoff requires timezone")
    cutoff = cutoff.astimezone(UTC)
    return cutoff.replace(
        year=cutoff.year - 1,
        day=min(cutoff.day, calendar.monthrange(cutoff.year - 1, cutoff.month)[1]),
    )


def _utc_date(value: Any) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError("existing history plan has invalid date")
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _nonnegative(value: Any) -> None:
    if type(value) is not int or value < 0:
        raise ValueError("existing history plan has invalid counter")


def _validate_legacy(plan: Mapping[str, Any], cutoff: datetime, now: datetime) -> None:
    """Unknown credit/lease cannot be converted into a fresh grant by admission."""
    for field in (
        "total_budget",
        "total_consumed",
        "source_cursor",
        "execution_attempt_limit",
        "execution_consumed",
        "execution_sent",
        "incremental_consumed",
    ):
        if field in plan:
            _nonnegative(plan[field])
    for field in ("budget", "incremental_policy", "incremental_source_consumed"):
        if field in plan and not isinstance(plan[field], Mapping):
            raise ValueError("existing history plan has invalid budget shape")
    for entry in plan.get("budget", {}).values():
        if not isinstance(entry, Mapping):
            raise ValueError("existing history plan has invalid source budget")
        for field in ("physical_attempts", "consumed"):
            if field in entry:
                _nonnegative(entry[field])
        if entry.get("consumed", 0) > entry.get("physical_attempts", float("inf")):
            raise ValueError("existing history plan exceeds source budget")
    for value in plan.get("incremental_source_consumed", {}).values():
        _nonnegative(value)
    for field in ("max_daily_total", "max_daily_source"):
        if field in plan.get("incremental_policy", {}):
            _nonnegative(plan["incremental_policy"][field])
    if plan.get("total_consumed", 0) > plan.get("total_budget", float("inf")):
        raise ValueError("existing history plan exceeds total budget")
    for field in ("execution_until", "admitted_at", "last_linked_at", "next_cycle_at"):
        if field in plan:
            _utc_date(plan[field])
    if "eligible" in plan and type(plan["eligible"]) is not bool:
        raise ValueError("existing history plan has invalid eligibility")
    if "state" in plan and plan["state"] not in {"active", "paused"}:
        raise ValueError("existing history plan has invalid state")
    if "sources" in plan and (
        not isinstance(plan["sources"], list)
        or any(source not in SOURCES for source in plan["sources"])
        or len(plan["sources"]) != len(set(plan["sources"]))
    ):
        raise ValueError("existing history plan has invalid sources")
    if "date_to" in plan and _utc_date(plan["date_to"]) != cutoff:
        raise ValueError("existing history plan has contradictory cutoff")
    if (
        "date_from" in plan
        and not calendar_history_start(cutoff) <= _utc_date(plan["date_from"]) < cutoff
    ):
        raise ValueError("existing history plan has contradictory range")
    if "authority" in plan and plan["authority"] != {"kind": "account_link_policy"}:
        raise ValueError("existing history plan has unknown authority")
    for field in (
        "execution_charged",
        "execution_sent_by_source",
        "execution_work_sent_by_source",
        "execution_work",
    ):
        if field in plan and (not isinstance(plan[field], Mapping) or plan[field]):
            # A pre-policy receipt cannot be attributed safely by a new account-link seed.
            raise ValueError("existing history plan has unattributed ledger")
    if "lease_until" in plan:
        if _utc_date(plan["lease_until"]) > now:
            raise ValueError("existing history plan has active lease")
    elif plan.get("lease_token") or plan.get("lease_owner"):
        raise ValueError("existing history plan has lease without expiry")
    if "lease" in plan:
        lease = plan["lease"]
        if not isinstance(lease, Mapping) or not lease or set(lease) - {"owner", "token", "until"}:
            raise ValueError("existing history plan has unknown lease")
        if "until" not in lease or _utc_date(lease["until"]) > now:
            raise ValueError("existing history plan has active or invalid lease")


def _missing_leaves(
    existing: Mapping[str, Any], defaults: Mapping[str, Any], prefix: str = ""
) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    for key, value in defaults.items():
        path = prefix + key
        if key not in existing:
            patch[path] = value
        elif isinstance(value, Mapping):
            if not isinstance(existing[key], Mapping):
                raise ValueError("existing history plan has invalid seed shape")
            patch.update(_missing_leaves(existing[key], value, path + "."))
    return patch


async def admit_history_onboarding(
    db: Any, seller_id: str, *, now: datetime, pilot_seed: bool = False
) -> None:
    """Add missing policy leaves under a snapshot CAS; never refill legacy state.

    Pilot counters are prospective only. Admission does not establish prior
    physical balances or start an execution window; the scoped operator still
    requires a verified baseline and a legitimate, never-reset prepare.
    """
    if not seller_id.isascii() or not seller_id.isdecimal():
        raise ValueError("onboarding requires a canonical numeric seller")
    now = now.astimezone(UTC).replace(microsecond=0)
    plans = db[PLAN_COLLECTION]
    with suppress(DuplicateKeyError):
        await plans.update_one(
            {"_id": seller_id},
            {"$setOnInsert": {"seller_id": seller_id, "cutoff": now, "schema_version": 1}},
            upsert=True,
        )
    existing = await plans.find_one({"_id": seller_id, "seller_id": seller_id})
    if existing is None or not isinstance(existing.get("cutoff"), datetime):
        raise ValueError("existing history plan has invalid identity or cutoff")
    cutoff = _utc_date(existing["cutoff"])
    if "policy_version" not in existing:
        _validate_legacy(existing, cutoff, now)
        initial = dict(zip(SOURCES[:-1], (800, 150, 250, 300, 500), strict=True))
        if pilot_seed and (
            "full_withdrawals" in existing.get("sources", [])
            or existing.get("state", "paused") != "paused"
        ):
            raise ValueError("pilot legacy scope must be paused without Full")
        defaults = {
            "policy_version": POLICY_VERSION,
            "authority": {"kind": "account_link_policy"},
            "state": "paused" if pilot_seed else "active",
            "eligible": True,
            "date_from": calendar_history_start(cutoff),
            "date_to": cutoff,
            "timezone": "UTC",
            "sources": list(SOURCES[:-1] if pilot_seed else SOURCES),
            "budget": {
                source: {
                    "physical_attempts": initial.get(source, 0) if pilot_seed else 20000,
                    "consumed": 0,
                }
                for source in SOURCES
            },
            "incremental_policy": {
                "max_daily_total": 500 if pilot_seed else 2000,
                "max_daily_source": 300 if pilot_seed else 1000,
            },
            "total_budget": 2000 if pilot_seed else 100000,
            "total_consumed": 0,
            "onboarding_status": "pending",
            "admitted_at": now,
            "next_cycle_at": now,
            "source_cursor": 0,
            "last_linked_at": now,
        }
        patch = _missing_leaves(existing, defaults)
        candidate = copy.deepcopy(existing)
        for path, value in patch.items():
            target = candidate
            parts = path.split(".")
            for part in parts[:-1]:
                target = target[part]
            target[parts[-1]] = value
        _validate_legacy(candidate, cutoff, now)
        result = await plans.update_one(
            {
                "_id": seller_id,
                "seller_id": seller_id,
                "$expr": {"$eq": ["$$ROOT", {"$literal": existing}]},
            },
            {"$set": patch},
        )
        if result.matched_count != 1:
            winner = await plans.find_one({"_id": seller_id, "seller_id": seller_id})
            if (
                winner is None
                or winner.get("policy_version") != POLICY_VERSION
                or winner.get("cutoff") != existing["cutoff"]
            ):
                raise ValueError("history admission snapshot changed")
            _validate_legacy(winner, cutoff, now)
            if (
                winner.get("authority") != defaults["authority"]
                or _missing_leaves(winner, defaults)
                or (
                    pilot_seed
                    and (
                        winner.get("state") != "paused"
                        or "full_withdrawals" in winner.get("sources", [])
                    )
                )
            ):
                raise ValueError("history admission winner has invalid policy")
            # A concurrent identical admission may win; never retry the legacy grant.
            existing = winner
    elif existing["policy_version"] != POLICY_VERSION:
        raise ValueError("existing history plan has unknown policy")
    if "last_linked_at" in existing:
        _utc_date(existing["last_linked_at"])
    await plans.update_one(
        {"_id": seller_id, "seller_id": seller_id, "policy_version": POLICY_VERSION},
        {"$max": {"last_linked_at": now}},
    )


def history_execution_query(now: datetime, *, charged: bool = False) -> dict[str, Any]:
    """Optional scoped pilot limits; ordinary product plans need no new config.

    The monotonic execution_consumed counter spans initial and daily maintenance
    attempts. Operators set an absolute limit from the measured baseline rather
    than reset either historical or daily counters.
    """
    current = now.astimezone(UTC)
    return {
        "$and": [
            {
                "$or": [
                    {"execution_until": {"$exists": False}},
                    {"execution_until": {"$gt": current}},
                ]
            },
            {
                "$or": [
                    {"execution_utc_day": {"$exists": False}},
                    {"execution_utc_day": current.date().isoformat()},
                ]
            },
            {
                "$or": [
                    {"execution_attempt_limit": {"$exists": False}},
                    {
                        "execution_attempt_limit": {"$type": ["int", "long"], "$gte": 0},
                        "$or": [
                            {"execution_consumed": {"$exists": False}},
                            {"execution_consumed": {"$type": ["int", "long"], "$gte": 0}},
                        ],
                        "$expr": {
                            ("$lte" if charged else "$lt"): [
                                {"$ifNull": ["$execution_consumed", 0]},
                                "$execution_attempt_limit",
                            ]
                        },
                    },
                ]
            },
        ]
    }


def history_execution_allowed(
    plan: Mapping[str, Any], *, now: datetime, charged: bool = False
) -> bool:
    """Mirror pre-charge limits for claims authority reread; fail closed on drift."""
    current = now.astimezone(UTC)
    if "execution_until" in plan:
        until = plan["execution_until"]
        if not isinstance(until, datetime):
            return False
        until = until.replace(tzinfo=UTC) if until.tzinfo is None else until.astimezone(UTC)
        if current >= until:
            return False
    if "execution_utc_day" in plan and plan["execution_utc_day"] != current.date().isoformat():
        return False
    if "execution_attempt_limit" in plan:
        limit, consumed = plan["execution_attempt_limit"], plan.get("execution_consumed", 0)
        if type(limit) is not int or type(consumed) is not int or limit < 0 or consumed < 0:
            return False
        if consumed > limit or (consumed == limit and not charged):
            return False
    return True


def history_request_trace(plan: Mapping[str, Any], source: str, *, incremental: bool) -> str | None:
    """Optional nonsecret execution tag, independent from seller/token identity."""
    execution_id = plan.get("execution_id")
    if execution_id is None:
        return None
    if (
        not isinstance(execution_id, str)
        or re.fullmatch(r"[a-f0-9]{32}", execution_id) is None
        or source not in SOURCES[:-1]
    ):
        raise ValueError("invalid history execution trace identity or source")
    phase = "maintenance" if incremental else "initial"
    return f"h1-{execution_id}:{source}:{phase}"
