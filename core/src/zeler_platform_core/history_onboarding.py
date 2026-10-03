"""Durable account-link intent. Admission performs no provider acquisition."""

from __future__ import annotations

import calendar
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
