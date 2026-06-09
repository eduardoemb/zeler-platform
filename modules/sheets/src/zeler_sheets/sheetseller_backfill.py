from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from dataclasses import field as dataclass_field
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, DecimalException, InvalidOperation
from typing import Any, Protocol, cast
from urllib.parse import quote

import httpx
from bson.decimal128 import Decimal128
from pymongo.errors import DuplicateKeyError

from zeler_platform_core.clients.meli_gateway_client import GatewayRateLimitError
from zeler_platform_core.models import (
    Item,
    ListingFeeProjection,
    ListingPriceFixedFeeProjection,
    PromoPriceProjection,
    ShipmentRealShippingCostProjection,
)
from zeler_platform_core.models.base import current_schema_version
from zeler_sheets.enrichment import (
    EnrichmentFailure,
    basis_hash,
    bounded_basis,
    classify_fetch_exception,
    enrichment_state,
    increment_reason_count,
    listing_fee_basis_matches,
    schema_safe_enrichment_state,
    trusted_state,
)
from zeler_sheets.formulas.read_models import normalize_sku
from zeler_sheets.status_history import (
    bson_ms_utc_datetime,
    normalize_status_history_datetimes,
    require_bson_ms_utc_datetime,
)

ITEMS_COLLECTION = "items"
ORDERS_COLLECTION = "orders"
SHIPMENTS_COLLECTION = "shipments"
ITEM_SKU_INDEX_COLLECTION = "sheets_item_sku_index"
ITEM_FORMULA_ROWS_COLLECTION = "sheets_item_formula_rows"
ITEM_STATUS_STATES_COLLECTION = "item_status_states"
READ_MODEL_SCHEMA_VERSION = 2
SELLER_SKU_ATTRIBUTE_ID = "SELLER_SKU"
DEFAULT_GATEWAY_BASE_URL = "http://gateway:8080/proxy/meli"
ITEM_DETAIL_BATCH_SIZE = 20
STATUS_HISTORY_SCALAR_FIELDS = ("status_started_at", "paused_since", "last_status_change_at")
FORMULA_ROW_REPLACE_ATTEMPTS = 3
SHIPMENT_REAL_SHIPPING_COST_ENRICHMENT_LIMIT = 100
SALE_PRICE_SOURCE = "/items/{id}/sale_price"
LISTING_PRICE_FIXED_FEE_SOURCE = "/sites/{site}/listing_prices"
LISTING_FEE_PROJECTION_SOURCE = LISTING_PRICE_FIXED_FEE_SOURCE
SELLER_SHIPPING_COST_SOURCE = "/users/{seller_id}/shipping_options/free"
SALE_PRICE_CONTEXT = "channel_marketplace"


def _should_preserve_listing_price_lookup_failure(failure: EnrichmentFailure) -> bool:
    return failure.status in {"transient", "unauthorized"}


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
    sale_price_requested: int = 0
    sale_price_promotions_enriched: int = 0
    sale_price_promotions_unavailable: int = 0
    listing_prices_requested: int = 0
    listing_fee_projections_enriched: int = 0
    listing_fee_projections_unavailable: int = 0
    listing_fixed_fee_requested: int = 0
    listing_fixed_fee_enriched: int = 0
    listing_fixed_fee_unavailable: int = 0
    listing_fixed_fee_missing_params: int = 0
    diagnostic_reason_counts: dict[str, int] = dataclass_field(default_factory=dict)

    def as_dict(self) -> dict[str, int | bool | str]:
        return asdict(self)


@dataclass(frozen=True)
class ShipmentRealShippingCostEnrichmentSummary:
    dry_run: bool
    limit: int
    shipments_read: int
    shipments_with_id: int
    shipment_costs_requested: int
    shipment_real_shipping_costs_enriched: int
    shipment_real_shipping_costs_unavailable: int
    shipments_planned: int
    shipments_updated: int

    def as_dict(self) -> dict[str, int | bool]:
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
    | ShipmentRealShippingCostEnrichmentSummary
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
        choices=(
            "items",
            "items-enrich",
            "shipments-costs",
            "order-lines",
            "orders-repair",
            "orders-normalize",
        ),
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
    parser.add_argument(
        "--enable-sale-price",
        action="store_true",
        dest="sale_price_enabled",
        default=False,
        help="Enable gated /items/{id}/sale_price enrichment after approved runtime validation.",
    )
    parser.add_argument(
        "--enable-listing-fixed-fee",
        action="store_true",
        dest="listing_fixed_fee_enabled",
        default=False,
        help=(
            "Enable gated /sites/{site}/listing_prices fixed-fee enrichment after approved "
            "runtime validation."
        ),
    )
    parser.add_argument(
        "--limit",
        type=_positive_int_arg,
        default=SHIPMENT_REAL_SHIPPING_COST_ENRICHMENT_LIMIT,
        help=(
            "Maximum persisted shipments to inspect for shipments-costs enrichment "
            f"(default: {SHIPMENT_REAL_SHIPPING_COST_ENRICHMENT_LIMIT})."
        ),
    )
    return parser


