from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from zeler_sheets.formulas.dispatcher import (
    FormulaExecutionContext,
    FormulaExecutionResult,
    FormulaHandler,
)
from zeler_sheets.formulas.read_models import FormulaReadModelRepository, normalize_sku

CORE_FORMULA_NAMES = frozenset(
    {
        "SHEETSELLER_SKU",
        "SHEETSELLER_ID",
        "SHEETSELLER_STOCK",
        "SHEETSELLER_PRECIO",
    }
)


def build_core_formula_handlers(
    repository: FormulaReadModelRepository,
) -> dict[str, FormulaHandler]:
    handlers = CoreFormulaHandlers(repository)
    return {
        "SHEETSELLER_SKU": handlers.sheetseller_sku,
        "SHEETSELLER_ID": handlers.sheetseller_id,
        "SHEETSELLER_STOCK": handlers.sheetseller_stock,
        "SHEETSELLER_PRECIO": handlers.sheetseller_precio,
    }


class CoreFormulaHandlers:
    def __init__(self, repository: FormulaReadModelRepository) -> None:
        self._repository = repository

    async def sheetseller_sku(self, context: FormulaExecutionContext) -> FormulaExecutionResult:
        requested_skus = _normalize_sku_argument(context.args.get("skus", "todos"))
        rows = await self._repository.find_sku_index_rows(
            seller_id=context.seller_id,
            skus=requested_skus if requested_skus is not None else None,
        )
        ordered_rows = _order_rows_by_requested_skus(rows, requested_skus)
        values: list[list[Any]] = []
        seen: set[str] = set()
        for row in ordered_rows:
            normalized = normalize_sku(row.get("normalized_sku", ""))
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            values.append([row.get("sku") or normalized])
        return FormulaExecutionResult(
            values=values,
            meta={"partial_misses": _partial_misses(requested_skus, seen)},
        )

    async def sheetseller_id(self, context: FormulaExecutionContext) -> FormulaExecutionResult:
        requested_skus = _normalize_sku_argument(context.args.get("skus", "todos"))
        rows = await self._repository.find_sku_index_rows(
            seller_id=context.seller_id,
            skus=requested_skus if requested_skus is not None else None,
        )
        ordered_rows = _order_rows_by_requested_skus(rows, requested_skus)
        matched_skus = {normalize_sku(row.get("normalized_sku", "")) for row in ordered_rows}
        return FormulaExecutionResult(
            values=[[row.get("item_id") or ""] for row in ordered_rows if row.get("item_id")],
            meta={"partial_misses": _partial_misses(requested_skus, matched_skus)},
        )

    async def sheetseller_stock(self, context: FormulaExecutionContext) -> FormulaExecutionResult:
        return await self._lookup_current_field(context, field="available_quantity")

    async def sheetseller_precio(self, context: FormulaExecutionContext) -> FormulaExecutionResult:
        return await self._lookup_current_field(context, field="base_price")

    async def _lookup_current_field(
        self, context: FormulaExecutionContext, *, field: str
    ) -> FormulaExecutionResult:
        pairs = _lookup_pairs(
            skus=context.args.get("skus"),
            item_ids=context.args.get("id_publicaciones"),
        )
        rows = await self._repository.find_item_formula_rows(
            seller_id=context.seller_id,
            skus=[pair.sku for pair in pairs],
            item_ids=[pair.item_id for pair in pairs],
        )
        rows_by_pair = {
            (normalize_sku(row.get("normalized_sku", "")), str(row.get("item_id", ""))): row
            for row in rows
        }
        values: list[list[Any]] = []
        misses = 0
        for pair in pairs:
            row = rows_by_pair.get((pair.sku, pair.item_id))
            current = row.get("current", {}) if row else {}
            value = current.get(field) if isinstance(current, Mapping) else None
            if value is None:
                misses += 1
                values.append([""])
            else:
                values.append([value])
        return FormulaExecutionResult(values=values, meta={"partial_misses": misses})


class _LookupPair:
    def __init__(self, *, sku: str, item_id: str) -> None:
        self.sku = sku
        self.item_id = item_id


def _lookup_pairs(*, skus: Any, item_ids: Any) -> list[_LookupPair]:
    normalized_skus = _flatten_sheet_values(skus, normalize=normalize_sku)
    normalized_item_ids = _flatten_sheet_values(
        item_ids, normalize=lambda value: str(value).strip()
    )
    if len(normalized_skus) == 1 and len(normalized_item_ids) > 1:
        normalized_skus = normalized_skus * len(normalized_item_ids)
    if len(normalized_item_ids) == 1 and len(normalized_skus) > 1:
        normalized_item_ids = normalized_item_ids * len(normalized_skus)
    return [
        _LookupPair(sku=sku, item_id=item_id)
        for sku, item_id in zip(normalized_skus, normalized_item_ids, strict=False)
        if sku and item_id
    ]


def _normalize_sku_argument(value: Any) -> list[str] | None:
    if isinstance(value, str) and value.strip().casefold() == "todos":
        return None
    return _flatten_sheet_values(value, normalize=normalize_sku)


def _flatten_sheet_values(value: Any, *, normalize: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        normalized = normalize(value)
        return [normalized] if normalized else []
    if isinstance(value, Iterable):
        flattened: list[str] = []
        for item in value:
            if isinstance(item, str) or not isinstance(item, Iterable):
                normalized = normalize(item)
                if normalized:
                    flattened.append(normalized)
            else:
                flattened.extend(_flatten_sheet_values(item, normalize=normalize))
        return flattened
    normalized = normalize(value)
    return [normalized] if normalized else []


def _order_rows_by_requested_skus(
    rows: list[dict[str, Any]], requested_skus: list[str] | None
) -> list[dict[str, Any]]:
    sorted_rows = sorted(
        rows,
        key=lambda row: (normalize_sku(row.get("normalized_sku", "")), str(row.get("item_id", ""))),
    )
    if requested_skus is None:
        return sorted_rows

    rows_by_sku: dict[str, list[dict[str, Any]]] = {}
    for row in sorted_rows:
        rows_by_sku.setdefault(normalize_sku(row.get("normalized_sku", "")), []).append(row)

    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()
    for sku in requested_skus:
        if sku in seen:
            continue
        seen.add(sku)
        ordered.extend(rows_by_sku.get(sku, []))
    return ordered


def _partial_misses(requested_skus: list[str] | None, matched_skus: set[str]) -> int:
    if requested_skus is None:
        return 0
    return sum(1 for sku in dict.fromkeys(requested_skus) if sku not in matched_skus)
