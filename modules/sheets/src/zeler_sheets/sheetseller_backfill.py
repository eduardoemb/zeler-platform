from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, cast
from urllib.parse import quote

import httpx
from bson.decimal128 import Decimal128

from zeler_platform_core.clients.meli_gateway_client import GatewayRateLimitError
from zeler_platform_core.models import Item
from zeler_platform_core.models.base import current_schema_version
from zeler_sheets.formulas.read_models import normalize_sku

ITEMS_COLLECTION = "items"
ORDERS_COLLECTION = "orders"
ITEM_SKU_INDEX_COLLECTION = "sheets_item_sku_index"
ITEM_FORMULA_ROWS_COLLECTION = "sheets_item_formula_rows"
READ_MODEL_SCHEMA_VERSION = 2
SELLER_SKU_ATTRIBUTE_ID = "SELLER_SKU"
DEFAULT_GATEWAY_BASE_URL = "http://gateway:8080/proxy/meli"
ITEM_DETAIL_BATCH_SIZE = 20


class MeliOrderGatewayClient(Protocol):
    async def fetch_resource(self, *, seller_id: str, path: str) -> dict[str, Any]: ...


class MeliItemGatewayClient(Protocol):
    async def fetch_resource(self, *, seller_id: str, path: str) -> Any: ...


@dataclass(frozen=True)
class BackfillSummary:
    seller_id: str
    dry_run: bool
    items_read: int
    items_with_sku: int
    skipped_missing_sku: int
    sku_index_upserts: int
    formula_row_upserts: int
    variation_sku_rows: int
    skipped_missing_variation_sku: int
    skipped_ambiguous_sku: int
    planned: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped_missing_source: int = 0
    skipped_ambiguous: int = 0
    errors: int = 0
    formula_rows_with_permalink: int = 0
    formula_rows_with_thumbnail: int = 0
    formula_rows_with_catalog_product_id: int = 0
    formula_rows_with_inventory_id: int = 0
    skipped_ambiguous_formula_identity: int = 0

    def as_dict(self) -> dict[str, int | bool | str]:
        return asdict(self)


@dataclass(frozen=True)
class OrderLineIdentityBackfillSummary:
    seller_id: str
    dry_run: bool
    orders_read: int
    order_lines_read: int
    order_lines_with_direct_sku: int
    order_lines_with_variation_id: int
    deterministic_pairs: int
    ambiguous_pairs: int
    sku_index_upserts: int

    def as_dict(self) -> dict[str, int | bool | str]:
        return asdict(self)


@dataclass(frozen=True)
class OrderIdentityRepairSummary:
    seller_id: str
    dry_run: bool
    date_from: str
    date_to: str
    orders_read: int
    orders_fetched: int
    orders_with_safe_identity: int
    orders_updated: int
    order_lines_read: int
    enriched_order_lines: int
    matched_order_lines: int
    updated_order_lines: int
    identity_fields_added: int
    skipped_unmatched_lines: int

    def as_dict(self) -> dict[str, int | bool | str]:
        return asdict(self)


@dataclass(frozen=True)
class OrderNormalizationSummary:
    seller_id: str
    dry_run: bool
    date_from: str
    date_to: str
    orders_read: int
    orders_to_update: int
    orders_updated: int
    date_fields_converted: int
    money_fields_converted: int
    skipped_unparseable_orders: int
    unparseable_date_values: int
    unparseable_money_values: int

    def as_dict(self) -> dict[str, int | bool | str]:
        return asdict(self)


@dataclass(frozen=True)
class ItemDetailEnrichmentSummary:
    dry_run: bool
    items_read: int
    batches_fetched: int
    item_details_returned: int
    items_validated: int
    items_planned: int
    items_updated: int
    unchanged: int
    shipping_options_requested: int = 0
    seller_shipping_costs_enriched: int = 0
    seller_shipping_costs_unavailable: int = 0

    def as_dict(self) -> dict[str, int | bool | str]:
        return asdict(self)


@dataclass(frozen=True)
class OrderIdentityMergeStats:
    matched_order_lines: int = 0
    updated_order_lines: int = 0
    identity_fields_added: int = 0
    skipped_unmatched_lines: int = 0


BackfillCliSummary = (
    BackfillSummary
    | ItemDetailEnrichmentSummary
    | OrderLineIdentityBackfillSummary
    | OrderIdentityRepairSummary
    | OrderNormalizationSummary
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill Sheetseller formula read models from canonical items."
    )
    parser.add_argument("--seller-id", required=True, help="Seller id to backfill.")
    parser.add_argument(
        "--source",
        choices=("items", "items-enrich", "order-lines", "orders-repair", "orders-normalize"),
        default="items",
        help="Read-model source to backfill (default: items).",
    )
    parser.add_argument(
        "--date-from",
        help="Inclusive order date start (YYYY-MM-DD) for order-scoped sources.",
    )
    parser.add_argument(
        "--date-to",
        help="Inclusive order date end (YYYY-MM-DD) for order-scoped sources.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        default=True,
        help="Read and summarize only; do not write read models (default).",
    )
    mode.add_argument(
        "--write",
        action="store_false",
        dest="dry_run",
        help="Explicitly write idempotent read-model upserts.",
    )
    return parser