async def run_sheetseller_backfill(
    *,
    db: Any,
    seller_id: str,
    dry_run: bool = True,
    item_ids: Sequence[str] | None = None,
) -> BackfillSummary:
    items = await _load_seller_items(db=db, seller_id=seller_id, item_ids=item_ids)
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
    status_states_by_item = await load_item_status_states_by_item(db=db, seller_id=seller_id)

    for item in items:
        item = _item_with_status_history(item, status_states_by_item.get(_item_id(item)))
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
            formula_row_doc = await _formula_row_with_latest_status_state(
                db=db,
                formula_row_doc=formula_row_doc,
            )
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
                if await _replace_formula_row_from_backfill_if_current(
                    formula_rows_collection,
                    formula_row_doc,
                    db=db,
                ):
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
    sale_price_enabled: bool = False,
    listing_fixed_fee_enabled: bool = False,
    item_ids: Sequence[str] | None = None,
) -> ItemDetailEnrichmentSummary:
    if batch_size < 1:
        msg = "batch_size must be positive"
        raise ValueError(msg)

    existing_items = await _load_seller_items(db=db, seller_id=seller_id, item_ids=item_ids)
    site_id = await _load_seller_site_id(db=db, seller_id=seller_id)
    existing_by_id = {_item_id(item): item for item in existing_items}
    item_ids = sorted(existing_by_id)
    synced_at = datetime.now(UTC)
    write_plans: list[tuple[dict[str, Any], dict[str, Any], bool, bool, bool]] = []
    batches_fetched = 0
    details_returned = 0
    items_validated = 0
    unchanged = 0
    shipping_options_requested = 0
    seller_shipping_costs_enriched = 0
    seller_shipping_costs_unavailable = 0
    sale_price_requested = 0
    sale_price_promotions_enriched = 0
    sale_price_promotions_unavailable = 0
    listing_prices_requested = 0
    listing_fee_projections_enriched = 0
    listing_fee_projections_unavailable = 0
    listing_fixed_fee_requested = 0
    listing_fixed_fee_enriched = 0
    listing_fixed_fee_unavailable = 0
    listing_fixed_fee_missing_params = 0
    diagnostic_reason_counts: dict[str, int] = {}

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
            existing_item = existing_by_id[item_id]
            item_enrichment_state = _existing_enrichment_state(existing_item)
            clear_current_promotion = False
            clear_listing_fixed_fee = False
            clear_listing_fee_projection = False
            is_free_shipping = _is_seller_paid_free_shipping(detail)
            if is_free_shipping:
                shipping_options_requested += 1
            seller_shipping_cost: Any = None
            seller_shipping_state: dict[str, Any] | None = None
            if _is_non_free_shipping(detail):
                seller_shipping_cost = 0
                seller_shipping_costs_enriched += 1
                seller_shipping_state = trusted_state(
                    source="/items/{id}",
                    synced_at=synced_at,
                    basis=_item_shipping_basis(detail),
                )
            elif is_free_shipping:
                try:
                    shipping_response = await gateway.fetch_resource(
                        seller_id=seller_id,
                        path=_seller_shipping_options_path(seller_id=seller_id, item_id=item_id),
                    )
                except (
                    RuntimeError,
                    GatewayRateLimitError,
                    httpx.HTTPStatusError,
                    httpx.RequestError,
                ) as exc:
                    failure = classify_fetch_exception(exc)
                    shipping_basis = _item_shipping_basis(detail)
                    if (
                        failure.preserve_existing
                        and existing_item.get("seller_shipping_cost") is not None
                    ):
                        if not _existing_enrichment_basis_matches(
                            existing_item,
                            field="seller_shipping_cost",
                            basis=shipping_basis,
                        ):
                            seller_shipping_costs_unavailable += 1
                            seller_shipping_state = enrichment_state(
                                source=SELLER_SHIPPING_COST_SOURCE,
                                status="basis_mismatch",
                                reason="basis_changed",
                                synced_at=synced_at,
                                basis=shipping_basis,
                            )
                            increment_reason_count(
                                diagnostic_reason_counts,
                                field="seller_shipping_cost",
                                status="basis_mismatch",
                                reason="basis_changed",
                            )
                        else:
                            seller_shipping_state = enrichment_state(
                                source=SELLER_SHIPPING_COST_SOURCE,
                                status=failure.status,
                                reason=failure.reason,
                                synced_at=synced_at,
                                basis=shipping_basis,
                            )
                            increment_reason_count(
                                diagnostic_reason_counts,
                                field="seller_shipping_cost",
                                status=failure.status,
                                reason=failure.reason,
                            )
                            seller_shipping_cost = existing_item["seller_shipping_cost"]
                    else:
                        seller_shipping_state = enrichment_state(
                            source=SELLER_SHIPPING_COST_SOURCE,
                            status=failure.status,
                            reason=failure.reason,
                            synced_at=synced_at,
                            basis=shipping_basis,
                        )
                        increment_reason_count(
                            diagnostic_reason_counts,
                            field="seller_shipping_cost",
                            status=failure.status,
                            reason=failure.reason,
                        )
                        seller_shipping_costs_unavailable += 1
                else:
                    seller_shipping_cost = _extract_seller_shipping_cost(shipping_response)
                    if seller_shipping_cost is None:
                        seller_shipping_costs_unavailable += 1
                        seller_shipping_state = enrichment_state(
                            source=SELLER_SHIPPING_COST_SOURCE,
                            status="malformed",
                            reason="malformed_response",
                            synced_at=synced_at,
                            basis=_item_shipping_basis(detail),
                        )
                        increment_reason_count(
                            diagnostic_reason_counts,
                            field="seller_shipping_cost",
                            status="malformed",
                            reason="malformed_response",
                        )
                    else:
                        seller_shipping_costs_enriched += 1
                        seller_shipping_state = trusted_state(
                            source=SELLER_SHIPPING_COST_SOURCE,
                            synced_at=synced_at,
                            basis=_item_shipping_basis(detail),
                        )
            else:
                seller_shipping_cost = None
            detail["seller_shipping_cost"] = seller_shipping_cost
            if seller_shipping_state is not None:
                item_enrichment_state["seller_shipping_cost"] = seller_shipping_state
            if sale_price_enabled:
                sale_price_requested += 1
                current_promotion, sale_price_failure = await _resolve_sale_price_projection(
                    gateway=gateway,
                    seller_id=seller_id,
                    item_id=item_id,
                    synced_at=synced_at,
                )
                if current_promotion is None:
                    existing_promotion = existing_item.get("current_promotion")
                    if sale_price_failure is not None:
                        item_enrichment_state["current_promotion"] = enrichment_state(
                            source=SALE_PRICE_SOURCE,
                            status=sale_price_failure.status,
                            reason=sale_price_failure.reason,
                            synced_at=synced_at,
                        )
                        increment_reason_count(
                            diagnostic_reason_counts,
                            field="current_promotion",
                            status=sale_price_failure.status,
                            reason=sale_price_failure.reason,
                        )
                        if sale_price_failure.preserve_existing and existing_promotion is not None:
                            detail["current_promotion"] = existing_promotion
                        else:
                            sale_price_promotions_unavailable += 1
                            detail["current_promotion"] = None
                            clear_current_promotion = "current_promotion" in existing_item
                    else:
                        sale_price_promotions_unavailable += 1
                        detail["current_promotion"] = None
                        clear_current_promotion = "current_promotion" in existing_item
                        item_enrichment_state["current_promotion"] = enrichment_state(
                            source=SALE_PRICE_SOURCE,
                            status="authoritative_absent",
                            reason="no_trusted_promotion",
                            synced_at=synced_at,
                        )
                        increment_reason_count(
                            diagnostic_reason_counts,
                            field="current_promotion",
                            status="authoritative_absent",
                            reason="no_trusted_promotion",
                        )
                else:
                    sale_price_promotions_enriched += 1
                    detail["current_promotion"] = current_promotion
                    item_enrichment_state["current_promotion"] = trusted_state(
                        source=SALE_PRICE_SOURCE,
                        synced_at=synced_at,
                    )
            elif "current_promotion" in existing_by_id[item_id]:
                detail["current_promotion"] = existing_by_id[item_id]["current_promotion"]
            if site_id is not None:
                listing_fee_context = build_listing_fee_projection_context(
                    site_id=site_id, detail=detail
                )
                if listing_fee_context is None:
                    listing_fee_projections_unavailable += 1
                    detail["listing_fee_projection"] = None
                    clear_listing_fee_projection = (
                        "listing_fee_projection" in existing_by_id[item_id]
                    )
                    item_enrichment_state["listing_fee_projection"] = enrichment_state(
                        source=LISTING_FEE_PROJECTION_SOURCE,
                        status="basis_mismatch",
                        reason="missing_basis",
                        synced_at=synced_at,
                    )
                    increment_reason_count(
                        diagnostic_reason_counts,
                        field="listing_fee_projection",
                        status="basis_mismatch",
                        reason="missing_basis",
                    )
                else:
                    listing_prices_requested += 1
                    try:
                        listing_fee_response = await gateway.fetch_resource(
                            seller_id=seller_id,
                            path=listing_fee_projection_path(listing_fee_context),
                        )
                    except (
                        RuntimeError,
                        GatewayRateLimitError,
                        httpx.HTTPStatusError,
                        httpx.RequestError,
                    ) as exc:
                        existing_projection = existing_item.get("listing_fee_projection")
                        failure = classify_fetch_exception(exc)
                        if not listing_fee_basis_matches(existing_projection, listing_fee_context):
                            listing_fee_projections_unavailable += 1
                            detail["listing_fee_projection"] = None
                            clear_listing_fee_projection = "listing_fee_projection" in existing_item
                            item_enrichment_state["listing_fee_projection"] = enrichment_state(
                                source=LISTING_FEE_PROJECTION_SOURCE,
                                status="basis_mismatch",
                                reason="basis_changed",
                                synced_at=synced_at,
                                basis=listing_fee_context,
                            )
                            increment_reason_count(
                                diagnostic_reason_counts,
                                field="listing_fee_projection",
                                status="basis_mismatch",
                                reason="basis_changed",
                            )
                        elif (
                            _should_preserve_listing_price_lookup_failure(failure)
                            and existing_projection is not None
                        ):
                            detail["listing_fee_projection"] = existing_projection
                            item_enrichment_state["listing_fee_projection"] = enrichment_state(
                                source=LISTING_FEE_PROJECTION_SOURCE,
                                status=failure.status,
                                reason=failure.reason,
                                synced_at=synced_at,
                                basis=listing_fee_context,
                            )
                            increment_reason_count(
                                diagnostic_reason_counts,
                                field="listing_fee_projection",
                                status=failure.status,
                                reason=failure.reason,
                            )
                        else:
                            listing_fee_projections_unavailable += 1
                            detail["listing_fee_projection"] = None
                            clear_listing_fee_projection = "listing_fee_projection" in existing_item
                            item_enrichment_state["listing_fee_projection"] = enrichment_state(
                                source=LISTING_FEE_PROJECTION_SOURCE,
                                status=failure.status,
                                reason=failure.reason,
                                synced_at=synced_at,
                                basis=listing_fee_context,
                            )
                            increment_reason_count(
                                diagnostic_reason_counts,
                                field="listing_fee_projection",
                                status=failure.status,
                                reason=failure.reason,
                            )
                    else:
                        listing_fee_projection = project_listing_fee_projection(
                            listing_fee_response,
                            context=listing_fee_context,
                            synced_at=synced_at,
                        )
                        if listing_fee_projection is None:
                            listing_fee_projections_unavailable += 1
                            detail["listing_fee_projection"] = None
                            clear_listing_fee_projection = (
                                "listing_fee_projection" in existing_by_id[item_id]
                            )
                            item_enrichment_state["listing_fee_projection"] = enrichment_state(
                                source=LISTING_FEE_PROJECTION_SOURCE,
                                status="malformed",
                                reason="malformed_response",
                                synced_at=synced_at,
                                basis=listing_fee_context,
                            )
                            increment_reason_count(
                                diagnostic_reason_counts,
                                field="listing_fee_projection",
                                status="malformed",
                                reason="malformed_response",
                            )
                        else:
                            listing_fee_projections_enriched += 1
                            detail["listing_fee_projection"] = listing_fee_projection
                            item_enrichment_state["listing_fee_projection"] = trusted_state(
                                source=LISTING_FEE_PROJECTION_SOURCE,
                                synced_at=synced_at,
                                basis=listing_fee_context,
                            )
            elif "listing_fee_projection" in existing_by_id[item_id]:
                detail["listing_fee_projection"] = None
                clear_listing_fee_projection = True
                item_enrichment_state["listing_fee_projection"] = enrichment_state(
                    source=LISTING_FEE_PROJECTION_SOURCE,
                    status="basis_mismatch",
                    reason="missing_site",
                    synced_at=synced_at,
                )
            if listing_fixed_fee_enabled:
                listing_params = _listing_price_fixed_fee_params(item_id=item_id, detail=detail)
                if listing_params is None:
                    listing_fixed_fee_missing_params += 1
                    detail["listing_price_fixed_fee"] = None
                    clear_listing_fixed_fee = "listing_price_fixed_fee" in existing_by_id[item_id]
                else:
                    listing_fixed_fee_requested += 1
                    (
                        fixed_fee_projection,
                        fixed_fee_failure,
                    ) = await _resolve_listing_price_fixed_fee_projection(
                        gateway=gateway,
                        seller_id=seller_id,
                        params=listing_params,
                        synced_at=synced_at,
                    )
                    existing_fixed_fee = existing_item.get("listing_price_fixed_fee")
                    if fixed_fee_projection is None:
                        if fixed_fee_failure is not None:
                            item_enrichment_state["listing_price_fixed_fee"] = enrichment_state(
                                source=LISTING_PRICE_FIXED_FEE_SOURCE,
                                status=fixed_fee_failure.status,
                                reason=fixed_fee_failure.reason,
                                synced_at=synced_at,
                                basis=listing_params,
                            )
                            increment_reason_count(
                                diagnostic_reason_counts,
                                field="listing_price_fixed_fee",
                                status=fixed_fee_failure.status,
                                reason=fixed_fee_failure.reason,
                            )
                            if _should_preserve_listing_price_lookup_failure(
                                fixed_fee_failure
                            ) and _listing_fixed_fee_basis_matches(
                                existing_fixed_fee, listing_params
                            ):
                                detail["listing_price_fixed_fee"] = existing_fixed_fee
                            else:
                                listing_fixed_fee_unavailable += 1
                                detail["listing_price_fixed_fee"] = None
                                clear_listing_fixed_fee = (
                                    "listing_price_fixed_fee" in existing_by_id[item_id]
                                )
                        else:
                            listing_fixed_fee_unavailable += 1
                            detail["listing_price_fixed_fee"] = None
                            clear_listing_fixed_fee = (
                                "listing_price_fixed_fee" in existing_by_id[item_id]
                            )
                            item_enrichment_state["listing_price_fixed_fee"] = enrichment_state(
                                source=LISTING_PRICE_FIXED_FEE_SOURCE,
                                status="malformed",
                                reason="malformed_response",
                                synced_at=synced_at,
                                basis=listing_params,
                            )
                            increment_reason_count(
                                diagnostic_reason_counts,
                                field="listing_price_fixed_fee",
                                status="malformed",
                                reason="malformed_response",
                            )
                    else:
                        listing_fixed_fee_enriched += 1
                        detail["listing_price_fixed_fee"] = fixed_fee_projection
                        item_enrichment_state["listing_price_fixed_fee"] = trusted_state(
                            source=LISTING_PRICE_FIXED_FEE_SOURCE,
                            synced_at=synced_at,
                            basis=listing_params,
                        )
            if item_enrichment_state:
                detail["enrichment_state"] = item_enrichment_state
            document = _canonical_item_detail_document(
                existing=existing_item,
                detail=detail,
                seller_id=seller_id,
                synced_at=synced_at,
            )
            items_validated += 1
            if (
                not clear_current_promotion
                and not clear_listing_fixed_fee
                and not clear_listing_fee_projection
                and _canonical_item_values_equal(existing_by_id[item_id], document)
            ):
                unchanged += 1
                continue
            write_plans.append(
                (
                    {"_id": item_id, "seller_id": seller_id},
                    document,
                    clear_current_promotion,
                    clear_listing_fixed_fee,
                    clear_listing_fee_projection,
                )
            )

    items_updated = 0
    if not dry_run:
        items_collection = db[ITEMS_COLLECTION]
        for (
            filter_spec,
            document,
            clear_current_promotion,
            clear_listing_fixed_fee,
            clear_listing_fee_projection,
        ) in write_plans:
            update: dict[str, Any] = {"$set": document}
            unset_fields: dict[str, str] = {}
            if clear_current_promotion:
                unset_fields["current_promotion"] = ""
            if clear_listing_fixed_fee:
                unset_fields["listing_price_fixed_fee"] = ""
            if clear_listing_fee_projection:
                unset_fields["listing_fee_projection"] = ""
            if unset_fields:
                update["$unset"] = unset_fields
            await items_collection.update_one(
                filter_spec,
                update,
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
        sale_price_requested=sale_price_requested,
        sale_price_promotions_enriched=sale_price_promotions_enriched,
        sale_price_promotions_unavailable=sale_price_promotions_unavailable,
        listing_prices_requested=listing_prices_requested,
        listing_fee_projections_enriched=listing_fee_projections_enriched,
        listing_fee_projections_unavailable=listing_fee_projections_unavailable,
        listing_fixed_fee_requested=listing_fixed_fee_requested,
        listing_fixed_fee_enriched=listing_fixed_fee_enriched,
        listing_fixed_fee_unavailable=listing_fixed_fee_unavailable,
        listing_fixed_fee_missing_params=listing_fixed_fee_missing_params,
        diagnostic_reason_counts=diagnostic_reason_counts,
    )


