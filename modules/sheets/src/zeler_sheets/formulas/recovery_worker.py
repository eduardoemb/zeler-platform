"""Execute persisted formula recovery outside the HTTP calculation path."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from pymongo.errors import PyMongoError

from zeler_platform_core.clients.meli_gateway_client import GatewayRateLimitError
from zeler_platform_core.devoluciones_readiness import (
    DevolucionesLeaseConflictError,
    DevolucionesLeaseLostError,
    DevolucionesOperationContext,
    acquire_devoluciones_operation,
    finish_devoluciones_operation,
    operation_lease_guard,
)
from zeler_sheets.event_persistence import SheetsEventPersistence
from zeler_sheets.formulas.read_models import read_model_reconciliation_marker_covers
from zeler_sheets.formulas.recovery import COOLDOWN, FormulaRecoveryQueue, OrderIdsRecoveryRequest


class FormulaRecoveryWorker:
    def __init__(
        self,
        *,
        db: Any,
        gateway: Any,
        queue: FormulaRecoveryQueue,
        detail_gateway: Any | None = None,
    ) -> None:
        self.db = db
        self.gateway = gateway
        self.detail_gateway = detail_gateway if detail_gateway is not None else gateway
        self.queue = queue

    async def process_once(self) -> str:
        return "processed" if await self.process_one() else "idle"

    async def process_one(self) -> bool:
        job = await self.queue.claim()
        if job is None:
            return False
        try:
            async with asyncio.timeout(240):
                if job["read_model"] == "questions":
                    await self._questions(job)
                elif job["read_model"] == "orders":
                    if "order_ids" in job:
                        job = await self._locate_orders(job)
                    await self._orders(job)
                else:
                    raise ValueError("recovery source not implemented")
        except httpx.HTTPStatusError as exc:
            transient = exc.response.status_code == 429 or exc.response.status_code >= 500
            await self.queue.finish(
                job,
                succeeded=False,
                retryable=transient,
                failure_reason="source_temporarily_unavailable" if transient else "source_rejected",
            )
        except (httpx.TransportError, TimeoutError, GatewayRateLimitError):
            await self.queue.finish(
                job,
                succeeded=False,
                retryable=True,
                failure_reason="source_temporarily_unavailable",
            )
        except (PyMongoError, DevolucionesLeaseConflictError, DevolucionesLeaseLostError):
            await self.queue.finish(
                job,
                succeeded=False,
                retryable=True,
                failure_reason="storage_unavailable",
            )
        except ValueError:
            await self.queue.finish(job, succeeded=False, failure_reason="source_incomplete")
        except Exception:  # noqa: BLE001 - never log upstream payloads or credentials.
            await self.queue.finish(job, succeeded=False)
        return True

    async def _locate_orders(self, job: dict[str, Any]) -> dict[str, Any]:
        requested = OrderIdsRecoveryRequest(job["seller_id"], tuple(job["order_ids"]))
        dates: list[datetime] = []
        for identity in requested.order_ids:
            response = await self.detail_gateway.request(
                method="GET", seller_id=requested.seller_id, path=f"/orders/{identity}"
            )
            if response.status_code not in {200, 206}:
                raise ValueError("order location unavailable")
            detail = response.json()
            seller = detail.get("seller") if isinstance(detail, dict) else None
            owners = (
                detail.get("seller_id") if isinstance(detail, dict) else None,
                seller.get("id") if isinstance(seller, dict) else None,
            )
            seller_unavailable = response.status_code == 206 and "seller" in {
                field.strip().lower()
                for field in response.headers.get("X-Content-Missing", "").split(",")
            }
            if (
                not isinstance(detail, dict)
                or str(detail.get("id")) != identity
                or (not any(owner is not None for owner in owners) and not seller_unavailable)
                or any(owner is not None and str(owner) != requested.seller_id for owner in owners)
            ):
                raise ValueError("order location scope mismatch")
            dates.append(_date(detail.get("date_created")))
        # Discovery is not coverage evidence: the existing search/detail pipeline
        # must still reconcile the inventory and include every requested identity.
        return {
            **job,
            "date_from": min(dates),
            "date_to": max(dates) + timedelta(milliseconds=1),
        }

    async def _coverage(
        self, job: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, datetime, datetime]:
        seller_id = job["seller_id"]
        marker_id = f"{seller_id}:{job['read_model']}"
        marker_before = await self.db["sheets_read_model_freshness"].find_one(
            {"_id": marker_id, "seller_id": seller_id},
        )
        start = _utc(job["date_from"])
        end = _utc(job["date_to"])
        if marker_before is not None:
            prior_start = marker_before.get("date_from")
            prior_end = marker_before.get("reconciled_until")
            if read_model_reconciliation_marker_covers(
                marker_before, date_from=prior_start, date_to=prior_end
            ):
                # Reacquire the whole union (including any gap), rather than
                # erase earlier coverage or extend proof without source data.
                start = min(
                    start,
                    _utc(prior_start) if isinstance(prior_start, datetime) else _date(prior_start),
                )
                end = max(
                    end, _utc(prior_end) if isinstance(prior_end, datetime) else _date(prior_end)
                )
        return marker_before, start, end

    async def _orders(self, job: dict[str, Any]) -> None:
        seller_id = job["seller_id"]
        marker_before, start, end = await self._coverage(job)
        resources: list[dict[str, Any]] = []
        unavailable_fields: dict[str, frozenset[str]] = {}
        seen: set[str] = set()
        total: int | None = None
        while True:
            params = {
                "seller": seller_id,
                "order.date_created.from": start.isoformat(timespec="milliseconds"),
                "order.date_created.to": (end - timedelta(milliseconds=1)).isoformat(
                    timespec="milliseconds"
                ),
                "sort": "date_asc",
                "offset": str(len(seen)),
                "limit": "50",
            }
            page = await self.gateway.fetch_resource(
                seller_id=seller_id, path="/orders/search?" + urlencode(params)
            )
            paging = page.get("paging") if isinstance(page, dict) else None
            count = paging.get("total") if isinstance(paging, dict) else None
            if type(count) is not int or not 0 <= count <= 10000:
                raise ValueError("order search total unavailable or over budget")
            if total is not None and count != total:
                raise ValueError("order search changed during recovery")
            total = count
            rows = page.get("results")
            if not isinstance(rows, list):
                raise ValueError("order search missing results")
            for row in rows:
                identity = str(row.get("id")) if isinstance(row, dict) else ""
                if not identity.isdecimal() or identity in seen:
                    raise ValueError("duplicate or invalid order identity")
                seen.add(identity)
                created = _date(row.get("date_created"))
                if not start <= created < end:
                    raise ValueError("order search outside requested range")
                response = await self.detail_gateway.request(
                    method="GET", seller_id=seller_id, path=f"/orders/{identity}"
                )
                missing = frozenset(
                    field.strip().lower()
                    for field in response.headers.get("X-Content-Missing", "").split(",")
                    if field.strip()
                )
                if (
                    response.status_code not in {200, 206}
                    or (response.status_code == 206 and not missing)
                    or missing - {"buyer", "shipping", "seller", "feedback", "mediations"}
                ):
                    raise ValueError("order source partial fields are not supported")
                detail = response.json()
                seller = detail.get("seller") if isinstance(detail, dict) else None
                owners = (
                    detail.get("seller_id") if isinstance(detail, dict) else None,
                    seller.get("id") if isinstance(seller, dict) else None,
                )
                search_seller = row.get("seller")
                search_owners = (
                    row.get("seller_id"),
                    search_seller.get("id") if isinstance(search_seller, dict) else None,
                )
                if (
                    not isinstance(detail, dict)
                    or str(detail.get("id")) != identity
                    or _date(detail.get("date_created")) != created
                    or not (
                        any(owner is not None for owner in owners)
                        or (
                            "seller" in missing
                            and any(owner is not None for owner in search_owners)
                        )
                    )
                    or any(
                        owner is not None and str(owner) != seller_id
                        for owner in (*owners, *search_owners)
                    )
                    or not isinstance(detail.get("order_items"), list)
                    or not detail["order_items"]
                ):
                    raise ValueError("order detail scope or required data mismatch")
                resources.append(detail)
                unavailable_fields[identity] = missing
            if len(seen) == total:
                break
            if not rows or len(seen) > total:
                raise ValueError("incomplete order search")

        if not set(job.get("order_ids", ())).issubset(seen):
            raise ValueError("requested orders absent from authoritative inventory")
        operation = await acquire_devoluciones_operation(
            db=self.db,
            seller_id=seller_id,
            scope="devoluciones",
            operation_id=job["_id"],
            attempt_token=job["attempt_token"],
        )
        published = False
        try:
            await self._publish(
                job,
                marker_before,
                start,
                end,
                resources,
                operation=operation,
                unavailable_fields=unavailable_fields,
            )
            published = True
        finally:
            if not published:
                with suppress(DevolucionesLeaseLostError):
                    await finish_devoluciones_operation(
                        db=self.db, operation=operation, succeeded=False
                    )

    async def _questions(self, job: dict[str, Any]) -> None:
        seller_id = job["seller_id"]
        marker_before, start, end = await self._coverage(job)
        resources: list[dict[str, Any]] = []
        seen: set[str] = set()
        total: int | None = None
        scroll: str | None = None
        while True:
            params = {
                "seller_id": seller_id,
                "api_version": "4",
                "limit": "50",
                "search_type": "scan",
            }
            if scroll is not None:
                params["scroll_id"] = scroll
            page = await self.gateway.fetch_resource(
                seller_id=seller_id, path="/questions/search?" + urlencode(params)
            )
            if not isinstance(page, dict):
                raise ValueError("invalid question search")
            page_total = page.get("total")
            if type(page_total) is not int or not 0 <= page_total <= 10000:
                raise ValueError("question search total unavailable or over budget")
            if total is not None and page_total != total:
                raise ValueError("question search changed during recovery")
            total = page_total
            rows = page.get("questions")
            if not isinstance(rows, list):
                raise ValueError("question search missing results")
            for row in rows:
                if not isinstance(row, dict) or row.get("id") is None:
                    raise ValueError("question search missing identity")
                question_id = str(row["id"])
                if question_id in seen or not question_id.isdecimal():
                    raise ValueError("duplicate or invalid question identity")
                seen.add(question_id)
                created = _date(row.get("date_created"))
                if start <= created < end:
                    detail = await self.detail_gateway.fetch_resource(
                        seller_id=seller_id, path=f"/questions/{question_id}"
                    )
                    if (
                        not isinstance(detail, dict)
                        or str(detail.get("id")) != question_id
                        or str(detail.get("seller_id")) != seller_id
                        or _date(detail.get("date_created")) != created
                    ):
                        raise ValueError("question detail scope mismatch")
                    if detail.get("status") == "ANSWERED" and not isinstance(
                        detail.get("answer"), dict
                    ):
                        raise ValueError("question answer unavailable")
                    resources.append(detail)
            if len(seen) == total:
                break
            if not rows or len(seen) > total:
                raise ValueError("incomplete question search")
            scroll = page.get("scroll_id")
            if not isinstance(scroll, str) or not scroll:
                raise ValueError("question continuation unavailable")

        await self._publish(job, marker_before, start, end, resources)

    async def _publish(
        self,
        job: dict[str, Any],
        marker_before: dict[str, Any] | None,
        start: datetime,
        end: datetime,
        resources: list[dict[str, Any]],
        *,
        operation: DevolucionesOperationContext | None = None,
        unavailable_fields: dict[str, frozenset[str]] | None = None,
    ) -> None:
        seller_id = job["seller_id"]
        read_model = job["read_model"]
        marker_id = f"{seller_id}:{read_model}"
        unavailable_fields = unavailable_fields or {}
        marker = {
            "_id": marker_id,
            "seller_id": seller_id,
            "read_model": read_model,
            "state": "reconciled",
            "date_from": start,
            "reconciled_until": end,
            "fresh_until": end,
            "updated_at": self.queue.now(),
            "valid_until": self.queue.now() + timedelta(minutes=15),
            "source": "zelerdata_read_model_reconcile",
            "schema_version": 1,
        }
        # Source acquisition happens outside Mongo transactions. Publish all
        # normalized rows, coverage and completion atomically for the live owner.
        async with (
            await self.db.client.start_session() as session,
            session.start_transaction(),
        ):
            now = self.queue.now()
            current_marker = await self.db["sheets_read_model_freshness"].find_one(
                {"_id": marker_id, "seller_id": seller_id},
                session=session,
            )
            if current_marker != marker_before:
                raise ValueError("coverage changed during source acquisition")
            finished = await self.queue.collection.update_one(
                self.queue._owned(job, now),
                {
                    "$set": {
                        "state": "completed",
                        "updated_at": now,
                        "available_at": now + COOLDOWN,
                    },
                    "$unset": {"attempt_token": "", "lease_until": "", "failure_reason": ""},
                },
                session=session,
            )
            if finished.matched_count != 1:
                raise ValueError("recovery lease lost before publication")
            writer = SheetsEventPersistence(db=self.db, clock=self.queue.now)
            for resource in resources:
                await writer.persist(
                    event_type=f"{read_model}.updated",
                    seller_id=seller_id,
                    resource=resource,
                    session=session,
                    operation=operation,
                    unavailable_fields=unavailable_fields.get(str(resource["id"]), frozenset()),
                )
            persisted = (
                await self.db[read_model]
                .find(
                    {"seller_id": seller_id, "date_created": {"$gte": start, "$lt": end}},
                    {
                        "_id": 1,
                        "buyer_id": 1,
                        "items": 1,
                        "shipment_id": 1,
                        "tags": 1,
                        "unavailable_fields": 1,
                    },
                    session=session,
                )
                .to_list(length=None)
            )
            if {str(row["_id"]) for row in persisted} != {str(row["id"]) for row in resources}:
                raise ValueError("persisted inventory differs from authoritative source")
            if read_model == "orders" and any(
                (not row.get("buyer_id") and "buyer_id" not in row.get("unavailable_fields", []))
                or not row.get("items")
                or (
                    "shipping" in unavailable_fields.get(str(row["_id"]), frozenset())
                    and not row.get("shipment_id")
                    and "no_shipping" not in (row.get("tags") or [])
                    and "shipment_id" not in row.get("unavailable_fields", [])
                )
                for row in persisted
            ):
                raise ValueError("persisted order required data unavailable")
            await self.db["sheets_read_model_freshness"].replace_one(
                {"_id": marker_id, "seller_id": seller_id},
                marker,
                upsert=True,
                session=session,
            )
            if operation is not None:
                released = await self.db["sheets_devoluciones_operations"].update_one(
                    operation_lease_guard(operation),
                    {
                        "$set": {"state": "succeeded", "error_code": None},
                        "$currentDate": {"finished_at": True, "lease_until": True},
                    },
                    session=session,
                )
                if released.matched_count != 1:
                    raise DevolucionesLeaseLostError("order publication lost its operation lease")


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _date(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("question date unavailable")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("question date timezone unavailable")
    parsed = parsed.astimezone(UTC)
    # Search can include microseconds omitted by detail responses. Compare at
    # BSON's millisecond precision, also used by persisted request boundaries.
    return parsed - timedelta(microseconds=parsed.microsecond % 1000)
