from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from zeler_sheets.formulas.dispatcher import FormulaDataUnavailableError
from zeler_sheets.formulas.schemas import FormulaContract

ITEM_FORMULA_ROWS_COLLECTION = "sheets_item_formula_rows"
ITEM_SKU_INDEX_COLLECTION = "sheets_item_sku_index"
ORDERS_COLLECTION = "orders"
QUESTIONS_COLLECTION = "questions"
UNBUILT_BATCH_MARKERS = frozenset({"C", "D", "E"})


class FormulaReadModelRepository:
    def __init__(self, *, db: Any) -> None:
        self._item_formula_rows = db[ITEM_FORMULA_ROWS_COLLECTION]
        self._item_sku_index = db[ITEM_SKU_INDEX_COLLECTION]
        self._orders = db[ORDERS_COLLECTION]
        self._questions = db[QUESTIONS_COLLECTION]

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


def require_formula_read_model_available(contract: FormulaContract) -> None:
    batches = set(contract.batch.split("/"))
    if batches & UNBUILT_BATCH_MARKERS:
        raise FormulaDataUnavailableError(contract.name)


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
