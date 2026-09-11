from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, DecimalException
from typing import Any, cast

from zeler_sheets.devoluciones_reconciliation import (
    read_devoluciones_claims_keyset,
    read_devoluciones_orders_by_id_keyset,
)
from zeler_sheets.formulas.dispatcher import FormulaDataUnavailableError
from zeler_sheets.formulas.pricing import acquired_current_price
from zeler_sheets.formulas.recovery import ItemInventoryRecoveryRequest
from zeler_sheets.formulas.refresh import MARKER_VALIDITY
from zeler_sheets.formulas.schemas import FormulaContract
from zeler_sheets.item_projection import item_source_fingerprint
from zeler_sheets.unit_costs import UnitCostLookup, resolve_unit_cost

ITEM_FORMULA_ROWS_COLLECTION = "sheets_item_formula_rows"
ITEM_SKU_INDEX_COLLECTION = "sheets_item_sku_index"
CATALOG_BUYBOX_SNAPSHOTS_COLLECTION = "sheets_catalog_buybox_snapshots"
CATALOG_PRODUCT_SNAPSHOTS_COLLECTION = "sheets_catalog_product_snapshots"
CATALOG_TIME_METRICS_COLLECTION = "sheets_catalog_time_metrics"
CLAIMS_COLLECTION = "claims"
FULL_WITHDRAWALS_COLLECTION = "sheets_full_withdrawals"
ITEM_STATUS_STATES_COLLECTION = "item_status_states"
ORDERS_COLLECTION = "orders"
PRICE_HISTORY_SNAPSHOTS_COLLECTION = "sheets_price_history_snapshots"
QUESTIONS_COLLECTION = "questions"
READ_MODEL_FRESHNESS_COLLECTION = "sheets_read_model_freshness"
SELLER_UNIT_COSTS_COLLECTION = "seller_unit_costs"
SHIPMENTS_COLLECTION = "shipments"
STOCK_TIME_METRICS_COLLECTION = "sheets_stock_time_metrics"
STOCKOUT_SNAPSHOTS_COLLECTION = "sheets_stockout_snapshots"
CATALOG_BUYBOX_SNAPSHOTS_READ_MODEL = "catalog_buybox_snapshots"
CATALOG_PRODUCT_SNAPSHOTS_READ_MODEL = "catalog_product_snapshots"
CATALOG_TIME_METRICS_READ_MODEL = "catalog_time_metrics"
CLAIMS_READ_MODEL = "claims"
DEVOLUCIONES_READ_MODEL = "devoluciones"
# Both writers are canonical: the joint reconcile publishes historical windows
# and the quota run publishes the settled windows of the refresh loop.
_DEVOLUCIONES_RECONCILED_SOURCES = frozenset(
    {
        "zelerdata_devoluciones_joint_reconcile",
        "zelerdata_devoluciones_quota_run",
    }
)
FULL_WITHDRAWALS_READ_MODEL = "full_withdrawals"
ITEM_FORMULA_ROWS_READ_MODEL = "item_formula_rows"
ITEM_STATUS_STATES_READ_MODEL = "item_status_states"
ORDERS_READ_MODEL = "orders"
PRICE_HISTORY_SNAPSHOTS_READ_MODEL = "price_history_snapshots"
QUESTIONS_READ_MODEL = "questions"
SHIPMENTS_READ_MODEL = "shipments"
STOCK_TIME_METRICS_READ_MODEL = "stock_time_metrics"
STOCKOUT_SNAPSHOTS_READ_MODEL = "stockout_snapshots"
INTERVAL_AGGREGATE_READ_MODELS = frozenset(
    {CATALOG_TIME_METRICS_READ_MODEL, STOCK_TIME_METRICS_READ_MODEL}
)
QUESTIONS_FRESHNESS_UNAVAILABLE_REASON = (
    "Questions read model has not passed freshness/reconciliation for the requested range."
)
RECONCILED_READ_MODEL_STATE = "reconciled"
PRODUCTIVE_READ_MODEL_STATES = frozenset({"fresh", "reconciled"})
UNBUILT_BATCH_MARKERS: frozenset[str] = frozenset()
SHIPMENT_RECEIVER_ADDRESS_PROJECTION = {
    "_id": 1,
    "formula_observed_at": 1,
    "unavailable_fields": 1,
    "receiver_address.name": 1,
    "receiver_address.street_name": 1,
    "receiver_address.street_number": 1,
    "receiver_address.neighborhood": 1,
    "receiver_address.zip_code": 1,
    "receiver_address.city": 1,
    "receiver_address.state": 1,
    "receiver_address.country": 1,
}
SHIPMENT_REAL_SHIPPING_COST_PROJECTION = {
    "_id": 1,
    "unavailable_fields": 1,
    "real_shipping_cost.seller_cost": 1,
    "real_shipping_cost.synced_at": 1,
}


@dataclass(frozen=True)
class DevolucionesReadSnapshot:
    revision: str
    proof_fingerprint: str


@dataclass(frozen=True)
class ItemRowResolution:
    """Rows for an item-formula read, plus how trustworthy their scope is.

    ``inventory_scope`` is true when the rows came from the caller-driven
    verified inventory enumeration instead of the reconciled marker. Formula
    readers must expose that difference: an enumeration proves current
    membership for the publications it returns, never a reconciled whole-seller
    interval, and it must never silently certify what it did not observe.
    """

    rows: list[dict[str, Any]]
    missing_items: tuple[str, ...]
    enumeration_current: bool
    inventory_scope: bool
    recovery: FormulaDataUnavailableError | None = None
    item_ids: tuple[str, ...] = ()

    def meta(self) -> dict[str, Any]:
        """Expose coverage only when the rows came from a verified enumeration."""
        if not self.inventory_scope:
            return {}
        return {
            "inventory_scope": True,
            "inventory_enumeration_current": self.enumeration_current,
            "inventory_rows_complete": self.enumeration_current and not self.missing_items,
            "inventory_partial_misses": len(self.missing_items),
        }


