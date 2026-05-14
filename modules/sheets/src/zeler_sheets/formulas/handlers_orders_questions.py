from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any

from zeler_sheets.formulas.dispatcher import (
    FormulaExecutionContext,
    FormulaExecutionResult,
    FormulaHandler,
)
from zeler_sheets.formulas.read_models import FormulaReadModelRepository, normalize_sku

BATCH_B_IMPLEMENTED_FORMULAS = frozenset(
    {
        "SHEETSELLER_ORDENES",
        "SHEETSELLER_VENTASTOTALES",
        "SHEETSELLER_UNIDADESVENDIDAS",
        "SHEETSELLER_ORDENESPORSKU",
        "SHEETSELLER_PREGUNTAS",
        "SHEETSELLER_PREGUNTASKPI",
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


def build_order_question_formula_handlers(
    repository: FormulaReadModelRepository,
) -> dict[str, FormulaHandler]:
    handlers = OrderQuestionFormulaHandlers(repository)
    return {
        "SHEETSELLER_ORDENES": handlers.sheetseller_ordenes,
        "SHEETSELLER_VENTASTOTALES": handlers.sheetseller_ventas_totales,
        "SHEETSELLER_UNIDADESVENDIDAS": handlers.sheetseller_unidades_vendidas,
        "SHEETSELLER_ORDENESPORSKU": handlers.sheetseller_ordenes_por_sku,
        "SHEETSELLER_PREGUNTAS": handlers.sheetseller_preguntas,
        "SHEETSELLER_PREGUNTASKPI": handlers.sheetseller_preguntas_kpi,
    }


class OrderQuestionFormulaHandlers:
    def __init__(self, repository: FormulaReadModelRepository) -> None:
        self._repository = repository

    async def sheetseller_ordenes(self, context: FormulaExecutionContext) -> FormulaExecutionResult:
        date_range = _date_range(context.args.get("fecha_inicial"), context.args.get("fecha_final"))
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
        values.extend(_order_row(order) for order in filtered_orders)
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
        date_range = _date_range(context.args.get("fecha_inicial"), context.args.get("fecha_final"))
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
        date_range = _date_range(context.args.get("fecha_inicial"), context.args.get("fecha_final"))
        orders = await self._repository.find_orders(
            seller_id=context.seller_id,
            date_from=date_range.start,
            date_to=date_range.end,
        )
        totals = _unit_totals_by_pair(orders)
        values: list[list[Any]] = []
        misses = 0
        for pair in pairs:
            units = totals.get((pair.sku, pair.item_id), Decimal("0"))
            if units == 0:
                misses += 1
            values.append([_sheet_number(units)])
        return FormulaExecutionResult(
            values=values,
            meta={"partial_misses": misses, "orders_count": len(orders)},
        )

    async def sheetseller_ordenes_por_sku(
        self, context: FormulaExecutionContext
    ) -> FormulaExecutionResult:
        requested_skus = _flatten_sheet_values(context.args.get("skus"), normalize=normalize_sku)
        date_range = _date_range(context.args.get("fecha_inicial"), context.args.get("fecha_final"))
        status_filter = _status_filter(context.args.get("estado", "todos"))
        buyer_filter = _buyer_filter(context.args.get("compradores", ""))
        orders = await self._repository.find_orders(
            seller_id=context.seller_id,
            date_from=date_range.start,
            date_to=date_range.end,
            status=status_filter,
        )
        filtered_orders = _filter_orders_by_buyers(orders, buyer_filter)
        values: list[list[Any]] = _header_row(
            context.args.get("encabezados"), ORDENES_POR_SKU_MVP_HEADERS
        )
        for requested_sku in dict.fromkeys(requested_skus):
            for order in filtered_orders:
                matching_items = _items_matching_sku(order, requested_sku)
                if not matching_items:
                    continue
                values.append(
                    [
                        requested_sku,
                        _document_id(order),
                        _sheet_datetime(order.get("date_created")),
                        order.get("status") or "",
                        _buyer_id(order),
                        _sheet_number(_decimal(order.get("total_amount"))),
                        _items_summary(matching_items),
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

    async def sheetseller_preguntas(
        self, context: FormulaExecutionContext
    ) -> FormulaExecutionResult:
        date_range = _date_range(context.args.get("fecha_inicial"), context.args.get("fecha_final"))
        hour_range = _hour_range(
            context.args.get("horario_inicial"), context.args.get("horario_final")
        )
        questions = await self._repository.find_questions(
            seller_id=context.seller_id,
            date_from=date_range.start,
            date_to=date_range.end,
        )
        filtered_questions = [
            question for question in questions if _question_in_hour_range(question, hour_range)
        ]
        values: list[list[Any]] = _header_row(
            context.args.get("encabezados"), PREGUNTAS_MVP_HEADERS
        )
        values.extend(_question_row(question) for question in filtered_questions)
        return FormulaExecutionResult(
            values=values,
            meta={"questions_count": len(filtered_questions), "columns": "questions_mvp"},
        )

    async def sheetseller_preguntas_kpi(
        self, context: FormulaExecutionContext
    ) -> FormulaExecutionResult:
        date_range = _date_range(context.args.get("fecha_inicio"), context.args.get("fecha_final"))
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


def _date_range(start_value: Any, end_value: Any) -> _DateRange:
    return _DateRange(
        start=_parse_date_boundary(start_value, end_of_day=False),
        end=_parse_date_boundary(end_value, end_of_day=True),
    )


def _parse_date_boundary(value: Any, *, end_of_day: bool) -> datetime:
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
        parsed = parsed.replace(tzinfo=UTC)
    parsed = parsed.astimezone(UTC)
    if date_only:
        boundary = time.max if end_of_day else time.min
        return datetime.combine(parsed.date(), boundary, tzinfo=UTC)
    return parsed


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


def _unit_totals_by_pair(orders: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], Decimal]:
    totals: dict[tuple[str, str], Decimal] = {}
    for order in orders:
        raw_items = order.get("items") or []
        if not isinstance(raw_items, Iterable) or isinstance(raw_items, (str, bytes)):
            continue
        for raw_item in raw_items:
            if not isinstance(raw_item, Mapping):
                continue
            sku = normalize_sku(_item_sku(raw_item))
            item_id = _item_id(raw_item)
            if not sku or not item_id:
                continue
            key = (sku, item_id)
            totals[key] = totals.get(key, Decimal("0")) + _decimal(
                raw_item.get("quantity", raw_item.get("qty", 0))
            )
    return totals


def _order_row(order: Mapping[str, Any]) -> list[Any]:
    return [
        _document_id(order),
        _sheet_datetime(order.get("date_created")),
        order.get("status") or "",
        _buyer_id(order),
        _sheet_number(_decimal(order.get("total_amount"))),
        _shipment_id(order),
        _items_summary(_order_items(order)),
    ]


def _question_row(question: Mapping[str, Any]) -> list[Any]:
    answer = question.get("answer")
    answer_values: Mapping[str, Any] = answer if isinstance(answer, Mapping) else {}
    return [
        _document_id(question),
        _sheet_datetime(question.get("date_created")),
        str(question.get("item_id") or ""),
        str(question.get("from_user_id") or ""),
        question.get("status") or "",
        question.get("text") or "",
        answer_values.get("text") or "",
        _sheet_datetime(
            answer_values.get("date_created")
            or answer_values.get("answered_at")
            or answer_values.get("created_at")
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


def _items_matching_sku(order: Mapping[str, Any], requested_sku: str) -> list[Mapping[str, Any]]:
    return [item for item in _order_items(order) if normalize_sku(_item_sku(item)) == requested_sku]


def _items_summary(items: Sequence[Mapping[str, Any]]) -> str:
    return ", ".join(_item_summary(item) for item in items if _item_summary(item))


def _item_summary(item: Mapping[str, Any]) -> str:
    sku = normalize_sku(_item_sku(item))
    item_id = _item_id(item)
    quantity = _sheet_number(_decimal(item.get("quantity", item.get("qty", 0))))
    if not sku and not item_id:
        return ""
    label = sku or item_id
    suffix = f" ({item_id})" if item_id and sku else ""
    return f"{label} x{quantity}{suffix}"


def _item_sku(item: Mapping[str, Any]) -> Any:
    raw_nested_item = item.get("item")
    nested_item: Mapping[str, Any] = raw_nested_item if isinstance(raw_nested_item, Mapping) else {}
    return item.get("sku") or item.get("seller_sku") or nested_item.get("seller_sku")


def _item_id(item: Mapping[str, Any]) -> str:
    raw_nested_item = item.get("item")
    nested_item: Mapping[str, Any] = raw_nested_item if isinstance(raw_nested_item, Mapping) else {}
    return str(
        item.get("item_id") or nested_item.get("id") or nested_item.get("item_id") or ""
    ).strip()


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


def _question_in_hour_range(question: Mapping[str, Any], hour_range: _HourRange) -> bool:
    created = _optional_datetime(question.get("date_created"))
    if created is None:
        return False
    question_time = created.time().replace(tzinfo=None)
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


def _sheet_datetime(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        parsed = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).isoformat()
    return str(value).strip()
