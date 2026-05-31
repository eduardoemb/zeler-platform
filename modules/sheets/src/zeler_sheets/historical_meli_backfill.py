from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol, cast
from urllib.parse import urlencode

from zeler_sheets.event_persistence import SheetsEventPersistence

DEFAULT_GATEWAY_BASE_URL = "http://gateway:8080/proxy/meli"
DEFAULT_GATEWAY_MODULE_ID = "bootstrap"
DEFAULT_ORDER_DETAIL_GATEWAY_MODULE_ID = "sheets"
DEFAULT_ORDER_PAGE_LIMIT = 50
ITEM_DETAIL_BATCH_SIZE = 20


class HistoricalMeliGateway(Protocol):
    async def fetch_resource(self, *, seller_id: str, path: str) -> Any: ...


@dataclass(frozen=True)
class InclusiveDateRange:
    date_from: str
    date_to: str
    start: datetime
    end_exclusive: datetime


@dataclass(frozen=True)
class HistoricalMeliBackfillSummary:
    seller_id: str
    dry_run: bool
    status: str
    date_from: str
    date_to: str
    date_to_exclusive: str
    max_orders: int | None
    orders_found: int
    orders_fetched: int
    items_fetched: int
    shipments_fetched: int
    item_detail_missing: int
    existing_orders: int
    existing_items: int
    existing_shipments: int
    missing_orders: int
    missing_items: int
    missing_shipments: int
    planned_orders: int
    planned_items: int
    planned_shipments: int
    written_orders: int
    written_items: int
    written_shipments: int
    order_ids: list[str]
    item_ids: list[str]
    missing_item_detail_ids: list[str]
    shipment_ids: list[str]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_inclusive_date_range(date_from: str, date_to: str) -> InclusiveDateRange:
    start_date = _parse_cli_date(date_from, field_name="date-from")
    end_date = _parse_cli_date(date_to, field_name="date-to")
    if end_date < start_date:
        raise ValueError("date-to must be on or after date-from")
    start = datetime.combine(start_date, datetime.min.time(), tzinfo=UTC)
    end_exclusive = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    return InclusiveDateRange(
        date_from=start_date.isoformat(),
        date_to=end_date.isoformat(),
        start=start,
        end_exclusive=end_exclusive,
    )


