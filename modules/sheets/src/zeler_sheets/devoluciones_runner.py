"""Advance policy- or operator-authorized DEVOLUCIONES runs from the refresh loop.

The systemd timer used to own this trigger. Per Q2-b/Q7-a the same worker loop
that keeps the other read models fresh also advances DEVOLUCIONES, so one loop
owns operational freshness.

Operator runs retain their explicit pilot authorization boundary. Product
onboarding admits independent bounded runs only under persisted account-link
policy; it revalidates seller, eligibility, source, cutoff and durable budget.
Both paths retain the existing fenced lease, exact window and joint readback
guarantees. Automatic policy does not re-authorize terminal operator runs.

With history on link off, a paused pilot plan cannot authorize its runs, so the
loop ignores them and extends certified coverage with one ordinary bounded tail
run per day instead (L-036: a paused pilot must not hold ordinary work).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, cast

import httpx
import structlog

from zeler_platform_core.devoluciones_readiness import (
    DEVOLUCIONES_OPERATIONS_COLLECTION,
    DEVOLUCIONES_READ_MODEL,
)
from zeler_platform_core.devoluciones_readiness import (
    acquire_devoluciones_operation as _acquire_onboarding_operation,
)
from zeler_platform_core.devoluciones_readiness import (
    finish_devoluciones_operation as _finish_onboarding_operation,
)
from zeler_platform_core.devoluciones_runs import RUNS_COLLECTION, WINDOW_DAYS, RunBinding
from zeler_platform_core.devoluciones_runs import MongoRunWindowRepository as _OnboardingRepository
from zeler_platform_core.history_onboarding import history_execution_allowed, history_request_trace
from zeler_sheets.formulas.pacing import (
    HistoryPolicyWaitError,
    admit_paced_dispatch,
    history_policy_dispatch,
)

logger = structlog.get_logger(__name__)

__all__ = [
    "ADVANCEABLE_RUN_STATES",
    "ORDINARY_TAIL_AUTHORIZATION",
    "advance_due_devoluciones_run",
    "admit_onboarding_devoluciones",
    "admit_ordinary_devoluciones_tail",
    "advance_onboarding_devoluciones",
    "advance_ordinary_devoluciones_tail",
    "ordinary_tail_binding",
    "ordinary_tail_bounds",
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
    history_work_enabled: bool = True,
    admit_tail: Callable[..., Awaitable[str | None]] | None = None,
) -> bool:
    """Advance at most one due DEVOLUCIONES window for ``seller_id``.

    Returns ``True`` only when a run was handed to the advancer, so the refresh
    cycle can report whether it did operational work. Missing, expired,
    foreign, or not-yet-due runs return ``False`` without touching the source.

    ``advance_enabled`` gates only source work. The marker renewal below is
    always attempted: it never calls Mercado Libre and only restores a proof
    whose fingerprint still matches the settled run.

    With ``history_work_enabled`` off, pilot (``onboarding:``) runs are
    ignored: their paused plan cannot authorize them, and they must not hold
    the single advancement slot. When nothing else is due, the cycle admits the
    ordinary daily tail that the pilot's incremental run used to provide.
    """
    clock = now or (lambda: datetime.now(UTC))
    current = clock().astimezone(UTC)
    if not advance_enabled:
        await renew_devoluciones_marker_if_proven(db, seller_id, now=clock)
        return False
    query: dict[str, Any] = {
        "seller_id": str(seller_id),
        "scope": "devoluciones",
        "state": {"$in": sorted(ADVANCEABLE_RUN_STATES)},
        "expires_at": {"$gt": current},
        "$or": [{"not_before": {"$exists": False}}, {"not_before": {"$lte": current}}],
    }
    if not history_work_enabled:
        query["authorization_id"] = {"$not": {"$regex": "^onboarding:"}}
    run = await db[RUNS_COLLECTION].find_one(query, sort=[("created_at", -1)])
    if not isinstance(run, dict) or not str(run.get("_id") or "").strip():
        # No window is due. The settled run's marker still has to outlive the
        # 30-minute lease, and the finalize only runs once, so the same cycle
        # renews the marker from the proof already persisted in Mongo. This is
        # also what repairs the marker after an acquisition that invalidated
        # readiness without publishing a replacement (for example an ``orders``
        # recovery job, which takes the same lease).
        await renew_devoluciones_marker_if_proven(db, seller_id, now=clock)
        if history_work_enabled:
            return False
        tail_id = await (admit_tail or admit_ordinary_devoluciones_tail)(
            db, str(seller_id), now=clock
        )
        if tail_id is None:
            return False
        run_id = tail_id
    else:
        # Existing independent proofs must get an opportunity even while a new
        # run has work on every refresh tick, or when that source attempt fails.
        # Renew before source work so a slow/failing upstream cannot starve history.
        await _renew_active_before_advance(db, seller_id, clock)
        run_id = str(run["_id"])
    if advance is None:
        advance = _runtime_advance
    await advance(db=db, run_id=run_id, now=clock)
    logger.info("zelerdata.devoluciones_run_advanced", run_id=run_id)
    return True


async def _renew_active_before_advance(
    db: Any, seller_id: str, clock: Callable[[], datetime]
) -> None:
    import asyncio

    from zeler_platform_core.devoluciones_certificates import coverage_control

    try:
        # Includes the compatibility read, not just the inner renewal batch.
        async with asyncio.timeout(30):
            control = await coverage_control(db, str(seller_id))
            if control.get("coverage_mode") == "active":
                await renew_due_certificates(db, str(seller_id), now=clock)
    except Exception as exc:  # noqa: BLE001 - local proof failure cannot suppress source work
        _report_refusal(
            seller_id, "certificate_renewal_before_advance_failed", detail=type(exc).__name__
        )


async def _runtime_advance(*, db: Any, run_id: str, now: Any = None) -> dict[str, int]:
    """Keep operator CLI authority separate from automatic product policy."""
    run = await db[RUNS_COLLECTION].find_one({"_id": run_id})
    if isinstance(run, Mapping) and run.get("authorization_id") == ORDINARY_TAIL_AUTHORIZATION:
        return await advance_ordinary_devoluciones_tail(db, run_id, now=now)
    if isinstance(run, Mapping) and str(run.get("authorization_id", "")).startswith("onboarding:"):
        from infra.operations.zelerdata_read_model_reconcile import (
            create_runtime_historical_meli_gateways,
        )

        from zeler_sheets.history_onboarding import PlanBudgetGateway

        plan_id = str(run["authorization_id"]).removeprefix("onboarding:")
        plan = await db[ONBOARDING_PLANS_COLLECTION].find_one({"_id": plan_id})
        if not isinstance(plan, Mapping):
            raise ValueError("onboarding authority is absent")
        raw_gateway = create_runtime_historical_meli_gateways().order_detail_gateway
        budget_gateway = PlanBudgetGateway(
            db, raw_gateway, str(run["seller_id"]), ONBOARDING_SOURCE
        )
        if _onboarding_utc(run["end"]) > _onboarding_utc(plan["date_to"]):
            budget_gateway.incremental = True
        outcome = await advance_onboarding_devoluciones(
            db,
            plan,
            gateway=budget_gateway,
            start=run["start"],
            end=run["end"],
            now=now,
        )
        return {"advanced": int(outcome["advanced"]), "finalized": int(outcome["finalized"])}
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
    from zeler_platform_core.devoluciones_certificates import coverage_control

    if (await coverage_control(db, str(seller_id))).get("coverage_mode") == "active":
        summary = await renew_due_certificates(db, str(seller_id), now=now)
        return bool(summary["renewed"])
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


async def renew_due_certificates(
    db: Any,
    seller_id: str,
    *,
    now: Callable[[], datetime] | None = None,
    max_count: int = 20,
    seconds: float = 30,
) -> dict[str, Any]:
    import asyncio
    import time

    if not 1 <= max_count <= 20 or not 0 < seconds <= 30:
        raise ValueError("certificate renewal budget exceeds contract")
    deadline = time.monotonic() + seconds
    try:
        async with asyncio.timeout(seconds):
            return await _renew_due_certificates(
                db, seller_id, now=now, max_count=max_count, seconds=seconds, deadline=deadline
            )
    except TimeoutError:
        # Earlier certificates may have committed. Do not fabricate aggregate
        # zero counts; status/readback remains the durable authority.
        return {"attempted": None, "renewed": None, "failed": None, "reason": "budget_exhausted"}


async def _renew_due_certificates(
    db: Any,
    seller_id: str,
    *,
    now: Callable[[], datetime] | None = None,
    max_count: int = 20,
    seconds: float = 30,
    deadline: float,
) -> dict[str, Any]:
    """One indexed, bounded, source-free batch; failures cannot starve older due work."""
    import asyncio
    import time

    from zeler_platform_core.devoluciones_certificates import (
        CERTIFICATES,
        VALIDITY,
        CoverageUnavailableError,
        coverage_control,
        require_compatible,
        utc,
        validate_certificate,
        validate_provenance,
    )
    from zeler_platform_core.devoluciones_readiness import (
        DevolucionesLeaseConflictError,
        acquire_devoluciones_operation,
        finish_devoluciones_operation,
        guarded_devoluciones_write,
        maintain_devoluciones_heartbeat,
        new_devoluciones_attempt_token,
    )
    from zeler_sheets.devoluciones_reconciliation import current_certificate_facts

    if not 1 <= max_count <= 20 or not 0 < seconds <= 30:
        raise ValueError("certificate renewal budget exceeds contract")
    clock = now or (lambda: datetime.now(UTC))
    summary: dict[str, Any] = {"attempted": 0, "renewed": 0, "failed": 0, "reason": None}
    try:
        previous_control = await coverage_control(db, seller_id)
        require_compatible(previous_control)
    except CoverageUnavailableError:
        return summary | {"reason": "incompatible_writer"}
    started = time.monotonic()
    slowest = 0.0
    due = [
        row
        async for row in db[CERTIFICATES]
        .find({"seller_id": seller_id, "next_check_at": {"$lte": clock()}})
        .sort([("next_check_at", 1), ("_id", 1)])
        .limit(max_count)
        .max_time_ms(5000)
    ]
    if not due:
        return summary
    try:
        operation = await acquire_devoluciones_operation(
            db=db,
            seller_id=seller_id,
            scope="devoluciones",
            operation_id="certificate_renewal",
            attempt_token=new_devoluciones_attempt_token(),
            invalidate_readiness=False,
            require_coverage_compatible=True,
        )
    except DevolucionesLeaseConflictError:
        return summary | {"reason": "lease_busy"}
    try:
        async with maintain_devoluciones_heartbeat(db=db, operation=operation):
            for candidate in due:
                if time.monotonic() - started + 5 > seconds:
                    break
                summary["attempted"] += 1
                attempt_started = time.monotonic()

                async def renew(session: Any, candidate: dict[str, Any] = candidate) -> None:
                    document = await db[CERTIFICATES].find_one(
                        {"_id": candidate["_id"], "seller_id": seller_id}, session=session
                    )
                    if not document or document["coverage_epoch"] != operation.coverage_epoch:
                        raise CoverageUnavailableError("certificate epoch is not current")
                    validate_certificate(document, now=clock())
                    await validate_provenance(db, document, session=session)
                    facts = await current_certificate_facts(
                        db,
                        seller_id,
                        utc(document["date_from"]),
                        utc(document["date_to"]),
                        session=session,
                    )
                    if any(document[key] != value for key, value in facts.items()):
                        raise CoverageUnavailableError("certificate joint proof drift")
                    current = clock()
                    await db[CERTIFICATES].update_one(
                        {"_id": document["_id"], "revision": document["revision"]},
                        {
                            "$set": {
                                "validated_at": current,
                                "valid_until": current + VALIDITY,
                                "next_check_at": current + timedelta(minutes=12),
                                "state": "reconciled",
                                "needs_reacquisition": False,
                                "invalidation_reason": None,
                            }
                        },
                        session=session,
                    )

                try:
                    async with asyncio.timeout(5):
                        await guarded_devoluciones_write(
                            db=db,
                            operation=operation,
                            seller_id=seller_id,
                            checkpoint={
                                "phase": "certificate_renewal",
                                "certificate_id": candidate["_id"],
                            },
                            writer=renew,
                        )
                    summary["renewed"] += 1
                except Exception:  # noqa: BLE001 - every certification failure withdraws readiness
                    summary["failed"] += 1

                    async def withdraw(session: Any, candidate: dict[str, Any] = candidate) -> None:
                        await db[CERTIFICATES].update_one(
                            {"_id": candidate["_id"], "revision": candidate["revision"]},
                            {
                                "$set": {
                                    "state": "stale",
                                    "needs_reacquisition": True,
                                    "invalidation_reason": "proof_drift",
                                    "next_check_at": clock() + timedelta(minutes=12),
                                },
                                "$inc": {"revision": 1},
                            },
                            session=session,
                        )

                    await guarded_devoluciones_write(
                        db=db,
                        operation=operation,
                        seller_id=seller_id,
                        checkpoint={"phase": "certificate_renewal_failed"},
                        writer=withdraw,
                    )
                slowest = max(slowest, time.monotonic() - attempt_started)
        previous = previous_control.get("coverage_renewal") or {}
        observed = previous.get("observed_at")
        measurement = {
            "observed_at": clock(),
            "attempted": summary["attempted"],
            "slowest_seconds": max(slowest, float(previous.get("slowest_seconds", 0))),
            "observed_interval_seconds": (clock() - utc(observed)).total_seconds()
            if isinstance(observed, datetime)
            else None,
        }

        async def record_measurement(session: Any) -> None:
            await db[DEVOLUCIONES_OPERATIONS_COLLECTION].update_one(
                {"seller_id": seller_id, "fence": operation.fence},
                {"$set": {"coverage_renewal": measurement}},
                session=session,
            )

        await guarded_devoluciones_write(
            db=db,
            operation=operation,
            seller_id=seller_id,
            checkpoint={"phase": "certificate_batch_measurement"},
            writer=record_measurement,
        )
    finally:
        remaining = deadline - time.monotonic()
        if remaining > 0:
            async with asyncio.timeout(remaining):
                await finish_devoluciones_operation(db=db, operation=operation, succeeded=True)
        # On exhausted deadline, stop I/O. The existing 120s lease expires;
        # never add an unbounded cleanup operation outside the batch budget.
    summary["elapsed_seconds"] = time.monotonic() - started
    return summary


# Product policy authority is distinct from the pilot CLI's operator boundary.
# Runs keep the original immutable binding/schema and exact readback gates.
ONBOARDING_PLANS_COLLECTION = "sheets_history_backfill_plans"
ONBOARDING_SOURCE = "claims_returns"
ONBOARDING_POLICY = "history-on-link-v1"


def _onboarding_utc(value: Any) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError("onboarding plan bounds are invalid")
    # Default BSON codecs decode dates as naive UTC; never interpret local TZ.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def _validated_onboarding_plan(
    db: Any,
    plan: Mapping[str, Any],
    *,
    charged: bool = False,
    start: datetime | None = None,
    end: datetime | None = None,
    now: datetime | None = None,
) -> Mapping[str, Any]:
    persisted = await db[ONBOARDING_PLANS_COLLECTION].find_one({"_id": plan.get("_id")})
    if isinstance(persisted, Mapping) and (
        persisted.get("state") != "active" or persisted.get("eligible") is not True
    ):
        raise HistoryPolicyWaitError("onboarding execution is held or no longer eligible")
    identity_fields = ("seller_id", "policy_version", "sources", "authority")
    date_fields = ("date_from", "date_to", "cutoff")
    if (
        not isinstance(persisted, Mapping)
        or not str(persisted.get("seller_id") or "").strip()
        or any(persisted.get(key) != plan.get(key) for key in identity_fields)
        or any(
            _onboarding_utc(persisted.get(key)) != _onboarding_utc(plan.get(key))
            for key in date_fields
        )
        or persisted.get("state") != "active"
        or persisted.get("eligible") is not True
        or plan.get("state") != "active"
        or plan.get("eligible") is not True
        or persisted.get("policy_version") != ONBOARDING_POLICY
        or persisted.get("authority", {}).get("kind") != "account_link_policy"
        or ONBOARDING_SOURCE not in persisted.get("sources", [])
    ):
        raise ValueError("onboarding policy authority is invalid or no longer eligible")
    if not history_execution_allowed(persisted, now=now or datetime.now(UTC), charged=charged):
        raise HistoryPolicyWaitError(
            "onboarding execution window or global attempt limit exhausted"
        )
    incremental = end is not None and _onboarding_utc(end) > _onboarding_utc(persisted["date_to"])
    if start is not None or end is not None:
        _onboarding_binding(persisted, start, end)
    budget = persisted.get("budget", {}).get(ONBOARDING_SOURCE, {}).get("physical_attempts")
    consumed = persisted.get("budget", {}).get(ONBOARDING_SOURCE, {}).get("consumed", 0)
    requested_budget = plan.get("budget", {}).get(ONBOARDING_SOURCE, {}).get("physical_attempts")
    if (
        type(budget) is not int
        or type(consumed) is not int
        or budget != requested_budget
        or budget < 1
        or consumed < 0
        or consumed > budget
        or (not incremental and not charged and consumed == budget)
    ):
        raise ValueError("onboarding source budget is exhausted or invalid")
    if incremental:
        policy = persisted.get("incremental_policy")
        if not isinstance(policy, Mapping) or policy != plan.get("incremental_policy"):
            raise ValueError("incremental budget policy is absent or has drifted")
        today = _onboarding_utc(now or datetime.now(UTC)).date().isoformat()
        same_day = persisted.get("incremental_day") == today
        limits = (
            (
                policy.get("max_daily_total"),
                persisted.get("incremental_consumed", 0) if same_day else 0,
            ),
            (
                policy.get("max_daily_source"),
                persisted.get("incremental_source_consumed", {}).get(ONBOARDING_SOURCE, 0)
                if same_day
                else 0,
            ),
        )
        for maximum, spent in limits:
            if (
                type(maximum) is not int
                or type(spent) is not int
                or maximum < 1
                or spent < 0
                or spent > maximum
                or (not charged and spent == maximum)
            ):
                raise ValueError("incremental daily budget is exhausted or invalid")
    start, end, cutoff = (_onboarding_utc(persisted[key]) for key in date_fields)
    if not start < end <= cutoff:
        raise ValueError("onboarding range is outside the stable cutoff")
    return persisted


def _onboarding_binding(
    plan: Mapping[str, Any], start: datetime | None, end: datetime | None
) -> Any:
    import hashlib
    import json

    from zeler_platform_core.devoluciones_runs import WINDOW_DAYS, RunBinding

    lower, upper = _onboarding_utc(plan["date_from"]), _onboarding_utc(plan["date_to"])
    start = _onboarding_utc(start) if start is not None else lower
    end = (
        _onboarding_utc(end) if end is not None else min(start + timedelta(days=WINDOW_DAYS), upper)
    )
    initial = lower <= start < end <= upper
    if not initial:
        scope = plan.get("incremental_scopes", {}).get(ONBOARDING_SOURCE)
        if not isinstance(scope, Mapping) or scope.get("policy_version") != ONBOARDING_POLICY:
            raise ValueError("onboarding unit is outside its authorized bounded range")
        scope_start, scope_end = (
            _onboarding_utc(scope.get("date_from")),
            _onboarding_utc(scope.get("date_to")),
        )
        if (
            not upper - timedelta(minutes=5) <= scope_start <= start < end <= scope_end
            or scope_end - scope_start > timedelta(days=1)
            or end - start > timedelta(days=1)
        ):
            raise ValueError("incremental unit is outside its authorized bounded range")
    if end - start > timedelta(days=WINDOW_DAYS):
        raise ValueError("onboarding unit is outside its authorized bounded range")
    policy = json.dumps(
        {
            "policy": plan["policy_version"],
            "seller": plan["seller_id"],
            "lower": lower.isoformat(),
            "upper": upper.isoformat(),
            "budget": plan["budget"][ONBOARDING_SOURCE]["physical_attempts"]
            if initial
            else plan.get("incremental_policy"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return RunBinding(
        authorization_id=f"onboarding:{plan['_id']}",
        cohort_id=ONBOARDING_POLICY,
        seller_id=str(plan["seller_id"]),
        scope="devoluciones",
        start=start,
        end=end,
        partition_version="v1",
        release_fingerprints={"onboarding_policy": hashlib.sha256(policy.encode()).hexdigest()},
    )


async def _require_onboarding_certificate_mode(db: Any, seller_id: str, current: datetime) -> None:
    """Only absence of coverage authority can initialize; legacy proof must migrate."""
    from zeler_platform_core.devoluciones_certificates import CERTIFICATES, coverage_control

    control = await coverage_control(db, seller_id)
    if control.get("coverage_mode") == "active":
        if control.get("coverage_ack_fence") != control.get("fence"):
            raise ValueError("onboarding certificate writer is incompatible")
        return
    if control:
        raise ValueError("onboarding requires legacy certificate migration")
    client = getattr(db, "client", None)
    if client is None:
        raise ValueError("onboarding certificate initialization requires a transaction")
    session = client.start_session()
    if hasattr(session, "__await__"):
        session = await session
    async with session, session.start_transaction():
        marker = await db[FRESHNESS_COLLECTION].find_one(
            {"seller_id": seller_id, "read_model": "devoluciones"}, session=session
        )
        certificate = await db[CERTIFICATES].find_one({"seller_id": seller_id}, session=session)
        # Bootstrap rows are facts, not coverage authority. Preserve them, but
        # never promote them to certificates without joint source/readback.
        if marker is not None or certificate is not None:
            raise ValueError("onboarding requires legacy certificate migration")
        await db[DEVOLUCIONES_OPERATIONS_COLLECTION].update_one(
            {"_id": f"{seller_id}:devoluciones"},
            {
                "$setOnInsert": {
                    "_id": f"{seller_id}:devoluciones",
                    "seller_id": seller_id,
                    "scope": "devoluciones",
                    "operation_id": "onboarding_initialize",
                    "attempt_token": "onboarding_initialize",
                    "state": "released",
                    "fence": 1,
                    "coverage_ack_fence": 1,
                    "coverage_epoch": 0,
                    "coverage_mode": "active",
                    "lease_until": current,
                    "heartbeat_at": current,
                    "started_at": current,
                    "updated_at": current,
                    "schema_version": 1,
                }
            },
            upsert=True,
            session=session,
        )
    # A concurrent writer must not silently turn a fresh-account initialization
    # into automatic migration or overwrite an existing coverage fence.
    control = await coverage_control(db, seller_id)
    if control.get("coverage_mode") != "active" or control.get("coverage_ack_fence") != control.get(
        "fence"
    ):
        raise ValueError("onboarding requires legacy certificate migration")


async def admit_onboarding_devoluciones(
    db: Any,
    plan: Mapping[str, Any],
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    now: Callable[[], datetime] | None = None,
) -> str:
    """Admit/reuse one <=10-day exact run from persisted account-link policy.

    No environment authority file, manual monthly prompt, source request, or
    certificate publication occurs here. Failed units remain failed; other
    independent units can still complete and publish their own exact proofs.
    """
    from zeler_platform_core.devoluciones_readiness import (
        new_devoluciones_attempt_token,
        stable_devoluciones_operation_id,
    )

    clock = now or (lambda: datetime.now(UTC))
    current = _onboarding_utc(clock())
    persisted = await _validated_onboarding_plan(
        db, plan, charged=True, start=start, end=end, now=current
    )
    binding = _onboarding_binding(persisted, start, end)
    if binding.end > current:
        raise ValueError("onboarding cannot acquire a future interval")
    existing = await db[RUNS_COLLECTION].find_one({"_id": binding.run_id})
    if existing is not None:
        _require_onboarding_run_binding(existing, binding)
        await _require_onboarding_certificate_mode(db, binding.seller_id, current)
        return str(binding.run_id)
    await _validated_onboarding_plan(db, plan, start=binding.start, end=binding.end, now=current)
    await _require_onboarding_certificate_mode(db, binding.seller_id, current)
    operation = await _acquire_onboarding_operation(
        db=db,
        seller_id=binding.seller_id,
        scope="devoluciones",
        operation_id=stable_devoluciones_operation_id("onboarding_admit", binding.run_id),
        attempt_token=new_devoluciones_attempt_token(),
        source_fingerprint=binding.run_id,
        invalidate_readiness=False,
        require_coverage_compatible=True,
    )
    try:
        await _validated_onboarding_plan(
            db, plan, start=binding.start, end=binding.end, now=current
        )
        if not await _OnboardingRepository(db).create(
            binding, operation=operation, created_at=current
        ):
            raise RuntimeError("onboarding exact run admission failed")
    except Exception:
        await _finish_onboarding_operation(
            db=db, operation=operation, succeeded=False, error_code="onboarding_admission_failed"
        )
        raise
    await _finish_onboarding_operation(db=db, operation=operation, succeeded=True)
    return str(binding.run_id)


def _require_onboarding_run_binding(run: Mapping[str, Any], binding: Any) -> None:
    if (
        run.get("_id") != binding.run_id
        or run.get("seller_id") != binding.seller_id
        or run.get("scope") != binding.scope
        or run.get("authorization_id") != binding.authorization_id
        or run.get("cohort_id") != binding.cohort_id
        or run.get("partition_version") != binding.partition_version
        or run.get("release_fingerprints") != dict(binding.release_fingerprints)
        or _onboarding_utc(run.get("start")) != binding.start
        or _onboarding_utc(run.get("end")) != binding.end
    ):
        raise ValueError("onboarding run binding drift")


class OnboardingDevolucionesGateway:
    """Validate current authority before every single physical upstream attempt."""

    def __init__(
        self,
        db: Any,
        plan: Mapping[str, Any],
        gateway: Any,
        *,
        charge: Callable[[], Awaitable[None]],
        start: datetime | None = None,
        end: datetime | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.db, self.plan, self.gateway, self.charge = db, plan, gateway, charge
        self.start, self.end = start, end
        self.now = now or (lambda: datetime.now(UTC))

    async def fetch_resource_once(self, *, seller_id: str, path: str) -> dict[str, Any]:
        import re

        if (
            seller_id != str(self.plan.get("seller_id"))
            or re.fullmatch(
                r"/(?:orders/[0-9]+|post-purchase/v1/claims/(?:search|[0-9]+)|"
                r"post-purchase/v2/claims/[0-9]+/returns)(?:\?[^#]*)?",
                path,
            )
            is None
        ):
            raise ValueError("onboarding request is outside source authority")
        persisted = await _validated_onboarding_plan(
            self.db, self.plan, start=self.start, end=self.end, now=self.now()
        )
        if self.start is not None or self.end is not None:
            _onboarding_binding(persisted, self.start, self.end)
        await self.charge()
        # Charging is durable and may race with pause/revocation; reread before
        # sending. An in-flight HTTP request cannot be retroactively unsent.
        persisted = await _validated_onboarding_plan(
            self.db, self.plan, charged=True, start=self.start, end=self.end, now=self.now()
        )
        if self.start is not None or self.end is not None:
            _onboarding_binding(persisted, self.start, self.end)
        trace = history_request_trace(
            persisted,
            ONBOARDING_SOURCE,
            incremental=self.end is not None
            and _onboarding_utc(self.end) > _onboarding_utc(persisted["date_to"]),
        )
        physical_gateway = await admit_paced_dispatch(self.gateway)
        if not history_execution_allowed(persisted, now=self.now(), charged=True):
            raise HistoryPolicyWaitError("history execution window ended after pacing")
        async with history_policy_dispatch():
            from zeler_platform_core.clients.meli_gateway_client import GatewayRateLimitError
            from zeler_sheets.history_pilot_stop import stop_pilot_429

            try:
                return cast(
                    "dict[str, Any]",
                    await physical_gateway.fetch_resource_once(
                        seller_id=seller_id,
                        path=path,
                        **({"headers": {"X-Zeler-History-Trace": trace}} if trace else {}),
                    ),
                )
            except (GatewayRateLimitError, httpx.HTTPStatusError) as error:
                await stop_pilot_429(
                    self.db,
                    captured=self.plan,
                    validated=persisted,
                    response=error.response,
                    now=self.now(),
                )
                raise

    async def fetch_resource(self, *, seller_id: str, path: str) -> dict[str, Any]:
        return await self.fetch_resource_once(seller_id=seller_id, path=path)


async def advance_onboarding_devoluciones(
    db: Any,
    plan: Mapping[str, Any],
    *,
    gateway: Any,
    charge: Callable[[], Awaitable[None]] | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    now: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Advance one exact bounded unit with real scopes, fences and physical quotas."""
    from infra.operations.zelerdata_read_model_reconcile import (
        advance_devoluciones_quota_run,
        execute_devoluciones_quota_window,
        readback_devoluciones_quota_run,
    )

    from zeler_platform_core.devoluciones_readiness import (
        new_devoluciones_attempt_token,
        stable_devoluciones_operation_id,
    )
    from zeler_sheets.devoluciones_reconciliation import (
        GatewayDevolucionesSource,
        _private_focused_devoluciones_diagnostic,
    )
    from zeler_sheets.history_pilot_stop import HistoryPilotStopError

    if charge is None:
        charge = getattr(gateway, "charge", None)
        gateway = getattr(gateway, "inner", gateway)
    if not callable(charge):
        raise ValueError("onboarding requires durable physical-attempt charging")
    clock = now or (lambda: datetime.now(UTC))
    run_id = await admit_onboarding_devoluciones(db, plan, start=start, end=end, now=clock)
    run = await db[RUNS_COLLECTION].find_one({"_id": run_id})
    if not isinstance(run, Mapping):
        raise RuntimeError("admitted onboarding run is absent")
    unchanged = {"run_id": run_id, "state": run["state"], "advanced": 0, "finalized": 0}
    if run["state"] not in ADVANCEABLE_RUN_STATES:
        return unchanged
    current = _onboarding_utc(clock())
    if current >= _onboarding_utc(run["expires_at"]):
        await db[RUNS_COLLECTION].update_one(
            {"_id": run_id, "state": run["state"]},
            {"$set": {"state": "expired", "updated_at": current}},
        )
        return unchanged | {"state": "expired"}
    if run.get("not_before") is not None and current < _onboarding_utc(run["not_before"]):
        return unchanged
    await _require_onboarding_certificate_mode(db, str(plan["seller_id"]), current)
    await _renew_active_before_advance(db, str(plan["seller_id"]), clock)
    operation = await _acquire_onboarding_operation(
        db=db,
        seller_id=str(plan["seller_id"]),
        scope="devoluciones",
        operation_id=stable_devoluciones_operation_id("onboarding_advance", run_id),
        attempt_token=new_devoluciones_attempt_token(),
        source_fingerprint=run_id,
        invalidate_readiness=False,
        require_coverage_compatible=True,
    )
    client = OnboardingDevolucionesGateway(
        db, plan, gateway, charge=charge, start=run["start"], end=run["end"], now=clock
    )
    source = GatewayDevolucionesSource(client, single_attempt=True)
    failure_reason: str | None = None

    async def execute(*, window: Mapping[str, Any], **_: Any) -> dict[str, Any]:
        from zeler_sheets.devoluciones_reconciliation import SourceCallBudgetError

        nonlocal failure_reason
        try:
            return await execute_devoluciones_quota_window(
                db=db,
                window=window,
                operation=operation,
                source=source,
                now=clock,
            )
        except HistoryPilotStopError as stopped:
            raise HistoryPolicyWaitError(stopped.reason) from None
        except HistoryPolicyWaitError:
            raise
        except SourceCallBudgetError:
            failure_reason = "physical_budget_exceeded"
            raise
        except Exception as error:
            failure_reason = "exact_source_proof_unavailable"
            # Preserve the original source failure even if logging is unavailable.
            # Only the existing closed, typed diagnostic crosses this boundary.
            with suppress(Exception):
                logger.warning(
                    "sheets.devoluciones_onboarding_source_proof_unavailable",
                    **_private_focused_devoluciones_diagnostic(error),
                )
            raise

    try:
        # Final readback is local and needs no additional source allowance.
        # The gateway still refuses every new physical request when exhausted.
        await _validated_onboarding_plan(
            db, plan, charged=True, start=run["start"], end=run["end"], now=clock()
        )
        outcome = await advance_devoluciones_quota_run(
            db=db,
            run_id=run_id,
            operation=operation,
            now=clock,
            source=execute,
            readback=lambda **kwargs: readback_devoluciones_quota_run(db=db, **kwargs),
        )
    except HistoryPolicyWaitError:
        await _finish_onboarding_operation(
            db=db, operation=operation, succeeded=False, error_code="onboarding_policy_wait"
        )
        return unchanged | {"reason": "policy_wait"}
    except Exception:
        await _finish_onboarding_operation(
            db=db, operation=operation, succeeded=False, error_code="onboarding_advancement_failed"
        )
        raise
    await _finish_onboarding_operation(db=db, operation=operation, succeeded=True)
    updated = await db[RUNS_COLLECTION].find_one({"_id": run_id})
    result = {"run_id": run_id, "state": updated["state"] if updated else "failed", **outcome}
    if failure_reason is not None:
        result["reason"] = failure_reason
    return result


