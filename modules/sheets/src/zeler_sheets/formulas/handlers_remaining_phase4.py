from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
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
from zeler_sheets.formulas.read_models import (
    CATALOG_BUYBOX_SNAPSHOTS_READ_MODEL,
    CATALOG_TIME_METRICS_READ_MODEL,
    FULL_WITHDRAWALS_READ_MODEL,
    ITEM_FORMULA_ROWS_READ_MODEL,
    ORDERS_READ_MODEL,
    PRICE_HISTORY_SNAPSHOTS_READ_MODEL,
    STOCK_TIME_METRICS_READ_MODEL,
    STOCKOUT_SNAPSHOTS_READ_MODEL,
    FormulaReadModelRepository,
    normalize_sku,
)

REMAINING_PHASE4_IMPLEMENTED_FORMULAS = frozenset(
    {
        "ZELERDATA_CATALOGO",
        "ZELERDATA_TIEMPOSINSTOCK",
        "ZELERDATA_TIEMPOSTOCKACTIVO",
        "ZELERDATA_SEMANASCONSTOCK",
        "ZELERDATA_PRECIOHISTORICO",
        "ZELERDATA_CATALOGOTIEMPO",
        "ZELERDATA_RETIROS",
    }
)

CATALOGO_HEADERS = [
    "ID CATALOGO",
    "URL CATALOGO",
    "ID PUBLICACION",
    "URL",
    "TITULO",
    "SKU",
    "CODIGO ML",
    "ENVIO A CARGO DE",
    "STOCK ACTUAL",
    "VENTAS 7 DIAS",
    "VENTAS 15 DIAS",
    "VENTAS 30 DIAS",
    "VENTAS 60 DIAS",
    "VENTAS 90 DIAS",
    "VENTAS 365 DIAS",
    "STATUS PUBLICACION CATALOGO",
    "STATUS WINNER CATALOGO",
    "% TIEMPO GANANDO CATALOGO SOBRE EL COMPETIDO",
    "PRECIO GANADOR CATALOGO",
    "MI PRECIO ACTUAL CATALOGO",
    "USUARIO GANADOR CATALOGO",
    "COMPARTIENDO CATALOGO CON USUARIOS",
    "PRICE TO WIN",
    "UNICO COMPETIDOR",
]
TIEMPOS_SIN_STOCK_HEADERS = [
    "ID PUBLICACION",
    "TITULO",
    "SKU",
    "PRECIO",
    "LOGISTICA",
    "URL",
    "STATUS",
    "TIEMPO SIN STOCK",
]
TIEMPO_STOCK_ACTIVO_HEADERS = [
    "ID PUBLICACION",
    "SKU",
    "TITULO",
    "URL",
    "TIEMPO ACTIVA",
    "TIEMPO TOTAL",
    "% TIEMPO ACTIVA",
]
PRECIO_HISTORICO_HEADERS = [
    "ID PUBLICACION",
    "TITULO",
    "PRECIO 1",
    "STATUS 1",
    "PRECIO 2",
    "STATUS 2",
    "PRECIO 3",
    "STATUS 3",
]
CATALOGOTIEMPO_HEADERS = [
    "ID PUBLICACION",
    "TITULO",
    "URL",
    "TIEMPO GANANDO CATALOGO EN HORAS",
    "TOTAL DE HORAS DISPONIBLE EN CATALOGO",
    "% DE TIEMPO GANANDO CATALOGO",
]
RETIROS_HEADERS = [
    "ID PRINCIPAL RETIRO",
    "ID SECUNDARIO RETIRO",
    "CODIGO ML",
    "ID PUBLICACION",
    "SKU",
    "TITULO",
    "UNIDADES SOLICITADAS",
    "FECHA DE CREACION",
    "FECHA DE ENTREGA",
]
SEMANAS_CON_STOCK_BASE_HEADERS = ["ID PUBLICACION", "SKU", "TITULO"]
NON_PRODUCTIVE_ORDER_STATUSES = frozenset({"cancelled", "canceled"})
CATALOGO_SALES_WINDOWS = (7, 15, 30, 60, 90, 365)