async def run_historical_meli_backfill(
    *,
    db: Any,
    gateway: HistoricalMeliGateway,
    order_detail_gateway: HistoricalMeliGateway,
    seller_id: str,
    date_from: str,
    date_to: str,
    dry_run: bool = True,
    approved_runtime: bool = False,
    max_orders: int | None = None,
) -> HistoricalMeliBackfillSummary:
    seller_id = str(seller_id)
    if not dry_run and not approved_runtime:
        raise ValueError("approved_runtime is required when dry_run is false")
    if max_orders is not None and max_orders < 1:
        raise ValueError("max-orders must be greater than zero")

    date_range = parse_inclusive_date_range(date_from, date_to)
    search_orders = await _search_orders(
        gateway=gateway,
        seller_id=seller_id,
        date_range=date_range,
        max_orders=max_orders,
    )
    order_ids = _unique_strings(_resource_id(order) for order in search_orders)
    orders = [
        cast(
            "dict[str, Any]",
            await order_detail_gateway.fetch_resource(
                seller_id=seller_id,
                path=f"/orders/{order_id}",
            ),
        )
        for order_id in order_ids
    ]

    item_ids = _unique_strings(
        item_id for order in orders for item_id in _extract_order_item_ids(order)
    )
    shipment_ids = _unique_strings(
        shipment_id
        for order in orders
        for shipment_id in [_extract_shipment_id(order)]
        if shipment_id
    )

    items = await _fetch_items(gateway=gateway, seller_id=seller_id, item_ids=item_ids)
    fetched_item_ids = set(_unique_strings(_resource_id(item) for item in items))
    missing_item_detail_ids = [item_id for item_id in item_ids if item_id not in fetched_item_ids]
    if missing_item_detail_ids and not dry_run:
        raise ValueError(
            "missing item details for "
            f"{len(missing_item_detail_ids)} item(s); refusing to write partial backfill"
        )
    shipments = [
        cast(
            "dict[str, Any]",
            await gateway.fetch_resource(seller_id=seller_id, path=f"/shipments/{shipment_id}"),
        )
        for shipment_id in shipment_ids
    ]

    existing_orders = await _count_existing(
        db=db, collection="orders", seller_id=seller_id, ids=order_ids
    )
    existing_items = await _count_existing(
        db=db, collection="items", seller_id=seller_id, ids=item_ids
    )
    existing_shipments = await _count_existing(
        db=db, collection="shipments", seller_id=seller_id, ids=shipment_ids
    )

    missing_orders = len(order_ids) - existing_orders
    missing_items = len(item_ids) - existing_items
    missing_shipments = len(shipment_ids) - existing_shipments
    written_orders = 0
    written_items = 0
    written_shipments = 0

    if not dry_run:
        persistence = SheetsEventPersistence(db=db)
        for order in orders:
            await persistence.persist(
                event_type="orders.updated", seller_id=seller_id, resource=order
            )
            written_orders += 1
        for item in items:
            await persistence.persist(
                event_type="items.updated", seller_id=seller_id, resource=item
            )
            written_items += 1
        for shipment in shipments:
            await persistence.persist(
                event_type="shipments.updated", seller_id=seller_id, resource=shipment
            )
            written_shipments += 1

    status = "dry_run_complete" if dry_run else "write_complete"
    return HistoricalMeliBackfillSummary(
        seller_id=seller_id,
        dry_run=dry_run,
        status=status,
        date_from=date_range.date_from,
        date_to=date_range.date_to,
        date_to_exclusive=_meli_datetime(date_range.end_exclusive),
        max_orders=max_orders,
        orders_found=len(order_ids),
        orders_fetched=len(orders),
        items_fetched=len(items),
        shipments_fetched=len(shipments),
        item_detail_missing=len(missing_item_detail_ids),
        existing_orders=existing_orders,
        existing_items=existing_items,
        existing_shipments=existing_shipments,
        missing_orders=missing_orders,
        missing_items=missing_items,
        missing_shipments=missing_shipments,
        planned_orders=len(orders),
        planned_items=len(items),
        planned_shipments=len(shipments),
        written_orders=written_orders,
        written_items=written_items,
        written_shipments=written_shipments,
        order_ids=order_ids,
        item_ids=item_ids,
        missing_item_detail_ids=missing_item_detail_ids,
        shipment_ids=shipment_ids,
    )


async def _search_orders(
    *,
    gateway: HistoricalMeliGateway,
    seller_id: str,
    date_range: InclusiveDateRange,
    max_orders: int | None,
) -> list[dict[str, Any]]:
    orders: list[dict[str, Any]] = []
    offset = 0
    while True:
        remaining = None if max_orders is None else max_orders - len(orders)
        if remaining is not None and remaining <= 0:
            break
        limit = min(DEFAULT_ORDER_PAGE_LIMIT, remaining or DEFAULT_ORDER_PAGE_LIMIT)
        page = await gateway.fetch_resource(
            seller_id=seller_id,
            path=_build_order_search_path(
                seller_id=seller_id,
                date_range=date_range,
                offset=offset,
                limit=limit,
            ),
        )
        page_orders = _page_results(page)
        orders.extend(page_orders[:remaining])
        paging = page.get("paging", {}) if isinstance(page, dict) else {}
        total = _optional_int(paging.get("total")) if isinstance(paging, dict) else None
        if not page_orders or len(page_orders) < limit:
            break
        offset += limit
        if total is not None and offset >= total:
            break
    return orders


