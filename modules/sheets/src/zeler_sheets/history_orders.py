"""Bounded creation-range staging and manifest observation, never coverage authority."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from bson import BSON

from zeler_platform_core.clients.meli_gateway_client import GatewayRateLimitError
from zeler_platform_core.models import SheetsHistoryAcquisition, SheetsHistoryReceipt
from zeler_sheets.formulas.pacing import (
    LocalQuotaTimeoutError,
    recovery_fetch_resource,
    recovery_quota_deadline,
)
from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker, _date
from zeler_sheets.history_acquisition import HistoryConflictError, HistoryLimitError
from zeler_sheets.history_continuation import HistoryContinuation
from zeler_sheets.history_order_subdivision import OrderRangeNode
from zeler_sheets.history_range_store import HistoryRangeStore, RangeSourceDriftError
from zeler_sheets.item_projection import item_source_fingerprint


class OrderEnumerationDriftError(ValueError):
    """A page contradicts already staged enumeration evidence."""


class HistoryHandoffPendingError(HistoryConflictError):
    """Acquisition reached a local publication boundary, not a provider failure."""


def _version(resource: dict[str, Any]) -> str | None:
    value = resource.get("date_last_updated")
    return None if value is None else _date(value).isoformat(timespec="milliseconds")


class HistoryOrdersProducer:
    def __init__(self, worker: FormulaRecoveryWorker, continuation: HistoryContinuation) -> None:
        self.worker = worker
        self.continuation = continuation
        self.ranges = HistoryRangeStore(continuation)

    async def step(
        self,
        job: dict[str, Any],
        head: SheetsHistoryAcquisition,
    ) -> SheetsHistoryAcquisition:
        if head.read_model != "orders" or head.phase not in {"discover", "hydrate", "verify"}:
            raise HistoryConflictError("this producer only stages order observations")
        async with (
            await self.worker.db.client.start_session() as session,
            session.start_transaction(),
        ):
            await self.continuation._current(job, head, session)
        try:
            with recovery_quota_deadline(asyncio.get_running_loop().time() + 239) as quota:
                async with asyncio.timeout(240):
                    if head.phase == "verify" and head.next_cursor is None:
                        return await self._known_cancelled(job, head)
                    if head.phase in {"discover", "verify"}:
                        return await self._discover(job, head)
                    return await self._hydrate(job, head)
        except (OrderEnumerationDriftError, RangeSourceDriftError):
            return await self.continuation.release(job, head, reason="source_drift")
        except (HistoryLimitError, HistoryConflictError):
            raise
        except LocalQuotaTimeoutError:
            return await self.continuation.release(job, head, reason="quota")
        except (httpx.HTTPError, GatewayRateLimitError, TimeoutError, ValueError) as error:
            reason = "quota" if isinstance(error, TimeoutError) and quota.expired else "failure"
            return await self.continuation.release(job, head, reason=reason)

    def _receipt(
        self,
        head: SheetsHistoryAcquisition,
        resource_id: str,
        kind: str,
        **fields: Any,
    ) -> SheetsHistoryReceipt:
        identity = (head.id, str(head.generation), str(head.pass_number), kind, resource_id)
        return SheetsHistoryReceipt.model_validate(
            {
                "_id": hashlib.sha256("\0".join(identity).encode()).hexdigest(),
                "acquisition_id": head.id,
                "seller_id": head.seller_id,
                "read_model": "orders",
                "generation": head.generation,
                "pass_number": head.pass_number,
                "page_sequence": head.page_sequence + 1,
                "kind": kind,
                "resource_id": resource_id,
                "observed_at": self.worker.queue.now(),
                **fields,
            }
        )

    async def _save(
        self,
        job: dict[str, Any],
        head: SheetsHistoryAcquisition,
        receipts: list[SheetsHistoryReceipt],
        **changes: Any,
    ) -> SheetsHistoryAcquisition:
        now = self.worker.queue.now()
        proposed = SheetsHistoryAcquisition.model_validate(
            {
                **head.model_dump(by_alias=True),
                "checkpoint_revision": head.checkpoint_revision + 1,
                "page_sequence": head.page_sequence + 1,
                "updated_at": now,
                "observed_from": head.observed_from or now,
                "observed_until": now,
                **changes,
            }
        )
        return await self.continuation.progress(job, head, proposed, receipts)

    async def _discover(
        self,
        job: dict[str, Any],
        head: SheetsHistoryAcquisition,
    ) -> SheetsHistoryAcquisition:
        offset = int(head.next_cursor or 0)
        active = await self.ranges._active(head, None) if head.active_range_id is not None else None
        bounds = (
            OrderRangeNode.model_validate({key: active[key] for key in OrderRangeNode.model_fields})
            if active
            else OrderRangeNode(
                node_id=head.id, root_id=head.id, date_from=head.date_from, date_to=head.date_to
            )
        )
        start_hour, last_hour = bounds.provider_hours()
        params = {
            "seller": head.seller_id,
            "order.date_created.from": start_hour.isoformat(timespec="milliseconds"),
            "order.date_created.to": last_hour.isoformat(timespec="milliseconds"),
            "sort": "date_asc",
            "offset": str(offset),
            "limit": "50",
        }
        page = await recovery_fetch_resource(
            self.worker.gateway,
            seller_id=head.seller_id,
            path="/orders/search?" + urlencode(params),
        )
        observed_at = self.worker.queue.now()
        if not isinstance(page, dict) or not isinstance(page.get("paging"), dict):
            raise ValueError("order page lacks pagination")
        total, rows = page["paging"].get("total"), page.get("results")
        if type(total) is not int or total < 0:
            raise ValueError("invalid order total")
        if len(BSON.encode(page)) > 4 * 1024 * 1024:
            raise HistoryLimitError("creation interval needs a bounded enumeration strategy")
        expected_total = active["source_total"] if active else head.source_total
        if expected_total is not None and total != expected_total:
            raise OrderEnumerationDriftError("order total changed")
        if not isinstance(rows, list) or len(rows) > 50 or offset + len(rows) > total:
            raise ValueError("invalid order page length")
        if total > self.ranges.result_budget:
            operation = self.ranges.split if active else self.ranges.start
            return await operation(job, head, observed_total=total, observed_at=observed_at)
        if not rows and offset != total:
            raise OrderEnumerationDriftError("order enumeration ended before its observed total")
        receipts = []
        identities: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("order search row is not an object")
            identity = str(row.get("id"))
            if not identity.isascii() or not identity.isdecimal():
                raise ValueError("invalid order identity")
            if identity in identities:
                raise OrderEnumerationDriftError("order page repeats an identity")
            identities.add(identity)
            created = _date(row.get("date_created"))
            seller = row.get("seller")
            owners = (row.get("seller_id"), seller.get("id") if isinstance(seller, dict) else None)
            if any(owner is not None and str(owner) != head.seller_id for owner in owners):
                raise ValueError("order search seller mismatch")
            if not start_hour <= created < last_hour + timedelta(hours=1):
                raise ValueError("order lies outside queried creation hours")
            inside = bounds.date_from <= created < bounds.date_to
            receipts.append(
                self._receipt(
                    head,
                    identity,
                    "membership" if inside else "exclusion",
                    source_hash=item_source_fingerprint(row),
                    source_payload=row,
                    observed_at=observed_at,
                    source_version=_version(row),
                    exclusion_reason=None if inside else "outside_requested_creation_interval",
                )
            )
        scope = {
            "acquisition_id": head.id,
            "generation": head.generation,
            "pass_number": head.pass_number,
        }
        if identities and await self.continuation.store.receipts.find_one(
            {
                **scope,
                "resource_id": {"$in": list(identities)},
                "kind": {"$in": ["membership", "exclusion"]},
            }
        ):
            raise OrderEnumerationDriftError("shifted page repeats an acquired identity")
        next_offset = offset + len(rows)
        verifying = head.phase == "verify"
        if active:

            async def verify_manifest(session: Any, final: bool) -> None:
                await self._compare_manifest(head, receipts, final=final, session=session)

            return await self.ranges.page(
                job,
                head,
                source_total=total,
                next_offset=next_offset,
                receipts=receipts,
                observed_at=observed_at,
                verify_manifest=verify_manifest if verifying else None,
            )
        if verifying:
            await self._compare_manifest(head, receipts, final=next_offset == total)
        return await self._save(
            job,
            head,
            receipts,
            source_total=total,
            observed_from=head.observed_from or observed_at,
            observed_until=observed_at,
            discovered_count=head.discovered_count
            + sum(receipt.kind == "membership" for receipt in receipts),
            next_cursor=None if next_offset == total else next_offset,
            phase="verify" if verifying else "hydrate" if next_offset == total else "discover",
        )

    async def _compare_manifest(
        self,
        head: SheetsHistoryAcquisition,
        receipts: list[SheetsHistoryReceipt],
        *,
        final: bool,
        session: Any = None,
    ) -> None:
        baseline = {
            "acquisition_id": head.id,
            "generation": head.generation,
            "pass_number": head.pass_number - 1,
            "kind": {"$in": ["membership", "exclusion"]},
        }
        collection = self.continuation.store.receipts
        for receipt in receipts:
            original = await collection.find_one(
                {**baseline, "resource_id": receipt.resource_id}, session=session
            )
            if original is None or any(
                original.get(field) != getattr(receipt, field)
                for field in ("kind", "source_version", "source_hash", "exclusion_reason")
            ):
                raise OrderEnumerationDriftError("verification manifest identity or source changed")
        if final:
            missing = await collection.aggregate(
                [
                    {
                        "$match": {
                            **baseline,
                            "resource_id": {"$nin": [receipt.resource_id for receipt in receipts]},
                        }
                    },
                    {
                        "$lookup": {
                            "from": "sheets_history_receipts",
                            "let": {"identity": "$resource_id", "kind": "$kind"},
                            "pipeline": [
                                {
                                    "$match": {
                                        "acquisition_id": head.id,
                                        "generation": head.generation,
                                        "pass_number": head.pass_number,
                                        "$expr": {
                                            "$and": [
                                                {"$eq": ["$resource_id", "$$identity"]},
                                                {"$eq": ["$kind", "$$kind"]},
                                            ]
                                        },
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
            if missing:
                raise OrderEnumerationDriftError("verification manifest omits prior identities")

    async def _known_cancelled(
        self, job: dict[str, Any], head: SheetsHistoryAcquisition
    ) -> SheetsHistoryAcquisition:
        """Stage source-confirmed search omissions, never remove them from order history."""
        pending = await self.worker.db.orders.aggregate(
            [
                {
                    "$match": {
                        "seller_id": head.seller_id,
                        "date_created": {"$gte": head.date_from, "$lt": head.date_to},
                    }
                },
                {"$project": {"_id": 1}},
                {"$sort": {"_id": 1}},
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
            ]
        ).to_list(length=1)
        if not pending:
            raise HistoryHandoffPendingError("known identities exhausted; reconciliation remains")
        if head.discovered_count >= 10000:
            raise HistoryLimitError("known order inventory exceeds local acquisition budget")
        identity = str(pending[0]["_id"])
        if not identity.isascii() or not identity.isdecimal():
            raise ValueError("known order identity is invalid")
        observation = await self.worker._order_detail_with_source(
            head.seller_id, identity, head.date_from, head.date_to
        )
        status = observation.source_payload.get("status")
        if not isinstance(status, str) or not status:
            raise ValueError("known order lacks current source status")
        if status != "cancelled":
            raise OrderEnumerationDriftError("non-cancelled known order is missing from search")
        evidence = {
            "source_payload": observation.source_payload,
            "source_hash": item_source_fingerprint(observation.source_payload),
            "source_version": _version(observation.source_payload),
            "observed_at": observation.observed_at,
        }
        receipts = [
            self._receipt(head, identity, "membership", **evidence),
            self._receipt(
                head,
                identity,
                "detail",
                **evidence,
                payload=observation.resource,
                payload_hash=item_source_fingerprint(observation.resource),
                unavailable_fields=sorted(observation.unavailable_fields),
            ),
            self._receipt(
                head,
                identity,
                "exclusion",
                **evidence,
                exclusion_reason="seller_search_omits_source_confirmed_cancelled_order",
            ),
        ]
        return await self._save(
            job,
            head,
            receipts,
            discovered_count=head.discovered_count + 1,
            fetched_count=head.fetched_count + 1,
        )

    async def _hydrate(
        self,
        job: dict[str, Any],
        head: SheetsHistoryAcquisition,
    ) -> SheetsHistoryAcquisition:
        scope = {
            "acquisition_id": head.id,
            "generation": head.generation,
            "pass_number": head.pass_number,
        }
        pending = await self.continuation.store.receipts.aggregate(
            [
                {"$match": {**scope, "kind": "membership"}},
                {"$sort": {"resource_id": 1}},
                {
                    "$lookup": {
                        "from": "sheets_history_receipts",
                        "let": {"identity": "$resource_id"},
                        "pipeline": [
                            {
                                "$match": {
                                    **scope,
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
            ]
        ).to_list(length=1)
        if not pending:
            return await self.continuation.begin_verification(job, head)
        membership = pending[0]
        observation = await self.worker._order_detail_with_source(
            head.seller_id,
            membership["resource_id"],
            head.date_from,
            head.date_to,
            search_row=membership.get("source_payload"),
        )
        detail, missing = observation.resource, observation.unavailable_fields
        version = _version(detail)
        if (
            version is not None
            and membership["source_version"] is not None
            and version != membership["source_version"]
        ):
            raise OrderEnumerationDriftError("order changed between search and detail")
        receipt = self._receipt(
            head,
            membership["resource_id"],
            "detail",
            payload=detail,
            payload_hash=item_source_fingerprint(detail),
            source_payload=observation.source_payload,
            source_hash=item_source_fingerprint(observation.source_payload),
            observed_at=observation.observed_at,
            source_version=version,
            unavailable_fields=sorted(missing),
        )
        return await self._save(job, head, [receipt], fetched_count=head.fetched_count + 1)