async def run_sheetseller_backfill(
    *, db: Any, seller_id: str, dry_run: bool = True
) -> BackfillSummary:
    items = await _load_seller_items(db=db, seller_id=seller_id)
    items_with_sku = 0
    skipped_missing_sku = 0
    variation_sku_rows = 0
    skipped_missing_variation_sku = 0
    skipped_ambiguous_sku = 0
    sku_index_upserts = 0
    formula_row_upserts = 0
    planned = 0
    updated = 0
    unchanged = 0
    skipped_missing_source = 0
    skipped_ambiguous_formula_identity = 0
    formula_rows_with_permalink = 0
    formula_rows_with_thumbnail = 0
    formula_rows_with_catalog_product_id = 0
    formula_rows_with_inventory_id = 0

    sku_index_collection = db[ITEM_SKU_INDEX_COLLECTION]
    formula_rows_collection = db[ITEM_FORMULA_ROWS_COLLECTION]
    order_line_identities_by_item = await load_order_line_sku_identities_by_item(
        sku_index_collection,
        seller_id=seller_id,
    )

    for item in items:
        sku_index_docs: list[dict[str, Any]]
        formula_row_docs: list[dict[str, Any]]
        item_sku = resolve_seller_sku(item)
        if item_sku.ambiguous:
            skipped_ambiguous_sku += 1
            sku_index_docs = []
            formula_row_docs = []
        elif item_sku.sku is None:
            skipped_missing_sku += 1
            sku_index_docs = []
            formula_row_docs = []
        else:
            items_with_sku += 1
            sku_index_docs = [build_sku_index_doc(item, seller_id=seller_id, sku=item_sku.sku)]
            formula_row_docs = [build_formula_row_doc(item, seller_id=seller_id, sku=item_sku.sku)]

        variation_docs, variation_skips, variation_ambiguous = build_variation_sku_index_docs(
            item, seller_id=seller_id
        )
        variation_sku_rows += len(variation_docs)
        skipped_missing_variation_sku += variation_skips
        skipped_ambiguous_sku += variation_ambiguous
        sku_index_docs.extend(variation_docs)
        variation_formula_rows, variation_missing_source, variation_ambiguous_identity = (
            build_variation_formula_row_docs(item, variation_docs, seller_id=seller_id)
        )
        formula_row_docs.extend(variation_formula_rows)
        skipped_missing_source += variation_missing_source
        skipped_ambiguous_formula_identity += variation_ambiguous_identity
        order_line_formula_rows = build_order_line_formula_row_docs(
            item,
            order_line_identities=order_line_identities_by_item.get(_item_id(item), ()),
            seller_id=seller_id,
        )
        formula_row_docs.extend(order_line_formula_rows)
        formula_row_docs = _dedupe_formula_row_docs(formula_row_docs)

        if not sku_index_docs and not formula_row_docs:
            continue

        sku_index_upserts += len(sku_index_docs)
        formula_row_upserts += len(formula_row_docs)

        changed_formula_rows: list[dict[str, Any]] = []
        for formula_row_doc in formula_row_docs:
            diagnostics = _formula_row_diagnostics(formula_row_doc)
            skipped_missing_source += 1 if diagnostics["missing_source"] else 0
            formula_rows_with_permalink += int(diagnostics["with_permalink"])
            formula_rows_with_thumbnail += int(diagnostics["with_thumbnail"])
            formula_rows_with_catalog_product_id += int(diagnostics["with_catalog_product_id"])
            formula_rows_with_inventory_id += int(diagnostics["with_inventory_id"])
            if await _is_existing_document_unchanged(formula_rows_collection, formula_row_doc):
                unchanged += 1
                continue
            planned += 1
            changed_formula_rows.append(formula_row_doc)

        if not dry_run:
            for sku_index_doc in sku_index_docs:
                await sku_index_collection.replace_one(
                    {"_id": sku_index_doc["_id"]}, sku_index_doc, upsert=True
                )
            for formula_row_doc in changed_formula_rows:
                await formula_rows_collection.replace_one(
                    {"_id": formula_row_doc["_id"]}, formula_row_doc, upsert=True
                )
                updated += 1

    return BackfillSummary(
        seller_id=seller_id,
        dry_run=dry_run,
        items_read=len(items),
        items_with_sku=items_with_sku,
        skipped_missing_sku=skipped_missing_sku,
        sku_index_upserts=sku_index_upserts,
        formula_row_upserts=formula_row_upserts,
        variation_sku_rows=variation_sku_rows,
        skipped_missing_variation_sku=skipped_missing_variation_sku,
        skipped_ambiguous_sku=skipped_ambiguous_sku,
        planned=planned,
        updated=updated,
        unchanged=unchanged,
        skipped_missing_source=skipped_missing_source,
        skipped_ambiguous=skipped_ambiguous_sku + skipped_ambiguous_formula_identity,
        errors=0,
        formula_rows_with_permalink=formula_rows_with_permalink,
        formula_rows_with_thumbnail=formula_rows_with_thumbnail,
        formula_rows_with_catalog_product_id=formula_rows_with_catalog_product_id,
        formula_rows_with_inventory_id=formula_rows_with_inventory_id,
        skipped_ambiguous_formula_identity=skipped_ambiguous_formula_identity,
    )


async def run_item_detail_enrichment(
    *,
    db: Any,
    gateway: MeliItemGatewayClient,
    seller_id: str,
    dry_run: bool = True,
    batch_size: int = ITEM_DETAIL_BATCH_SIZE,
) -> ItemDetailEnrichmentSummary:
    if batch_size < 1:
        msg = "batch_size must be positive"
        raise ValueError(msg)

    existing_items = await _load_seller_items(db=db, seller_id=seller_id)
    existing_by_id = {_item_id(item): item for item in existing_items}
    item_ids = sorted(existing_by_id)
    synced_at = datetime.now(UTC)
    write_plans: list[tuple[dict[str, Any], dict[str, Any]]] = []
    batches_fetched = 0
    details_returned = 0
    items_validated = 0
    unchanged = 0
    shipping_options_requested = 0
    seller_shipping_costs_enriched = 0
    seller_shipping_costs_unavailable = 0

    for batch in _chunks(item_ids, batch_size):
        response = await gateway.fetch_resource(
            seller_id=seller_id,
            path=_item_detail_batch_path(batch),
        )
        batches_fetched += 1
        raw_details = _extract_item_detail_entries(response)
        details_returned += len(raw_details)
        by_id = _validated_detail_entries_by_id(
            raw_details, expected_ids=set(batch), seller_id=seller_id
        )
        if set(by_id) != set(batch):
            msg = "item detail batch did not return every requested item"
            raise RuntimeError(msg)
        for item_id in batch:
            detail = dict(by_id[item_id])
            seller_shipping_cost = await _resolve_seller_shipping_cost(
                gateway=gateway,
                seller_id=seller_id,
                item_id=item_id,
                detail=detail,
            )
            is_free_shipping = _is_seller_paid_free_shipping(detail)
            if is_free_shipping:
                shipping_options_requested += 1
            if seller_shipping_cost is None:
                if is_free_shipping:
                    seller_shipping_costs_unavailable += 1
            else:
                seller_shipping_costs_enriched += 1
            detail["seller_shipping_cost"] = seller_shipping_cost
            document = _canonical_item_detail_document(
                existing=existing_by_id[item_id],
                detail=detail,
                seller_id=seller_id,
                synced_at=synced_at,
            )
            items_validated += 1
            if _canonical_item_values_equal(existing_by_id[item_id], document):
                unchanged += 1
                continue
            write_plans.append(({"_id": item_id, "seller_id": seller_id}, document))

    items_updated = 0
    if not dry_run:
        items_collection = db[ITEMS_COLLECTION]
        for filter_spec, document in write_plans:
            await items_collection.update_one(
                filter_spec,
                {"$set": document},
                upsert=False,
                bypass_document_validation=False,
            )
            items_updated += 1

    return ItemDetailEnrichmentSummary(
        dry_run=dry_run,
        items_read=len(existing_items),
        batches_fetched=batches_fetched,
        item_details_returned=details_returned,
        items_validated=items_validated,
        items_planned=len(write_plans),
        items_updated=items_updated,
        unchanged=unchanged,
        shipping_options_requested=shipping_options_requested,
        seller_shipping_costs_enriched=seller_shipping_costs_enriched,
        seller_shipping_costs_unavailable=seller_shipping_costs_unavailable,
    )


