from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime, time, timedelta, tzinfo
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from zeler_sheets.formulas.dispatcher import (
    FormulaExecutionContext,
    FormulaExecutionResult,
    FormulaHandler,
)
from zeler_sheets.formulas.read_models import FormulaReadModelRepository, normalize_sku

BATCH_B_IMPLEMENTED_FORMULAS = frozenset(
    {
        "ZELERDATA_ORDENES",
        "ZELERDATA_VENTASTOTALES",
        "ZELERDATA_UNIDADESVENDIDAS",
        "ZELERDATA_ORDENESPORSKU",
        "ZELERDATA_DIASDESDEULTIMAVENTA",
        "ZELERDATA_PRODUCTOSINVENTA",
        "ZELERDATA_VENTAPORDIAS",
        "ZELERDATA_VENTASYSTOCK",
        "ZELERDATA_TOPVENTASUNIDADES",
        "ZELERDATA_TOPVENTASDINERO",
        "ZELERDATA_PREGUNTAS",
        "ZELERDATA_PREGUNTASKPI",
    }
)

ORDENES_MVP_HEADERS = ["ID Orden", "Fecha", "Estado", "Buyer ID", "Total", "Shipment ID", "Items"]
ORDENES_POR_SKU_MVP_HEADERS = [
    "SKU",
    "ID Orden",
    "Fecha",
    "Estado",
    "Buyer ID",
    "Total",
    "Items",
]
PREGUNTAS_MVP_HEADERS = [
    "ID Pregunta",
    "Fecha",
    "Item ID",
    "Buyer ID",
    "Estado",
    "Pregunta",
    "Respuesta",
    "Fecha respuesta",
]
PREGUNTAS_KPI_MVP_HEADERS = ["Métrica", "Valor"]
VENTAS_Y_STOCK_MVP_HEADERS = [
    "SKU",
    "ID Publicación",
    "Ventas 7 días",
    "Ventas 15 días",
    "Ventas 30 días",
    "Stock",
]
TOP_VENTAS_UNIDADES_MVP_HEADERS = ["SKU", "ID Publicación", "Unidades vendidas"]
TOP_VENTAS_DINERO_MVP_HEADERS = ["SKU", "ID Publicación", "Ventas"]


def build_order_question_formula_handlers(
    repository: FormulaReadModelRepository,
    *,
    now_fn: Callable[[], datetime] | None = None,
) -> dict[str, FormulaHandler]:
    handlers = OrderQuestionFormulaHandlers(repository, now_fn=now_fn)
    return {
        "ZELERDATA_ORDENES": handlers.sheetseller_ordenes,
        "ZELERDATA_VENTASTOTALES": handlers.sheetseller_ventas_totales,
        "ZELERDATA_UNIDADESVENDIDAS": handlers.sheetseller_unidades_vendidas,
        "ZELERDATA_ORDENESPORSKU": handlers.sheetseller_ordenes_por_sku,
        "ZELERDATA_DIASDESDEULTIMAVENTA": handlers.sheetseller_dias_desde_ultima_venta,
        "ZELERDATA_PRODUCTOSINVENTA": handlers.sheetseller_productos_sin_venta,
        "ZELERDATA_VENTAPORDIAS": handlers.sheetseller_venta_por_dias,
        "ZELERDATA_VENTASYSTOCK": handlers.sheetseller_ventas_y_stock,
        "ZELERDATA_TOPVENTASUNIDADES": handlers.sheetseller_top_ventas_unidades,
        "ZELERDATA_TOPVENTASDINERO": handlers.sheetseller_top_ventas_dinero,
        "ZELERDATA_PREGUNTAS": handlers.sheetseller_preguntas,
        "ZELERDATA_PREGUNTASKPI": handlers.sheetseller_preguntas_kpi,
    }


