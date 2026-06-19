from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, cast

ITEM_HISTORY_PROJECTION_COLLECTION = "item_history_projection"
CATALOG_CHANGE_EVENTS_COLLECTION = "meli_item_events"
WITHDRAWAL_RECORDS_COLLECTION = "withdrawal_records"
STOCK_TIME_METRICS_COLLECTION = "sheets_stock_time_metrics"
CATALOG_TIME_METRICS_COLLECTION = "sheets_catalog_time_metrics"
FULL_WITHDRAWALS_COLLECTION = "sheets_full_withdrawals"

READ_MODEL_SCHEMA_VERSION = 1
LEGACY_HISTORY_IMPORT_SOURCE = "legacy_history_import"
LEGACY_IMPORTED_BASIS = "legacy_imported"
OBSERVED_ONLY_BASIS = "observed_only"
STOCK_TIME_METRICS = "stock_time_metrics"
CATALOG_TIME_METRICS = "catalog_time_metrics"
FULL_WITHDRAWALS = "full_withdrawals"
CATALOG_WINNING_STATES = frozenset({"ganando", "winning"})
CATALOG_AVAILABLE_STATES = frozenset({"ganando", "winning", "perdiendo", "losing"})
STOCK_ACTIVE_STATES = frozenset({"active", "activa", "con stock", "in stock", "in_stock"})


@dataclass(frozen=True)
class SourceGatedReadModelImportSummary:
    seller_id: str
    dry_run: bool
    date_from: datetime
    date_to: datetime
    stock_time_metrics_planned: int = 0
    stock_time_metrics_updated: int = 0
    catalog_time_metrics_planned: int = 0
    catalog_time_metrics_updated: int = 0
    full_withdrawals_planned: int = 0
    full_withdrawals_updated: int = 0
    stock_time_item_ids: tuple[str, ...] = ()
    catalog_time_item_ids: tuple[str, ...] = ()
    full_withdrawal_ids: tuple[str, ...] = ()
    coverage_basis: Mapping[str, str] = field(default_factory=dict)
    source_inventory_counts: Mapping[str, int] = field(default_factory=dict)
    coverage_complete: Mapping[str, bool] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["coverage_basis"] = dict(self.coverage_basis)
        payload["source_inventory_counts"] = dict(self.source_inventory_counts)
        payload["coverage_complete"] = dict(self.coverage_complete)
        return payload


@dataclass(frozen=True)
class _BuildResult:
    documents: list[dict[str, Any]]
    source_inventory_count: int
    coverage_complete: bool


