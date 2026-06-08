from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime, time, timedelta, tzinfo
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bson.decimal128 import Decimal128

from zeler_sheets.formulas.dispatcher import (
    FormulaExecutionContext,
    FormulaExecutionResult,
    FormulaHandler,
)
from zeler_sheets.formulas.output_normalization import NA_VALUE, normalize_response_rows
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
        "ZELERDATA_COMPRADORES",
        "ZELERDATA_PREGUNTAS",
        "ZELERDATA_PREGUNTASKPI",
    }
)

ORDER_LINE_LEGACY_HEADERS = [
    "Fecha",
    "ID Orden",
    "Título",
    "SKU",
    "ID Publicación",
    "Unidades Vendidas",
    "Precio",
    "ID Carrito",
    "% Comisión",
    "Comisión",
    "Costo Por Unidad",
    "Costo De Envío",
    "Status",
]
BUYER_ADDRESS_LEGACY_HEADERS = [
    "Nombre Comprador",
    "Calle",
    "Número",
    "Colonia",
    "Código Postal",
    "Ciudad",
    "Estado",
    "País",
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
    "Unidades Vendidas (7 días)",
    "Unidades Vendidas (15 días)",
    "Unidades Vendidas (30 días)",
    "Stock actual",
]
TOP_VENTAS_UNIDADES_MVP_HEADERS = ["ID Publicación", "SKU", "Título", "Unidades Vendidas"]
TOP_VENTAS_DINERO_MVP_HEADERS = [
    "ID Publicación",
    "SKU",
    "Título",
    "Unidades Vendidas",
    "Cantidad De Dinero",
]
PRODUCTOS_SIN_VENTA_LEGACY_HEADERS = [
    "Título",
    "Código ML",
    "ID Publicación",
    "SKU",
    "Stock Actual",
    "Fecha Ultimo Cambio",
    "Status Actual",
    "Envío A Cargo De",
]


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
        "ZELERDATA_COMPRADORES": handlers.sheetseller_compradores,
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
        buyer_selection = _buyer_selection(context.args.get("compradores", ""))
        orders = await self._repository.find_orders(
            seller_id=context.seller_id,
            date_from=date_range.start,
            date_to=date_range.end,
            status=status_filter,
        )
        filtered_orders = _filter_orders_by_buyers(orders, buyer_selection.buyer_filter)
        sku_resolver = await _sku_resolver_for_orders(
            repository=self._repository,
            seller_id=context.seller_id,
            orders=filtered_orders,
        )
        item_rows = await _item_formula_rows_for_orders(
            repository=self._repository,
            seller_id=context.seller_id,
            orders=filtered_orders,
            sku_resolver=sku_resolver,
        )
        order_lines = [
            (order, line)
            for order in filtered_orders
            for line in _order_lines(order, sku_resolver=sku_resolver)
        ]
        receiver_addresses = await _receiver_addresses_for_orders(
            repository=self._repository,
            seller_id=context.seller_id,
            orders=filtered_orders,
            enabled=buyer_selection.include_buyer_columns,
        )
        real_shipping_costs = await _real_shipping_costs_for_orders(
            repository=self._repository,
            seller_id=context.seller_id,
            orders=filtered_orders,
        )
        headers = _order_line_headers(include_buyer_columns=buyer_selection.include_buyer_columns)
        values: list[list[Any]] = _header_row(context.args.get("encabezados"), headers)
        header_rows = len(values)
        values.extend(
            _order_line_row(
                order,
                line,
                item_rows=item_rows,
                receiver_addresses=receiver_addresses,
                real_shipping_costs=real_shipping_costs,
                timezone=timezone,
                include_buyer_columns=buyer_selection.include_buyer_columns,
            )
            for order, line in order_lines
        )
        return FormulaExecutionResult(
            values=normalize_response_rows(values, header_rows=header_rows),
            meta={
                "orders_count": len(filtered_orders),
                "status_filter": status_filter or "todos",
                "buyer_filter_count": len(buyer_selection.buyer_filter),
                "columns": _order_line_columns_meta(
                    include_buyer_columns=buyer_selection.include_buyer_columns
                ),
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
        buyer_selection = _buyer_selection(context.args.get("compradores", ""))
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
        filtered_orders = _filter_orders_by_buyers(orders, buyer_selection.buyer_filter)
        item_rows = await _item_formula_rows_for_orders(
            repository=self._repository,
            seller_id=context.seller_id,
            orders=filtered_orders,
            sku_resolver=sku_resolver,
        )
        filtered_lines = [
            (order, line)
            for requested_sku in dict.fromkeys(requested_skus)
            for order in filtered_orders
            for line in _order_lines(order, sku_resolver=sku_resolver)
            if line.sku == requested_sku
        ]
        receiver_addresses = await _receiver_addresses_for_orders(
            repository=self._repository,
            seller_id=context.seller_id,
            orders=filtered_orders,
            enabled=buyer_selection.include_buyer_columns,
        )
        real_shipping_costs = await _real_shipping_costs_for_orders(
            repository=self._repository,
            seller_id=context.seller_id,
            orders=[order for order, _line in filtered_lines],
        )
        headers = _order_line_headers(include_buyer_columns=buyer_selection.include_buyer_columns)
        values: list[list[Any]] = _header_row(context.args.get("encabezados"), headers)
        header_rows = len(values)
        for order, line in filtered_lines:
            values.append(
                _order_line_row(
                    order,
                    line,
                    item_rows=item_rows,
                    receiver_addresses=receiver_addresses,
                    real_shipping_costs=real_shipping_costs,
                    timezone=timezone,
                    include_buyer_columns=buyer_selection.include_buyer_columns,
                )
            )
        rows_count = len(values) - (1 if _headers_requested(context.args.get("encabezados")) else 0)
        return FormulaExecutionResult(
            values=normalize_response_rows(values, header_rows=header_rows),
            meta={
                "orders_count": rows_count,
                "status_filter": status_filter or "todos",
                "buyer_filter_count": len(buyer_selection.buyer_filter),
                "sku_filter_count": len(dict.fromkeys(requested_skus)),
                "columns": _order_line_columns_meta(
                    include_buyer_columns=buyer_selection.include_buyer_columns
                ),
            },
        )

    async def sheetseller_compradores(
        self, context: FormulaExecutionContext
    ) -> FormulaExecutionResult:
        requested_order_ids = _flatten_sheet_values(
            context.args.get("id_ordenes"), normalize=lambda order_id: str(order_id).strip()
        )
        orders = await self._repository.find_orders_by_ids(
            seller_id=context.seller_id,
            order_ids=requested_order_ids,
            limit=max(1000, len(requested_order_ids)),
        )
        orders_by_id = {_document_id(order): order for order in orders}
        ordered_orders = [
            orders_by_id[order_id]
            for order_id in dict.fromkeys(requested_order_ids)
            if order_id in orders_by_id
        ]
        receiver_addresses = await _receiver_addresses_for_orders(
            repository=self._repository,
            seller_id=context.seller_id,
            orders=ordered_orders,
            enabled=True,
        )
        values: list[list[Any]] = _header_row(
            context.args.get("encabezados"), BUYER_ADDRESS_LEGACY_HEADERS
        )
        values.extend(
            _buyer_address_values(_receiver_address_for_order(order, receiver_addresses))
            for order in ordered_orders
        )
        address_available = sum(
            1
            for order in ordered_orders
            if _address_has_source_values(_receiver_address_for_order(order, receiver_addresses))
        )
        return FormulaExecutionResult(
            values=values,
            meta={
                "orders_count": len(ordered_orders),
                "address_available": address_available,
                "address_missing": len(ordered_orders) - address_available,
                "columns": "buyer_address_snapshot",
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
        sku_resolver = await _sku_resolver_for_orders(
            repository=self._repository,
            seller_id=context.seller_id,
            orders=orders,
        )
        recent_totals, enriched_count = _unit_totals_by_pair(orders, sku_resolver=sku_resolver)
        values: list[list[Any]] = _header_row(
            context.args.get("encabezados"),
            PRODUCTOS_SIN_VENTA_LEGACY_HEADERS,
        )
        header_rows = len(values)
        for row in ordered_rows:
            sku = normalize_sku(row.get("normalized_sku") or row.get("sku"))
            item_id = str(row.get("item_id") or "").strip()
            if not sku or not item_id:
                continue
            if recent_totals.get((sku, item_id), Decimal("0")) > 0:
                continue
            values.append(
                [
                    _current_value(row, "title"),
                    _inventory_code(row),
                    item_id,
                    row.get("sku") or sku,
                    _current_value(row, "available_quantity"),
                    NA_VALUE,
                    _current_value(row, "status"),
                    _current_value(row, "shipping_payer"),
                ]
            )
        header_count = 1 if _headers_requested(context.args.get("encabezados")) else 0
        return FormulaExecutionResult(
            values=normalize_response_rows(values, header_rows=header_rows),
            meta={
                "rows_count": len(values) - header_count,
                "orders_count": len(orders),
                "rango_dias": range_days,
                "columns": "legacy_products_without_sales",
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
                "columns": "legacy_sales_and_stock",
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
        item_rows = await _item_formula_rows_for_pairs(
            repository=self._repository,
            seller_id=context.seller_id,
            pairs=[pair for pair, _units in ranked],
        )
        values: list[list[Any]] = _header_row(
            context.args.get("encabezados"), TOP_VENTAS_UNIDADES_MVP_HEADERS
        )
        values.extend(
            [
                item_id,
                sku,
                _title_for_pair(item_rows, sku=sku, item_id=item_id),
                _sheet_number(units),
            ]
            for (sku, item_id), units in ranked
        )
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
        unit_totals, _ = _unit_totals_by_pair(orders, sku_resolver=sku_resolver)
        ranked = sorted(totals.items(), key=lambda entry: (-entry[1], entry[0][0], entry[0][1]))[
            :top_count
        ]
        item_rows = await _item_formula_rows_for_pairs(
            repository=self._repository,
            seller_id=context.seller_id,
            pairs=[pair for pair, _revenue in ranked],
        )
        values: list[list[Any]] = _header_row(
            context.args.get("encabezados"), TOP_VENTAS_DINERO_MVP_HEADERS
        )
        values.extend(
            [
                [
                    item_id,
                    sku,
                    _title_for_pair(item_rows, sku=sku, item_id=item_id),
                    _sheet_number(unit_totals.get((sku, item_id), Decimal("0"))),
                    _sheet_number(revenue),
                ]
                for (sku, item_id), revenue in ranked
            ]
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


class _BuyerSelection:
    def __init__(self, *, buyer_filter: set[str], include_buyer_columns: bool) -> None:
        self.buyer_filter = buyer_filter
        self.include_buyer_columns = include_buyer_columns


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
            if any(_normalize_variation_id(row.get("variation_id")) for row in rows):
                return _SkuResolution(sku="", enriched=False)
            rows = [row for row in rows if not _normalize_variation_id(row.get("variation_id"))]

        sku = _unique_sku(rows)
        return _SkuResolution(sku=sku, enriched=bool(sku))


class _OrderLine:
    def __init__(
        self,
        *,
        sku: str,
        item_id: str,
        title: str,
        quantity: Decimal,
        unit_price: Decimal | None,
        sale_fee: Decimal | None,
        sale_fee_source: str | None,
        sale_fee_synced_at: datetime | None,
        variation_id: str,
        enriched: bool,
    ) -> None:
        self.sku = sku
        self.item_id = item_id
        self.title = title
        self.quantity = quantity
        self.unit_price = unit_price
        self.sale_fee = sale_fee
        self.sale_fee_source = sale_fee_source
        self.sale_fee_synced_at = sale_fee_synced_at
        self.variation_id = variation_id
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


def _buyer_selection(value: Any) -> _BuyerSelection:
    buyer_flag = _buyer_boolean_flag(value)
    if buyer_flag is not None:
        return _BuyerSelection(buyer_filter=set(), include_buyer_columns=buyer_flag)
    buyer_filter = _buyer_filter(value)
    return _BuyerSelection(
        buyer_filter=buyer_filter,
        include_buyer_columns=bool(buyer_filter),
    )


def _buyer_boolean_flag(value: Any) -> bool | None:
    flattened = _flatten_sheet_values(value, normalize=lambda item: str(item).strip().casefold())
    if len(flattened) != 1:
        return None
    if flattened[0] in {"si", "sí", "verdadero", "true", "1", "yes"}:
        return True
    if flattened[0] in {"no", "falso", "false", "0"}:
        return False
    return None


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
    rows = await repository.find_sku_index_rows(
        seller_id=seller_id,
        item_ids=item_ids,
        variation_ids=None,
        limit=max(500, len(item_ids) * 10),
    )
    return _OrderSkuResolver(rows)


async def _item_formula_rows_for_orders(
    *,
    repository: FormulaReadModelRepository,
    seller_id: str,
    orders: Sequence[Mapping[str, Any]],
    sku_resolver: _OrderSkuResolver,
) -> dict[tuple[str, str], Mapping[str, Any]]:
    pairs = [
        (sku_resolver.resolve(item).sku, _item_id(item))
        for order in orders
        for item in _order_items(order)
        if sku_resolver.resolve(item).sku and _item_id(item)
    ]
    return await _item_formula_rows_for_pairs(
        repository=repository,
        seller_id=seller_id,
        pairs=pairs,
    )


async def _item_formula_rows_for_pairs(
    *,
    repository: FormulaReadModelRepository,
    seller_id: str,
    pairs: Sequence[tuple[str, str]],
) -> dict[tuple[str, str], Mapping[str, Any]]:
    normalized_pairs = list(
        dict.fromkeys((sku, item_id) for sku, item_id in pairs if sku and item_id)
    )
    if not normalized_pairs:
        return {}
    rows = await repository.find_item_formula_rows(
        seller_id=seller_id,
        skus=[sku for sku, _item_id in normalized_pairs],
        item_ids=[item_id for _sku, item_id in normalized_pairs],
        limit=max(500, len(normalized_pairs) * 2),
    )
    return {
        (
            normalize_sku(row.get("normalized_sku") or row.get("sku")),
            str(row.get("item_id") or ""),
        ): row
        for row in rows
    }


async def _real_shipping_costs_for_orders(
    *,
    repository: FormulaReadModelRepository,
    seller_id: str,
    orders: Sequence[Mapping[str, Any]],
) -> dict[str, Decimal]:
    shipment_ids = list(
        dict.fromkeys(shipment_id for order in orders if (shipment_id := _shipment_id(order)))
    )
    if not shipment_ids:
        return {}
    return await repository.find_shipment_real_shipping_costs(
        seller_id=seller_id,
        shipment_ids=shipment_ids,
        limit=max(1000, len(shipment_ids)),
    )


async def _receiver_addresses_for_orders(
    *,
    repository: FormulaReadModelRepository,
    seller_id: str,
    orders: Sequence[Mapping[str, Any]],
    enabled: bool,
) -> dict[str, dict[str, Any]]:
    if not enabled:
        return {}
    shipment_ids = list(
        dict.fromkeys(shipment_id for order in orders if (shipment_id := _shipment_id(order)))
    )
    if not shipment_ids:
        return {}
    return await repository.find_shipment_receiver_addresses(
        seller_id=seller_id,
        shipment_ids=shipment_ids,
        limit=max(1000, len(shipment_ids)),
    )


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
        if not item_id:
            continue
        lines.append(
            _OrderLine(
                sku=resolution.sku,
                item_id=item_id,
                title=_item_title(item),
                quantity=_item_quantity(item),
                unit_price=_item_unit_price(item),
                sale_fee=_item_sale_fee(item),
                sale_fee_source=_item_sale_fee_source(item),
                sale_fee_synced_at=_optional_datetime(item.get("sale_fee_synced_at")),
                variation_id=_item_variation_id(item),
                enriched=resolution.enriched,
            )
        )
    return lines


def _order_line_row(
    order: Mapping[str, Any],
    line: _OrderLine,
    *,
    item_rows: Mapping[tuple[str, str], Mapping[str, Any]],
    receiver_addresses: Mapping[str, Mapping[str, Any]],
    real_shipping_costs: Mapping[str, Any],
    timezone: tzinfo,
    include_buyer_columns: bool,
) -> list[Any]:
    row = item_rows.get((line.sku, line.item_id))
    commission_percent, commission_amount, commission_unit_cost = _realized_commission_values(line)
    values = [
        _sheet_datetime(order.get("date_created"), timezone=timezone),
        _document_id(order),
        line.title or _current_value(row, "title"),
        line.sku,
        line.item_id,
        _sheet_number(line.quantity),
        "" if line.unit_price is None else _sheet_number(line.unit_price),
        _order_meli_pack_id(order),
        commission_percent,
        commission_amount,
        commission_unit_cost,
        _shipment_real_shipping_cost_value(order, real_shipping_costs),
        order.get("status") or "",
    ]
    if include_buyer_columns:
        values.extend(_buyer_address_values(_receiver_address_for_order(order, receiver_addresses)))
    return values


def _realized_commission_values(line: _OrderLine) -> tuple[Any, Any, Any]:
    if (
        line.sale_fee is None
        or line.unit_price is None
        or line.quantity <= 0
        or line.unit_price <= 0
        or line.sale_fee_source != "/orders/{id}"
        or line.sale_fee_synced_at is None
    ):
        return NA_VALUE, NA_VALUE, NA_VALUE
    unit_cost = line.sale_fee / line.quantity
    percent = (unit_cost / line.unit_price) * Decimal("100")
    return _sheet_number(percent), _sheet_number(line.sale_fee), _sheet_number(unit_cost)


def _order_meli_pack_id(order: Mapping[str, Any]) -> str:
    value = order.get("meli_pack_id")
    if value is None:
        return NA_VALUE
    normalized = str(value).strip()
    return normalized or NA_VALUE


def _listing_fixed_fee(row: Mapping[str, Any] | None) -> Any:
    if row is None:
        return NA_VALUE
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
    fixed_fee = _fixed_fee_decimal(projection.get("fixed_fee"))
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
    current_decimal = _fixed_fee_decimal(current_value)
    param_decimal = _fixed_fee_decimal(param_value)
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


def _fixed_fee_decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, Decimal128):
        decimal_value = value.to_decimal()
    elif isinstance(value, Decimal):
        decimal_value = value
    elif isinstance(value, int):
        decimal_value = Decimal(value)
    elif isinstance(value, float):
        decimal_value = Decimal(str(value))
    else:
        try:
            decimal_value = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
    return decimal_value if decimal_value.is_finite() and decimal_value >= 0 else None


def _order_line_headers(*, include_buyer_columns: bool) -> list[str]:
    if not include_buyer_columns:
        return ORDER_LINE_LEGACY_HEADERS
    return ORDER_LINE_LEGACY_HEADERS + BUYER_ADDRESS_LEGACY_HEADERS


def _order_line_columns_meta(*, include_buyer_columns: bool) -> str:
    return "legacy_order_lines_with_buyers" if include_buyer_columns else "legacy_order_lines"


def _buyer_address_values(address: Mapping[str, Any]) -> list[Any]:
    return [
        _address_value(address, "name"),
        _address_value(address, "street_name"),
        _address_value(address, "street_number"),
        _address_value(address, "neighborhood", "colonia"),
        _address_value(address, "zip_code"),
        _address_value(address, "city"),
        _address_value(address, "state"),
        _address_value(address, "country"),
    ]


def _address_value(address: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = address.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return NA_VALUE


def _receiver_address_for_order(
    order: Mapping[str, Any], receiver_addresses: Mapping[str, Mapping[str, Any]]
) -> Mapping[str, Any]:
    shipment_id = _shipment_id(order)
    if not shipment_id:
        return {}
    return receiver_addresses.get(shipment_id, {})


def _shipment_real_shipping_cost_value(
    order: Mapping[str, Any], real_shipping_costs: Mapping[str, Any]
) -> Any:
    shipment_id = _shipment_id(order)
    if not shipment_id:
        return NA_VALUE
    cost = _optional_non_negative_decimal(real_shipping_costs.get(shipment_id))
    if cost is None:
        return NA_VALUE
    return _sheet_number(cost)


def _address_has_source_values(address: Mapping[str, Any]) -> bool:
    return any(value != NA_VALUE for value in _buyer_address_values(address))


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


def _item_title(item: Mapping[str, Any]) -> str:
    raw_nested_item = item.get("item")
    nested_item: Mapping[str, Any] = raw_nested_item if isinstance(raw_nested_item, Mapping) else {}
    return str(item.get("title") or nested_item.get("title") or "").strip()


def _normalize_optional_sku(value: Any) -> str:
    if value is None:
        return ""
    return normalize_sku(value)


def _with_enrichment_meta(meta: dict[str, Any], *, enriched_count: int) -> dict[str, Any]:
    if not enriched_count:
        return meta
    return meta | {"sku_enriched_items": enriched_count}


def _inventory_code(row: Mapping[str, Any]) -> Any:
    return row.get("inventory_id") or _current_value(row, "inventory_id")


def _title_for_pair(
    rows_by_pair: Mapping[tuple[str, str], Mapping[str, Any]], *, sku: str, item_id: str
) -> Any:
    return _current_value(rows_by_pair.get((sku, item_id)), "title")


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


def _item_sale_fee(item: Mapping[str, Any]) -> Decimal | None:
    return _optional_non_negative_decimal(item.get("sale_fee"))


def _item_sale_fee_source(item: Mapping[str, Any]) -> str | None:
    value = item.get("sale_fee_source")
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


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


def _optional_non_negative_decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, (bool, dict, list, tuple, set)):
        return None
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite() or parsed < 0:
        return None
    return parsed


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
