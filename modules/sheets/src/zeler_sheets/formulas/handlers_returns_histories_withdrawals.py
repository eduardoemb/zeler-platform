from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, date, datetime, time
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
    CLAIMS_READ_MODEL,
    ITEM_FORMULA_ROWS_READ_MODEL,
    ITEM_STATUS_STATES_READ_MODEL,
    ORDERS_READ_MODEL,
    FormulaReadModelRepository,
    normalize_sku,
)

RETURNS_HISTORIES_WITHDRAWALS_IMPLEMENTED_FORMULAS = frozenset(
    {
        "ZELERDATA_DEVOLUCIONES",
        "ZELERDATA_PUBLICACIONESDESCUIDADAS",
        "ZELERDATA_TIEMPOACTIVA",
    }
)

DEVOLUCIONES_HEADERS = ["ID PUBLICACION", "SKU", "UNIDADES DEVUELTAS", "TITULO"]
PUBLICACIONES_DESCUIDADAS_HEADERS = [
    "ID PUBLICACION",
    "TITULO",
    "SKU",
    "STOCK ACTUAL",
    "STOCK A RETIRAR",
    "MOTIVO DE RETIRO",
    "PRECIO",
    "LOGISTICA",
    "URL",
    "TIPO DE PUBLICACION",
    "STATUS",
    "CODIGO ML",
]
NEGLECTED_PUBLICATION_THRESHOLD_DAYS = 10
CANCELLED_RETURN_STATUSES = frozenset({"cancelled", "canceled"})
FULL_LOGISTIC_TYPES = frozenset({"fulfillment", "full"})


def build_returns_histories_withdrawals_formula_handlers(
    repository: FormulaReadModelRepository,
    *,
    now_fn: Callable[[], datetime] | None = None,
) -> dict[str, FormulaHandler]:
    handlers = ReturnsHistoriesWithdrawalsFormulaHandlers(repository, now_fn=now_fn)
    return {
        "ZELERDATA_DEVOLUCIONES": handlers.sheetseller_devoluciones,
        "ZELERDATA_PUBLICACIONESDESCUIDADAS": handlers.sheetseller_publicaciones_descuidadas,
        "ZELERDATA_TIEMPOACTIVA": handlers.sheetseller_tiempo_activa,
    }