async def run_shipment_real_shipping_cost_enrichment(
    *,
    db: Any,
    gateway: MeliItemGatewayClient,
    seller_id: str,
    dry_run: bool = True,
    limit: int = SHIPMENT_REAL_SHIPPING_COST_ENRICHMENT_LIMIT,
) -> ShipmentRealShippingCostEnrichmentSummary:
    if limit < 1:
        msg = "limit must be positive"
        raise ValueError(msg)

    shipments = await _load_shipments_needing_real_shipping_cost(
        db=db,
        seller_id=seller_id,
        limit=limit,
    )
    synced_at = datetime.now(UTC)
    seen_shipment_ids: set[str] = set()
    shipments_with_id = 0
    shipment_costs_requested = 0
    shipment_real_shipping_costs_enriched = 0
    shipment_real_shipping_costs_unavailable = 0
    write_plans: list[tuple[dict[str, Any], dict[str, Any]]] = []

    for shipment in shipments:
        shipment_id = _optional_string(shipment.get("_id") or shipment.get("id"))
        if shipment_id is None or shipment_id in seen_shipment_ids:
            continue
        seen_shipment_ids.add(shipment_id)
        shipments_with_id += 1
        shipment_costs_requested += 1
        projection = await _resolve_shipment_real_shipping_cost_projection(
            gateway=gateway,
            seller_id=seller_id,
            shipment_id=shipment_id,
            synced_at=synced_at,
        )
        if projection is None:
            shipment_real_shipping_costs_unavailable += 1
            continue
        shipment_real_shipping_costs_enriched += 1
        write_plans.append(
            (
                {"_id": shipment_id, "seller_id": seller_id},
                {"$set": {"real_shipping_cost": projection}},
            )
        )

    shipments_updated = 0
    if not dry_run:
        shipments_collection = db[SHIPMENTS_COLLECTION]
        for filter_spec, update in write_plans:
            await shipments_collection.update_one(
                filter_spec,
                update,
                upsert=False,
                bypass_document_validation=False,
            )
            shipments_updated += 1

    return ShipmentRealShippingCostEnrichmentSummary(
        dry_run=dry_run,
        limit=limit,
        shipments_read=len(shipments),
        shipments_with_id=shipments_with_id,
        shipment_costs_requested=shipment_costs_requested,
        shipment_real_shipping_costs_enriched=shipment_real_shipping_costs_enriched,
        shipment_real_shipping_costs_unavailable=shipment_real_shipping_costs_unavailable,
        shipments_planned=len(write_plans),
        shipments_updated=shipments_updated,
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


async def load_item_status_states_by_item(*, db: Any, seller_id: str) -> dict[str, dict[str, Any]]:
    states = (
        await db[ITEM_STATUS_STATES_COLLECTION].find({"seller_id": seller_id}).to_list(length=None)
    )
    return {
        item_id: normalize_status_history_datetimes(state)
        for state in states
        if (item_id := _optional_string(state.get("item_id"))) is not None
    }


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
    currency_id = _formula_row_currency_id(item)
    site_id = _formula_row_site_id(item_id=item_id, item=item)
    resolved_variation_id = _optional_string(variation_id)
    resolved_inventory_id = _optional_string(inventory_id)
    if resolved_inventory_id is None and resolved_variation_id is None:
        resolved_inventory_id = _optional_string(item.get("inventory_id"))
    status_history_scalars = {
        field: value
        for field in (
            "status_observed_at",
            "status_started_at",
            "paused_since",
            "last_status_change_at",
        )
        if (value := bson_ms_utc_datetime(item.get(field))) is not None
    }
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
            "currency_id": currency_id,
            "site_id": site_id,
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
            **_formula_row_listing_fixed_fee_fields(item),
            **_formula_row_listing_fee_projection_fields(item),
            **_formula_row_current_promotion_fields(item),
            "inventory_id": resolved_inventory_id,
            **_formula_row_listing_price_shipping_basis_fields(item),
            "shipping_logistic_type": _shipping_logistic_type(item.get("shipping")),
            "shipping_payer": _shipping_payer(item.get("shipping")),
            **status_history_scalars,
        },
        "date_created": date_created,
        "updated_at": updated_at,
        "schema_version": READ_MODEL_SCHEMA_VERSION,
    }