class OrderQuestionFormulaHandlers:
    def __init__(
        self,
        repository: FormulaReadModelRepository,
        *,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._now_fn = now_fn or (lambda: datetime.now(UTC))

    async def sheetseller_ordenes(self, context: FormulaExecutionContext) -> FormulaExecutionResult:
        timezone = _context_timezone(context)
        date_range = _date_range(
            context.args.get("fecha_inicial"),
            context.args.get("fecha_final"),
            timezone=timezone,
        )
        status_filter = _status_filter(context.args.get("estado", "todos"))
        buyer_filter = _buyer_filter(context.args.get("compradores", ""))
        orders = await self._repository.find_orders(
            seller_id=context.seller_id,
            date_from=date_range.start,
            date_to=date_range.end,
            status=status_filter,
        )
        filtered_orders = _filter_orders_by_buyers(orders, buyer_filter)
        values: list[list[Any]] = _header_row(context.args.get("encabezados"), ORDENES_MVP_HEADERS)
        values.extend(_order_row(order, timezone=timezone) for order in filtered_orders)
        return FormulaExecutionResult(
            values=values,
            meta={
                "orders_count": len(filtered_orders),
                "status_filter": status_filter or "todos",
                "buyer_filter_count": len(buyer_filter),
                "columns": "orders_mvp",
            },
        )

    async def sheetseller_ventas_totales(
        self, context: FormulaExecutionContext
    ) -> FormulaExecutionResult:
        date_range = _date_range(
            context.args.get("fecha_inicial"),
            context.args.get("fecha_final"),
            timezone=_context_timezone(context),
        )
        status_filter = _status_filter(context.args.get("estado", "todos"))
        orders = await self._repository.find_orders(
            seller_id=context.seller_id,
            date_from=date_range.start,
            date_to=date_range.end,
            status=status_filter,
        )
        total = sum((_decimal(order.get("total_amount")) for order in orders), Decimal("0"))
        return FormulaExecutionResult(
            values=[[_sheet_number(total)]],
            meta={
                "orders_count": len(orders),
                "status_filter": status_filter or "todos",
            },
        )

    async def sheetseller_unidades_vendidas(
        self, context: FormulaExecutionContext
    ) -> FormulaExecutionResult:
        pairs = _lookup_pairs(
            skus=context.args.get("skus"),
            item_ids=context.args.get("id_publicaciones"),
        )
        date_range = _date_range(
            context.args.get("fecha_inicial"),
            context.args.get("fecha_final"),
            timezone=_context_timezone(context),
        )
        orders = await self._repository.find_orders(
            seller_id=context.seller_id,
            date_from=date_range.start,
            date_to=date_range.end,
        )
        sku_resolver = await _sku_resolver_for_orders(
            repository=self._repository,
            seller_id=context.seller_id,
            orders=orders,
        )
        totals, enriched_count = _unit_totals_by_pair(orders, sku_resolver=sku_resolver)
        values: list[list[Any]] = []
        misses = 0
        for pair in pairs:
            units = totals.get((pair.sku, pair.item_id), Decimal("0"))
            if units == 0:
                misses += 1
            values.append([_sheet_number(units)])
        return FormulaExecutionResult(
            values=values,
            meta=_with_enrichment_meta(
                {"partial_misses": misses, "orders_count": len(orders)},
                enriched_count=enriched_count,
            ),
        )

    async def sheetseller_ordenes_por_sku(
        self, context: FormulaExecutionContext
    ) -> FormulaExecutionResult:
        requested_skus = _flatten_sheet_values(context.args.get("skus"), normalize=normalize_sku)
        timezone = _context_timezone(context)
        date_range = _date_range(
            context.args.get("fecha_inicial"),
            context.args.get("fecha_final"),
            timezone=timezone,
        )
        status_filter = _status_filter(context.args.get("estado", "todos"))
        buyer_filter = _buyer_filter(context.args.get("compradores", ""))
        orders = await self._repository.find_orders(
            seller_id=context.seller_id,
            date_from=date_range.start,
            date_to=date_range.end,
            status=status_filter,
        )
        sku_resolver = await _sku_resolver_for_orders(
            repository=self._repository,
            seller_id=context.seller_id,
            orders=orders,
        )
        filtered_orders = _filter_orders_by_buyers(orders, buyer_filter)
        values: list[list[Any]] = _header_row(
            context.args.get("encabezados"), ORDENES_POR_SKU_MVP_HEADERS
        )
        for requested_sku in dict.fromkeys(requested_skus):
            for order in filtered_orders:
                matching_items = _items_matching_sku(
                    order,
                    requested_sku,
                    sku_resolver=sku_resolver,
                )
                if not matching_items:
                    continue
                values.append(
                    [
                        requested_sku,
                        _document_id(order),
                        _sheet_datetime(order.get("date_created"), timezone=timezone),
                        order.get("status") or "",
                        _buyer_id(order),
                        _sheet_number(_decimal(order.get("total_amount"))),
                        _items_summary(matching_items, sku_resolver=sku_resolver),
                    ]
                )
        rows_count = len(values) - (1 if _headers_requested(context.args.get("encabezados")) else 0)
        return FormulaExecutionResult(
            values=values,
            meta={
                "orders_count": rows_count,
                "status_filter": status_filter or "todos",
                "buyer_filter_count": len(buyer_filter),
                "sku_filter_count": len(dict.fromkeys(requested_skus)),
                "columns": "orders_by_sku_mvp",
            },
        )

    async def sheetseller_dias_desde_ultima_venta(
        self, context: FormulaExecutionContext
    ) -> FormulaExecutionResult:
        pairs = _lookup_pairs(
            skus=context.args.get("skus"),
            item_ids=context.args.get("id_publicaciones"),
        )
        timezone = _context_timezone(context)
        now = _as_utc_datetime(self._now_fn())
        local_now = now.astimezone(timezone)
        orders = await self._repository.find_orders(
            seller_id=context.seller_id,
            date_from=datetime(1970, 1, 1, tzinfo=UTC),
            date_to=_local_day_boundary(local_now.date(), time.max, timezone=timezone),
        )
        sku_resolver = await _sku_resolver_for_orders(
            repository=self._repository,
            seller_id=context.seller_id,
            orders=orders,
        )
        latest_by_pair, enriched_count = _latest_sale_dates_by_pair(
            orders,
            sku_resolver=sku_resolver,
        )
        values: list[list[Any]] = []
        misses = 0
        today = local_now.date()
        for pair in pairs:
            latest = latest_by_pair.get((pair.sku, pair.item_id))
            if latest is None:
                misses += 1
                values.append([""])
            else:
                values.append([max((today - latest.astimezone(timezone).date()).days, 0)])
        return FormulaExecutionResult(
            values=values,
            meta=_with_enrichment_meta(
                {"partial_misses": misses, "orders_count": len(orders)},
                enriched_count=enriched_count,
            ),
        )

    async def sheetseller_productos_sin_venta(
        self, context: FormulaExecutionContext
    ) -> FormulaExecutionResult:
        range_days = _positive_int(context.args.get("rango_dias"))
        timezone = _context_timezone(context)
        now = _as_utc_datetime(self._now_fn())
        local_now = now.astimezone(timezone)
        date_range = _last_days_range(now, range_days, timezone=timezone)
        rows = await self._repository.find_item_formula_rows(seller_id=context.seller_id)
        ordered_rows = sorted(
            rows,
            key=lambda row: (
                normalize_sku(row.get("normalized_sku", "")),
                str(row.get("item_id", "")),
            ),
        )
        orders = await self._repository.find_orders(
            seller_id=context.seller_id,
            date_from=date_range.start,
            date_to=date_range.end,
        )
        all_orders = await self._repository.find_orders(
            seller_id=context.seller_id,
            date_from=datetime(1970, 1, 1, tzinfo=UTC),
            date_to=_local_day_boundary(local_now.date(), time.max, timezone=timezone),
        )
        sku_resolver = await _sku_resolver_for_orders(
            repository=self._repository,
            seller_id=context.seller_id,
            orders=orders,
        )
        all_orders_sku_resolver = await _sku_resolver_for_orders(
            repository=self._repository,
            seller_id=context.seller_id,
            orders=all_orders,
        )
        recent_totals, enriched_count = _unit_totals_by_pair(orders, sku_resolver=sku_resolver)
        last_sales, _ = _latest_sale_dates_by_pair(
            all_orders,
            sku_resolver=all_orders_sku_resolver,
        )
        values: list[list[Any]] = _header_row(
            context.args.get("encabezados"),
            ["SKU", "ID Publicación", "Título", "Stock", "Días sin venta"],
        )
        for row in ordered_rows:
            sku = normalize_sku(row.get("normalized_sku") or row.get("sku"))
            item_id = str(row.get("item_id") or "").strip()
            if not sku or not item_id:
                continue
            if recent_totals.get((sku, item_id), Decimal("0")) > 0:
                continue
            latest = last_sales.get((sku, item_id))
            values.append(
                [
                    row.get("sku") or sku,
                    item_id,
                    _current_value(row, "title"),
                    _current_value(row, "available_quantity"),
                    ""
                    if latest is None
                    else max((local_now.date() - latest.astimezone(timezone).date()).days, 0),
                ]
            )
        header_count = 1 if _headers_requested(context.args.get("encabezados")) else 0
        return FormulaExecutionResult(
            values=values,
            meta={
                "rows_count": len(values) - header_count,
                "orders_count": len(orders),
                "rango_dias": range_days,
                "columns": "products_without_sales_mvp",
                "sku_enriched_items": enriched_count,
            },
        )

    async def sheetseller_venta_por_dias(
        self, context: FormulaExecutionContext
    ) -> FormulaExecutionResult:
        pairs = _lookup_pairs(
            skus=context.args.get("skus"),
            item_ids=context.args.get("id_publicaciones"),
        )
        range_days = _positive_int(context.args.get("rango_dias"))
        date_range = _last_days_range(
            self._now_fn(), range_days, timezone=_context_timezone(context)
        )
        orders = await self._repository.find_orders(
            seller_id=context.seller_id,
            date_from=date_range.start,
            date_to=date_range.end,
        )
        sku_resolver = await _sku_resolver_for_orders(
            repository=self._repository,
            seller_id=context.seller_id,
            orders=orders,
        )
        totals, enriched_count = _unit_totals_by_pair(orders, sku_resolver=sku_resolver)
        values: list[list[Any]] = []
        misses = 0
        for pair in pairs:
            units = totals.get((pair.sku, pair.item_id), Decimal("0"))
            if units == 0:
                misses += 1
            values.append([_sheet_number(units)])
        return FormulaExecutionResult(
            values=values,
            meta={
                "partial_misses": misses,
                "orders_count": len(orders),
                "rango_dias": range_days,
                "sku_enriched_items": enriched_count,
            },
        )

    async def sheetseller_ventas_y_stock(
        self, context: FormulaExecutionContext
    ) -> FormulaExecutionResult:
        pairs = _lookup_pairs(
            skus=context.args.get("skus"),
            item_ids=context.args.get("id_publicaciones"),
        )
        timezone = _context_timezone(context)
        now = _as_utc_datetime(self._now_fn())
        date_ranges = {days: _last_days_range(now, days, timezone=timezone) for days in (7, 15, 30)}
        rows = await self._repository.find_item_formula_rows(
            seller_id=context.seller_id,
            skus=[pair.sku for pair in pairs],
            item_ids=[pair.item_id for pair in pairs],
        )
        rows_by_pair = {
            (normalize_sku(row.get("normalized_sku", "")), str(row.get("item_id", ""))): row
            for row in rows
        }
        orders = await self._repository.find_orders(
            seller_id=context.seller_id,
            date_from=date_ranges[30].start,
            date_to=date_ranges[30].end,
        )
        sku_resolver = await _sku_resolver_for_orders(
            repository=self._repository,
            seller_id=context.seller_id,
            orders=orders,
        )
        totals_by_window: dict[int, dict[tuple[str, str], Decimal]] = {}
        enriched_count = 0
        for days, current_range in date_ranges.items():
            window_orders = [order for order in orders if _order_in_range(order, current_range)]
            totals_by_window[days], current_enriched_count = _unit_totals_by_pair(
                window_orders,
                sku_resolver=sku_resolver,
            )
            enriched_count = max(enriched_count, current_enriched_count)

        values: list[list[Any]] = _header_row(
            context.args.get("encabezados"), VENTAS_Y_STOCK_MVP_HEADERS
        )
        misses = 0
        for pair in pairs:
            row = rows_by_pair.get((pair.sku, pair.item_id))
            stock = _current_value(row, "available_quantity") if row else ""
            if row is None:
                misses += 1
            values.append(
                [
                    pair.sku,
                    pair.item_id,
                    _sheet_number(totals_by_window[7].get((pair.sku, pair.item_id), Decimal("0"))),
                    _sheet_number(totals_by_window[15].get((pair.sku, pair.item_id), Decimal("0"))),
                    _sheet_number(totals_by_window[30].get((pair.sku, pair.item_id), Decimal("0"))),
                    stock,
                ]
            )
        return FormulaExecutionResult(
            values=values,
            meta={
                "partial_misses": misses,
                "orders_count": len(orders),
                "columns": "sales_and_stock_mvp",
                "sku_enriched_items": enriched_count,
            },
        )

    async def sheetseller_top_ventas_unidades(
        self, context: FormulaExecutionContext
    ) -> FormulaExecutionResult:
        date_range = _date_range(
            context.args.get("fecha_inicial"),
            context.args.get("fecha_final"),
            timezone=_context_timezone(context),
        )
        top_count = _positive_int(context.args.get("cantidad_top"))
        orders = await self._repository.find_orders(
            seller_id=context.seller_id,
            date_from=date_range.start,
            date_to=date_range.end,
        )
        sku_resolver = await _sku_resolver_for_orders(
            repository=self._repository,
            seller_id=context.seller_id,
            orders=orders,
        )
        totals, enriched_count = _unit_totals_by_pair(orders, sku_resolver=sku_resolver)
        ranked = sorted(totals.items(), key=lambda entry: (-entry[1], entry[0][0], entry[0][1]))[
            :top_count
        ]
        values: list[list[Any]] = _header_row(
            context.args.get("encabezados"), TOP_VENTAS_UNIDADES_MVP_HEADERS
        )
        values.extend([[sku, item_id, _sheet_number(units)] for (sku, item_id), units in ranked])
        return FormulaExecutionResult(
            values=values,
            meta={
                "orders_count": len(orders),
                "rows_count": len(ranked),
                "columns": "top_sales_units_mvp",
                "sku_enriched_items": enriched_count,
            },
        )

    async def sheetseller_top_ventas_dinero(
        self, context: FormulaExecutionContext
    ) -> FormulaExecutionResult:
        date_range = _date_range(
            context.args.get("fecha_inicial"),
            context.args.get("fecha_final"),
            timezone=_context_timezone(context),
        )
        top_count = _positive_int(context.args.get("cantidad_top"))
        orders = await self._repository.find_orders(
            seller_id=context.seller_id,
            date_from=date_range.start,
            date_to=date_range.end,
        )
        sku_resolver = await _sku_resolver_for_orders(
            repository=self._repository,
            seller_id=context.seller_id,
            orders=orders,
        )
        totals, enriched_count, missing_price_count = _revenue_totals_by_pair(
            orders,
            sku_resolver=sku_resolver,
        )
        ranked = sorted(totals.items(), key=lambda entry: (-entry[1], entry[0][0], entry[0][1]))[
            :top_count
        ]
        values: list[list[Any]] = _header_row(
            context.args.get("encabezados"), TOP_VENTAS_DINERO_MVP_HEADERS
        )
        values.extend(
            [[sku, item_id, _sheet_number(revenue)] for (sku, item_id), revenue in ranked]
        )
        return FormulaExecutionResult(
            values=values,
            meta={
                "orders_count": len(orders),
                "rows_count": len(ranked),
                "columns": "top_sales_revenue_mvp",
                "sku_enriched_items": enriched_count,
                "items_without_unit_price": missing_price_count,
            },
        )

    async def sheetseller_preguntas(
        self, context: FormulaExecutionContext
    ) -> FormulaExecutionResult:
        timezone = _context_timezone(context)
        date_range = _date_range(
            context.args.get("fecha_inicial"),
            context.args.get("fecha_final"),
            timezone=timezone,
        )
        hour_range = _hour_range(
            context.args.get("horario_inicial"), context.args.get("horario_final")
        )
        questions = await self._repository.find_questions(
            seller_id=context.seller_id,
            date_from=date_range.start,
            date_to=date_range.end,
        )
        filtered_questions = [
            question
            for question in questions
            if _question_in_hour_range(question, hour_range, timezone=timezone)
        ]
        values: list[list[Any]] = _header_row(
            context.args.get("encabezados"), PREGUNTAS_MVP_HEADERS
        )
        values.extend(_question_row(question, timezone=timezone) for question in filtered_questions)
        return FormulaExecutionResult(
            values=values,
            meta={"questions_count": len(filtered_questions), "columns": "questions_mvp"},
        )

    async def sheetseller_preguntas_kpi(
        self, context: FormulaExecutionContext
    ) -> FormulaExecutionResult:
        date_range = _date_range(
            context.args.get("fecha_inicio"),
            context.args.get("fecha_final"),
            timezone=_context_timezone(context),
        )
        questions = await self._repository.find_questions(
            seller_id=context.seller_id,
            date_from=date_range.start,
            date_to=date_range.end,
        )
        status_counts = _question_status_counts(questions)
        average_response_minutes = _average_response_minutes(questions)
        values: list[list[Any]] = _header_row(
            context.args.get("encabezados"), PREGUNTAS_KPI_MVP_HEADERS
        )
        values.extend(
            [
                ["Total preguntas", len(questions)],
                ["Respondidas", status_counts["answered"]],
                ["Sin responder", status_counts["unanswered"]],
                ["Eliminadas/Baneadas", status_counts["removed"]],
                ["Tiempo promedio respuesta (min)", average_response_minutes],
            ]
        )
        return FormulaExecutionResult(
            values=values,
            meta={"questions_count": len(questions), "columns": "preguntas_kpi_mvp"},
        )


class _DateRange:
    def __init__(self, *, start: datetime, end: datetime) -> None:
        self.start = start
        self.end = end


class _LookupPair:
    def __init__(self, *, sku: str, item_id: str) -> None:
        self.sku = sku
        self.item_id = item_id


class _HourRange:
    def __init__(self, *, start: time, end: time) -> None:
        self.start = start
        self.end = end


class _SkuResolution:
    def __init__(self, *, sku: str, enriched: bool) -> None:
        self.sku = sku
        self.enriched = enriched


class _OrderSkuResolver:
    def __init__(self, rows: Sequence[Mapping[str, Any]]) -> None:
        rows_by_item_id: dict[str, list[Mapping[str, Any]]] = {}
        for row in rows:
            item_id = str(row.get("item_id") or "").strip()
            if item_id:
                rows_by_item_id.setdefault(item_id, []).append(row)
        self._rows_by_item_id = rows_by_item_id

    def resolve(self, item: Mapping[str, Any]) -> _SkuResolution:
        direct_sku = _normalize_optional_sku(_item_sku(item))
        if direct_sku:
            return _SkuResolution(sku=direct_sku, enriched=False)

        item_id = _item_id(item)
        if not item_id:
            return _SkuResolution(sku="", enriched=False)

        rows = self._rows_by_item_id.get(item_id, [])
        variation_id = _item_variation_id(item)
        if variation_id:
            variation_matches = [
                row
                for row in rows
                if _normalize_variation_id(row.get("variation_id")) == variation_id
            ]
            sku = _unique_sku(variation_matches)
            if sku:
                return _SkuResolution(sku=sku, enriched=True)

        sku = _unique_sku(rows)
        return _SkuResolution(sku=sku, enriched=bool(sku))


class _OrderLine:
    def __init__(
        self,
        *,
        sku: str,
        item_id: str,
        quantity: Decimal,
        unit_price: Decimal | None,
        enriched: bool,
    ) -> None:
        self.sku = sku
        self.item_id = item_id
        self.quantity = quantity
        self.unit_price = unit_price
        self.enriched = enriched


def _date_range(start_value: Any, end_value: Any, *, timezone: tzinfo = UTC) -> _DateRange:
    return _DateRange(
        start=_parse_date_boundary(start_value, end_of_day=False, timezone=timezone),
        end=_parse_date_boundary(end_value, end_of_day=True, timezone=timezone),
    )


def _last_days_range(now_value: datetime, days: int, *, timezone: tzinfo = UTC) -> _DateRange:
    now = _as_utc_datetime(now_value)
    local_now = now.astimezone(timezone)
    start_date = local_now.date() - timedelta(days=days - 1)
    return _DateRange(
        start=_local_day_boundary(start_date, time.min, timezone=timezone),
        end=_local_day_boundary(local_now.date(), time.max, timezone=timezone),
    )


def _parse_date_boundary(value: Any, *, end_of_day: bool, timezone: tzinfo = UTC) -> datetime:
    if isinstance(value, datetime):
        parsed = value
        date_only = False
    elif isinstance(value, str):
        stripped = value.strip()
        date_only = "T" not in stripped and len(stripped) == 10
        parsed = datetime.fromisoformat(stripped.replace("Z", "+00:00"))
    else:
        raise ValueError("expected ISO date or datetime")

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone if date_only else UTC)
    parsed = parsed.astimezone(UTC)
    if date_only:
        boundary = time.max if end_of_day else time.min
        return _local_day_boundary(parsed.astimezone(timezone).date(), boundary, timezone=timezone)
    return parsed