async def run_source_gated_read_model_import(
    *,
    db: Any,
    seller_id: str,
    date_from: Any,
    date_to: Any,
    dry_run: bool = True,
    now: datetime | None = None,
    max_items: int | None = None,
) -> SourceGatedReadModelImportSummary:
    del now
    seller = str(seller_id).strip()
    interval = _ReadInterval.from_bounds(date_from, date_to)
    account_ids = await _seller_account_ids(db, seller_id=seller)
    projections = await _seller_scoped_documents(
        db[ITEM_HISTORY_PROJECTION_COLLECTION],
        seller_id=seller,
        account_ids=account_ids,
        limit=max_items,
    )
    catalog_change_events = await _seller_scoped_documents(
        db[CATALOG_CHANGE_EVENTS_COLLECTION],
        seller_id=seller,
        account_ids=account_ids,
        limit=None,
        extra_filter={"event_type": "catalog_change"},
    )
    withdrawal_records = await _seller_scoped_documents(
        db[WITHDRAWAL_RECORDS_COLLECTION],
        seller_id=seller,
        account_ids=account_ids,
        limit=max_items,
    )

    stock_result = _bounded_result(
        _stock_time_metric_documents(seller, projections, interval=interval),
        max_documents=max_items,
    )
    catalog_result = _bounded_result(
        _catalog_time_metric_documents(
            seller,
            projections,
            interval=interval,
            catalog_changes_by_item=_catalog_change_events_by_item(catalog_change_events),
        ),
        max_documents=max_items,
    )
    withdrawal_result = _bounded_result(
        _full_withdrawal_documents(seller, withdrawal_records, interval=interval),
        max_documents=max_items,
    )
    stock_docs = stock_result.documents
    catalog_docs = catalog_result.documents
    withdrawal_docs = withdrawal_result.documents

    stock_updated = await _write_documents(
        db[STOCK_TIME_METRICS_COLLECTION], stock_docs, dry_run=dry_run
    )
    catalog_updated = await _write_documents(
        db[CATALOG_TIME_METRICS_COLLECTION], catalog_docs, dry_run=dry_run
    )
    withdrawal_updated = await _write_documents(
        db[FULL_WITHDRAWALS_COLLECTION], withdrawal_docs, dry_run=dry_run
    )

    return SourceGatedReadModelImportSummary(
        seller_id=seller,
        dry_run=dry_run,
        date_from=interval.start,
        date_to=interval.end,
        stock_time_metrics_planned=len(stock_docs),
        stock_time_metrics_updated=stock_updated,
        catalog_time_metrics_planned=len(catalog_docs),
        catalog_time_metrics_updated=catalog_updated,
        full_withdrawals_planned=len(withdrawal_docs),
        full_withdrawals_updated=withdrawal_updated,
        stock_time_item_ids=tuple(dict.fromkeys(doc["item_id"] for doc in stock_docs)),
        catalog_time_item_ids=tuple(dict.fromkeys(doc["item_id"] for doc in catalog_docs)),
        full_withdrawal_ids=tuple(dict.fromkeys(doc["_id"] for doc in withdrawal_docs)),
        coverage_basis={
            STOCK_TIME_METRICS: _basis_for_result(stock_result),
            CATALOG_TIME_METRICS: _basis_for_result(catalog_result),
            FULL_WITHDRAWALS: _basis_for_result(withdrawal_result),
        },
        source_inventory_counts={
            STOCK_TIME_METRICS: stock_result.source_inventory_count,
            CATALOG_TIME_METRICS: catalog_result.source_inventory_count,
            FULL_WITHDRAWALS: withdrawal_result.source_inventory_count,
        },
        coverage_complete={
            STOCK_TIME_METRICS: stock_result.coverage_complete,
            CATALOG_TIME_METRICS: catalog_result.coverage_complete,
            FULL_WITHDRAWALS: withdrawal_result.coverage_complete,
        },
    )


@dataclass(frozen=True)
class _ReadInterval:
    start: datetime
    end: datetime

    @classmethod
    def from_bounds(cls, date_from: Any, date_to: Any) -> _ReadInterval:
        start = _coerce_utc_datetime(date_from)
        end = _coerce_utc_datetime(date_to)
        if end <= start:
            raise ValueError("date_to must be after date_from")
        return cls(start=start, end=end)

    @property
    def total_hours(self) -> Decimal:
        return _hours_between(self.start, self.end)


@dataclass(frozen=True)
class _HistorySegment:
    state: str
    start: datetime
    end: datetime