# Ordinary forward tail. The pilot's incremental claims run was the only thing
# extending certified coverage; with the pilot paused, coverage froze and every
# current DEVOLUCIONES range became unavailable (2026-10-07). The tail runs only
# with history on link off, so it never competes with a live pilot plan.
ORDINARY_TAIL_AUTHORIZATION = "refresh-tail:v1"
ORDINARY_TAIL_COHORT = "zelerdata-refresh-tail-v1"
# Claims created just before midnight need a moment to appear in the search.
ORDINARY_TAIL_SETTLE = timedelta(hours=1)
# One partition window per run keeps each run inside the existing call budget.
ORDINARY_TAIL_MAX = timedelta(days=WINDOW_DAYS)


def ordinary_tail_bounds(
    coverage_end: datetime | None, *, now: datetime
) -> tuple[datetime, datetime] | None:
    """Return the next unacquired interval up to the last settled UTC midnight.

    The tail only moves forward from the newest certified interval. It never
    starts without certified coverage: initial acquisition stays with the
    operator or the onboarding policy.
    """
    if coverage_end is None:
        return None
    start = _onboarding_utc(coverage_end)
    settled = _onboarding_utc(now) - ORDINARY_TAIL_SETTLE
    end = min(datetime.combine(settled.date(), time.min, tzinfo=UTC), start + ORDINARY_TAIL_MAX)
    return (start, end) if start < end else None


