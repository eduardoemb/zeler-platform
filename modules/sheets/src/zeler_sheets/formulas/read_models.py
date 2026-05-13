from __future__ import annotations

from typing import Any, cast

from zeler_sheets.formulas.dispatcher import FormulaDataUnavailableError
from zeler_sheets.formulas.schemas import FormulaContract

ITEM_FORMULA_ROWS_COLLECTION = "sheets_item_formula_rows"
ITEM_SKU_INDEX_COLLECTION = "sheets_item_sku_index"
UNBUILT_BATCH_MARKERS = frozenset({"C", "D", "E"})


class FormulaReadModelRepository:
    def __init__(self, *, db: Any) -> None:
        self._item_formula_rows = db[ITEM_FORMULA_ROWS_COLLECTION]
        self._item_sku_index = db[ITEM_SKU_INDEX_COLLECTION]

    async def find_sku_index_rows(
        self,
        *,
        seller_id: str,
        skus: list[str] | tuple[str, ...] | None = None,
        item_ids: list[str] | tuple[str, ...] | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        filter_spec = _seller_item_filter(seller_id=seller_id, skus=skus, item_ids=item_ids)
        cursor = self._item_sku_index.find(filter_spec).sort(
            [("normalized_sku", 1), ("item_id", 1)]
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
    if inventory_ids:
        filter_spec["inventory_id"] = {"$in": [str(inventory_id) for inventory_id in inventory_ids]}
    return filter_spec
