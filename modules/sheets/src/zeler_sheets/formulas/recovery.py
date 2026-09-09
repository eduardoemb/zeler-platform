"""Durable, coalesced recovery requests; no external API calls on formula execution."""

from __future__ import annotations

import hashlib
import re
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
IMPLEMENTED_MODELS = frozenset(
    {
        "questions",
        "orders",
        "shipments",
        "item_formula_rows",
        "catalog_product_snapshots",
        "catalog_buybox_snapshots",
    }
)


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


@dataclass(frozen=True)
class ItemIdsRecoveryRequest:
    seller_id: str
    item_ids: tuple[str, ...]
    read_model: str = "item_formula_rows"

    def __post_init__(self) -> None:
        if (
            re.fullmatch(r"[0-9]+", self.seller_id) is None
            or self.read_model not in {"item_formula_rows", "catalog_buybox_snapshots"}
            or not 1 <= len(self.item_ids) <= 20
            or any(re.fullmatch(r"ML[A-Z][0-9]+", value) is None for value in self.item_ids)
        ):
            raise ValueError("item recovery requires a seller and 1 to 20 publication IDs")
        object.__setattr__(self, "item_ids", tuple(sorted(set(self.item_ids))))

    @property
    def key(self) -> str:
        return hashlib.sha256(
            "\0".join((self.seller_id, self.read_model, "ids", *self.item_ids)).encode()
        ).hexdigest()


@dataclass(frozen=True)
class CatalogProductIdsRecoveryRequest:
    seller_id: str
    catalog_product_ids: tuple[str, ...]
    read_model: str = "catalog_product_snapshots"

    def __post_init__(self) -> None:
        if (
            re.fullmatch(r"[0-9]+", self.seller_id) is None
            or self.read_model != "catalog_product_snapshots"
            or not 1 <= len(self.catalog_product_ids) <= 20
            or any(
                re.fullmatch(r"ML[A-Z][0-9]+", value) is None for value in self.catalog_product_ids
            )
        ):
            raise ValueError("catalog recovery requires a seller and 1 to 20 product IDs")
        object.__setattr__(
            self, "catalog_product_ids", tuple(sorted(set(self.catalog_product_ids)))
        )

    @property
    def key(self) -> str:
        return hashlib.sha256(
            "\0".join(
                (self.seller_id, self.read_model, "products", *self.catalog_product_ids)
            ).encode()
        ).hexdigest()


@dataclass(frozen=True)
class CatalogRecoveryRequest:
    """One durable intent, executed in bounded catalog chunks by the worker."""

    seller_id: str
    read_model: str
    ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            re.fullmatch(r"[0-9]+", self.seller_id) is None
            or self.read_model not in {"catalog_product_snapshots", "catalog_buybox_snapshots"}
            or not 1 <= len(self.ids) <= 10000
            or any(re.fullmatch(r"ML[A-Z][0-9]+", value) is None for value in self.ids)
        ):
            raise ValueError("catalog intent requires a seller and at most 10000 explicit IDs")
        object.__setattr__(self, "ids", tuple(sorted(set(self.ids))))

    @property
    def key(self) -> str:
        return hashlib.sha256(
            "\0".join((self.seller_id, self.read_model, "catalog_intent", *self.ids)).encode()
        ).hexdigest()


