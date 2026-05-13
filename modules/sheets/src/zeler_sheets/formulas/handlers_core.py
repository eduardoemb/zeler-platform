from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
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
        "SHEETSELLER_PUBLICACIONES",
        "SHEETSELLER_ID",
        "SHEETSELLER_STOCK",
        "SHEETSELLER_TITULO",
        "SHEETSELLER_URL",
        "SHEETSELLER_PRECIO",
        "SHEETSELLER_IDSTOCK",
        "SHEETSELLER_STATUS",
        "SHEETSELLER_CODIGOML",
        "SHEETSELLER_CODIGOML2SKUID",
        "SHEETSELLER_DIASPUBLICADA",
        "SHEETSELLER_IMAGENES",
        "SHEETSELLER_CATEGORIAS",
    }
)


def build_core_formula_handlers(
    repository: FormulaReadModelRepository,
    *,
    now_fn: Callable[[], datetime] | None = None,
) -> dict[str, FormulaHandler]:
    handlers = CoreFormulaHandlers(repository, now_fn=now_fn)
    return {
        "SHEETSELLER_SKU": handlers.sheetseller_sku,
        "SHEETSELLER_PUBLICACIONES": handlers.sheetseller_publicaciones,
        "SHEETSELLER_ID": handlers.sheetseller_id,
        "SHEETSELLER_STOCK": handlers.sheetseller_stock,
        "SHEETSELLER_TITULO": handlers.sheetseller_titulo,
        "SHEETSELLER_URL": handlers.sheetseller_url,
        "SHEETSELLER_PRECIO": handlers.sheetseller_precio,
        "SHEETSELLER_IDSTOCK": handlers.sheetseller_idstock,
        "SHEETSELLER_STATUS": handlers.sheetseller_status,
        "SHEETSELLER_CODIGOML": handlers.sheetseller_codigoml,
        "SHEETSELLER_CODIGOML2SKUID": handlers.sheetseller_codigoml2skuid,
        "SHEETSELLER_DIASPUBLICADA": handlers.sheetseller_diaspublicada,
        "SHEETSELLER_IMAGENES": handlers.sheetseller_imagenes,
        "SHEETSELLER_CATEGORIAS": handlers.sheetseller_categorias,
    }


