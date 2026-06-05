from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from bson.decimal128 import Decimal128

from zeler_sheets.formulas.dispatcher import (
    FormulaExecutionContext,
    FormulaExecutionResult,
    FormulaHandler,
)
from zeler_sheets.formulas.output_normalization import NA_VALUE, normalize_response_rows
from zeler_sheets.formulas.read_models import FormulaReadModelRepository, normalize_sku

CORE_FORMULA_NAMES = frozenset(
    {
        "ZELERDATA_SKU",
        "ZELERDATA_PUBLICACIONES",
        "ZELERDATA_ID",
        "ZELERDATA_STOCK",
        "ZELERDATA_TITULO",
        "ZELERDATA_URL",
        "ZELERDATA_PRECIO",
        "ZELERDATA_IDSTOCK",
        "ZELERDATA_STATUS",
        "ZELERDATA_PAUSADAS",
        "ZELERDATA_CODIGOML",
        "ZELERDATA_CODIGOML2SKUID",
        "ZELERDATA_DIASPUBLICADA",
        "ZELERDATA_DASHBOARD",
        "ZELERDATA_DASHBOARDSINCATALOGO",
        "ZELERDATA_COMISION",
        "ZELERDATA_IMAGENES",
        "ZELERDATA_CATEGORIAS",
    }
)

DASHBOARD_WINDOW_DAYS = (7, 15, 30, 60, 90)
LISTING_PRICE_SOURCE = "/sites/{site}/listing_prices"

DASHBOARD_LEGACY_HEADERS = [
    "ID Publicación",
    "Título",
    "SKU",
    "Stock Actual",
    "Precio",
    "Logística",
    "URL",
    "Tipo De Publicación",
    "Status",
    "Código ML",
    "Días Pausada",
    "Ventas (7 días)",
    "Ventas (15 días)",
    "Ventas (30 días)",
    "Ventas (60 días)",
    "Ventas (90 días)",
    "Envió A Cargo De",
    "Costo De Envío",
    "% Comisión",
    "Comisión",
    "Costo Por Unidad",
    "Tiene Catálogo",
]

PUBLICACIONES_LEGACY_HEADERS = [
    "ID Publicación",
    "Título",
    "SKU",
    "Stock Actual",
    "Precio",
    "Logística",
    "URL",
    "Tipo De Publicación",
    "Status",
    "Código ML",
    "ID Inventario",
    "Tiempo En Pausa",
]

COMISION_LEGACY_HEADERS = ["ID Publicación", "% Comisión", "Comisión", "Costo De Envío"]


