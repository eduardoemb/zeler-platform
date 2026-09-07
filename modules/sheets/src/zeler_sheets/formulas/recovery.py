"""Durable, coalesced recovery requests; no external API calls on formula execution."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

RECOVERABLE_MODELS = frozenset(
    {
        "questions",
        "orders",
        "shipments",
        "item_formula_rows",
        "catalog_product_snapshots",
        "catalog_buybox_snapshots",
    }
)
LEASE = timedelta(minutes=10)
COOLDOWN = timedelta(minutes=15)
MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class RecoveryRequest:
    seller_id: str
    read_model: str
    date_from: datetime
    date_to: datetime

    def __post_init__(self) -> None:
        if not self.seller_id.strip() or self.read_model not in RECOVERABLE_MODELS:
            raise ValueError("a seller and recoverable read model are required")
        if self.date_from.tzinfo is None or self.date_to.tzinfo is None:
            raise ValueError("recovery dates must include timezone")
        if not timedelta(0) < self.date_to - self.date_from <= timedelta(days=90):
            raise ValueError("recovery range must be positive and at most 90 days")

    @property
    def key(self) -> str:
        parts = (
            self.seller_id,
            self.read_model,
            self.date_from.astimezone(UTC).isoformat(),
            self.date_to.astimezone(UTC).isoformat(),
        )
        return hashlib.sha256("\0".join(parts).encode()).hexdigest()


class FormulaRecoveryQueue:
    def __init__(self, db: Any, *, now: Callable[[], datetime] | None = None) -> None:
        self.collection = db["sheets_formula_recovery_jobs"]
        self.now = now or (lambda: datetime.now(UTC))

    async def enqueue(self, request: RecoveryRequest) -> str:
        now = self.now()
        initial = {
            "_id": request.key,
            "seller_id": request.seller_id,
            "read_model": request.read_model,
            "date_from": request.date_from,
            "date_to": request.date_to,
            "state": "pending",
            "attempts": 0,
            "created_at": now,
            "updated_at": now,
            "available_at": now,
        }
        # A simultaneous upsert can already have persisted this exact request.
        with suppress(DuplicateKeyError):
            await self.collection.update_one(
                {"_id": request.key}, {"$setOnInsert": initial}, upsert=True
            )
        await self.collection.update_one(
            {
                "_id": request.key,
                "state": {"$in": ["completed", "failed"]},
                "available_at": {"$lte": now},
            },
            {"$set": {"state": "pending", "attempts": 0, "updated_at": now}},
        )
        return request.key

    async def claim(self) -> dict[str, Any] | None:
        now = self.now()
        await self.collection.update_many(
            {
                "state": "running",
                "lease_until": {"$lte": now},
                "attempts": {"$gte": MAX_ATTEMPTS},
            },
            {
                "$set": {
                    "state": "failed",
                    "failure_reason": "attempts_exhausted",
                    "updated_at": now,
                    "available_at": now + COOLDOWN,
                },
                "$unset": {"lease_until": "", "attempt_token": ""},
            },
        )
        claimed = await self.collection.find_one_and_update(
            {
                "attempts": {"$lt": MAX_ATTEMPTS},
                "available_at": {"$lte": now},
                "$or": [
                    {"state": "pending"},
                    {"state": "running", "lease_until": {"$lte": now}},
                ],
            },
            {
                "$set": {
                    "state": "running",
                    "attempt_token": uuid4().hex,
                    "lease_until": now + LEASE,
                    "updated_at": now,
                },
                "$inc": {"attempts": 1},
            },
            sort=[("available_at", 1), ("_id", 1)],
            return_document=ReturnDocument.AFTER,
        )
        return dict(claimed) if claimed is not None else None

    async def renew(self, job: dict[str, Any]) -> bool:
        now = self.now()
        result = await self.collection.update_one(
            self._owned(job, now),
            {"$set": {"lease_until": now + LEASE, "updated_at": now}},
        )
        return bool(result.matched_count)

    async def finish(
        self,
        job: dict[str, Any],
        *,
        succeeded: bool,
        retryable: bool = False,
        failure_reason: str = "recovery_failed",
    ) -> bool:
        now = self.now()
        retry = not succeeded and retryable and job["attempts"] < MAX_ATTEMPTS
        if failure_reason not in {
            "recovery_failed",
            "source_temporarily_unavailable",
            "source_rejected",
            "source_incomplete",
            "storage_unavailable",
        }:
            raise ValueError("unsupported public recovery failure reason")
        fields = {
            "state": "completed" if succeeded else "pending" if retry else "failed",
            "available_at": now
            + (timedelta(seconds=30 * 2 ** (job["attempts"] - 1)) if retry else COOLDOWN),
            "updated_at": now,
        }
        unset = {"lease_until": "", "attempt_token": ""}
        if succeeded:
            unset["failure_reason"] = ""
        else:
            fields["failure_reason"] = failure_reason
        result = await self.collection.update_one(
            self._owned(job, now),
            {
                "$set": fields,
                "$unset": unset,
            },
        )
        return bool(result.matched_count)

    @staticmethod
    def _owned(job: dict[str, Any], now: datetime) -> dict[str, Any]:
        return {
            "_id": job["_id"],
            "state": "running",
            "attempt_token": job["attempt_token"],
            "lease_until": {"$gt": now},
        }