class CoreFormulaHandlers:
    def __init__(
        self,
        repository: FormulaReadModelRepository,
        *,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._now_fn = now_fn or (lambda: datetime.now(UTC))

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

    async def sheetseller_publicaciones(
        self, context: FormulaExecutionContext
    ) -> FormulaExecutionResult:
        requested_skus = _normalize_sku_argument(context.args.get("skus", "todos"))
        rows = await self._repository.find_item_formula_rows(
            seller_id=context.seller_id,
            skus=requested_skus,
        )
        ordered_rows = _order_rows_by_requested_skus(rows, requested_skus)
        values: list[list[Any]] = _header_row(
            context.args.get("encabezados"),
            ["SKU", "ID Publicación", "Título", "Status", "Stock", "Precio", "URL"],
        )
        matched_skus: set[str] = set()
        for row in ordered_rows:
            item_id = row.get("item_id") or ""
            if not item_id:
                continue
            current = row.get("current", {})
            current_values = current if isinstance(current, Mapping) else {}
            values.append(
                [
                    row.get("sku") or row.get("normalized_sku") or "",
                    item_id,
                    current_values.get("title") or "",
                    current_values.get("status") or "",
                    _blank_if_none(current_values.get("available_quantity")),
                    _blank_if_none(current_values.get("base_price")),
                    current_values.get("permalink") or "",
                ]
            )
            matched_skus.add(normalize_sku(row.get("normalized_sku", "")))
        return FormulaExecutionResult(
            values=values,
            meta={
                "partial_misses": _partial_misses(requested_skus, matched_skus),
                "columns": "minimal_current_item",
            },
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

    async def sheetseller_titulo(self, context: FormulaExecutionContext) -> FormulaExecutionResult:
        return await self._lookup_current_field_by_item_id(context, field="title")

    async def sheetseller_url(self, context: FormulaExecutionContext) -> FormulaExecutionResult:
        return await self._lookup_current_field(context, field="permalink")

    async def sheetseller_precio(self, context: FormulaExecutionContext) -> FormulaExecutionResult:
        return await self._lookup_current_field(context, field="base_price")

    async def sheetseller_idstock(self, context: FormulaExecutionContext) -> FormulaExecutionResult:
        requested_skus = _normalize_sku_argument(context.args.get("skus"))
        rows = await self._repository.find_item_formula_rows(
            seller_id=context.seller_id,
            skus=requested_skus,
        )
        ordered_rows = _order_rows_by_requested_skus(rows, requested_skus)
        values: list[list[Any]] = _header_row(
            context.args.get("encabezados"), ["SKU", "ID Publicación", "Stock"]
        )
        matched_skus: set[str] = set()
        for row in ordered_rows:
            sku = row.get("sku") or row.get("normalized_sku") or ""
            item_id = row.get("item_id") or ""
            if not item_id:
                continue
            current = row.get("current", {})
            stock = current.get("available_quantity") if isinstance(current, Mapping) else None
            values.append([sku, item_id, "" if stock is None else stock])
            matched_skus.add(normalize_sku(row.get("normalized_sku", "")))
        return FormulaExecutionResult(
            values=values,
            meta={"partial_misses": _partial_misses(requested_skus, matched_skus)},
        )

    async def sheetseller_status(self, context: FormulaExecutionContext) -> FormulaExecutionResult:
        return await self._lookup_current_field_by_item_id(context, field="status")

    async def sheetseller_codigoml(
        self, context: FormulaExecutionContext
    ) -> FormulaExecutionResult:
        return await self._lookup_current_field(
            context,
            field="inventory_id",
            row_field_fallback="inventory_id",
        )

    async def sheetseller_codigoml2skuid(
        self, context: FormulaExecutionContext
    ) -> FormulaExecutionResult:
        requested_codes = _normalize_inventory_code_argument(context.args.get("codigo_ml"))
        rows = await self._repository.find_item_formula_rows(
            seller_id=context.seller_id,
            inventory_ids=requested_codes,
        )
        ordered_rows = _order_rows_by_requested_inventory_codes(rows, requested_codes)
        values: list[list[Any]] = _header_row(
            context.args.get("encabezados"), ["Código ML", "ID Publicación", "SKU"]
        )
        matched_codes: set[str] = set()
        for row in ordered_rows:
            inventory_id = str(row.get("inventory_id") or "").strip()
            item_id = row.get("item_id") or ""
            sku = row.get("sku") or row.get("normalized_sku") or ""
            if not inventory_id or not item_id:
                continue
            values.append([inventory_id, item_id, sku])
            matched_codes.add(_normalize_inventory_code(inventory_id))
        return FormulaExecutionResult(
            values=values,
            meta={"partial_misses": _partial_misses(requested_codes, matched_codes)},
        )

    async def sheetseller_diaspublicada(
        self, context: FormulaExecutionContext
    ) -> FormulaExecutionResult:
        item_ids = _normalize_item_id_argument(context.args.get("id_publicaciones"))
        rows = await self._repository.find_item_formula_rows(
            seller_id=context.seller_id,
            item_ids=item_ids,
        )
        rows_by_item_id = {str(row.get("item_id", "")).strip(): row for row in rows}
        today = _as_utc_datetime(self._now_fn()).date()
        values: list[list[Any]] = []
        misses = 0
        for item_id in item_ids:
            row = rows_by_item_id.get(item_id)
            published_at = _published_at(row) if row else None
            if published_at is None:
                misses += 1
                values.append([""])
            else:
                values.append([max((today - published_at.date()).days, 0)])
        return FormulaExecutionResult(values=values, meta={"partial_misses": misses})

    async def sheetseller_imagenes(
        self, context: FormulaExecutionContext
    ) -> FormulaExecutionResult:
        image_variant = _image_variant(context.args.get("imagen"))
        requested_skus = _normalize_sku_argument(context.args.get("skus", "todos"))
        requested_item_ids = _normalize_optional_item_ids(
            context.args.get("id_publicaciones", "todos")
        )

        if requested_skus is not None and requested_item_ids is not None:
            return await self._lookup_thumbnail_by_pairs(
                context,
                requested_skus=requested_skus,
                requested_item_ids=requested_item_ids,
                image_variant=image_variant,
            )

        rows = await self._repository.find_item_formula_rows(
            seller_id=context.seller_id,
            skus=requested_skus,
            item_ids=requested_item_ids,
        )
        ordered_rows = _order_image_rows(
            rows,
            requested_skus=requested_skus,
            requested_item_ids=requested_item_ids,
        )
        values = [[_current_value(row, "thumbnail")] for row in ordered_rows]
        return FormulaExecutionResult(
            values=values,
            meta={
                "partial_misses": _image_partial_misses(
                    requested_skus=requested_skus,
                    requested_item_ids=requested_item_ids,
                    rows=ordered_rows,
                ),
                "columns": "thumbnail_url",
                "image_variant": image_variant,
            },
        )

    async def sheetseller_categorias(
        self, context: FormulaExecutionContext
    ) -> FormulaExecutionResult:
        return await self._lookup_current_field_by_item_id(context, field="category_id")

    async def _lookup_current_field(
        self,
        context: FormulaExecutionContext,
        *,
        field: str,
        row_field_fallback: str | None = None,
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
            if value is None and row_field_fallback is not None and row is not None:
                value = row.get(row_field_fallback)
            if value is None:
                misses += 1
                values.append([""])
            else:
                values.append([value])
        return FormulaExecutionResult(values=values, meta={"partial_misses": misses})

    async def _lookup_current_field_by_item_id(
        self, context: FormulaExecutionContext, *, field: str
    ) -> FormulaExecutionResult:
        item_ids = _normalize_item_id_argument(context.args.get("id_publicaciones"))
        rows = await self._repository.find_item_formula_rows(
            seller_id=context.seller_id,
            item_ids=item_ids,
        )
        rows_by_item_id = {str(row.get("item_id", "")).strip(): row for row in rows}
        values: list[list[Any]] = []
        misses = 0
        for item_id in item_ids:
            row = rows_by_item_id.get(item_id)
            current = row.get("current", {}) if row else {}
            value = current.get(field) if isinstance(current, Mapping) else None
            if value is None:
                misses += 1
                values.append([""])
            else:
                values.append([value])
        return FormulaExecutionResult(values=values, meta={"partial_misses": misses})

    async def _lookup_thumbnail_by_pairs(
        self,
        context: FormulaExecutionContext,
        *,
        requested_skus: list[str],
        requested_item_ids: list[str],
        image_variant: str,
    ) -> FormulaExecutionResult:
        pairs = _lookup_pairs(skus=requested_skus, item_ids=requested_item_ids)
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
            value = _current_value(row, "thumbnail") if row is not None else ""
            if value == "":
                misses += 1
            values.append([value])
        return FormulaExecutionResult(
            values=values,
            meta={
                "partial_misses": misses,
                "columns": "thumbnail_url",
                "image_variant": image_variant,
            },
        )


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


def _normalize_item_id_argument(value: Any) -> list[str]:
    return _flatten_sheet_values(value, normalize=lambda item_id: str(item_id).strip())


def _normalize_optional_item_ids(value: Any) -> list[str] | None:
    if isinstance(value, str) and value.strip().casefold() == "todos":
        return None
    return _normalize_item_id_argument(value)


def _normalize_inventory_code_argument(value: Any) -> list[str]:
    return _flatten_sheet_values(value, normalize=_normalize_inventory_code)


def _normalize_inventory_code(value: Any) -> str:
    return str(value).strip().upper()


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


def _order_rows_by_requested_inventory_codes(
    rows: list[dict[str, Any]], requested_codes: list[str]
) -> list[dict[str, Any]]:
    sorted_rows = sorted(
        rows,
        key=lambda row: (
            _normalize_inventory_code(row.get("inventory_id", "")),
            str(row.get("item_id", "")),
        ),
    )
    rows_by_code: dict[str, list[dict[str, Any]]] = {}
    for row in sorted_rows:
        rows_by_code.setdefault(_normalize_inventory_code(row.get("inventory_id", "")), []).append(
            row
        )

    ordered: list[dict[str, Any]] = []
    for code in dict.fromkeys(requested_codes):
        ordered.extend(rows_by_code.get(code, []))
    return ordered


def _order_rows_by_requested_item_ids(
    rows: list[dict[str, Any]], requested_item_ids: list[str]
) -> list[dict[str, Any]]:
    sorted_rows = sorted(
        rows,
        key=lambda row: (str(row.get("item_id", "")), normalize_sku(row.get("normalized_sku", ""))),
    )
    rows_by_item_id: dict[str, list[dict[str, Any]]] = {}
    for row in sorted_rows:
        rows_by_item_id.setdefault(str(row.get("item_id", "")).strip(), []).append(row)

    ordered: list[dict[str, Any]] = []
    for item_id in dict.fromkeys(requested_item_ids):
        ordered.extend(rows_by_item_id.get(item_id, []))
    return ordered


def _order_image_rows(
    rows: list[dict[str, Any]],
    *,
    requested_skus: list[str] | None,
    requested_item_ids: list[str] | None,
) -> list[dict[str, Any]]:
    if requested_item_ids is not None:
        return _order_rows_by_requested_item_ids(rows, requested_item_ids)
    return _order_rows_by_requested_skus(rows, requested_skus)


def _partial_misses(requested_skus: list[str] | None, matched_skus: set[str]) -> int:
    if requested_skus is None:
        return 0
    return sum(1 for sku in dict.fromkeys(requested_skus) if sku not in matched_skus)


def _image_partial_misses(
    *,
    requested_skus: list[str] | None,
    requested_item_ids: list[str] | None,
    rows: list[dict[str, Any]],
) -> int:
    if requested_item_ids is not None:
        matched_item_ids = {str(row.get("item_id", "")).strip() for row in rows}
        return sum(
            1 for item_id in dict.fromkeys(requested_item_ids) if item_id not in matched_item_ids
        )
    if requested_skus is not None:
        matched_skus = {normalize_sku(row.get("normalized_sku", "")) for row in rows}
        return _partial_misses(requested_skus, matched_skus)
    return 0


def _header_row(value: Any, headers: list[str]) -> list[list[Any]]:
    if str(value or "").strip().casefold() in {"si", "sí", "true", "1", "yes"}:
        return [headers]
    return []


def _blank_if_none(value: Any) -> Any:
    return "" if value is None else value


def _current_value(row: Mapping[str, Any], field: str) -> Any:
    current = row.get("current", {})
    if not isinstance(current, Mapping):
        return ""
    return _blank_if_none(current.get(field))


def _image_variant(value: Any) -> str:
    variant = str(value or "principal").strip().casefold()
    return variant or "principal"


def _published_at(row: Mapping[str, Any]) -> datetime | None:
    current = row.get("current", {})
    value = current.get("date_created") if isinstance(current, Mapping) else None
    if value is None:
        value = row.get("date_created") or row.get("created_at")
    if value is None:
        return None
    try:
        return _as_utc_datetime(value)
    except (TypeError, ValueError):
        return None


def _as_utc_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise TypeError("expected datetime or ISO datetime string")
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
