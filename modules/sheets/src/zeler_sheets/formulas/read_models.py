from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, DecimalException
from typing import Any, cast

from zeler_sheets.formulas.dispatcher import FormulaDataUnavailableError
from zeler_sheets.formulas.schemas import FormulaContract
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
    "real_shipping_cost.seller_cost": 1,
}


class FormulaReadModelRepository:
    def __init__(self, *, db: Any) -> None:
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
        limit: int = 500,
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
        limit: int | None = 500,
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

    async def find_orders(
        self,
        *,
        seller_id: str,
        date_from: Any,
        date_to: Any,
        status: str | None = None,
        limit: int = 1000,
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
        limit: int = 1000,
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

    async def find_catalog_buybox_snapshots(
        self,
        *,
        seller_id: str,
        limit: int = 1000,
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
        limit: int = 1000,
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
        limit: int = 1000,
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
        limit: int = 1000,
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
        limit: int = 1000,
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
        limit: int = 1000,
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
        normalized_shipment_ids = list(
            dict.fromkeys(
                str(shipment_id).strip() for shipment_id in shipment_ids if str(shipment_id).strip()
            )
        )
        if not normalized_shipment_ids:
            return {}
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
            if shipment_id and isinstance(receiver_address, dict):
                snapshots[shipment_id] = receiver_address
        return snapshots

    async def find_shipment_real_shipping_costs(
        self,
        *,
        seller_id: str,
        shipment_ids: list[str] | tuple[str, ...],
        limit: int = 1000,
    ) -> dict[str, Decimal]:
        normalized_shipment_ids = list(
            dict.fromkeys(
                str(shipment_id).strip() for shipment_id in shipment_ids if str(shipment_id).strip()
            )
        )
        if not normalized_shipment_ids:
            return {}
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
        return costs

    async def find_questions(
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
            raise FormulaDataUnavailableError(formula, QUESTIONS_FRESHNESS_UNAVAILABLE_REASON)

    async def require_read_model_productive(
        self,
        *,
        seller_id: str,
        read_model: str,
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
        if not _read_model_freshness_marker_covers(marker, date_to=date_to):
            reason = (
                f"Read model {read_model} has not passed freshness/reconciliation "
                "for the requested range."
            )
            raise FormulaDataUnavailableError(formula, reason)

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
            coverage_basis="legacy_imported",
            exact_interval=read_model in INTERVAL_AGGREGATE_READ_MODELS,
        ):
            reason = (
                f"Read model {read_model} has not passed freshness/reconciliation "
                "for the requested range."
            )
            raise FormulaDataUnavailableError(formula, reason)

    async def find_unit_costs(
        self,
        *,
        seller_id: str,
        lookups: list[UnitCostLookup] | tuple[UnitCostLookup, ...],
        limit: int = 1000,
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


def read_model_freshness_id(seller_id: str, read_model: str) -> str:
    return f"{seller_id}:{read_model}"


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
) -> bool:
    if not isinstance(marker, dict):
        return False
    if str(marker.get("state") or "").strip().casefold() != RECONCILED_READ_MODEL_STATE:
        return False
    if (
        coverage_basis is not None
        and str(marker.get("coverage_basis") or "").strip() != coverage_basis
    ):
        return False
    requested_from = _safe_utc_datetime(date_from)
    requested_until = _safe_utc_datetime(date_to)
    coverage_start = _first_utc_datetime(
        marker.get("date_from"),
        marker.get("last_event_synced_at"),
    )
    reconciled_until = _safe_utc_datetime(marker.get("reconciled_until"))
    if (
        requested_from is None
        or requested_until is None
        or coverage_start is None
        or reconciled_until is None
        or reconciled_until < coverage_start
    ):
        return False
    if exact_interval:
        return coverage_start == requested_from and reconciled_until == requested_until
    return coverage_start <= requested_from and reconciled_until >= requested_until


def _read_model_freshness_marker_covers(marker: Any, *, date_to: Any) -> bool:
    if not isinstance(marker, dict):
        return False
    state = str(marker.get("state") or "").strip().casefold()
    if state not in PRODUCTIVE_READ_MODEL_STATES:
        return False
    requested_until = _safe_utc_datetime(date_to)
    if requested_until is None:
        return False
    fresh_until = _latest_utc_datetime(
        marker.get("fresh_until"),
        marker.get("reconciled_until"),
    )
    return fresh_until is not None and fresh_until >= requested_until


def _latest_utc_datetime(*values: Any) -> datetime | None:
    parsed = [
        date_value for value in values if (date_value := _safe_utc_datetime(value)) is not None
    ]
    return max(parsed) if parsed else None


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