def _local_day_boundary(date_value: Any, boundary: time, *, timezone: tzinfo) -> datetime:
    return datetime.combine(date_value, boundary, tzinfo=timezone).astimezone(UTC)


def _as_utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _status_filter(value: Any) -> str | None:
    status = str(value or "todos").strip()
    if status.casefold() == "todos" or not status:
        return None
    return status


def _buyer_filter(value: Any) -> set[str]:
    if isinstance(value, str) and not value.strip():
        return set()
    return set(_flatten_sheet_values(value, normalize=lambda buyer_id: str(buyer_id).strip()))


def _filter_orders_by_buyers(
    orders: Sequence[Mapping[str, Any]], buyer_filter: set[str]
) -> list[Mapping[str, Any]]:
    if not buyer_filter:
        return list(orders)
    return [order for order in orders if _buyer_id(order) in buyer_filter]


def _hour_range(start_value: Any, end_value: Any) -> _HourRange:
    return _HourRange(
        start=_parse_hour(start_value, default=time.min),
        end=_parse_hour(end_value, default=time.max),
    )


def _parse_hour(value: Any, *, default: time) -> time:
    if value is None or str(value).strip() == "":
        return default
    if isinstance(value, time):
        return value
    parts = str(value).strip().split(":")
    if len(parts) == 1:
        return time(hour=int(parts[0]))
    return time(
        hour=int(parts[0]), minute=int(parts[1]), second=int(parts[2]) if len(parts) > 2 else 0
    )