def _formula_row_current_promotion_fields(item: dict[str, Any]) -> dict[str, Any]:
    current_promotion = _schema_safe_current_promotion(item.get("current_promotion"))
    return {"current_promotion": current_promotion} if current_promotion is not None else {}


def _formula_row_listing_fixed_fee_fields(item: dict[str, Any]) -> dict[str, Any]:
    fixed_fee = _schema_safe_listing_fixed_fee(item.get("listing_price_fixed_fee"))
    return {"listing_price_fixed_fee": fixed_fee} if fixed_fee is not None else {}


def _formula_row_listing_fee_projection_fields(item: dict[str, Any]) -> dict[str, Any]:
    projection = _schema_safe_listing_fee_projection(item.get("listing_fee_projection"))
    return {"listing_fee_projection": projection} if projection is not None else {}


def _formula_row_listing_price_shipping_basis_fields(item: dict[str, Any]) -> dict[str, Any]:
    shipping = item.get("shipping")
    shipping_values = shipping if isinstance(shipping, dict) else {}
    fields: dict[str, Any] = {}
    shipping_mode = _optional_string(shipping_values.get("mode"))
    logistic_type = _optional_string(shipping_values.get("logistic_type"))
    if shipping_mode is not None:
        fields["shipping_mode"] = shipping_mode
    if logistic_type is not None:
        fields["logistic_type"] = logistic_type
    billable_weight = _schema_safe_numeric(
        item.get("billable_weight") or shipping_values.get("billable_weight")
    )
    if billable_weight is not None:
        fields["billable_weight"] = billable_weight
    if "tags" in item:
        fields["tags"] = _schema_safe_tags(item.get("tags"))
    return fields


async def _load_seller_items(
    *, db: Any, seller_id: str, item_ids: Sequence[str] | None = None
) -> list[dict[str, Any]]:
    filter_spec: dict[str, Any] = {"seller_id": seller_id}
    normalized_item_ids = _unique_non_blank_strings(item_ids or ())
    if normalized_item_ids:
        filter_spec["_id"] = {"$in": normalized_item_ids}
    cursor = db[ITEMS_COLLECTION].find(filter_spec).sort([("_id", 1)])
    return cast("list[dict[str, Any]]", await cursor.to_list(length=None))


def _unique_non_blank_strings(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(normalized for value in values if (normalized := str(value).strip())))


async def _load_seller_site_id(*, db: Any, seller_id: str) -> str | None:
    seller_id_candidates: list[str | int] = [seller_id]
    if seller_id.isdecimal():
        seller_id_candidates.append(int(seller_id))
    for seller_id_candidate in seller_id_candidates:
        account = await db["meli_accounts"].find_one({"seller_id": seller_id_candidate})
        if not isinstance(account, dict):
            continue
        site_id = _optional_string(account.get("site_id"))
        if site_id is not None:
            return site_id.upper()
    return None


def _item_with_status_history(
    item: dict[str, Any], status_state: dict[str, Any] | None
) -> dict[str, Any]:
    if status_state is None:
        return _item_without_status_history(item)
    status_state = normalize_status_history_datetimes(status_state)
    enriched = dict(item)
    enriched["status"] = status_state["current_status"]
    for field in (
        "status_observed_at",
        "status_started_at",
        "paused_since",
        "last_status_change_at",
    ):
        enriched.pop(field, None)
    if (last_observed_at := bson_ms_utc_datetime(status_state.get("last_observed_at"))) is not None:
        enriched["status_observed_at"] = last_observed_at
    for field in ("status_started_at", "paused_since", "last_status_change_at"):
        if (value := bson_ms_utc_datetime(status_state.get(field))) is not None:
            enriched[field] = value
    return enriched


async def _replace_formula_row_from_backfill_if_current(
    collection: Any, formula_row_doc: dict[str, Any], *, db: Any
) -> bool:
    for _ in range(FORMULA_ROW_REPLACE_ATTEMPTS):
        existing = await collection.find_one({"_id": formula_row_doc["_id"]})
        if existing is not None:
            latest_formula_row_doc = await _formula_row_with_latest_status_state(
                db=db,
                formula_row_doc=formula_row_doc,
            )
            latest_observed_at = _formula_row_status_observed_at(latest_formula_row_doc)
            existing_observed_at = _formula_row_status_observed_at(existing)
            if existing_observed_at is not None and (
                latest_observed_at is None or existing_observed_at > latest_observed_at
            ):
                return False
            candidate = _formula_row_with_better_live_paused_scalar_tuple(
                planned=latest_formula_row_doc,
                existing=existing,
            )
            result = await collection.replace_one(
                {
                    "_id": candidate["_id"],
                    **_formula_row_status_history_tuple_guard(existing),
                },
                candidate,
                upsert=False,
            )
            if result.matched_count > 0:
                return True
            continue

        latest_formula_row_doc = await _formula_row_with_latest_status_state(
            db=db,
            formula_row_doc=formula_row_doc,
        )
        try:
            result = await collection.replace_one(
                {
                    "_id": latest_formula_row_doc["_id"],
                    **_status_observed_at_guard("current.status_observed_at", None),
                },
                latest_formula_row_doc,
                upsert=True,
            )
        except DuplicateKeyError:
            continue
        if result.matched_count > 0 or result.upserted_id is not None:
            return True
    return False


async def _formula_row_with_latest_status_state(
    *, db: Any, formula_row_doc: dict[str, Any]
) -> dict[str, Any]:
    seller_id = _optional_string(formula_row_doc.get("seller_id"))
    item_id = _optional_string(formula_row_doc.get("item_id"))
    if seller_id is None or item_id is None:
        return _formula_row_without_status_history(formula_row_doc)
    status_state = await db[ITEM_STATUS_STATES_COLLECTION].find_one(
        {"seller_id": seller_id, "item_id": item_id}
    )
    return _formula_row_with_status_history(formula_row_doc, status_state)