def build_remaining_phase4_formula_handlers(
    repository: FormulaReadModelRepository,
    *,
    now_fn: Callable[[], datetime] | None = None,
) -> dict[str, FormulaHandler]:
    handlers = RemainingPhase4FormulaHandlers(repository, now_fn=now_fn)
    return {
        "ZELERDATA_CATALOGO": handlers.sheetseller_catalogo,
        "ZELERDATA_TIEMPOSINSTOCK": handlers.sheetseller_tiempos_sin_stock,
        "ZELERDATA_TIEMPOSTOCKACTIVO": handlers.sheetseller_tiempo_stock_activo,
        "ZELERDATA_SEMANASCONSTOCK": handlers.sheetseller_semanas_con_stock,
        "ZELERDATA_PRECIOHISTORICO": handlers.sheetseller_precio_historico,
        "ZELERDATA_CATALOGOTIEMPO": handlers.sheetseller_catalogo_tiempo,
        "ZELERDATA_RETIROS": handlers.sheetseller_retiros,
    }


class RemainingPhase4FormulaHandlers:
    def __init__(
        self,
        repository: FormulaReadModelRepository,
        *,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._now_fn = now_fn or (lambda: datetime.now(UTC))

    async def sheetseller_catalogo(
        self, context: FormulaExecutionContext
    ) -> FormulaExecutionResult:
        now = _as_utc_datetime(self._now_fn())
        await self._repository.require_read_model_productive(
            seller_id=context.seller_id,
            read_model=CATALOG_BUYBOX_SNAPSHOTS_READ_MODEL,
            date_to=now,
            formula=context.contract.name,
        )
        await self._repository.require_read_model_productive(
            seller_id=context.seller_id,
            read_model=ITEM_FORMULA_ROWS_READ_MODEL,
            date_to=now,
            formula=context.contract.name,
        )
        await self._repository.require_read_model_productive(
            seller_id=context.seller_id,
            read_model=ORDERS_READ_MODEL,
            date_to=now,
            formula=context.contract.name,
        )
        rows = await self._repository.find_item_formula_rows(
            seller_id=context.seller_id,
            limit=None,
            sort_by="publication",
        )
        catalog_rows = [
            row for row in rows if _non_blank(_current_mapping(row).get("catalog_product_id"))
        ]
        buybox_rows = await self._repository.find_catalog_buybox_snapshots(
            seller_id=context.seller_id,
            limit=max(1000, len(catalog_rows)),
        )
        buybox_by_item_id = {
            str(row.get("item_id") or "").strip(): row for row in buybox_rows if row.get("item_id")
        }
        orders = await self._repository.find_orders(
            seller_id=context.seller_id,
            date_from=now - timedelta(days=max(CATALOGO_SALES_WINDOWS)),
            date_to=_day_end(now),
            limit=5000,
        )
        sales_by_item = _sales_windows_by_item(orders, now=now)
        values: list[list[Any]] = _header_row(context.args.get("encabezados"), CATALOGO_HEADERS)
        header_rows = len(values)
        values.extend(
            _catalogo_row(
                row,
                buybox=buybox_by_item_id.get(str(row.get("item_id") or "").strip()),
                sales=sales_by_item.get(str(row.get("item_id") or "").strip(), {}),
                tipo_precio=context.args.get("tipo_precio", "base"),
            )
            for row in catalog_rows
        )
        return FormulaExecutionResult(
            values=normalize_response_rows(values, header_rows=header_rows),
            meta={"rows_count": len(catalog_rows), "columns": "legacy_catalog_matrix"},
        )

    async def sheetseller_tiempos_sin_stock(
        self, context: FormulaExecutionContext
    ) -> FormulaExecutionResult:
        now = _as_utc_datetime(self._now_fn())
        await self._repository.require_read_model_productive(
            seller_id=context.seller_id,
            read_model=STOCKOUT_SNAPSHOTS_READ_MODEL,
            date_to=now,
            formula=context.contract.name,
        )
        snapshots = await self._repository.find_stockout_snapshots(
            seller_id=context.seller_id,
            limit=1000,
        )
        out_of_stock = [snapshot for snapshot in snapshots if _is_currently_out_of_stock(snapshot)]
        values: list[list[Any]] = _header_row(
            context.args.get("encabezados"), TIEMPOS_SIN_STOCK_HEADERS
        )
        header_rows = len(values)
        values.extend(
            _stockout_row(snapshot, now=now, tipo_precio=context.args.get("tipo_precio", "base"))
            for snapshot in out_of_stock
        )
        return FormulaExecutionResult(
            values=normalize_response_rows(values, header_rows=header_rows),
            meta={"rows_count": len(out_of_stock), "columns": "stockout_duration"},
        )

    async def sheetseller_tiempo_stock_activo(
        self, context: FormulaExecutionContext
    ) -> FormulaExecutionResult:
        date_from = _day_start(_parse_date(context.args.get("fecha_inicial")))
        date_to = _day_after(_parse_date(context.args.get("fecha_final")))
        await self._repository.require_read_model_reconciled_range(
            seller_id=context.seller_id,
            read_model=STOCK_TIME_METRICS_READ_MODEL,
            date_from=date_from,
            date_to=date_to,
            formula=context.contract.name,
        )
        item_ids = _normalize_optional_item_ids(context.args.get("id_publicaciones", "todos"))
        metrics = await self._repository.find_stock_time_metrics(
            seller_id=context.seller_id,
            date_from=date_from,
            date_to=date_to,
            item_ids=item_ids,
            limit=1000,
        )
        values: list[list[Any]] = _header_row(
            context.args.get("encabezados"), TIEMPO_STOCK_ACTIVO_HEADERS
        )
        header_rows = len(values)
        values.extend(_stock_time_row(metric) for metric in metrics)
        return FormulaExecutionResult(
            values=normalize_response_rows(values, header_rows=header_rows),
            meta={"rows_count": len(metrics), "columns": "stock_time_metrics"},
        )

    async def sheetseller_semanas_con_stock(
        self, context: FormulaExecutionContext
    ) -> FormulaExecutionResult:
        date_from = _day_start(_parse_date(context.args.get("fecha_inicial")))
        date_to = _day_after(_parse_date(context.args.get("fecha_final")))
        await self._repository.require_read_model_reconciled_range(
            seller_id=context.seller_id,
            read_model=STOCK_TIME_METRICS_READ_MODEL,
            date_from=date_from,
            date_to=date_to,
            formula=context.contract.name,
        )
        item_ids = _normalize_optional_item_ids(context.args.get("id_publicaciones", "todos"))
        skus = _normalize_optional_skus(context.args.get("skus", "todos"))
        metrics = await self._repository.find_stock_time_metrics(
            seller_id=context.seller_id,
            date_from=date_from,
            date_to=date_to,
            item_ids=item_ids,
            skus=skus,
            limit=1000,
        )
        week_headers = _week_headers(metrics)
        headers = [*SEMANAS_CON_STOCK_BASE_HEADERS, *week_headers]
        values: list[list[Any]] = _header_row(context.args.get("encabezados"), headers)
        header_rows = len(values)
        values.extend(_weekly_stock_row(metric, week_headers=week_headers) for metric in metrics)
        return FormulaExecutionResult(
            values=normalize_response_rows(values, header_rows=header_rows),
            meta={"rows_count": len(metrics), "columns": "weekly_stock_presence"},
        )

    async def sheetseller_precio_historico(
        self, context: FormulaExecutionContext
    ) -> FormulaExecutionResult:
        await self._repository.require_read_model_productive(
            seller_id=context.seller_id,
            read_model=PRICE_HISTORY_SNAPSHOTS_READ_MODEL,
            date_to=_as_utc_datetime(self._now_fn()),
            formula=context.contract.name,
        )
        item_ids = _normalize_optional_item_ids(context.args.get("id_publicaciones", "todos"))
        rows = await self._repository.find_price_history_snapshots(
            seller_id=context.seller_id,
            item_ids=item_ids,
            limit=1000,
        )
        values: list[list[Any]] = _header_row(
            context.args.get("encabezados"), PRECIO_HISTORICO_HEADERS
        )
        header_rows = len(values)
        values.extend(
            _price_history_row(row, tipo_precio=context.args.get("tipo_precio", "base"))
            for row in rows
        )
        return FormulaExecutionResult(
            values=normalize_response_rows(values, header_rows=header_rows),
            meta={"rows_count": len(rows), "columns": "price_history"},
        )

    async def sheetseller_catalogo_tiempo(
        self, context: FormulaExecutionContext
    ) -> FormulaExecutionResult:
        date_from = _day_start(_parse_date(context.args.get("fecha_inicial")))
        date_to = _day_after(_parse_date(context.args.get("fecha_final")))
        await self._repository.require_read_model_reconciled_range(
            seller_id=context.seller_id,
            read_model=CATALOG_TIME_METRICS_READ_MODEL,
            date_from=date_from,
            date_to=date_to,
            formula=context.contract.name,
        )
        item_ids = _normalize_optional_item_ids(context.args.get("id_publicaciones", "todos"))
        metrics = await self._repository.find_catalog_time_metrics(
            seller_id=context.seller_id,
            date_from=date_from,
            date_to=date_to,
            item_ids=item_ids,
            limit=1000,
        )
        values: list[list[Any]] = _header_row(
            context.args.get("encabezados"), CATALOGOTIEMPO_HEADERS
        )
        header_rows = len(values)
        values.extend(_catalog_time_row(metric) for metric in metrics)
        return FormulaExecutionResult(
            values=normalize_response_rows(values, header_rows=header_rows),
            meta={"rows_count": len(metrics), "columns": "catalog_winning_time"},
        )

    async def sheetseller_retiros(self, context: FormulaExecutionContext) -> FormulaExecutionResult:
        date_from = _day_start(_parse_date(context.args.get("fecha_inicial")))
        date_to = _day_after(_parse_date(context.args.get("fecha_final")))
        await self._repository.require_read_model_reconciled_range(
            seller_id=context.seller_id,
            read_model=FULL_WITHDRAWALS_READ_MODEL,
            date_from=date_from,
            date_to=date_to,
            formula=context.contract.name,
        )
        rows = await self._repository.find_full_withdrawals(
            seller_id=context.seller_id,
            date_from=date_from,
            date_to=date_to,
            limit=1000,
        )
        values: list[list[Any]] = _header_row(context.args.get("encabezados"), RETIROS_HEADERS)
        header_rows = len(values)
        values.extend(_withdrawal_row(row) for row in rows)
        return FormulaExecutionResult(
            values=normalize_response_rows(values, header_rows=header_rows),
            meta={"rows_count": len(rows), "columns": "full_withdrawals"},
        )


class _OrderLine:
    def __init__(self, *, item_id: str, quantity: Decimal) -> None:
        self.item_id = item_id
        self.quantity = quantity


def _catalogo_row(
    row: Mapping[str, Any],
    *,
    buybox: Mapping[str, Any] | None,
    sales: Mapping[int, Decimal],
    tipo_precio: Any,
) -> list[Any]:
    current = _current_mapping(row)
    catalog_product_id = _current_value(current, "catalog_product_id")
    return [
        catalog_product_id,
        _first_value(buybox, "catalog_url", "catalog_permalink", "url"),
        str(row.get("item_id") or ""),
        _current_value(current, "permalink", "url"),
        _current_value(current, "title"),
        row.get("sku") or row.get("normalized_sku") or NA_VALUE,
        row.get("inventory_id") or _current_value(current, "inventory_id"),
        _current_value(current, "shipping_payer"),
        _sheet_optional_number(current.get("available_quantity")),
        *[_sheet_optional_number(sales.get(window)) for window in CATALOGO_SALES_WINDOWS],
        _current_value(current, "status"),
        _first_value(buybox, "buybox_status", "winner_status", "status"),
        _sheet_optional_number(
            _first_value(buybox, "winning_time_percent", "winning_percent", "catalog_win_percent")
        ),
        _sheet_optional_number(_first_value(buybox, "winning_price", "winner_price")),
        _selected_price(current, tipo_precio=tipo_precio),
        _first_value(buybox, "winning_user_id", "winner_user_id", "winner_user"),
        _sheet_optional_number(_first_value(buybox, "competitor_count", "shared_users_count")),
        _sheet_optional_number(_first_value(buybox, "price_to_win", "price_to_win_amount")),
        _first_value(buybox, "only_competitor", "unico_competidor"),
    ]


def _stockout_row(snapshot: Mapping[str, Any], *, now: datetime, tipo_precio: Any) -> list[Any]:
    started_at = _first_datetime(
        snapshot.get("out_of_stock_since"),
        snapshot.get("started_at"),
        snapshot.get("observed_at"),
    )
    return [
        _document_item_id(snapshot),
        _snapshot_value(snapshot, "title"),
        _snapshot_value(snapshot, "sku", "normalized_sku"),
        _selected_price(snapshot, tipo_precio=tipo_precio),
        _snapshot_value(snapshot, "logistic_type", "shipping_logistic_type"),
        _snapshot_value(snapshot, "url", "permalink"),
        _snapshot_value(snapshot, "status"),
        max((now.date() - started_at.date()).days, 0) if started_at is not None else NA_VALUE,
    ]


def _stock_time_row(metric: Mapping[str, Any]) -> list[Any]:
    return [
        _document_item_id(metric),
        _snapshot_value(metric, "sku", "normalized_sku"),
        _snapshot_value(metric, "title"),
        _snapshot_value(metric, "url", "permalink"),
        _sheet_optional_number(metric.get("active_stock_hours")),
        _sheet_optional_number(metric.get("total_hours")),
        _sheet_optional_number(metric.get("active_stock_percent")),
    ]


def _weekly_stock_row(metric: Mapping[str, Any], *, week_headers: Sequence[str]) -> list[Any]:
    weeks_by_header = {_week_header(week): week for week in _weeks(metric)}
    return [
        _document_item_id(metric),
        _snapshot_value(metric, "sku", "normalized_sku"),
        _snapshot_value(metric, "title"),
        *[_weekly_stock_cell(weeks_by_header.get(header)) for header in week_headers],
    ]


def _price_history_row(row: Mapping[str, Any], *, tipo_precio: Any) -> list[Any]:
    prices = _history_entries(row, preferred_key="prices", fallback_key=f"{tipo_precio}_prices")[:3]
    flattened: list[Any] = []
    for entry in prices:
        flattened.extend(
            [
                _sheet_optional_number(_first_value(entry, "price", "amount")),
                _snapshot_value(entry, "status", "state"),
            ]
        )
    while len(flattened) < 6:
        flattened.append(NA_VALUE)
    return [_document_item_id(row), _snapshot_value(row, "title"), *flattened]


def _catalog_time_row(metric: Mapping[str, Any]) -> list[Any]:
    return [
        _document_item_id(metric),
        _snapshot_value(metric, "title"),
        _snapshot_value(metric, "url", "permalink"),
        _sheet_optional_number(metric.get("winning_hours")),
        _sheet_optional_number(_first_value(metric, "available_hours", "total_hours")),
        _sheet_optional_number(_first_value(metric, "winning_percent", "winning_time_percent")),
    ]


def _withdrawal_row(row: Mapping[str, Any]) -> list[Any]:
    return [
        _snapshot_value(row, "withdrawal_id", "id"),
        _snapshot_value(row, "withdrawal_detail_id", "detail_id", "secondary_id"),
        _snapshot_value(row, "inventory_id", "codigo_ml"),
        _document_item_id(row),
        _snapshot_value(row, "sku", "normalized_sku"),
        _snapshot_value(row, "title"),
        _sheet_optional_number(_first_value(row, "requested_quantity", "quantity")),
        _datetime_cell(row.get("created_at")),
        _datetime_cell(row.get("delivered_at")),
    ]


def _sales_windows_by_item(
    orders: Sequence[Mapping[str, Any]], *, now: datetime
) -> dict[str, dict[int, Decimal]]:
    sales: dict[str, dict[int, Decimal]] = {}
    for order in orders:
        if not _order_is_non_cancelled(order):
            continue
        created_at = _optional_datetime(order.get("date_created"))
        if created_at is None:
            continue
        age_days = max((now.date() - created_at.date()).days, 0)
        for line in _order_lines(order):
            item_sales = sales.setdefault(
                line.item_id, {window: Decimal("0") for window in CATALOGO_SALES_WINDOWS}
            )
            for window in CATALOGO_SALES_WINDOWS:
                if age_days <= window:
                    item_sales[window] += line.quantity
    return sales


def _order_lines(order: Mapping[str, Any]) -> list[_OrderLine]:
    raw_items = order.get("items") or []
    if not isinstance(raw_items, Iterable) or isinstance(raw_items, (str, bytes)):
        return []
    lines: list[_OrderLine] = []
    for item in raw_items:
        if not isinstance(item, Mapping):
            continue
        item_id = _item_id(item)
        if not item_id:
            continue
        quantity = _optional_non_negative_decimal(item.get("quantity", item.get("qty", 0)))
        if quantity is None or quantity <= 0:
            continue
        lines.append(_OrderLine(item_id=item_id, quantity=quantity))
    return lines


def _item_id(item: Mapping[str, Any]) -> str:
    raw_nested_item = item.get("item")
    nested_item: Mapping[str, Any] = raw_nested_item if isinstance(raw_nested_item, Mapping) else {}
    return str(
        item.get("item_id") or nested_item.get("id") or nested_item.get("item_id") or ""
    ).strip()


def _order_is_non_cancelled(order: Mapping[str, Any]) -> bool:
    return str(order.get("status") or "").strip().casefold() not in NON_PRODUCTIVE_ORDER_STATUSES


def _is_currently_out_of_stock(snapshot: Mapping[str, Any]) -> bool:
    state = str(snapshot.get("stock_state") or snapshot.get("state") or "").strip().casefold()
    if state in {"out_of_stock", "sin_stock", "sin stock"}:
        return True
    current_stock = _optional_non_negative_decimal(
        _first_value(snapshot, "current_stock", "available_quantity", "stock")
    )
    return current_stock == Decimal("0")


def _week_headers(metrics: Sequence[Mapping[str, Any]]) -> list[str]:
    for metric in metrics:
        headers = [_week_header(week) for week in _weeks(metric)]
        if headers:
            return headers
    return []


def _weeks(metric: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw_weeks = metric.get("weeks") or []
    if not isinstance(raw_weeks, Sequence) or isinstance(raw_weeks, (str, bytes)):
        return []
    return [week for week in raw_weeks if isinstance(week, Mapping)]


def _week_header(week: Mapping[str, Any]) -> str:
    start = _sheet_optional_number(_first_value(week, "start_day", "start"))
    end = _sheet_optional_number(_first_value(week, "end_day", "end"))
    return f"{start} - {end}"


def _weekly_stock_cell(week: Mapping[str, Any] | None) -> str:
    if week is None:
        return NA_VALUE
    for key in ("label", "status"):
        value = week.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return "Con stock" if bool(week.get("has_stock")) else "Sin stock"


def _history_entries(
    row: Mapping[str, Any], *, preferred_key: str, fallback_key: str
) -> list[Mapping[str, Any]]:
    for key in (preferred_key, fallback_key, "history"):
        value = row.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return [entry for entry in value if isinstance(entry, Mapping)]
    return []


def _current_mapping(row: Mapping[str, Any] | None) -> Mapping[str, Any]:
    current = row.get("current") if row is not None else None
    return current if isinstance(current, Mapping) else {}


def _document_item_id(row: Mapping[str, Any]) -> str:
    return str(row.get("item_id") or row.get("publication_id") or "").strip()


def _snapshot_value(snapshot: Mapping[str, Any], *fields: str) -> Any:
    for field in fields:
        value = snapshot.get(field)
        if value is not None and str(value).strip():
            return value
    return NA_VALUE


def _current_value(current: Mapping[str, Any], *fields: str) -> Any:
    for field in fields:
        value = current.get(field)
        if value is not None and str(value).strip():
            return value
    return NA_VALUE


def _first_value(mapping: Mapping[str, Any] | None, *fields: str) -> Any:
    if mapping is None:
        return None
    for field in fields:
        value = mapping.get(field)
        if value is not None and str(value).strip():
            return value
    return None


def _selected_price(mapping: Mapping[str, Any], *, tipo_precio: Any) -> Any:
    price_kind = str(tipo_precio or "base").strip().casefold()
    price_keys = ("promo_price", "promotional_price") if price_kind == "promo" else ()
    for key in (*price_keys, "base_price", "price"):
        parsed = _optional_non_negative_decimal(mapping.get(key))
        if parsed is not None:
            return _sheet_number(parsed)
    return NA_VALUE


def _normalize_optional_item_ids(value: Any) -> list[str] | None:
    normalized = _flatten_sheet_values(value, normalize=lambda item_id: str(item_id).strip())
    if not normalized or any(item_id.casefold() == "todos" for item_id in normalized):
        return None
    return normalized


def _normalize_optional_skus(value: Any) -> list[str] | None:
    normalized = _flatten_sheet_values(value, normalize=normalize_sku)
    if not normalized or any(sku.casefold() == "todos" for sku in normalized):
        return None
    return normalized


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


def _header_row(value: Any, headers: list[str]) -> list[list[Any]]:
    return [headers] if _headers_requested(value) else []


def _headers_requested(value: Any) -> bool:
    return str(value or "").strip().casefold() in {
        "si",
        "sí",
        "verdadero",
        "true",
        "1",
        "yes",
    }


def _parse_date(value: Any) -> datetime:
    if isinstance(value, datetime):
        return _as_utc_datetime(value)
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=UTC)
    if isinstance(value, str):
        return _as_utc_datetime(datetime.fromisoformat(value.replace("Z", "+00:00")))
    msg = "expected date/datetime or ISO date string"
    raise TypeError(msg)


def _day_start(value: datetime) -> datetime:
    parsed = _as_utc_datetime(value)
    return datetime.combine(parsed.date(), time.min, tzinfo=UTC)


def _day_end(value: datetime) -> datetime:
    parsed = _as_utc_datetime(value)
    return datetime.combine(parsed.date(), time.max, tzinfo=UTC)


def _day_after(value: datetime) -> datetime:
    parsed = _as_utc_datetime(value)
    return datetime.combine(parsed.date() + timedelta(days=1), time.min, tzinfo=UTC)


def _first_datetime(*values: Any) -> datetime | None:
    for value in values:
        parsed = _optional_datetime(value)
        if parsed is not None:
            return parsed
    return None


def _optional_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _as_utc_datetime(value)
    if isinstance(value, str):
        try:
            return _as_utc_datetime(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def _as_utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _datetime_cell(value: Any) -> str:
    parsed = _optional_datetime(value)
    if parsed is None:
        return NA_VALUE
    return parsed.isoformat()


def _non_blank(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def _optional_non_negative_decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, (bool, dict, list, tuple, set)):
        return None
    if isinstance(value, Decimal128):
        parsed = value.to_decimal()
    elif isinstance(value, Decimal):
        parsed = value
    else:
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
    return parsed if parsed.is_finite() and parsed >= 0 else None


def _sheet_optional_number(value: Any) -> Any:
    parsed = _optional_non_negative_decimal(value)
    if parsed is None:
        return NA_VALUE
    return _sheet_number(parsed)


def _sheet_number(value: Decimal) -> int | float:
    if value == value.to_integral_value():
        return int(value)
    return float(value)
