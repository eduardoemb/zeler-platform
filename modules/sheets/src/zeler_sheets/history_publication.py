"""Bounded guarded order projection and receipt-backed coverage finalization."""

from __future__ import annotations

from contextlib import suppress
from datetime import datetime, timedelta
from functools import partial
from typing import Any
from uuid import uuid4

from bson import BSON

from zeler_platform_core.devoluciones_readiness import (
    DevolucionesLeaseLostError,
    acquire_devoluciones_operation,
    finish_devoluciones_operation,
    operation_lease_guard,
)
from zeler_platform_core.models import SheetsHistoryAcquisition, SheetsHistoryReceipt
from zeler_sheets.event_persistence import SheetsEventPersistence
from zeler_sheets.formulas.refresh import merge_interval_proofs, reconciled_marker
from zeler_sheets.history_acquisition import (
    HistoryConflictError,
    HistoryLimitError,
    _document,
    _head,
)
from zeler_sheets.history_continuation import HistoryContinuation, _binding
from zeler_sheets.item_projection import item_source_fingerprint


def _withdraw(marker: dict[str, Any], head: SheetsHistoryAcquisition) -> dict[str, Any]:
    if marker.get("state") != "reconciled":
        return marker
    remaining = []
    for proof in [marker, *marker.get("retained_intervals", [])]:
        start, end = proof.get("date_from"), proof.get("reconciled_until")
        if (
            proof.get("state") != "reconciled"
            or not isinstance(start, datetime)
            or not isinstance(end, datetime)
        ):
            continue
        compact = {
            key: value
            for key, value in proof.items()
            if key in {"state", "date_from", "reconciled_until", "valid_until", "coverage_basis"}
        }
        if end <= head.date_from:
            remaining.append({**compact, "valid_until": min(proof["valid_until"], head.date_from)})
            continue
        if start >= head.date_to:
            remaining.append(compact)
            continue
        if start < head.date_from:
            remaining.append(
                {
                    **compact,
                    "reconciled_until": head.date_from,
                    "valid_until": min(proof["valid_until"], head.date_from),
                }
            )
        if end > head.date_to:
            remaining.append({**compact, "date_from": head.date_to})
    if not remaining:
        return {**marker, "state": "stale", "retained_intervals": []}
    remaining.sort(key=lambda proof: proof["reconciled_until"])
    latest = remaining.pop()
    return {
        **marker,
        **latest,
        "fresh_until": latest["reconciled_until"],
        "retained_intervals": remaining,
    }


def _observed(receipt: SheetsHistoryReceipt) -> datetime:
    return receipt.observed_at