def _formula_row_with_status_history(
    formula_row_doc: dict[str, Any], status_state: dict[str, Any] | None
) -> dict[str, Any]:
    refreshed = _formula_row_without_status_history(formula_row_doc)
    if status_state is None:
        return refreshed
    status_state = normalize_status_history_datetimes(status_state)
    current = refreshed.get("current")
    if not isinstance(current, dict):
        return refreshed
    current["status"] = status_state["current_status"]
    if (last_observed_at := bson_ms_utc_datetime(status_state.get("last_observed_at"))) is not None:
        current["status_observed_at"] = last_observed_at
    for field in STATUS_HISTORY_SCALAR_FIELDS:
        if (value := bson_ms_utc_datetime(status_state.get(field))) is not None:
            current[field] = value
    return refreshed


def _formula_row_without_status_history(formula_row_doc: dict[str, Any]) -> dict[str, Any]:
    stripped = dict(formula_row_doc)
    current = stripped.get("current")
    if not isinstance(current, dict):
        return stripped
    stripped_current = dict(current)
    for field in (
        "status_observed_at",
        "status_started_at",
        "paused_since",
        "last_status_change_at",
    ):
        stripped_current.pop(field, None)
    stripped["current"] = stripped_current
    return stripped


def _item_without_status_history(item: dict[str, Any]) -> dict[str, Any]:
    stripped = dict(item)
    for field in (
        "status_observed_at",
        "status_started_at",
        "paused_since",
        "last_status_change_at",
    ):
        stripped.pop(field, None)
    return stripped


def _formula_row_status_observed_at(formula_row_doc: dict[str, Any] | None) -> datetime | None:
    if formula_row_doc is None:
        return None
    current = formula_row_doc.get("current")
    if not isinstance(current, dict):
        return None
    value = current.get("status_observed_at")
    return bson_ms_utc_datetime(value)


def _formula_row_with_better_live_paused_scalar_tuple(
    *, planned: dict[str, Any], existing: dict[str, Any]
) -> dict[str, Any]:
    planned_observed_at = _formula_row_status_observed_at(planned)
    if (
        planned_observed_at is None
        or _formula_row_status_observed_at(existing) != planned_observed_at
    ):
        return planned
    planned_current = planned.get("current")
    existing_current = existing.get("current")
    if not isinstance(planned_current, dict) or not isinstance(existing_current, dict):
        return planned
    if _optional_string(planned_current.get("status")) != "paused":
        return planned
    if _optional_string(existing_current.get("status")) != "paused":
        return planned
    planned_scalars_raw = {
        field: bson_ms_utc_datetime(planned_current.get(field))
        for field in STATUS_HISTORY_SCALAR_FIELDS
    }
    existing_scalars_raw = {
        field: bson_ms_utc_datetime(existing_current.get(field))
        for field in STATUS_HISTORY_SCALAR_FIELDS
    }
    if any(value is None for value in planned_scalars_raw.values()) or any(
        value is None for value in existing_scalars_raw.values()
    ):
        return planned
    planned_scalars = cast("dict[str, datetime]", planned_scalars_raw)
    existing_scalars = cast("dict[str, datetime]", existing_scalars_raw)
    if existing_scalars["paused_since"] >= planned_scalars["paused_since"]:
        return planned
    if any(
        existing_scalars[field] > planned_scalars[field] for field in STATUS_HISTORY_SCALAR_FIELDS
    ):
        return planned

    merged = dict(planned)
    merged_current = dict(planned_current)
    for field, value in existing_scalars.items():
        merged_current[field] = value
    merged["current"] = merged_current
    return merged


def _formula_row_status_history_tuple_guard(formula_row_doc: dict[str, Any]) -> dict[str, Any]:
    current = formula_row_doc.get("current")
    current_values = current if isinstance(current, dict) else {}
    guard: dict[str, Any] = {}
    status = _optional_string(current_values.get("status"))
    guard["current.status"] = status if status is not None else {"$exists": False}
    for field in ("status_observed_at", *STATUS_HISTORY_SCALAR_FIELDS):
        value = bson_ms_utc_datetime(current_values.get(field))
        guard[f"current.{field}"] = value if value is not None else {"$exists": False}
    return guard


def _status_observed_at_guard(field: str, observed_at: datetime | None) -> dict[str, Any]:
    if observed_at is None:
        return {"$or": [{field: {"$exists": False}}]}
    observed_at = require_bson_ms_utc_datetime(observed_at)
    return {
        "$or": [
            {field: {"$exists": False}},
            {field: {"$lte": observed_at}},
        ]
    }


async def _load_shipments_needing_real_shipping_cost(
    *, db: Any, seller_id: str, limit: int
) -> list[dict[str, Any]]:
    cursor = (
        db[SHIPMENTS_COLLECTION]
        .find(
            {
                "seller_id": seller_id,
                "$or": [
                    {"real_shipping_cost": {"$exists": False}},
                    {"real_shipping_cost": None},
                ],
            }
        )
        .sort([("_id", 1)])
    )
    return cast("list[dict[str, Any]]", await cursor.to_list(length=limit))


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
    payload = {
        **existing,
        **detail,
        "_id": item_id,
        "seller_id": seller_id,
        "last_meli_sync_at": synced_at,
        "schema_version": current_schema_version("items"),
    }
    payload = normalize_status_history_datetimes(payload)
    fixed_fee = payload.get("listing_price_fixed_fee")
    if isinstance(fixed_fee, dict):
        payload["listing_price_fixed_fee"] = _normalize_mongo_loaded_listing_fixed_fee_datetimes(
            fixed_fee
        )
    model = Item.model_validate(payload)
    document = normalize_status_history_datetimes(model.model_dump(by_alias=True, mode="python"))
    if document.get("status_observed_at") is None:
        document.pop("status_observed_at", None)
    for money_field in ("price", "base_price", "seller_shipping_cost"):
        document[money_field] = _schema_safe_numeric(document.get(money_field))
    fixed_fee = _schema_safe_listing_fixed_fee(document.get("listing_price_fixed_fee"))
    if fixed_fee is None:
        document.pop("listing_price_fixed_fee", None)
    else:
        document["listing_price_fixed_fee"] = fixed_fee
    listing_fee_projection = _schema_safe_listing_fee_projection(
        document.get("listing_fee_projection")
    )
    if listing_fee_projection is None:
        document.pop("listing_fee_projection", None)
    else:
        document["listing_fee_projection"] = listing_fee_projection
    current_promotion = _schema_safe_current_promotion(document.get("current_promotion"))
    if current_promotion is None:
        document.pop("current_promotion", None)
    else:
        document["current_promotion"] = current_promotion
    enrichment = schema_safe_enrichment_state(document.get("enrichment_state"))
    if enrichment is None:
        document.pop("enrichment_state", None)
    else:
        document["enrichment_state"] = enrichment
    return document


async def _resolve_sale_price_projection(
    *,
    gateway: MeliItemGatewayClient,
    seller_id: str,
    item_id: str,
    synced_at: datetime,
) -> tuple[dict[str, Any] | None, EnrichmentFailure | None]:
    try:
        response = await gateway.fetch_resource(
            seller_id=seller_id,
            path=_sale_price_path(item_id),
        )
    except (RuntimeError, GatewayRateLimitError, httpx.HTTPStatusError, httpx.RequestError) as exc:
        return None, classify_fetch_exception(exc)
    return project_sale_price_projection(response, synced_at=synced_at), None


async def _resolve_shipment_real_shipping_cost_projection(
    *,
    gateway: MeliItemGatewayClient,
    seller_id: str,
    shipment_id: str,
    synced_at: datetime,
) -> dict[str, Any] | None:
    try:
        response = await gateway.fetch_resource(
            seller_id=seller_id,
            path=_shipment_costs_path(shipment_id),
        )
    except (RuntimeError, GatewayRateLimitError, httpx.HTTPStatusError, httpx.RequestError):
        return None
    projection = ShipmentRealShippingCostProjection.from_meli_costs_payload(
        response,
        seller_id=seller_id,
        synced_at=synced_at,
    )
    return _schema_safe_shipment_real_shipping_cost_projection(projection)


