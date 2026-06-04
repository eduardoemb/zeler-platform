from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from zeler_sheets.formulas.dispatcher import FormulaDataUnavailableError
from zeler_sheets.formulas.schemas import FormulaContract
from zeler_sheets.unit_costs import UnitCostLookup, resolve_unit_cost

ITEM_FORMULA_ROWS_COLLECTION = "sheets_item_formula_rows"
ITEM_SKU_INDEX_COLLECTION = "sheets_item_sku_index"
ORDERS_COLLECTION = "orders"
QUESTIONS_COLLECTION = "questions"
SELLER_UNIT_COSTS_COLLECTION = "seller_unit_costs"
SHIPMENTS_COLLECTION = "shipments"
UNBUILT_BATCH_MARKERS = frozenset({"C", "D", "E"})
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


class FormulaReadModelRepository:
    def __init__(self, *, db: Any) -> None:
        self._item_formula_rows = db[ITEM_FORMULA_ROWS_COLLECTION]
        self._item_sku_index = db[ITEM_SKU_INDEX_COLLECTION]
        self._orders = db[ORDERS_COLLECTION]
        self._questions = db[QUESTIONS_COLLECTION]
        self._seller_unit_costs = db[SELLER_UNIT_COSTS_COLLECTION]
        self._shipments = db[SHIPMENTS_COLLECTION]

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
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        filter_spec = _seller_item_filter(
            seller_id=seller_id,
            skus=skus,
            item_ids=item_ids,
            inventory_ids=inventory_ids,
        )
        cursor = self._item_formula_rows.find(filter_spec).sort(
            [("normalized_sku", 1), ("item_id", 1)]
        )
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
