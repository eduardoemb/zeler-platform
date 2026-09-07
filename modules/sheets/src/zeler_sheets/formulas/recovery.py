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
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

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
IMPLEMENTED_MODELS = frozenset({"questions", "orders", "shipments"})


def recovery_sellers(value: str | None) -> frozenset[str]:
    """Runtime recovery is closed unless sellers are explicitly configured."""
    if not value or not value.strip():
        return frozenset()
    sellers = frozenset(part.strip() for part in value.split(","))
    if any(not seller.isascii() or not seller.isdecimal() for seller in sellers):
        raise ValueError("formula recovery requires explicit numeric seller IDs")
    return sellers


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
        # BSON stores milliseconds: expand rather than truncate the requested
        # interval so persisted coverage still contains its original endpoints.
        start = self.date_from.astimezone(UTC)
        end = self.date_to.astimezone(UTC)
        object.__setattr__(
            self, "date_from", start - timedelta(microseconds=start.microsecond % 1000)
        )
        object.__setattr__(self, "date_to", end + timedelta(microseconds=(-end.microsecond) % 1000))

    @property
    def key(self) -> str:
        parts = (
            self.seller_id,
            self.read_model,
            self.date_from.astimezone(UTC).isoformat(),
            self.date_to.astimezone(UTC).isoformat(),
        )
        return hashlib.sha256("\0".join(parts).encode()).hexdigest()


@dataclass(frozen=True)
class OrderIdsRecoveryRequest:
    seller_id: str
    order_ids: tuple[str, ...]
    read_model: str = "orders"

    def __post_init__(self) -> None:
        if (
            not self.seller_id.strip()
            or self.read_model != "orders"
            or not 1 <= len(self.order_ids) <= 100
            or any(
                not identity.isascii() or not identity.isdecimal() for identity in self.order_ids
            )
        ):
            raise ValueError("a seller and at most 100 numeric order IDs are required")
        object.__setattr__(self, "order_ids", tuple(sorted(set(self.order_ids))))

    @property
    def key(self) -> str:
        return hashlib.sha256(
            "\0".join((self.seller_id, self.read_model, "ids", *self.order_ids)).encode()
        ).hexdigest()


@dataclass(frozen=True)
class ShipmentIdsRecoveryRequest:
    seller_id: str
    shipment_ids: tuple[str, ...]
    read_model: str = "shipments"

    def __post_init__(self) -> None:
        if (
            not self.seller_id.strip()
            or self.read_model != "shipments"
            or not 1 <= len(self.shipment_ids) <= 100
            or any(
                not identity.isascii() or not identity.isdecimal() for identity in self.shipment_ids
            )
        ):
            raise ValueError("a seller and at most 100 numeric shipment IDs are required")
        object.__setattr__(self, "shipment_ids", tuple(sorted(set(self.shipment_ids))))

    @property
    def key(self) -> str:
        return hashlib.sha256(
            "\0".join((self.seller_id, self.read_model, "ids", *self.shipment_ids)).encode()
        ).hexdigest()


class FormulaRecoveryQueue:
    def __init__(
        self,
        db: Any,
        *,
        now: Callable[[], datetime] | None = None,
        enabled_models: frozenset[str] = RECOVERABLE_MODELS,
        allowed_sellers: frozenset[str] | None = None,
        max_active_jobs_per_seller: int = 20,
    ) -> None:
        if type(max_active_jobs_per_seller) is not int or max_active_jobs_per_seller < 1:
            raise ValueError("recovery capacity must be a positive integer")
        self.collection = db["sheets_formula_recovery_jobs"]
        self.admission = db["sheets_formula_recovery_admission"]
        self.max_active_jobs_per_seller = max_active_jobs_per_seller
        self.now = now or (lambda: datetime.now(UTC))
        self.enabled_models = enabled_models
        self.allowed_sellers = allowed_sellers

    async def ensure_indexes(self) -> None:
        await self.collection.create_index(
            [("seller_id", 1), ("state", 1)], name="recovery_seller_active"
        )
        await self.collection.create_index(
            [("state", 1), ("read_model", 1), ("available_at", 1), ("_id", 1)],
            name="recovery_claim",
        )
        await self.collection.create_index(
            [("state", 1), ("lease_until", 1)],
            name="recovery_expired_lease",
        )

    async def enqueue(
        self, request: RecoveryRequest | OrderIdsRecoveryRequest | ShipmentIdsRecoveryRequest
    ) -> str:
        if self.allowed_sellers is not None and request.seller_id not in self.allowed_sellers:
            raise ValueError("recovery seller is not enabled")
        if request.read_model not in self.enabled_models:
            raise ValueError("recovery source is not enabled")
        if request.read_model == "shipments" and not isinstance(
            request, ShipmentIdsRecoveryRequest
        ):
            raise ValueError("shipment recovery requires explicit IDs")
        now = self.now()
        initial = {
            "_id": request.key,
            "seller_id": request.seller_id,
            "read_model": request.read_model,
            "state": "pending",
            "attempts": 0,
            "created_at": now,
            "updated_at": now,
            "available_at": now,
        }
        if isinstance(request, OrderIdsRecoveryRequest):
            initial["order_ids"] = list(request.order_ids)
        elif isinstance(request, ShipmentIdsRecoveryRequest):
            initial["shipment_ids"] = list(request.shipment_ids)
        else:
            initial.update(date_from=request.date_from, date_to=request.date_to)
        # One guard per seller (identity/revision only) serializes admission
        # across API processes. Seed outside the transaction to handle first use.
        with suppress(DuplicateKeyError):
            await self.admission.update_one(
                {"_id": request.seller_id}, {"$setOnInsert": {"revision": 0}}, upsert=True
            )

        async def admit(session: Any) -> None:
            # A count followed by insertion without this write can oversubscribe
            # under snapshot isolation. Transaction retries refresh the snapshot.
            await self.admission.update_one(
                {"_id": request.seller_id}, {"$inc": {"revision": 1}}, session=session
            )
            existing = await self.collection.find_one({"_id": request.key}, session=session)
            if existing is not None and existing["state"] in {"pending", "running"}:
                return
            active = await self.collection.count_documents(
                {"seller_id": request.seller_id, "state": {"$in": ["pending", "running"]}},
                limit=self.max_active_jobs_per_seller,
                session=session,
            )
            if active >= self.max_active_jobs_per_seller:
                raise ValueError("recovery seller capacity reached")
            if existing is None:
                await self.collection.insert_one(initial, session=session)
            else:
                # Cooldown is not advanced by a new request. Reopening consumes
                # capacity, but completing a job frees it without a second counter.
                await self.collection.update_one(
                    {"_id": request.key},
                    {"$set": {"state": "pending", "attempts": 0, "updated_at": now}},
                    session=session,
                )

        async with await self.collection.database.client.start_session() as session:
            await session.with_transaction(
                admit, read_concern=ReadConcern("snapshot"), write_concern=WriteConcern("majority")
            )
        return request.key

    async def claim(self) -> dict[str, Any] | None:
        now = self.now()
        seller_filter = (
            {"seller_id": {"$in": sorted(self.allowed_sellers)}}
            if self.allowed_sellers is not None
            else {}
        )
        await self.collection.update_many(
            {
                **seller_filter,
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
                **seller_filter,
                "attempts": {"$lt": MAX_ATTEMPTS},
                "read_model": {"$in": sorted(self.enabled_models)},
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
        session: Any = None,
    ) -> bool:
        if session is not None and not session.in_transaction:
            raise ValueError("recovery publication requires an active transaction")
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
            **({"session": session} if session is not None else {}),
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