async def run_order_line_identity_backfill(
    *,
    db: Any,
    seller_id: str,
    dry_run: bool = True,
    date_from: str | None = None,
    date_to: str | None = None,
) -> OrderLineIdentityBackfillSummary:
    orders = await _load_seller_orders(
        db=db, seller_id=seller_id, date_from=date_from, date_to=date_to
    )
    order_lines_read = 0
    order_lines_with_direct_sku = 0
    order_lines_with_variation_id = 0
    identities: dict[tuple[str, str | None], dict[str, _OrderLineIdentityCandidate]] = {}

    for order in orders:
        if _is_cancelled_order(order):
            continue
        updated_at = order.get("date_created") or order.get("updated_at")
        for item in _order_line_items(order):
            order_lines_read += 1
            variation_id = _order_line_variation_id(item)
            if variation_id is not None:
                order_lines_with_variation_id += 1
            sku = resolve_order_line_sku(item)
            if sku is None:
                continue
            order_lines_with_direct_sku += 1
            item_id = _order_line_item_id(item)
            if item_id is None:
                continue
            identity_key = (item_id, variation_id)
            by_sku = identities.setdefault(identity_key, {})
            normalized_sku = normalize_sku(sku)
            by_sku.setdefault(
                normalized_sku,
                _OrderLineIdentityCandidate(
                    sku=sku,
                    item_id=item_id,
                    variation_id=variation_id,
                    updated_at=updated_at,
                ),
            )

    deterministic_candidates: list[_OrderLineIdentityCandidate] = []
    ambiguous_pairs = 0
    for by_sku in identities.values():
        if len(by_sku) == 1:
            deterministic_candidates.append(next(iter(by_sku.values())))
        elif len(by_sku) > 1:
            ambiguous_pairs += 1

    sku_index_collection = db[ITEM_SKU_INDEX_COLLECTION]
    sku_index_docs = [
        build_order_line_sku_index_doc(candidate, seller_id=seller_id)
        for candidate in deterministic_candidates
    ]
    if not dry_run:
        for sku_index_doc in sku_index_docs:
            await sku_index_collection.replace_one(
                {"_id": sku_index_doc["_id"]}, sku_index_doc, upsert=True
            )

    return OrderLineIdentityBackfillSummary(
        seller_id=seller_id,
        dry_run=dry_run,
        orders_read=len(orders),
        order_lines_read=order_lines_read,
        order_lines_with_direct_sku=order_lines_with_direct_sku,
        order_lines_with_variation_id=order_lines_with_variation_id,
        deterministic_pairs=len(deterministic_candidates),
        ambiguous_pairs=ambiguous_pairs,
        sku_index_upserts=len(sku_index_docs),
    )


async def run_order_identity_repair(
    *,
    db: Any,
    gateway: MeliOrderGatewayClient,
    seller_id: str,
    date_from: str,
    date_to: str,
    dry_run: bool = True,
) -> OrderIdentityRepairSummary:
    orders = await _load_seller_orders(
        db=db, seller_id=seller_id, date_from=date_from, date_to=date_to
    )
    orders_fetched = 0
    orders_with_safe_identity = 0
    orders_updated = 0
    order_lines_read = 0
    enriched_order_lines = 0
    matched_order_lines = 0
    updated_order_lines = 0
    identity_fields_added = 0
    skipped_unmatched_lines = 0
    orders_collection = db[ORDERS_COLLECTION]
    write_plans: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []

    for order in orders:
        existing_items = _order_line_items(order)
        order_lines_read += len(existing_items)
        order_id = str(order.get("_id") or order.get("id") or "").strip()
        if not order_id:
            skipped_unmatched_lines += len(existing_items)
            continue

        payload = await gateway.fetch_resource(seller_id=seller_id, path=f"/orders/{order_id}")
        orders_fetched += 1
        enriched_items = [
            identity
            for raw_item in _order_line_items(payload)
            if _has_safe_identity_fields(identity := extract_safe_order_item_identity(raw_item))
        ]
        enriched_order_lines += len(enriched_items)
        if enriched_items:
            orders_with_safe_identity += 1

        merged_items, stats = merge_order_items_identity(existing_items, enriched_items)
        matched_order_lines += stats.matched_order_lines
        updated_order_lines += stats.updated_order_lines
        identity_fields_added += stats.identity_fields_added
        skipped_unmatched_lines += stats.skipped_unmatched_lines

        if stats.identity_fields_added > 0:
            write_plans.append(({"_id": order["_id"], "seller_id": seller_id}, merged_items))

    if not dry_run:
        for filter_spec, merged_items in write_plans:
            await orders_collection.update_one(
                filter_spec,
                {"$set": {"items": merged_items}},
                upsert=False,
                bypass_document_validation=True,
            )
            orders_updated += 1

    return OrderIdentityRepairSummary(
        seller_id=seller_id,
        dry_run=dry_run,
        date_from=date_from,
        date_to=date_to,
        orders_read=len(orders),
        orders_fetched=orders_fetched,
        orders_with_safe_identity=orders_with_safe_identity,
        orders_updated=orders_updated,
        order_lines_read=order_lines_read,
        enriched_order_lines=enriched_order_lines,
        matched_order_lines=matched_order_lines,
        updated_order_lines=updated_order_lines,
        identity_fields_added=identity_fields_added,
        skipped_unmatched_lines=skipped_unmatched_lines,
    )


