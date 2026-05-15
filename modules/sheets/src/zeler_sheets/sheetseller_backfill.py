from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any, cast

from zeler_sheets.formulas.read_models import normalize_sku

ITEMS_COLLECTION = "items"
ITEM_SKU_INDEX_COLLECTION = "sheets_item_sku_index"
ITEM_FORMULA_ROWS_COLLECTION = "sheets_item_formula_rows"
READ_MODEL_SCHEMA_VERSION = 2
SELLER_SKU_ATTRIBUTE_ID = "SELLER_SKU"


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


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill Sheetseller formula read models from canonical items."
    )
    parser.add_argument("--seller-id", required=True, help="Seller id to backfill.")
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


@dataclass(frozen=True)
class SkuCandidate:
    sku: str | None
    source: str | None
    ambiguous: bool = False


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


async def _run_cli(args: argparse.Namespace) -> BackfillSummary:
    from motor.motor_asyncio import AsyncIOMotorClient

    mongo_uri = os.environ.get("MONGO_URI")
    mongo_db_name = os.environ.get("MONGO_DB")
    if not mongo_uri:
        raise SystemExit("MONGO_URI is required")
    if not mongo_db_name:
        raise SystemExit("MONGO_DB is required")

    client: AsyncIOMotorClient[Any] = AsyncIOMotorClient(mongo_uri)
    try:
        return await run_sheetseller_backfill(
            db=client[mongo_db_name], seller_id=args.seller_id, dry_run=args.dry_run
        )
    finally:
        client.close()


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    summary = asyncio.run(_run_cli(args))
    print(json.dumps(summary.as_dict(), sort_keys=True))


if __name__ == "__main__":
    main()
