"""Bounded persisted-history 429 fence; ordinary product retries are unchanged."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any

import httpx

from zeler_platform_core.history_onboarding import PLAN_COLLECTION, POLICY_VERSION
from zeler_sheets.devoluciones_reconciliation import SourceCallBudgetError


class HistoryPilotStopError(SourceCallBudgetError):
    """Abort RETURNS before its retry branch; callers translate this into WAIT."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


async def stop_pilot_429(
    db: Any,
    *,
    captured: Mapping[str, Any],
    validated: Mapping[str, Any],
    response: Any,
    now: datetime,
) -> None:
    """Pause only the dispatch's persisted execution, retaining every debit.

    A response with missing/local attempt metadata is NOT remote proof, but may
    not authorize another scoped collector send. No environment/header authority
    is inferred; both snapshots come from the caller's existing durable checks.
    """
    if not isinstance(response, httpx.Response) or response.status_code != 429:
        return
    execution = captured.get("execution_id")
    if execution is None:
        return
    if (
        not isinstance(execution, str)
        or re.fullmatch(r"[a-f0-9]{32}", execution) is None
        or validated.get("execution_id") != execution
        or captured.get("seller_id") != validated.get("seller_id")
        or validated.get("_id") != validated.get("seller_id")
        or validated.get("policy_version") != POLICY_VERSION
        or validated.get("authority") != {"kind": "account_link_policy"}
        or validated.get("eligible") is not True
        or validated.get("state") != "active"
        or not isinstance(validated.get("execution_until"), datetime)
        or not isinstance(validated.get("execution_utc_day"), str)
        or type(validated.get("execution_attempt_limit")) is not int
        or validated["execution_attempt_limit"] < 1
    ):
        raise HistoryPilotStopError("pilot_authority_unverifiable")
    metadata = response.headers.get("X-Zeler-Upstream-Attempts")
    reason = (
        "remote_429"
        if metadata == "1"
        else "local_429_wait"
        if metadata == "0"
        else "upstream_attempt_metadata_unverifiable"
    )
    query = {
        "_id": validated["_id"],
        "seller_id": validated["seller_id"],
        "execution_id": execution,
        "policy_version": POLICY_VERSION,
        "authority.kind": "account_link_policy",
        "state": "active",
        "eligible": True,
        "execution_utc_day": validated["execution_utc_day"],
        "execution_until": validated["execution_until"],
        "execution_attempt_limit": validated["execution_attempt_limit"],
    }
    try:
        await db[PLAN_COLLECTION].update_one(query, {"$set": {"state": "paused"}})
    except Exception:  # noqa: BLE001 - never replace a conservative abort with retryable DB error
        raise HistoryPilotStopError("pilot_pause_unconfirmed") from None
    raise HistoryPilotStopError(reason)