async def _seller_scoped_documents(
    collection: Any,
    *,
    seller_id: str,
    account_ids: Sequence[Any],
    limit: int | None,
    extra_filter: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    base_filter = dict(extra_filter or {})
    documents: list[dict[str, Any]] = []
    documents.extend(await _all(collection, {**base_filter, "seller_id": seller_id}, limit=limit))
    numeric_seller_id = _int(seller_id)
    if numeric_seller_id is not None:
        documents.extend(
            await _all(collection, {**base_filter, "seller_id": numeric_seller_id}, limit=limit)
        )
    for account_id in account_ids:
        documents.extend(
            await _all(collection, {**base_filter, "account_id": account_id}, limit=limit)
        )
        if (account_id_str := _str(account_id)) is not None:
            documents.extend(
                await _all(collection, {**base_filter, "account_id": account_id_str}, limit=limit)
            )
    return _limit(_dedupe_documents(documents), limit)


async def _seller_account_ids(db: Any, *, seller_id: str) -> tuple[Any, ...]:
    account_ids: list[Any] = []
    for seller_key in (seller_id, _int(seller_id)):
        if seller_key is None:
            continue
        for account in await _all(db["meli_accounts"], {"seller_id": seller_key}, limit=None):
            for field_name in ("account_id", "_id", "meli_user_id"):
                if (account_id := account.get(field_name)) is not None:
                    account_ids.append(account_id)
    return tuple(dict.fromkeys(account_ids))


def _dedupe_documents(documents: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for index, document in enumerate(documents):
        dedupe_key = _str(document.get("_id")) or f"index:{index}"
        deduped.setdefault(dedupe_key, document)
    return list(deduped.values())


def _limit(documents: list[dict[str, Any]], limit: int | None) -> list[dict[str, Any]]:
    return documents if limit is None else documents[:limit]


def _stock_time_metric_documents(
    seller_id: str, projections: Sequence[Mapping[str, Any]], *, interval: _ReadInterval
) -> _BuildResult:
    documents: list[dict[str, Any]] = []
    source_inventory_count = 0
    incomplete_source_count = 0
    for projection in projections:
        item_id = _item_id(projection)
        if item_id is None:
            continue
        variations_history = projection.get("variations_history")
        if not isinstance(variations_history, Mapping) or not variations_history:
            source_inventory_count += 1
            incomplete_source_count += 1
            continue
        for sku, raw_history in sorted(variations_history.items(), key=lambda item: str(item[0])):
            normalized_sku = _str(sku)
            source_inventory_count += 1
            history = _history_entries(raw_history)
            segments = _covered_segments(history, interval=interval)
            if normalized_sku is None or segments is None:
                incomplete_source_count += 1
                continue
            active_hours = sum(
                (
                    _hours_between(segment.start, segment.end)
                    for segment in segments
                    if _stock_active(segment.state)
                ),
                Decimal("0"),
            )
            document = {
                "_id": _stock_metric_id(seller_id, item_id, normalized_sku, interval),
                "seller_id": seller_id,
                "item_id": item_id,
                "sku": normalized_sku,
                "normalized_sku": normalized_sku.upper(),
                "title": _str(projection.get("title")),
                "url": _str(projection.get("permalink") or projection.get("url")),
                "date_from": interval.start,
                "date_to": interval.end,
                "active_stock_hours": _decimal_hours(active_hours),
                "total_hours": _decimal_hours(interval.total_hours),
                "active_stock_percent": _percent(active_hours, interval.total_hours),
                "weeks": _week_buckets(segments, interval=interval),
                "source": LEGACY_HISTORY_IMPORT_SOURCE,
                "history_basis": LEGACY_IMPORTED_BASIS,
                "coverage_basis": LEGACY_IMPORTED_BASIS,
                "schema_version": READ_MODEL_SCHEMA_VERSION,
            }
            documents.append(document)
    return _BuildResult(
        documents=documents,
        source_inventory_count=source_inventory_count,
        coverage_complete=source_inventory_count > 0
        and incomplete_source_count == 0
        and len(documents) == source_inventory_count,
    )


def _catalog_time_metric_documents(
    seller_id: str,
    projections: Sequence[Mapping[str, Any]],
    *,
    interval: _ReadInterval,
    catalog_changes_by_item: Mapping[str, Sequence[Mapping[str, Any]]],
) -> _BuildResult:
    documents: list[dict[str, Any]] = []
    source_inventory_count = 0
    incomplete_source_count = 0
    projection_item_ids: set[str] = set()
    for projection in projections:
        item_id = _item_id(projection)
        if item_id is None:
            continue
        projection_item_ids.add(item_id)
        source_inventory_count += 1
        history = _catalog_history_entries(projection, catalog_changes_by_item)
        segments = _covered_segments(history, interval=interval)
        if segments is None:
            incomplete_source_count += 1
            continue
        documents.append(
            _catalog_metric_document(seller_id, item_id, projection, segments, interval)
        )
    for item_id, event_history in sorted(catalog_changes_by_item.items()):
        if item_id in projection_item_ids:
            continue
        source_inventory_count += 1
        segments = _covered_segments(event_history, interval=interval)
        if segments is None:
            incomplete_source_count += 1
            continue
        documents.append(_catalog_metric_document(seller_id, item_id, {}, segments, interval))
    return _BuildResult(
        documents=documents,
        source_inventory_count=source_inventory_count,
        coverage_complete=source_inventory_count > 0
        and incomplete_source_count == 0
        and len(documents) == source_inventory_count,
    )


def _full_withdrawal_documents(
    seller_id: str, records: Sequence[Mapping[str, Any]], *, interval: _ReadInterval
) -> _BuildResult:
    documents: list[dict[str, Any]] = []
    source_inventory_count = 0
    incomplete_source_count = 0
    for record in records:
        withdrawal_id = _str(record.get("withdrawal_id") or record.get("id"))
        for package_index, package in enumerate(_packages(record), start=1):
            detail_id = _str(
                package.get("withdrawal_detail_id")
                or package.get("detail_id")
                or package.get("bulto_id")
                or package.get("package_id")
                or package_index
            )
            created_at = _first_datetime(package.get("date_created"), record.get("date_created"))
            if created_at is None:
                source_inventory_count += 1
                incomplete_source_count += 1
                continue
            if not (interval.start <= created_at < interval.end):
                continue
            products = _products(package)
            if not products:
                source_inventory_count += 1
                incomplete_source_count += 1
                continue
            for product in products:
                source_inventory_count += 1
                identity = _str(
                    product.get("inventory_id") or product.get("item_id") or product.get("sku")
                )
                if withdrawal_id is None or detail_id is None or identity is None:
                    incomplete_source_count += 1
                    continue
                documents.append(
                    {
                        "_id": f"{seller_id}:{withdrawal_id}:{detail_id}:{identity}",
                        "seller_id": seller_id,
                        "withdrawal_id": withdrawal_id,
                        "withdrawal_detail_id": detail_id,
                        "inventory_id": _str(product.get("inventory_id")),
                        "item_id": _str(product.get("item_id")),
                        "sku": _str(product.get("sku")),
                        "title": _str(product.get("title")),
                        "requested_quantity": _int(product.get("quantity") or product.get("qty")),
                        "created_at": created_at,
                        "delivered_at": _first_datetime(
                            product.get("date_delivery"), package.get("date_delivery")
                        ),
                        "source": LEGACY_HISTORY_IMPORT_SOURCE,
                        "history_basis": LEGACY_IMPORTED_BASIS,
                        "coverage_basis": LEGACY_IMPORTED_BASIS,
                        "schema_version": READ_MODEL_SCHEMA_VERSION,
                    }
                )
    return _BuildResult(
        documents=documents,
        source_inventory_count=source_inventory_count,
        coverage_complete=source_inventory_count > 0
        and incomplete_source_count == 0
        and len(documents) == source_inventory_count,
    )


def _catalog_metric_document(
    seller_id: str,
    item_id: str,
    source: Mapping[str, Any],
    segments: Sequence[_HistorySegment],
    interval: _ReadInterval,
) -> dict[str, Any]:
    winning_hours = sum(
        (
            _hours_between(segment.start, segment.end)
            for segment in segments
            if _catalog_winning(segment.state)
        ),
        Decimal("0"),
    )
    available_hours = sum(
        (
            _hours_between(segment.start, segment.end)
            for segment in segments
            if _catalog_available(segment.state)
        ),
        Decimal("0"),
    )
    return {
        "_id": _item_metric_id(seller_id, item_id, interval),
        "seller_id": seller_id,
        "item_id": item_id,
        "title": _str(source.get("title")),
        "url": _str(source.get("permalink") or source.get("url")),
        "date_from": interval.start,
        "date_to": interval.end,
        "winning_hours": _decimal_hours(winning_hours),
        "available_hours": _decimal_hours(available_hours),
        "winning_percent": _percent(winning_hours, available_hours),
        "source": LEGACY_HISTORY_IMPORT_SOURCE,
        "history_basis": LEGACY_IMPORTED_BASIS,
        "coverage_basis": LEGACY_IMPORTED_BASIS,
        "schema_version": READ_MODEL_SCHEMA_VERSION,
    }


def _catalog_change_events_by_item(
    events: Sequence[Mapping[str, Any]],
) -> dict[str, tuple[Mapping[str, Any], ...]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for event in events:
        if (item_id := _str(event.get("item_id") or event.get("id"))) is None:
            continue
        grouped.setdefault(item_id, []).extend(_catalog_change_entries([event]))
    return {item_id: tuple(entries) for item_id, entries in grouped.items()}


def _catalog_history_entries(
    projection: Mapping[str, Any],
    catalog_changes_by_item: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[Mapping[str, Any]]:
    catalog_history = _history_entries(projection.get("catalog_history"))
    if catalog_history:
        return catalog_history
    catalog_change = _catalog_change_entries(
        projection.get("catalog_change") or projection.get("catalog_changes")
    )
    if catalog_change:
        return catalog_change
    item_id = _item_id(projection)
    if item_id is None:
        return []
    return list(catalog_changes_by_item.get(item_id, ()))


def _catalog_change_entries(raw_history: Any) -> list[Mapping[str, Any]]:
    if not isinstance(raw_history, Sequence) or isinstance(raw_history, (str, bytes, bytearray)):
        return []
    entries: list[Mapping[str, Any]] = []
    for raw_entry in raw_history:
        if not isinstance(raw_entry, Mapping):
            continue
        data = raw_entry.get("data")
        if not isinstance(data, Mapping):
            data = {}
        state = _str(
            raw_entry.get("status2")
            or raw_entry.get("status")
            or raw_entry.get("new_value")
            or data.get("new_value")
            or data.get("status")
        )
        changed_at = (
            raw_entry.get("changed_at")
            or raw_entry.get("timestamp")
            or data.get("changed_at")
            or data.get("timestamp")
        )
        if state is None or changed_at is None:
            continue
        entries.append({"status2": state, "changed_at": changed_at})
    return entries


def _covered_segments(
    history: Sequence[Mapping[str, Any]], *, interval: _ReadInterval
) -> list[_HistorySegment] | None:
    normalized = sorted(
        (
            (changed_at, state)
            for entry in history
            if (changed_at := _first_datetime(entry.get("changed_at"), entry.get("timestamp")))
            is not None
            and (
                state := _str(entry.get("status2") or entry.get("status") or entry.get("new_value"))
            )
            is not None
        ),
        key=lambda item: item[0],
    )
    if not normalized:
        return None
    current_state: str | None = None
    current_start = interval.start
    segments: list[_HistorySegment] = []
    for changed_at, state in normalized:
        if changed_at <= interval.start:
            current_state = state
            continue
        if changed_at >= interval.end:
            break
        if current_state is None:
            return None
        if changed_at > current_start:
            segments.append(_HistorySegment(current_state, current_start, changed_at))
        current_state = state
        current_start = changed_at
    if current_state is None:
        return None
    if current_start < interval.end:
        segments.append(_HistorySegment(current_state, current_start, interval.end))
    return segments


def _week_buckets(
    segments: Sequence[_HistorySegment], *, interval: _ReadInterval
) -> list[dict[str, Any]]:
    buckets: list[dict[str, Any]] = []
    bucket_start = interval.start
    while bucket_start < interval.end:
        bucket_end = min(bucket_start + timedelta(days=7), interval.end)
        has_stock = any(
            _stock_active(segment.state)
            and segment.start < bucket_end
            and segment.end > bucket_start
            for segment in segments
        )
        last_day = (bucket_end - timedelta(microseconds=1)).day
        buckets.append({"start_day": bucket_start.day, "end_day": last_day, "has_stock": has_stock})
        bucket_start = bucket_end
    return buckets


async def _write_documents(
    collection: Any, documents: Sequence[dict[str, Any]], *, dry_run: bool
) -> int:
    if dry_run:
        return 0
    updated = 0
    for document in documents:
        replacement = _bson_safe_document(document)
        result = await collection.replace_one({"_id": replacement["_id"]}, replacement, upsert=True)
        updated += int(_write_applied(result))
    return updated


def _bson_safe_document(document: Mapping[str, Any]) -> dict[str, Any]:
    return {key: _bson_safe_value(value) for key, value in document.items()}


def _bson_safe_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return _decimal_to_bson_number(value)
    if isinstance(value, Mapping):
        return {key: _bson_safe_value(nested_value) for key, nested_value in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_bson_safe_value(item) for item in value]
    return value


def _decimal_to_bson_number(value: Decimal) -> int | float:
    if not value.is_finite():
        msg = "Decimal values must be finite before BSON writes"
        raise ValueError(msg)
    integral_value = value.to_integral_value()
    if value == integral_value:
        return int(integral_value)
    return float(value)


def _basis_for_result(result: _BuildResult) -> str:
    return LEGACY_IMPORTED_BASIS if result.coverage_complete else OBSERVED_ONLY_BASIS


def _bounded_result(result: _BuildResult, *, max_documents: int | None) -> _BuildResult:
    if max_documents is None:
        return result
    return _BuildResult(
        documents=_limit(result.documents, max_documents),
        source_inventory_count=result.source_inventory_count,
        coverage_complete=False,
    )


def _packages(record: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = record.get("bultos") or record.get("packages")
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        return [package for package in raw if isinstance(package, Mapping)]
    return [record]


def _products(package: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = package.get("products") or package.get("items")
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        return [product for product in raw if isinstance(product, Mapping)]
    return [package]


def _history_entries(raw_history: Any) -> list[Mapping[str, Any]]:
    if isinstance(raw_history, Sequence) and not isinstance(raw_history, (str, bytes, bytearray)):
        return [entry for entry in raw_history if isinstance(entry, Mapping)]
    return []


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


def _stock_active(state: str) -> bool:
    return _state_key(state) in STOCK_ACTIVE_STATES


def _catalog_winning(state: str) -> bool:
    return _state_key(state) in CATALOG_WINNING_STATES


def _catalog_available(state: str) -> bool:
    return _state_key(state) in CATALOG_AVAILABLE_STATES


def _state_key(state: str) -> str:
    return state.strip().casefold().replace("_", " ")


def _stock_metric_id(seller_id: str, item_id: str, sku: str, interval: _ReadInterval) -> str:
    return f"{seller_id}:{item_id}:{sku}:{_date_key(interval.start)}:{_date_key(interval.end)}"


def _item_metric_id(seller_id: str, item_id: str, interval: _ReadInterval) -> str:
    return f"{seller_id}:{item_id}:{_date_key(interval.start)}:{_date_key(interval.end)}"


def _date_key(value: datetime) -> str:
    return value.astimezone(UTC).date().isoformat()


def _item_id(document: Mapping[str, Any]) -> str | None:
    return _str(document.get("item_id") or document.get("id") or document.get("_id"))


def _str(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _first_datetime(*values: Any) -> datetime | None:
    for value in values:
        if (parsed := _maybe_datetime(value)) is not None:
            return parsed
    return None


def _coerce_utc_datetime(value: Any) -> datetime:
    if (parsed := _maybe_datetime(value)) is None:
        msg = "expected date, datetime, or ISO date string"
        raise TypeError(msg)
    return parsed


def _maybe_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _utc(value)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return _utc(parsed)
    return None


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _hours_between(start: datetime, end: datetime) -> Decimal:
    seconds = Decimal(str(max((end - start).total_seconds(), 0)))
    return _decimal_hours(seconds / Decimal("3600"))


def _decimal_hours(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001")).normalize()


def _percent(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator <= 0:
        return Decimal("0.0000")
    try:
        return ((numerator / denominator) * Decimal("100")).quantize(Decimal("0.0001"))
    except (InvalidOperation, ZeroDivisionError):
        return Decimal("0.0000")


def _write_applied(result: Any) -> bool:
    return bool(
        getattr(result, "matched_count", 0) > 0
        or getattr(result, "modified_count", 0) > 0
        or getattr(result, "upserted_id", None) is not None
    )
