"""Guarded one-time consolidation of overlapping item recovery jobs."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from zeler_sheets.formulas.recovery import CatalogRecoveryRequest


@dataclass(frozen=True)
class ItemCatalogReconciliation:
    fingerprint: str
    active_jobs: int
    superseded_jobs: int
    outstanding_ids: int


def _plan(
    jobs: list[dict[str, Any]], *, seller_id: str, now: datetime
) -> tuple[ItemCatalogReconciliation, tuple[str, ...]]:
    successes: set[str] = set()
    outstanding: set[str] = set()
    evidence: list[dict[str, Any]] = []
    if len(jobs) > 20:
        raise ValueError("too many active item jobs for bounded reconciliation")
    for job in jobs:
        if job.get("seller_id") != seller_id or job.get("read_model") != "item_formula_rows":
            raise ValueError("reconciliation scope changed")
        ids = tuple(job.get("item_ids", []))
        if not ids or ids != CatalogRecoveryRequest(seller_id, "item_formula_rows", ids).ids:
            raise ValueError("invalid item job identities")
        offset = job.get("catalog_offset", 0)
        failed = job.get("catalog_failed_offsets", [])
        if (
            type(offset) is not int
            or not 0 <= offset <= len(ids)
            or offset % 20
            or not isinstance(failed, list)
            or any(
                type(value) is not int or value < 0 or value >= offset or value % 20
                for value in failed
            )
            or len(set(failed)) != len(failed)
        ):
            raise ValueError("invalid item job checkpoint")
        lease = job.get("lease_until")
        if job.get("state") == "running" and (
            not isinstance(lease, datetime)
            or (lease.replace(tzinfo=UTC) if lease.tzinfo is None else lease) > now
        ):
            raise ValueError("active item job lease; stop and drain the worker first")
        if job.get("state") not in {"pending", "running"}:
            raise ValueError("reconciliation job state changed")
        failed_set = set(failed)
        for chunk_start in range(0, offset, 20):
            (outstanding if chunk_start in failed_set else successes).update(
                ids[chunk_start : chunk_start + 20]
            )
        outstanding.update(ids[offset:])
        evidence.append(
            {
                "id": str(job["_id"]),
                "state": job["state"],
                "updated_at": str(job.get("updated_at")),
                "ids": ids,
                "offset": offset,
                "failed": sorted(failed_set),
            }
        )
    remaining = tuple(sorted(outstanding - successes))
    if len(remaining) > 10000:
        raise ValueError("reconciliation exceeds one bounded catalog job")
    fingerprint = hashlib.sha256(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    plan = ItemCatalogReconciliation(
        fingerprint=fingerprint,
        active_jobs=len(jobs),
        superseded_jobs=len(jobs) if len(jobs) > 1 else 0,
        outstanding_ids=len(remaining),
    )
    return plan, remaining


async def reconcile_item_catalog_jobs(
    db: Any,
    *,
    seller_id: str,
    execute: bool = False,
    expected_fingerprint: str | None = None,
) -> ItemCatalogReconciliation:
    """Dry-run by default; execute only for an exact, drained queue snapshot."""
    if re.fullmatch(r"[0-9]+", seller_id) is None:
        raise ValueError("numeric seller ID required")
    if execute and (
        expected_fingerprint is None or re.fullmatch(r"[0-9a-f]{64}", expected_fingerprint) is None
    ):
        raise ValueError("matching dry-run fingerprint required")
    collection = db["sheets_formula_recovery_jobs"]
    scope = {
        "seller_id": seller_id,
        "read_model": "item_formula_rows",
        "state": {"$in": ["pending", "running"]},
        "item_ids": {"$exists": True},
    }

    async def inspect(
        session: Any = None,
    ) -> tuple[ItemCatalogReconciliation, tuple[str, ...], list[dict[str, Any]]]:
        jobs = await collection.find(scope, session=session).sort("_id", 1).to_list(length=21)
        plan, remaining = _plan(jobs, seller_id=seller_id, now=datetime.now(UTC))
        return plan, remaining, jobs

    if not execute:
        plan, _, _ = await inspect()
        return plan

    async def apply(session: Any) -> ItemCatalogReconciliation:
        await db["sheets_formula_recovery_admission"].update_one(
            {"_id": seller_id}, {"$inc": {"revision": 1}}, upsert=True, session=session
        )
        plan, remaining, jobs = await inspect(session)
        if plan.fingerprint != expected_fingerprint:
            raise ValueError("reconciliation fingerprint changed")
        if plan.active_jobs < 2:
            raise ValueError("no overlapping item jobs to reconcile")
        now = datetime.now(UTC)
        replacement_id = hashlib.sha256(
            f"item-reconcile:{seller_id}:{plan.fingerprint}".encode()
        ).hexdigest()
        for job in jobs:
            changed = await collection.update_one(
                {
                    "_id": job["_id"],
                    "seller_id": seller_id,
                    "state": job["state"],
                    "updated_at": job.get("updated_at"),
                    **(
                        {"catalog_offset": job["catalog_offset"]} if "catalog_offset" in job else {}
                    ),
                },
                {
                    "$set": {
                        "state": "failed",
                        "failure_reason": "superseded_by_item_reconciliation",
                        "superseded_by": replacement_id if remaining else None,
                        "updated_at": now,
                    },
                    "$unset": {"attempt_token": "", "lease_until": ""},
                },
                session=session,
            )
            if changed.matched_count != 1:
                raise ValueError("item job changed during reconciliation")
        if remaining:
            await collection.insert_one(
                {
                    "_id": replacement_id,
                    "seller_id": seller_id,
                    "read_model": "item_formula_rows",
                    "state": "pending",
                    "attempts": 0,
                    "item_ids": list(remaining),
                    "catalog_offset": 0,
                    "reconciled_from": [job["_id"] for job in jobs],
                    "created_at": now,
                    "updated_at": now,
                    "available_at": now,
                },
                session=session,
            )
        return plan

    async with await db.client.start_session() as session:
        return cast(
            ItemCatalogReconciliation,
            await session.with_transaction(
                apply, read_concern=ReadConcern("snapshot"), write_concern=WriteConcern("majority")
            ),
        )