def _build_order_search_path(
    *, seller_id: str, date_range: InclusiveDateRange, offset: int, limit: int
) -> str:
    query = urlencode(
        {
            "seller": seller_id,
            "order.date_created.from": _meli_datetime(date_range.start),
            "order.date_created.to": _meli_datetime(
                date_range.end_exclusive - timedelta(milliseconds=1), include_milliseconds=True
            ),
            "sort": "date_asc",
            "offset": str(offset),
            "limit": str(limit),
        }
    )
    return f"/orders/search?{query}"


async def _fetch_items(
    *, gateway: HistoricalMeliGateway, seller_id: str, item_ids: Sequence[str]
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for batch in _chunks(item_ids, ITEM_DETAIL_BATCH_SIZE):
        response = await gateway.fetch_resource(
            seller_id=seller_id, path=f"/items?ids={','.join(batch)}"
        )
        items.extend(_parse_item_detail_response(response))
    return items


async def _count_existing(*, db: Any, collection: str, seller_id: str, ids: Sequence[str]) -> int:
    existing = 0
    for document_id in ids:
        found = await db[collection].find_one({"_id": document_id, "seller_id": seller_id})
        if found is not None:
            existing += 1
    return existing


def _parse_cli_date(value: str, *, field_name: str) -> date:
    normalized = value.strip()
    if len(normalized) != 10:
        raise ValueError(f"{field_name} must use YYYY-MM-DD")
    try:
        return date.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{field_name} must use YYYY-MM-DD") from exc


def _meli_datetime(value: datetime, *, include_milliseconds: bool = False) -> str:
    parsed = value.astimezone(UTC)
    if include_milliseconds:
        milliseconds = parsed.microsecond // 1000
        return parsed.strftime("%Y-%m-%dT%H:%M:%S") + f".{milliseconds:03d}Z"
    return parsed.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _page_results(page: Any) -> list[dict[str, Any]]:
    if not isinstance(page, dict):
        return []
    results = page.get("results")
    if not isinstance(results, list):
        return []
    return [result for result in results if isinstance(result, dict)]


def _parse_item_detail_response(response: Any) -> list[dict[str, Any]]:
    if isinstance(response, dict):
        body = response.get("body") if "body" in response else response
        return [body] if isinstance(body, dict) else []
    if not isinstance(response, list):
        return []
    items: list[dict[str, Any]] = []
    for entry in response:
        if not isinstance(entry, dict):
            continue
        if "body" in entry:
            body = entry.get("body")
            if isinstance(body, dict) and _resource_id(body) is not None:
                items.append(body)
            continue
        if _resource_id(entry) is not None:
            items.append(entry)
    return items


def _extract_order_item_ids(order: dict[str, Any]) -> list[str]:
    raw_items = order.get("order_items") or order.get("items") or []
    if not isinstance(raw_items, Sequence) or isinstance(raw_items, (str, bytes)):
        return []
    ids: list[str] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        item = raw_item.get("item")
        item_id = _resource_id(item) if isinstance(item, dict) else raw_item.get("item_id")
        if item_id is not None:
            ids.append(item_id)
    return ids


def _extract_shipment_id(order: dict[str, Any]) -> str | None:
    shipping = order.get("shipping")
    if isinstance(shipping, dict):
        return _optional_string(shipping.get("id") or shipping.get("shipment_id"))
    return _optional_string(order.get("shipment_id"))


def _resource_id(resource: Any) -> str | None:
    if not isinstance(resource, dict):
        return None
    return _optional_string(resource.get("id") or resource.get("_id"))


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _unique_strings(values: Sequence[str | None] | Any) -> list[str]:
    unique: dict[str, None] = {}
    for value in values:
        if value is None:
            continue
        normalized = str(value).strip()
        if normalized:
            unique.setdefault(normalized, None)
    return list(unique)


def _chunks(values: Sequence[str], size: int) -> list[list[str]]:
    return [list(values[index : index + size]) for index in range(0, len(values), size)]


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Safely backfill historical MercadoLibre orders/items/shipments for Sheetseller."
        )
    )
    parser.add_argument("--seller-id", required=True, help="Seller id to backfill.")
    parser.add_argument("--date-from", required=True, help="Inclusive start date (YYYY-MM-DD).")
    parser.add_argument("--date-to", required=True, help="Inclusive end date (YYYY-MM-DD).")
    parser.add_argument(
        "--max-orders",
        "--limit",
        dest="max_orders",
        type=_positive_int,
        help="Optional maximum orders to process for trial runs.",
    )
    parser.add_argument(
        "--module-id",
        default=DEFAULT_GATEWAY_MODULE_ID,
        help=(
            "Gateway admin client module id for order search, item detail, and shipment detail. "
            f"Defaults to {DEFAULT_GATEWAY_MODULE_ID!r}."
        ),
    )
    parser.add_argument(
        "--order-detail-module-id",
        default=DEFAULT_ORDER_DETAIL_GATEWAY_MODULE_ID,
        help=(
            "Gateway admin client module id for /orders/{id} detail fetches. "
            f"Defaults to {DEFAULT_ORDER_DETAIL_GATEWAY_MODULE_ID!r}."
        ),
    )
    parser.add_argument(
        "--confirm-approved-runtime",
        action="store_true",
        help="Required with --write to confirm execution from an approved runtime context.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        default=True,
        help="Fetch and summarize only; do not write (default).",
    )
    mode.add_argument(
        "--write",
        action="store_false",
        dest="dry_run",
        help="Explicitly perform idempotent canonical upserts.",
    )
    return parser