def ordinary_tail_binding(
    seller_id: str, start: datetime, end: datetime, *, admitted_on: date
) -> RunBinding:
    # The admission day is part of the identity, so a failed or expired run is
    # retried at most once per UTC day instead of on every cycle.
    return RunBinding(
        authorization_id=ORDINARY_TAIL_AUTHORIZATION,
        cohort_id=ORDINARY_TAIL_COHORT,
        seller_id=seller_id,
        scope="devoluciones",
        start=start,
        end=end,
        partition_version="v1",
        release_fingerprints={"admitted_on": admitted_on.isoformat()},
    )


async def admit_ordinary_devoluciones_tail(
    db: Any, seller_id: str, *, now: Callable[[], datetime] | None = None
) -> str | None:
    """Admit the ordinary tail run, or return ``None`` when none is due."""
    from zeler_platform_core.devoluciones_certificates import CERTIFICATES, coverage_control
    from zeler_platform_core.devoluciones_readiness import (
        new_devoluciones_attempt_token,
        stable_devoluciones_operation_id,
    )

    current = _onboarding_utc((now or (lambda: datetime.now(UTC)))())
    control = await coverage_control(db, seller_id)
    if (
        control.get("coverage_mode") != "active"
        or control.get("coverage_ack_fence") != control.get("fence")
        or type(control.get("coverage_epoch")) is not int
    ):
        return None
    latest = await db[CERTIFICATES].find_one(
        {"seller_id": seller_id, "coverage_epoch": control["coverage_epoch"]},
        sort=[("date_to", -1)],
    )
    bounds = ordinary_tail_bounds(
        latest.get("date_to") if isinstance(latest, Mapping) else None, now=current
    )
    if bounds is None:
        return None
    binding = ordinary_tail_binding(seller_id, *bounds, admitted_on=current.date())
    if await db[RUNS_COLLECTION].find_one({"_id": binding.run_id}) is not None:
        return None
    operation = await _acquire_onboarding_operation(
        db=db,
        seller_id=seller_id,
        scope="devoluciones",
        operation_id=stable_devoluciones_operation_id("refresh_tail_admit", binding.run_id),
        attempt_token=new_devoluciones_attempt_token(),
        source_fingerprint=binding.run_id,
        invalidate_readiness=False,
        require_coverage_compatible=True,
    )
    try:
        if not await _OnboardingRepository(db).create(
            binding, operation=operation, created_at=current
        ):
            raise RuntimeError("ordinary tail admission failed")
    except Exception:
        await _finish_onboarding_operation(
            db=db, operation=operation, succeeded=False, error_code="refresh_tail_admission_failed"
        )
        raise
    await _finish_onboarding_operation(db=db, operation=operation, succeeded=True)
    logger.info(
        "zelerdata.devoluciones_tail_admitted",
        seller_id=seller_id,
        run_id=binding.run_id,
        start=binding.start.isoformat(),
        end=binding.end.isoformat(),
    )
    return str(binding.run_id)


