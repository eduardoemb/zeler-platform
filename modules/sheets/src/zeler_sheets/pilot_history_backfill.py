"""Runtime history backfill callback for the refresh supervisor.

Receives a seller ID, regenerates the 12-month plan deterministically from
the persisted cutoff and records every chunk's observed queue state. Returns
True when at least one enqueue call succeeds, including concurrent coalescence;
the return value does not prove this callback inserted a new job.

This module does not call Mercado Libre and does not bypass any queue guard:
it reuses ``FormulaRecoveryQueue.enqueue`` so dedup, capacity, leases and
seller allowlists all apply unchanged.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog
from pymongo import ReturnDocument

from zeler_sheets.formulas.read_models import read_model_reconciliation_marker_covers
from zeler_sheets.formulas.recovery import (
    OrderHistoryRecoveryRequest,
    QuestionScanRecoveryRequest,
    RecoveryCapacityError,
)
from zeler_sheets.pilot_history import ChunkPriority, HistoryPlanner
from zeler_sheets.pilot_history_recovery_bridge import chunk_to_recovery_request

logger = structlog.get_logger(__name__)

__all__ = ["build_pilot_history_backfill"]

PLAN_COLLECTION = "sheets_history_backfill_plans"
PILOT_HISTORY_ACTIVE_JOBS = 4


def build_pilot_history_backfill(
    *,
    db: Any,
    recovery_queue: Any,
    order_history: bool = False,
    question_history: bool = False,
) -> Any:
    """Return an async callable(seller_id) -> bool for the refresh supervisor."""

    async def history_backfill(seller_id: str) -> bool:
        seller_id = str(seller_id).strip()
        if not seller_id:
            return False
        plan_collection = db[PLAN_COLLECTION]
        plan_doc = await plan_collection.find_one({"_id": seller_id})
        if plan_doc is None:
            cutoff = datetime.now(UTC).replace(microsecond=0)
            plan_doc = await plan_collection.find_one_and_update(
                {"_id": seller_id},
                {
                    "$setOnInsert": {
                        "seller_id": seller_id,
                        "cutoff": cutoff,
                        "schema_version": 1,
                    }
                },
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
        if plan_doc is not None and plan_doc.get("policy_version") == "history-on-link-v1":
            # The account-link coordinator owns new admission under this plan.
            # Existing legacy work drains normally; never duplicate its year.
            return False
        stored_cutoff = plan_doc.get("cutoff") if plan_doc is not None else None
        if not isinstance(stored_cutoff, datetime) or stored_cutoff.tzinfo is None:
            logger.warning("zelerdata.history_backfill_invalid_cutoff", seller_id=seller_id)
            return False
        cutoff = stored_cutoff.astimezone(UTC)
        planner = HistoryPlanner(cutoff=cutoff, months=12)
        order_plan_id = f"pilot-12m:{cutoff.isoformat(timespec='milliseconds')}"
        question_plan = planner.plan_for("questions")
        question_scan = QuestionScanRecoveryRequest(
            seller_id, order_plan_id, question_plan.chunks[0].start, cutoff
        )

        resources = ("orders", "questions", "shipments", "items")
        priorities = {
            ChunkPriority.RECENT: 0,
            ChunkPriority.OLDEST_EDGE: 1,
            ChunkPriority.MIDDLE: 2,
        }
        chunks = sorted(
            (chunk for resource in resources for chunk in planner.plan_for(resource).chunks),
            key=lambda chunk: (priorities[chunk.priority], chunk.start, chunk.resource),
        )
        requests = {
            chunk.id: (
                OrderHistoryRecoveryRequest(seller_id, order_plan_id, chunk.start, chunk.end)
                if order_history and chunk.resource == "orders"
                else question_scan
                if question_history and chunk.resource == "questions"
                else chunk_to_recovery_request(chunk, seller_id=seller_id)
            )
            for chunk in chunks
            if chunk.resource in {"orders", "questions"}
        }
        completed_order_proofs: dict[str, str] = {}
        if not order_history:
            # A legacy planner may still run after the plan-bound order protocol
            # has completed. Its old request keys differ, so queue dedup alone
            # would reacquire the same twelve months on every worker restart.
            order_chunks = [chunk for chunk in chunks if chunk.resource == "orders"]
            proof_requests = {
                chunk.id: OrderHistoryRecoveryRequest(
                    seller_id, order_plan_id, chunk.start, chunk.end
                )
                for chunk in order_chunks
            }
            proof_jobs = {
                job["_id"]: job
                for job in await recovery_queue.collection.find(
                    {
                        "_id": {
                            "$in": [proof_request.key for proof_request in proof_requests.values()]
                        },
                        "seller_id": seller_id,
                        "read_model": "orders",
                        "history_protocol_version": 1,
                        "history_plan_id": order_plan_id,
                        "state": "completed",
                    },
                    {"date_from": 1, "date_to": 1},
                ).to_list(length=len(order_chunks))
            }
            marker = await db["sheets_read_model_freshness"].find_one(
                {"_id": f"{seller_id}:orders", "seller_id": seller_id, "read_model": "orders"}
            )
            for chunk in order_chunks:
                proof_request = proof_requests[chunk.id]
                job = proof_jobs.get(proof_request.key)
                if (
                    job is not None
                    and _same_utc_instant(job.get("date_from"), chunk.start)
                    and _same_utc_instant(job.get("date_to"), chunk.end)
                    and read_model_reconciliation_marker_covers(
                        marker, date_from=chunk.start, date_to=chunk.end
                    )
                ):
                    completed_order_proofs[chunk.id] = proof_request.key
        history_budget = len({request.key for request in requests.values()})
        active_history = 0
        if type(recovery_queue.max_active_jobs_per_seller) is int and (
            recovery_queue.max_active_jobs_per_seller > PILOT_HISTORY_ACTIVE_JOBS
        ):
            history_budget = PILOT_HISTORY_ACTIVE_JOBS
            history_keys = {request.key for request in requests.values()}
            if order_history:
                # Count both new orders and legacy monthly jobs after the switch.
                history_keys.update(
                    chunk_to_recovery_request(chunk, seller_id=seller_id).key
                    for chunk in chunks
                    if chunk.resource == "orders"
                )
            if question_history:
                history_keys.update(
                    chunk_to_recovery_request(chunk, seller_id=seller_id).key
                    for chunk in chunks
                    if chunk.resource == "questions"
                )
            active_history = await recovery_queue.collection.count_documents(
                {
                    "_id": {"$in": list(history_keys)},
                    "seller_id": seller_id,
                    "state": {"$in": ["pending", "running"]},
                }
            )
        states = ("queued", "running", "completed", "failed", "pending", "blocked")
        progress: dict[str, dict[str, Any]] = {
            resource: {
                **dict.fromkeys(states, 0),
                "accepted_or_coalesced_this_cycle": 0,
                "chunks": [],
            }
            for resource in resources
        }
        capacity_reached = active_history >= history_budget
        accepted = False
        legacy_active: set[str] = set()
        if question_history:
            legacy_question_keys = [
                chunk_to_recovery_request(chunk, seller_id=seller_id).key
                for chunk in question_plan.chunks
            ]
            if await recovery_queue.collection.count_documents(
                {
                    "_id": {"$in": legacy_question_keys},
                    "seller_id": seller_id,
                    "state": {"$in": ["pending", "running"]},
                },
                limit=1,
            ):
                legacy_active.update(chunk.id for chunk in question_plan.chunks)
        for chunk in chunks:
            request = requests.get(chunk.id)
            if request is None or capacity_reached or chunk.id in completed_order_proofs:
                continue
            job = await recovery_queue.collection.find_one(
                {"_id": request.key, "seller_id": seller_id}, {"state": 1}
            )
            if job is not None:
                continue
            if chunk.id in legacy_active:
                continue
            if order_history and chunk.resource == "orders":
                legacy_key = chunk_to_recovery_request(chunk, seller_id=seller_id).key
                legacy = await recovery_queue.collection.find_one(
                    {"_id": legacy_key, "seller_id": seller_id}, {"state": 1}
                )
                if legacy is not None and legacy.get("state") in {"pending", "running"}:
                    legacy_active.add(chunk.id)
                    continue
            try:
                await recovery_queue.enqueue(request, reopen_terminal=False)
            except RecoveryCapacityError:
                capacity_reached = True
            else:
                progress[chunk.resource]["accepted_or_coalesced_this_cycle"] += 1
                accepted = True
                active_history += 1
                capacity_reached = active_history >= history_budget
        for chunk in chunks:
            entry: dict[str, Any] = {
                "chunk_id": chunk.id,
                "date_from": chunk.start,
                "date_to": chunk.end,
                "state": "blocked",
                "reason": "acquisition_path_unresolved",
            }
            request = requests.get(chunk.id)
            if chunk.id in completed_order_proofs:
                entry.update(
                    request_key=completed_order_proofs[chunk.id],
                    state="completed",
                    reason="completed_history_proof",
                    attempts=0,
                )
            elif request is not None:
                job = await recovery_queue.collection.find_one(
                    {"_id": request.key, "seller_id": seller_id}, {"state": 1, "attempts": 1}
                )
                state = job.get("state") if job else None
                entry.update(
                    request_key=request.key,
                    state="queued" if state == "pending" else state or "pending",
                    reason="job_failed" if state == "failed" else None,
                    attempts=job.get("attempts", 0) if job else 0,
                )
                if job is None and capacity_reached:
                    entry["reason"] = "capacity_deferred"
                if job is None and chunk.id in legacy_active:
                    entry.update(state="blocked", reason="legacy_order_job_active")
            entry["observed_at"] = datetime.now(UTC)
            progress[chunk.resource][entry["state"]] += 1
            progress[chunk.resource]["chunks"].append(entry)
        await plan_collection.update_one(
            {"_id": seller_id},
            {"$set": {"progress": progress, "updated_at": datetime.now(UTC)}},
            upsert=True,
        )
        return accepted

    return history_backfill


def _same_utc_instant(left: Any, right: datetime) -> bool:
    if not isinstance(left, datetime):
        return False
    return (left.replace(tzinfo=UTC) if left.tzinfo is None else left.astimezone(UTC)) == right
