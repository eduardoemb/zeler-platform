from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from bson.decimal128 import Decimal128

from zeler_sheets.formulas.catalog_values import catalog_shared_users
from zeler_sheets.formulas.dispatcher import (
    FormulaDataUnavailableError,
    FormulaExecutionContext,
    FormulaExecutionResult,
    FormulaHandler,
)
from zeler_sheets.formulas.matrix_contracts import (
    CATALOGO_COMPLETO_VISIBLE_HEADERS,
    CATALOGOBUYBOX_VISIBLE_HEADERS,
    OBTENER_CATALOGO_VISIBLE_HEADERS,
)
from zeler_sheets.formulas.output_normalization import NA_VALUE, normalize_response_rows
from zeler_sheets.formulas.read_models import (
    CATALOG_BUYBOX_SNAPSHOTS_READ_MODEL,
    CATALOG_PRODUCT_SNAPSHOTS_READ_MODEL,
    ITEM_FORMULA_ROWS_READ_MODEL,
    ORDERS_READ_MODEL,
    SHIPMENTS_READ_MODEL,
    FormulaReadModelRepository,
    normalize_sku,
)

ITEM_SHIPPING_CATALOG_IMPLEMENTED_FORMULAS = frozenset(
    {
        "ZELERDATA_MEDIDASGENERAL",
        "ZELERDATA_MEDIDAS",
        "ZELERDATA_SUPERMERCADO",
        "ZELERDATA_OBTENER_CATALOGO",
        "ZELERDATA_CATALOGOSINVINCULAR",
        "ZELERDATA_CATALOGOBUYBOX",
        "ZELERDATA_CATALOGO_COMPLETO",
        "ZELERDATA_COSTOENVIOVENDEDOR",
        "ZELERDATA_ENVIOSMERCADOENVIOS",
    }
)

MEDIDAS_GENERAL_HEADERS = ["ID PUBLICACION", "SKU", "TITULO", "MEDIDAS (LARGO * ALTO * ANCHO)"]
CATALOGOS_SIN_VINCULAR_HEADERS = ["ID PUBLICACION", "TITULO"]
ENVIOS_MERCADOENVIOS_HEADERS = [
    "ID ORDEN",
    "ID PAQUETE",
    "TITULO",
    "SKU",
    "UNIDADES VENDIDAS",
    "ESTADO",
    "FECHA ENVIO",
    "DEMORADO",
    "PAQUETERIA",
]
NON_PRODUCTIVE_ORDER_STATUSES = frozenset({"cancelled", "canceled"})
CLOSED_SHIPMENT_STATUSES = frozenset({"delivered", "shipped"})
SUPERMARKET_TAG = "supermarket_eligible"


def build_item_shipping_catalog_formula_handlers(
    repository: FormulaReadModelRepository,
    *,
    now_fn: Callable[[], datetime] | None = None,
) -> dict[str, FormulaHandler]:
    handlers = ItemShippingCatalogFormulaHandlers(repository, now_fn=now_fn)
    return {
        "ZELERDATA_MEDIDASGENERAL": handlers.sheetseller_medidas_general,
        "ZELERDATA_MEDIDAS": handlers.sheetseller_medidas,
        "ZELERDATA_SUPERMERCADO": handlers.sheetseller_supermercado,
        "ZELERDATA_OBTENER_CATALOGO": handlers.sheetseller_obtener_catalogo,
        "ZELERDATA_CATALOGOSINVINCULAR": handlers.sheetseller_catalogos_sin_vincular,
        "ZELERDATA_CATALOGOBUYBOX": handlers.sheetseller_catalogo_buybox,
        "ZELERDATA_CATALOGO_COMPLETO": handlers.sheetseller_catalogo_completo,
        "ZELERDATA_COSTOENVIOVENDEDOR": handlers.sheetseller_costo_envio_vendedor,
        "ZELERDATA_ENVIOSMERCADOENVIOS": handlers.sheetseller_envios_mercadoenvios,
    }