async def advance_ordinary_devoluciones_tail(
    db: Any, run_id: str, *, now: Callable[[], datetime] | None = None
) -> dict[str, int]:
    """Advance one tail window through the ordinary runtime gateway."""
    from infra.operations.zelerdata_read_model_reconcile import (
        DevolucionesQuotaProofError,
        _finalize_devoluciones_quota_run,
        advance_devoluciones_quota_run,
        execute_devoluciones_quota_window,
        readback_devoluciones_quota_run,
    )

    from zeler_platform_core.devoluciones_readiness import (
        new_devoluciones_attempt_token,
        stable_devoluciones_operation_id,
    )
    from zeler_sheets.devoluciones_reconciliation import _private_focused_devoluciones_diagnostic

    clock = now or (lambda: datetime.now(UTC))

    run = await db[RUNS_COLLECTION].find_one({"_id": run_id})
    if not isinstance(run, Mapping) or run.get("authorization_id") != ORDINARY_TAIL_AUTHORIZATION:
        raise ValueError("run is not an ordinary tail run")
    seller_id = str(run["seller_id"])

    async def readback(**kwargs: Any) -> Mapping[str, Any]:
        try:
            return await readback_devoluciones_quota_run(db=db, **kwargs)
        except Exception as exc:
            # Finalization turns this into a failed run without a trace.
            logger.warning(
                "zelerdata.devoluciones_tail_failed",
                phase="readback",
                seller_id=seller_id,
                run_id=run_id,
                error_type=type(exc).__name__,
            )
            raise

    operation = await _acquire_onboarding_operation(
        db=db,
        seller_id=seller_id,
        scope="devoluciones",
        operation_id=stable_devoluciones_operation_id("refresh_tail_advance", run_id),
        attempt_token=new_devoluciones_attempt_token(),
        source_fingerprint=run_id,
        invalidate_readiness=False,
        require_coverage_compatible=True,
    )

    async def execute(*, window: Mapping[str, Any], **_: Any) -> dict[str, Any]:
        # No source override: the window uses the ordinary runtime gateway and
        # the existing per-window physical attempt ledger. A pre-v2 row the
        # inventory no longer reports would fail the final readback every day
        # (2026-10-08), so the tail quarantines it. A listed claim whose detail
        # Mercado Libre forbids failed the window every day (2026-10-09), so
        # the tail excludes one such claim per window.
        try:
            proof = await execute_devoluciones_quota_window(
                db=db,
                window=window,
                operation=operation,
                now=clock,
                quarantine_legacy_claims=True,
                exclude_forbidden_claim_details=True,
            )
        except HistoryPolicyWaitError:
            raise
        except Exception as exc:
            # The quota runner turns every source failure into a failed run
            # without a trace (2026-10-09/10). Bounded fields only: no
            # exception text, URL or token.
            counts = exc.counts if isinstance(exc, DevolucionesQuotaProofError) else {}
            logger.warning(
                "zelerdata.devoluciones_tail_failed",
                phase="window",
                seller_id=seller_id,
                run_id=run_id,
                window_index=window.get("index"),
                error_type=type(exc).__name__,
                **_private_focused_devoluciones_diagnostic(exc),
                **counts,
            )
            raise
        if proof.get("quarantined_legacy_claims"):
            logger.info(
                "zelerdata.devoluciones_legacy_claims_quarantined",
                seller_id=seller_id,
                run_id=run_id,
                count=proof["quarantined_legacy_claims"],
            )
        if proof.get("excluded_claim_detail_forbidden"):
            logger.warning(
                "zelerdata.devoluciones_forbidden_claim_excluded",
                seller_id=seller_id,
                run_id=run_id,
                window_index=window.get("index"),
                count=proof["excluded_claim_detail_forbidden"],
                claim_ids=proof.get("forbidden_claim_ids"),
            )
        return proof

    try:
        outcome = await advance_devoluciones_quota_run(
            db=db,
            run_id=run_id,
            operation=operation,
            now=clock,
            source=execute,
            readback=readback,
        )
        advanced = await db[RUNS_COLLECTION].find_one({"_id": run_id})
        if (
            outcome.get("advanced")
            and isinstance(advanced, Mapping)
            and advanced.get("state") == "active"
            and int(advanced.get("next_window_index", 0)) >= int(advanced.get("window_count", 1))
        ):
            # A one-window run expires 1070 s after admission, but the next
            # cycle arrives only after this cycle's work plus the 900 s
            # interval. Finalization makes no source calls, so publish now
            # instead of letting the tail expire unfinalized on busy cycles.
            finalized = await _finalize_devoluciones_quota_run(
                db=db, run=advanced, operation=operation, current=clock(), readback=readback
            )
            outcome = {"advanced": outcome["advanced"], "finalized": finalized["finalized"]}
            if not finalized["finalized"]:
                logger.warning(
                    "zelerdata.devoluciones_tail_failed",
                    phase="finalize",
                    seller_id=seller_id,
                    run_id=run_id,
                )
    except Exception:
        await _finish_onboarding_operation(
            db=db,
            operation=operation,
            succeeded=False,
            error_code="refresh_tail_advancement_failed",
        )
        raise
    await _finish_onboarding_operation(db=db, operation=operation, succeeded=True)
    return outcome