def _lookup_pairs(*, skus: Any, item_ids: Any) -> list[_LookupPair]:
    normalized_skus = _flatten_sheet_values(skus, normalize=normalize_sku)
    normalized_item_ids = _flatten_sheet_values(
        item_ids, normalize=lambda item_id: str(item_id).strip()
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


def _positive_int(value: Any) -> int:
    parsed = int(str(value).strip())
    return max(parsed, 1)


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


async def _sku_resolver_for_orders(
    *,
    repository: FormulaReadModelRepository,
    seller_id: str,
    orders: Sequence[Mapping[str, Any]],
) -> _OrderSkuResolver:
    item_ids = list(
        dict.fromkeys(
            item_id
            for order in orders
            for item in _order_items(order)
            if (item_id := _item_id(item))
        )
    )
    if not item_ids:
        return _OrderSkuResolver([])
    variation_values = [
        _item_variation_id(item) for order in orders for item in _order_items(order)
    ]
    variation_ids: list[str | None] | None = None
    if any(variation_values):
        variation_ids = list(dict.fromkeys(value or None for value in variation_values))
    rows = await repository.find_sku_index_rows(
        seller_id=seller_id,
        item_ids=item_ids,
        variation_ids=variation_ids,
        limit=max(500, len(item_ids) * 10),
    )
    return _OrderSkuResolver(rows)


def _unit_totals_by_pair(
    orders: Sequence[Mapping[str, Any]], *, sku_resolver: _OrderSkuResolver
) -> tuple[dict[tuple[str, str], Decimal], int]:
    totals: dict[tuple[str, str], Decimal] = {}
    enriched_count = 0
    for order in orders:
        for line in _order_lines(order, sku_resolver=sku_resolver):
            if not line.sku or not line.item_id:
                continue
            key = (line.sku, line.item_id)
            totals[key] = totals.get(key, Decimal("0")) + line.quantity
            if line.enriched:
                enriched_count += 1
    return totals, enriched_count


def _latest_sale_dates_by_pair(
    orders: Sequence[Mapping[str, Any]], *, sku_resolver: _OrderSkuResolver
) -> tuple[dict[tuple[str, str], datetime], int]:
    latest: dict[tuple[str, str], datetime] = {}
    enriched_count = 0
    for order in orders:
        sold_at = _optional_datetime(order.get("date_created"))
        if sold_at is None:
            continue
        for line in _order_lines(order, sku_resolver=sku_resolver):
            if not line.sku or not line.item_id:
                continue
            key = (line.sku, line.item_id)
            if key not in latest or sold_at > latest[key]:
                latest[key] = sold_at
            if line.enriched:
                enriched_count += 1
    return latest, enriched_count


def _revenue_totals_by_pair(
    orders: Sequence[Mapping[str, Any]], *, sku_resolver: _OrderSkuResolver
) -> tuple[dict[tuple[str, str], Decimal], int, int]:
    totals: dict[tuple[str, str], Decimal] = {}
    enriched_count = 0
    missing_price_count = 0
    for order in orders:
        for line in _order_lines(order, sku_resolver=sku_resolver):
            if not line.sku or not line.item_id:
                continue
            if line.enriched:
                enriched_count += 1
            if line.unit_price is None:
                missing_price_count += 1
                continue
            key = (line.sku, line.item_id)
            totals[key] = totals.get(key, Decimal("0")) + (line.quantity * line.unit_price)
    return totals, enriched_count, missing_price_count


def _order_lines(order: Mapping[str, Any], *, sku_resolver: _OrderSkuResolver) -> list[_OrderLine]:
    lines: list[_OrderLine] = []
    for item in _order_items(order):
        resolution = sku_resolver.resolve(item)
        item_id = _item_id(item)
        if not resolution.sku or not item_id:
            continue
        lines.append(
            _OrderLine(
                sku=resolution.sku,
                item_id=item_id,
                quantity=_item_quantity(item),
                unit_price=_item_unit_price(item),
                enriched=resolution.enriched,
            )
        )
    return lines


def _order_row(order: Mapping[str, Any], *, timezone: tzinfo) -> list[Any]:
    return [
        _document_id(order),
        _sheet_datetime(order.get("date_created"), timezone=timezone),
        order.get("status") or "",
        _buyer_id(order),
        _sheet_number(_decimal(order.get("total_amount"))),
        _shipment_id(order),
        _items_summary(_order_items(order)),
    ]


def _question_row(question: Mapping[str, Any], *, timezone: tzinfo) -> list[Any]:
    answer = question.get("answer")
    answer_values: Mapping[str, Any] = answer if isinstance(answer, Mapping) else {}
    return [
        _document_id(question),
        _sheet_datetime(question.get("date_created"), timezone=timezone),
        str(question.get("item_id") or ""),
        str(question.get("from_user_id") or ""),
        question.get("status") or "",
        question.get("text") or "",
        answer_values.get("text") or "",
        _sheet_datetime(
            answer_values.get("date_created")
            or answer_values.get("answered_at")
            or answer_values.get("created_at"),
            timezone=timezone,
        ),
    ]


def _document_id(document: Mapping[str, Any]) -> str:
    return str(document.get("_id") or document.get("id") or "").strip()


def _buyer_id(order: Mapping[str, Any]) -> str:
    return str(order.get("buyer_id") or "").strip()


def _shipment_id(order: Mapping[str, Any]) -> str:
    return str(order.get("shipment_id") or "").strip()


def _order_items(order: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw_items = order.get("items") or []
    if not isinstance(raw_items, Iterable) or isinstance(raw_items, (str, bytes)):
        return []
    return [item for item in raw_items if isinstance(item, Mapping)]


def _items_matching_sku(
    order: Mapping[str, Any], requested_sku: str, *, sku_resolver: _OrderSkuResolver
) -> list[Mapping[str, Any]]:
    return [item for item in _order_items(order) if sku_resolver.resolve(item).sku == requested_sku]


def _items_summary(
    items: Sequence[Mapping[str, Any]], sku_resolver: _OrderSkuResolver | None = None
) -> str:
    return ", ".join(
        summary for item in items if (summary := _item_summary(item, sku_resolver=sku_resolver))
    )


def _item_summary(item: Mapping[str, Any], sku_resolver: _OrderSkuResolver | None = None) -> str:
    sku = (
        sku_resolver.resolve(item).sku if sku_resolver else _normalize_optional_sku(_item_sku(item))
    )
    item_id = _item_id(item)
    quantity = _sheet_number(_item_quantity(item))
    if not sku and not item_id:
        return ""
    label = sku or item_id
    suffix = f" ({item_id})" if item_id and sku else ""
    return f"{label} x{quantity}{suffix}"


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


def _normalize_optional_sku(value: Any) -> str:
    if value is None:
        return ""
    return normalize_sku(value)


def _with_enrichment_meta(meta: dict[str, Any], *, enriched_count: int) -> dict[str, Any]:
    if not enriched_count:
        return meta
    return meta | {"sku_enriched_items": enriched_count}


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


def _unique_sku(rows: Sequence[Mapping[str, Any]]) -> str:
    normalized_skus = {
        normalized
        for row in rows
        if (normalized := _normalize_optional_sku(row.get("normalized_sku") or row.get("sku")))
    }
    if len(normalized_skus) != 1:
        return ""
    return next(iter(normalized_skus))


def _item_quantity(item: Mapping[str, Any]) -> Decimal:
    return _decimal(item.get("quantity", item.get("qty", 0)))


def _item_unit_price(item: Mapping[str, Any]) -> Decimal | None:
    for key in ("unit_price", "full_unit_price"):
        value = item.get(key)
        if value is not None:
            return _decimal(value)
    return None


def _order_in_range(order: Mapping[str, Any], date_range: _DateRange) -> bool:
    created = _optional_datetime(order.get("date_created"))
    if created is None:
        return False
    return date_range.start <= created <= date_range.end


def _question_status_counts(questions: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = {"answered": 0, "unanswered": 0, "removed": 0}
    for question in questions:
        status = str(question.get("status") or "").strip().upper()
        if status == "ANSWERED":
            counts["answered"] += 1
        elif status == "UNANSWERED":
            counts["unanswered"] += 1
        elif status in {"DELETED", "BANNED"}:
            counts["removed"] += 1
    return counts


def _question_in_hour_range(
    question: Mapping[str, Any], hour_range: _HourRange, *, timezone: tzinfo
) -> bool:
    created = _optional_datetime(question.get("date_created"))
    if created is None:
        return False
    question_time = created.astimezone(timezone).time().replace(tzinfo=None)
    if hour_range.start <= hour_range.end:
        return hour_range.start <= question_time <= hour_range.end
    return question_time >= hour_range.start or question_time <= hour_range.end


def _average_response_minutes(questions: Sequence[Mapping[str, Any]]) -> int:
    response_minutes: list[int] = []
    for question in questions:
        question_created = _optional_datetime(question.get("date_created"))
        answer = question.get("answer")
        if question_created is None or not isinstance(answer, Mapping):
            continue
        answer_created = _optional_datetime(
            answer.get("date_created") or answer.get("answered_at") or answer.get("created_at")
        )
        if answer_created is None or answer_created < question_created:
            continue
        response_minutes.append(round((answer_created - question_created).total_seconds() / 60))
    if not response_minutes:
        return 0
    return round(sum(response_minutes) / len(response_minutes))


def _current_value(row: Mapping[str, Any] | None, field: str) -> Any:
    if row is None:
        return ""
    current = row.get("current", {})
    if not isinstance(current, Mapping):
        return ""
    value = current.get(field)
    return "" if value is None else value


def _optional_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        return _parse_date_boundary(value, end_of_day=False)
    except (TypeError, ValueError):
        return None


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


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _sheet_number(value: Decimal) -> int | float:
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def _sheet_datetime(value: Any, *, timezone: tzinfo = UTC) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        parsed = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return parsed.astimezone(timezone).isoformat()
    if not _is_utc_timezone(timezone):
        try:
            parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except ValueError:
            return str(value).strip()
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(timezone).isoformat()
    return str(value).strip()


def _is_utc_timezone(timezone: tzinfo) -> bool:
    return timezone is UTC or getattr(timezone, "key", None) == "UTC"


def _context_timezone(context: FormulaExecutionContext) -> tzinfo:
    value = getattr(context, "seller_timezone", "UTC")
    if not isinstance(value, str) or not value.strip():
        return UTC
    try:
        return ZoneInfo(value.strip())
    except ZoneInfoNotFoundError:
        return UTC