def _shipment_costs_path(shipment_id: str) -> str:
    escaped_shipment_id = quote(shipment_id, safe="")
    return f"/shipments/{escaped_shipment_id}/costs"


def _sale_price_path(item_id: str) -> str:
    escaped_item_id = quote(item_id, safe="")
    return f"/items/{escaped_item_id}/sale_price?context={SALE_PRICE_CONTEXT}"


def project_sale_price_projection(payload: Any, *, synced_at: datetime) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    sale_amount = _safe_decimal(payload.get("amount"))
    regular_amount = _safe_decimal(payload.get("regular_amount"))
    currency_id = _optional_string(payload.get("currency_id"))
    if sale_amount is None or regular_amount is None or currency_id is None:
        return None
    if sale_amount >= regular_amount:
        return None
    reference_at = _sale_price_reference_at(payload) or synced_at
    discount_percent = _safe_decimal(payload.get("discount_percent"))
    if discount_percent is None:
        raw_discount_percent = (regular_amount - sale_amount) / regular_amount * Decimal("100")
        discount_percent = raw_discount_percent.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    try:
        projection = PromoPriceProjection.model_validate(
            {
                "source": SALE_PRICE_SOURCE,
                "sale_amount": sale_amount,
                "regular_amount": regular_amount,
                "discount_percent": discount_percent,
                "currency_id": currency_id,
                "promotion_id": _optional_string(
                    payload.get("promotion_id") or payload.get("campaign_id")
                ),
                "promotion_type": _optional_string(
                    payload.get("promotion_type") or payload.get("type")
                ),
                "reference_at": reference_at,
                "synced_at": synced_at,
            }
        )
    except (InvalidOperation, ValueError):
        return None
    return _schema_safe_current_promotion(projection)


def _sale_price_reference_at(payload: dict[str, Any]) -> datetime | None:
    for key in ("reference_at", "last_updated", "updated_at", "date_created"):
        value = payload.get(key)
        if value is None:
            continue
        try:
            parsed = _parse_utc_datetime(value) if isinstance(value, str) else value
        except ValueError:
            continue
        if isinstance(parsed, datetime):
            return (
                parsed.astimezone(UTC) if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
            )
    return None


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
    for removable_projection in ("current_promotion", "listing_price_fixed_fee"):
        if removable_projection in existing and removable_projection not in planned:
            return False
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
    except (InvalidOperation, ValueError):
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


def _schema_safe_tags(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [tag for raw in value if (tag := str(raw).strip())]


def _existing_enrichment_state(item: dict[str, Any]) -> dict[str, dict[str, Any]]:
    state = item.get("enrichment_state")
    if not isinstance(state, dict):
        return {}
    return {str(key): dict(value) for key, value in state.items() if isinstance(value, dict)}


def _existing_enrichment_basis_matches(
    item: dict[str, Any], *, field: str, basis: dict[str, Any]
) -> bool:
    state = _existing_enrichment_state(item).get(field)
    if state is None:
        return False
    expected_hash = basis_hash(basis)
    if expected_hash is not None and state.get("basis_hash") == expected_hash:
        return True
    existing_basis = state.get("basis")
    if not isinstance(existing_basis, dict):
        return False
    return bounded_basis(existing_basis) == bounded_basis(basis)


def _item_shipping_basis(detail: dict[str, Any]) -> dict[str, Any]:
    shipping = detail.get("shipping")
    shipping_values = shipping if isinstance(shipping, dict) else {}
    basis: dict[str, Any] = {}
    for key, value in {
        "site_id": detail.get("site_id") or _site_from_item_id(str(detail.get("id") or "")),
        "category_id": detail.get("category_id"),
        "currency_id": detail.get("currency_id"),
        "listing_type_id": detail.get("listing_type_id"),
        "price": detail.get("price"),
        "shipping_mode": shipping_values.get("mode") or detail.get("shipping_mode"),
        "logistic_type": shipping_values.get("logistic_type"),
        "billable_weight": detail.get("billable_weight") or shipping_values.get("billable_weight"),
        "tags": detail.get("tags"),
    }.items():
        if value is not None:
            basis[key] = value
    return basis


def _safe_decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, (bool, dict, list)):
        return None
    if isinstance(value, Decimal128):
        decimal_value = value.to_decimal()
    elif isinstance(value, Decimal):
        decimal_value = value
    else:
        try:
            decimal_value = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
    if not decimal_value.is_finite() or decimal_value < 0:
        return None
    return decimal_value


def _listing_price_fixed_fee_params(
    *, item_id: str, detail: dict[str, Any]
) -> dict[str, Any] | None:
    site_id = _optional_string(detail.get("site_id")) or _site_from_item_id(item_id)
    category_id = _optional_string(detail.get("category_id"))
    price = _safe_decimal(detail.get("price") or detail.get("base_price"))
    currency_id = _optional_string(detail.get("currency_id"))
    listing_type_id = _optional_string(detail.get("listing_type_id"))
    shipping = detail.get("shipping")
    shipping_values = shipping if isinstance(shipping, dict) else {}
    shipping_mode = _optional_string(shipping_values.get("mode"))
    logistic_type = _optional_string(shipping_values.get("logistic_type"))
    if None in (
        site_id,
        category_id,
        price,
        currency_id,
        listing_type_id,
        shipping_mode,
        logistic_type,
    ):
        return None
    params: dict[str, Any] = {
        "site_id": site_id,
        "category_id": category_id,
        "price": price,
        "currency_id": str(currency_id).upper(),
        "listing_type_id": listing_type_id,
        "shipping_mode": shipping_mode,
        "logistic_type": logistic_type,
    }
    billable_weight = _safe_decimal(
        detail.get("billable_weight") or shipping_values.get("billable_weight")
    )
    if billable_weight is not None:
        params["billable_weight"] = billable_weight
    tags = detail.get("tags")
    if isinstance(tags, list):
        clean_tags = [tag for raw in tags if (tag := str(raw).strip())]
        if clean_tags:
            params["tags"] = clean_tags
    return params


def _listing_fixed_fee_basis_matches(existing_projection: Any, params: dict[str, Any]) -> bool:
    projection = _schema_safe_listing_fixed_fee(existing_projection)
    if projection is None:
        return False
    existing_params = projection.get("params")
    if not isinstance(existing_params, dict):
        return False
    for key in (
        "site_id",
        "category_id",
        "currency_id",
        "listing_type_id",
        "shipping_mode",
        "logistic_type",
    ):
        existing_value = _optional_string(existing_params.get(key))
        params_value = _optional_string(params.get(key))
        if key in {"site_id", "currency_id"}:
            existing_value = existing_value.upper() if existing_value is not None else None
            params_value = params_value.upper() if params_value is not None else None
        if existing_value != params_value:
            return False
    for key in ("price", "billable_weight"):
        if _safe_decimal(existing_params.get(key)) != _safe_decimal(params.get(key)):
            return False
    return _clean_string_list(existing_params.get("tags")) == _clean_string_list(params.get("tags"))


def _site_from_item_id(item_id: str) -> str | None:
    normalized = item_id.strip().upper()
    return normalized[:3] if len(normalized) >= 3 and normalized[:3].isalpha() else None


def _formula_row_currency_id(item: dict[str, Any]) -> str | None:
    currency_id = _optional_string(item.get("currency_id"))
    return currency_id.upper() if currency_id is not None else None


def _formula_row_site_id(*, item_id: str, item: dict[str, Any]) -> str | None:
    site_id = _optional_string(item.get("site_id")) or _site_from_item_id(item_id)
    return site_id.upper() if site_id is not None else None