def validate_cli_safety(args: argparse.Namespace) -> None:
    if not bool(args.dry_run) and not bool(args.confirm_approved_runtime):
        raise SystemExit("--confirm-approved-runtime is required with --write")


async def _run_cli(args: argparse.Namespace) -> HistoricalMeliBackfillSummary:
    validate_cli_safety(args)

    from motor.motor_asyncio import AsyncIOMotorClient

    from zeler_platform_core.auth.meli_gateway_auth import MeliGatewayAuth
    from zeler_platform_core.clients.meli_gateway_client import MeliGatewayClient

    mongo_uri = os.environ.get("MONGO_URI")
    mongo_db_name = os.environ.get("MONGO_DB")
    if not mongo_uri:
        raise SystemExit("MONGO_URI is required")
    if not mongo_db_name:
        raise SystemExit("MONGO_DB is required")

    from google.cloud import kms

    client: AsyncIOMotorClient[Any] = AsyncIOMotorClient(mongo_uri)
    try:
        gateway_base_url = os.environ.get("GATEWAY_BASE_URL", DEFAULT_GATEWAY_BASE_URL)
        kms_client = kms.KeyManagementServiceClient()
        gateway = MeliGatewayClient(
            gateway_base_url,
            MeliGatewayAuth(str(args.module_id), kms_client),
        )
        order_detail_gateway = gateway
        if str(args.order_detail_module_id) != str(args.module_id):
            order_detail_gateway = MeliGatewayClient(
                gateway_base_url,
                MeliGatewayAuth(str(args.order_detail_module_id), kms_client),
            )
        return await run_historical_meli_backfill(
            db=client[mongo_db_name],
            gateway=gateway,
            order_detail_gateway=order_detail_gateway,
            seller_id=str(args.seller_id),
            date_from=str(args.date_from),
            date_to=str(args.date_to),
            dry_run=bool(args.dry_run),
            approved_runtime=bool(args.confirm_approved_runtime),
            max_orders=cast("int | None", args.max_orders),
        )
    finally:
        client.close()


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        summary = asyncio.run(_run_cli(args))
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(summary.as_dict(), sort_keys=True))


if __name__ == "__main__":
    main()