class ItemShippingCatalogFormulaHandlers:
    def __init__(
        self,
        repository: FormulaReadModelRepository,
        *,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._now_fn = now_fn or (lambda: datetime.now(UTC))

    async def sheetseller_supermercado(
        self, context: FormulaExecutionContext
    ) -> FormulaExecutionResult:
        item_ids = _normalize_optional_item_ids(context.args.get("id_publicaciones"))
        resolution = await self._repository.resolve_item_formula_rows(
            seller_id=context.seller_id,
            formula=context.contract.name,
            now=_as_utc_datetime(self._now_fn()),
            item_ids=item_ids or None,
        )
        rows_by_item_id = _first_rows_by_item_id(resolution.rows)
        values: list[list[Any]] = []
        misses = 0
        requested_ids = item_ids if item_ids is not None else list(rows_by_item_id)
        for item_id in requested_ids:
            row = rows_by_item_id.get(item_id)
            if row is None:
                misses += 1
                values.append(["N/A"])
                continue
            values.append(["Supermercado" if _has_current_tag(row, SUPERMARKET_TAG) else "Normal"])
        return FormulaExecutionResult(
            values=values,
            meta={"partial_misses": misses, **resolution.meta()},
            recovery=resolution.recovery,
        )

    async def sheetseller_medidas(self, context: FormulaExecutionContext) -> FormulaExecutionResult:
        skus_argument = context.args.get("skus", "todos")
        item_ids_argument = context.args.get("id_publicaciones", "todos")
        whole_seller = _is_all_scope(skus_argument) and _is_all_scope(item_ids_argument)
        pairs = (
            [] if whole_seller else _lookup_pairs(skus=skus_argument, item_ids=item_ids_argument)
        )
        resolution = await self._repository.resolve_item_formula_rows(
            seller_id=context.seller_id,
            formula=context.contract.name,
            now=_as_utc_datetime(self._now_fn()),
            skus=None if whole_seller else [pair.sku for pair in pairs] or None,
            item_ids=None if whole_seller else [pair.item_id for pair in pairs] or None,
        )
        rows_by_pair = _rows_by_pair(resolution.rows)
        values: list[list[Any]] = []
        misses = 0
        lookup_pairs = pairs or _pairs_from_rows(resolution.rows)
        for pair in lookup_pairs:
            measurement = _measurement_value(rows_by_pair.get((pair.sku, pair.item_id)))
            if measurement == NA_VALUE:
                misses += 1
            values.append([measurement])
        return FormulaExecutionResult(
            values=values,
            meta={"partial_misses": misses, **resolution.meta()},
            recovery=resolution.recovery,
        )

    async def sheetseller_medidas_general(
        self, context: FormulaExecutionContext
    ) -> FormulaExecutionResult:
        requested_skus = _normalize_optional_sku_argument(context.args.get("skus", "todos"))
        requested_item_ids = _normalize_optional_item_ids(
            context.args.get("id_publicaciones", "todos")
        )
        resolution = await self._repository.resolve_item_formula_rows(
            seller_id=context.seller_id,
            formula=context.contract.name,
            now=_as_utc_datetime(self._now_fn()),
            skus=requested_skus,
            item_ids=requested_item_ids,
        )
        ordered_rows = _order_item_rows(
            resolution.rows, requested_skus=requested_skus, item_ids=requested_item_ids
        )
        values: list[list[Any]] = _header_row(
            context.args.get("encabezados"), MEDIDAS_GENERAL_HEADERS
        )
        header_rows = len(values)
        measurement_misses = 0
        for row in ordered_rows:
            measurement = _measurement_value(row)
            if measurement == NA_VALUE:
                measurement_misses += 1
            values.append(
                [
                    str(row.get("item_id") or ""),
                    row.get("sku") or row.get("normalized_sku") or "",
                    _current_value(row, "title"),
                    measurement,
                ]
            )
        return FormulaExecutionResult(
            values=normalize_response_rows(values, header_rows=header_rows),
            meta={
                "rows_count": len(ordered_rows),
                "measurement_misses": measurement_misses,
                **resolution.meta(),
            },
            recovery=resolution.recovery,
        )

    async def sheetseller_costo_envio_vendedor(
        self, context: FormulaExecutionContext
    ) -> FormulaExecutionResult:
        now = _as_utc_datetime(self._now_fn())
        await self._repository.require_read_model_productive(
            seller_id=context.seller_id,
            read_model=ORDERS_READ_MODEL,
            date_to=now,
            formula=context.contract.name,
        )
        pairs = _lookup_pairs(
            skus=context.args.get("skus"),
            item_ids=context.args.get("id_publicaciones"),
        )
        orders = await self._repository.find_orders(
            seller_id=context.seller_id,
            date_from=datetime(1970, 1, 1, tzinfo=UTC),
            date_to=_day_end(now),
            limit=None,
        )
        selected = _latest_shipping_order_lines_by_pair(orders, pairs=pairs)
        missing_order_ids = tuple(
            dict.fromkeys(
                _document_id(order)
                for order, _line in selected.values()
                if "shipment_id" in (order.get("unavailable_fields") or [])
            )
        )
        if missing_order_ids:
            raise FormulaDataUnavailableError(
                context.contract.name,
                "Latest relevant order shipment identity is unavailable.",
                read_model="orders",
                order_ids=missing_order_ids,
            )
        real_shipping_costs = await _real_shipping_costs_for_orders(
            repository=self._repository,
            seller_id=context.seller_id,
            orders=[order for order, _line in selected.values()],
        )
        latest_cost_by_pair = {
            pair: real_shipping_costs[_shipment_id(order)] / line.quantity
            for pair, (order, line) in selected.items()
        }
        values: list[list[Any]] = []
        misses = 0
        for pair in pairs:
            cost = latest_cost_by_pair.get((pair.sku, pair.item_id))
            if cost is None:
                misses += 1
                values.append([NA_VALUE])
                continue
            values.append([_sheet_number(cost)])
        return FormulaExecutionResult(
            values=values,
            meta={"partial_misses": misses, "orders_count": len(orders)},
        )

    async def sheetseller_envios_mercadoenvios(
        self, context: FormulaExecutionContext
    ) -> FormulaExecutionResult:
        now = _as_utc_datetime(self._now_fn())
        await self._repository.require_read_model_productive(
            seller_id=context.seller_id,
            read_model=ORDERS_READ_MODEL,
            date_to=now,
            formula=context.contract.name,
        )
        await self._repository.require_read_model_productive(
            seller_id=context.seller_id,
            read_model=SHIPMENTS_READ_MODEL,
            date_to=now,
            formula=context.contract.name,
        )
        orders = await self._repository.find_orders(
            seller_id=context.seller_id,
            date_from=datetime.combine((now - timedelta(days=29)).date(), time.min, tzinfo=UTC),
            date_to=_day_end(now),
            limit=None,
        )
        shipments = await _shipments_for_orders(
            repository=self._repository,
            seller_id=context.seller_id,
            orders=orders,
        )
        status_filter = _status_filter(context.args.get("estado_etiqueta", "todos"))
        rows = [
            _mercadoenvios_row(order, line, shipment=shipments.get(_shipment_id(order)))
            for order in orders
            if _order_is_non_cancelled(order)
            and (shipment := shipments.get(_shipment_id(order))) is not None
            and _shipment_is_open(shipment)
            and _shipment_matches_status(shipment, status_filter)
            for line in _order_lines(order)
        ]
        values: list[list[Any]] = _header_row(
            context.args.get("encabezados"), ENVIOS_MERCADOENVIOS_HEADERS
        )
        header_rows = len(values)
        values.extend(rows)
        return FormulaExecutionResult(
            values=normalize_response_rows(values, header_rows=header_rows),
            meta={
                "orders_count": len(rows),
                "status_filter": status_filter or "todos",
                "columns": "legacy_mercadoenvios",
            },
        )

    async def sheetseller_obtener_catalogo(
        self, context: FormulaExecutionContext
    ) -> FormulaExecutionResult:
        return await self._catalog_products(context, complete=False)

    async def sheetseller_catalogo_completo(
        self, context: FormulaExecutionContext
    ) -> FormulaExecutionResult:
        return await self._catalog_products(context, complete=True)

    async def _catalog_products(
        self, context: FormulaExecutionContext, *, complete: bool
    ) -> FormulaExecutionResult:
        (
            snapshots,
            missing,
            missing_items,
            inventory_current,
            source_missing,
        ) = await self._repository.find_recent_catalog_product_inventory(
            seller_id=context.seller_id,
            formula=context.contract.name,
            now=_as_utc_datetime(self._now_fn()),
        )
        headers = list(
            CATALOGO_COMPLETO_VISIBLE_HEADERS if complete else OBTENER_CATALOGO_VISIBLE_HEADERS
        )
        values = _header_row(context.args.get("encabezados"), headers)
        by_id = {snapshot["catalog_product_id"]: snapshot for snapshot in snapshots}
        cached_ids = set(by_id) & set(source_missing)
        recoverable = tuple(identity for identity in missing if identity not in source_missing)
        for identity in sorted(set(by_id) | set(missing)):
            values.append(
                _catalogo_completo_row(by_id[identity])[: len(headers)]
                if identity in by_id
                else ["DATA_UNAVAILABLE"] * len(headers)
            )
        inventory_gap = not inventory_current or bool(missing_items)
        if inventory_gap:
            values.append(["DATA_UNAVAILABLE"] * len(headers))
        recovery = None
        additional_recoveries = []
        if inventory_gap:
            recovery = FormulaDataUnavailableError(
                context.contract.name,
                "Current catalog inventory is incomplete or expired.",
                read_model=ITEM_FORMULA_ROWS_READ_MODEL,
                item_ids=missing_items if inventory_current else (),
            )
        if recoverable:
            catalog_recovery = FormulaDataUnavailableError(
                context.contract.name,
                "Catalog products are missing, expired or unverified.",
                read_model=CATALOG_PRODUCT_SNAPSHOTS_READ_MODEL,
                catalog_product_ids=recoverable,
            )
            if recovery is None:
                recovery = catalog_recovery
            else:
                additional_recoveries.append(catalog_recovery)
        return FormulaExecutionResult(
            values=values,
            recovery=recovery,
            additional_recoveries=tuple(additional_recoveries),
            meta={
                "rows_count": len(by_id) + len(missing) + int(inventory_gap),
                "available_products": len(by_id),
                "cached_products": len(cached_ids),
                "source_unavailable_products": len(source_missing),
                "unavailable_product_reasons": {
                    identity: "catalog_product_not_found" for identity in source_missing
                },
                "cached_product_observed_at": {
                    identity: _as_utc_datetime(by_id[identity]["snapshot_at"])
                    for identity in sorted(cached_ids)
                },
                "unavailable_products": len(missing),
                "unavailable_items": len(missing_items),
                "inventory_enumeration_current": inventory_current,
                "catalog_products_complete": not inventory_gap
                and not missing
                and not source_missing,
                **(
                    {
                        "unavailable_reason": "inventory_incomplete"
                        if inventory_gap
                        else "catalog_products_missing_or_expired"
                        if recoverable
                        else "catalog_product_not_found"
                    }
                    if recovery or source_missing
                    else {}
                ),
                "columns": "catalog_complete_current" if complete else "catalog_legacy_simple",
            },
        )

    async def sheetseller_catalogo_buybox(
        self, context: FormulaExecutionContext
    ) -> FormulaExecutionResult:
        (
            snapshots,
            missing,
            missing_items,
            current,
        ) = await self._repository.find_recent_catalog_buybox_inventory(
            seller_id=context.seller_id,
            formula=context.contract.name,
            now=_as_utc_datetime(self._now_fn()),
        )
        values: list[list[Any]] = _header_row(
            context.args.get("encabezados"), list(CATALOGOBUYBOX_VISIBLE_HEADERS)
        )
        by_id = {snapshot["item_id"]: snapshot for snapshot in snapshots}
        recoverable = set(missing)
        for identity in sorted(set(by_id) | set(missing)):
            row = (
                _catalogo_buybox_row(by_id[identity])
                if identity in by_id
                else ["DATA_UNAVAILABLE"] * 9
            )
            if "DATA_UNAVAILABLE" in row:
                recoverable.add(identity)
            values.append(row)
        inventory_gap = not current or bool(missing_items)
        if inventory_gap:
            values.append(["DATA_UNAVAILABLE"] * 9)
        reason = "inventory_incomplete" if inventory_gap else "buybox_missing_expired_or_incomplete"
        recovery = None
        additional_recoveries: tuple[FormulaDataUnavailableError, ...] = ()
        if inventory_gap or recoverable:
            recovery = FormulaDataUnavailableError(
                context.contract.name,
                "Buybox coverage is incomplete.",
                read_model=ITEM_FORMULA_ROWS_READ_MODEL
                if inventory_gap
                else CATALOG_BUYBOX_SNAPSHOTS_READ_MODEL,
                item_ids=(missing_items if current else ())
                if inventory_gap
                else tuple(sorted(recoverable)),
            )
        if inventory_gap and recoverable:
            additional_recoveries = (
                FormulaDataUnavailableError(
                    context.contract.name,
                    "Known catalog items need competition recovery.",
                    read_model=CATALOG_BUYBOX_SNAPSHOTS_READ_MODEL,
                    item_ids=tuple(sorted(recoverable)),
                ),
            )
        return FormulaExecutionResult(
            values=values,
            recovery=recovery,
            additional_recoveries=additional_recoveries,
            meta={
                "rows_count": len(by_id) + len(missing) + int(inventory_gap),
                "columns": "catalog_buybox_current",
                "inventory_enumeration_current": current,
                "unavailable_items": len(missing_items),
                "unavailable_buybox_items": len(recoverable),
                "buybox_complete": not inventory_gap and not recoverable,
                **({"unavailable_reason": reason} if recovery else {}),
            },
        )

    async def sheetseller_catalogos_sin_vincular(
        self, context: FormulaExecutionContext
    ) -> FormulaExecutionResult:
        resolution = await self._repository.resolve_item_formula_rows(
            seller_id=context.seller_id,
            formula=context.contract.name,
            now=_as_utc_datetime(self._now_fn()),
        )
        suggested_rows = [row for row in resolution.rows if _is_catalog_link_suggestion(row)]
        values: list[list[Any]] = _header_row(
            context.args.get("encabezados"), CATALOGOS_SIN_VINCULAR_HEADERS
        )
        values.extend(
            [str(row.get("item_id") or ""), _current_value(row, "title")] for row in suggested_rows
        )
        return FormulaExecutionResult(
            values=values,
            meta={
                "rows_count": len(suggested_rows),
                "columns": "catalog_link_suggestions",
                **resolution.meta(),
            },
            recovery=resolution.recovery,
        )


class _LookupPair:
    def __init__(self, *, sku: str, item_id: str) -> None:
        self.sku = sku
        self.item_id = item_id


class _OrderLine:
    def __init__(
        self,
        *,
        sku: str,
        item_id: str,
        title: str,
        quantity: Decimal,
    ) -> None:
        self.sku = sku
        self.item_id = item_id
        self.title = title
        self.quantity = quantity


async def _real_shipping_costs_for_orders(
    *,
    repository: FormulaReadModelRepository,
    seller_id: str,
    orders: Sequence[Mapping[str, Any]],
) -> dict[str, Decimal]:
    shipment_ids = list(
        dict.fromkeys(shipment_id for order in orders if (shipment_id := _shipment_id(order)))
    )
    return await repository.find_shipment_real_shipping_costs(
        seller_id=seller_id,
        shipment_ids=shipment_ids,
        limit=max(1000, len(shipment_ids)),
    )


async def _shipments_for_orders(
    *,
    repository: FormulaReadModelRepository,
    seller_id: str,
    orders: Sequence[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    shipment_ids = list(
        dict.fromkeys(shipment_id for order in orders if (shipment_id := _shipment_id(order)))
    )
    rows = await repository.find_shipments_by_ids(
        seller_id=seller_id,
        shipment_ids=shipment_ids,
        limit=max(1000, len(shipment_ids)),
    )
    return {str(row.get("_id") or "").strip(): row for row in rows if row.get("_id")}


def _latest_shipping_order_lines_by_pair(
    orders: Sequence[Mapping[str, Any]], *, pairs: Sequence[_LookupPair]
) -> dict[tuple[str, str], tuple[Mapping[str, Any], _OrderLine]]:
    wanted = {(pair.sku, pair.item_id) for pair in pairs}
    latest: dict[tuple[str, str], tuple[datetime, Mapping[str, Any], _OrderLine]] = {}
    for order in orders:
        if not _order_is_non_cancelled(order):
            continue
        created = _optional_datetime(order.get("date_created"))
        shipment_id = _shipment_id(order)
        shipment_unknown = "shipment_id" in (order.get("unavailable_fields") or [])
        if created is None or (not shipment_id and not shipment_unknown):
            continue
        for line in _order_lines(order):
            if not line.sku or not line.item_id or line.quantity <= 0:
                continue
            key = (line.sku, line.item_id)
            if key not in wanted:
                continue
            current = latest.get(key)
            if current is None or created > current[0]:
                latest[key] = (created, order, line)
    return {key: (order, line) for key, (_created, order, line) in latest.items()}


def _mercadoenvios_row(
    order: Mapping[str, Any], line: _OrderLine, *, shipment: Mapping[str, Any] | None
) -> list[Any]:
    shipment_values = shipment or {}
    return [
        _document_id(order),
        _official_pack_id(order),
        line.title,
        line.sku,
        _sheet_number(line.quantity),
        _shipment_status(shipment_values),
        _shipment_date(shipment_values),
        "Si" if bool(shipment_values.get("delayed")) else "No",
        _shipment_carrier(shipment_values),
    ]


def _catalogo_completo_row(snapshot: Mapping[str, Any]) -> list[Any]:
    return [
        _catalog_value(snapshot, "title"),
        _catalog_value(snapshot, "description"),
        _image_formula(_catalog_value(snapshot, "image_url")),
        _catalog_attribute(snapshot, "BRAND"),
        _catalog_attribute(snapshot, "MODEL"),
        _catalog_attribute(snapshot, "GTIN"),
    ]


def _catalogo_buybox_row(snapshot: Mapping[str, Any]) -> list[Any]:
    return [
        _catalog_value(snapshot, "title"),
        _catalog_value(snapshot, "item_id"),
        _catalog_value(snapshot, "catalog_product_id"),
        _sheet_optional_number(snapshot.get("available_quantity")),
        _catalog_value(snapshot, "buybox_status")
        if snapshot.get("buybox_status")
        else "DATA_UNAVAILABLE",
        _sheet_optional_number(snapshot.get("price"))
        if _optional_non_negative_decimal(snapshot.get("price")) is not None
        else "DATA_UNAVAILABLE",
        _sheet_optional_number(snapshot.get("winning_price")),
        catalog_shared_users(snapshot),
        snapshot["only_competitor"]
        if isinstance(snapshot.get("only_competitor"), bool)
        else "DATA_UNAVAILABLE",
    ]


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


def _normalize_optional_sku_argument(value: Any) -> list[str] | None:
    if isinstance(value, str) and value.strip().casefold() == "todos":
        return None
    return _flatten_sheet_values(value, normalize=normalize_sku)


def _normalize_optional_item_ids(value: Any) -> list[str] | None:
    if isinstance(value, str) and value.strip().casefold() == "todos":
        return None
    return _normalize_item_id_argument(value)


def _is_all_scope(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip().casefold() == "todos")


def _pairs_from_rows(rows: Sequence[Mapping[str, Any]]) -> list[_LookupPair]:
    pairs: list[_LookupPair] = []
    for row in rows:
        item_id = str(row.get("item_id") or "").strip()
        sku = normalize_sku(row.get("normalized_sku") or row.get("sku"))
        if item_id and sku:
            pairs.append(_LookupPair(sku=sku, item_id=item_id))
    return pairs


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


def _order_item_rows(
    rows: list[dict[str, Any]], *, requested_skus: list[str] | None, item_ids: list[str] | None
) -> list[dict[str, Any]]:
    sorted_rows = sorted(
        rows,
        key=lambda row: (
            str(row.get("item_id") or ""),
            normalize_sku(row.get("normalized_sku") or ""),
        ),
    )
    if item_ids:
        rows_by_item_id = _rows_grouped_by_item_id(sorted_rows)
        ordered = [
            row for item_id in dict.fromkeys(item_ids) for row in rows_by_item_id.get(item_id, [])
        ]
    elif requested_skus:
        rows_by_sku = _rows_grouped_by_sku(sorted_rows)
        ordered = [row for sku in dict.fromkeys(requested_skus) for row in rows_by_sku.get(sku, [])]
    else:
        ordered = sorted_rows
    return ordered


def _first_rows_by_item_id(rows: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    rows_by_item_id: dict[str, Mapping[str, Any]] = {}
    for row in sorted(rows, key=lambda current: normalize_sku(current.get("normalized_sku") or "")):
        item_id = str(row.get("item_id") or "").strip()
        if item_id and item_id not in rows_by_item_id:
            rows_by_item_id[item_id] = row
    return rows_by_item_id


def _rows_by_pair(rows: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], Mapping[str, Any]]:
    return {
        (
            normalize_sku(row.get("normalized_sku") or row.get("sku")),
            str(row.get("item_id") or ""),
        ): row
        for row in rows
    }


def _rows_grouped_by_item_id(rows: Sequence[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("item_id") or "").strip(), []).append(row)
    return grouped


def _rows_grouped_by_sku(rows: Sequence[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(normalize_sku(row.get("normalized_sku") or row.get("sku")), []).append(
            row
        )
    return grouped


def _current_mapping(row: Mapping[str, Any] | None) -> Mapping[str, Any]:
    current = row.get("current") if row is not None else None
    return current if isinstance(current, Mapping) else {}


def _current_value(row: Mapping[str, Any] | None, field: str) -> Any:
    value = _current_mapping(row).get(field)
    return "" if value is None else value


def _has_current_tag(row: Mapping[str, Any], expected_tag: str) -> bool:
    tags = _current_mapping(row).get("tags")
    if not isinstance(tags, Sequence) or isinstance(tags, (str, bytes)):
        return False
    return expected_tag in {str(tag).strip() for tag in tags}


def _measurement_value(row: Mapping[str, Any] | None) -> str:
    current = _current_mapping(row)
    dimensions = current.get("dimensions") or current.get("measurement") or current.get("measures")
    if not isinstance(dimensions, Mapping):
        return NA_VALUE
    length = _dimension_part(dimensions, "length", "largo")
    height = _dimension_part(dimensions, "height", "alto")
    width = _dimension_part(dimensions, "width", "ancho")
    if length is None or height is None or width is None:
        return NA_VALUE
    return f"{length} * {height} * {width}"


def _dimension_part(dimensions: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = dimensions.get(key)
        if value is not None and str(value).strip() != "":
            return str(_sheet_optional_number(value))
    return None


def _is_catalog_link_suggestion(row: Mapping[str, Any]) -> bool:
    current = _current_mapping(row)
    if str(current.get("catalog_product_id") or "").strip():
        return False
    if _has_current_tag(row, "catalog_suggestion") or _has_current_tag(row, "catalog_suggested"):
        return True
    suggestion = current.get("catalog_suggestion")
    return bool(suggestion)


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
        lines.append(
            _OrderLine(
                sku=normalize_sku(_item_sku(item)),
                item_id=item_id,
                title=_item_title(item),
                quantity=_decimal(item.get("quantity", item.get("qty", 0))),
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


def _order_is_non_cancelled(order: Mapping[str, Any]) -> bool:
    return str(order.get("status") or "").strip().casefold() not in NON_PRODUCTIVE_ORDER_STATUSES


def _shipment_is_open(shipment: Mapping[str, Any]) -> bool:
    return _shipment_status(shipment).casefold() not in CLOSED_SHIPMENT_STATUSES


def _shipment_matches_status(shipment: Mapping[str, Any], status_filter: str | None) -> bool:
    return (
        status_filter is None or _shipment_status(shipment).casefold() == status_filter.casefold()
    )


def _status_filter(value: Any) -> str | None:
    status = str(value or "todos").strip()
    if not status or status.casefold() == "todos":
        return None
    return status


def _shipment_id(order: Mapping[str, Any]) -> str:
    return str(order.get("shipment_id") or "").strip()


def _document_id(document: Mapping[str, Any]) -> str:
    return str(document.get("_id") or document.get("id") or "").strip()


def _official_pack_id(order: Mapping[str, Any]) -> str:
    value = order.get("meli_pack_id")
    if value is None:
        return "N/A"
    normalized = str(value).strip()
    return normalized or "N/A"


def _shipment_status(shipment: Mapping[str, Any]) -> str:
    return str(shipment.get("status") or shipment.get("label_status") or "").strip()


def _shipment_date(shipment: Mapping[str, Any]) -> str:
    for key in ("estimated_shipping_at", "shipping_deadline", "estimated_delivery_time"):
        value = shipment.get(key)
        if isinstance(value, Mapping):
            value = value.get("date") or value.get("estimated_date")
        if value is not None and str(value).strip():
            return str(value).strip()
    return NA_VALUE


def _shipment_carrier(shipment: Mapping[str, Any]) -> str:
    for key in ("carrier", "tracking_method", "logistic_type"):
        value = shipment.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return NA_VALUE


def _catalog_value(snapshot: Mapping[str, Any], field: str) -> Any:
    value = snapshot.get(field)
    return value if value is not None and str(value).strip() else NA_VALUE


def _catalog_attribute(snapshot: Mapping[str, Any], attribute_id: str) -> Any:
    attributes = snapshot.get("attributes")
    if isinstance(attributes, Mapping):
        value = attributes.get(attribute_id) or attributes.get(attribute_id.casefold())
        return value if value is not None and str(value).strip() else NA_VALUE
    if isinstance(attributes, Sequence) and not isinstance(attributes, (str, bytes)):
        for attribute in attributes:
            if not isinstance(attribute, Mapping):
                continue
            if str(attribute.get("id") or "").strip().upper() != attribute_id:
                continue
            value = attribute.get("value_name") or attribute.get("value") or attribute.get("name")
            return value if value is not None and str(value).strip() else NA_VALUE
    return NA_VALUE


def _image_formula(value: Any) -> str:
    if value == NA_VALUE or value is None or not str(value).strip():
        return NA_VALUE
    escaped = str(value).strip().replace('"', '""')
    return f'=IMAGE("{escaped}")'


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


def _day_end(value: datetime) -> datetime:
    parsed = _as_utc_datetime(value)
    return datetime.combine(parsed.date(), time.max, tzinfo=UTC)


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


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, ValueError):
        return Decimal("0")


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