@dataclass(frozen=True)
class ItemInventoryRecoveryRequest:
    seller_id: str
    read_model: str = "item_formula_rows"

    def __post_init__(self) -> None:
        if (
            re.fullmatch(r"[0-9]+", self.seller_id) is None
            or self.read_model != "item_formula_rows"
        ):
            raise ValueError("inventory recovery requires a numeric seller")

    @property
    def key(self) -> str:
        return hashlib.sha256(
            "\0".join((self.seller_id, self.read_model, "inventory")).encode()
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
        self,
        request: RecoveryRequest
        | OrderIdsRecoveryRequest
        | ShipmentIdsRecoveryRequest
        | ItemIdsRecoveryRequest
        | CatalogProductIdsRecoveryRequest
        | CatalogRecoveryRequest
        | ItemInventoryRecoveryRequest,
    ) -> str:
        if self.allowed_sellers is not None and request.seller_id not in self.allowed_sellers:
            raise ValueError("recovery seller is not enabled")
        if request.read_model not in self.enabled_models:
            raise ValueError("recovery source is not enabled")
        if request.read_model == "shipments" and not isinstance(
            request, ShipmentIdsRecoveryRequest
        ):
            raise ValueError("shipment recovery requires explicit IDs")
        if request.read_model == "catalog_product_snapshots" and not isinstance(
            request, (CatalogProductIdsRecoveryRequest, CatalogRecoveryRequest)
        ):
            raise ValueError("catalog recovery requires explicit product IDs")
        if request.read_model == "catalog_buybox_snapshots" and not isinstance(
            request, (ItemIdsRecoveryRequest, CatalogRecoveryRequest)
        ):
            raise ValueError("buybox recovery requires explicit publication IDs")
        if request.read_model == "item_formula_rows" and not isinstance(
            request, (ItemIdsRecoveryRequest, ItemInventoryRecoveryRequest)
        ):
            raise ValueError("item recovery requires explicit IDs or an inventory request")
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
        if isinstance(request, CatalogRecoveryRequest):
            field = (
                "item_ids"
                if request.read_model == "catalog_buybox_snapshots"
                else "catalog_product_ids"
            )
            initial.update({field: list(request.ids), "catalog_offset": 0})
        elif isinstance(request, OrderIdsRecoveryRequest):
            initial["order_ids"] = list(request.order_ids)
        elif isinstance(request, ShipmentIdsRecoveryRequest):
            initial["shipment_ids"] = list(request.shipment_ids)
        elif isinstance(request, ItemIdsRecoveryRequest):
            initial["item_ids"] = list(request.item_ids)
        elif isinstance(request, CatalogProductIdsRecoveryRequest):
            initial["catalog_product_ids"] = list(request.catalog_product_ids)
        elif isinstance(request, ItemInventoryRecoveryRequest):
            initial["inventory_scope"] = True
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
                    {
                        "$set": {
                            "state": "pending",
                            "attempts": 0,
                            "updated_at": now,
                            **(
                                {"catalog_offset": 0}
                                if isinstance(request, CatalogRecoveryRequest)
                                else {}
                            ),
                        },
                        **(
                            {
                                "$unset": {
                                    "inventory_offset": "",
                                    "inventory_unavailable_ids": "",
                                }
                            }
                            if isinstance(request, ItemInventoryRecoveryRequest)
                            else {
                                "$unset": {
                                    "catalog_failed_offsets": "",
                                    "catalog_failure_reason": "",
                                }
                            }
                            if isinstance(request, CatalogRecoveryRequest)
                            else {}
                        ),
                    },
                    session=session,
                )

        async with await self.collection.database.client.start_session() as session:
            await session.with_transaction(
                admit, read_concern=ReadConcern("snapshot"), write_concern=WriteConcern("majority")
            )
        return request.key

    async def checkpoint_inventory(
        self,
        job: dict[str, Any],
        *,
        item_ids: list[str],
        offset: int,
        unavailable: bool = False,
    ) -> bool:
        if (
            job.get("inventory_scope") is not True
            or len(item_ids) > 10000
            or item_ids != sorted(set(item_ids))
            or any(re.fullmatch(r"ML[A-Z][0-9]+", identity) is None for identity in item_ids)
            or type(offset) is not int
            or type(unavailable) is not bool
            or (unavailable and "inventory_offset" not in job)
            or not 0 <= offset <= len(item_ids)
            or ("inventory_offset" not in job and offset != 0)
            or (
                "inventory_offset" in job
                and (
                    item_ids != job["inventory_ids"]
                    or not job["inventory_offset"] < offset <= job["inventory_offset"] + 20
                )
            )
        ):
            raise ValueError("invalid inventory checkpoint")
        now = self.now()
        completed = offset == len(item_ids)
        missing = sorted(
            set(job.get("inventory_unavailable_ids", []))
            | (set(item_ids[job["inventory_offset"] : offset]) if unavailable else set())
        )
        terminal_failure = completed and bool(missing)
        available_at = now
        if completed:
            available_at = now + COOLDOWN
            if not terminal_failure:
                # A successful scan ages from discovery, not completion. Do
                # not add another full wait after its inventory has expired.
                observed = job.get("inventory_observed_at") or job["updated_at"]
                if observed.tzinfo is None:
                    observed = observed.replace(tzinfo=UTC)
                available_at = max(now, observed + COOLDOWN)
        result = await self.collection.update_one(
            self._owned(job, now),
            {
                "$set": {
                    "inventory_ids": item_ids,
                    "inventory_offset": offset,
                    "inventory_unavailable_ids": missing,
                    **(
                        {"inventory_observed_at": job["updated_at"]}
                        if "inventory_offset" not in job
                        else {}
                    ),
                    "state": "failed"
                    if terminal_failure
                    else "completed"
                    if completed
                    else "pending",
                    "attempts": 0,
                    "updated_at": now,
                    "available_at": available_at,
                    **({"failure_reason": "source_incomplete"} if terminal_failure else {}),
                },
                "$unset": {
                    "attempt_token": "",
                    "lease_until": "",
                    **({"failure_reason": ""} if not terminal_failure else {}),
                },
            },
        )
        return bool(result.matched_count)

    async def claim(self) -> dict[str, Any] | None:
        now = self.now()
        seller_filter = (
            {"seller_id": {"$in": sorted(self.allowed_sellers)}}
            if self.allowed_sellers is not None
            else {}
        )
        # A crashed final attempt must not strand the remaining catalog chunks.
        # Claim its expired lease atomically before recording the failed chunk.
        exhausted_catalog = await self.collection.find_one_and_update(
            {
                **seller_filter,
                "state": "running",
                "catalog_offset": {"$exists": True},
                "read_model": {"$in": sorted(self.enabled_models)},
                "lease_until": {"$lte": now},
                "attempts": {"$gte": MAX_ATTEMPTS},
            },
            {"$set": {"lease_until": now + LEASE, "attempt_token": uuid4().hex}},
            return_document=ReturnDocument.AFTER,
        )
        if exhausted_catalog:
            await self.finish(exhausted_catalog, succeeded=False)
        await self.collection.update_many(
            {
                **seller_filter,
                "catalog_offset": {"$exists": False},
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
        if (
            not succeeded
            and not retry
            and job.get("inventory_scope") is True
            and "inventory_offset" in job
            and failure_reason in {"source_incomplete", "source_temporarily_unavailable"}
        ):
            return await self.checkpoint_inventory(
                job,
                item_ids=job["inventory_ids"],
                offset=min(job["inventory_offset"] + 20, len(job["inventory_ids"])),
                unavailable=True,
            )
        fields: dict[str, Any] = {
            "state": "completed" if succeeded else "pending" if retry else "failed",
            "available_at": now
            + (timedelta(seconds=30 * 2 ** (job["attempts"] - 1)) if retry else COOLDOWN),
            "updated_at": now,
        }
        if succeeded and job["read_model"] in {
            "catalog_product_snapshots",
            "catalog_buybox_snapshots",
        }:
            observed = job["updated_at"]
            if observed.tzinfo is None:
                observed = observed.replace(tzinfo=UTC)
            fields["available_at"] = max(now, observed + COOLDOWN)
        unset = {"lease_until": "", "attempt_token": ""}
        if succeeded:
            unset["failure_reason"] = ""
        else:
            fields["failure_reason"] = failure_reason
        if "catalog_offset" in job and not retry:
            field = (
                "item_ids"
                if job["read_model"] == "catalog_buybox_snapshots"
                else "catalog_product_ids"
            )
            ids, offset = job[field], job["catalog_offset"]
            if type(offset) is not int or not 0 <= offset < len(ids) or offset % 20:
                raise ValueError("invalid catalog continuation offset")
            next_offset = min(offset + 20, len(ids))
            failed = list(job.get("catalog_failed_offsets", []))
            if not succeeded:
                failed.append(offset)
                fields["catalog_failure_reason"] = failure_reason
            done = next_offset == len(ids)
            fields.update(
                catalog_offset=next_offset,
                catalog_failed_offsets=failed,
                attempts=0,
                state=("failed" if failed else "completed") if done else "pending",
                available_at=now + COOLDOWN if done else now,
            )
            if failed:
                unset.pop("failure_reason", None)
                fields["failure_reason"] = (
                    fields.get("catalog_failure_reason") or job["catalog_failure_reason"]
                )
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
