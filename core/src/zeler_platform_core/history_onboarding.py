"""Durable account-link intent. Admission performs no provider acquisition."""

from __future__ import annotations

import calendar
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


async def admit_history_onboarding(db: Any, seller_id: str, *, now: datetime) -> None:
    """Idempotent intent, preserving legacy progress, certificates and fixed cutoff."""
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
    if (
        existing is None
        or not isinstance(existing.get("cutoff"), datetime)
        or existing["cutoff"].tzinfo is None
    ):
        raise ValueError("existing history plan has invalid identity or cutoff")
    cutoff = existing["cutoff"].astimezone(UTC)
    # Upgrading a pre-existing planner never replaces its progress or its cutoff.
    await plans.update_one(
        {"_id": seller_id, "policy_version": {"$exists": False}},
        {
            "$set": {
                "policy_version": POLICY_VERSION,
                "authority": {"kind": "account_link_policy"},
                "state": "active",
                "eligible": True,
                "date_from": calendar_history_start(cutoff),
                "date_to": cutoff,
                "timezone": "UTC",
                "sources": list(SOURCES),
                "budget": {
                    source: {"physical_attempts": 20000, "consumed": 0} for source in SOURCES
                },
                "incremental_policy": {"max_daily_total": 2000, "max_daily_source": 1000},
                "total_budget": 100000,
                "total_consumed": 0,
                "onboarding_status": "pending",
                "admitted_at": now,
                "next_cycle_at": now,
                "source_cursor": 0,
                "last_linked_at": now,
            }
        },
    )
    await plans.update_one(
        {"_id": seller_id, "policy_version": POLICY_VERSION}, {"$set": {"last_linked_at": now}}
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
