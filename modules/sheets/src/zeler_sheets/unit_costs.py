from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from bson.decimal128 import Decimal128

from zeler_sheets.formulas.output_normalization import NA_VALUE


@dataclass(frozen=True)
class UnitCostLookup:
    seller_id: str
    normalized_sku: str = ""
    item_id: str = ""
    variation_id: str = ""
    as_of: datetime | None = None
    currency: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "seller_id", str(self.seller_id).strip())
        object.__setattr__(self, "normalized_sku", normalize_sku(self.normalized_sku))
        object.__setattr__(self, "item_id", str(self.item_id or "").strip())
        object.__setattr__(self, "variation_id", str(self.variation_id or "").strip())
        if self.as_of is not None:
            object.__setattr__(self, "as_of", _optional_datetime(self.as_of))
        if self.currency is not None:
            object.__setattr__(self, "currency", str(self.currency).strip().upper() or None)


def resolve_unit_cost(docs: Sequence[Mapping[str, Any]], lookup: UnitCostLookup) -> Decimal | str:
    matches_by_rank: dict[int, list[Decimal]] = {}
    for doc in docs:
        rank = _match_rank(doc, lookup)
        value = _valid_unit_cost(doc, lookup) if rank else None
        if value is not None:
            matches_by_rank.setdefault(rank, []).append(value)
    if not matches_by_rank:
        return NA_VALUE
    values = matches_by_rank[max(matches_by_rank)]
    if len(values) != 1:
        return NA_VALUE
    return values[0]


def sheet_unit_cost_value(value: Decimal | str) -> int | float | str:
    if value == NA_VALUE or not isinstance(value, Decimal):
        return NA_VALUE
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def _valid_unit_cost(doc: Mapping[str, Any], lookup: UnitCostLookup) -> Decimal | None:
    currency = str(doc.get("currency") or "").strip().upper()
    if (
        str(doc.get("seller_id") or "").strip() != lookup.seller_id
        or str(doc.get("status") or "").strip() != "active"
        or not currency
        or (lookup.currency and currency != lookup.currency)
        or not _is_effective(doc, lookup.as_of)
    ):
        return None
    try:
        value = doc.get("unit_cost")
        if isinstance(value, Decimal128):
            parsed = value.to_decimal()
        elif isinstance(value, Decimal):
            parsed = value
        else:
            parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() and parsed >= 0 else None


def _match_rank(doc: Mapping[str, Any], lookup: UnitCostLookup) -> int:
    doc_sku = normalize_sku(doc.get("normalized_sku") or "")
    doc_item = str(doc.get("item_id") or "").strip()
    doc_variation = str(doc.get("variation_id") or "").strip()
    sku_matches = bool(doc_sku and lookup.normalized_sku and doc_sku == lookup.normalized_sku)
    item_matches = bool(doc_item and lookup.item_id and doc_item == lookup.item_id)
    variation_matches = bool(
        doc_variation and lookup.variation_id and doc_variation == lookup.variation_id
    )
    if doc_variation and not variation_matches:
        return 0
    if doc_item and not item_matches:
        return 0
    if doc_sku and not sku_matches:
        return 0
    return (
        5
        if variation_matches and item_matches and sku_matches
        else 4
        if variation_matches and item_matches
        else 3
        if item_matches and sku_matches
        else 2
        if item_matches
        else 1
        if sku_matches
        else 0
    )


def _is_effective(doc: Mapping[str, Any], as_of: datetime | None) -> bool:
    if as_of is None:
        as_of = datetime.now(UTC)
    effective_from = _optional_datetime(doc.get("effective_from"))
    effective_to = _optional_datetime(doc.get("effective_to"))
    if effective_from is not None and as_of < effective_from:
        return False
    return not (effective_to is not None and as_of >= effective_to)


def _optional_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def normalize_sku(sku: Any) -> str:
    return str(sku).strip().upper()