class FormulaReadModelRepository:
    def __init__(self, *, db: Any) -> None:
        self._db = db
        self._item_formula_rows = db[ITEM_FORMULA_ROWS_COLLECTION]
        self._item_sku_index = db[ITEM_SKU_INDEX_COLLECTION]
        self._catalog_buybox_snapshots = db[CATALOG_BUYBOX_SNAPSHOTS_COLLECTION]
        self._catalog_product_snapshots = db[CATALOG_PRODUCT_SNAPSHOTS_COLLECTION]
        self._catalog_time_metrics = db[CATALOG_TIME_METRICS_COLLECTION]
        self._claims = db[CLAIMS_COLLECTION]
        self._full_withdrawals = db[FULL_WITHDRAWALS_COLLECTION]
        self._item_status_states = db[ITEM_STATUS_STATES_COLLECTION]
        self._orders = db[ORDERS_COLLECTION]
        self._price_history_snapshots = db[PRICE_HISTORY_SNAPSHOTS_COLLECTION]
        self._questions = db[QUESTIONS_COLLECTION]
        self._read_model_freshness = db[READ_MODEL_FRESHNESS_COLLECTION]
        self._seller_unit_costs = db[SELLER_UNIT_COSTS_COLLECTION]
        self._shipments = db[SHIPMENTS_COLLECTION]
        self._stock_time_metrics = db[STOCK_TIME_METRICS_COLLECTION]
        self._stockout_snapshots = db[STOCKOUT_SNAPSHOTS_COLLECTION]

    async def find_sku_index_rows(
        self,
        *,
        seller_id: str,
        skus: list[str] | tuple[str, ...] | None = None,
        item_ids: list[str] | tuple[str, ...] | None = None,
        variation_ids: list[Any] | tuple[Any, ...] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        filter_spec = _seller_item_filter(
            seller_id=seller_id, skus=skus, item_ids=item_ids, variation_ids=variation_ids
        )
        cursor = self._item_sku_index.find(filter_spec).sort(
            [("normalized_sku", 1), ("item_id", 1), ("variation_id", 1)]
        )
        return cast("list[dict[str, Any]]", await cursor.to_list(length=limit))

    async def find_item_formula_rows(
        self,
        *,
        seller_id: str,
        skus: list[str] | tuple[str, ...] | None = None,
        item_ids: list[str] | tuple[str, ...] | None = None,
        inventory_ids: list[str] | tuple[str, ...] | None = None,
        limit: int | None = None,
        sort_by: str = "sku",
    ) -> list[dict[str, Any]]:
        filter_spec = _seller_item_filter(
            seller_id=seller_id,
            skus=skus,
            item_ids=item_ids,
            inventory_ids=inventory_ids,
        )
        sort_spec = (
            [("item_id", 1), ("variation_id", 1), ("normalized_sku", 1), ("_id", 1)]
            if sort_by == "publication"
            else [("normalized_sku", 1), ("item_id", 1)]
        )
        cursor = self._item_formula_rows.find(filter_spec).sort(sort_spec)
        return cast("list[dict[str, Any]]", await cursor.to_list(length=limit))

    async def resolve_item_formula_rows(
        self,
        *,
        seller_id: str,
        formula: str,
        now: datetime,
        skus: list[str] | tuple[str, ...] | None = None,
        item_ids: list[str] | tuple[str, ...] | None = None,
    ) -> ItemRowResolution:
        """Resolve item rows from the marker, else from verified current inventory.

        The reconciled marker is the stronger claim and is preferred. When the
        marker is missing or expired, this falls back to the same caller-driven
        verification that CALIDAD and CALCULADORA already use. An explicit
        selection is verified per publication; a whole-seller read uses the
        recent inventory enumeration. Either way only observed publications are
        returned and unverified ones stay explicitly missing instead of being
        presented as complete. No global marker is inferred from the sweep.
        """
        requested = tuple(dict.fromkeys(str(item_id).strip() for item_id in item_ids or ()))
        requested_skus = tuple(
            dict.fromkeys(normalized for sku in skus or () if (normalized := normalize_sku(sku)))
        )
        try:
            await self.require_read_model_productive(
                seller_id=seller_id,
                read_model=ITEM_FORMULA_ROWS_READ_MODEL,
                date_to=now,
                formula=formula,
            )
        except FormulaDataUnavailableError as unavailable:
            if requested:
                try:
                    rows, missing = await self.find_recent_item_formula_rows(
                        seller_id=seller_id,
                        item_ids=list(requested),
                        formula=formula,
                        now=now,
                    )
                except FormulaDataUnavailableError:
                    # Nothing in the selection is verifiable: keep the original
                    # reconciliation error rather than dropping evidence.
                    raise unavailable from None
                current = True
            else:
                try:
                    rows, _, missing, current = await self.find_recent_item_inventory(
                        seller_id=seller_id, formula=formula, now=now
                    )
                except FormulaDataUnavailableError:
                    # No verified enumeration exists yet: keep the original
                    # reconciliation error instead of presenting an empty table.
                    raise unavailable from None
            rows = _filter_rows_by_sku(rows, requested_skus)
            return ItemRowResolution(
                rows=rows,
                missing_items=tuple(missing),
                enumeration_current=current,
                inventory_scope=True,
                item_ids=requested,
                recovery=FormulaDataUnavailableError(
                    formula,
                    "Inventory publications need recovery.",
                    read_model=ITEM_FORMULA_ROWS_READ_MODEL,
                    item_ids=() if not current and not requested else tuple(missing),
                )
                if missing or not current
                else None,
            )
        rows = await self.find_item_formula_rows(
            seller_id=seller_id,
            skus=list(requested_skus) or None,
            item_ids=list(requested) or None,
            limit=None,
            sort_by="publication",
        )
        return ItemRowResolution(
            rows=rows,
            missing_items=(),
            enumeration_current=True,
            inventory_scope=False,
            item_ids=requested,
        )

    async def find_recent_item_inventory(
        self, *, seller_id: str, formula: str, now: datetime
    ) -> tuple[list[dict[str, Any]], list[str], tuple[str, ...], bool]:
        try:
            request = ItemInventoryRecoveryRequest(seller_id)
        except ValueError as exc:
            raise FormulaDataUnavailableError(
                formula,
                "Current inventory enumeration is unavailable for this seller.",
                read_model=ITEM_FORMULA_ROWS_READ_MODEL,
            ) from exc
        job = await self._db["sheets_formula_recovery_jobs"].find_one(
            {
                "_id": request.key,
                "seller_id": seller_id,
                "read_model": ITEM_FORMULA_ROWS_READ_MODEL,
                "inventory_scope": True,
            }
        )
        identities = job.get("inventory_ids") if job else None
        observed = _safe_utc_datetime(job.get("inventory_observed_at")) if job else None
        if (
            not job
            or not isinstance(identities, list)
            or len(identities) > 10000
            or any(
                not isinstance(value, str) or re.fullmatch(r"ML[A-Z][0-9]+", value) is None
                for value in identities
            )
            or identities != sorted(set(identities))
            or observed is None
            or observed > now
            or job.get("state") not in {"pending", "running", "completed", "failed"}
            or (
                "inventory_offset" in job
                and (
                    type(job["inventory_offset"]) is not int
                    or not 0 <= job["inventory_offset"] <= len(identities)
                )
            )
        ):
            raise FormulaDataUnavailableError(
                formula,
                "Current inventory enumeration is missing, malformed or expired.",
                read_model=ITEM_FORMULA_ROWS_READ_MODEL,
            )
        enumeration_current = now - timedelta(minutes=15) < observed
        if not identities:
            if not enumeration_current:
                raise FormulaDataUnavailableError(
                    formula,
                    "Empty inventory enumeration expired.",
                    read_model=ITEM_FORMULA_ROWS_READ_MODEL,
                )
            return [], [], (), True
        try:
            rows, missing = await self.find_recent_item_formula_rows(
                seller_id=seller_id, item_ids=identities, formula=formula, now=now
            )
        except FormulaDataUnavailableError:
            # Membership is known, but no safe matrix of source-bound rows was
            # obtained. Preserve explicit unavailable IDs, never partial rows.
            return [], identities, tuple(identities), enumeration_current
        # Known membership remains useful, but only individually current,
        # source-verified rows may survive an expired enumeration. The caller
        # must expose unknown inventory coverage and request rediscovery.
        return rows, identities, missing, enumeration_current

    async def find_recent_item_formula_rows(
        self, *, seller_id: str, item_ids: list[str], formula: str, now: datetime
    ) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
        requested = set(item_ids)
        rows = await self.find_item_formula_rows(
            seller_id=seller_id, item_ids=item_ids, limit=10001, sort_by="publication"
        )
        sources = (
            await self._db["items"]
            .find({"seller_id": seller_id, "_id": {"$in": item_ids}})
            .to_list(length=10001)
        )
        by_id = {str(source["_id"]): source for source in sources}
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(str(row["item_id"]), []).append(row)
        missing = []
        for identity in sorted(requested):
            source = by_id.get(identity)
            group = grouped.get(identity, [])
            observed = _safe_utc_datetime(source.get("last_meli_sync_at")) if source else None
            if (
                not source
                or not group
                or observed is None
                or not now - timedelta(minutes=15) < observed <= now
            ):
                missing.append(identity)
                continue
            fingerprint = item_source_fingerprint(source)
            if any(
                not isinstance(snapshot := row.get("source_snapshot"), dict)
                or snapshot.get("fingerprint") != fingerprint
                or _safe_utc_datetime(snapshot.get("observed_at")) != observed
                or type(snapshot.get("rows_count")) is not int
                or snapshot["rows_count"] != len(group)
                for row in group
            ):
                missing.append(identity)
        if len(rows) > 10000 or len(sources) > 10000 or len(missing) == len(requested):
            raise FormulaDataUnavailableError(
                formula,
                "Selected item_formula_rows are missing, incomplete or not recently acquired.",
                read_model=ITEM_FORMULA_ROWS_READ_MODEL,
                item_ids=tuple(sorted(requested)),
            )
        unavailable = set(missing)
        return [row for row in rows if str(row["item_id"]) not in unavailable], tuple(missing)

    async def catalog_sales_coverage(
        self, *, seller_id: str, formula: str, now: datetime, windows: tuple[int, ...]
    ) -> tuple[datetime, tuple[int, ...], FormulaDataUnavailableError | None]:
        marker = await self._read_model_freshness.find_one(
            {"_id": f"{seller_id}:orders", "seller_id": seller_id, "read_model": ORDERS_READ_MODEL}
        )
        end = _safe_utc_datetime(marker.get("reconciled_until")) if marker else None
        # A recent acquired cut is useful without pretending it is live data.
        as_of = end if end is not None and now - timedelta(minutes=15) < end <= now else now
        covered = tuple(
            days
            for days in windows
            if read_model_reconciliation_marker_covers(
                marker,
                date_from=(as_of - timedelta(days=days)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                ),
                date_to=as_of,
            )
        )
        missing = next((days for days in windows if days not in covered), None)
        recovery = None
        if missing is not None:
            start = (as_of - timedelta(days=missing)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            # Recovery acquires this interval without expanding it to older
            # coverage. Admission remains bounded to 90 days.
            recovery = FormulaDataUnavailableError(
                formula,
                "Catalog sales interval is not reconciled.",
                read_model=ORDERS_READ_MODEL,
                date_from=start,
                date_to=min(as_of, start + timedelta(days=90)),
            )
        return as_of, covered, recovery

    async def find_orders(
        self,
        *,
        seller_id: str,
        date_from: Any,
        date_to: Any,
        status: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        filter_spec: dict[str, Any] = _seller_date_filter(
            seller_id=seller_id,
            date_from=date_from,
            date_to=date_to,
        )
        if status is not None:
            filter_spec["status"] = status
        cursor = self._orders.find(filter_spec).sort([("date_created", 1), ("_id", 1)])
        return cast("list[dict[str, Any]]", await cursor.to_list(length=limit))

    async def find_orders_by_ids(
        self,
        *,
        seller_id: str,
        order_ids: list[str] | tuple[str, ...],
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        normalized_order_ids = list(
            dict.fromkeys(str(order_id).strip() for order_id in order_ids if str(order_id).strip())
        )
        if not normalized_order_ids:
            return []
        cursor = self._orders.find(
            {"seller_id": seller_id, "_id": {"$in": normalized_order_ids}}
        ).sort([("date_created", 1), ("_id", 1)])
        return cast("list[dict[str, Any]]", await cursor.to_list(length=limit))

    async def find_return_claims(
        self,
        *,
        seller_id: str,
        date_from: Any,
        date_to: Any,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        filter_spec = _seller_date_filter(
            seller_id=seller_id,
            date_from=date_from,
            date_to=date_to,
        )
        filter_spec["type"] = {"$in": ["returns", "return"]}
        cursor = self._claims.find(filter_spec).sort([("date_created", 1), ("_id", 1)])
        return cast("list[dict[str, Any]]", await cursor.to_list(length=limit))

    async def find_devoluciones_claims(
        self,
        *,
        seller_id: str,
        date_from: datetime,
        date_to: datetime,
    ) -> list[dict[str, Any]]:
        return await read_devoluciones_claims_keyset(
            db=self._db,
            seller_id=seller_id,
            date_from=date_from,
            date_to=date_to,
        )

    async def find_devoluciones_orders(
        self,
        *,
        seller_id: str,
        order_ids: list[str] | tuple[str, ...],
    ) -> list[dict[str, Any]]:
        return await read_devoluciones_orders_by_id_keyset(
            db=self._db,
            seller_id=seller_id,
            order_ids=order_ids,
        )

    async def find_item_status_states(
        self,
        *,
        seller_id: str,
        item_ids: list[str] | tuple[str, ...] | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        filter_spec: dict[str, Any] = {"seller_id": seller_id}
        normalized_item_ids = list(
            dict.fromkeys(
                str(item_id).strip() for item_id in item_ids or [] if str(item_id).strip()
            )
        )
        if normalized_item_ids:
            filter_spec["item_id"] = {"$in": normalized_item_ids}
        cursor = self._item_status_states.find(filter_spec).sort([("item_id", 1), ("_id", 1)])
        return cast("list[dict[str, Any]]", await cursor.to_list(length=limit))

    async def find_shipments_by_ids(
        self,
        *,
        seller_id: str,
        shipment_ids: list[str] | tuple[str, ...],
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        normalized_shipment_ids = list(
            dict.fromkeys(
                str(shipment_id).strip() for shipment_id in shipment_ids if str(shipment_id).strip()
            )
        )
        if not normalized_shipment_ids:
            return []
        cursor = self._shipments.find(
            {"seller_id": seller_id, "_id": {"$in": normalized_shipment_ids}}
        ).sort([("_id", 1)])
        return cast(
            "list[dict[str, Any]]",
            await cursor.to_list(length=max(limit, len(normalized_shipment_ids))),
        )

    async def find_catalog_product_snapshots(
        self,
        *,
        seller_id: str,
        catalog_product_ids: list[str] | tuple[str, ...] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        filter_spec: dict[str, Any] = {"seller_id": seller_id}
        normalized_ids = list(
            dict.fromkeys(
                str(catalog_id).strip()
                for catalog_id in catalog_product_ids or []
                if str(catalog_id).strip()
            )
        )
        if normalized_ids:
            filter_spec["catalog_product_id"] = {"$in": normalized_ids}
        cursor = self._catalog_product_snapshots.find(filter_spec).sort(
            [("catalog_product_id", 1), ("_id", 1)]
        )
        return cast("list[dict[str, Any]]", await cursor.to_list(length=limit))

    async def find_recent_catalog_product_inventory(
        self, *, seller_id: str, formula: str, now: datetime
    ) -> tuple[list[dict[str, Any]], tuple[str, ...], tuple[str, ...], bool, tuple[str, ...]]:
        rows, _, missing_items, current = await self.find_recent_item_inventory(
            seller_id=seller_id, formula=formula, now=now
        )
        product_ids: set[str] = set()
        invalid_items = set(missing_items)
        trusted = {str(row["item_id"]): row["source_snapshot"] for row in rows}
        sources = (
            await self._db["items"]
            .find({"seller_id": seller_id, "_id": {"$in": sorted(trusted)}})
            .to_list(length=10001)
            if trusted
            else []
        )
        invalid_items.update(set(trusted) - {str(source["_id"]) for source in sources})
        for source in sources:
            item_id = str(source["_id"])
            if item_source_fingerprint(source) != trusted[item_id][
                "fingerprint"
            ] or _safe_utc_datetime(source.get("last_meli_sync_at")) != _safe_utc_datetime(
                trusted[item_id]["observed_at"]
            ):
                invalid_items.add(item_id)
                continue
            # SKU-less parents may have only variant formula rows. Associations
            # belong to the verified canonical item, not the set of SKU rows.
            for resource in [source, *(source.get("variations") or [])]:
                identity = resource.get("catalog_product_id")
                if identity is None:
                    continue
                if (
                    not isinstance(identity, str)
                    or re.fullmatch(r"ML[A-Z][0-9]+", identity) is None
                ):
                    invalid_items.add(item_id)
                    continue
                product_ids.add(identity)
        snapshots = (
            await self.find_catalog_product_snapshots(
                seller_id=seller_id, catalog_product_ids=sorted(product_ids)
            )
            if product_ids
            else []
        )
        ready = []
        source_missing: set[str] = set()
        for snapshot in snapshots:
            observed = _safe_utc_datetime(snapshot.get("snapshot_at"))
            title = snapshot.get("title")
            if not (
                snapshot.get("_id") == f"{seller_id}:{snapshot.get('catalog_product_id')}"
                and observed is not None
                and observed <= now
                and snapshot.get("source") in {"sheets_backfill", "historical_meli_backfill"}
            ):
                continue
            unavailable = snapshot.get("source_unavailable")
            checked = (
                _safe_utc_datetime(unavailable.get("observed_at"))
                if isinstance(unavailable, dict)
                else None
            )
            known_missing = (
                isinstance(unavailable, dict)
                and unavailable.get("reason") == "catalog_product_not_found"
                and checked is not None
                and now - timedelta(minutes=15) < checked <= now
                and checked >= observed
            )
            if known_missing:
                source_missing.add(snapshot["catalog_product_id"])
            if (
                (now - timedelta(minutes=15) < observed or known_missing)
                and isinstance(title, str)
                and bool(title.strip())
                and {"description", "image_url", "attributes"} <= snapshot.keys()
            ):
                # A fresh 404 can use the last known payload, but the caller
                # must label it cached and must not claim current completeness.
                ready.append(snapshot)
        missing = tuple(sorted(product_ids - {row["catalog_product_id"] for row in ready}))
        return ready, missing, tuple(sorted(invalid_items)), current, tuple(sorted(source_missing))

    async def find_recent_catalog_buybox_inventory(
        self,
        *,
        seller_id: str,
        formula: str,
        now: datetime,
        inventory: tuple[list[dict[str, Any]], list[str], tuple[str, ...], bool] | None = None,
    ) -> tuple[list[dict[str, Any]], tuple[str, ...], tuple[str, ...], bool]:
        if inventory is None:
            inventory = await self.find_recent_item_inventory(
                seller_id=seller_id, formula=formula, now=now
            )
        rows, _, missing_items, current = inventory
        trusted = {str(row["item_id"]): row["source_snapshot"] for row in rows}
        sources = (
            await self._db["items"]
            .find({"seller_id": seller_id, "_id": {"$in": sorted(trusted)}})
            .to_list(length=10001)
            if trusted
            else []
        )
        invalid = set(missing_items) | (set(trusted) - {str(row["_id"]) for row in sources})
        participating = {}
        for source in sources:
            identity = str(source["_id"])
            if item_source_fingerprint(source) != trusted[identity][
                "fingerprint"
            ] or _safe_utc_datetime(source.get("last_meli_sync_at")) != _safe_utc_datetime(
                trusted[identity]["observed_at"]
            ):
                invalid.add(identity)
                continue
            if source.get("catalog_listing") is False:
                continue
            product = source.get("catalog_product_id")
            if (
                source.get("catalog_listing") is not True
                or not isinstance(product, str)
                or re.fullmatch(r"ML[A-Z][0-9]+", product) is None
                or not isinstance(source.get("title"), str)
                or not source["title"].strip()
                or not isinstance(source.get("available_quantity"), int)
                or isinstance(source.get("available_quantity"), bool)
                or source["available_quantity"] < 0
            ):
                invalid.add(identity)
                continue
            participating[identity] = source
        snapshots = (
            await self._catalog_buybox_snapshots.find(
                {"seller_id": seller_id, "item_id": {"$in": sorted(participating)}}
            ).to_list(length=None)
            if participating
            else []
        )
        ready = []
        for snapshot in snapshots:
            identity = snapshot.get("item_id")
            source = participating.get(identity)
            observed = _safe_utc_datetime(snapshot.get("snapshot_at"))
            synced = _safe_utc_datetime(source.get("last_meli_sync_at")) if source else None
            if (
                source
                and observed is not None
                and synced is not None
                and now - timedelta(minutes=15) < observed <= now
                and synced <= observed
                and snapshot.get("_id") == f"{seller_id}:{identity}"
                and snapshot.get("source") in {"sheets_backfill", "historical_meli_backfill"}
                and snapshot.get("catalog_product_id") == source["catalog_product_id"]
                and snapshot.get("title") == source["title"].strip()
                and snapshot.get("available_quantity") == source.get("available_quantity")
            ):
                if snapshot.get("price") is None:
                    snapshot = {**snapshot, "price": acquired_current_price(source)}
                offers_at = _safe_utc_datetime(snapshot.get("offers_snapshot_at", observed))
                ready.append(
                    snapshot
                    if offers_at is not None and now - timedelta(minutes=15) < offers_at <= now
                    else {**snapshot, "competitor_count": None, "only_competitor": None}
                )
        missing = set(participating) - {row["item_id"] for row in ready}
        return ready, tuple(sorted(missing)), tuple(sorted(invalid)), current

    async def find_catalog_buybox_snapshots(
        self,
        *,
        seller_id: str,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        cursor = self._catalog_buybox_snapshots.find({"seller_id": seller_id}).sort(
            [("item_id", 1), ("catalog_product_id", 1), ("_id", 1)]
        )
        return cast("list[dict[str, Any]]", await cursor.to_list(length=limit))

    async def find_catalog_time_metrics(
        self,
        *,
        seller_id: str,
        date_from: Any,
        date_to: Any,
        item_ids: list[str] | tuple[str, ...] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        filter_spec = _seller_exact_interval_filter(
            seller_id=seller_id,
            date_from=date_from,
            date_to=date_to,
            item_ids=item_ids,
        )
        cursor = self._catalog_time_metrics.find(filter_spec).sort(
            [("item_id", 1), ("date_from", 1), ("_id", 1)]
        )
        return cast("list[dict[str, Any]]", await cursor.to_list(length=limit))

    async def find_price_history_snapshots(
        self,
        *,
        seller_id: str,
        item_ids: list[str] | tuple[str, ...] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        filter_spec: dict[str, Any] = {"seller_id": seller_id}
        if item_ids:
            filter_spec["item_id"] = {"$in": [str(item_id) for item_id in item_ids]}
        cursor = self._price_history_snapshots.find(filter_spec).sort([("item_id", 1), ("_id", 1)])
        return cast("list[dict[str, Any]]", await cursor.to_list(length=limit))

    async def find_stockout_snapshots(
        self,
        *,
        seller_id: str,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        cursor = self._stockout_snapshots.find({"seller_id": seller_id}).sort(
            [("item_id", 1), ("_id", 1)]
        )
        return cast("list[dict[str, Any]]", await cursor.to_list(length=limit))

    async def find_stock_time_metrics(
        self,
        *,
        seller_id: str,
        date_from: Any,
        date_to: Any,
        item_ids: list[str] | tuple[str, ...] | None = None,
        skus: list[str] | tuple[str, ...] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        filter_spec = _seller_exact_interval_filter(
            seller_id=seller_id,
            date_from=date_from,
            date_to=date_to,
            item_ids=item_ids,
        )
        normalized_skus = list(
            dict.fromkeys(normalized for sku in skus or [] if (normalized := normalize_sku(sku)))
        )
        if normalized_skus:
            filter_spec["normalized_sku"] = {"$in": normalized_skus}
        cursor = self._stock_time_metrics.find(filter_spec).sort(
            [("item_id", 1), ("normalized_sku", 1), ("date_from", 1), ("_id", 1)]
        )
        return cast("list[dict[str, Any]]", await cursor.to_list(length=limit))

    async def find_full_withdrawals(
        self,
        *,
        seller_id: str,
        date_from: Any,
        date_to: Any,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        filter_spec: dict[str, Any] = {
            "seller_id": seller_id,
            "created_at": {"$gte": date_from, "$lt": date_to},
        }
        cursor = self._full_withdrawals.find(filter_spec).sort(
            [("created_at", 1), ("withdrawal_id", 1), ("withdrawal_detail_id", 1), ("_id", 1)]
        )
        return cast("list[dict[str, Any]]", await cursor.to_list(length=limit))

    async def find_shipment_receiver_addresses(
        self,
        *,
        seller_id: str,
        shipment_ids: list[str] | tuple[str, ...],
        limit: int = 1000,
    ) -> dict[str, dict[str, Any]]:
        snapshots, recoverable, declared = await self.find_shipment_receiver_addresses_partial(
            seller_id=seller_id, shipment_ids=shipment_ids, limit=limit
        )
        if recoverable or declared:
            raise FormulaDataUnavailableError(
                "Shipment",
                "Required receiver_address is unavailable or has not been refreshed.",
                read_model="shipments",
                shipment_ids=(*recoverable, *declared),
            )
        return snapshots

    async def find_shipment_receiver_addresses_partial(
        self,
        *,
        seller_id: str,
        shipment_ids: list[str] | tuple[str, ...],
        limit: int = 1000,
    ) -> tuple[dict[str, dict[str, Any]], tuple[str, ...], tuple[str, ...]]:
        """Serve every known address and classify the remainder.

        Returns ``(addresses, recoverable, declared)``. ``recoverable`` may be
        fetched again from the source; ``declared`` is an absence Mercado Libre
        itself reported and must be served as NA.
        """
        normalized_shipment_ids = list(
            dict.fromkeys(
                str(shipment_id).strip() for shipment_id in shipment_ids if str(shipment_id).strip()
            )
        )
        if not normalized_shipment_ids:
            return {}, (), ()
        cursor = _find_with_optional_projection(
            self._shipments,
            {"seller_id": seller_id, "_id": {"$in": normalized_shipment_ids}},
            SHIPMENT_RECEIVER_ADDRESS_PROJECTION,
        )
        rows = cast(
            "list[dict[str, Any]]",
            await cursor.to_list(length=max(limit, len(normalized_shipment_ids))),
        )
        snapshots: dict[str, dict[str, Any]] = {}
        for row in rows:
            shipment_id = str(row.get("_id") or "").strip()
            receiver_address = row.get("receiver_address")
            if (
                shipment_id
                and isinstance(receiver_address, dict)
                and any(
                    isinstance(value, str) and value.strip() for value in receiver_address.values()
                )
            ):
                snapshots[shipment_id] = receiver_address
        recoverable, declared = _missing_shipment_field_ids(
            rows, normalized_shipment_ids, "receiver_address", set(snapshots)
        )
        return snapshots, recoverable, declared

    async def find_shipment_real_shipping_costs(
        self,
        *,
        seller_id: str,
        shipment_ids: list[str] | tuple[str, ...],
        limit: int = 1000,
    ) -> dict[str, Decimal]:
        costs, recoverable, declared = await self.find_shipment_real_shipping_costs_partial(
            seller_id=seller_id, shipment_ids=shipment_ids, limit=limit
        )
        if recoverable or declared:
            raise FormulaDataUnavailableError(
                "Shipment",
                "Required real_shipping_cost is unavailable or has not been refreshed.",
                read_model="shipments",
                shipment_ids=(*recoverable, *declared),
            )
        return costs

    async def find_shipment_real_shipping_costs_partial(
        self,
        *,
        seller_id: str,
        shipment_ids: list[str] | tuple[str, ...],
        limit: int = 1000,
    ) -> tuple[dict[str, Decimal], tuple[str, ...], tuple[str, ...]]:
        """Serve every known cost and classify the remainder."""
        normalized_shipment_ids = list(
            dict.fromkeys(
                str(shipment_id).strip() for shipment_id in shipment_ids if str(shipment_id).strip()
            )
        )
        if not normalized_shipment_ids:
            return {}, (), ()
        cursor = _find_with_optional_projection(
            self._shipments,
            {"seller_id": seller_id, "_id": {"$in": normalized_shipment_ids}},
            SHIPMENT_REAL_SHIPPING_COST_PROJECTION,
        )
        rows = cast(
            "list[dict[str, Any]]",
            await cursor.to_list(length=max(limit, len(normalized_shipment_ids))),
        )
        costs: dict[str, Decimal] = {}
        for row in rows:
            shipment_id = str(row.get("_id") or "").strip()
            projection = row.get("real_shipping_cost")
            if not shipment_id or not isinstance(projection, dict):
                continue
            seller_cost = _finite_non_negative_decimal(projection.get("seller_cost"))
            if seller_cost is not None:
                costs[shipment_id] = seller_cost
        recoverable, declared = _missing_shipment_field_ids(
            rows, normalized_shipment_ids, "real_shipping_cost", set(costs)
        )
        return costs, recoverable, declared

    async def find_questions(
        self,
        *,
        seller_id: str,
        date_from: Any,
        date_to: Any,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        filter_spec = _seller_date_filter(
            seller_id=seller_id,
            date_from=date_from,
            date_to=date_to,
        )
        cursor = self._questions.find(filter_spec).sort([("date_created", 1), ("_id", 1)])
        return cast("list[dict[str, Any]]", await cursor.to_list(length=limit))

    async def require_questions_read_model_productive(
        self,
        *,
        seller_id: str,
        date_from: Any,
        date_to: Any,
        formula: str,
    ) -> None:
        marker = await self._read_model_freshness.find_one(
            {
                "_id": read_model_freshness_id(seller_id, QUESTIONS_READ_MODEL),
                "seller_id": seller_id,
                "read_model": QUESTIONS_READ_MODEL,
            }
        )
        if not _questions_freshness_marker_covers(
            marker,
            date_from=date_from,
            date_to=date_to,
        ):
            raise FormulaDataUnavailableError(
                formula,
                QUESTIONS_FRESHNESS_UNAVAILABLE_REASON,
                read_model=QUESTIONS_READ_MODEL,
                date_from=_safe_utc_datetime(date_from),
                date_to=_safe_utc_datetime(date_to),
            )

    async def require_read_model_productive(
        self,
        *,
        seller_id: str,
        read_model: str,
        date_to: Any,
        formula: str,
        item_ids: list[str] | None = None,
    ) -> None:
        marker = await self._read_model_freshness.find_one(
            {
                "_id": read_model_freshness_id(seller_id, read_model),
                "seller_id": seller_id,
                "read_model": read_model,
            }
        )
        if not _read_model_freshness_marker_covers(marker, date_to=date_to):
            reason = (
                f"Read model {read_model} has not passed freshness/reconciliation "
                "for the requested range."
            )
            raise FormulaDataUnavailableError(
                formula,
                reason,
                read_model=read_model,
                date_to=_safe_utc_datetime(date_to),
                item_ids=tuple(item_ids or ()),
            )

    async def require_read_model_reconciled_range(
        self,
        *,
        seller_id: str,
        read_model: str,
        date_from: Any,
        date_to: Any,
        formula: str,
    ) -> None:
        marker = await self._read_model_freshness.find_one(
            {
                "_id": read_model_freshness_id(seller_id, read_model),
                "seller_id": seller_id,
                "read_model": read_model,
            }
        )
        if not read_model_reconciliation_marker_covers(
            marker,
            date_from=date_from,
            date_to=date_to,
            coverage_basis=None if read_model == ORDERS_READ_MODEL else "legacy_imported",
            exact_interval=read_model in INTERVAL_AGGREGATE_READ_MODELS,
        ):
            reason = (
                f"Read model {read_model} has not passed freshness/reconciliation "
                "for the requested range."
            )
            raise FormulaDataUnavailableError(
                formula,
                reason,
                read_model=read_model,
                date_from=_safe_utc_datetime(date_from),
                date_to=_safe_utc_datetime(date_to),
            )

    async def require_devoluciones_reconciled_range(
        self,
        *,
        seller_id: str,
        date_from: datetime,
        date_to: datetime,
        now: datetime,
        formula: str,
    ) -> DevolucionesReadSnapshot:
        marker = await self._read_model_freshness.find_one(
            {
                "_id": read_model_freshness_id(seller_id, DEVOLUCIONES_READ_MODEL),
                "seller_id": seller_id,
                "read_model": DEVOLUCIONES_READ_MODEL,
                "state": RECONCILED_READ_MODEL_STATE,
                "$expr": {"$gt": ["$valid_until", "$$NOW"]},
            }
        )
        if not devoluciones_reconciliation_marker_covers(
            marker,
            date_from=date_from,
            date_to=date_to,
            now=now,
        ):
            _raise_devoluciones_snapshot_unavailable(formula)
        revision = str(marker.get("revision") or "").strip()
        proof_fingerprint = str(marker.get("proof_fingerprint") or "").strip()
        if not revision or not proof_fingerprint:
            _raise_devoluciones_snapshot_unavailable(formula)
        return DevolucionesReadSnapshot(
            revision=revision,
            proof_fingerprint=proof_fingerprint,
        )

    async def validate_devoluciones_read_snapshot(
        self,
        *,
        seller_id: str,
        date_from: datetime,
        date_to: datetime,
        now: datetime,
        formula: str,
        snapshot: DevolucionesReadSnapshot,
    ) -> None:
        marker = await self._read_model_freshness.find_one(
            {
                "_id": read_model_freshness_id(seller_id, DEVOLUCIONES_READ_MODEL),
                "seller_id": seller_id,
                "read_model": DEVOLUCIONES_READ_MODEL,
                "state": RECONCILED_READ_MODEL_STATE,
                "revision": snapshot.revision,
                "proof_fingerprint": snapshot.proof_fingerprint,
                "$expr": {"$gt": ["$valid_until", "$$NOW"]},
            }
        )
        if not devoluciones_reconciliation_marker_covers(
            marker,
            date_from=date_from,
            date_to=date_to,
            now=now,
        ):
            _raise_devoluciones_snapshot_unavailable(formula)

    async def find_unit_costs(
        self,
        *,
        seller_id: str,
        lookups: list[UnitCostLookup] | tuple[UnitCostLookup, ...],
        limit: int | None = None,
    ) -> dict[UnitCostLookup, Any]:
        normalized_lookups = [
            lookup for lookup in lookups if lookup.normalized_sku or lookup.item_id
        ]
        if not normalized_lookups:
            return {}
        skus = list(
            dict.fromkeys(
                lookup.normalized_sku for lookup in normalized_lookups if lookup.normalized_sku
            )
        )
        item_ids = list(
            dict.fromkeys(lookup.item_id for lookup in normalized_lookups if lookup.item_id)
        )
        branches: list[dict[str, Any]] = []
        if skus:
            branches.append({"normalized_sku": {"$in": skus}})
        if item_ids:
            branches.append({"item_id": {"$in": item_ids}})
        filter_spec: dict[str, Any] = {"seller_id": seller_id}
        if branches:
            filter_spec["$or"] = branches
        cursor = self._seller_unit_costs.find(filter_spec).sort(
            [("normalized_sku", 1), ("item_id", 1), ("variation_id", 1), ("effective_from", -1)]
        )
        docs = cast("list[dict[str, Any]]", await cursor.to_list(length=limit))
        return {lookup: resolve_unit_cost(docs, lookup) for lookup in normalized_lookups}


def require_formula_read_model_available(contract: FormulaContract) -> None:
    batches = set(contract.batch.split("/"))
    if batches & UNBUILT_BATCH_MARKERS:
        raise FormulaDataUnavailableError(contract.name)


def _raise_devoluciones_snapshot_unavailable(formula: str) -> None:
    raise FormulaDataUnavailableError(
        formula,
        "The joint devoluciones claims/orders freshness/reconciliation snapshot changed, does "
        "not enclose the requested range, or has expired.",
    )


def read_model_freshness_id(seller_id: str, read_model: str) -> str:
    return f"{seller_id}:{read_model}"


def _missing_shipment_field_ids(
    rows: list[dict[str, Any]], shipment_ids: Sequence[str], field: str, available_ids: set[str]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split absent shipment fields into recoverable and declared-missing IDs.

    A shipment receiver address is immutable history: once the source delivered
    it, every later read may serve it without re-acquiring it inside a short
    freshness window. Requiring a recent observation for a multi-year history is
    impossible under the reserved quota and made complete tables unavailable.
    The seller-scoped document and a non-empty value remain the proof; a field
    the source explicitly declared unavailable is irrecoverable and is reported
    separately so callers can emit NA without a permanent recovery loop.
    """
    by_id = {str(row.get("_id")): row for row in rows}
    now = datetime.now(UTC)
    recoverable: list[str] = []
    declared: list[str] = []
    for identity in shipment_ids:
        row = by_id.get(identity, {})
        observed = _safe_utc_datetime(
            row.get("formula_observed_at")
            if field == "receiver_address"
            else (row.get("real_shipping_cost") or {}).get("synced_at")
        )
        # An observation from the future is not a valid proof of anything; ask
        # the source again instead of trusting it.
        future = observed is not None and observed > now
        if (
            identity in available_ids
            and field not in (row.get("unavailable_fields") or [])
            and not future
        ):
            continue
        if field in (row.get("unavailable_fields") or []):
            declared.append(identity)
        else:
            recoverable.append(identity)
    return tuple(recoverable), tuple(declared)


def _require_shipment_field(
    rows: list[dict[str, Any]], shipment_ids: list[str], field: str, available_ids: set[str]
) -> None:
    recoverable, declared = _missing_shipment_field_ids(rows, shipment_ids, field, available_ids)
    missing = (*recoverable, *declared)
    if missing:
        raise FormulaDataUnavailableError(
            "Shipment",
            f"Required {field} is unavailable or has not been refreshed.",
            read_model="shipments",
            shipment_ids=tuple(missing),
        )


def _find_with_optional_projection(
    collection: Any,
    filter_spec: dict[str, Any],
    projection: dict[str, int],
) -> Any:
    try:
        return collection.find(filter_spec, projection)
    except TypeError:
        return collection.find(filter_spec)


def normalize_sku(sku: Any) -> str:
    return str(sku).strip().upper()


def _questions_freshness_marker_covers(marker: Any, *, date_from: Any, date_to: Any) -> bool:
    return read_model_reconciliation_marker_covers(
        marker,
        date_from=date_from,
        date_to=date_to,
    )


def read_model_reconciliation_marker_covers(
    marker: Any,
    *,
    date_from: Any,
    date_to: Any,
    coverage_basis: str | None = None,
    exact_interval: bool = False,
    now: datetime | None = None,
    allow_live_claim: bool = True,
) -> bool:
    """Whether a reconciled marker authorizes a read of ``date_from..date_to``.

    A reconciled interval is a durable record of what was acquired from the
    source and verified against it. Its ``valid_until`` window governs only the
    live claim at the edge of coverage: an expired window stops certifying the
    uncovered tail of a "recent" read, and never rewrites history that was
    already acquired. Invalidating the marker (``stale``/``failed``) still
    withdraws every interval at once.
    """
    if not isinstance(marker, dict):
        return False
    proofs = _marker_interval_proofs(marker)
    if proofs is None:
        return False
    current, retained = proofs
    read_instant = _safe_utc_datetime(now) or datetime.now(UTC)
    requested_from = _safe_utc_datetime(date_from)
    requested_until = _safe_utc_datetime(date_to)
    # A range that has not started yet, or that cannot be compared as an
    # instant, is never authorized by any claim.
    if requested_from is None or requested_until is None or requested_from > read_instant:
        return False
    if exact_interval:
        return _exact_interval_is_proven(
            current,
            requested_from=requested_from,
            requested_until=requested_until,
            read_instant=read_instant,
            coverage_basis=coverage_basis,
        )
    covered = [
        proof
        for proof in [current, *retained]
        if _is_proven_interval(proof, coverage_basis=coverage_basis)
    ]
    if not covered:
        return False
    covered.sort(key=lambda proof: _safe_utc_datetime(proof.get("date_from")) or datetime.min)
    return _union_covers_instant(
        covered,
        requested_from=requested_from,
        requested_until=requested_until,
        read_instant=read_instant,
        reference=current,
        allow_live_claim=allow_live_claim,
    )


def _marker_interval_proofs(
    marker: Any, *, states: frozenset[str] = frozenset({RECONCILED_READ_MODEL_STATE})
) -> tuple[dict[str, Any], list[Any]] | None:
    """Split a marker into its current claim and independently retained proofs.

    Returns ``None`` when the marker is not in one of the accepted productive
    states, which is how an invalidated marker withdraws every interval it used
    to hold. Retained proofs are themselves checked against the same states.
    """
    if not isinstance(marker, dict):
        return None
    if str(marker.get("state") or "").strip().casefold() not in states:
        return None
    if "retained_intervals" not in marker:
        return marker, []
    retained = marker["retained_intervals"]
    if not isinstance(retained, list):
        return None
    current = {key: value for key, value in marker.items() if key != "retained_intervals"}
    return current, [proof for proof in retained if isinstance(proof, dict)]


def _exact_interval_is_proven(
    proof: dict[str, Any],
    *,
    requested_from: datetime,
    requested_until: datetime,
    read_instant: datetime,
    coverage_basis: str | None,
) -> bool:
    """Strict interval equality for models whose window is the whole proof."""
    if not _claim_is_open(proof, read_instant=read_instant) or not _is_proven_interval(
        proof, coverage_basis=coverage_basis
    ):
        return False
    coverage_start = _first_utc_datetime(
        proof.get("date_from"),
        proof.get("last_event_synced_at"),
    )
    reconciled_until = _safe_utc_datetime(proof.get("reconciled_until"))
    if coverage_start is None or reconciled_until is None:
        return False
    # The requested end may fall inside the current local day, which has not
    # finished yet; what can be compared is the part that already happened.
    bounded_until = min(requested_until, read_instant)
    return coverage_start == requested_from and reconciled_until == bounded_until


def _union_covers_instant(
    proofs: list[dict[str, Any]],
    *,
    requested_from: datetime,
    requested_until: datetime,
    read_instant: datetime,
    reference: dict[str, Any],
    allow_live_claim: bool,
) -> bool:
    """Whether the union of durable proofs reaches the requested read instant.

    Only the uncovered tail may lean on the live claim of ``reference``. A gap
    between two independent proofs is never silently covered.
    """
    requested_instant = min(requested_until, read_instant)
    intervals: list[tuple[datetime, datetime]] = []
    for proof in proofs:
        start = _safe_utc_datetime(proof.get("date_from")) or _safe_utc_datetime(
            proof.get("last_event_synced_at")
        )
        end = _safe_utc_datetime(proof.get("reconciled_until"))
        if start is None or end is None or end < start:
            continue
        # Gaps outside the requested range are irrelevant; only the span the
        # caller actually reads must be covered without holes.
        clipped_start = max(start, requested_from)
        clipped_end = min(end, requested_instant)
        if clipped_start <= clipped_end:
            intervals.append((clipped_start, clipped_end))
    if not intervals:
        return False
    intervals.sort()
    if intervals[0][0] > requested_from:
        return False
    covered_until = intervals[0][1]
    for start, end in intervals[1:]:
        if start > covered_until:
            return False
        covered_until = max(covered_until, end)
    if covered_until >= requested_instant:
        return True
    return allow_live_claim and _live_claim_covers_instant(
        reference,
        coverage_until=covered_until,
        read_instant=read_instant,
    )


def _is_proven_interval(proof: Any, *, coverage_basis: str | None) -> bool:
    """Whether a claim still records a reconciled acquisition.

    Unlike the live claim, a proven interval is not withdrawn when its validity
    window closes; only an explicit invalidation does that.
    """
    if not isinstance(proof, dict):
        return False
    if str(proof.get("state") or "").strip().casefold() != RECONCILED_READ_MODEL_STATE:
        return False
    return not (
        coverage_basis is not None
        and str(proof.get("coverage_basis") or "").strip() != coverage_basis
    )


def _claim_is_open(proof: Any, *, read_instant: datetime) -> bool:
    """Whether a claim may still certify the live edge of coverage."""
    if not isinstance(proof, dict):
        return False
    if str(proof.get("state") or "").strip().casefold() != RECONCILED_READ_MODEL_STATE:
        return False
    valid_until = proof.get("valid_until")
    if valid_until is None:
        return True
    parsed = _safe_utc_datetime(valid_until)
    return parsed is not None and parsed > read_instant


def devoluciones_reconciliation_marker_covers(
    marker: Any,
    *,
    date_from: Any,
    date_to: Any,
    now: Any,
) -> bool:
    if not isinstance(marker, dict):
        return False
    if marker.get("read_model") != DEVOLUCIONES_READ_MODEL:
        return False
    if str(marker.get("state") or "").strip().casefold() != RECONCILED_READ_MODEL_STATE:
        return False
    requested_from = _safe_utc_datetime(date_from)
    requested_until = _safe_utc_datetime(date_to)
    coverage_start = _safe_utc_datetime(marker.get("date_from"))
    reconciled_until = _safe_utc_datetime(marker.get("reconciled_until"))
    fresh_until = _safe_utc_datetime(marker.get("fresh_until"))
    last_event_synced_at = _safe_utc_datetime(marker.get("last_event_synced_at"))
    valid_until = _safe_utc_datetime(marker.get("valid_until"))
    current_time = _safe_utc_datetime(now)
    return bool(
        requested_from is not None
        and requested_until is not None
        and requested_from < requested_until
        and coverage_start is not None
        and reconciled_until is not None
        and fresh_until == reconciled_until
        and last_event_synced_at == coverage_start
        and marker.get("source") in _DEVOLUCIONES_RECONCILED_SOURCES
        and coverage_start < reconciled_until
        and coverage_start <= requested_from
        and reconciled_until >= requested_until
        and valid_until is not None
        and current_time is not None
        and valid_until > current_time
    )


def _read_model_freshness_marker_covers(marker: Any, *, date_to: Any) -> bool:
    """Whether a marker certifies a read that reaches ``date_to``.

    A historical-window publication legitimately narrows the top-level claim
    while retaining the newer proof it did not re-acquire. The gate therefore
    considers every durable proof: a "now" read is served from whichever claim
    is still live, instead of reporting unavailable until the next fast cycle.
    """
    proofs = _marker_interval_proofs(marker, states=PRODUCTIVE_READ_MODEL_STATES)
    if proofs is None:
        return False
    current, retained = proofs
    now = datetime.now(UTC)
    requested_until = _safe_utc_datetime(date_to)
    if requested_until is None:
        return False
    if requested_until > now:
        # A "now"-bounded read demands coverage of an instant that has not
        # happened yet. Hours that have not occurred cannot be reconciled, so
        # the requirement stops at the read instant.
        requested_until = now
    return any(
        _productive_claim_covers_instant(proof, requested_until=requested_until, now=now)
        for proof in [current, *retained]
    )


def _productive_claim_covers_instant(
    proof: Any, *, requested_until: datetime, now: datetime
) -> bool:
    """Whether one claim certifies data up to ``requested_until``.

    The claim must be productive and its own validity window must still be open;
    a claim further behind than the two-cycle tolerance must drive a new
    acquisition instead of presenting stale data as current.
    """
    if not isinstance(proof, dict):
        return False
    state = str(proof.get("state") or "").strip().casefold()
    if state not in PRODUCTIVE_READ_MODEL_STATES:
        return False
    valid_until = proof.get("valid_until")
    if valid_until is not None:
        parsed_validity = _safe_utc_datetime(valid_until)
        if parsed_validity is None or parsed_validity <= now:
            return False
    fresh_until = _latest_utc_datetime(
        proof.get("fresh_until"),
        proof.get("reconciled_until"),
    )
    if fresh_until is None:
        return False
    if fresh_until >= requested_until:
        return True
    return _live_claim_covers_instant(proof, coverage_until=fresh_until, read_instant=now)


def _latest_utc_datetime(*values: Any) -> datetime | None:
    parsed = [
        date_value for value in values if (date_value := _safe_utc_datetime(value)) is not None
    ]
    return max(parsed) if parsed else None


def _live_claim_covers_instant(
    marker: Any, *, coverage_until: datetime | None, read_instant: datetime
) -> bool:
    """Whether a still-valid claim may certify current data.

    The tolerance is exactly the marker validity window (two refresh cycles),
    measured from the instant the acquisition actually certified. A claim that
    has expired, or whose coverage is older than that window, never qualifies.
    """
    if not isinstance(marker, dict) or coverage_until is None:
        return False
    valid_until = _safe_utc_datetime(marker.get("valid_until"))
    if valid_until is None or valid_until <= read_instant:
        return False
    return read_instant <= coverage_until + MARKER_VALIDITY


def _first_utc_datetime(*values: Any) -> datetime | None:
    for value in values:
        if (date_value := _safe_utc_datetime(value)) is not None:
            return date_value
    return None


def _safe_utc_datetime(value: Any) -> datetime | None:
    try:
        return _as_utc_datetime(value)
    except (TypeError, ValueError):
        return None


def _finite_non_negative_decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, (bool, dict, list, tuple, set)):
        return None
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    except (DecimalException, ValueError):
        return None
    if not parsed.is_finite() or parsed < 0:
        return None
    return parsed


def _seller_item_filter(
    *,
    seller_id: str,
    skus: list[str] | tuple[str, ...] | None = None,
    item_ids: list[str] | tuple[str, ...] | None = None,
    variation_ids: list[Any] | tuple[Any, ...] | None = None,
    inventory_ids: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    filter_spec: dict[str, Any] = {"seller_id": seller_id}
    normalized_skus = list(
        dict.fromkeys(normalized for sku in skus or [] if (normalized := normalize_sku(sku)))
    )
    if normalized_skus:
        filter_spec["normalized_sku"] = {"$in": normalized_skus}
    if item_ids:
        filter_spec["item_id"] = {"$in": [str(item_id) for item_id in item_ids]}
    if variation_ids:
        normalized_variations = list(
            dict.fromkeys(
                None if variation_id is None else str(variation_id).strip()
                for variation_id in variation_ids
            )
        )
        filter_spec["variation_id"] = {"$in": normalized_variations}
    if inventory_ids:
        filter_spec["inventory_id"] = {"$in": [str(inventory_id) for inventory_id in inventory_ids]}
    return filter_spec


def _filter_rows_by_sku(
    rows: list[dict[str, Any]], requested_skus: tuple[str, ...]
) -> list[dict[str, Any]]:
    """Keep only rows whose normalized SKU was explicitly requested."""
    if not requested_skus:
        return rows
    wanted = set(requested_skus)
    return [
        row for row in rows if normalize_sku(row.get("normalized_sku") or row.get("sku")) in wanted
    ]


def _seller_date_filter(*, seller_id: str, date_from: Any, date_to: Any) -> dict[str, Any]:
    return {
        "seller_id": seller_id,
        "$or": [
            {"date_created": {"$gte": date_from, "$lte": date_to}},
            {
                "date_created": {
                    "$gte": _iso_date_lower_bound(date_from),
                    "$lte": _iso_date_upper_bound(date_to),
                }
            },
        ],
    }


def _seller_exact_interval_filter(
    *,
    seller_id: str,
    date_from: Any,
    date_to: Any,
    item_ids: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    filter_spec: dict[str, Any] = {
        "seller_id": seller_id,
        "date_from": date_from,
        "date_to": date_to,
    }
    if item_ids:
        filter_spec["item_id"] = {"$in": [str(item_id) for item_id in item_ids]}
    return filter_spec


def _iso_date_lower_bound(value: Any) -> str:
    parsed = _as_utc_datetime(value)
    return parsed.date().isoformat()


def _iso_date_upper_bound(value: Any) -> str:
    parsed = _as_utc_datetime(value)
    return f"{parsed.date().isoformat()}T99:99:99"


def _as_utc_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        msg = "expected datetime or ISO datetime string"
        raise TypeError(msg)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
