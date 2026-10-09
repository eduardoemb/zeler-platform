"""Append-only log of when publications start and stop being available.

`available` means the publication is `active` and has stock above zero, as the
legacy SheetSeller `variations_history` did. A publication with variations keeps
one series per variation; otherwise it keeps one series of its own. A row is
written only when a series has none yet or its availability changed, so the log
is silent while nothing changes and readers compute intervals between rows.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pymongo.errors import DuplicateKeyError

from zeler_platform_core.models import ItemAvailabilityTransition
from zeler_sheets.sheetseller_backfill import resolve_seller_sku, resolve_variation_sku

AVAILABILITY_TRANSITIONS_COLLECTION = "sheets_item_availability_transitions"
AVAILABILITY_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class _SeriesObservation:
    variation_id: str | None
    sku: str | None
    available_quantity: int


async def record_availability_observation(
    db: Any,
    item: Mapping[str, Any],
    *,
    seller_id: str,
    observed_at: datetime,
    source: str,
) -> int:
    """Append a row for each series whose availability changed; return how many."""
    item_id = str(item.get("_id") or item.get("id") or "").strip()
    status = str(item.get("status") or "").strip()
    if not item_id or not status:
        return 0
    observed_at = _utc_ms(observed_at)
    collection = db[AVAILABILITY_TRANSITIONS_COLLECTION]
    written = 0
    for series in _series_observations(item):
        available = status == "active" and series.available_quantity > 0
        scope = {
            "seller_id": str(seller_id),
            "item_id": item_id,
            "variation_id": series.variation_id,
        }
        latest = await collection.find(scope).sort([("observed_at", -1)]).to_list(length=1)
        if latest:
            latest_at = _utc_ms(latest[0]["observed_at"])
            if observed_at <= latest_at or bool(latest[0].get("available")) == available:
                continue
        row = ItemAvailabilityTransition.model_validate(
            {
                "_id": _row_id(
                    seller_id=str(seller_id),
                    item_id=item_id,
                    variation_id=series.variation_id,
                    observed_at=observed_at,
                ),
                **scope,
                "sku": series.sku,
                "available": available,
                "status": status,
                "available_quantity": series.available_quantity,
                "observed_at": observed_at,
                "source": source,
                "schema_version": AVAILABILITY_SCHEMA_VERSION,
            }
        )
        try:
            await collection.insert_one(row.model_dump(by_alias=True, mode="python"))
        except DuplicateKeyError:
            # The same observation was already written by a retry or a twin.
            continue
        written += 1
    return written


def _series_observations(item: Mapping[str, Any]) -> list[_SeriesObservation]:
    raw_variations = item.get("variations")
    variations = [
        variation
        for variation in (raw_variations if isinstance(raw_variations, list) else [])
        if isinstance(variation, dict) and _identity(variation.get("id")) is not None
    ]
    if variations:
        observations = []
        for variation in variations:
            quantity = _stock(variation.get("available_quantity"))
            if quantity is None:
                continue
            candidate = resolve_variation_sku(variation)
            observations.append(
                _SeriesObservation(
                    variation_id=_identity(variation.get("id")),
                    sku=None if candidate.ambiguous else candidate.sku,
                    available_quantity=quantity,
                )
            )
        return observations
    quantity = _stock(item.get("available_quantity"))
    if quantity is None:
        return []
    candidate = resolve_seller_sku(dict(item))
    return [
        _SeriesObservation(
            variation_id=None,
            sku=None if candidate.ambiguous else candidate.sku,
            available_quantity=quantity,
        )
    ]


def _row_id(
    *, seller_id: str, item_id: str, variation_id: str | None, observed_at: datetime
) -> str:
    return f"{seller_id}:{item_id}:{variation_id or '-'}:{observed_at.isoformat()}"


def _identity(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    normalized = str(value).strip()
    return normalized or None


def _stock(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        quantity = int(value)
    except (TypeError, ValueError):
        return None
    return quantity if quantity >= 0 else None


def _utc_ms(value: datetime) -> datetime:
    aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    # Mongo stores milliseconds; compare and key rows at the stored precision.
    return aware.replace(microsecond=aware.microsecond // 1000 * 1000)
