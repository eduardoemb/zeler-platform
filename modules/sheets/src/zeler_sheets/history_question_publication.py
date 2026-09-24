"""Bounded question projection and receipt-backed scan finalization."""

from __future__ import annotations

from datetime import datetime, timedelta
from functools import partial
from typing import Any

from bson import BSON

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
from zeler_sheets.history_publication import _withdraw
from zeler_sheets.item_projection import item_source_fingerprint


def _observed(receipt: SheetsHistoryReceipt) -> datetime:
    return receipt.observed_at


class HistoryQuestionPublisher:
    def __init__(self, continuation: HistoryContinuation) -> None:
        self.continuation = continuation
        self.store = continuation.store

    async def batch(
        self, job: dict[str, Any], expected: SheetsHistoryAcquisition, *, limit: int = 20
    ) -> SheetsHistoryAcquisition:
        head = _head(expected)
        if type(limit) is not int or not 1 <= limit <= 20:
            raise HistoryLimitError("question publication requires 1..20 records")
        if head.read_model != "questions" or head.phase != "publish" or head.next_cursor:
            raise HistoryConflictError("question publication requires a verified handoff")
        if head.published_count >= head.fetched_count:
            raise HistoryConflictError("question publication finalization remains pending")

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
                raise HistoryConflictError("question publication checkpoint changed")
            scope = {
                "acquisition_id": head.id,
                "generation": head.generation,
                "pass_number": head.pass_number,
                "seller_id": head.seller_id,
                "read_model": "questions",
            }
            members = await (
                self.store.receipts.find(
                    {
                        **scope,
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
                raise HistoryConflictError("question publication membership is incomplete")
            details = []
            byte_count = 0
            for member in members:
                receipt = await self.store.receipts.find_one(
                    {**scope, "kind": "detail", "resource_id": member["resource_id"]},
                    session=session,
                )
                if receipt is None:
                    raise HistoryConflictError("question publication detail is missing")
                detail = SheetsHistoryReceipt.model_validate(receipt)
                byte_count += len(BSON.encode(_document(detail, 1024 * 1024)))
                source, payload = detail.source_payload, detail.payload
                if (
                    source is None
                    or payload is None
                    or item_source_fingerprint(source) != detail.source_hash
                    or item_source_fingerprint(payload) != detail.payload_hash
                ):
                    raise HistoryConflictError("question publication receipt fingerprint mismatch")
                created = datetime.fromisoformat(
                    str(payload.get("date_created", "")).replace("Z", "+00:00")
                )
                if (
                    str(payload.get("id")) != detail.resource_id
                    or str(payload.get("seller_id")) != head.seller_id
                    or created.tzinfo is None
                    or not head.date_from <= created < head.date_to
                ):
                    raise HistoryConflictError("question publication identity or interval mismatch")
                details.append(detail)
            if byte_count > 4 * 1024 * 1024:
                raise HistoryLimitError("question publication inputs exceed local byte budget")
            markers = self.store.db["sheets_read_model_freshness"]
            marker = await markers.find_one({"_id": f"{head.seller_id}:questions"}, session=session)
            if marker is not None:
                withdrawn = _withdraw(marker, head)
                if len(BSON.encode(withdrawn)) > 1024 * 1024:
                    raise HistoryLimitError("question publication proof exceeds local budget")
                await markers.replace_one({"_id": marker["_id"]}, withdrawn, session=session)
            for detail in details:
                writer = SheetsEventPersistence(db=self.store.db, clock=partial(_observed, detail))
                await writer.persist(
                    event_type="questions.updated",
                    seller_id=head.seller_id,
                    resource=detail.payload or {},
                    session=session,
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
                raise HistoryConflictError("question publication head changed")
            await self.continuation._pending(job, saved, 0, timedelta(0), session)
            return saved

        async with await self.store.db.client.start_session() as session:
            return SheetsHistoryAcquisition.model_validate(
                await session.with_transaction(transaction)
            )

    async def finalize(
        self, job: dict[str, Any], expected: SheetsHistoryAcquisition
    ) -> SheetsHistoryAcquisition:
        head = _head(expected)
        observed_until = head.observed_until
        if (
            head.read_model != "questions"
            or head.phase != "publish"
            or head.next_cursor is not None
            or head.source_total is None
            or observed_until is None
            or head.published_count != head.fetched_count
            or head.fetched_count != head.source_total
        ):
            raise HistoryConflictError("question finalization requires every verified member")

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
                raise HistoryConflictError("question finalization checkpoint changed")
            scope = {
                "seller_id": head.seller_id,
                "date_created": {"$gte": head.date_from, "$lt": head.date_to},
            }
            questions = self.store.db.questions
            if await questions.count_documents(scope, session=session) != head.fetched_count:
                raise HistoryConflictError("question inventory differs from verified scan")
            extra = await questions.aggregate(
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
                raise HistoryConflictError("question inventory differs from verified scan")
            async for row in questions.find(
                scope, {"item_id": 1, "from_user_id": 1, "status": 1, "answer": 1}, session=session
            ):
                if (
                    not row.get("item_id")
                    or not row.get("from_user_id")
                    or (row.get("status") == "ANSWERED" and not row.get("answer"))
                ):
                    raise HistoryConflictError("published question required data unavailable")
            proof = reconciled_marker(
                seller_id=head.seller_id,
                read_model="questions",
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
                "updated_at": self.store.queue.now(),
                "retained_intervals": merged,
            }
            if len(BSON.encode(marker)) > 1024 * 1024:
                raise HistoryLimitError("question publication proof exceeds local budget")
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
                completed.model_dump(by_alias=True),
                session=session,
            )
            if result.matched_count != 1 or not await self.store.queue.finish(
                job, succeeded=True, session=session
            ):
                raise HistoryConflictError("question finalization lost its owner")
            return completed

        async with await self.store.db.client.start_session() as session:
            return SheetsHistoryAcquisition.model_validate(
                await session.with_transaction(transaction)
            )
