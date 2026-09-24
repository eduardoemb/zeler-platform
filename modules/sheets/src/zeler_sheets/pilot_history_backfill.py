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

from zeler_sheets.formulas.recovery import OrderHistoryRecoveryRequest, RecoveryCapacityError
from zeler_sheets.pilot_history import ChunkPriority, HistoryPlanner
from zeler_sheets.pilot_history_recovery_bridge import chunk_to_recovery_request

logger = structlog.get_logger(__name__)

__all__ = ["build_pilot_history_backfill"]

PLAN_COLLECTION = "sheets_history_backfill_plans"
PILOT_HISTORY_ACTIVE_JOBS = 4


def build_pilot_history_backfill(
    *, db: Any, recovery_queue: Any, order_history: bool = False
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
        stored_cutoff = plan_doc.get("cutoff") if plan_doc is not None else None
        if not isinstance(stored_cutoff, datetime) or stored_cutoff.tzinfo is None:
            logger.warning("zelerdata.history_backfill_invalid_cutoff", seller_id=seller_id)
            return False
        cutoff = stored_cutoff.astimezone(UTC)
        planner = HistoryPlanner(cutoff=cutoff, months=12)
        order_plan_id = f"pilot-12m:{cutoff.isoformat(timespec='milliseconds')}"

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
                else chunk_to_recovery_request(chunk, seller_id=seller_id)
            )
            for chunk in chunks
            if chunk.resource in {"orders", "questions"}
        }
        history_budget = len(requests)
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
        for chunk in chunks:
            request = requests.get(chunk.id)
            if request is None or capacity_reached:
                continue
            job = await recovery_queue.collection.find_one(
                {"_id": request.key, "seller_id": seller_id}, {"state": 1}
            )
            if job is not None:
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
            if request is not None:
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
