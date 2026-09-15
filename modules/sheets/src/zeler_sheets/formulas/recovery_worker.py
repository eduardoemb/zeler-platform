"""Execute persisted formula recovery outside the HTTP calculation path."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from bson import BSON
from pymongo.errors import DuplicateKeyError, PyMongoError

from zeler_platform_core.clients.meli_gateway_client import GatewayRateLimitError
from zeler_platform_core.devoluciones_readiness import (
    DevolucionesLeaseConflictError,
    DevolucionesLeaseLostError,
    DevolucionesOperationContext,
    acquire_devoluciones_operation,
    finish_devoluciones_operation,
    operation_lease_guard,
)
from zeler_platform_core.models.entities import ShipmentRealShippingCostProjection
from zeler_sheets.catalog_observations import record_catalog_observation
from zeler_sheets.event_persistence import (
    SheetsEventPersistence,
    _canonical_shipment_document,
    _receiver_address_snapshot,
    _shipment_id,
)
from zeler_sheets.formulas.dispatcher import FormulaDataUnavailableError
from zeler_sheets.formulas.pacing import (
    LocalQuotaTimeoutError,
    recovery_fetch_resource,
    recovery_quota_deadline,
    recovery_request,
)
from zeler_sheets.formulas.pricing import acquired_current_price
from zeler_sheets.formulas.read_models import (
    FormulaReadModelRepository,
    read_model_reconciliation_marker_covers,
)
from zeler_sheets.formulas.recovery import (
    COOLDOWN,
    CatalogProductIdsRecoveryRequest,
    CatalogRecoveryRequest,
    FormulaRecoveryQueue,
    ItemIdsRecoveryRequest,
    OrderIdsRecoveryRequest,
    ShipmentIdsRecoveryRequest,
)
from zeler_sheets.formulas.refresh import merge_interval_proofs, reconciled_marker
from zeler_sheets.historical_meli_backfill import (
    _catalog_buybox_snapshot,
    _catalog_product_snapshot,
    _catalog_snapshot_source_rows_from_resources,
)
from zeler_sheets.sheetseller_backfill import (
    ItemDetailEnrichmentSummary,
    RetryableItemAcquisitionError,
    _discover_current_item_ids,
    run_item_detail_enrichment,
    run_sheetseller_backfill,
)


def _catalog_offer_count(resource: Any, *, item_id: str, seller_id: str) -> tuple[int, bool]:
    if not isinstance(resource, dict):
        raise ValueError("catalog offer listing is unavailable")
    paging, rows = resource.get("paging"), resource.get("results")
    if not isinstance(paging, dict) or not isinstance(rows, list):
        raise ValueError("catalog offer paging is unavailable")
    total, offset, limit = paging.get("total"), paging.get("offset"), paging.get("limit")
    if (
        type(total) is not int
        or type(offset) is not int
        or type(limit) is not int
        or total < 0
        or offset != 0
        or limit <= 0
        or len(rows) != min(total, limit)
    ):
        raise ValueError("catalog offer paging is inconsistent")
    identities = []
    for row in rows:
        identity = row.get("item_id") if isinstance(row, dict) else None
        if not isinstance(identity, str) or re.fullmatch(r"ML[A-Z][0-9]+", identity) is None:
            raise ValueError("catalog offer identity is unavailable")
        if identity == item_id and str(row.get("seller_id")) != seller_id:
            raise ValueError("catalog offer ownership is inconsistent")
        identities.append(identity)
    if len(set(identities)) != len(identities):
        raise ValueError("catalog offer identities are duplicated")
    return total, total == 1 and identities == [item_id]


def _catalog_snapshot_filter(seller_id: str, identity: str, observed: datetime) -> dict[str, Any]:
    return {
        "_id": f"{seller_id}:{identity}",
        "seller_id": seller_id,
        "$and": [
            {"$or": [{field: {"$lte": observed}}, {field: {"$exists": False}}]}
            for field in ("snapshot_at", "source_unavailable.observed_at")
        ],
    }


def _catalog_chunk(job: dict[str, Any], field: str) -> tuple[str, ...]:
    ids = tuple(job[field])
    if "catalog_offset" not in job:
        return ids
    intent = CatalogRecoveryRequest(job["seller_id"], job["read_model"], ids)
    offset = job["catalog_offset"]
    if ids != intent.ids or type(offset) is not int or not 0 <= offset < len(ids) or offset % 20:
        raise ValueError("invalid catalog continuation")
    return ids[offset : offset + 20]


def _order_missing_fields(response: httpx.Response) -> frozenset[str]:
    header = response.headers.get("X-Content-Missing", "").strip().lower()
    # Mercado Libre also emits a bracketed, non-JSON list such as [buyer].
    if header.startswith("[") and header.endswith("]"):
        header = header[1:-1].strip()
    if not header:
        return frozenset()
    if re.fullmatch(r"[a-z_]+(?:\s*,\s*[a-z_]+)*", header) is None:
        raise ValueError("order source partial fields are not supported")
    missing = frozenset(field.strip() for field in header.split(","))
    if missing - {"buyer", "shipping", "seller", "feedback", "mediations"}:
        raise ValueError("order source partial fields are not supported")
    return missing


@dataclass(frozen=True)
class OrderDetailObservation:
    resource: dict[str, Any]
    unavailable_fields: frozenset[str]
    source_payload: dict[str, Any]
    observed_at: datetime


class FormulaRecoveryWorker:
    def __init__(
        self,
        *,
        db: Any,
        gateway: Any,
        queue: FormulaRecoveryQueue,
        detail_gateway: Any | None = None,
        lane: str | None = None,
    ) -> None:
        self.lane = lane
        self.db = db
        self.gateway = gateway
        self.detail_gateway = detail_gateway if detail_gateway is not None else gateway
        self.queue = queue

    async def process_once(self) -> str:
        return "processed" if await self.process_one() else "idle"

    async def process_one(self) -> bool:
        job = await self.queue.claim(lane=self.lane) if self.lane else await self.queue.claim()
        if job is None:
            return False
        try:
            with recovery_quota_deadline(asyncio.get_running_loop().time() + 239) as quota:
                async with asyncio.timeout(240):
                    if job["read_model"] == "questions":
                        await self._questions(job)
                    elif job["read_model"] == "orders":
                        if "order_ids" in job:
                            job = await self._locate_orders(job)
                        await self._orders(job)
                    elif job["read_model"] == "shipments":
                        await self._shipments(job)
                    elif job["read_model"] == "item_formula_rows":
                        await self._items(job)
                    elif job["read_model"] == "catalog_product_snapshots":
                        await self._catalog_products(job)
                    elif job["read_model"] == "catalog_buybox_snapshots":
                        await self._catalog_buybox(job)
                    else:
                        raise ValueError("recovery source not implemented")
        except LocalQuotaTimeoutError:
            await self.queue.defer_quota(job)
        except httpx.HTTPStatusError as exc:
            transient = exc.response.status_code == 429 or exc.response.status_code >= 500
            await self.queue.finish(
                job,
                succeeded=False,
                retryable=transient,
                failure_reason="source_temporarily_unavailable" if transient else "source_rejected",
            )
        except (
            httpx.TransportError,
            TimeoutError,
            GatewayRateLimitError,
            RetryableItemAcquisitionError,
        ) as exc:
            # A quota-expired child can still be joining a sibling when the
            # outer deadline cancels the wave. Preserve the known local cause.
            if isinstance(exc, TimeoutError) and quota.expired:
                await self.queue.defer_quota(job)
            else:
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

    async def _catalog_products(self, job: dict[str, Any]) -> None:
        requested = CatalogProductIdsRecoveryRequest(
            job["seller_id"], _catalog_chunk(job, "catalog_product_ids")
        )
        ids = list(requested.catalog_product_ids)
        sources = (
            await self.db["items"]
            .find(
                {
                    "seller_id": requested.seller_id,
                    "$or": [
                        {"catalog_product_id": {"$in": ids}},
                        {"variations.catalog_product_id": {"$in": ids}},
                    ],
                },
                {"_id": 1, "catalog_product_id": 1, "variations.catalog_product_id": 1},
            )
            .to_list(length=None)
        )
        associated = {
            identity
            for source in _catalog_snapshot_source_rows_from_resources(sources)
            for identity in (source.catalog_product_id, *source.variation_catalog_product_ids)
            if identity is not None
        }
        if not set(ids) <= associated:
            raise ValueError("requested catalog products are not associated with this seller")

        async def acquire(identity: str) -> Exception | None:
            observed = self.queue.now()
            if await self.queue.collection.find_one(self.queue._owned(job, observed)) is None:
                raise ValueError("catalog recovery lease lost")
            try:
                resource = await recovery_fetch_resource(
                    self.detail_gateway,
                    request_timeout=10,
                    seller_id=requested.seller_id,
                    path=f"/products/{identity}",
                )
                snapshot = _catalog_product_snapshot(resource, seller_id=requested.seller_id)
                if (
                    snapshot is None
                    or snapshot["catalog_product_id"] != identity
                    or not snapshot["title"]
                    or not isinstance(resource.get("title") or resource.get("name"), str)
                ):
                    raise ValueError("catalog product identity or title is unavailable")
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    await self._catalog_product_not_found(job, identity, observed)
                    return None
                return exc
            except (httpx.HTTPError, TimeoutError, GatewayRateLimitError, ValueError) as exc:
                return exc
            if (
                await self.queue.collection.find_one(self.queue._owned(job, self.queue.now()))
                is None
            ):
                raise ValueError("catalog recovery lease lost before persistence")
            snapshot["snapshot_at"] = observed
            snapshot["source"] = "sheets_backfill"
            # Overlapping batches may finish out of order. Never replace a
            # newer observation; a duplicate ID then means it already won.
            with suppress(DuplicateKeyError):
                await self.db["sheets_catalog_product_snapshots"].replace_one(
                    _catalog_snapshot_filter(requested.seller_id, identity, observed),
                    snapshot,
                    upsert=True,
                )
            return None

        await self._finish_catalog_batch(job, ids, acquire)

    async def _catalog_buybox(self, job: dict[str, Any]) -> None:
        requested = ItemIdsRecoveryRequest(
            job["seller_id"],
            _catalog_chunk(job, "item_ids"),
            read_model="catalog_buybox_snapshots",
        )
        items = await self.db.items.find(
            {"seller_id": requested.seller_id, "_id": {"$in": list(requested.item_ids)}}
        ).to_list(20)
        by_id = {item["_id"]: item for item in items}
        if set(by_id) != set(requested.item_ids):
            raise ValueError("buybox publications must belong to the requested seller")

        async def acquire(
            identity: str,
            *,
            enriched: bool = False,
            dependency_failure: Exception | None = None,
        ) -> Exception | None:
            item = by_id[identity]
            synced = item.get("last_meli_sync_at")
            if isinstance(synced, datetime):
                synced = (
                    synced.replace(tzinfo=UTC) if synced.tzinfo is None else synced.astimezone(UTC)
                )
            now = self.queue.now()
            if not isinstance(synced, datetime) or not now - COOLDOWN < synced <= now:
                if enriched:
                    raise RetryableItemAcquisitionError("buybox publication remains unacquired")
                # Resolve stale participation under this lease without preventing
                # independent, already verified siblings from being persisted.
                partial = await self._acquire_item_batch(
                    job, ItemIdsRecoveryRequest(requested.seller_id, (identity,))
                )
                refreshed = await self.db.items.find_one(
                    {"_id": identity, "seller_id": requested.seller_id}
                )
                if refreshed is None:
                    raise ValueError("buybox publication ownership changed during acquisition")
                by_id[identity] = refreshed
                return await acquire(
                    identity,
                    enriched=True,
                    dependency_failure=RetryableItemAcquisitionError(
                        "buybox publication dependency incomplete"
                    )
                    if partial
                    else None,
                )
            if item.get("catalog_listing") is not True:
                raise ValueError("buybox requires fresh explicit catalog participation")
            source = _catalog_snapshot_source_rows_from_resources([item])[0]
            if (
                not source.catalog_product_id
                or not source.title
                or source.available_quantity is None
            ):
                raise ValueError("buybox publication purpose fields are unavailable")
            observed = self.queue.now()
            if await self.queue.collection.find_one(self.queue._owned(job, observed)) is None:
                raise ValueError("buybox recovery lease lost")
            resource = await recovery_fetch_resource(
                self.detail_gateway,
                request_timeout=10,
                seller_id=requested.seller_id,
                path=f"/items/{identity}/price_to_win?version=v2",
            )
            if (
                not isinstance(resource, dict)
                or resource.get("item_id") != identity
                or (
                    resource.get("catalog_product_id") is not None
                    and resource["catalog_product_id"] != source.catalog_product_id
                )
            ):
                raise ValueError("buybox response identity is unverified")
            # price_to_win may omit the product. The owned, fresh item supplies
            # it; the canonical item is rechecked before any snapshot is stored.
            snapshot = _catalog_buybox_snapshot(
                resource, seller_id=requested.seller_id, source=source
            )
            if (
                snapshot is None
                or not snapshot["buybox_status"]
                or "competitors_sharing_first_place" not in snapshot
            ):
                raise ValueError("buybox competition fields are unavailable")
            if snapshot.get("price") is None:
                snapshot["price"] = acquired_current_price(item)
                if snapshot["price"] is None and not enriched:
                    # Resolve the price dependency under this durable intent;
                    # independent item/catalog jobs can run in either order.
                    try:
                        partial = await self._acquire_item_batch(
                            job, ItemIdsRecoveryRequest(requested.seller_id, (identity,))
                        )
                        if partial:
                            dependency_failure = RetryableItemAcquisitionError(
                                "buybox price dependency incomplete"
                            )
                    except (
                        httpx.HTTPError,
                        TimeoutError,
                        GatewayRateLimitError,
                        RetryableItemAcquisitionError,
                    ) as exc:
                        dependency_failure = exc
                    refreshed = await self.db.items.find_one(
                        {"_id": identity, "seller_id": requested.seller_id}
                    )
                    if refreshed is None or refreshed.get("catalog_listing") is not True:
                        raise ValueError("buybox participation changed during enrichment")
                    by_id[identity] = refreshed
                    # Acquire competition again against the new canonical cut.
                    return await acquire(
                        identity, enriched=True, dependency_failure=dependency_failure
                    )
                if snapshot["price"] is None:
                    dependency_failure = dependency_failure or ValueError(
                        "buybox current price remains unavailable"
                    )
            offer_failure = dependency_failure
            snapshot.update(competitor_count=None, only_competitor=None, offers_snapshot_at=None)
            offers: dict[str, Any] = {"results": []}
            try:
                offers = await recovery_fetch_resource(
                    self.detail_gateway,
                    request_timeout=10,
                    seller_id=requested.seller_id,
                    path=f"/products/{source.catalog_product_id}/items",
                )
                count, only = _catalog_offer_count(
                    offers, item_id=identity, seller_id=requested.seller_id
                )
                snapshot.update(
                    competitor_count=count, only_competitor=only, offers_snapshot_at=observed
                )
            except (httpx.HTTPError, TimeoutError, GatewayRateLimitError, ValueError) as exc:
                offer_failure = offer_failure or exc
                offers = {"results": []}
                prior = await self.db.sheets_catalog_buybox_snapshots.find_one(
                    {"_id": snapshot["_id"], "seller_id": requested.seller_id}
                )
                if prior and prior.get("catalog_product_id") == source.catalog_product_id:
                    # Preserve known offers with their own acquisition cut, never
                    # relabel them with the freshly acquired competition time.
                    snapshot.update(
                        competitor_count=prior.get("competitor_count"),
                        only_competitor=prior.get("only_competitor"),
                        offers_snapshot_at=prior.get("offers_snapshot_at", prior["snapshot_at"]),
                    )
            try:
                winner = resource.get("winner")
                if "winner" in resource and winner is None:
                    snapshot["winning_user_id"] = None
                elif isinstance(winner, dict):
                    winner_id = winner.get("item_id")
                    if isinstance(winner_id, str) and re.fullmatch(r"ML[A-Z][0-9]+", winner_id):
                        if winner_id == identity:
                            snapshot["winning_user_id"] = requested.seller_id
                        else:
                            matches = [
                                row for row in offers["results"] if row["item_id"] == winner_id
                            ]
                            if len(matches) == 1:
                                winner_seller = matches[0].get("seller_id")
                            else:
                                detail = await recovery_fetch_resource(
                                    self.detail_gateway,
                                    request_timeout=10,
                                    seller_id=requested.seller_id,
                                    path=f"/items/{winner_id}",
                                )
                                if (
                                    not isinstance(detail, dict)
                                    or detail.get("id") != winner_id
                                    or detail.get("catalog_product_id") != source.catalog_product_id
                                ):
                                    raise ValueError("winner publication identity is inconsistent")
                                winner_seller = detail.get("seller_id")
                            if (
                                not str(winner_seller).isascii()
                                or not str(winner_seller).isdecimal()
                            ):
                                raise ValueError("winner seller identity is unavailable")
                            snapshot["winning_user_id"] = str(winner_seller)
            except (httpx.HTTPError, TimeoutError, GatewayRateLimitError, ValueError) as exc:
                offer_failure = offer_failure or exc
            current = await self.db.items.find_one(
                {"_id": identity, "seller_id": requested.seller_id}
            )
            if current is None or BSON.encode(current) != BSON.encode(item):
                raise ValueError("buybox publication changed during acquisition")
            if (
                await self.queue.collection.find_one(self.queue._owned(job, self.queue.now()))
                is None
            ):
                raise ValueError("buybox recovery lease lost before persistence")
            snapshot.update(snapshot_at=observed, source="sheets_backfill")
            await record_catalog_observation(self.db, snapshot)
            with suppress(DuplicateKeyError):
                await self.db.sheets_catalog_buybox_snapshots.replace_one(
                    _catalog_snapshot_filter(requested.seller_id, identity, observed),
                    snapshot,
                    upsert=True,
                )
            return offer_failure

        await self._finish_catalog_batch(job, list(requested.item_ids), acquire)

    async def _finish_catalog_batch(
        self,
        job: dict[str, Any],
        ids: list[str],
        acquire: Callable[[str], Awaitable[Exception | None]],
    ) -> None:
        failures: list[Exception] = []

        async def guarded_acquire(identity: str) -> Exception | None:
            try:
                return await acquire(identity)
            except Exception as exc:  # noqa: BLE001 - preserve type after joining sibling writes.
                return exc

        # Join at most four independent acquisitions before admitting the next
        # wave or finishing the lease. Cancellation also drains started writes.
        for offset in range(0, len(ids), 4):
            async with asyncio.TaskGroup() as group:
                tasks = [
                    group.create_task(guarded_acquire(identity))
                    for identity in ids[offset : offset + 4]
                ]
            for task in tasks:
                failure = task.result()
                if failure is None:
                    continue
                if not isinstance(
                    failure,
                    (
                        httpx.HTTPError,
                        TimeoutError,
                        GatewayRateLimitError,
                        RetryableItemAcquisitionError,
                        ValueError,
                    ),
                ):
                    # Storage/implementation errors retain the outer worker's
                    # classification, rather than becoming an ExceptionGroup.
                    raise failure
                failures.append(failure)
        if failures:
            # Keep successfully acquired products even when a sibling failed.
            # The outer worker applies the existing bounded retry policy.
            transient = next(
                (
                    failure
                    for failure in failures
                    if isinstance(
                        failure,
                        (
                            httpx.TransportError,
                            TimeoutError,
                            GatewayRateLimitError,
                            RetryableItemAcquisitionError,
                        ),
                    )
                    or (
                        isinstance(failure, httpx.HTTPStatusError)
                        and (
                            failure.response.status_code == 429
                            or failure.response.status_code >= 500
                        )
                    )
                ),
                None,
            )
            raise transient or failures[0]
        await self.queue.finish(job, succeeded=True)

    async def _catalog_product_not_found(
        self, job: dict[str, Any], identity: str, observed: datetime
    ) -> None:
        if await self.queue.collection.find_one(self.queue._owned(job, self.queue.now())) is None:
            raise ValueError("catalog recovery lease lost before unavailable observation")
        with suppress(DuplicateKeyError):
            await self.db["sheets_catalog_product_snapshots"].update_one(
                _catalog_snapshot_filter(job["seller_id"], identity, observed),
                {
                    "$set": {
                        "source_unavailable": {
                            "reason": "catalog_product_not_found",
                            "observed_at": observed,
                        }
                    },
                    "$setOnInsert": {
                        "_id": f"{job['seller_id']}:{identity}",
                        "seller_id": job["seller_id"],
                        "catalog_product_id": identity,
                        "snapshot_at": observed,
                        "source": "sheets_backfill",
                        "schema_version": 1,
                    },
                },
                upsert=True,
            )

    async def _items(self, job: dict[str, Any]) -> None:
        if job.get("inventory_scope") is True:
            if "inventory_offset" not in job:
                identities = sorted(
                    await _discover_current_item_ids(self.gateway, seller_id=job["seller_id"])
                )
                await self.queue.checkpoint_inventory(job, item_ids=identities, offset=0)
                return
            identities = job["inventory_ids"]
            offset = job["inventory_offset"]
            requested = ItemIdsRecoveryRequest(
                job["seller_id"], tuple(identities[offset : offset + 20])
            )
        else:
            requested = ItemIdsRecoveryRequest(job["seller_id"], _catalog_chunk(job, "item_ids"))
        partial = await self._acquire_item_batch(job, requested)
        if not partial and job.get("inventory_scope") is True:
            await self.queue.checkpoint_inventory(
                job, item_ids=identities, offset=offset + len(requested.item_ids)
            )
            return
        await self.queue.finish(
            job, succeeded=not partial, retryable=partial, failure_reason="source_incomplete"
        )

    async def _acquire_item_batch(
        self, job: dict[str, Any], requested: ItemIdsRecoveryRequest
    ) -> bool:
        """Acquire and project one batch; return whether recovery remains incomplete."""
        if await self.queue.collection.find_one(self.queue._owned(job, self.queue.now())) is None:
            raise ValueError("item recovery lease lost before acquisition")

        async def acquire(ids: tuple[str, ...]) -> ItemDetailEnrichmentSummary | Exception:
            try:
                return await run_item_detail_enrichment(
                    db=self.db,
                    gateway=self.detail_gateway,
                    seller_id=requested.seller_id,
                    acquire_item_ids=ids,
                    dry_run=False,
                    sale_price_enabled=True,
                    listing_fixed_fee_enabled=True,
                    quality_enabled=True,
                    base_only=job.get("inventory_scope") is True,
                )
            except Exception as exc:  # noqa: BLE001 - preserve classification after joining siblings.
                return exc

        # At most four independent sub-batches. Join every write before
        # projecting/finishing, including when the outer lease task is cancelled.
        batch_size = 20 if job.get("inventory_scope") is True else 5
        async with asyncio.TaskGroup() as group:
            tasks = [
                group.create_task(acquire(requested.item_ids[offset : offset + batch_size]))
                for offset in range(0, len(requested.item_ids), batch_size)
            ]
        acquired = []
        acquisition_error: Exception | None = None
        for task in tasks:
            result = task.result()
            if isinstance(result, Exception):
                acquisition_error = acquisition_error or result
            else:
                acquired.append(result)
        if await self.queue.collection.find_one(self.queue._owned(job, self.queue.now())) is None:
            raise ValueError("item recovery lease lost before projection")
        stored = (
            await self.db["items"]
            .find(
                {"seller_id": requested.seller_id, "_id": {"$in": list(requested.item_ids)}},
                {"_id": 1},
            )
            .to_list(length=21)
        )
        stored_ids = tuple(sorted(str(item["_id"]) for item in stored))
        try:
            if stored_ids:
                persistence = SheetsEventPersistence(db=self.db)
                for item_id in stored_ids:
                    if (
                        await self.queue.collection.find_one(
                            self.queue._owned(job, self.queue.now())
                        )
                        is None
                    ):
                        raise ValueError("item recovery lease lost before history projection")
                    await persistence.project_acquired_item_history(
                        seller_id=requested.seller_id, item_id=item_id
                    )
                await run_sheetseller_backfill(
                    db=self.db,
                    seller_id=requested.seller_id,
                    item_ids=stored_ids,
                    dry_run=False,
                )
        except Exception as projection_error:
            if acquisition_error is not None:
                raise acquisition_error from projection_error
            raise
        if acquisition_error is not None:
            raise acquisition_error
        # A selected batch is not an inventory reconciliation. Preserve field
        # availability states and never publish a whole-seller freshness marker.
        partial = (
            any(result.item_details_stale_unavailable > 0 for result in acquired)
            or stored_ids != requested.item_ids
            or (
                job.get("inventory_scope") is not True
                and any(
                    count > 0 and ":transient:" in reason
                    for result in acquired
                    for reason, count in result.diagnostic_reason_counts.items()
                )
            )
        )
        if not partial:
            try:
                _, missing = await FormulaReadModelRepository(
                    db=self.db
                ).find_recent_item_formula_rows(
                    seller_id=requested.seller_id,
                    item_ids=list(requested.item_ids),
                    formula="ZELERDATA_CALCULADORA",
                    now=self.queue.now(),
                )
                partial = bool(missing)
            except FormulaDataUnavailableError:
                partial = True
        return partial

    async def _shipments(self, job: dict[str, Any]) -> None:
        requested = ShipmentIdsRecoveryRequest(job["seller_id"], tuple(job["shipment_ids"]))
        resources: list[dict[str, Any]] = []
        retry_partial = False
        for identity in requested.shipment_ids:
            relation_response = await self.detail_gateway.request(
                method="GET",
                seller_id=requested.seller_id,
                path=f"/shipments/{identity}/orders",
                headers={"X-New-Domain": "true"},
            )
            if relation_response.status_code != 200:
                raise ValueError("shipment order relationship unavailable")
            relations = relation_response.json()
            if not isinstance(relations, list) or not relations:
                raise ValueError("shipment order relationship unavailable")
            owned_orders = sorted(
                {
                    str(row.get("order_id"))
                    for row in relations
                    if isinstance(row, dict) and str(row.get("seller_id")) == requested.seller_id
                }
            )
            if not owned_orders or any(
                not identity.isascii() or not identity.isdecimal() for identity in owned_orders
            ):
                raise ValueError("shipment seller relationship unavailable")
            response = await self.detail_gateway.request(
                method="GET",
                seller_id=requested.seller_id,
                path=f"/shipments/{identity}",
                headers={"x-format-new": "true"},
            )
            if response.status_code != 200:
                raise ValueError("shipment detail incomplete")
            detail = response.json()
            if (
                not isinstance(detail, dict)
                or str(detail.get("id")) != identity
                or (
                    detail.get("seller_id") is not None
                    and str(detail["seller_id"]) != requested.seller_id
                )
                or (
                    detail.get("order_id") is not None
                    and str(detail["order_id"]) not in owned_orders
                )
            ):
                raise ValueError("shipment detail scope mismatch")
            observed_at = self.queue.now()
            cost = None
            try:
                cost_response = await self.detail_gateway.request(
                    method="GET",
                    seller_id=requested.seller_id,
                    path=f"/shipments/{identity}/costs",
                    headers={"x-format-new": "true"},
                )
                if cost_response.status_code == 200:
                    cost = ShipmentRealShippingCostProjection.from_meli_costs_payload(
                        cost_response.json(), seller_id=requested.seller_id, synced_at=observed_at
                    )
                elif cost_response.status_code == 429 or cost_response.status_code >= 500:
                    retry_partial = True
            except httpx.HTTPStatusError as exc:
                retry_partial |= exc.response.status_code == 429 or exc.response.status_code >= 500
            except (httpx.TransportError, TimeoutError, GatewayRateLimitError):
                retry_partial = True
            except ValueError:
                # Independently acquired address/status remain useful. Never
                # attach the upstream diagnostic or substitute another sender's cost.
                pass
            unavailable = []
            if cost is None:
                unavailable.append("real_shipping_cost")
            if _receiver_address_snapshot(detail) is None:
                unavailable.append("receiver_address")
            resources.append(
                {
                    **detail,
                    "order_id": owned_orders[0],
                    "real_shipping_cost": cost.model_dump(mode="python", exclude_none=True)
                    if cost
                    else None,
                    "formula_observed_at": observed_at,
                    "unavailable_fields": sorted(unavailable),
                }
            )
        # Explicit IDs do not prove a historical inventory. Publish only these
        # normalized documents and the live job's completion, not a range marker.
        async with (
            await self.db.client.start_session() as session,
            session.start_transaction(),
        ):
            if not await self.queue.finish(
                job,
                succeeded=not retry_partial,
                retryable=retry_partial,
                failure_reason="source_temporarily_unavailable",
                session=session,
            ):
                raise ValueError("shipment recovery lease lost before publication")
            writer = SheetsEventPersistence(db=self.db, clock=self.queue.now)
            for resource in resources:
                prior = await self.db["shipments"].find_one(
                    {"_id": str(resource["id"]), "seller_id": requested.seller_id}, session=session
                )
                for field in resource["unavailable_fields"]:
                    if prior and isinstance(prior.get(field), dict):
                        resource[field] = dict(prior[field])
                        if field == "receiver_address":
                            resource.pop("destination", None)
                        elif isinstance(resource[field].get("synced_at"), datetime):
                            # Default Mongo decoding omits tzinfo; do not change
                            # the cached observation time while normalizing it.
                            resource[field]["synced_at"] = _utc(resource[field]["synced_at"])
                await writer.persist(
                    event_type="shipments.updated",
                    seller_id=requested.seller_id,
                    resource=resource,
                    session=session,
                )
                stored = await self.db["shipments"].find_one(
                    {"_id": str(resource["id"]), "seller_id": requested.seller_id}, session=session
                )
                expected = _canonical_shipment_document(resource, seller_id=requested.seller_id)
                if stored is None or BSON.encode(stored).decode() != BSON.encode(expected).decode():
                    raise ValueError("shipment changed during acquisition")

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
            seller_unavailable = response.status_code == 206 and "seller" in _order_missing_fields(
                response
            )
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
        if marker_before is not None and job["read_model"] != "orders":
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
                # Meli search has hour precision. Fractional end-of-hour values
                # can include the next hour; exact row/detail checks stay below.
                "order.date_created.to": (end - timedelta(milliseconds=1))
                .replace(minute=0, second=0, microsecond=0)
                .isoformat(timespec="milliseconds"),
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
            details_to_fetch: list[tuple[str, dict[str, Any] | None]] = []
            for row in rows:
                identity = str(row.get("id")) if isinstance(row, dict) else ""
                if not identity.isdecimal() or identity in seen:
                    raise ValueError("duplicate or invalid order identity")
                seen.add(identity)
                created = _date(row.get("date_created"))
                if not start <= created < end:
                    raise ValueError("order search outside requested range")
                details_to_fetch.append((identity, row))
            for identity, detail, missing in await self._order_details(
                seller_id, details_to_fetch, start, end
            ):
                resources.append(detail)
                unavailable_fields[identity] = missing
            if len(seen) == total:
                break
            if not rows or len(seen) > total:
                raise ValueError("incomplete order search")

        # Seller search can omit legitimate cancelled orders. Revalidate known
        # identities by detail; local ownership alone is never source evidence.
        known = (
            await self.db.orders.find(
                {"seller_id": seller_id, "date_created": {"$gte": start, "$lt": end}},
                {"_id": 1},
            )
            .limit(10001)
            .to_list(length=None)
        )
        known_ids = {str(row["_id"]) for row in known}
        if len(known_ids | seen) > 10000:
            raise ValueError("known order inventory is over recovery budget")
        absent_ids = sorted(known_ids - seen)
        for identity in absent_ids:
            if not identity.isascii() or not identity.isdecimal():
                raise ValueError("known order identity is invalid")
        for identity, detail, missing in await self._order_details(
            seller_id, [(identity, None) for identity in absent_ids], start, end
        ):
            resources.append(detail)
            unavailable_fields[identity] = missing
            seen.add(identity)

        if not set(job.get("order_ids", ())).issubset(seen):
            raise ValueError("requested orders absent from authoritative inventory")
        operation = await acquire_devoluciones_operation(
            db=self.db,
            seller_id=seller_id,
            scope="devoluciones",
            operation_id=job["_id"],
            attempt_token=job["attempt_token"],
            # An orders re-acquisition rewrites order rows only. It must not
            # withdraw the settled DEVOLUCIONES readiness proof, because that
            # proof covers claims-derived returns the sweep never touches: doing
            # so left ZELERDATA_DEVOLUCIONES unavailable for most of every cycle.
            # Only a claims acquisition invalidates readiness, exactly as the
            # event handler does.
            invalidate_readiness=False,
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

    async def _order_details(
        self,
        seller_id: str,
        identities: list[tuple[str, dict[str, Any] | None]],
        start: datetime,
        end: datetime,
    ) -> list[tuple[str, dict[str, Any], frozenset[str]]]:
        async def acquire(
            identity: str, search_row: dict[str, Any] | None
        ) -> tuple[str, dict[str, Any], frozenset[str]] | Exception:
            try:
                detail, missing = await self._order_detail(
                    seller_id, identity, start, end, search_row=search_row
                )
                return identity, detail, missing
            except Exception as exc:  # noqa: BLE001 - rethrow original type after joining the wave
                return exc

        results = []
        for offset in range(0, len(identities), 4):
            # Join every in-flight request on failure/cancellation. Preserve the
            # original exception for process_one's retry classification.
            async with asyncio.TaskGroup() as group:
                tasks = [
                    group.create_task(acquire(identity, row))
                    for identity, row in identities[offset : offset + 4]
                ]
            for task in tasks:
                result = task.result()
                if isinstance(result, Exception):
                    raise result
                results.append(result)
        return results

    async def _order_detail(
        self,
        seller_id: str,
        identity: str,
        start: datetime,
        end: datetime,
        *,
        search_row: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], frozenset[str]]:
        observation = await self._order_detail_with_source(
            seller_id, identity, start, end, search_row=search_row
        )
        return observation.resource, observation.unavailable_fields

    async def _order_detail_with_source(
        self,
        seller_id: str,
        identity: str,
        start: datetime,
        end: datetime,
        *,
        search_row: dict[str, Any] | None = None,
    ) -> OrderDetailObservation:
        for attempt in range(3):
            try:
                response = await self.detail_gateway.request(
                    method="GET", seller_id=seller_id, path=f"/orders/{identity}"
                )
                break
            except GatewayRateLimitError as exc:
                delay = exc.response.headers.get("Retry-After", "").strip()
                if attempt == 2 or not delay.isascii() or not delay.isdecimal():
                    raise
                # Keep acquired pages while the gateway window resets. Use the
                # actual header, not the shared client's 30-second cap. The
                # enclosing 240-second job deadline and cancellation still apply.
                await asyncio.sleep(max(1, int(delay)))
        observed_at = self.queue.now()
        missing = _order_missing_fields(response)
        if response.status_code not in {200, 206} or (response.status_code == 206 and not missing):
            raise ValueError("order source partial fields are not supported")
        detail = response.json()
        if not isinstance(detail, dict):
            raise ValueError("order detail is not an object")
        seller = detail.get("seller")
        owners = (detail.get("seller_id"), seller.get("id") if isinstance(seller, dict) else None)
        row = search_row or {}
        search_seller = row.get("seller")
        search_owners = (
            row.get("seller_id"),
            search_seller.get("id") if isinstance(search_seller, dict) else None,
        )
        created = _date(detail.get("date_created"))
        if (
            str(detail.get("id")) != identity
            or not start <= created < end
            or (search_row is not None and created != _date(row.get("date_created")))
            or not (
                any(owner is not None for owner in owners)
                or ("seller" in missing and any(owner is not None for owner in search_owners))
            )
            or any(
                owner is not None and str(owner) != seller_id for owner in (*owners, *search_owners)
            )
            or not isinstance(detail.get("order_items"), list)
            or not detail["order_items"]
        ):
            raise ValueError("order detail scope or required data mismatch")
        source = deepcopy(detail)
        resource, unavailable = await self._recover_order_shipment(
            seller_id, identity, detail, missing
        )
        return OrderDetailObservation(resource, unavailable, source, observed_at)

    async def _recover_order_shipment(
        self, seller_id: str, identity: str, detail: dict[str, Any], missing: frozenset[str]
    ) -> tuple[dict[str, Any], frozenset[str]]:
        if _shipment_id(detail) or "no_shipping" in (detail.get("tags") or []):
            return detail, missing
        unavailable = missing | {"shipping"}
        try:
            response = await recovery_request(
                self.detail_gateway,
                request_timeout=5,
                method="GET",
                seller_id=seller_id,
                path=f"/orders/{identity}/shipments?hosted=true",
                headers={"X-New-Domain": "true"},
            )
            # 204 also represents delayed propagation, not proven absence.
            if response.status_code != 200:
                return detail, unavailable
            relations = response.json()
        except (httpx.HTTPError, GatewayRateLimitError, TimeoutError, ValueError):
            return detail, unavailable
        if not isinstance(relations, list) or not 1 <= len(relations) <= 100:
            return detail, unavailable
        forward: set[str] = set()
        for relation in relations:
            if not isinstance(relation, dict) or any(
                relation.get(field) is not None and str(relation[field]) != expected
                for field, expected in (("order_id", identity), ("seller_id", seller_id))
            ):
                return detail, unavailable
            if relation.get("type") == "forward":
                shipment_id = str(relation.get("id"))
                if not shipment_id.isascii() or not shipment_id.isdecimal():
                    return detail, unavailable
                forward.add(shipment_id)
        if len(forward) != 1:
            return detail, unavailable
        shipping = detail.get("shipping")
        recovered = {
            **detail,
            "shipping": {**(shipping if isinstance(shipping, dict) else {}), "id": forward.pop()},
        }
        return recovered, missing - {"shipping"}

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
        marker = reconciled_marker(
            seller_id=seller_id,
            read_model=read_model,
            start=start,
            end=end,
            now=self.queue.now(),
        )
        if (
            read_model == "orders"
            and marker_before is not None
            and marker_before.get("state") == "reconciled"
        ):
            # Retain every proven interval as durable history. Overlapping or
            # contiguous acquisitions merge into one proof; a real gap between
            # them is preserved so it is never presented as covered. Proofs the
            # new marker already covers need no separate record.
            previous = {
                key: value for key, value in marker_before.items() if key != "retained_intervals"
            }
            candidates = [
                proof
                for proof in [previous, *marker_before.get("retained_intervals", [])]
                if not read_model_reconciliation_marker_covers(
                    marker,
                    date_from=proof.get("date_from"),
                    date_to=proof.get("reconciled_until"),
                )
            ]
            marker["retained_intervals"] = merge_interval_proofs(candidates)
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
