"""Fenced subdivision staging; no producer activation or publication authority."""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

from zeler_platform_core.models import (
    SheetsHistoryAcquisition,
    SheetsHistoryOrderRange,
    SheetsHistoryReceipt,
)
from zeler_platform_core.models.base import assert_aware_utc_datetime
from zeler_sheets.history_acquisition import (
    HistoryConflictError,
    HistoryLimitError,
    _document,
    _head,
)
from zeler_sheets.history_continuation import HistoryContinuation
from zeler_sheets.history_order_subdivision import OrderRangeNode, subdivide_order_range


class RangeSourceDriftError(HistoryConflictError):
    """Range observations disagree; restart acquisition rather than reset ownership."""


class HistoryRangeStore:
    def __init__(self, continuation: HistoryContinuation, *, result_budget: int = 10000) -> None:
        if type(result_budget) is not int or result_budget < 1:
            raise ValueError("invalid local range budget")
        self.continuation = continuation
        self.store = continuation.store
        self.collection = self.store.db.sheets_history_order_ranges
        self.result_budget = result_budget

    def _scope(self, head: SheetsHistoryAcquisition) -> dict[str, Any]:
        return {
            "acquisition_id": head.id,
            "generation": head.generation,
            "pass_number": head.pass_number,
        }

    def _node(self, head: SheetsHistoryAcquisition, node: OrderRangeNode) -> dict[str, Any]:
        identity = f"{head.id}\0{head.generation}\0{head.pass_number}\0{node.node_id}"
        return _document(
            SheetsHistoryOrderRange.model_validate(
                {
                    **node.model_dump(),
                    **self._scope(head),
                    "seller_id": head.seller_id,
                    "_id": hashlib.sha256(identity.encode()).hexdigest(),
                }
            ),
            64 * 1024,
        )

    async def _active(self, head: SheetsHistoryAcquisition, session: Any) -> dict[str, Any]:
        node = await self.collection.find_one(
            {"_id": head.active_range_id, **self._scope(head)}, session=session
        )
        if (
            node is None
            or node["state"] != "pending"
            or node["seller_id"] != head.seller_id
            or node["root_id"] != head.id
        ):
            raise HistoryConflictError("active range binding changed")
        validated = SheetsHistoryOrderRange.model_validate(node)
        if not head.date_from <= validated.date_from < validated.date_to <= head.date_to:
            raise HistoryConflictError("active range escapes fixed bounds")
        if validated.root_id != head.id or validated.next_offset != (head.next_cursor or 0):
            raise HistoryConflictError("active range checkpoint changed")
        return dict(node)

    async def _run(
        self,
        job: dict[str, Any],
        head: SheetsHistoryAcquisition,
        action: Callable[[Any], Awaitable[tuple[dict[str, Any], list[SheetsHistoryReceipt]]]],
        observed_at: datetime | None = None,
    ) -> SheetsHistoryAcquisition:
        head = _head(head)
        if observed_at is not None:
            observed_at = assert_aware_utc_datetime(observed_at)
        if head.read_model != "orders" or head.phase not in {"discover", "verify"}:
            raise HistoryConflictError("range store requires order discovery or verification")

        async def transaction(session: Any) -> SheetsHistoryAcquisition:
            await self.continuation._current(job, head, session)
            changes, receipts = await action(session)
            if observed_at is not None:
                changes["observed_from"] = min(
                    observed_at, changes.get("observed_from") or head.observed_from or observed_at
                )
                changes["observed_until"] = max(
                    observed_at, changes.get("observed_until") or head.observed_until or observed_at
                )
            proposed = SheetsHistoryAcquisition.model_validate(
                {
                    **head.model_dump(by_alias=True),
                    "checkpoint_revision": head.checkpoint_revision + 1,
                    "page_sequence": head.page_sequence + 1,
                    "updated_at": self.store.queue.now(),
                    **changes,
                }
            )
            saved = await self.store.checkpoint(job, head, proposed, receipts, session=session)
            await self.continuation._pending(job, saved, 0, timedelta(0), session)
            return saved

        async with await self.store.db.client.start_session() as session:
            return SheetsHistoryAcquisition.model_validate(
                await session.with_transaction(transaction)
            )

    async def start(
        self,
        job: dict[str, Any],
        head: SheetsHistoryAcquisition,
        *,
        observed_total: int | None = None,
        observed_at: datetime | None = None,
    ) -> SheetsHistoryAcquisition:
        async def action(session: Any) -> tuple[dict[str, Any], list[SheetsHistoryReceipt]]:
            if (
                head.active_range_id is not None
                or head.discovered_count
                or head.next_cursor not in (None, 0)
            ):
                raise HistoryConflictError("range root requires untouched discovery")
            node = self._node(
                head,
                OrderRangeNode(
                    node_id=head.id, root_id=head.id, date_from=head.date_from, date_to=head.date_to
                ),
            )
            await self.collection.insert_one(node, session=session)
            if observed_total is not None:
                return await self._split_node(head, node, observed_total, session), []
            return {"active_range_id": node["_id"], "next_cursor": 0}, []

        return await self._run(job, head, action, observed_at)

    async def split(
        self,
        job: dict[str, Any],
        head: SheetsHistoryAcquisition,
        *,
        observed_total: int,
        observed_at: datetime | None = None,
    ) -> SheetsHistoryAcquisition:
        async def action(session: Any) -> tuple[dict[str, Any], list[SheetsHistoryReceipt]]:
            parent = await self._active(head, session)
            return await self._split_node(head, parent, observed_total, session), []

        return await self._run(job, head, action, observed_at)

    async def _split_node(
        self,
        head: SheetsHistoryAcquisition,
        parent: dict[str, Any],
        observed_total: int,
        session: Any,
    ) -> dict[str, Any]:
        if parent["next_offset"]:
            raise HistoryConflictError("partially acquired ranges require restart before splitting")
        node = OrderRangeNode.model_validate(
            {key: parent[key] for key in OrderRangeNode.model_fields}
        )
        children = subdivide_order_range(
            node, observed_total=observed_total, local_result_budget=self.result_budget
        )
        if len(children) != 2:
            raise HistoryConflictError("range is within local budget")
        documents = [self._node(head, child) for child in children]
        await self.collection.insert_many(documents, session=session)
        await self.collection.update_one(
            {"_id": parent["_id"]},
            {"$set": {"state": "split", "source_total": observed_total}},
            session=session,
        )
        return {"active_range_id": documents[0]["_id"], "next_cursor": 0}

    async def page(
        self,
        job: dict[str, Any],
        head: SheetsHistoryAcquisition,
        *,
        source_total: int,
        next_offset: int,
        receipts: list[SheetsHistoryReceipt],
        observed_at: datetime | None = None,
        verify_manifest: Callable[[Any, bool], Awaitable[None]] | None = None,
    ) -> SheetsHistoryAcquisition:
        if len(receipts) > 50:
            raise HistoryLimitError("range page exceeds local record budget")
        if head.phase == "verify" and verify_manifest is None:
            raise HistoryConflictError("verification requires manifest comparison")

        async def action(session: Any) -> tuple[dict[str, Any], list[SheetsHistoryReceipt]]:
            node = await self._active(head, session)
            state = "enumerated" if next_offset == source_total else "pending"
            changed = SheetsHistoryOrderRange.model_validate(
                {**node, "source_total": source_total, "next_offset": next_offset, "state": state}
            )
            if source_total > self.result_budget:
                raise HistoryLimitError("range exceeds local result budget")
            if node["source_total"] not in (None, source_total):
                raise RangeSourceDriftError("range total changed")
            if next_offset - node["next_offset"] != len(receipts):
                raise HistoryConflictError("range page length changed")
            if not receipts and source_total != 0:
                raise HistoryConflictError("empty range page makes no progress")
            bounds = OrderRangeNode.model_validate(
                {key: node[key] for key in OrderRangeNode.model_fields}
            )
            lower, upper = bounds.provider_hours()
            for receipt in receipts:
                raw = receipt.source_payload or {}
                created = assert_aware_utc_datetime(
                    datetime.fromisoformat(str(raw.get("date_created")))
                )
                inside = bounds.date_from <= created < bounds.date_to
                if (
                    not lower <= created < upper + timedelta(hours=1)
                    or (receipt.kind != ("membership" if inside else "exclusion"))
                    or (
                        not inside
                        and receipt.exclusion_reason != "outside_requested_creation_interval"
                    )
                ):
                    raise HistoryConflictError("receipt does not match active range bounds")
                if await self.store.receipts.find_one(
                    {**self._scope(head), "resource_id": receipt.resource_id}, session=session
                ):
                    raise HistoryConflictError("range page repeats acquired identity")
            await self.collection.replace_one(
                {"_id": node["_id"]}, _document(changed, 64 * 1024), session=session
            )
            active = changed.model_dump(by_alias=True)
            if state == "enumerated":
                active = await self.collection.find_one(
                    {**self._scope(head), "state": "pending"},
                    sort=[("date_from", 1), ("node_id", 1)],
                    session=session,
                )
            changes: dict[str, Any] = {
                "active_range_id": active["_id"] if active else None,
                "next_cursor": active["next_offset"] if active else None,
                "discovered_count": head.discovered_count
                + sum(receipt.kind == "membership" for receipt in receipts),
            }
            if receipts:
                changes["observed_from"] = min(
                    [receipt.observed_at for receipt in receipts]
                    + ([head.observed_from] if head.observed_from is not None else [])
                )
                changes["observed_until"] = max(
                    [receipt.observed_at for receipt in receipts]
                    + ([head.observed_until] if head.observed_until is not None else [])
                )
            if active is None:
                await self._check_split_totals(head, session)
                totals = await self.collection.aggregate(
                    [
                        {"$match": {**self._scope(head), "state": "enumerated"}},
                        {"$group": {"_id": None, "total": {"$sum": "$source_total"}}},
                    ],
                    session=session,
                ).to_list(length=1)
                changes.update(
                    phase="verify" if head.phase == "verify" else "hydrate",
                    source_total=totals[0]["total"],
                )
            if verify_manifest is not None:
                await verify_manifest(session, active is None)
            return changes, receipts

        return await self._run(job, head, action, observed_at)

    async def _check_split_totals(self, head: SheetsHistoryAcquisition, session: Any) -> None:
        inconsistent = await self.collection.aggregate(
            [
                {"$match": {**self._scope(head), "state": "split"}},
                {
                    "$lookup": {
                        "from": "sheets_history_order_ranges",
                        "let": {"parent": "$node_id"},
                        "pipeline": [
                            {
                                "$match": {
                                    **self._scope(head),
                                    "$expr": {"$eq": ["$parent_id", "$$parent"]},
                                }
                            }
                        ],
                        "as": "children",
                    }
                },
                {
                    "$match": {
                        "$expr": {
                            "$or": [
                                {"$ne": [{"$size": "$children"}, 2]},
                                {"$ne": ["$source_total", {"$sum": "$children.source_total"}]},
                            ]
                        }
                    }
                },
                {"$limit": 1},
            ],
            session=session,
        ).to_list(length=1)
        if inconsistent:
            raise RangeSourceDriftError("subdivision source totals changed")