async def run_order_normalization(
    *,
    db: Any,
    seller_id: str,
    date_from: str,
    date_to: str,
    dry_run: bool = True,
) -> OrderNormalizationSummary:
    orders = await _load_seller_orders(
        db=db, seller_id=seller_id, date_from=date_from, date_to=date_to
    )
    orders_collection = db[ORDERS_COLLECTION]
    write_plans: list[tuple[dict[str, Any], dict[str, Any]]] = []
    date_fields_converted = 0
    money_fields_converted = 0
    skipped_unparseable_orders = 0
    unparseable_date_values = 0
    unparseable_money_values = 0

    for order in orders:
        set_fields: dict[str, Any] = {}
        order_unparseable_dates = 0
        order_unparseable_money = 0

        for field in ("date_created", "date_closed"):
            value = order.get(field)
            if not isinstance(value, str):
                continue
            parsed_date = _parse_order_datetime(value)
            if parsed_date is None:
                order_unparseable_dates += 1
                continue
            set_fields[field] = parsed_date

        total_amount = order.get("total_amount")
        if isinstance(total_amount, str):
            parsed_amount = _parse_order_money(total_amount)
            if parsed_amount is None:
                order_unparseable_money += 1
            else:
                set_fields["total_amount"] = parsed_amount

        for index, item in enumerate(_order_line_items(order)):
            unit_price = item.get("unit_price")
            if not isinstance(unit_price, str):
                continue
            parsed_unit_price = _parse_order_money(unit_price)
            if parsed_unit_price is None:
                order_unparseable_money += 1
                continue
            set_fields[f"items.{index}.unit_price"] = parsed_unit_price

        if order_unparseable_dates or order_unparseable_money:
            skipped_unparseable_orders += 1
            unparseable_date_values += order_unparseable_dates
            unparseable_money_values += order_unparseable_money
            continue
        if not set_fields:
            continue

        date_fields_converted += sum(
            1 for field in ("date_created", "date_closed") if field in set_fields
        )
        money_fields_converted += sum(
            1 for field in set_fields if field == "total_amount" or field.endswith(".unit_price")
        )
        write_plans.append(({"_id": order["_id"], "seller_id": seller_id}, set_fields))

    orders_updated = 0
    if not dry_run:
        for filter_spec, set_fields in write_plans:
            await orders_collection.update_one(
                filter_spec,
                {"$set": set_fields},
                upsert=False,
                bypass_document_validation=False,
            )
            orders_updated += 1

    return OrderNormalizationSummary(
        seller_id=seller_id,
        dry_run=dry_run,
        date_from=date_from,
        date_to=date_to,
        orders_read=len(orders),
        orders_to_update=len(write_plans),
        orders_updated=orders_updated,
        date_fields_converted=date_fields_converted,
        money_fields_converted=money_fields_converted,
        skipped_unparseable_orders=skipped_unparseable_orders,
        unparseable_date_values=unparseable_date_values,
        unparseable_money_values=unparseable_money_values,
    )


@dataclass(frozen=True)
class SkuCandidate:
    sku: str | None
    source: str | None
    ambiguous: bool = False


@dataclass(frozen=True)
class _OrderLineIdentityCandidate:
    sku: str
    item_id: str
    variation_id: str | None
    updated_at: Any


def extract_seller_sku(item: dict[str, Any]) -> str | None:
    return resolve_seller_sku(item).sku


def resolve_seller_sku(item: dict[str, Any]) -> SkuCandidate:
    attributes = item.get("attributes")
    if not isinstance(attributes, Sequence) or isinstance(attributes, (str, bytes)):
        return SkuCandidate(sku=None, source=None)

    candidates: list[str] = []
    for attribute in attributes:
        if not isinstance(attribute, dict):
            continue
        attribute_id = str(attribute.get("id") or "").strip().upper()
        if attribute_id != SELLER_SKU_ATTRIBUTE_ID:
            continue
        for key in ("value_name", "value", "name"):
            sku = _string_value(attribute.get(key))
            if sku is not None:
                candidates.append(sku)
                break
    return _single_sku_candidate(candidates, source="item_attribute")


def build_sku_index_docs(item: dict[str, Any], *, seller_id: str) -> list[dict[str, Any]]:
    item_sku = resolve_seller_sku(item)
    item_docs = (
        [build_sku_index_doc(item, seller_id=seller_id, sku=item_sku.sku)]
        if item_sku.sku and not item_sku.ambiguous
        else []
    )
    variation_docs, _, _ = build_variation_sku_index_docs(item, seller_id=seller_id)
    return item_docs + variation_docs


def build_variation_sku_index_docs(
    item: dict[str, Any], *, seller_id: str
) -> tuple[list[dict[str, Any]], int, int]:
    variations = item.get("variations")
    if not isinstance(variations, Sequence) or isinstance(variations, (str, bytes)):
        return [], 0, 0

    docs: list[dict[str, Any]] = []
    missing = 0
    ambiguous = 0
    for variation in variations:
        if not isinstance(variation, dict):
            continue
        variation_id = _optional_string(variation.get("id") or variation.get("variation_id"))
        if variation_id is None:
            missing += 1
            continue
        candidate = resolve_variation_sku(variation)
        if candidate.ambiguous:
            ambiguous += 1
            continue
        if candidate.sku is None or candidate.source is None:
            missing += 1
            continue
        docs.append(
            build_sku_index_doc(
                item,
                seller_id=seller_id,
                sku=candidate.sku,
                variation_id=variation_id,
                identity_level="variation",
                source=candidate.source,
                inventory_id=_optional_string(variation.get("inventory_id")),
            )
        )
    return docs, missing, ambiguous


def build_variation_formula_row_docs(
    item: dict[str, Any], variation_docs: Sequence[dict[str, Any]], *, seller_id: str
) -> tuple[list[dict[str, Any]], int, int]:
    docs: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    missing_source = 0
    ambiguous = 0
    for variation_doc in variation_docs:
        variation_id = _optional_string(variation_doc.get("variation_id"))
        sku = _optional_string(variation_doc.get("sku"))
        inventory_id = _optional_string(variation_doc.get("inventory_id"))
        if variation_id is None or sku is None:
            ambiguous += 1
            continue
        if inventory_id is None:
            missing_source += 1
            continue
        formula_row = build_formula_row_doc(
            item,
            seller_id=seller_id,
            sku=sku,
            variation_id=variation_id,
            inventory_id=inventory_id,
        )
        row_id = str(formula_row["_id"])
        if row_id in seen_ids:
            ambiguous += 1
            continue
        seen_ids.add(row_id)
        docs.append(formula_row)
    return docs, missing_source, ambiguous


async def load_order_line_sku_identities_by_item(
    sku_index_collection: Any, *, seller_id: str
) -> dict[str, list[dict[str, Any]]]:
    identities = await sku_index_collection.find(
        {
            "seller_id": seller_id,
            "source": "order_line",
        }
    ).to_list(length=None)
    by_item: dict[str, list[dict[str, Any]]] = {}
    for identity in identities:
        item_id = _optional_string(identity.get("item_id"))
        if item_id is None:
            continue
        by_item.setdefault(item_id, []).append(identity)
    return by_item