def build_core_formula_handlers(
    repository: FormulaReadModelRepository,
    *,
    now_fn: Callable[[], datetime] | None = None,
) -> dict[str, FormulaHandler]:
    handlers = CoreFormulaHandlers(repository, now_fn=now_fn)
    return {
        "ZELERDATA_SKU": handlers.sheetseller_sku,
        "ZELERDATA_PUBLICACIONES": handlers.sheetseller_publicaciones,
        "ZELERDATA_ID": handlers.sheetseller_id,
        "ZELERDATA_STOCK": handlers.sheetseller_stock,
        "ZELERDATA_TITULO": handlers.sheetseller_titulo,
        "ZELERDATA_URL": handlers.sheetseller_url,
        "ZELERDATA_PRECIO": handlers.sheetseller_precio,
        "ZELERDATA_IDSTOCK": handlers.sheetseller_idstock,
        "ZELERDATA_STATUS": handlers.sheetseller_status,
        "ZELERDATA_PAUSADAS": handlers.sheetseller_pausadas,
        "ZELERDATA_CODIGOML": handlers.sheetseller_codigoml,
        "ZELERDATA_CODIGOML2SKUID": handlers.sheetseller_codigoml2skuid,
        "ZELERDATA_DIASPUBLICADA": handlers.sheetseller_diaspublicada,
        "ZELERDATA_DASHBOARD": handlers.sheetseller_dashboard,
        "ZELERDATA_DASHBOARDSINCATALOGO": handlers.sheetseller_dashboard_sin_catalogo,
        "ZELERDATA_COMISION": handlers.sheetseller_comision,
        "ZELERDATA_IMAGENES": handlers.sheetseller_imagenes,
        "ZELERDATA_CATEGORIAS": handlers.sheetseller_categorias,
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
            PUBLICACIONES_LEGACY_HEADERS,
        )
        header_rows = len(values)
        matched_skus: set[str] = set()
        today = _as_utc_datetime(self._now_fn()).date()
        for row in ordered_rows:
            item_id = row.get("item_id") or ""
            if not item_id:
                continue
            values.append(_publicaciones_row(row, today=today))
            matched_skus.add(normalize_sku(row.get("normalized_sku", "")))
        return FormulaExecutionResult(
            values=normalize_response_rows(values, header_rows=header_rows),
            meta={
                "partial_misses": _partial_misses(requested_skus, matched_skus),
                "columns": "legacy_publications",
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
            context.args.get("encabezados"), ["ID Publicación", "Stock"]
        )
        matched_skus: set[str] = set()
        for row in ordered_rows:
            item_id = row.get("item_id") or ""
            if not item_id:
                continue
            current = row.get("current", {})
            stock = current.get("available_quantity") if isinstance(current, Mapping) else None
            values.append([item_id, "" if stock is None else stock])
            matched_skus.add(normalize_sku(row.get("normalized_sku", "")))
        return FormulaExecutionResult(
            values=values,
            meta={"partial_misses": _partial_misses(requested_skus, matched_skus)},
        )

    async def sheetseller_status(self, context: FormulaExecutionContext) -> FormulaExecutionResult:
        return await self._lookup_current_field_by_item_id(context, field="status")

    async def sheetseller_pausadas(
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
            paused_days = _paused_days(rows_by_item_id.get(item_id), today=today)
            if paused_days is None:
                misses += 1
                values.append([NA_VALUE])
            else:
                values.append([paused_days])
        return FormulaExecutionResult(values=values, meta={"partial_misses": misses})

    async def sheetseller_codigoml(
        self, context: FormulaExecutionContext
    ) -> FormulaExecutionResult:
        return await self._lookup_current_field(
            context,
            field="inventory_id",
            row_field_fallback="inventory_id",
            missing_value=NA_VALUE,
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
            context.args.get("encabezados"), ["ID Publicación", "SKU"]
        )
        matched_codes: set[str] = set()
        for row in ordered_rows:
            inventory_id = str(row.get("inventory_id") or "").strip()
            item_id = row.get("item_id") or ""
            sku = row.get("sku") or row.get("normalized_sku") or ""
            if not inventory_id or not item_id:
                continue
            values.append([item_id, sku])
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

    async def sheetseller_dashboard(
        self, context: FormulaExecutionContext
    ) -> FormulaExecutionResult:
        return await self._dashboard_table(context, exclude_catalog=False)

    async def sheetseller_dashboard_sin_catalogo(
        self, context: FormulaExecutionContext
    ) -> FormulaExecutionResult:
        return await self._dashboard_table(context, exclude_catalog=True)

    async def sheetseller_comision(
        self, context: FormulaExecutionContext
    ) -> FormulaExecutionResult:
        requested_item_ids = _normalize_item_id_argument(context.args.get("id_publicaciones"))
        rows = await self._repository.find_item_formula_rows(
            seller_id=context.seller_id,
            item_ids=requested_item_ids,
        )
        ordered_rows = _order_rows_by_requested_item_ids(rows, requested_item_ids)
        values: list[list[Any]] = _header_row(
            context.args.get("encabezados"), COMISION_LEGACY_HEADERS
        )
        header_rows = len(values)
        matched_item_ids: set[str] = set()
        for row in ordered_rows:
            item_id = str(row.get("item_id") or "").strip()
            if not item_id:
                continue
            values.append(_comision_row(row))
            matched_item_ids.add(item_id)
        return FormulaExecutionResult(
            values=normalize_response_rows(values, header_rows=header_rows),
            meta={
                "partial_misses": _item_id_partial_misses(requested_item_ids, matched_item_ids),
                "columns": "legacy_commission",
            },
        )

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
        missing_value: str = "",
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
                values.append([missing_value])
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

    async def _dashboard_table(
        self, context: FormulaExecutionContext, *, exclude_catalog: bool
    ) -> FormulaExecutionResult:
        requested_skus = _normalize_sku_argument(context.args.get("skus", "todos"))
        rows = await self._repository.find_item_formula_rows(
            seller_id=context.seller_id,
            skus=requested_skus,
        )
        ordered_rows = _order_rows_by_requested_skus(rows, requested_skus)
        visible_rows = [
            row for row in ordered_rows if not exclude_catalog or not _has_catalog_product(row)
        ]
        sales_windows = await self._dashboard_sales_windows(context.seller_id, visible_rows)
        headers = list(DASHBOARD_LEGACY_HEADERS)
        tipo_precio = str(context.args.get("tipo_precio") or "").strip().casefold()
        include_promo = tipo_precio == "todos"
        use_promo_as_selected_price = tipo_precio == "promo"
        if include_promo:
            headers.append("Precio Promo")
        values: list[list[Any]] = _header_row(context.args.get("encabezados"), headers)
        header_rows = len(values)
        today = _as_utc_datetime(self._now_fn()).date()
        for row in visible_rows:
            item_id = row.get("item_id") or ""
            if not item_id:
                continue
            values.append(
                _dashboard_row(
                    row,
                    sales_windows=sales_windows,
                    include_promo=include_promo,
                    today=today,
                    use_promo_as_selected_price=use_promo_as_selected_price,
                )
            )

        matched_skus = {normalize_sku(row.get("normalized_sku", "")) for row in ordered_rows}
        meta: dict[str, Any] = {
            "partial_misses": _partial_misses(requested_skus, matched_skus),
            "columns": "legacy_dashboard",
        }
        if exclude_catalog:
            meta["excluded_catalog_rows"] = len(ordered_rows) - len(visible_rows)
        return FormulaExecutionResult(
            values=normalize_response_rows(values, header_rows=header_rows), meta=meta
        )

    async def _dashboard_sales_windows(
        self, seller_id: str, rows: Iterable[Mapping[str, Any]]
    ) -> dict[int, dict[tuple[str, str], int]]:
        row_pairs = {
            (
                normalize_sku(row.get("normalized_sku") or row.get("sku")),
                str(row.get("item_id") or ""),
            )
            for row in rows
            if normalize_sku(row.get("normalized_sku") or row.get("sku")) and row.get("item_id")
        }
        if not row_pairs:
            return {days: {} for days in DASHBOARD_WINDOW_DAYS}
        now = _as_utc_datetime(self._now_fn())
        orders = await self._repository.find_orders(
            seller_id=seller_id,
            date_from=_last_days_start(now, 90),
            date_to=_day_end(now),
        )
        sku_resolver = await _dashboard_sku_resolver_for_orders(
            repository=self._repository,
            seller_id=seller_id,
            orders=orders,
        )
        windows: dict[int, dict[tuple[str, str], int]] = {
            days: {} for days in DASHBOARD_WINDOW_DAYS
        }
        for order in orders:
            created = _optional_datetime(order.get("date_created"))
            if created is None:
                continue
            for item in _order_items(order):
                sku = _dashboard_order_item_sku(item, sku_resolver=sku_resolver)
                item_id = _item_id(item)
                key = (sku, item_id)
                if key not in row_pairs:
                    continue
                quantity = _item_quantity(item)
                for days in windows:
                    if _last_days_start(now, days) <= created <= _day_end(now):
                        windows[days][key] = windows[days].get(key, 0) + quantity
        return windows


class _LookupPair:
    def __init__(self, *, sku: str, item_id: str) -> None:
        self.sku = sku
        self.item_id = item_id


class _DashboardSkuResolver:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        rows_by_item_id: dict[str, list[dict[str, Any]]] = {}
        rows_by_item_level: dict[str, list[dict[str, Any]]] = {}
        rows_by_item_variation: dict[tuple[str, str], list[dict[str, Any]]] = {}
        items_with_variation_rows: set[str] = set()
        for row in rows:
            item_id = str(row.get("item_id") or "").strip()
            if item_id:
                rows_by_item_id.setdefault(item_id, []).append(row)
                variation_id = _normalize_variation_id(row.get("variation_id"))
                if variation_id:
                    items_with_variation_rows.add(item_id)
                    rows_by_item_variation.setdefault((item_id, variation_id), []).append(row)
                else:
                    rows_by_item_level.setdefault(item_id, []).append(row)
        self._rows_by_item_id = rows_by_item_id
        self._rows_by_item_level = rows_by_item_level
        self._rows_by_item_variation = rows_by_item_variation
        self._items_with_variation_rows = items_with_variation_rows

    def resolve(self, item_id: str, variation_id: str = "") -> str:
        item_id = str(item_id or "").strip()
        if variation_id:
            variation_rows = self._rows_by_item_variation.get((item_id, variation_id), [])
            if variation_rows:
                return _unique_dashboard_sku(variation_rows)
            if item_id in self._items_with_variation_rows:
                return ""
            return _unique_dashboard_sku(self._rows_by_item_level.get(item_id, []))
        return _unique_dashboard_sku(self._rows_by_item_id.get(item_id, []))


def _unique_dashboard_sku(rows: Iterable[Mapping[str, Any]]) -> str:
    normalized_skus = {
        normalize_sku(row.get("normalized_sku") or row.get("sku"))
        for row in rows
        if normalize_sku(row.get("normalized_sku") or row.get("sku"))
    }
    if len(normalized_skus) != 1:
        return ""
    return next(iter(normalized_skus))


async def _dashboard_sku_resolver_for_orders(
    *,
    repository: FormulaReadModelRepository,
    seller_id: str,
    orders: list[dict[str, Any]],
) -> _DashboardSkuResolver:
    item_ids = list(
        dict.fromkeys(
            item_id
            for order in orders
            for item in _order_items(order)
            if (item_id := _item_id(item))
        )
    )
    if not item_ids:
        return _DashboardSkuResolver([])
    rows = await repository.find_sku_index_rows(
        seller_id=seller_id,
        item_ids=item_ids,
        limit=max(500, len(item_ids) * 10),
    )
    return _DashboardSkuResolver(rows)


def _dashboard_order_item_sku(
    item: Mapping[str, Any], *, sku_resolver: _DashboardSkuResolver
) -> str:
    direct_sku = normalize_sku(_item_sku(item))
    if direct_sku:
        return direct_sku
    return sku_resolver.resolve(_item_id(item), _item_variation_id(item))


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


def _item_id_partial_misses(requested_item_ids: list[str], matched_item_ids: set[str]) -> int:
    return sum(
        1 for item_id in dict.fromkeys(requested_item_ids) if item_id not in matched_item_ids
    )


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
    if _headers_requested(value):
        return [headers]
    return []


def _headers_requested(value: Any) -> bool:
    return str(value or "").strip().casefold() in {
        "si",
        "sí",
        "verdadero",
        "true",
        "1",
        "yes",
    }


def _blank_if_none(value: Any) -> Any:
    return "" if value is None else value


def _current_value(row: Mapping[str, Any], field: str) -> Any:
    current = row.get("current", {})
    if not isinstance(current, Mapping):
        return ""
    return _blank_if_none(current.get(field))


def _inventory_code(row: Mapping[str, Any]) -> Any:
    return row.get("inventory_id") or _current_value(row, "inventory_id")


def _listing_type_id(row: Mapping[str, Any]) -> Any:
    value = _current_value(row, "listing_type_id")
    return value or NA_VALUE


def _publicaciones_row(row: Mapping[str, Any], *, today: date) -> list[Any]:
    inventory_code = _inventory_code(row)
    paused_days = _paused_days(row, today=today)
    return [
        row.get("item_id") or "",
        _current_value(row, "title"),
        row.get("sku") or row.get("normalized_sku") or "",
        _current_value(row, "available_quantity"),
        _current_value(row, "base_price"),
        _current_value(row, "shipping_logistic_type"),
        _current_value(row, "permalink"),
        _listing_type_id(row),
        _current_value(row, "status"),
        inventory_code,
        inventory_code,
        paused_days if paused_days is not None else NA_VALUE,
    ]


def _dashboard_row(
    row: Mapping[str, Any],
    *,
    sales_windows: Mapping[int, Mapping[tuple[str, str], int]],
    include_promo: bool,
    today: date,
    use_promo_as_selected_price: bool,
) -> list[Any]:
    values = _dashboard_row_base(
        row,
        sales_windows=sales_windows,
        today=today,
        use_promo_as_selected_price=use_promo_as_selected_price,
    )
    return [*values, _promo_price(row)] if include_promo else values


def _dashboard_row_base(
    row: Mapping[str, Any],
    *,
    sales_windows: Mapping[int, Mapping[tuple[str, str], int]],
    today: date,
    use_promo_as_selected_price: bool,
) -> list[Any]:
    key = (
        normalize_sku(row.get("normalized_sku") or row.get("sku")),
        str(row.get("item_id") or ""),
    )
    paused_days = _paused_days(row, today=today)
    return [
        row.get("item_id") or "",
        _current_value(row, "title"),
        row.get("sku") or row.get("normalized_sku") or "",
        _current_value(row, "available_quantity"),
        _promo_price(row) if use_promo_as_selected_price else _current_value(row, "base_price"),
        _current_value(row, "shipping_logistic_type"),
        _current_value(row, "permalink"),
        _listing_type_id(row),
        _current_value(row, "status"),
        _inventory_code(row),
        paused_days if paused_days is not None else NA_VALUE,
        sales_windows.get(7, {}).get(key, 0),
        sales_windows.get(15, {}).get(key, 0),
        sales_windows.get(30, {}).get(key, 0),
        sales_windows.get(60, {}).get(key, 0),
        sales_windows.get(90, {}).get(key, 0),
        _current_value(row, "shipping_payer"),
        _seller_shipping_cost(row),
        _listing_fee_projection_value(row, "percentage_fee"),
        _listing_fee_projection_value(row, "sale_fee_amount"),
        _listing_fixed_fee(row),
        "Sí" if _has_catalog_product(row) else "No",
    ]


def _listing_fixed_fee(row: Mapping[str, Any]) -> Any:
    current = row.get("current", {})
    if not isinstance(current, Mapping):
        return NA_VALUE
    projection = current.get("listing_price_fixed_fee")
    if not isinstance(projection, Mapping):
        return NA_VALUE
    if projection.get("source") != "/sites/{site}/listing_prices":
        return NA_VALUE
    projection_currency_id = str(projection.get("currency_id") or "").strip()
    if not projection_currency_id:
        return NA_VALUE
    if projection.get("synced_at") is None:
        return NA_VALUE
    params = projection.get("params")
    if not isinstance(params, Mapping):
        return NA_VALUE
    required_params = (
        "site_id",
        "category_id",
        "price",
        "currency_id",
        "listing_type_id",
        "shipping_mode",
        "logistic_type",
    )
    if any(not str(params.get(key) or "").strip() for key in required_params):
        return NA_VALUE
    if projection_currency_id != str(params.get("currency_id") or "").strip():
        return NA_VALUE
    if not _fixed_fee_params_match_row_basis(row, params):
        return NA_VALUE
    fixed_fee = _promo_decimal(projection.get("fixed_fee"))
    if fixed_fee is None:
        return NA_VALUE
    raw_fixed_fee = projection.get("fixed_fee")
    return raw_fixed_fee.to_decimal() if isinstance(raw_fixed_fee, Decimal128) else raw_fixed_fee


def _fixed_fee_params_match_row_basis(row: Mapping[str, Any], params: Mapping[str, Any]) -> bool:
    current = row.get("current", {})
    if not isinstance(current, Mapping):
        return False
    for current_key, param_key in (
        ("site_id", "site_id"),
        ("category_id", "category_id"),
        ("currency_id", "currency_id"),
        ("listing_type_id", "listing_type_id"),
    ):
        if not _fixed_fee_string_basis_matches(current, current_key, params, param_key):
            return False

    if not _fixed_fee_price_basis_matches(current, params):
        return False

    for current_key, param_key in (
        ("shipping_mode", "shipping_mode"),
        ("logistic_type", "logistic_type"),
    ):
        if param_key in params and not _fixed_fee_string_basis_matches(
            current, current_key, params, param_key
        ):
            return False

    if not _fixed_fee_optional_decimal_basis_matches(
        current.get("billable_weight"), params.get("billable_weight")
    ):
        return False
    return _fixed_fee_optional_tags_basis_matches(current.get("tags"), params.get("tags"))


def _fixed_fee_string_basis_matches(
    current: Mapping[str, Any], current_key: str, params: Mapping[str, Any], param_key: str
) -> bool:
    current_value = current.get(current_key)
    param_value = params.get(param_key)
    return (
        _has_fixed_fee_basis(current_value)
        and _has_fixed_fee_basis(param_value)
        and str(current_value).strip() == str(param_value).strip()
    )


def _fixed_fee_price_basis_matches(current: Mapping[str, Any], params: Mapping[str, Any]) -> bool:
    current_price = current.get("price")
    if not _has_fixed_fee_basis(current_price) and "price" not in current:
        current_price = current.get("base_price")
    return _fixed_fee_decimal_basis_matches(current_price, params.get("price"))


def _fixed_fee_decimal_basis_matches(current_value: Any, param_value: Any) -> bool:
    current_decimal = _promo_decimal(current_value)
    param_decimal = _promo_decimal(param_value)
    return (
        current_decimal is not None
        and param_decimal is not None
        and current_decimal == param_decimal
    )


def _fixed_fee_optional_decimal_basis_matches(current_value: Any, param_value: Any) -> bool:
    if not _has_fixed_fee_basis(current_value) and not _has_fixed_fee_basis(param_value):
        return True
    return _fixed_fee_decimal_basis_matches(current_value, param_value)


def _fixed_fee_optional_tags_basis_matches(current_value: Any, param_value: Any) -> bool:
    current_tags = _fixed_fee_tags(current_value)
    param_tags = _fixed_fee_tags(param_value)
    if _fixed_fee_tags_are_absent(current_value, current_tags) and _fixed_fee_tags_are_absent(
        param_value, param_tags
    ):
        return True
    return _fixed_fee_tags_basis_matches(current_value, param_value)


def _fixed_fee_tags_basis_matches(current_value: Any, param_value: Any) -> bool:
    current_tags = _fixed_fee_tags(current_value)
    param_tags = _fixed_fee_tags(param_value)
    return current_tags is not None and param_tags is not None and current_tags == param_tags


def _fixed_fee_tags_are_absent(value: Any, normalized_tags: list[str] | None) -> bool:
    return value is None or normalized_tags == []


def _fixed_fee_tags(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    return [tag for raw in value if (tag := str(raw).strip())]


def _has_fixed_fee_basis(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def _comision_row(row: Mapping[str, Any]) -> list[Any]:
    return [
        row.get("item_id") or "",
        _listing_fee_projection_value(row, "percentage_fee"),
        _listing_fee_projection_value(row, "sale_fee_amount"),
        _seller_shipping_cost(row),
    ]


def _listing_fee_projection_value(row: Mapping[str, Any], field: str) -> Any:
    current = row.get("current", {})
    if not isinstance(current, Mapping):
        return NA_VALUE
    projection = current.get("listing_fee_projection")
    if not isinstance(projection, Mapping):
        return NA_VALUE
    if projection.get("source") != LISTING_PRICE_SOURCE:
        return NA_VALUE
    value = _projection_decimal(projection.get(field))
    return value if value is not None else NA_VALUE


def _projection_decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal128):
        decimal_value = value.to_decimal()
    elif isinstance(value, Decimal):
        decimal_value = value
    elif isinstance(value, int):
        decimal_value = Decimal(value)
    elif isinstance(value, float):
        decimal_value = Decimal(str(value)) if math.isfinite(value) else Decimal("NaN")
    else:
        try:
            decimal_value = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
    return decimal_value if decimal_value.is_finite() and decimal_value >= 0 else None


def _promo_price(row: Mapping[str, Any]) -> Any:
    current = row.get("current", {})
    if not isinstance(current, Mapping):
        return NA_VALUE
    projection = current.get("current_promotion")
    if not isinstance(projection, Mapping):
        return NA_VALUE
    if projection.get("source") != "/items/{id}/sale_price":
        return NA_VALUE
    if not str(projection.get("currency_id") or "").strip():
        return NA_VALUE
    if projection.get("reference_at") is None or projection.get("synced_at") is None:
        return NA_VALUE
    sale_amount = _promo_decimal(projection.get("sale_amount"))
    regular_amount = _promo_decimal(projection.get("regular_amount"))
    if sale_amount is None or regular_amount is None or sale_amount >= regular_amount:
        return NA_VALUE
    raw_sale_amount = projection.get("sale_amount")
    return (
        raw_sale_amount.to_decimal() if isinstance(raw_sale_amount, Decimal128) else raw_sale_amount
    )


def _promo_decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, Decimal128):
        decimal_value = value.to_decimal()
    elif isinstance(value, Decimal):
        decimal_value = value
    elif isinstance(value, int):
        decimal_value = Decimal(value)
    elif isinstance(value, float):
        decimal_value = Decimal(str(value)) if math.isfinite(value) else Decimal("NaN")
    else:
        try:
            decimal_value = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
    return decimal_value if decimal_value.is_finite() and decimal_value >= 0 else None


def _seller_shipping_cost(row: Mapping[str, Any]) -> Any:
    value = _current_value(row, "seller_shipping_cost")
    if value == "" or isinstance(value, bool):
        return NA_VALUE
    if isinstance(value, Decimal128):
        decimal_value = value.to_decimal()
        return decimal_value if decimal_value.is_finite() and decimal_value >= 0 else NA_VALUE
    if isinstance(value, Decimal):
        return value if value.is_finite() and value >= 0 else NA_VALUE
    if isinstance(value, int):
        return value if value >= 0 else NA_VALUE
    if isinstance(value, float):
        return value if math.isfinite(value) and value >= 0 else NA_VALUE
    return NA_VALUE


def _paused_days(row: Mapping[str, Any] | None, *, today: date) -> int | None:
    if row is None:
        return None
    current = row.get("current", {})
    if not isinstance(current, Mapping):
        return None
    if str(current.get("status") or "").strip().casefold() != "paused":
        return None
    paused_since = _optional_datetime(current.get("paused_since"))
    if paused_since is None:
        return None
    return max((today - paused_since.date()).days, 0)


def _last_days_start(now: datetime, days: int) -> datetime:
    local_date = now.astimezone(UTC).date() - timedelta(days=days - 1)
    return datetime.combine(local_date, time.min, tzinfo=UTC)


def _day_end(now: datetime) -> datetime:
    return datetime.combine(now.astimezone(UTC).date(), time.max, tzinfo=UTC)


def _optional_datetime(value: Any) -> datetime | None:
    try:
        return _as_utc_datetime(value)
    except (TypeError, ValueError):
        return None


def _order_items(order: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw_items = order.get("items") or []
    if not isinstance(raw_items, Iterable) or isinstance(raw_items, (str, bytes)):
        return []
    return [item for item in raw_items if isinstance(item, Mapping)]


def _item_sku(item: Mapping[str, Any]) -> Any:
    raw_nested_item = item.get("item")
    nested_item: Mapping[str, Any] = raw_nested_item if isinstance(raw_nested_item, Mapping) else {}
    return (
        item.get("sku")
        or item.get("seller_sku")
        or item.get("seller_custom_field")
        or nested_item.get("seller_sku")
        or nested_item.get("seller_custom_field")
        or ""
    )


def _item_id(item: Mapping[str, Any]) -> str:
    raw_nested_item = item.get("item")
    nested_item: Mapping[str, Any] = raw_nested_item if isinstance(raw_nested_item, Mapping) else {}
    return str(
        item.get("item_id") or nested_item.get("id") or nested_item.get("item_id") or ""
    ).strip()


def _item_variation_id(item: Mapping[str, Any]) -> str:
    raw_nested_item = item.get("item")
    nested_item: Mapping[str, Any] = raw_nested_item if isinstance(raw_nested_item, Mapping) else {}
    return _normalize_variation_id(item.get("variation_id") or nested_item.get("variation_id"))


def _normalize_variation_id(value: Any) -> str:
    return str(value or "").strip()


def _item_quantity(item: Mapping[str, Any]) -> int:
    try:
        return int(str(item.get("quantity", item.get("qty", 0))))
    except ValueError:
        return 0


def _has_catalog_product(row: Mapping[str, Any]) -> bool:
    current = row.get("current", {})
    value = current.get("catalog_product_id") if isinstance(current, Mapping) else None
    return str(value or "").strip() != ""


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