class ReturnsHistoriesWithdrawalsFormulaHandlers:
    def __init__(
        self,
        repository: FormulaReadModelRepository,
        *,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._now_fn = now_fn or (lambda: datetime.now(UTC))

    async def sheetseller_devoluciones(
        self, context: FormulaExecutionContext
    ) -> FormulaExecutionResult:
        date_from = _day_start(_parse_date(context.args.get("fecha_inicio")))
        date_to = _day_end(_parse_date(context.args.get("fecha_final")))
        await self._repository.require_read_model_productive(
            seller_id=context.seller_id,
            read_model=CLAIMS_READ_MODEL,
            date_to=date_to,
            formula=context.contract.name,
        )
        await self._repository.require_read_model_productive(
            seller_id=context.seller_id,
            read_model=ORDERS_READ_MODEL,
            date_to=date_to,
            formula=context.contract.name,
        )
        requested_item_ids = _normalize_optional_item_ids(
            context.args.get("id_publicaciones", "todos")
        )
        claims = await self._repository.find_return_claims(
            seller_id=context.seller_id,
            date_from=date_from,
            date_to=date_to,
            limit=5000,
        )
        productive_claims = [claim for claim in claims if not _is_cancelled_return_claim(claim)]
        order_ids = list(
            dict.fromkeys(order_id for claim in productive_claims if (order_id := _order_id(claim)))
        )
        orders = await self._repository.find_orders_by_ids(
            seller_id=context.seller_id,
            order_ids=order_ids,
            limit=max(1000, len(order_ids)),
        )
        orders_by_id = {_document_id(order): order for order in orders}
        requested_set = set(requested_item_ids or [])
        aggregates: dict[tuple[str, str], _ReturnAggregate] = {}

        for claim in productive_claims:
            order = orders_by_id.get(_order_id(claim))
            if order is None:
                continue
            for line in _order_lines(order):
                if requested_set and line.item_id not in requested_set:
                    continue
                key = (line.item_id, line.sku)
                aggregate = aggregates.setdefault(
                    key,
                    _ReturnAggregate(item_id=line.item_id, sku=line.sku, title=line.title),
                )
                aggregate.quantity += line.quantity
                if not aggregate.title and line.title:
                    aggregate.title = line.title

        values: list[list[Any]] = _header_row(context.args.get("encabezados"), DEVOLUCIONES_HEADERS)
        header_rows = len(values)
        for aggregate in sorted(
            aggregates.values(),
            key=lambda current: (-current.quantity, current.item_id, current.sku),
        ):
            values.append(
                [
                    aggregate.item_id,
                    aggregate.sku,
                    _sheet_number(Decimal(aggregate.quantity)),
                    aggregate.title,
                ]
            )
        return FormulaExecutionResult(
            values=normalize_response_rows(values, header_rows=header_rows),
            meta={
                "claims_count": len(productive_claims),
                "order_count": len(orders),
                "rows_count": len(aggregates),
                "columns": "legacy_returns",
            },
        )

    async def sheetseller_publicaciones_descuidadas(
        self, context: FormulaExecutionContext
    ) -> FormulaExecutionResult:
        now = _as_utc_datetime(self._now_fn())
        await self._repository.require_read_model_productive(
            seller_id=context.seller_id,
            read_model=ITEM_FORMULA_ROWS_READ_MODEL,
            date_to=now,
            formula=context.contract.name,
        )
        rows = await self._repository.find_item_formula_rows(
            seller_id=context.seller_id,
            limit=None,
            sort_by="publication",
        )
        neglected_rows = [row for row in rows if _is_neglected_full_publication(row, now=now)]
        values: list[list[Any]] = _header_row(
            context.args.get("encabezados"), PUBLICACIONES_DESCUIDADAS_HEADERS
        )
        header_rows = len(values)
        values.extend(
            _neglected_publication_row(row, tipo_precio=context.args.get("tipo_precio", "base"))
            for row in neglected_rows
        )
        return FormulaExecutionResult(
            values=normalize_response_rows(values, header_rows=header_rows),
            meta={
                "rows_count": len(neglected_rows),
                "threshold_days": NEGLECTED_PUBLICATION_THRESHOLD_DAYS,
                "columns": "legacy_neglected_publications",
            },
        )

    async def sheetseller_tiempo_activa(
        self, context: FormulaExecutionContext
    ) -> FormulaExecutionResult:
        item_ids = _normalize_item_id_argument(context.args.get("id_publicaciones"))
        now = _as_utc_datetime(self._now_fn())
        await self._repository.require_read_model_productive(
            seller_id=context.seller_id,
            read_model=ITEM_STATUS_STATES_READ_MODEL,
            date_to=now,
            formula=context.contract.name,
        )
        states = await self._repository.find_item_status_states(
            seller_id=context.seller_id,
            item_ids=item_ids,
            limit=max(500, len(item_ids)),
        )
        states_by_item_id = {str(state.get("item_id") or "").strip(): state for state in states}
        values: list[list[Any]] = []
        misses = 0
        for item_id in item_ids:
            active_days = _active_days(states_by_item_id.get(item_id), now=now)
            if active_days is None:
                misses += 1
                values.append([NA_VALUE])
            else:
                values.append([active_days])
        return FormulaExecutionResult(
            values=values,
            meta={"partial_misses": misses, "columns": "active_status_days"},
        )


class _OrderLine:
    def __init__(self, *, item_id: str, sku: str, title: str, quantity: int) -> None:
        self.item_id = item_id
        self.sku = sku
        self.title = title
        self.quantity = quantity


class _ReturnAggregate:
    def __init__(self, *, item_id: str, sku: str, title: str) -> None:
        self.item_id = item_id
        self.sku = sku
        self.title = title
        self.quantity = 0


def _is_cancelled_return_claim(claim: Mapping[str, Any]) -> bool:
    return str(claim.get("status") or "").strip().casefold() in CANCELLED_RETURN_STATUSES


def _order_id(claim: Mapping[str, Any]) -> str:
    return str(claim.get("order_id") or "").strip()


def _document_id(document: Mapping[str, Any]) -> str:
    return str(document.get("_id") or document.get("id") or "").strip()


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
        quantity = _positive_int(item.get("quantity", item.get("qty", 0)))
        if quantity <= 0:
            continue
        lines.append(
            _OrderLine(
                item_id=item_id,
                sku=normalize_sku(_item_sku(item)),
                title=_item_title(item),
                quantity=quantity,
            )
        )
    return lines


def _item_sku(item: Mapping[str, Any]) -> str:
    raw_nested_item = item.get("item")
    nested_item: Mapping[str, Any] = raw_nested_item if isinstance(raw_nested_item, Mapping) else {}
    return str(
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


def _item_title(item: Mapping[str, Any]) -> str:
    raw_nested_item = item.get("item")
    nested_item: Mapping[str, Any] = raw_nested_item if isinstance(raw_nested_item, Mapping) else {}
    return str(item.get("title") or nested_item.get("title") or "").strip()


def _is_neglected_full_publication(row: Mapping[str, Any], *, now: datetime) -> bool:
    current = _current_mapping(row)
    if str(current.get("status") or "").strip().casefold() != "paused":
        return False
    if _optional_non_negative_decimal(current.get("available_quantity")) != Decimal("0"):
        return False
    if not _is_full_logistic(current):
        return False
    paused_since = _first_datetime(
        current.get("paused_since"),
        current.get("status_started_at"),
        current.get("last_status_change_at"),
    )
    if paused_since is None:
        return False
    return (now.date() - paused_since.date()).days > NEGLECTED_PUBLICATION_THRESHOLD_DAYS


def _neglected_publication_row(row: Mapping[str, Any], *, tipo_precio: Any) -> list[Any]:
    current = _current_mapping(row)
    return [
        str(row.get("item_id") or ""),
        _current_value(row, "title"),
        row.get("sku") or row.get("normalized_sku") or "",
        _sheet_optional_number(current.get("available_quantity")),
        _stock_to_withdraw(current),
        _withdrawal_reason(current),
        _selected_price(current, tipo_precio=tipo_precio),
        _logistic_type(current),
        _current_value(row, "permalink", "url"),
        _current_value(row, "listing_type_id", "listing_type"),
        _current_value(row, "status"),
        _current_value(row, "inventory_id") or row.get("inventory_id") or NA_VALUE,
    ]


def _active_days(state: Mapping[str, Any] | None, *, now: datetime) -> int | None:
    if state is None:
        return None
    if str(state.get("current_status") or "").strip().casefold() != "active":
        return None
    started_at = _first_datetime(state.get("status_started_at"), state.get("first_observed_at"))
    if started_at is None:
        return None
    return max((now.date() - started_at.date()).days, 0)


def _is_full_logistic(current: Mapping[str, Any]) -> bool:
    return _logistic_type(current).casefold() in FULL_LOGISTIC_TYPES


def _logistic_type(current: Mapping[str, Any]) -> str:
    shipping = current.get("shipping")
    shipping_mapping: Mapping[str, Any] = shipping if isinstance(shipping, Mapping) else {}
    for value in (
        current.get("shipping_logistic_type"),
        current.get("logistic_type"),
        current.get("fulfillment_type"),
        shipping_mapping.get("logistic_type"),
        shipping_mapping.get("mode"),
    ):
        if value is not None and str(value).strip():
            return str(value).strip()
    return NA_VALUE


def _stock_to_withdraw(current: Mapping[str, Any]) -> Any:
    for value in (
        current.get("stock_to_withdraw"),
        current.get("quantity_to_withdraw"),
        current.get("unavailable_quantity"),
        _unavailable_detail_value(current, "quantity", "stock", "stock_to_withdraw"),
    ):
        parsed = _optional_non_negative_decimal(value)
        if parsed is not None:
            return _sheet_number(parsed)
    return NA_VALUE


def _withdrawal_reason(current: Mapping[str, Any]) -> str:
    for value in (
        current.get("withdrawal_reason"),
        current.get("unavailable_reason"),
        _unavailable_detail_value(current, "reason", "description", "message"),
    ):
        if value is not None and str(value).strip():
            return str(value).strip()
    return NA_VALUE


def _unavailable_detail_value(current: Mapping[str, Any], *keys: str) -> Any:
    details = current.get("unavailable_details") or current.get("unavailable_detail")
    detail: Mapping[str, Any] | None = None
    if isinstance(details, Mapping):
        detail = details
    elif isinstance(details, Sequence) and not isinstance(details, (str, bytes)):
        for candidate in details:
            if isinstance(candidate, Mapping):
                detail = candidate
                break
    if detail is None:
        return None
    for key in keys:
        value = detail.get(key)
        if value is not None and str(value).strip():
            return value
    return None


def _selected_price(current: Mapping[str, Any], *, tipo_precio: Any) -> Any:
    price_kind = str(tipo_precio or "base").strip().casefold()
    price_keys = ("promo_price", "promotional_price", "price") if price_kind == "promo" else ()
    for key in (*price_keys, "base_price", "price"):
        value = current.get(key)
        parsed = _optional_non_negative_decimal(value)
        if parsed is not None:
            return _sheet_number(parsed)
    return NA_VALUE


def _current_mapping(row: Mapping[str, Any] | None) -> Mapping[str, Any]:
    current = row.get("current") if row is not None else None
    return current if isinstance(current, Mapping) else {}


def _current_value(row: Mapping[str, Any] | None, *fields: str) -> Any:
    current = _current_mapping(row)
    for field in fields:
        value = current.get(field)
        if value is not None and str(value).strip():
            return value
    return NA_VALUE


def _normalize_optional_item_ids(value: Any) -> list[str] | None:
    normalized = _normalize_item_id_argument(value)
    if not normalized or any(item_id.casefold() == "todos" for item_id in normalized):
        return None
    return normalized


def _normalize_item_id_argument(value: Any) -> list[str]:
    return _flatten_sheet_values(value, normalize=lambda item_id: str(item_id).strip())


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


def _parse_date(value: Any) -> datetime:
    if isinstance(value, datetime):
        return _as_utc_datetime(value)
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=UTC)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return _as_utc_datetime(parsed)
    msg = "expected date/datetime or ISO date string"
    raise TypeError(msg)


def _day_start(value: datetime) -> datetime:
    parsed = _as_utc_datetime(value)
    return datetime.combine(parsed.date(), time.min, tzinfo=UTC)


def _day_end(value: datetime) -> datetime:
    parsed = _as_utc_datetime(value)
    return datetime.combine(parsed.date(), time.max, tzinfo=UTC)


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


def _positive_int(value: Any) -> int:
    parsed = _optional_non_negative_decimal(value)
    if parsed is None:
        return 0
    return int(parsed)


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