class HistoryOrderPublisher:
    def __init__(self, continuation: HistoryContinuation) -> None:
        self.continuation = continuation
        self.store = continuation.store

    async def finalize(
        self, job: dict[str, Any], expected: SheetsHistoryAcquisition
    ) -> SheetsHistoryAcquisition:
        head = _head(expected)
        observed_until = head.observed_until
        if (
            head.read_model != "orders"
            or head.phase != "publish"
            or head.next_cursor is not None
            or head.source_total is None
            or observed_until is None
            or head.published_count != head.fetched_count
        ):
            raise HistoryConflictError("publication finalization requires every verified order")

        async def transaction(session: Any) -> SheetsHistoryAcquisition:
            await self.store._fence(job, head, session)
            current = await self.store.heads.find_one({"_id": head.id}, session=session)
            claimed = await self.store.queue.collection.find_one(
                {"_id": job["_id"]}, session=session
            )
            if (
                current is None
                or SheetsHistoryAcquisition.model_validate(current) != head
                or claimed is None
                or any(claimed.get(key) != value for key, value in _binding(head).items())
            ):
                raise HistoryConflictError("publication finalization checkpoint changed")
            scope = {
                "seller_id": head.seller_id,
                "date_created": {"$gte": head.date_from, "$lt": head.date_to},
            }
            orders = self.store.db.orders
            if await orders.count_documents(scope, session=session) != head.fetched_count:
                raise HistoryConflictError("published order inventory differs from verified source")
            extra = await orders.aggregate(
                [
                    {"$match": scope},
                    {
                        "$lookup": {
                            "from": "sheets_history_receipts",
                            "let": {"identity": {"$toString": "$_id"}},
                            "pipeline": [
                                {
                                    "$match": {
                                        "acquisition_id": head.id,
                                        "generation": head.generation,
                                        "pass_number": head.pass_number,
                                        "kind": "membership",
                                        "$expr": {"$eq": ["$resource_id", "$$identity"]},
                                    }
                                },
                                {"$limit": 1},
                            ],
                            "as": "observations",
                        }
                    },
                    {"$match": {"observations": {"$size": 0}}},
                    {"$limit": 1},
                ],
                session=session,
            ).to_list(length=1)
            if extra:
                raise HistoryConflictError("published order inventory differs from verified source")
            async for row in orders.find(
                scope,
                {"buyer_id": 1, "items": 1, "shipment_id": 1, "tags": 1, "unavailable_fields": 1},
                session=session,
            ):
                unavailable = set(row.get("unavailable_fields") or [])
                if (
                    (not row.get("buyer_id") and "buyer_id" not in unavailable)
                    or not row.get("items")
                    or (
                        "shipping" in unavailable
                        and not row.get("shipment_id")
                        and "no_shipping" not in (row.get("tags") or [])
                        and "shipment_id" not in unavailable
                    )
                ):
                    raise HistoryConflictError("published order required data unavailable")
            now = self.store.queue.now()
            proof = reconciled_marker(
                seller_id=head.seller_id,
                read_model="orders",
                start=head.date_from,
                end=head.date_to,
                now=observed_until,
            )
            markers = self.store.db["sheets_read_model_freshness"]
            current_marker = await markers.find_one(
                {"_id": proof["_id"], "seller_id": head.seller_id}, session=session
            )
            candidates = [proof]
            if current_marker is not None and current_marker.get("state") == "reconciled":
                candidates.append(current_marker)
                candidates.extend(current_marker.get("retained_intervals", []))
            merged = merge_interval_proofs(candidates)
            latest = merged.pop()
            marker = {
                **proof,
                **latest,
                "fresh_until": latest["reconciled_until"],
                "updated_at": now,
                "retained_intervals": merged,
            }
            if len(BSON.encode(marker)) > 1024 * 1024:
                raise HistoryLimitError("publication proof document exceeds local budget")
            await markers.replace_one(
                {"_id": proof["_id"], "seller_id": head.seller_id},
                marker,
                upsert=True,
                session=session,
            )
            completed = _head(
                SheetsHistoryAcquisition.model_validate(
                    {
                        **head.model_dump(by_alias=True),
                        "phase": "completed",
                        "checkpoint_revision": head.checkpoint_revision + 1,
                        "updated_at": now,
                    }
                )
            )
            result = await self.store.heads.replace_one(
                {
                    "_id": head.id,
                    "generation": head.generation,
                    "checkpoint_revision": head.checkpoint_revision,
                },
                completed.model_dump(by_alias=True),
                session=session,
            )
            if result.matched_count != 1 or not await self.store.queue.finish(
                job, succeeded=True, session=session
            ):
                raise HistoryConflictError("publication finalization lost its owner")
            return completed

        async with await self.store.db.client.start_session() as session:
            return SheetsHistoryAcquisition.model_validate(
                await session.with_transaction(transaction)
            )

    async def batch(
        self, job: dict[str, Any], expected: SheetsHistoryAcquisition, *, limit: int = 20
    ) -> SheetsHistoryAcquisition:
        head = _head(expected)
        if type(limit) is not int or not 1 <= limit <= 20:
            raise HistoryLimitError("publication requires 1..20 records")
        if head.phase != "publish" or head.read_model != "orders" or head.next_cursor is not None:
            raise HistoryConflictError("publication requires persisted publish prerequisite")
        if head.published_count >= head.fetched_count:
            raise HistoryConflictError("publication finalization remains pending")
        operation = await acquire_devoluciones_operation(
            db=self.store.db,
            seller_id=head.seller_id,
            scope="devoluciones",
            operation_id=f"history:{head.id}:{head.checkpoint_revision}",
            attempt_token=uuid4().hex,
            invalidate_readiness=False,
        )

        async def transaction(session: Any) -> SheetsHistoryAcquisition:
            await self.store._fence(job, head, session)
            current = await self.store.heads.find_one({"_id": head.id}, session=session)
            claimed = await self.store.queue.collection.find_one(
                {"_id": job["_id"]}, session=session
            )
            if (
                current is None
                or SheetsHistoryAcquisition.model_validate(current) != head
                or claimed is None
                or any(claimed.get(key) != value for key, value in _binding(head).items())
            ):
                raise HistoryConflictError("publication checkpoint changed")
            scope = {
                "acquisition_id": head.id,
                "generation": head.generation,
                "seller_id": head.seller_id,
                "read_model": "orders",
            }
            members = (
                await self.store.receipts.find(
                    {
                        **scope,
                        "pass_number": head.pass_number,
                        "kind": "membership",
                        "resource_id": {"$gt": head.publish_after or ""},
                    },
                    session=session,
                )
                .sort("resource_id", 1)
                .limit(limit)
                .to_list(length=limit)
            )
            if not members:
                raise HistoryConflictError("publication membership is incomplete")
            details = []
            byte_count = 0
            for member in members:
                receipt = await self.store.receipts.find_one(
                    {
                        **scope,
                        "pass_number": {"$in": [head.pass_number - 1, head.pass_number]},
                        "kind": "detail",
                        "resource_id": member["resource_id"],
                    },
                    sort=[("pass_number", -1)],
                    session=session,
                )
                if receipt is None:
                    raise HistoryConflictError("publication detail is missing")
                detail = SheetsHistoryReceipt.model_validate(receipt)
                byte_count += len(BSON.encode(_document(detail, 1024 * 1024)))
                payload = detail.payload or {}
                source = detail.source_payload
                if (
                    source is None
                    or item_source_fingerprint(source) != detail.source_hash
                    or item_source_fingerprint(payload) != detail.payload_hash
                ):
                    raise HistoryConflictError("publication receipt fingerprint mismatch")
                for document in (payload, source):
                    seller = document.get("seller")
                    created = datetime.fromisoformat(
                        str(document.get("date_created", "")).replace("Z", "+00:00")
                    )
                    if (
                        str(document.get("id")) != detail.resource_id
                        or not isinstance(seller, dict)
                        or str(seller.get("id")) != head.seller_id
                        or created.tzinfo is None
                        or not head.date_from <= created < head.date_to
                    ):
                        raise HistoryConflictError(
                            "publication receipt identity or interval mismatch"
                        )
                details.append(detail)
            if byte_count > 4 * 1024 * 1024:
                raise HistoryLimitError("publication receipt inputs exceed local byte budget")
            markers = self.store.db["sheets_read_model_freshness"]
            marker = await markers.find_one({"_id": f"{head.seller_id}:orders"}, session=session)
            if marker is not None:
                withdrawn = _withdraw(marker, head)
                if len(BSON.encode(withdrawn)) > 1024 * 1024:
                    raise HistoryLimitError("publication proof document exceeds local budget")
                await markers.replace_one({"_id": marker["_id"]}, withdrawn, session=session)
            for detail in details:
                writer = SheetsEventPersistence(db=self.store.db, clock=partial(_observed, detail))
                await writer.persist(
                    event_type="orders.updated",
                    seller_id=head.seller_id,
                    resource=detail.payload or {},
                    operation=operation,
                    session=session,
                    unavailable_fields=frozenset(detail.unavailable_fields),
                )
            saved = _head(
                SheetsHistoryAcquisition.model_validate(
                    {
                        **head.model_dump(by_alias=True),
                        "published_count": head.published_count + len(details),
                        "publish_after": details[-1].resource_id,
                        "checkpoint_revision": head.checkpoint_revision + 1,
                        "updated_at": self.store.queue.now(),
                    }
                )
            )
            result = await self.store.heads.replace_one(
                {
                    "_id": head.id,
                    "generation": head.generation,
                    "checkpoint_revision": head.checkpoint_revision,
                },
                saved.model_dump(by_alias=True),
                session=session,
            )
            if result.matched_count != 1:
                raise HistoryConflictError("publication head changed")
            released = await self.store.db["sheets_devoluciones_operations"].update_one(
                operation_lease_guard(operation),
                [
                    {
                        "$set": {
                            "state": "succeeded",
                            "lease_until": "$$NOW",
                            "updated_at": "$$NOW",
                            "finished_at": "$$NOW",
                            "error_code": None,
                        }
                    }
                ],
                session=session,
            )
            if released.matched_count != 1:
                raise DevolucionesLeaseLostError("publication operation lease lost")
            await self.continuation._pending(job, saved, 0, timedelta(0), session)
            return saved

        try:
            async with await self.store.db.client.start_session() as session:
                return SheetsHistoryAcquisition.model_validate(
                    await session.with_transaction(transaction)
                )
        except BaseException:
            with suppress(DevolucionesLeaseLostError):
                await finish_devoluciones_operation(
                    db=self.store.db, operation=operation, succeeded=False
                )
            raise
