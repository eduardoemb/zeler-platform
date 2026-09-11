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

from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from zeler_platform_core.devoluciones_readiness import (
    DEVOLUCIONES_OPERATIONS_COLLECTION,
    DEVOLUCIONES_READ_MODEL,
)
from zeler_platform_core.devoluciones_runs import RUNS_COLLECTION

logger = structlog.get_logger(__name__)

__all__ = [
    "ADVANCEABLE_RUN_STATES",
    "advance_due_devoluciones_run",
    "renew_devoluciones_marker_if_proven",
]

FRESHNESS_COLLECTION = "sheets_read_model_freshness"
# The provenance a settled quota run publishes; renewal restores exactly this
# value so the formula gate keeps accepting one canonical source.
QUOTA_RUN_SOURCE = "zelerdata_devoluciones_quota_run"
# Mirrors ``DEVOLUCIONES_MARKER_VALIDITY``: the renewed lease covers two refresh
# cycles, exactly like the marker the quota finalize publishes.
DEVOLUCIONES_MARKER_VALIDITY = timedelta(minutes=30)

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
    advance_enabled: bool = True,
) -> bool:
    """Advance at most one due DEVOLUCIONES window for ``seller_id``.

    Returns ``True`` only when an authorized run was handed to the advancer, so
    the refresh cycle can report whether it did operational work. Missing,
    expired, foreign, or not-yet-due runs return ``False`` without touching the
    source or creating anything.

    ``advance_enabled`` gates only source work. The marker renewal below is
    always attempted: it never calls Mercado Libre and only restores a proof
    whose fingerprint still matches the settled run.
    """
    clock = now or (lambda: datetime.now(UTC))
    current = clock().astimezone(UTC)
    if not advance_enabled:
        await renew_devoluciones_marker_if_proven(db, seller_id, now=clock)
        return False
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
        # No window is due. The settled run's marker still has to outlive the
        # 30-minute lease, and the finalize only runs once, so the same cycle
        # renews the marker from the proof already persisted in Mongo. This is
        # also what repairs the marker after an acquisition that invalidated
        # readiness without publishing a replacement (for example an ``orders``
        # recovery job, which takes the same lease).
        await renew_devoluciones_marker_if_proven(db, seller_id, now=clock)
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


async def renew_devoluciones_marker_if_proven(
    db: Any,
    seller_id: str,
    *,
    now: Callable[[], datetime] | None = None,
    range_certification: Callable[..., Awaitable[str | None]] | None = None,
) -> bool:
    """Extend the DEVOLUCIONES marker from the proof already persisted in Mongo.

    The quota finalize publishes the marker once, when the last window settles.
    Nothing re-runs it afterwards, so without a renewal the 30-minute marker
    lease would expire a proof whose rows are still authoritative, and any
    acquisition that invalidates readiness (an ``orders`` recovery job takes the
    same lease) would leave ``ZELERDATA_DEVOLUCIONES`` unavailable forever.

    Renewal never calls Mercado Libre and never widens coverage: it only
    restores a marker whose settled run windows still certify the same range. A
    missing run, an absent fingerprint, or a range that no longer proves itself
    complete is refused, so an unproven marker can never be made productive.

    Certification is deliberately not byte-for-byte fingerprint equality. The
    finalize fingerprint folds in live ``claims`` counts, so any legitimate
    change inside the settled range (a later-arriving claim, a rewritten row)
    would change it and freeze the heartbeat forever. The gate instead requires
    the range to still certify itself: same bounds, at least the expected
    claims persisted and complete, and no missing rows.

    It is a heartbeat, not an expiry repair: a still-open proof is extended on
    every cycle, because waiting for the lease to lapse would leave a
    multi-minute window where the proven range is unreadable. A marker that an
    acquisition set ``stale`` is repaired the same way, since its fingerprint
    still proves the settled run.
    """
    clock = now or (lambda: datetime.now(UTC))
    current = clock().astimezone(UTC)
    marker_id = f"{seller_id}:{DEVOLUCIONES_READ_MODEL}"
    marker = await db[FRESHNESS_COLLECTION].find_one(
        {"_id": marker_id, "seller_id": str(seller_id), "read_model": DEVOLUCIONES_READ_MODEL}
    )
    if not isinstance(marker, Mapping):
        _report_refusal(seller_id, "marker_absent")
        return False
    if str(marker.get("state") or "").strip().casefold() != "reconciled" and (
        await _live_acquisition_holds_the_lease(db, seller_id, current=current)
    ):
        # The marker is withdrawn, which is what an acquisition that invalidates
        # readiness does on purpose so no reader consumes a proof while its rows
        # are rewritten. Repairing it underneath a live acquisition would defeat
        # that guard, so defer until the acquisition releases. A marker that is
        # still reconciled proves no such acquisition is live, and an
        # acquisition that does not withdraw readiness (the orders sweep) must
        # not stall the heartbeat.
        _report_refusal(seller_id, "withdrawing_acquisition_holds_the_lease")
        return False
    proof_fingerprint = str(marker.get("proof_fingerprint") or "").strip()
    if not proof_fingerprint:
        _report_refusal(seller_id, "proof_fingerprint_absent")
        return False
    revision = str(marker.get("revision") or "").strip()
    run_id = revision
    if not run_id:
        _report_refusal(seller_id, "revision_absent")
        return False
    run = await db[RUNS_COLLECTION].find_one(
        {
            "_id": run_id,
            "seller_id": str(seller_id),
            "scope": "devoluciones",
            "state": "completed",
        }
    )
    if not isinstance(run, Mapping):
        _report_refusal(seller_id, "settled_run_absent")
        return False
    if range_certification is None:
        range_certification = _runtime_range_certification
    try:
        refusal = await range_certification(db=db, run=run)
    except Exception as exc:  # noqa: BLE001 - refusal must stay observable
        _report_refusal(seller_id, "range_certification_failed", detail=type(exc).__name__)
        return False
    if refusal:
        _report_refusal(
            seller_id,
            refusal,
            detail=await _proof_drift_detail(db=db, run=run),
        )
        return False
    reconciled_until = marker.get("reconciled_until")
    date_from = marker.get("date_from")
    if not isinstance(reconciled_until, datetime) or not isinstance(date_from, datetime):
        _report_refusal(seller_id, "marker_window_incomplete")
        return False
    updated = await db[FRESHNESS_COLLECTION].update_one(
        {
            "_id": marker_id,
            "seller_id": str(seller_id),
            "read_model": DEVOLUCIONES_READ_MODEL,
            "proof_fingerprint": proof_fingerprint,
        },
        {
            "$set": {
                "state": "reconciled",
                "date_from": date_from,
                "reconciled_until": reconciled_until,
                "fresh_until": reconciled_until,
                "last_event_synced_at": date_from,
                "valid_until": current + DEVOLUCIONES_MARKER_VALIDITY,
                "updated_at": current,
                "source": QUOTA_RUN_SOURCE,
                "revision": run_id,
                "proof_fingerprint": proof_fingerprint,
                "schema_version": 1,
            }
        },
        upsert=False,
    )
    return getattr(updated, "matched_count", 0) == 1


