"""Shared persisted promotional-price interpretation for formula consumers."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from bson.decimal128 import Decimal128

from zeler_sheets.formulas.output_normalization import NA_VALUE


def acquired_current_price(item: Mapping[str, Any]) -> Any:
    """Use a price only from the item's verified promotion acquisition cut."""
    synced = item.get("last_meli_sync_at")
    enrichment = item.get("enrichment_state")
    state = enrichment.get("current_promotion") if isinstance(enrichment, Mapping) else None
    currency = item.get("currency_id")
    if (
        not isinstance(synced, datetime)
        or not isinstance(state, Mapping)
        or state.get("source") != "/items/{id}/sale_price"
        or state.get("synced_at") != synced
        or not isinstance(currency, str)
        or not currency.strip()
    ):
        return None
    if state.get("status") == "authoritative_absent":
        value = item.get("price")
    elif state.get("status") == "trusted":
        projection = item.get("current_promotion")
        if (
            not isinstance(projection, Mapping)
            or projection.get("synced_at") != synced
            or projection.get("currency_id") != currency
            or not isinstance(projection.get("reference_at"), datetime)
            or non_negative_decimal(promo_price({"current": item})) is None
        ):
            return None
        value = projection.get("sale_amount")
    else:
        return None
    # Keep BSON numeric types: parseable strings are not a numeric snapshot.
    if not isinstance(value, (int, float, Decimal128)) or non_negative_decimal(value) is None:
        return None
    return value


def promo_price(row: Mapping[str, Any]) -> Any:
    current = row.get("current", {})
    if not isinstance(current, Mapping):
        return NA_VALUE
    enrichment = current.get("enrichment_state")
    state = enrichment.get("current_promotion") if isinstance(enrichment, Mapping) else None
    if isinstance(state, Mapping):
        if state.get("status") == "authoritative_absent":
            return NA_VALUE
        if state.get("status") != "trusted":
            return "DATA_UNAVAILABLE"
    invalid_value = "DATA_UNAVAILABLE" if isinstance(state, Mapping) else NA_VALUE
    projection = current.get("current_promotion")
    if not isinstance(projection, Mapping):
        return invalid_value
    if projection.get("source") != "/items/{id}/sale_price":
        return invalid_value
    if not str(projection.get("currency_id") or "").strip():
        return invalid_value
    if projection.get("reference_at") is None or projection.get("synced_at") is None:
        return invalid_value
    sale_amount = non_negative_decimal(projection.get("sale_amount"))
    regular_amount = non_negative_decimal(projection.get("regular_amount"))
    if sale_amount is None or regular_amount is None or sale_amount >= regular_amount:
        return invalid_value
    raw_sale_amount = projection.get("sale_amount")
    return (
        raw_sale_amount.to_decimal() if isinstance(raw_sale_amount, Decimal128) else raw_sale_amount
    )


def non_negative_decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, Decimal128):
        decimal_value = value.to_decimal()
    elif isinstance(value, Decimal):
        decimal_value = value
    elif isinstance(value, int):
        decimal_value = Decimal(value)
    elif isinstance(value, float):
        decimal_value = Decimal(str(value)) if math.isfinite(value) else Decimal("NaN")
    else:
        try:
            decimal_value = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
    return decimal_value if decimal_value.is_finite() and decimal_value >= 0 else None
