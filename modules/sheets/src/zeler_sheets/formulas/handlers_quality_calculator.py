from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from bson.decimal128 import Decimal128

from zeler_sheets.formulas.dispatcher import (
    FormulaDataUnavailableError,
    FormulaExecutionContext,
    FormulaExecutionResult,
    FormulaHandler,
)
from zeler_sheets.formulas.matrix_contracts import (
    CALCULADORA_VISIBLE_HEADERS,
    CALIDAD_VISIBLE_HEADERS,
)
from zeler_sheets.formulas.output_normalization import NA_VALUE, normalize_response_rows
from zeler_sheets.formulas.pricing import promo_price
from zeler_sheets.formulas.read_models import (
    ITEM_FORMULA_ROWS_READ_MODEL,
    FormulaReadModelRepository,
)
from zeler_sheets.status_history import bson_ms_utc_datetime

QUALITY_CALCULATOR_IMPLEMENTED_FORMULAS = frozenset({"ZELERDATA_CALIDAD", "ZELERDATA_CALCULADORA"})

CALIDAD_HEADERS = list(CALIDAD_VISIBLE_HEADERS)
CALCULADORA_HEADERS = list(CALCULADORA_VISIBLE_HEADERS)


def build_quality_calculator_formula_handlers(
    repository: FormulaReadModelRepository,
    *,
    now_fn: Callable[[], datetime] | None = None,
) -> dict[str, FormulaHandler]:
    handlers = QualityCalculatorFormulaHandlers(repository, now_fn=now_fn)
    return {
        "ZELERDATA_CALIDAD": handlers.sheetseller_calidad,
        "ZELERDATA_CALCULADORA": handlers.sheetseller_calculadora,
    }


