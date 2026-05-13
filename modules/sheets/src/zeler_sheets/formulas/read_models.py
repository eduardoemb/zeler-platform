from __future__ import annotations

from typing import Any, cast

from zeler_sheets.formulas.dispatcher import FormulaDataUnavailableError
from zeler_sheets.formulas.schemas import FormulaContract

ITEM_FORMULA_ROWS_COLLECTION = "sheets_item_formula_rows"
UNBUILT_BATCH_MARKERS = frozenset({"C", "D", "E"})


class FormulaReadModelRepository:
    def __init__(self, *, db: Any) -> None:
        self._item_formula_rows = db[ITEM_FORMULA_ROWS_COLLECTION]

    async def find_item_formula_rows(
        self,
        *,
        seller_id: str,
        skus: list[str] | tuple[str, ...] | None = None,
        item_ids: list[str] | tuple[str, ...] | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        filter_spec: dict[str, Any] = {"seller_id": seller_id}
        normalized_skus = [_normalize_sku(sku) for sku in skus or [] if _normalize_sku(sku)]
        if normalized_skus:
            filter_spec["normalized_sku"] = {"$in": normalized_skus}
        if item_ids:
            filter_spec["item_id"] = {"$in": list(item_ids)}
        cursor = self._item_formula_rows.find(filter_spec).sort(
            [("normalized_sku", 1), ("item_id", 1)]
        )
        return cast("list[dict[str, Any]]", await cursor.to_list(length=limit))


def require_formula_read_model_available(contract: FormulaContract) -> None:
    batches = set(contract.batch.split("/"))
    if batches & UNBUILT_BATCH_MARKERS:
        raise FormulaDataUnavailableError(contract.name)


def _normalize_sku(sku: str) -> str:
    return str(sku).strip().upper()