def _schema_safe_listing_fixed_fee(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, ListingPriceFixedFeeProjection):
        raw_projection = value.model_dump(mode="python", exclude_none=True)
    elif isinstance(value, dict):
        try:
            raw_projection = ListingPriceFixedFeeProjection.model_validate(
                _listing_fixed_fee_validation_payload(value)
            ).model_dump(mode="python", exclude_none=True)
        except (InvalidOperation, ValueError):
            return None
    else:
        return None
    raw_params = raw_projection["params"]
    shipping_mode = _optional_string(raw_params.get("shipping_mode"))
    logistic_type = _optional_string(raw_params.get("logistic_type"))
    fixed_fee = _decimal128_or_none(raw_projection["fixed_fee"])
    price = _decimal128_or_none(raw_params["price"])
    if fixed_fee is None or price is None or shipping_mode is None or logistic_type is None:
        return None
    params: dict[str, Any] = {
        "site_id": raw_params["site_id"],
        "category_id": raw_params["category_id"],
        "price": price,
        "currency_id": raw_params["currency_id"],
        "listing_type_id": raw_params["listing_type_id"],
        "shipping_mode": shipping_mode,
        "logistic_type": logistic_type,
    }
    if raw_params.get("billable_weight") is not None:
        billable_weight = _decimal128_or_none(raw_params["billable_weight"])
        if billable_weight is None:
            return None
        params["billable_weight"] = billable_weight
    if raw_params.get("tags"):
        params["tags"] = list(raw_params["tags"])
    return {
        "source": raw_projection["source"],
        "fixed_fee": fixed_fee,
        "currency_id": raw_projection["currency_id"],
        "synced_at": raw_projection["synced_at"],
        "params": params,
    }


def _schema_safe_listing_fee_projection(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, ListingFeeProjection):
        raw_projection = value.model_dump(mode="python", exclude_none=True)
    elif isinstance(value, dict):
        try:
            raw_projection = ListingFeeProjection.model_validate(
                _listing_fee_allowed_fields(_normalize_mongo_loaded_listing_fee_datetimes(value))
            ).model_dump(mode="python", exclude_none=True)
        except (InvalidOperation, ValueError):
            return None
    else:
        return None
    price = _decimal128_or_none(raw_projection["price"])
    sale_fee_amount = _decimal128_or_none(raw_projection["sale_fee_amount"])
    percentage_fee = _decimal128_or_none(raw_projection["percentage_fee"])
    if price is None or sale_fee_amount is None or percentage_fee is None:
        return None
    projection: dict[str, Any] = {
        "source": raw_projection["source"],
        "site_id": raw_projection["site_id"],
        "currency_id": raw_projection["currency_id"],
        "price": price,
        "listing_type_id": raw_projection["listing_type_id"],
        "category_id": raw_projection["category_id"],
        "sale_fee_amount": sale_fee_amount,
        "percentage_fee": percentage_fee,
        "synced_at": raw_projection["synced_at"],
    }
    for key in ("shipping_mode", "logistic_type"):
        if raw_projection.get(key) is not None:
            projection[key] = raw_projection[key]
    if raw_projection.get("billable_weight") is not None:
        billable_weight = _decimal128_or_none(raw_projection["billable_weight"])
        if billable_weight is None:
            return None
        projection["billable_weight"] = billable_weight
    if raw_projection.get("tags"):
        projection["tags"] = list(raw_projection["tags"])
    for key in (
        "gross_amount",
        "fixed_fee",
        "meli_percentage_fee",
        "financing_add_on_fee",
    ):
        if raw_projection.get(key) is not None:
            decimal_value = _decimal128_or_none(raw_projection[key])
            if decimal_value is None:
                return None
            projection[key] = decimal_value
    return projection


def _decimal128_or_none(value: Any) -> Decimal128 | None:
    try:
        return Decimal128(value)
    except (DecimalException, ValueError):
        return None


