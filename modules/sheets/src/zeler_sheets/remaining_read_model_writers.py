from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from bson.decimal128 import Decimal128
from pymongo.errors import DuplicateKeyError

ITEMS_COLLECTION = "items"
ITEM_FORMULA_ROWS_COLLECTION = "sheets_item_formula_rows"
PRICE_HISTORY_SNAPSHOTS_COLLECTION = "sheets_price_history_snapshots"
STOCKOUT_SNAPSHOTS_COLLECTION = "sheets_stockout_snapshots"
READ_MODEL_SCHEMA_VERSION = 1
PRICE_HISTORY_LIMIT = 3
OBSERVATION_BASES = frozenset({"current_observed", "event_observed", "zeler_first_observed"})
OBSERVATION_SOURCES = frozenset(
    {
        "sheets_event_persistence",
        "sheets_backfill",
        "historical_meli_backfill",
        "manual_reconciliation",
    }
)


@dataclass(frozen=True)
class RemainingObservedReadModelSeedSummary:
    seller_id: str
    dry_run: bool
    source: str
    items_considered: int
    price_snapshots_planned: int
    price_snapshots_updated: int
    stockout_snapshots_planned: int
    stockout_snapshots_updated: int
    price_item_ids: tuple[str, ...]
    stockout_item_ids: tuple[str, ...]
    skipped_price_missing_basis: int = 0
    skipped_stockout_missing_basis: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


async def run_remaining_observed_read_model_seed(
    db: Any,
    seller_id: str,
    *,
    dry_run: bool = True,
    now: datetime | None = None,
    now_fn: Callable[[], datetime] | None = None,
    max_items: int | None = None,
) -> RemainingObservedReadModelSeedSummary:
    seller = str(seller_id)
    observed_now = _utc(now_fn() if now_fn is not None else now or datetime.now(UTC))
    candidates = await _current_observed_candidates(
        db=db, seller_id=seller, fallback_observed_at=observed_now, limit=max_items
    )
    price_planned = price_updated = stockout_planned = stockout_updated = 0
    skipped_price = skipped_stockout = 0
    price_item_ids: list[str] = []
    stockout_item_ids: list[str] = []
    for item, observed_at in candidates:
        item_id = _item_id(item)
        if (
            item_id is None
            or _price_entry(item, observed_at=observed_at, observation_basis="current_observed")
            is None
        ):
            skipped_price += 1
        else:
            price_planned += 1
            price_item_ids.append(item_id)
            if not dry_run and await record_price_history_observation(
                db,
                item,
                seller_id=seller,
                observed_at=observed_at,
                source="sheets_backfill",
                observation_basis="current_observed",
            ):
                price_updated += 1
        stockout_basis = _stockout_basis(item, default="current_observed")
        stockout_observed_at = _stockout_observed_at(item, fallback_observed_at=observed_now)
        if (
            item_id is None
            or _stockout_doc(
                item,
                seller_id=seller,
                observed_at=stockout_observed_at,
                source="sheets_backfill",
                observation_basis=stockout_basis,
                existing=None,
            )
            is None
        ):
            skipped_stockout += 1
        else:
            stockout_planned += 1
            stockout_item_ids.append(item_id)
            if not dry_run and await record_stockout_observation(
                db,
                item,
                seller_id=seller,
                observed_at=stockout_observed_at,
                source="sheets_backfill",
                observation_basis="current_observed",
            ):
                stockout_updated += 1
    return RemainingObservedReadModelSeedSummary(
        seller_id=seller,
        dry_run=dry_run,
        source="current_observed",
        items_considered=len(candidates),
        price_snapshots_planned=price_planned,
        price_snapshots_updated=price_updated,
        stockout_snapshots_planned=stockout_planned,
        stockout_snapshots_updated=stockout_updated,
        price_item_ids=tuple(price_item_ids),
        stockout_item_ids=tuple(stockout_item_ids),
        skipped_price_missing_basis=skipped_price,
        skipped_stockout_missing_basis=skipped_stockout,
    )