def build_order_line_formula_row_docs(
    item: dict[str, Any], *, order_line_identities: Sequence[dict[str, Any]], seller_id: str
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for identity in order_line_identities:
        sku = _optional_string(identity.get("sku") or identity.get("normalized_sku"))
        if sku is None:
            continue
        rows.append(
            build_formula_row_doc(
                item,
                seller_id=seller_id,
                sku=sku,
                variation_id=_optional_string(identity.get("variation_id")),
                inventory_id=_order_line_identity_inventory_id(item, identity),
            )
        )
    return _dedupe_formula_row_docs(rows)


def build_order_line_sku_index_docs(
    order: dict[str, Any], *, seller_id: str
) -> list[dict[str, Any]]:
    if _is_cancelled_order(order):
        return []

    updated_at = order.get("date_created") or order.get("updated_at")
    identities: dict[tuple[str, str | None], dict[str, _OrderLineIdentityCandidate]] = {}
    for item in _order_line_items(order):
        sku = resolve_order_line_sku(item)
        if sku is None:
            continue
        item_id = _order_line_item_id(item)
        if item_id is None:
            continue
        variation_id = _order_line_variation_id(item)
        by_sku = identities.setdefault((item_id, variation_id), {})
        normalized_sku = normalize_sku(sku)
        by_sku.setdefault(
            normalized_sku,
            _OrderLineIdentityCandidate(
                sku=sku,
                item_id=item_id,
                variation_id=variation_id,
                updated_at=updated_at,
            ),
        )

    deterministic_candidates = [
        next(iter(by_sku.values())) for by_sku in identities.values() if len(by_sku) == 1
    ]
    return [
        build_order_line_sku_index_doc(candidate, seller_id=seller_id)
        for candidate in deterministic_candidates
    ]


def _order_line_identity_inventory_id(item: dict[str, Any], identity: dict[str, Any]) -> str | None:
    inventory_id = _optional_string(identity.get("inventory_id"))
    if inventory_id is not None:
        return inventory_id
    variation_id = _optional_string(identity.get("variation_id"))
    if variation_id is None:
        return None
    return _variation_inventory_id(item, variation_id)


def _variation_inventory_id(item: dict[str, Any], variation_id: str) -> str | None:
    variations = item.get("variations")
    if not isinstance(variations, Sequence) or isinstance(variations, (str, bytes)):
        return None
    for variation in variations:
        if not isinstance(variation, dict):
            continue
        current_variation_id = _optional_string(
            variation.get("id") or variation.get("variation_id")
        )
        if current_variation_id == variation_id:
            return _optional_string(variation.get("inventory_id"))
    return None


def _dedupe_formula_row_docs(docs: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for doc in docs:
        deduped.setdefault(str(doc["_id"]), doc)
    return list(deduped.values())


def resolve_variation_sku(variation: dict[str, Any]) -> SkuCandidate:
    attribute_candidates = _seller_sku_values(variation.get("attributes"))
    if attribute_candidates:
        return _single_sku_candidate(attribute_candidates, source="variation_attribute")
    seller_custom_field = _string_value(variation.get("seller_custom_field"))
    if seller_custom_field is not None:
        return SkuCandidate(sku=seller_custom_field, source="variation_seller_custom_field")
    return SkuCandidate(sku=None, source=None)


def build_sku_index_doc(
    item: dict[str, Any],
    *,
    seller_id: str,
    sku: str | None = None,
    variation_id: str | None = None,
    identity_level: str = "item",
    source: str = "item_attribute",
    inventory_id: str | None = None,
) -> dict[str, Any]:
    resolved_sku = sku or extract_seller_sku(item)
    if resolved_sku is None:
        msg = "item does not contain a SELLER_SKU attribute"
        raise ValueError(msg)
    item_id = _item_id(item)
    normalized_sku = normalize_sku(resolved_sku)
    resolved_inventory_id = inventory_id
    if resolved_inventory_id is None and variation_id is None:
        resolved_inventory_id = _optional_string(item.get("inventory_id"))
    return {
        "_id": _read_model_id(
            seller_id=seller_id,
            normalized_sku=normalized_sku,
            item_id=item_id,
            variation_id=variation_id,
        ),
        "seller_id": seller_id,
        "seller_nickname": _optional_string(item.get("seller_nickname") or item.get("nickname")),
        "sku": resolved_sku,
        "normalized_sku": normalized_sku,
        "item_id": item_id,
        "variation_id": variation_id,
        "identity_level": identity_level,
        "source": source,
        "inventory_id": resolved_inventory_id,
        "updated_at": _updated_at(item),
        "schema_version": READ_MODEL_SCHEMA_VERSION,
    }


def build_order_line_sku_index_doc(
    candidate: _OrderLineIdentityCandidate, *, seller_id: str
) -> dict[str, Any]:
    normalized_sku = normalize_sku(candidate.sku)
    return {
        "_id": _read_model_id(
            seller_id=seller_id,
            normalized_sku=normalized_sku,
            item_id=candidate.item_id,
            variation_id=candidate.variation_id,
        ),
        "seller_id": seller_id,
        "seller_nickname": None,
        "sku": candidate.sku,
        "normalized_sku": normalized_sku,
        "item_id": candidate.item_id,
        "variation_id": candidate.variation_id,
        "identity_level": "variation" if candidate.variation_id is not None else "item",
        "source": "order_line",
        "inventory_id": None,
        "updated_at": _coerce_datetime_value(candidate.updated_at),
        "schema_version": READ_MODEL_SCHEMA_VERSION,
    }


def build_formula_row_doc(
    item: dict[str, Any],
    *,
    seller_id: str,
    sku: str | None = None,
    variation_id: str | None = None,
    inventory_id: str | None = None,
) -> dict[str, Any]:
    resolved_sku = sku or extract_seller_sku(item)
    if resolved_sku is None:
        msg = "item does not contain a SELLER_SKU attribute"
        raise ValueError(msg)
    item_id = _item_id(item)
    normalized_sku = normalize_sku(resolved_sku)
    date_created = item.get("date_created")
    updated_at = _updated_at(item)
    resolved_variation_id = _optional_string(variation_id)
    resolved_inventory_id = _optional_string(inventory_id)
    if resolved_inventory_id is None and resolved_variation_id is None:
        resolved_inventory_id = _optional_string(item.get("inventory_id"))
    return {
        "_id": _formula_row_id(
            seller_id=seller_id,
            normalized_sku=normalized_sku,
            item_id=item_id,
            variation_id=resolved_variation_id,
        ),
        "seller_id": seller_id,
        "seller_nickname": _optional_string(item.get("seller_nickname") or item.get("nickname")),
        "sku": resolved_sku,
        "normalized_sku": normalized_sku,
        "item_id": item_id,
        "variation_id": resolved_variation_id,
        "inventory_id": resolved_inventory_id,
        "current": {
            "title": item.get("title"),
            "status": item.get("status"),
            "available_quantity": item.get("available_quantity"),
            **({"price": _schema_safe_numeric(item.get("price"))} if "price" in item else {}),
            "base_price": _schema_safe_numeric(item.get("base_price")),
            "category_id": item.get("category_id"),
            "date_created": date_created,
            "updated_at": updated_at,
            "permalink": _optional_string(item.get("permalink")),
            "thumbnail": _optional_string(item.get("thumbnail")),
            "catalog_product_id": _optional_string(item.get("catalog_product_id")),
            "listing_type_id": _optional_string(item.get("listing_type_id")),
            **(
                {"seller_shipping_cost": _schema_safe_numeric(item.get("seller_shipping_cost"))}
                if "seller_shipping_cost" in item
                else {}
            ),
            "inventory_id": resolved_inventory_id,
            "shipping_logistic_type": _shipping_logistic_type(item.get("shipping")),
            "shipping_payer": _shipping_payer(item.get("shipping")),
        },
        "date_created": date_created,
        "updated_at": updated_at,
        "schema_version": READ_MODEL_SCHEMA_VERSION,
    }


async def _load_seller_items(*, db: Any, seller_id: str) -> list[dict[str, Any]]:
    cursor = db[ITEMS_COLLECTION].find({"seller_id": seller_id}).sort([("_id", 1)])
    return cast("list[dict[str, Any]]", await cursor.to_list(length=None))


def _chunks(items: Sequence[str], size: int) -> Sequence[list[str]]:
    return [list(items[index : index + size]) for index in range(0, len(items), size)]


def _item_detail_batch_path(item_ids: Sequence[str]) -> str:
    return f"/items?ids={','.join(item_ids)}"


def _extract_item_detail_entries(response: Any) -> list[dict[str, Any]]:
    if isinstance(response, list):
        raw_entries = response
    elif isinstance(response, dict) and isinstance(response.get("results"), list):
        raw_entries = response["results"]
    elif isinstance(response, dict):
        raw_entries = [response]
    else:
        msg = "item detail response must be a list or object"
        raise RuntimeError(msg)
    return [entry for entry in raw_entries if isinstance(entry, dict)]


def _validated_detail_entries_by_id(
    entries: Sequence[dict[str, Any]], *, expected_ids: set[str], seller_id: str
) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for entry in entries:
        status_code = entry.get("code")
        if status_code is not None and int(status_code) != 200:
            msg = f"item detail fetch failed with status {int(status_code)}"
            raise RuntimeError(msg)
        body = entry.get("body", entry)
        if not isinstance(body, dict):
            msg = "item detail body must be an object"
            raise RuntimeError(msg)
        item_id = _optional_string(body.get("id") or body.get("_id"))
        if item_id is None or item_id not in expected_ids:
            msg = "item detail response contained an unexpected item"
            raise RuntimeError(msg)
        body_seller_id = _optional_string(body.get("seller_id"))
        if body_seller_id is not None and body_seller_id != seller_id:
            msg = "item detail response seller did not match requested seller"
            raise RuntimeError(msg)
        by_id[item_id] = body
    return by_id


def _canonical_item_detail_document(
    *, existing: dict[str, Any], detail: dict[str, Any], seller_id: str, synced_at: datetime
) -> dict[str, Any]:
    item_id = _item_id(existing)
    model = Item.model_validate(
        {
            **existing,
            **detail,
            "_id": item_id,
            "seller_id": seller_id,
            "last_meli_sync_at": synced_at,
            "schema_version": current_schema_version("items"),
        }
    )
    document = model.model_dump(by_alias=True, mode="python")
    for money_field in ("price", "base_price", "seller_shipping_cost"):
        document[money_field] = _schema_safe_numeric(document.get(money_field))
    return document


async def _resolve_seller_shipping_cost(
    *,
    gateway: MeliItemGatewayClient,
    seller_id: str,
    item_id: str,
    detail: dict[str, Any],
) -> Decimal | int | None:
    if _is_non_free_shipping(detail):
        return 0
    if not _is_seller_paid_free_shipping(detail):
        return None
    try:
        response = await gateway.fetch_resource(
            seller_id=seller_id,
            path=_seller_shipping_options_path(seller_id=seller_id, item_id=item_id),
        )
    except (RuntimeError, GatewayRateLimitError, httpx.HTTPStatusError, httpx.RequestError):
        return None
    return _extract_seller_shipping_cost(response)


def _seller_shipping_options_path(*, seller_id: str, item_id: str) -> str:
    escaped_seller_id = quote(str(seller_id), safe="")
    escaped_item_id = quote(item_id, safe="")
    return f"/users/{escaped_seller_id}/shipping_options/free?item_id={escaped_item_id}"


def _is_seller_paid_free_shipping(item: dict[str, Any]) -> bool:
    shipping = item.get("shipping")
    return isinstance(shipping, dict) and shipping.get("free_shipping") is True


def _is_non_free_shipping(item: dict[str, Any]) -> bool:
    shipping = item.get("shipping")
    return isinstance(shipping, dict) and shipping.get("free_shipping") is False


def _extract_seller_shipping_cost(response: Any) -> Decimal | None:
    if not isinstance(response, dict):
        return None
    coverage = response.get("coverage")
    if not isinstance(coverage, dict):
        return None
    all_country = coverage.get("all_country")
    if not isinstance(all_country, dict):
        return None
    return _bounded_shipping_cost(all_country.get("list_cost"))


def _bounded_shipping_cost(value: Any) -> Decimal | None:
    if value is None or isinstance(value, (bool, dict, list)):
        return None
    try:
        cost = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not cost.is_finite() or cost < 0:
        return None
    return cost


def _canonical_item_values_equal(existing: dict[str, Any], planned: dict[str, Any]) -> bool:
    return all(
        _formula_row_values_equal(existing.get(key), value)
        for key, value in planned.items()
        if key != "last_meli_sync_at"
    )


async def _load_seller_orders(
    *, db: Any, seller_id: str, date_from: str | None = None, date_to: str | None = None
) -> list[dict[str, Any]]:
    filter_spec = _seller_order_filter(seller_id=seller_id, date_from=date_from, date_to=date_to)
    cursor = db[ORDERS_COLLECTION].find(filter_spec).sort([("_id", 1)])
    return cast("list[dict[str, Any]]", await cursor.to_list(length=None))


def _seller_order_filter(
    *, seller_id: str, date_from: str | None, date_to: str | None
) -> dict[str, Any]:
    filter_spec: dict[str, Any] = {"seller_id": seller_id}
    if date_from is not None and date_to is not None:
        filter_spec["$or"] = [
            {
                "date_created": {
                    "$gte": _parse_utc_datetime(date_from),
                    "$lt": _parse_utc_datetime(date_to, end_exclusive=True),
                }
            },
            {
                "date_created": {
                    "$gte": _date_bound_string(date_from),
                    "$lt": _date_bound_string(date_to, end_exclusive=True),
                }
            },
        ]
    return filter_spec


def _is_cancelled_order(order: dict[str, Any]) -> bool:
    return str(order.get("status") or "").strip().casefold() == "cancelled"


def _parse_utc_datetime(value: str, *, end_exclusive: bool = False) -> datetime:
    normalized = value.strip()
    if len(normalized) == 10:
        parsed_date = date.fromisoformat(normalized)
        parsed = datetime.combine(parsed_date, datetime.min.time(), tzinfo=UTC)
        return parsed + timedelta(days=1) if end_exclusive else parsed
    parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parse_order_datetime(value: str) -> datetime | None:
    try:
        return _parse_utc_datetime(value)
    except ValueError:
        return None


def _parse_order_money(value: str) -> Decimal128 | None:
    try:
        parsed = Decimal(value.strip())
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite():
        return None
    return Decimal128(parsed)


def _schema_safe_numeric(value: Any) -> int | float | Decimal128 | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal128):
        return value if value.to_decimal().is_finite() else None
    if isinstance(value, Decimal):
        return Decimal128(value) if value.is_finite() else None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return _parse_order_money(value)
    return None


def _shipping_logistic_type(shipping: Any) -> str | None:
    if not isinstance(shipping, dict):
        return None
    return _optional_string(shipping.get("logistic_type") or shipping.get("mode"))


def _shipping_payer(shipping: Any) -> str | None:
    if not isinstance(shipping, dict) or "free_shipping" not in shipping:
        return None
    free_shipping = shipping.get("free_shipping")
    if isinstance(free_shipping, bool):
        return "Vendedor" if free_shipping else "Comprador"
    return None


def _date_bound_string(value: str, *, end_exclusive: bool = False) -> str:
    parsed = _parse_utc_datetime(value, end_exclusive=end_exclusive)
    if len(value.strip()) == 10:
        return parsed.date().isoformat()
    return parsed.isoformat()


def _order_line_items(order: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items = order.get("items") or order.get("order_items") or []
    if not isinstance(raw_items, Sequence) or isinstance(raw_items, (str, bytes)):
        return []
    return [item for item in raw_items if isinstance(item, dict)]


def extract_safe_order_item_identity(item: dict[str, Any]) -> dict[str, str]:
    nested_item = _nested_order_item(item)
    identity: dict[str, str] = {}
    for field, value in (
        ("item_id", _order_line_item_id(item)),
        ("variation_id", _order_line_variation_id(item)),
        ("sku", _first_string_value(item.get("sku"), nested_item.get("sku"))),
        (
            "seller_sku",
            _first_string_value(
                item.get("seller_sku"),
                nested_item.get("seller_sku"),
                _first_seller_sku_from_order_attributes(item, nested_item),
            ),
        ),
        (
            "seller_custom_field",
            _first_string_value(
                item.get("seller_custom_field"), nested_item.get("seller_custom_field")
            ),
        ),
    ):
        normalized = _string_value(value)
        if normalized is not None:
            identity[field] = normalized
    return identity


def merge_order_items_identity(
    existing_items: Sequence[dict[str, Any]], enriched_items: Sequence[dict[str, Any]]
) -> tuple[list[dict[str, Any]], OrderIdentityMergeStats]:
    existing_counts = _item_id_counts(existing_items)
    enriched_counts = _item_id_counts(enriched_items)
    enriched_by_item = {
        str(item["item_id"]): item
        for item in enriched_items
        if item.get("item_id") is not None and enriched_counts.get(str(item["item_id"])) == 1
    }

    matched_order_lines = 0
    updated_order_lines = 0
    identity_fields_added = 0
    skipped_unmatched_lines = 0
    merged_items: list[dict[str, Any]] = []

    for existing_item in existing_items:
        merged_item = dict(existing_item)
        item_id = _order_line_item_id(existing_item)
        enriched_item = (
            enriched_by_item.get(item_id)
            if item_id is not None
            and existing_counts.get(item_id) == 1
            and enriched_counts.get(item_id) == 1
            else None
        )
        if enriched_item is None:
            skipped_unmatched_lines += 1
            merged_items.append(merged_item)
            continue

        matched_order_lines += 1
        added_for_line = 0
        for field in ("variation_id", "sku", "seller_sku", "seller_custom_field"):
            if _string_value(merged_item.get(field)) is not None:
                continue
            value = _string_value(enriched_item.get(field))
            if value is None:
                continue
            merged_item[field] = value
            added_for_line += 1
        if added_for_line:
            updated_order_lines += 1
            identity_fields_added += added_for_line
        merged_items.append(merged_item)

    return merged_items, OrderIdentityMergeStats(
        matched_order_lines=matched_order_lines,
        updated_order_lines=updated_order_lines,
        identity_fields_added=identity_fields_added,
        skipped_unmatched_lines=skipped_unmatched_lines,
    )


def _has_safe_identity_fields(identity: dict[str, str]) -> bool:
    return any(
        identity.get(field)
        for field in ("variation_id", "sku", "seller_sku", "seller_custom_field")
    )


def _item_id_counts(items: Sequence[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        item_id = _order_line_item_id(item)
        if item_id is not None:
            counts[item_id] = counts.get(item_id, 0) + 1
    return counts


def resolve_order_line_sku(item: dict[str, Any]) -> str | None:
    nested_item = _nested_order_item(item)
    value = (
        item.get("sku")
        or item.get("seller_sku")
        or item.get("seller_custom_field")
        or nested_item.get("sku")
        or nested_item.get("seller_sku")
        or nested_item.get("seller_custom_field")
        or _first_seller_sku_from_order_attributes(item, nested_item)
    )
    return _string_value(value)


def _order_line_item_id(item: dict[str, Any]) -> str | None:
    nested_item = _nested_order_item(item)
    return _optional_string(
        item.get("item_id") or nested_item.get("id") or nested_item.get("item_id")
    )


def _order_line_variation_id(item: dict[str, Any]) -> str | None:
    nested_item = _nested_order_item(item)
    return _optional_string(item.get("variation_id") or nested_item.get("variation_id"))


def _nested_order_item(item: dict[str, Any]) -> dict[str, Any]:
    nested_item = item.get("item")
    return nested_item if isinstance(nested_item, dict) else {}


def _first_seller_sku_from_order_attributes(
    item: dict[str, Any], nested_item: dict[str, Any]
) -> str | None:
    for attributes in (
        item.get("variation_attributes"),
        nested_item.get("variation_attributes"),
        item.get("attributes"),
        nested_item.get("attributes"),
    ):
        values = _seller_sku_values(attributes)
        if values:
            return values[0]
    return None


def _first_string_value(*values: Any) -> str | None:
    for value in values:
        normalized = _string_value(value)
        if normalized is not None:
            return normalized
    return None


def _string_value(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("value_name", "name", "id"):
            nested = _string_value(value.get(key))
            if nested is not None:
                return nested
        return None
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for entry in value:
            nested = _string_value(entry)
            if nested is not None:
                return nested
        return None
    normalized = str(value or "").strip()
    return normalized or None


def _seller_sku_values(attributes: Any) -> list[str]:
    if not isinstance(attributes, Sequence) or isinstance(attributes, (str, bytes)):
        return []
    candidates: list[str] = []
    for attribute in attributes:
        if not isinstance(attribute, dict):
            continue
        attribute_id = str(attribute.get("id") or "").strip().upper()
        if attribute_id != SELLER_SKU_ATTRIBUTE_ID:
            continue
        for key in ("value_name", "value", "name"):
            sku = _string_value(attribute.get(key))
            if sku is not None:
                candidates.append(sku)
                break
    return candidates


def _single_sku_candidate(candidates: Sequence[str], *, source: str) -> SkuCandidate:
    normalized = {normalize_sku(candidate) for candidate in candidates if normalize_sku(candidate)}
    if not normalized:
        return SkuCandidate(sku=None, source=None)
    if len(normalized) > 1:
        return SkuCandidate(sku=None, source=source, ambiguous=True)
    selected_normalized = next(iter(normalized))
    for candidate in candidates:
        if normalize_sku(candidate) == selected_normalized:
            return SkuCandidate(sku=candidate.strip(), source=source)
    return SkuCandidate(sku=None, source=None)


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _item_id(item: dict[str, Any]) -> str:
    item_id = str(item.get("_id") or item.get("id") or "").strip()
    if not item_id:
        msg = "item is missing _id/id"
        raise ValueError(msg)
    return item_id


def _updated_at(item: dict[str, Any]) -> Any:
    return _coerce_datetime_value(item.get("updated_at") or item.get("last_updated"))


def _coerce_datetime_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return _parse_utc_datetime(value)
        except ValueError:
            return value
    return value


def _read_model_id(
    *, seller_id: str, normalized_sku: str, item_id: str, variation_id: str | None
) -> str:
    identity = variation_id if variation_id is not None else "item"
    return f"{seller_id}:{normalized_sku}:{item_id}:{identity}"


def _formula_row_id(
    *, seller_id: str, normalized_sku: str, item_id: str, variation_id: str | None = None
) -> str:
    base_id = f"{seller_id}:{normalized_sku}:{item_id}"
    return f"{base_id}:{variation_id}" if variation_id is not None else base_id


def _formula_row_diagnostics(formula_row_doc: dict[str, Any]) -> dict[str, int | bool]:
    current = formula_row_doc.get("current")
    current_values = current if isinstance(current, dict) else {}
    fields = {
        "permalink": _optional_string(current_values.get("permalink")),
        "thumbnail": _optional_string(current_values.get("thumbnail")),
        "catalog_product_id": _optional_string(current_values.get("catalog_product_id")),
        "inventory_id": _optional_string(
            current_values.get("inventory_id") or formula_row_doc.get("inventory_id")
        ),
    }
    return {
        "missing_source": any(value is None for value in fields.values()),
        "with_permalink": 1 if fields["permalink"] is not None else 0,
        "with_thumbnail": 1 if fields["thumbnail"] is not None else 0,
        "with_catalog_product_id": 1 if fields["catalog_product_id"] is not None else 0,
        "with_inventory_id": 1 if fields["inventory_id"] is not None else 0,
    }


async def _is_existing_document_unchanged(collection: Any, document: dict[str, Any]) -> bool:
    find_one = getattr(collection, "find_one", None)
    if find_one is None:
        return False
    existing = await find_one({"_id": document["_id"]})
    return bool(existing is not None and _formula_row_values_equal(existing, document))


def _formula_row_values_equal(left: Any, right: Any) -> bool:
    if isinstance(left, dict) and isinstance(right, dict):
        if left.keys() != right.keys():
            return False
        return all(_formula_row_values_equal(left[key], right[key]) for key in left)
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return False
        return all(
            _formula_row_values_equal(left_value, right_value)
            for left_value, right_value in zip(left, right, strict=True)
        )
    left_decimal = _formula_row_decimal_value(left)
    right_decimal = _formula_row_decimal_value(right)
    if left_decimal is not None and right_decimal is not None:
        return left_decimal == right_decimal
    left_datetime = _formula_row_datetime_value(left, right)
    right_datetime = _formula_row_datetime_value(right, left)
    if left_datetime is not None and right_datetime is not None:
        return left_datetime == right_datetime
    return bool(left == right)


def _formula_row_decimal_value(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, Decimal128):
        decimal_value = value.to_decimal()
        return decimal_value if decimal_value.is_finite() else None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value)) if math.isfinite(value) else None
    return None


def _formula_row_datetime_value(value: Any, other: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    if not isinstance(value, str) or not isinstance(other, (datetime, date)):
        return None
    try:
        return _parse_utc_datetime(value)
    except ValueError:
        return None


async def _run_cli(args: argparse.Namespace) -> BackfillCliSummary:
    from motor.motor_asyncio import AsyncIOMotorClient

    from zeler_platform_core.auth.meli_gateway_auth import MeliGatewayAuth
    from zeler_platform_core.clients.meli_gateway_client import MeliGatewayClient

    mongo_uri = os.environ.get("MONGO_URI")
    mongo_db_name = os.environ.get("MONGO_DB")
    if not mongo_uri:
        raise SystemExit("MONGO_URI is required")
    if not mongo_db_name:
        raise SystemExit("MONGO_DB is required")

    client: AsyncIOMotorClient[Any] = AsyncIOMotorClient(mongo_uri)
    try:
        if args.source == "orders-normalize":
            date_from, date_to = _require_order_dates(args)
            return await run_order_normalization(
                db=client[mongo_db_name],
                seller_id=args.seller_id,
                date_from=date_from,
                date_to=date_to,
                dry_run=args.dry_run,
            )
        if args.source == "orders-repair":
            date_from, date_to = _require_order_dates(args)
            from google.cloud import kms

            gateway = MeliGatewayClient(
                os.environ.get("GATEWAY_BASE_URL", DEFAULT_GATEWAY_BASE_URL),
                MeliGatewayAuth("sheets", kms.KeyManagementServiceClient()),
            )
            return await run_order_identity_repair(
                db=client[mongo_db_name],
                gateway=gateway,
                seller_id=args.seller_id,
                date_from=date_from,
                date_to=date_to,
                dry_run=args.dry_run,
            )
        if args.source == "items-enrich":
            from google.cloud import kms

            gateway = MeliGatewayClient(
                os.environ.get("GATEWAY_BASE_URL", DEFAULT_GATEWAY_BASE_URL),
                MeliGatewayAuth("sheets", kms.KeyManagementServiceClient()),
            )
            return await run_item_detail_enrichment(
                db=client[mongo_db_name],
                gateway=gateway,
                seller_id=args.seller_id,
                dry_run=args.dry_run,
            )
        if args.source == "order-lines":
            return await run_order_line_identity_backfill(
                db=client[mongo_db_name],
                seller_id=args.seller_id,
                dry_run=args.dry_run,
                date_from=args.date_from,
                date_to=args.date_to,
            )
        return await run_sheetseller_backfill(
            db=client[mongo_db_name], seller_id=args.seller_id, dry_run=args.dry_run
        )
    finally:
        client.close()


def _require_order_dates(args: argparse.Namespace) -> tuple[str, str]:
    if not args.date_from or not args.date_to:
        raise SystemExit("--date-from and --date-to are required for order-scoped sources")
    return str(args.date_from), str(args.date_to)


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    summary = asyncio.run(_run_cli(args))
    print(json.dumps(summary.as_dict(), sort_keys=True))


if __name__ == "__main__":
    main()