def _report_refusal(seller_id: str, reason: str, *, detail: str | None = None) -> None:
    """Make a refused heartbeat observable instead of a silent ``False``.

    A renewal that quietly stops extending the proof looks exactly like a
    healthy cycle from the outside: the marker stays ``reconciled`` until its
    lease lapses and ``ZELERDATA_DEVOLUCIONES`` starts answering
    ``UNAVAILABLE`` between cycles. Naming the refusal reason is what lets an
    operator tell ``proof_changed`` apart from a deferred acquisition.
    """
    logger.info(
        "zelerdata.devoluciones_renewal_refused",
        seller_id=str(seller_id),
        reason=reason,
        detail=detail,
    )


async def _live_acquisition_holds_the_lease(db: Any, seller_id: str, *, current: datetime) -> bool:
    """Whether another holder is actively re-acquiring the DEVOLUCIONES scope."""
    operation = await db[DEVOLUCIONES_OPERATIONS_COLLECTION].find_one(
        {
            "_id": f"{seller_id}:{DEVOLUCIONES_READ_MODEL}",
            "seller_id": str(seller_id),
            "scope": DEVOLUCIONES_READ_MODEL,
            "state": "running",
            "lease_until": {"$gt": current},
        }
    )
    return isinstance(operation, Mapping)


async def _proof_drift_detail(*, db: Any, run: Mapping[str, Any]) -> str:
    """Describe how the live readback differs from the settled run.

    The fingerprint intentionally refuses when the live readback moves, but the
    bare reason cannot tell an operator whether the pilot gained a legitimate
    claim, lost a row, or only changed a completeness field. The counts make
    that distinction visible from the worker log alone.
    """
    from infra.operations.zelerdata_read_model_reconcile import (
        _contiguous_devoluciones_run_windows,
        readback_devoluciones_quota_run,
    )

    try:
        windows = await _contiguous_devoluciones_run_windows(db=db, run=run)
        if windows is None:
            return "windows_incomplete"
        proof = await readback_devoluciones_quota_run(db=db, run=run, windows=windows)
    except Exception as exc:  # noqa: BLE001 - diagnostics must not mask the refusal
        return f"probe_failed={type(exc).__name__}"
    return (
        f"expected={proof.get('expected_count')}"
        f" persisted={proof.get('persisted_count')}"
        f" complete={proof.get('complete_count')}"
        f" missing={proof.get('missing_count')}"
    )


async def _runtime_range_certification(*, db: Any, run: Mapping[str, Any]) -> str | None:
    """Return ``None`` when the settled range still proves itself complete.

    The proof folds in live ``claims`` counts, so an exact-fingerprint gate
    freezes the heartbeat as soon as the range legitimately changes. Requiring
    the range bounds and the completeness counts instead keeps the proof strong
    (a regressed range is refused) without coupling it to churn.
    """
    from infra.operations.zelerdata_read_model_reconcile import (
        _contiguous_devoluciones_run_windows,
        readback_devoluciones_quota_run,
    )

    windows = await _contiguous_devoluciones_run_windows(db=db, run=run)
    if windows is None:
        return "settled_run_windows_incomplete"
    proof = await readback_devoluciones_quota_run(db=db, run=run, windows=windows)
    expected = sum(int(window["expected_count"]) for window in windows)
    if proof.get("start") != run["start"] or proof.get("end") != run["end"]:
        return "settled_range_moved"
    if int(proof.get("expected_count") or 0) != expected:
        return "settled_range_expectation_changed"
    if int(proof.get("missing_count") or 0) != 0:
        return "settled_range_has_missing_claims"
    if int(proof.get("persisted_count") or 0) < expected:
        return "settled_range_not_persisted"
    if int(proof.get("complete_count") or 0) < expected:
        return "settled_range_incomplete"
    return None