async def record_price_history_observation(
    db: Any,
    item: Mapping[str, Any],
    *,
    seller_id: str,
    observed_at: datetime,
    source: str,
    observation_basis: str,
) -> bool:
    item_id = _item_id(item)
    entry = _price_entry(item, observed_at=_utc(observed_at), observation_basis=observation_basis)
    if item_id is None or entry is None:
        return False
    collection = db[PRICE_HISTORY_SNAPSHOTS_COLLECTION]
    doc_id = _doc_id(seller_id, item_id)
    existing = await collection.find_one({"_id": doc_id})
    if (latest_existing := _latest_price_observed_at(existing)) is not None and _utc(
        observed_at
    ) < latest_existing:
        return False
    prices = _price_entries(existing)
    if prices and _same_price(prices[0], entry):
        if not _price_document_needs_normalization(existing, prices):
            return False
        return await _replace_observation_document(
            collection,
            doc_id=doc_id,
            document=_price_history_doc(
                seller_id=str(seller_id),
                item_id=item_id,
                title=_str(item.get("title")),
                prices=prices,
                snapshot_at=_existing_snapshot_at(existing, fallback=_utc(observed_at)),
                source=_existing_source(existing, source),
                observation_basis=_existing_observation_basis(existing, observation_basis),
            ),
            timestamp_field="snapshot_at",
            observed_at=_utc(observed_at),
            existing=existing,
        )
    return await _replace_observation_document(
        collection,
        doc_id=doc_id,
        document=_price_history_doc(
            seller_id=str(seller_id),
            item_id=item_id,
            title=_str(item.get("title")),
            prices=[entry, *prices][:PRICE_HISTORY_LIMIT],
            snapshot_at=_utc(observed_at),
            source=source,
            observation_basis=observation_basis,
        ),
        timestamp_field="snapshot_at",
        observed_at=_utc(observed_at),
        existing=existing,
    )


async def record_stockout_observation(
    db: Any,
    item: Mapping[str, Any],
    *,
    seller_id: str,
    observed_at: datetime,
    source: str,
    observation_basis: str,
) -> bool:
    item_id = _item_id(item)
    if item_id is None:
        return False
    collection = db[STOCKOUT_SNAPSHOTS_COLLECTION]
    doc_id = _doc_id(seller_id, item_id)
    existing = await collection.find_one({"_id": doc_id})
    if (
        isinstance(existing, Mapping)
        and (latest_existing := _dt(existing.get("observed_at"))) is not None
        and _utc(observed_at) < latest_existing
    ):
        return False
    document = _stockout_doc(
        item,
        seller_id=str(seller_id),
        observed_at=_utc(observed_at),
        source=source,
        observation_basis=_stockout_basis(item, default=observation_basis),
        existing=existing,
    )
    if document is None:
        return False
    return await _replace_observation_document(
        collection,
        doc_id=doc_id,
        document=document,
        timestamp_field="observed_at",
        observed_at=_utc(observed_at),
        existing=existing,
    )


async def _current_observed_candidates(
    *, db: Any, seller_id: str, fallback_observed_at: datetime, limit: int | None = None
) -> list[tuple[dict[str, Any], datetime]]:
    if limit is not None and limit <= 0:
        return []
    by_item: dict[str, tuple[dict[str, Any], datetime]] = {}
    for row in await _all(db[ITEM_FORMULA_ROWS_COLLECTION], {"seller_id": seller_id}, limit=limit):
        if _formula_row_is_variation_scoped(row):
            continue
        current = row.get("current")
        item_id = _str(row.get("item_id"))
        if item_id is None or not isinstance(current, Mapping):
            continue
        by_item.setdefault(
            item_id,
            (
                {
                    "_id": item_id,
                    "seller_id": seller_id,
                    "title": current.get("title"),
                    "status": current.get("status"),
                    "price": current.get("price"),
                    "available_quantity": current.get("available_quantity"),
                    "sku": row.get("sku"),
                    "normalized_sku": row.get("normalized_sku"),
                    "url": current.get("url") or current.get("permalink"),
                    "logistic_type": current.get("logistic_type")
                    or current.get("shipping_logistic_type"),
                    **_status_dates(current),
                },
                _first_dt(current.get("updated_at"), row.get("updated_at"), fallback_observed_at),
            ),
        )
        if limit is not None and len(by_item) >= limit:
            break
    remaining_limit = None if limit is None else max(limit - len(by_item), 0)
    if remaining_limit == 0:
        return list(by_item.values())
    for item in await _all(db[ITEMS_COLLECTION], {"seller_id": seller_id}, limit=remaining_limit):
        item_id = _item_id(item)
        if item_id is None:
            continue
        raw_shipping = item.get("shipping")
        shipping: Mapping[str, Any] = raw_shipping if isinstance(raw_shipping, Mapping) else {}
        candidate = dict(item)
        sku = _str(item.get("sku") or item.get("seller_sku")) or _attribute_sku(item)
        candidate.update(
            {
                "_id": item_id,
                "seller_id": seller_id,
                "sku": sku,
                "normalized_sku": str(sku).strip().upper() if sku else None,
                "url": item.get("url") or item.get("permalink"),
                "logistic_type": item.get("logistic_type") or shipping.get("logistic_type"),
            }
        )
        by_item.setdefault(
            item_id,
            (
                candidate,
                _first_dt(
                    item.get("last_meli_sync_at"), item.get("last_updated"), fallback_observed_at
                ),
            ),
        )
        if limit is not None and len(by_item) >= limit:
            break
    candidates = list(by_item.values())
    return candidates[:limit] if limit is not None else candidates


