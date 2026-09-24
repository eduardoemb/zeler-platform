"""Atomic staging yields and bounded retries; no acquisition worker is activated."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from zeler_platform_core.models import SheetsHistoryAcquisition, SheetsHistoryReceipt
from zeler_sheets.history_acquisition import HistoryAcquisitionStore, HistoryConflictError, _head


def _binding(head: SheetsHistoryAcquisition) -> dict[str, Any]:
    return {
        "history_protocol_version": 1,
        "history_acquisition_id": head.id,
        "history_generation": head.generation,
        "history_pass_number": head.pass_number,
        "history_checkpoint_revision": head.checkpoint_revision,
    }


class HistoryContinuation:
    def __init__(self, store: HistoryAcquisitionStore) -> None:
        self.store = store

    async def _current(
        self,
        job: dict[str, Any],
        head: SheetsHistoryAcquisition,
        session: Any,
    ) -> dict[str, Any]:
        await self.store._fence(job, head, session)
        if head.published_count:
            raise HistoryConflictError("continuation cannot withdraw publication progress")
        current = await self.store.heads.find_one({"_id": head.id}, session=session)
        if current is not None:
            current = SheetsHistoryAcquisition.model_validate(current).model_dump(by_alias=True)
        if current != head.model_dump(by_alias=True) or head.phase not in {
            "discover",
            "hydrate",
            "verify",
        }:
            raise HistoryConflictError("continuation requires the current staging checkpoint")
        claimed = await self.store.queue.collection.find_one({"_id": job["_id"]}, session=session)
        if claimed is None or claimed["attempts"] < 1:
            raise HistoryConflictError("continuation requires a claimed attempt")
        if claimed.get("history_acquisition_id", head.id) != head.id:
            raise HistoryConflictError("queue references another acquisition")
        if "history_protocol_version" in claimed and any(
            claimed.get(field) != value for field, value in _binding(head).items()
        ):
            raise HistoryConflictError("queue references another history checkpoint")
        return dict(claimed)

    async def _pending(
        self,
        job: dict[str, Any],
        head: SheetsHistoryAcquisition,
        attempts: int,
        delay: timedelta,
        session: Any,
    ) -> None:
        now = self.store.queue.now()
        result = await self.store.queue.collection.update_one(
            self.store.queue._owned(job, now),
            {
                "$set": {
                    **_binding(head),
                    "state": "pending",
                    "attempts": attempts,
                    "updated_at": now,
                    "available_at": now + delay,
                },
                "$unset": {"attempt_token": "", "lease_until": "", "failure_reason": ""},
            },
            session=session,
        )
        if result.matched_count != 1:
            raise HistoryConflictError("lease lost before continuation yield")

    async def progress(
        self,
        job: dict[str, Any],
        expected: SheetsHistoryAcquisition,
        proposed: SheetsHistoryAcquisition,
        receipts: list[SheetsHistoryReceipt],
    ) -> SheetsHistoryAcquisition:
        expected, proposed = _head(expected), _head(proposed)
        progress_fields = ("next_cursor", "phase", "discovered_count", "fetched_count")
        if all(getattr(expected, field) == getattr(proposed, field) for field in progress_fields):
            raise HistoryConflictError("a revision alone is not durable acquisition progress")

        async def transaction(session: Any) -> SheetsHistoryAcquisition:
            await self._current(job, expected, session)
            saved = await self.store.checkpoint(job, expected, proposed, receipts, session=session)
            await self._pending(job, saved, 0, timedelta(0), session)
            return saved

        async with await self.store.db.client.start_session() as session:
            return SheetsHistoryAcquisition.model_validate(
                await session.with_transaction(transaction)
            )

    async def begin_verification(
        self, job: dict[str, Any], expected: SheetsHistoryAcquisition
    ) -> SheetsHistoryAcquisition:
        """Allocate an observation pass, preserving the hydrated baseline and retry budget."""
        expected = _head(expected)
        if (
            expected.read_model != "orders"
            or expected.phase != "hydrate"
            or expected.next_cursor is not None
            or expected.source_total is None
            or expected.fetched_count != expected.discovered_count
        ):
            raise HistoryConflictError("verification requires hydrated enumeration")

        async def transaction(session: Any) -> SheetsHistoryAcquisition:
            await self._current(job, expected, session)
            scope = {
                "acquisition_id": expected.id,
                "generation": expected.generation,
                "pass_number": expected.pass_number,
            }
            counts = {
                kind: await self.store.receipts.count_documents(
                    {**scope, "kind": kind}, session=session
                )
                for kind in ("membership", "exclusion", "detail")
            }
            if (
                counts["membership"] != expected.discovered_count
                or counts["detail"] != expected.fetched_count
                or counts["membership"] + counts["exclusion"] != expected.source_total
                or await self.store.receipts.find_one(
                    {**scope, "source_payload": None}, session=session
                )
            ):
                raise HistoryConflictError("verification baseline lacks source receipts")
            saved = _head(
                SheetsHistoryAcquisition.model_validate(
                    {
                        **expected.model_dump(by_alias=True),
                        "pass_number": expected.pass_number + 1,
                        "active_range_id": None,
                        "checkpoint_revision": expected.checkpoint_revision + 1,
                        "page_sequence": 0,
                        "phase": "verify",
                        "next_cursor": 0,
                        "discovered_count": 0,
                        "fetched_count": 0,
                        "updated_at": self.store.queue.now(),
                    }
                )
            )
            result = await self.store.heads.replace_one(
                {
                    "_id": expected.id,
                    "generation": expected.generation,
                    "checkpoint_revision": expected.checkpoint_revision,
                },
                saved.model_dump(by_alias=True),
                session=session,
            )
            if result.matched_count != 1:
                raise HistoryConflictError("verification checkpoint changed")
            await self.store._fence(job, saved, session)
            await self._pending(job, saved, 0, timedelta(0), session)
            return saved

        async with await self.store.db.client.start_session() as session:
            return SheetsHistoryAcquisition.model_validate(
                await session.with_transaction(transaction)
            )

    async def begin_publication(
        self, job: dict[str, Any], expected: SheetsHistoryAcquisition
    ) -> SheetsHistoryAcquisition:
        """Hand a complete verified manifest to the bounded publisher atomically."""
        expected = _head(expected)
        if (
            expected.read_model != "orders"
            or expected.phase != "verify"
            or expected.next_cursor is not None
            or expected.active_range_id is not None
            or expected.source_total is None
            or expected.observed_from is None
            or expected.published_count
        ):
            raise HistoryConflictError("publication requires completed order verification")

        async def transaction(session: Any) -> SheetsHistoryAcquisition:
            await self._current(job, expected, session)
            scope = {
                "acquisition_id": expected.id,
                "generation": expected.generation,
                "pass_number": expected.pass_number,
            }
            receipts = self.store.receipts
            member_count = await receipts.count_documents(
                {**scope, "kind": "membership"}, session=session
            )
            outside_count = await receipts.count_documents(
                {
                    **scope,
                    "kind": "exclusion",
                    "exclusion_reason": "outside_requested_creation_interval",
                },
                session=session,
            )
            cancelled_count = await receipts.count_documents(
                {
                    **scope,
                    "kind": "exclusion",
                    "exclusion_reason": "seller_search_omits_source_confirmed_cancelled_order",
                },
                session=session,
            )
            excluded_count = await receipts.count_documents(
                {**scope, "kind": "exclusion"}, session=session
            )
            if (
                member_count != expected.discovered_count
                or excluded_count != outside_count + cancelled_count
                or member_count < cancelled_count
                or member_count - cancelled_count + outside_count != expected.source_total
            ):
                raise HistoryConflictError("verified order manifest count changed")
            missing_detail = await receipts.aggregate(
                [
                    {"$match": {**scope, "kind": "membership"}},
                    {
                        "$lookup": {
                            "from": "sheets_history_receipts",
                            "let": {"identity": "$resource_id"},
                            "pipeline": [
                                {
                                    "$match": {
                                        "acquisition_id": expected.id,
                                        "generation": expected.generation,
                                        "pass_number": {
                                            "$in": [expected.pass_number - 1, expected.pass_number]
                                        },
                                        "kind": "detail",
                                        "$expr": {"$eq": ["$resource_id", "$$identity"]},
                                    }
                                },
                                {"$limit": 1},
                            ],
                            "as": "details",
                        }
                    },
                    {"$match": {"details": {"$size": 0}}},
                    {"$limit": 1},
                ],
                session=session,
            ).to_list(length=1)
            if missing_detail:
                raise HistoryConflictError("verified order detail is missing")
            saved = _head(
                SheetsHistoryAcquisition.model_validate(
                    {
                        **expected.model_dump(by_alias=True),
                        "phase": "publish",
                        "fetched_count": member_count,
                        "checkpoint_revision": expected.checkpoint_revision + 1,
                        "updated_at": self.store.queue.now(),
                    }
                )
            )
            result = await self.store.heads.replace_one(
                {
                    "_id": expected.id,
                    "generation": expected.generation,
                    "checkpoint_revision": expected.checkpoint_revision,
                },
                saved.model_dump(by_alias=True),
                session=session,
            )
            if result.matched_count != 1:
                raise HistoryConflictError("publication handoff checkpoint changed")
            await self._pending(job, saved, 0, timedelta(0), session)
            return saved

        async with await self.store.db.client.start_session() as session:
            return SheetsHistoryAcquisition.model_validate(
                await session.with_transaction(transaction)
            )

    async def release(
        self,
        job: dict[str, Any],
        expected: SheetsHistoryAcquisition,
        *,
        reason: str,
    ) -> SheetsHistoryAcquisition:
        if reason not in {"quota", "failure", "cursor_expired", "source_drift"}:
            raise ValueError("unsupported continuation reason")
        expected = _head(expected)

        async def transaction(session: Any) -> SheetsHistoryAcquisition:
            claimed = await self._current(job, expected, session)
            restart = reason in {"cursor_expired", "source_drift"}
            if reason == "failure" or (restart and expected.drift_restarts == 3):
                finished = await self.store.queue.finish(
                    claimed,
                    succeeded=False,
                    retryable=reason == "failure",
                    failure_reason="source_temporarily_unavailable"
                    if reason == "failure"
                    else "source_incomplete",
                    session=session,
                )
                if not finished:
                    raise HistoryConflictError("lease lost before failure release")
                await self.store.queue.collection.update_one(
                    {"_id": claimed["_id"]},
                    {"$set": _binding(expected)},
                    session=session,
                )
                return expected
            saved = expected
            if restart:
                saved = _head(
                    SheetsHistoryAcquisition.model_validate(
                        {
                            **expected.model_dump(by_alias=True),
                            "pass_number": expected.pass_number + 1,
                            "active_range_id": None,
                            "drift_restarts": expected.drift_restarts + 1,
                            "checkpoint_revision": expected.checkpoint_revision + 1,
                            "page_sequence": 0,
                            "phase": "discover",
                            "next_cursor": None,
                            "source_total": None,
                            "discovered_count": 0,
                            "fetched_count": 0,
                            "published_count": 0,
                            "publish_after": None,
                            "observed_from": None,
                            "observed_until": None,
                            "updated_at": self.store.queue.now(),
                        }
                    )
                )
                result = await self.store.heads.replace_one(
                    {
                        "_id": expected.id,
                        "generation": expected.generation,
                        "checkpoint_revision": expected.checkpoint_revision,
                    },
                    saved.model_dump(by_alias=True),
                    session=session,
                )
                if result.matched_count != 1:
                    raise HistoryConflictError("restart checkpoint changed")
            await self.store._fence(job, saved, session)
            await self._pending(
                claimed,
                saved,
                claimed["attempts"] - 1,
                timedelta(seconds=1 if reason == "quota" else 0),
                session,
            )
            return saved

        async with await self.store.db.client.start_session() as session:
            return SheetsHistoryAcquisition.model_validate(
                await session.with_transaction(transaction)
            )
