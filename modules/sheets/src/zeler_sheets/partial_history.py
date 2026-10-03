"""Project usable staged rows without certifying incomplete historical coverage.

This is a separate partial-data path, not a bypass of HistoryOrderPublisher's
exact-range checks. It never modifies acquisition heads or membership receipts,
never publishes a quota certificate, and keeps bounded missing-record retries
apart from valid canonical records. Callers own job admission/plan scheduling.
"""

from __future__ import annotations

from datetime import UTC, datetime
from functools import partial
from typing import Any
from uuid import uuid4

import httpx
from bson import BSON
from pydantic import ValidationError

from zeler_platform_core.devoluciones_readiness import (
    acquire_devoluciones_operation,
    finish_devoluciones_operation,
)
from zeler_platform_core.models import SheetsHistoryAcquisition
from zeler_sheets.event_persistence import SheetsEventPersistence
from zeler_sheets.formulas.pacing import recovery_fetch_resource
from zeler_sheets.history_acquisition import HistoryConflictError
from zeler_sheets.item_projection import item_source_fingerprint
from zeler_sheets.onboarding_sources import _timestamp

PENDING_COLLECTION = "sheets_history_pending_records"
_JOBS_COLLECTION = "sheets_formula_recovery_jobs"


def _validate_resource(
    payload: dict[str, Any], head: SheetsHistoryAcquisition, identity: str
) -> None:
    seller = payload.get("seller") if head.read_model == "orders" else None
    seller_id = seller.get("id") if isinstance(seller, dict) else payload.get("seller_id")
    if (
        str(payload.get("id")) != identity
        or str(seller_id) != head.seller_id
        or not head.date_from <= _timestamp(payload.get("date_created")) < head.date_to
    ):
        raise ValueError("resource identity, seller or interval mismatch")
    if head.read_model == "questions" and str(payload.get("status")).upper() == "ANSWERED":
        answer = payload.get("answer")
        if not isinstance(answer, dict) or not isinstance(answer.get("text"), str):
            raise ValueError("answered question lacks its answer")
        _timestamp(answer.get("date_created"))


async def _detail(
    db: Any, worker: Any, head: SheetsHistoryAcquisition, member: dict[str, Any]
) -> tuple[dict[str, Any], frozenset[str], datetime]:
    identity = member["resource_id"]
    source = member.get("source_payload")
    if not isinstance(source, dict) or item_source_fingerprint(source) != member.get("source_hash"):
        raise ValueError("membership source fingerprint mismatch")
    source_seller = source.get("seller") if head.read_model == "orders" else None
    seller = source_seller.get("id") if isinstance(source_seller, dict) else source.get("seller_id")
    if str(source.get("id")) != identity or str(seller) != head.seller_id:
        raise ValueError("membership ownership mismatch")
    detail = await db["sheets_history_receipts"].find_one(
        {
            "acquisition_id": head.id,
            "seller_id": head.seller_id,
            "read_model": head.read_model,
            "generation": head.generation,
            "pass_number": head.pass_number,
            "kind": "detail",
            "resource_id": identity,
        }
    )
    if detail is not None:
        payload = detail.get("payload")
        if not isinstance(payload, dict) or item_source_fingerprint(payload) != detail.get(
            "payload_hash"
        ):
            raise ValueError("detail fingerprint mismatch")
        return (
            payload,
            frozenset(detail.get("unavailable_fields") or []),
            _timestamp(detail["observed_at"]),
        )
    if head.read_model == "orders":
        observed = await worker._order_detail_with_source(
            head.seller_id,
            identity,
            head.date_from,
            head.date_to,
            search_row=source,
        )
        return observed.resource, observed.unavailable_fields, _timestamp(observed.observed_at)
    payload = await recovery_fetch_resource(
        worker.detail_gateway, seller_id=head.seller_id, path=f"/questions/{identity}?api_version=4"
    )
    return payload, frozenset(), datetime.now(UTC).replace(microsecond=0)