class QualityCalculatorFormulaHandlers:
    def __init__(
        self,
        repository: FormulaReadModelRepository,
        *,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._now_fn = now_fn or (lambda: datetime.now(UTC))

    async def sheetseller_calidad(self, context: FormulaExecutionContext) -> FormulaExecutionResult:
        now = _as_utc_datetime(self._now_fn())
        unavailable_items: tuple[str, ...] = ()
        inventory_scope = False
        enumeration_current = True
        try:
            await self._repository.require_read_model_productive(
                seller_id=context.seller_id,
                read_model=ITEM_FORMULA_ROWS_READ_MODEL,
                date_to=now,
                formula=context.contract.name,
            )
        except FormulaDataUnavailableError:
            (
                rows,
                _,
                unavailable_items,
                enumeration_current,
            ) = await self._repository.find_recent_item_inventory(
                seller_id=context.seller_id, formula=context.contract.name, now=now
            )
            inventory_scope = True
        else:
            rows = await self._repository.find_item_formula_rows(
                seller_id=context.seller_id,
                limit=None,
                sort_by="publication",
            )
        values: list[list[Any]] = _header_row(context.args.get("encabezados"), CALIDAD_HEADERS)
        header_rows = len(values)
        values.extend(_quality_row(row) for row in rows)
        values.extend(
            [item_id, *["DATA_UNAVAILABLE"] * (len(CALIDAD_HEADERS) - 1)]
            for item_id in unavailable_items
        )
        if not enumeration_current:
            values.append(_expired_inventory_warning(len(CALIDAD_HEADERS)))
        return FormulaExecutionResult(
            values=normalize_response_rows(values, header_rows=header_rows),
            meta={
                "rows_count": len(values) - header_rows,
                "columns": "modern_quality_projection",
                **(
                    {
                        "inventory_rows_complete": enumeration_current and not unavailable_items,
                        "inventory_enumeration_current": enumeration_current,
                        "partial_misses": len(unavailable_items),
                    }
                    if inventory_scope
                    else {}
                ),
                **(
                    {
                        "unavailable_items": list(unavailable_items),
                        "unavailable_reason": "missing_incomplete_or_stale_projection",
                    }
                    if unavailable_items
                    else {}
                ),
            },
            recovery=(
                FormulaDataUnavailableError(
                    context.contract.name,
                    "Inventory publications need recovery.",
                    read_model=ITEM_FORMULA_ROWS_READ_MODEL,
                )
                if unavailable_items or not enumeration_current
                else None
            ),
        )

    async def sheetseller_calculadora(
        self, context: FormulaExecutionContext
    ) -> FormulaExecutionResult:
        requested_item_ids = _normalize_optional_item_ids(context.args.get("id_publicaciones"))
        now = _as_utc_datetime(self._now_fn())
        unavailable_items: tuple[str, ...] = ()
        inventory_scope = False
        enumeration_current = True
        try:
            await self._repository.require_read_model_productive(
                seller_id=context.seller_id,
                read_model=ITEM_FORMULA_ROWS_READ_MODEL,
                date_to=now,
                formula=context.contract.name,
                item_ids=requested_item_ids,
            )
        except FormulaDataUnavailableError:
            if not requested_item_ids:
                (
                    rows,
                    requested_item_ids,
                    unavailable_items,
                    enumeration_current,
                ) = await self._repository.find_recent_item_inventory(
                    seller_id=context.seller_id,
                    formula=context.contract.name,
                    now=now,
                )
                inventory_scope = True
            else:
                rows, unavailable_items = await self._repository.find_recent_item_formula_rows(
                    seller_id=context.seller_id,
                    item_ids=requested_item_ids,
                    formula=context.contract.name,
                    now=now,
                )
        else:
            rows = await self._repository.find_item_formula_rows(
                seller_id=context.seller_id,
                item_ids=requested_item_ids,
                limit=None,
                sort_by="publication",
            )
            if requested_item_ids:
                represented = {str(row["item_id"]) for row in rows}
                unavailable_items = tuple(
                    item_id for item_id in requested_item_ids if item_id not in represented
                )
        values: list[list[Any]] = _header_row(context.args.get("encabezados"), CALCULADORA_HEADERS)
        header_rows = len(values)
        missing_count = 0
        if requested_item_ids is None:
            ordered_rows = sorted(rows, key=_row_sort_key)
            values.extend(
                _calculator_row(row, tipo_precio=context.args.get("tipo_precio", "actual"), now=now)
                for row in ordered_rows
            )
            rows_count = len(ordered_rows)
        else:
            rows_by_item_id = _rows_grouped_by_item_id(rows)
            rows_count = 0
            for item_id in requested_item_ids:
                current_rows = rows_by_item_id.get(item_id, [])
                if not current_rows:
                    missing_count += 1
                    rows_count += 1
                    values.append([item_id, *["DATA_UNAVAILABLE" for _ in CALCULADORA_HEADERS[1:]]])
                    continue
                for row in current_rows:
                    rows_count += 1
                    values.append(
                        _calculator_row(
                            row, tipo_precio=context.args.get("tipo_precio", "actual"), now=now
                        )
                    )
        if not enumeration_current:
            values.append(_expired_inventory_warning(len(CALCULADORA_HEADERS)))
            rows_count += 1
        present_ids = {str(row["item_id"]) for row in rows}
        unavailable_field_items = {
            str(row[0])
            for row in values[header_rows:]
            if row[0] in present_ids and "DATA_UNAVAILABLE" in row[4:9]
        }
        recovery_items = tuple(sorted(set(unavailable_items) | unavailable_field_items))
        return FormulaExecutionResult(
            values=normalize_response_rows(values, header_rows=header_rows),
            meta={
                "partial_misses": missing_count,
                "rows_count": rows_count,
                "columns": "modern_cost_projection",
                **(
                    {"unavailable_field_items": sorted(unavailable_field_items)}
                    if unavailable_field_items
                    else {}
                ),
                **(
                    {
                        "inventory_rows_complete": enumeration_current and not unavailable_items,
                        "inventory_enumeration_current": enumeration_current,
                    }
                    if inventory_scope
                    else {}
                ),
                **(
                    {
                        "unavailable_items": list(unavailable_items),
                        "unavailable_reason": "missing_incomplete_or_stale_projection",
                    }
                    if unavailable_items
                    else {}
                ),
            },
            recovery=(
                FormulaDataUnavailableError(
                    context.contract.name,
                    "Selected publications or their price/cost fields are unavailable.",
                    read_model=ITEM_FORMULA_ROWS_READ_MODEL,
                    item_ids=()
                    if inventory_scope and (unavailable_items or not enumeration_current)
                    else recovery_items,
                )
                if recovery_items or not enumeration_current
                else None
            ),
        )


def _expired_inventory_warning(width: int) -> list[str]:
    # Apps Script returns values, not metadata: incomplete coverage must remain
    # visible in the spreadsheet even when every previously known ID is readable.
    return [
        "DATA_UNAVAILABLE",
        "inventory_enumeration_expired",
        *["DATA_UNAVAILABLE"] * (width - 2),
    ]


def _quality_row(row: Mapping[str, Any]) -> list[Any]:
    current = _current_mapping(row)
    projection = _quality_projection(current)
    score = _quality_score(current, projection)
    return [
        str(row.get("item_id") or ""),
        row.get("sku") or row.get("normalized_sku") or NA_VALUE,
        _current_value(current, "title"),
        _current_value(current, "status"),
        _current_value(current, "permalink", "url"),
        _sheet_optional_number(current.get("available_quantity")),
        _current_value(current, "listing_type_id"),
        _sheet_optional_number(score),
        _quality_level(projection, score=score),
        _datetime_cell(_projection_value(projection, "calculated_at", "synced_at", "updated_at")),
        _component_status(projection, "gtin"),
        _component_score(projection, "gtin"),
        _component_status(projection, "images", "pictures", "picture"),
        _component_score(projection, "images", "pictures", "picture"),
        _component_status(projection, "title"),
        _component_score(projection, "title"),
        _component_status(projection, "shipping", "mercado_envios", "mercadoenvios"),
        _component_score(projection, "shipping", "mercado_envios", "mercadoenvios"),
        _pending_actions(projection),
    ]


def _calculator_row(
    row: Mapping[str, Any], *, tipo_precio: Any, now: datetime | None = None
) -> list[Any]:
    current = _current_mapping(row)
    if now is not None and isinstance(row.get("source_snapshot"), Mapping):
        states = dict(_optional_mapping(current.get("enrichment_state")) or {})
        for field in (
            "seller_shipping_cost",
            "listing_fee_projection",
            "listing_price_fixed_fee",
            "current_promotion",
        ):
            state = _optional_mapping(states.get(field)) or {}
            observed = bson_ms_utc_datetime(state.get("synced_at"))
            if observed is None or not now - timedelta(minutes=15) < observed <= now:
                states[field] = {"status": "unavailable", "reason": "stale_or_unverified"}
        current = {**current, "enrichment_state": states}
    price = _selected_price(current, tipo_precio=tipo_precio)
    seller_shipping_cost = _acquired_cost(
        current, "seller_shipping_cost", current.get("seller_shipping_cost")
    )
    fee_projection = _optional_mapping(current.get("listing_fee_projection"))
    commission = _acquired_cost(
        current,
        "listing_fee_projection",
        fee_projection.get("sale_fee_amount") if fee_projection else None,
    )
    commission_percent = _acquired_cost(
        current,
        "listing_fee_projection",
        fee_projection.get("percentage_fee") if fee_projection else None,
    )
    fixed_fee_projection = _optional_mapping(current.get("listing_price_fixed_fee"))
    fixed_fee = _acquired_cost(
        current,
        "listing_price_fixed_fee",
        fixed_fee_projection.get("fixed_fee") if fixed_fee_projection else None,
    )
    total_costs = _total_costs(seller_shipping_cost, commission, fixed_fee)
    if isinstance(price, str):
        net_amount: Decimal | str | None = price
    elif isinstance(total_costs, str):
        net_amount = total_costs
    else:
        net_amount = price - total_costs if price is not None and total_costs is not None else None
    return [
        str(row.get("item_id") or ""),
        row.get("sku") or row.get("normalized_sku") or NA_VALUE,
        _current_value(current, "title"),
        _current_value(current, "currency_id"),
        price if isinstance(price, str) else _sheet_optional_number(price),
        _sheet_optional_number(seller_shipping_cost),
        _sheet_optional_number(commission),
        _sheet_optional_number(commission_percent),
        _sheet_optional_number(fixed_fee),
        _current_value(current, "category_id"),
        "CATALOGO" if _non_blank(current.get("catalog_product_id")) else "REGULAR",
        _current_value(current, "shipping_logistic_type", "logistic_type"),
        _current_value(current, "listing_type_id"),
        _sheet_optional_number(total_costs),
        _sheet_number(net_amount)
        if isinstance(net_amount, Decimal)
        else _sheet_optional_number(net_amount),
    ]


def _quality_projection(current: Mapping[str, Any]) -> Mapping[str, Any]:
    for key in ("quality_projection", "quality_performance", "quality", "health_projection"):
        value = current.get(key)
        if isinstance(value, Mapping):
            return value
    return {}


def _quality_score(current: Mapping[str, Any], projection: Mapping[str, Any]) -> Decimal | None:
    for value in (
        _projection_value(projection, "score", "quality_score", "health"),
        current.get("health"),
    ):
        score = _optional_non_negative_decimal(value)
        if score is not None:
            return score
    return None


def _quality_level(projection: Mapping[str, Any], *, score: Decimal | None) -> Any:
    raw_level = _projection_value(projection, "level", "quality_level")
    if raw_level is not None and str(raw_level).strip():
        return str(raw_level).strip()
    if score is None:
        return NA_VALUE
    if score >= Decimal("0.8"):
        return "good"
    if score >= Decimal("0.5"):
        return "regular"
    return "poor"


def _component_status(projection: Mapping[str, Any], *keys: str) -> Any:
    component = _component(projection, *keys)
    for key in ("status", "state", "level"):
        value = component.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return NA_VALUE


def _component_score(projection: Mapping[str, Any], *keys: str) -> Any:
    component = _component(projection, *keys)
    return _sheet_optional_number(component.get("score", component.get("value")))


def _component(projection: Mapping[str, Any], *keys: str) -> Mapping[str, Any]:
    components = projection.get("components") or projection.get("component_scores")
    if isinstance(components, Mapping):
        for key in keys:
            value = components.get(key) or components.get(key.upper())
            if isinstance(value, Mapping):
                return value
    if isinstance(components, Sequence) and not isinstance(components, (str, bytes)):
        expected = {key.casefold() for key in keys}
        for value in components:
            if not isinstance(value, Mapping):
                continue
            component_id = str(value.get("id") or value.get("name") or "").strip().casefold()
            if component_id in expected:
                return value
    return {}


def _pending_actions(projection: Mapping[str, Any]) -> str:
    value = _projection_value(projection, "pending_actions", "actions", "recommendations")
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        actions = [str(action).strip() for action in value if str(action).strip()]
        return " | ".join(actions) if actions else NA_VALUE
    if value is not None and str(value).strip():
        return str(value).strip()
    return NA_VALUE


def _projection_value(projection: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = projection.get(key)
        if value is not None:
            return value
    return None


def _selected_price(current: Mapping[str, Any], *, tipo_precio: Any) -> Decimal | str | None:
    price_kind = str(tipo_precio or "actual").strip().casefold()
    if price_kind == "promo":
        selected = promo_price({"current": current})
        if isinstance(selected, str) and selected in {NA_VALUE, "DATA_UNAVAILABLE"}:
            return selected
        return _optional_non_negative_decimal(selected)
    if price_kind == "base":
        base_price = _optional_non_negative_decimal(current.get("base_price"))
        if base_price is not None:
            return base_price
    return _optional_non_negative_decimal(current.get("price")) or _optional_non_negative_decimal(
        current.get("base_price")
    )


def _acquired_cost(current: Mapping[str, Any], field: str, value: Any) -> Decimal | str | None:
    parsed = _optional_non_negative_decimal(value)
    enrichment = _optional_mapping(current.get("enrichment_state"))
    state = _optional_mapping(enrichment.get(field)) if enrichment else None
    if state is None:
        return parsed
    if state.get("status") == "authoritative_absent":
        return NA_VALUE
    if state.get("status") != "trusted" or parsed is None:
        return "DATA_UNAVAILABLE"
    return parsed


def _total_costs(*values: Decimal | str | None) -> Decimal | str | None:
    if "DATA_UNAVAILABLE" in values:
        return "DATA_UNAVAILABLE"
    if NA_VALUE in values:
        return NA_VALUE
    if any(value is None for value in values):
        return None
    return sum((value for value in values if isinstance(value, Decimal)), Decimal("0"))


def _current_mapping(row: Mapping[str, Any] | None) -> Mapping[str, Any]:
    current = row.get("current") if row is not None else None
    return current if isinstance(current, Mapping) else {}


def _current_value(current: Mapping[str, Any], *fields: str) -> Any:
    for field in fields:
        value = current.get(field)
        if value is not None and str(value).strip():
            return value
    return NA_VALUE


def _normalize_optional_item_ids(value: Any) -> list[str] | None:
    item_ids = _flatten_sheet_values(value, normalize=lambda item_id: str(item_id).strip())
    if not item_ids or any(item_id.casefold() == "todos" for item_id in item_ids):
        return None
    return item_ids


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


def _rows_grouped_by_item_id(rows: Sequence[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in sorted(rows, key=_row_sort_key):
        grouped.setdefault(str(row.get("item_id") or "").strip(), []).append(row)
    return grouped


def _row_sort_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("item_id") or ""),
        str(row.get("normalized_sku") or row.get("sku") or ""),
        str(row.get("variation_id") or ""),
    )


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


def _datetime_cell(value: Any) -> str:
    if isinstance(value, datetime):
        return _as_utc_datetime(value).isoformat()
    if value is not None and str(value).strip():
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return _as_utc_datetime(parsed).isoformat()
        except ValueError:
            return str(value).strip()
    return NA_VALUE


def _as_utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _optional_mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


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
    if isinstance(value, str) and value in {NA_VALUE, "DATA_UNAVAILABLE"}:
        return value
    parsed = _optional_non_negative_decimal(value)
    if parsed is None:
        return NA_VALUE
    return _sheet_number(parsed)


def _sheet_number(value: Decimal) -> int | float:
    if value == value.to_integral_value():
        return int(value)
    return float(value)