def _normalize_mongo_loaded_listing_fixed_fee_datetimes(value: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(value)
    current = normalized.get("synced_at")
    if isinstance(current, datetime):
        normalized["synced_at"] = (
            current.astimezone(UTC) if current.tzinfo is not None else current.replace(tzinfo=UTC)
        )
    return normalized


def _normalize_mongo_loaded_listing_fee_datetimes(value: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(value)
    current = normalized.get("synced_at")
    if isinstance(current, datetime):
        normalized["synced_at"] = (
            current.astimezone(UTC) if current.tzinfo is not None else current.replace(tzinfo=UTC)
        )
    return normalized


def _listing_fee_allowed_fields(value: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = {
        "source",
        "site_id",
        "currency_id",
        "price",
        "listing_type_id",
        "category_id",
        "sale_fee_amount",
        "percentage_fee",
        "shipping_mode",
        "logistic_type",
        "billable_weight",
        "tags",
        "gross_amount",
        "fixed_fee",
        "meli_percentage_fee",
        "financing_add_on_fee",
        "synced_at",
    }
    return {key: current for key, current in value.items() if key in allowed_keys}


def _listing_fixed_fee_validation_payload(value: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_mongo_loaded_listing_fixed_fee_datetimes(value)
    raw_params = normalized.get("params")
    params = raw_params if isinstance(raw_params, dict) else {}
    allowed_params = {
        key: params[key]
        for key in (
            "site_id",
            "category_id",
            "price",
            "currency_id",
            "listing_type_id",
            "shipping_mode",
            "logistic_type",
            "billable_weight",
            "tags",
        )
        if key in params
    }
    return {
        key: normalized[key]
        for key in ("source", "fixed_fee", "currency_id", "synced_at")
        if key in normalized
    } | {"params": allowed_params}


def _schema_safe_current_promotion(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, PromoPriceProjection):
        raw_projection = value.model_dump(mode="python", exclude_none=True)
    elif isinstance(value, dict):
        try:
            raw_projection = PromoPriceProjection.model_validate(
                _normalize_mongo_loaded_promo_datetimes(value)
            ).model_dump(mode="python", exclude_none=True)
        except ValueError:
            return None
    else:
        return None
    projection: dict[str, Any] = {
        "source": raw_projection["source"],
        "sale_amount": Decimal128(raw_projection["sale_amount"]),
        "regular_amount": Decimal128(raw_projection["regular_amount"]),
        "currency_id": raw_projection["currency_id"],
        "reference_at": raw_projection["reference_at"],
        "synced_at": raw_projection["synced_at"],
    }
    if raw_projection.get("discount_percent") is not None:
        projection["discount_percent"] = Decimal128(raw_projection["discount_percent"])
    for key in ("promotion_id", "promotion_type"):
        if raw_projection.get(key) is not None:
            projection[key] = raw_projection[key]
    return projection


async def _resolve_listing_fee_projection(
    *,
    gateway: MeliItemGatewayClient,
    seller_id: str,
    context: dict[str, Any],
    synced_at: datetime,
) -> dict[str, Any] | None:
    try:
        response = await gateway.fetch_resource(
            seller_id=seller_id,
            path=listing_fee_projection_path(context),
        )
    except (RuntimeError, GatewayRateLimitError, httpx.HTTPStatusError, httpx.RequestError):
        return None
    return project_listing_fee_projection(response, context=context, synced_at=synced_at)


def build_listing_fee_projection_context(
    *, site_id: str | None, detail: dict[str, Any]
) -> dict[str, Any] | None:
    resolved_site_id = _optional_string(site_id)
    price = _safe_decimal(detail.get("price"))
    currency_id = _optional_string(detail.get("currency_id"))
    listing_type_id = _optional_string(detail.get("listing_type_id"))
    category_id = _optional_string(detail.get("category_id"))
    if (
        resolved_site_id is None
        or price is None
        or currency_id is None
        or listing_type_id is None
        or category_id is None
    ):
        return None
    shipping = detail.get("shipping")
    shipping_values = shipping if isinstance(shipping, dict) else {}
    context: dict[str, Any] = {
        "site_id": resolved_site_id.upper(),
        "price": price,
        "listing_type_id": listing_type_id,
        "category_id": category_id,
        "currency_id": currency_id.upper(),
    }
    optional_values = {
        "logistic_type": _optional_string(shipping_values.get("logistic_type")),
        "shipping_mode": _optional_string(
            shipping_values.get("mode") or detail.get("shipping_mode")
        ),
        "billable_weight": _safe_decimal(
            detail.get("billable_weight") or shipping_values.get("billable_weight")
        ),
    }
    context.update({key: value for key, value in optional_values.items() if value is not None})
    shipping_modes = _clean_string_list(detail.get("shipping_modes"))
    if shipping_modes:
        context["shipping_modes"] = shipping_modes
    tags = _clean_string_list(detail.get("tags"))
    if tags:
        context["tags"] = tags
    return context


def listing_fee_projection_path(context: dict[str, Any]) -> str:
    site_id = quote(str(context["site_id"]), safe="")
    ordered_keys = [
        "price",
        "listing_type_id",
        "category_id",
        "currency_id",
        "logistic_type",
        "shipping_mode",
        "billable_weight",
    ]
    query_parts = [
        f"{key}={quote(_param_string(context[key]), safe='')}"
        for key in ordered_keys
        if context.get(key) is not None
    ]
    for repeated_key in ("shipping_modes", "tags"):
        values = context.get(repeated_key)
        if isinstance(values, list):
            query_parts.extend(
                f"{repeated_key}={quote(str(value), safe='')}"
                for value in values
                if str(value).strip()
            )
    return f"/sites/{site_id}/listing_prices?{'&'.join(query_parts)}"


def project_listing_fee_projection(
    payload: Any, *, context: dict[str, Any], synced_at: datetime
) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    sale_fee_details = payload.get("sale_fee_details")
    if not isinstance(sale_fee_details, dict):
        return None
    sale_fee_amount = _safe_decimal(payload.get("sale_fee_amount"))
    percentage_fee = _safe_decimal(sale_fee_details.get("percentage_fee"))
    payload_currency = _optional_string(payload.get("currency_id"))
    context_currency = _optional_string(context.get("currency_id"))
    if (
        sale_fee_amount is None
        or percentage_fee is None
        or (
            payload_currency is not None
            and context_currency is not None
            and payload_currency.upper() != context_currency.upper()
        )
    ):
        return None
    try:
        projection = ListingFeeProjection.model_validate(
            {
                "source": LISTING_FEE_PROJECTION_SOURCE,
                "site_id": context.get("site_id"),
                "currency_id": context_currency,
                "price": context.get("price"),
                "listing_type_id": context.get("listing_type_id"),
                "category_id": context.get("category_id"),
                "shipping_mode": context.get("shipping_mode"),
                "logistic_type": context.get("logistic_type"),
                "billable_weight": context.get("billable_weight"),
                "tags": context.get("tags"),
                "sale_fee_amount": sale_fee_amount,
                "percentage_fee": percentage_fee,
                "gross_amount": _safe_decimal(sale_fee_details.get("gross_amount")),
                "fixed_fee": _safe_decimal(sale_fee_details.get("fixed_fee")),
                "meli_percentage_fee": _safe_decimal(sale_fee_details.get("meli_percentage_fee")),
                "financing_add_on_fee": _safe_decimal(sale_fee_details.get("financing_add_on_fee")),
                "synced_at": synced_at,
            }
        )
    except (InvalidOperation, ValueError):
        return None
    return _schema_safe_listing_fee_projection(projection)


def _clean_string_list(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for raw in value if (item := _optional_string(raw)) is not None]


async def _resolve_listing_price_fixed_fee_projection(
    *,
    gateway: MeliItemGatewayClient,
    seller_id: str,
    params: dict[str, Any],
    synced_at: datetime,
) -> tuple[dict[str, Any] | None, EnrichmentFailure | None]:
    try:
        response = await gateway.fetch_resource(
            seller_id=seller_id,
            path=_listing_price_fixed_fee_path(params),
        )
    except (RuntimeError, GatewayRateLimitError, httpx.HTTPStatusError, httpx.RequestError) as exc:
        return None, classify_fetch_exception(exc)
    return (
        project_listing_price_fixed_fee_projection(response, params=params, synced_at=synced_at),
        None,
    )


def _listing_price_fixed_fee_path(params: dict[str, Any]) -> str:
    site_id = quote(str(params["site_id"]), safe="")
    ordered_keys = [
        "price",
        "category_id",
        "currency_id",
        "listing_type_id",
        "shipping_mode",
        "logistic_type",
        "billable_weight",
    ]
    query_parts = [
        f"{key}={quote(_param_string(params[key]), safe='')}"
        for key in ordered_keys
        if params.get(key) is not None
    ]
    tags = params.get("tags")
    if isinstance(tags, list):
        query_parts.extend(f"tags={quote(str(tag), safe='')}" for tag in tags if str(tag).strip())
    return f"/sites/{site_id}/listing_prices?{'&'.join(query_parts)}"


def _param_string(value: Any) -> str:
    decimal_value = _safe_decimal(value)
    if decimal_value is not None:
        return format(decimal_value, "f")
    return str(value)


def project_listing_price_fixed_fee_projection(
    payload: Any, *, params: dict[str, Any], synced_at: datetime
) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    sale_fee_details = payload.get("sale_fee_details")
    if not isinstance(sale_fee_details, dict):
        return None
    fixed_fee = _safe_decimal(sale_fee_details.get("fixed_fee"))
    payload_currency = _optional_string(payload.get("currency_id") or params.get("currency_id"))
    if fixed_fee is None or payload_currency is None:
        return None
    try:
        projection = ListingPriceFixedFeeProjection.model_validate(
            {
                "source": LISTING_PRICE_FIXED_FEE_SOURCE,
                "fixed_fee": fixed_fee,
                "currency_id": payload_currency,
                "synced_at": synced_at,
                "params": params,
            }
        )
    except (InvalidOperation, ValueError):
        return None
    return _schema_safe_listing_fixed_fee(projection)


def _schema_safe_shipment_real_shipping_cost_projection(
    value: ShipmentRealShippingCostProjection | None,
) -> dict[str, Any] | None:
    if value is None:
        return None
    raw_projection = value.model_dump(mode="python", exclude_none=True)
    seller_cost = _decimal128_or_none(raw_projection["seller_cost"])
    if seller_cost is None:
        return None
    projection: dict[str, Any] = {
        "source": raw_projection["source"],
        "seller_cost": seller_cost,
        "synced_at": raw_projection["synced_at"],
    }
    if raw_projection.get("receiver_cost") is not None:
        receiver_cost = _decimal128_or_none(raw_projection["receiver_cost"])
        if receiver_cost is None:
            return None
        projection["receiver_cost"] = receiver_cost
    for key in ("currency_id", "matched_sender_id"):
        if raw_projection.get(key) is not None:
            projection[key] = raw_projection[key]
    return projection


def _normalize_mongo_loaded_promo_datetimes(value: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(value)
    for key in ("reference_at", "synced_at"):
        current = normalized.get(key)
        if isinstance(current, datetime):
            normalized[key] = (
                current.astimezone(UTC)
                if current.tzinfo is not None
                else current.replace(tzinfo=UTC)
            )
    return normalized


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
        return require_bson_ms_utc_datetime(value)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    if not isinstance(value, str) or not isinstance(other, (datetime, date)):
        return None
    try:
        return require_bson_ms_utc_datetime(_parse_utc_datetime(value))
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
            from google.cloud import kms_v1

            gateway = MeliGatewayClient(
                os.environ.get("GATEWAY_BASE_URL", DEFAULT_GATEWAY_BASE_URL),
                MeliGatewayAuth("sheets", kms_v1.KeyManagementServiceClient()),
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
            from google.cloud import kms_v1

            gateway = MeliGatewayClient(
                os.environ.get("GATEWAY_BASE_URL", DEFAULT_GATEWAY_BASE_URL),
                MeliGatewayAuth("sheets", kms_v1.KeyManagementServiceClient()),
            )
            return await run_item_detail_enrichment(
                db=client[mongo_db_name],
                gateway=gateway,
                seller_id=args.seller_id,
                dry_run=args.dry_run,
                sale_price_enabled=bool(args.sale_price_enabled),
                listing_fixed_fee_enabled=bool(args.listing_fixed_fee_enabled),
            )
        if args.source == "shipments-costs":
            from google.cloud import kms_v1

            gateway = MeliGatewayClient(
                os.environ.get("GATEWAY_BASE_URL", DEFAULT_GATEWAY_BASE_URL),
                MeliGatewayAuth("sheets", kms_v1.KeyManagementServiceClient()),
            )
            return await run_shipment_real_shipping_cost_enrichment(
                db=client[mongo_db_name],
                gateway=gateway,
                seller_id=args.seller_id,
                dry_run=args.dry_run,
                limit=cast("int", args.limit),
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


def _positive_int_arg(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    summary = asyncio.run(_run_cli(args))
    print(json.dumps(summary.as_dict(), sort_keys=True))


if __name__ == "__main__":
    main()
