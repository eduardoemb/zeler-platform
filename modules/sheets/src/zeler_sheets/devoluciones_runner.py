"""Advance an already-authorized DEVOLUCIONES run from the refresh loop.

The systemd timer used to own this trigger. Per Q2-b/Q7-a the same worker loop
that keeps the other read models fresh also advances DEVOLUCIONES, so one loop
owns operational freshness.

This module never widens the authorization boundary. It only *advances* a run
that an operator already authorized: the run must exist for this seller, be in
an advanceable state, still be unexpired, and be past its own ``not_before``.
Creating, re-authorizing, or extending a run stays an explicit operator action,
and the underlying advancement keeps the existing lease, window, and readback
guarantees.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import structlog

from zeler_platform_core.devoluciones_runs import RUNS_COLLECTION

logger = structlog.get_logger(__name__)

__all__ = ["ADVANCEABLE_RUN_STATES", "advance_due_devoluciones_run"]

# Mirrors ``devoluciones_run_allows_advancement``: every other lifecycle state
# (``finalizing``, ``completed``, ``failed``, ``expired``) must never start
# source work from the loop.
ADVANCEABLE_RUN_STATES: frozenset[str] = frozenset({"authorized", "active"})


async def advance_due_devoluciones_run(
    db: Any,
    seller_id: str,
    *,
    now: Callable[[], datetime] | None = None,
    advance: Callable[..., Awaitable[dict[str, int]]] | None = None,
) -> bool:
    """Advance at most one due DEVOLUCIONES window for ``seller_id``.

    Returns ``True`` only when an authorized run was handed to the advancer, so
    the refresh cycle can report whether it did operational work. Missing,
    expired, foreign, or not-yet-due runs return ``False`` without touching the
    source or creating anything.
    """
    clock = now or (lambda: datetime.now(UTC))
    current = clock().astimezone(UTC)
    run = await db[RUNS_COLLECTION].find_one(
        {
            "seller_id": str(seller_id),
            "scope": "devoluciones",
            "state": {"$in": sorted(ADVANCEABLE_RUN_STATES)},
            "expires_at": {"$gt": current},
            "$or": [{"not_before": {"$exists": False}}, {"not_before": {"$lte": current}}],
        },
        sort=[("created_at", -1)],
    )
    if not isinstance(run, dict) or not str(run.get("_id") or "").strip():
        return False

    run_id = str(run["_id"])
    if advance is None:
        advance = _runtime_advance
    await advance(db=db, run_id=run_id, now=clock)
    logger.info("zelerdata.devoluciones_run_advanced", run_id=run_id)
    return True


async def _runtime_advance(*, db: Any, run_id: str, now: Any = None) -> dict[str, int]:
    """Bind the real maintenance CLI, which owns the lease and readback gates."""
    from infra.operations.devoluciones_quota_advance import advance_authorized_quota_run

    return await advance_authorized_quota_run(db=db, run_id=run_id, now=now)
