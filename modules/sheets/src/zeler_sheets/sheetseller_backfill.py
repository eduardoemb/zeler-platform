from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol, cast

from zeler_sheets.formulas.read_models import normalize_sku

ITEMS_COLLECTION = "items"
ORDERS_COLLECTION = "orders"
ITEM_SKU_INDEX_COLLECTION = "sheets_item_sku_index"
ITEM_FORMULA_ROWS_COLLECTION = "sheets_item_formula_rows"
READ_MODEL_SCHEMA_VERSION = 2
SELLER_SKU_ATTRIBUTE_ID = "SELLER_SKU"
DEFAULT_GATEWAY_BASE_URL = "http://gateway:8080/proxy/meli"


class MeliOrderGatewayClient(Protocol):
    async def fetch_resource(self, *, seller_id: str, path: str) -> dict[str, Any]: ...


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
class OrderIdentityMergeStats:
    matched_order_lines: int = 0
    updated_order_lines: int = 0
    identity_fields_added: int = 0
    skipped_unmatched_lines: int = 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill Sheetseller formula read models from canonical items."
    )
    parser.add_argument("--seller-id", required=True, help="Seller id to backfill.")
    parser.add_argument(
        "--source",
        choices=("items", "order-lines", "orders-repair"),
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

    sku_index_collection = db[ITEM_SKU_INDEX_COLLECTION]
    formula_rows_collection = db[ITEM_FORMULA_ROWS_COLLECTION]

    for item in items:
        sku_index_docs: list[dict[str, Any]]
        formula_row_doc: dict[str, Any] | None
        item_sku = resolve_seller_sku(item)
        if item_sku.ambiguous:
            skipped_ambiguous_sku += 1
            sku_index_docs = []
            formula_row_doc = None
        elif item_sku.sku is None:
            skipped_missing_sku += 1
            sku_index_docs = []
            formula_row_doc = None
        else:
            items_with_sku += 1
            sku_index_docs = [build_sku_index_doc(item, seller_id=seller_id, sku=item_sku.sku)]
            formula_row_doc = build_formula_row_doc(item, seller_id=seller_id, sku=item_sku.sku)

        variation_docs, variation_skips, variation_ambiguous = build_variation_sku_index_docs(
            item, seller_id=seller_id
        )
        variation_sku_rows += len(variation_docs)
        skipped_missing_variation_sku += variation_skips
        skipped_ambiguous_sku += variation_ambiguous
        sku_index_docs.extend(variation_docs)

        if not sku_index_docs and formula_row_doc is None:
            continue

        sku_index_upserts += len(sku_index_docs)
        formula_row_upserts += 1 if formula_row_doc is not None else 0

        if dry_run:
            continue

        for sku_index_doc in sku_index_docs:
            await sku_index_collection.replace_one(
                {"_id": sku_index_doc["_id"]}, sku_index_doc, upsert=True
            )
        if formula_row_doc is not None:
            await formula_rows_collection.replace_one(
                {"_id": formula_row_doc["_id"]}, formula_row_doc, upsert=True
            )

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
        "inventory_id": inventory_id,
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
        "updated_at": candidate.updated_at,
        "schema_version": READ_MODEL_SCHEMA_VERSION,
    }


def build_formula_row_doc(
    item: dict[str, Any], *, seller_id: str, sku: str | None = None
) -> dict[str, Any]:
    resolved_sku = sku or extract_seller_sku(item)
    if resolved_sku is None:
        msg = "item does not contain a SELLER_SKU attribute"
        raise ValueError(msg)
    item_id = _item_id(item)
    normalized_sku = normalize_sku(resolved_sku)
    date_created = item.get("date_created")
    updated_at = _updated_at(item)
    return {
        "_id": _formula_row_id(seller_id=seller_id, normalized_sku=normalized_sku, item_id=item_id),
        "seller_id": seller_id,
        "seller_nickname": _optional_string(item.get("seller_nickname") or item.get("nickname")),
        "sku": resolved_sku,
        "normalized_sku": normalized_sku,
        "item_id": item_id,
        "variation_id": item.get("variation_id"),
        "inventory_id": None,
        "current": {
            "title": item.get("title"),
            "status": item.get("status"),
            "available_quantity": item.get("available_quantity"),
            "base_price": item.get("base_price"),
            "category_id": item.get("category_id"),
            "date_created": date_created,
            "updated_at": updated_at,
            "permalink": None,
            "thumbnail": None,
            "catalog_product_id": None,
            "inventory_id": None,
        },
        "date_created": date_created,
        "updated_at": updated_at,
        "schema_version": READ_MODEL_SCHEMA_VERSION,
    }


async def _load_seller_items(*, db: Any, seller_id: str) -> list[dict[str, Any]]:
    cursor = db[ITEMS_COLLECTION].find({"seller_id": seller_id}).sort([("_id", 1)])
    return cast("list[dict[str, Any]]", await cursor.to_list(length=None))


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
    return item.get("updated_at") or item.get("last_updated")


def _read_model_id(
    *, seller_id: str, normalized_sku: str, item_id: str, variation_id: str | None
) -> str:
    identity = variation_id if variation_id is not None else "item"
    return f"{seller_id}:{normalized_sku}:{item_id}:{identity}"


def _formula_row_id(*, seller_id: str, normalized_sku: str, item_id: str) -> str:
    return f"{seller_id}:{normalized_sku}:{item_id}"


async def _run_cli(
    args: argparse.Namespace,
) -> BackfillSummary | OrderLineIdentityBackfillSummary | OrderIdentityRepairSummary:
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
        raise SystemExit("--date-from and --date-to are required for --source orders-repair")
    return str(args.date_from), str(args.date_to)


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    summary = asyncio.run(_run_cli(args))
    print(json.dumps(summary.as_dict(), sort_keys=True))


if __name__ == "__main__":
    main()