async def _all(
    collection: Any, filter_spec: dict[str, Any], *, limit: int | None = None
) -> list[dict[str, Any]]:
    cursor = collection.find(filter_spec)
    if limit is not None and callable(cursor_limit := getattr(cursor, "limit", None)):
        cursor = cursor_limit(limit)
    if callable(to_list := getattr(cursor, "to_list", None)):
        return [dict(row) for row in await to_list(length=limit)]
    rows: list[dict[str, Any]] = []
    async for row in cast("AsyncIterator[Mapping[str, Any]]", cursor):
        rows.append(dict(row))
        if limit is not None and len(rows) >= limit:
            break
    return rows


def _price_entry(
    item: Mapping[str, Any], *, observed_at: datetime, observation_basis: str
) -> dict[str, Any] | None:
    price = _money(item.get("price"))
    status = _str(item.get("status"))
    if price is None or status is None:
        return None
    return {
        "price": Decimal128(str(price)),
        "status": status,
        "observed_at": _utc(observed_at),
        "observation_basis": _observation_basis(observation_basis, "current_observed"),
    }


def _stockout_doc(
    item: Mapping[str, Any],
    *,
    seller_id: str,
    observed_at: datetime,
    source: str,
    observation_basis: str,
    existing: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    item_id = _item_id(item)
    stock = _stock(item.get("available_quantity"))
    if item_id is None or stock is None:
        return None
    stock_state = "out_of_stock" if stock <= 0 else "in_stock"
    return {
        "_id": _doc_id(seller_id, item_id),
        "seller_id": seller_id,
        "item_id": item_id,
        "sku": _str(item.get("sku")),
        "normalized_sku": _str(item.get("normalized_sku")),
        "title": _str(item.get("title")),
        "price": Decimal128(str(price))
        if (price := _money(item.get("price"))) is not None
        else None,
        "logistic_type": _str(item.get("logistic_type")),
        "url": _str(item.get("url") or item.get("permalink")),
        "status": _str(item.get("status")),
        "stock_state": stock_state,
        "current_stock": stock,
        "out_of_stock_since": _out_since(item, stock_state, observed_at, existing),
        "observed_at": _utc(observed_at),
        "source": _observation_source(source, "sheets_backfill"),
        "observation_basis": observation_basis,
        "schema_version": READ_MODEL_SCHEMA_VERSION,
    }


def _price_history_doc(
    *,
    seller_id: str,
    item_id: str,
    title: str | None,
    prices: Sequence[Mapping[str, Any]],
    snapshot_at: datetime,
    source: str,
    observation_basis: str,
) -> dict[str, Any]:
    return {
        "_id": _doc_id(seller_id, item_id),
        "seller_id": seller_id,
        "item_id": item_id,
        "title": title,
        "prices": [dict(entry) for entry in prices][:PRICE_HISTORY_LIMIT],
        "snapshot_at": _utc(snapshot_at),
        "source": _observation_source(source, "sheets_backfill"),
        "observation_basis": _observation_basis(observation_basis, "current_observed"),
        "schema_version": READ_MODEL_SCHEMA_VERSION,
    }


def _price_entries(existing: Any) -> list[dict[str, Any]]:
    if not isinstance(existing, Mapping) or not isinstance(existing.get("prices"), Sequence):
        return []
    fallback_basis = _observation_basis(existing.get("observation_basis"), "current_observed")
    entries: list[dict[str, Any]] = []
    for entry in existing["prices"]:
        if not isinstance(entry, Mapping):
            continue
        price = _money(entry.get("price"))
        status = _str(entry.get("status"))
        observed_at = _dt(entry.get("observed_at"))
        if price is None or status is None or observed_at is None:
            continue
        entries.append(
            {
                "price": Decimal128(str(price)),
                "status": status,
                "observed_at": observed_at,
                "observation_basis": _observation_basis(
                    entry.get("observation_basis"), fallback_basis
                ),
            }
        )
    return entries[:PRICE_HISTORY_LIMIT]


def _price_document_needs_normalization(
    existing: Any, normalized_prices: Sequence[Mapping[str, Any]]
) -> bool:
    if not isinstance(existing, Mapping):
        return False
    if _str(existing.get("observation_basis")) not in OBSERVATION_BASES:
        return True
    if _str(existing.get("source")) not in OBSERVATION_SOURCES:
        return True
    if not isinstance(existing.get("snapshot_at"), datetime):
        return True
    raw_prices = existing.get("prices")
    if not isinstance(raw_prices, Sequence) or isinstance(raw_prices, (str, bytes, bytearray)):
        return bool(normalized_prices)
    if len(raw_prices) != len(normalized_prices):
        return True
    return any(
        not isinstance(entry, Mapping)
        or _str(entry.get("observation_basis")) not in OBSERVATION_BASES
        or not isinstance(entry.get("observed_at"), datetime)
        or not _raw_price_is_schema_numeric(entry.get("price"))
        for entry in raw_prices
    )


def _latest_price_observed_at(existing: Any) -> datetime | None:
    timestamps = [entry["observed_at"] for entry in _price_entries(existing)]
    return max(timestamps) if timestamps else None


def _same_price(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return _money(left.get("price")) == _money(right.get("price")) and _str(
        left.get("status")
    ) == _str(right.get("status"))


def _stockout_basis(item: Mapping[str, Any], *, default: str) -> str:
    if (
        _stock(item.get("available_quantity")) == 0
        and _first_dt_or_none(*_status_dates(item).values()) is None
    ):
        return "zeler_first_observed"
    return default


def _stockout_observed_at(item: Mapping[str, Any], *, fallback_observed_at: datetime) -> datetime:
    return _first_dt_or_none(*_status_dates(item).values()) or _utc(fallback_observed_at)


def _observation_basis(value: Any, fallback: str) -> str:
    normalized = _str(value)
    if normalized in OBSERVATION_BASES:
        return normalized
    return fallback if fallback in OBSERVATION_BASES else "current_observed"


def _observation_source(value: Any, fallback: str) -> str:
    normalized = _str(value)
    if normalized in OBSERVATION_SOURCES:
        return normalized
    return fallback if fallback in OBSERVATION_SOURCES else "sheets_backfill"


def _existing_observation_basis(existing: Any, fallback: str) -> str:
    if isinstance(existing, Mapping):
        return _observation_basis(existing.get("observation_basis"), fallback)
    return _observation_basis(None, fallback)


def _existing_source(existing: Any, fallback: str) -> str:
    if isinstance(existing, Mapping):
        return _observation_source(existing.get("source"), fallback)
    return _observation_source(None, fallback)


def _existing_snapshot_at(existing: Any, *, fallback: datetime) -> datetime:
    if (
        isinstance(existing, Mapping)
        and (snapshot_at := _dt(existing.get("snapshot_at"))) is not None
    ):
        return snapshot_at
    return fallback


def _existing_str(existing: Any, field: str) -> str | None:
    return _str(existing.get(field)) if isinstance(existing, Mapping) else None


def _raw_price_is_schema_numeric(value: Any) -> bool:
    return isinstance(value, (Decimal128, Decimal, int, float)) and not isinstance(value, bool)


async def _replace_observation_document(
    collection: Any,
    *,
    doc_id: str,
    document: dict[str, Any],
    timestamp_field: str,
    observed_at: datetime,
    existing: Any,
) -> bool:
    if not isinstance(existing, Mapping) and await _insert_observation_document(
        collection, document
    ):
        return True
    result = await collection.replace_one(
        _monotonic_replace_filter(
            doc_id,
            timestamp_field=timestamp_field,
            observed_at=observed_at,
            existing=existing,
        ),
        document,
        upsert=False,
    )
    return _write_applied(result)


async def _insert_observation_document(collection: Any, document: dict[str, Any]) -> bool:
    insert_one = getattr(collection, "insert_one", None)
    if not callable(insert_one):
        return False
    try:
        result = await insert_one(document)
    except DuplicateKeyError:
        return False
    return getattr(result, "inserted_id", None) is not None


def _monotonic_replace_filter(
    doc_id: str,
    *,
    timestamp_field: str,
    observed_at: datetime,
    existing: Any,
) -> dict[str, Any]:
    timestamp_conditions: list[dict[str, Any]] = [
        {timestamp_field: {"$exists": False}},
        {timestamp_field: {"$lte": _utc(observed_at)}},
    ]
    if isinstance(existing, Mapping):
        raw_timestamp = existing.get(timestamp_field)
        if (
            not isinstance(raw_timestamp, datetime)
            and (parsed_timestamp := _dt(raw_timestamp)) is not None
            and parsed_timestamp <= _utc(observed_at)
        ):
            timestamp_conditions.append({timestamp_field: raw_timestamp})
    return {
        "_id": doc_id,
        "$or": timestamp_conditions,
    }


def _write_applied(result: Any) -> bool:
    return bool(
        getattr(result, "matched_count", 0) > 0
        or getattr(result, "modified_count", 0) > 0
        or getattr(result, "upserted_id", None) is not None
    )


def _out_since(
    item: Mapping[str, Any],
    stock_state: str,
    observed_at: datetime,
    existing: Mapping[str, Any] | None,
) -> datetime | None:
    if stock_state != "out_of_stock":
        return None
    if (
        isinstance(existing, Mapping)
        and existing.get("stock_state") == "out_of_stock"
        and (since := _dt(existing.get("out_of_stock_since"))) is not None
    ):
        return since
    return _first_dt(*_status_dates(item).values(), observed_at)


def _status_dates(source: Mapping[str, Any]) -> dict[str, Any]:
    return {
        field: source.get(field)
        for field in (
            "paused_since",
            "status_started_at",
            "last_status_change_at",
            "status_observed_at",
        )
    }


def _formula_row_is_variation_scoped(row: Mapping[str, Any]) -> bool:
    return (
        _str(row.get("variation_id")) is not None or _str(row.get("identity_level")) == "variation"
    )


def _item_id(item: Mapping[str, Any]) -> str | None:
    return _str(item.get("_id") or item.get("id") or item.get("item_id"))


def _doc_id(seller_id: str, item_id: str) -> str:
    return f"{seller_id}:{item_id}"


def _attribute_sku(item: Mapping[str, Any]) -> str | None:
    attributes = item.get("attributes")
    if not isinstance(attributes, Sequence) or isinstance(attributes, (str, bytes, bytearray)):
        return None
    for attribute in attributes:
        if (
            not isinstance(attribute, Mapping)
            or str(attribute.get("id") or "").upper() != "SELLER_SKU"
        ):
            continue
        if sku := _str(
            attribute.get("value_name") or attribute.get("value") or attribute.get("name")
        ):
            return sku
    return None


def _str(value: Any) -> str | None:
    if value is None:
        return None
    return normalized if (normalized := str(value).strip()) else None


def _stock(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _money(value: Any) -> Decimal | None:
    if (
        value is None
        or isinstance(value, bool | Mapping)
        or (isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray))
    ):
        return None
    parsed = value.to_decimal() if isinstance(value, Decimal128) else value
    try:
        amount = parsed if isinstance(parsed, Decimal) else Decimal(str(parsed))
    except (InvalidOperation, ValueError):
        return None
    return amount if amount.is_finite() and amount >= 0 else None


def _first_dt(*values: Any) -> datetime:
    return _first_dt_or_none(*values) or datetime.now(UTC)


def _first_dt_or_none(*values: Any) -> datetime | None:
    for value in values:
        if (parsed := _dt(value)) is not None:
            return parsed
    return None


def _dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _utc(value)
    if isinstance(value, str):
        try:
            return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