async def advance_partial_history(
    *, db: Any, worker: Any, job: dict[str, Any], max_details: int = 20
) -> dict[str, Any]:
    """Publish up to twenty valid rows; missing rows get at most three attempts."""
    if type(max_details) is not int or not 1 <= max_details <= 20:
        raise ValueError("partial detail budget must be one to twenty")
    raw = await db["sheets_history_acquisitions"].find_one(
        {
            "_id": job.get("history_acquisition_id"),
            "seller_id": job.get("seller_id"),
            "read_model": job.get("read_model"),
            "job_id": job.get("_id"),
        }
    )
    if raw is None:
        return {
            "state": "pending_dependencies",
            "complete": False,
            "persisted": 0,
            "pending_count": 0,
        }
    head = SheetsHistoryAcquisition.model_validate(raw)
    scope = {
        "acquisition_id": head.id,
        "seller_id": head.seller_id,
        "read_model": head.read_model,
        "generation": head.generation,
        "pass_number": head.pass_number,
    }
    receipts = db["sheets_history_receipts"]
    member_count = await receipts.count_documents({**scope, "kind": "membership"})
    exclusions = await receipts.count_documents({**scope, "kind": "exclusion"})
    if (
        head.source_total is None
        or head.next_cursor is not None
        or member_count != head.discovered_count
        or member_count + exclusions < head.source_total
    ):
        return {
            "state": "pending_dependencies",
            "complete": False,
            "persisted": 0,
            "pending_count": 0,
        }
    old_cursor = job.get("partial_cursor")
    binding = {
        "acquisition_id": head.id,
        "generation": head.generation,
        "pass_number": head.pass_number,
    }
    if isinstance(old_cursor, dict) and any(old_cursor.get(k) != v for k, v in binding.items()):
        raise HistoryConflictError("partial cursor belongs to another acquisition pass")
    after = old_cursor.get("after", "") if isinstance(old_cursor, dict) else ""
    members = (
        await receipts.find({**scope, "kind": "membership", "resource_id": {"$gt": after}})
        .sort("resource_id", 1)
        .limit(max_details)
        .to_list(length=max_details)
    )
    initial_pass = bool(members)
    pending = db[PENDING_COLLECTION]
    if not members:
        retry = (
            await pending.find({**scope, "state": "pending", "attempts": {"$lt": 3}})
            .sort("resource_id", 1)
            .limit(max_details)
            .to_list(length=max_details)
        )
        for row in retry:
            member = await receipts.find_one(
                {**scope, "kind": "membership", "resource_id": row["resource_id"]}
            )
            if member is not None:
                members.append(member)
    total_persisted = int(job.get("partial_persisted") or 0)
    operation = None
    if members and head.read_model == "orders":
        operation = await acquire_devoluciones_operation(
            db=db,
            seller_id=head.seller_id,
            scope="devoluciones",
            operation_id=f"partial-history:{head.id}",
            attempt_token=uuid4().hex,
            invalidate_readiness=False,
        )
    succeeded = False
    try:
        for member in members:
            identity = member["resource_id"]
            if not isinstance(identity, str) or not identity.isascii() or not identity.isdecimal():
                raise HistoryConflictError("partial membership identity is invalid")
            pending_id = f"{head.id}:{head.generation}:{head.pass_number}:{identity}"
            previous = await pending.find_one({"_id": pending_id, "seller_id": head.seller_id})
            attempts = (previous or {}).get("attempts", 0) + 1
            if attempts > 3:
                continue
            code = None
            try:
                if len(BSON.encode(member)) > 1024 * 1024:
                    raise ValueError("partial input exceeds byte budget")
                payload, missing, observed_at = await _detail(db, worker, head, member)
                _validate_resource(payload, head, identity)
                if len(BSON.encode(payload)) > 1024 * 1024:
                    raise ValueError("partial payload exceeds byte budget")
                existing = await db[head.read_model].find_one({"_id": identity})
                if existing is not None and str(existing.get("seller_id")) != head.seller_id:
                    raise ValueError("canonical row belongs to another seller")
                current = await db["sheets_history_acquisitions"].find_one({"_id": head.id})
                if current is None or any(
                    current.get(k) != raw.get(k)
                    for k in ("generation", "pass_number", "checkpoint_revision")
                ):
                    raise HistoryConflictError("acquisition changed during partial projection")
                observed_at = observed_at.replace(
                    microsecond=observed_at.microsecond // 1000 * 1000
                )
                writer = SheetsEventPersistence(db=db, clock=partial(_timestamp, observed_at))
                await writer.persist(
                    event_type=f"{head.read_model}.updated",
                    seller_id=head.seller_id,
                    resource=payload,
                    operation=operation,
                    unavailable_fields=missing,
                )
            except httpx.HTTPStatusError as exc:
                code = f"http_{exc.response.status_code}"
            except (httpx.RequestError, TimeoutError):
                code = "source_retry_required"
            except HistoryConflictError:
                raise
            except (ValueError, TypeError, ValidationError):
                code = "invalid_or_unavailable_record"
            if code is not None:
                await pending.update_one(
                    {"_id": pending_id, "seller_id": head.seller_id},
                    {
                        "$set": {
                            **scope,
                            "resource_id": identity,
                            "attempts": attempts,
                            "state": "unavailable" if attempts == 3 else "pending",
                            "error_code": code,
                            "updated_at": datetime.now(UTC),
                        },
                        "$setOnInsert": {"_id": pending_id},
                    },
                    upsert=True,
                )
            else:
                total_persisted += 1
                if previous is not None:
                    await pending.update_one(
                        {"_id": pending_id, "seller_id": head.seller_id},
                        {"$set": {"state": "resolved", "attempts": attempts, "error_code": None}},
                    )
            if initial_pass:
                after = identity
        succeeded = True
    finally:
        if operation is not None:
            await finish_devoluciones_operation(db=db, operation=operation, succeeded=succeeded)
    checkpoint = {**binding, "after": after}
    result = await db[_JOBS_COLLECTION].update_one(
        {
            "_id": job["_id"],
            "seller_id": head.seller_id,
            "read_model": head.read_model,
            "partial_cursor": old_cursor,
        },
        {"$set": {"partial_cursor": checkpoint, "partial_persisted": total_persisted}},
    )
    if result.matched_count != 1:
        raise HistoryConflictError("partial projection cursor changed")
    remaining = await receipts.count_documents(
        {**scope, "kind": "membership", "resource_id": {"$gt": after}}
    )
    pending_count = await pending.count_documents(
        {**scope, "state": {"$in": ["pending", "unavailable"]}}
    )
    retryable = await pending.count_documents({**scope, "state": "pending", "attempts": {"$lt": 3}})
    return {
        "state": "partial_available" if pending_count else "available_uncertified",
        "complete": not remaining and not retryable,
        "persisted": total_persisted,
        "pending_count": pending_count,
        "processed": len(members),
        "coverage_complete": False,
    }
