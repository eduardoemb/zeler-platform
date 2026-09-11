"""Renew heartbeat freshness markers for observed-only read models.

Four read models are *observed history*: shipments, price history, stockout
snapshots and item status states. Their truth is "what the platform actually
observed", not "everything the source had in a range", so no source
reconciliation can certify them. Demanding a reconciled interval left complete
formulas permanently unavailable even though the data was present and was being
refreshed.

The refresh loop renews a heartbeat marker for each of them. The marker
certifies that the loop audited the model at ``now``, records the newest and
oldest observation it saw, and expires after two refresh cycles. If the loop
stops, the marker expires and the formulas fail closed again. A model with no
observation, or whose newest observation is older than the daily sweep horizon,
is never certified, so stale data cannot be presented as current.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from zeler_sheets.formulas.refresh import MARKER_VALIDITY

READ_MODEL_FRESHNESS_COLLECTION = "sheets_read_model_freshness"
OBSERVED_ONLY_BASIS = "observed_only"
OBSERVED_MARKER_SOURCE = "zelerdata_observed_read_model"
PRODUCTIVE_MARKER_STATES = frozenset({"fresh", "reconciled"})
# Matches the daily sweep horizon. It is a fail-closed backstop against
# certifying abandoned data, not a freshness SLA: the refresh loop renews these
# observations far more often while acquisition is alive.
OBSERVED_MARKER_MAX_AGE = timedelta(days=7)
# Read model -> collection and the field that records when it was observed.
OBSERVED_READ_MODEL_SOURCES: Mapping[str, tuple[str, str]] = {
    "shipments": ("shipments", "formula_observed_at"),
    "price_history_snapshots": ("sheets_price_history_snapshots", "snapshot_at"),
    "stockout_snapshots": ("sheets_stockout_snapshots", "observed_at"),
    "item_status_states": ("item_status_states", "last_observed_at"),
}


async def publish_observed_read_model_markers(
    db: Any,
    seller_id: str,
    *,
    now_fn: Callable[[], datetime] | None = None,
) -> tuple[str, ...]:
    """Renew observed heartbeat markers; return the read models published.

    A marker that is already productive for a "now" read is left untouched, so a
    reconciled source claim is never downgraded by the heartbeat.
    """
    seller = str(seller_id)
    now = _utc((now_fn or (lambda: datetime.now(UTC)))())
    collection = db[READ_MODEL_FRESHNESS_COLLECTION]
    published: list[str] = []
    for read_model, (collection_name, timestamp_field) in sorted(
        OBSERVED_READ_MODEL_SOURCES.items()
    ):
        marker_id = f"{seller}:{read_model}"
        existing = await collection.find_one(
            {"_id": marker_id, "seller_id": seller, "read_model": read_model}
        )
        if _marker_already_productive(existing, now=now):
            continue
        source = db[collection_name]
        newest = await _edge_observation(
            source, seller_id=seller, field=timestamp_field, newest=True
        )
        if newest is None or now - newest > OBSERVED_MARKER_MAX_AGE:
            continue
        oldest = await _edge_observation(
            source, seller_id=seller, field=timestamp_field, newest=False
        )
        marker = {
            "_id": marker_id,
            "seller_id": seller,
            "read_model": read_model,
            "state": "fresh",
            "date_from": oldest or newest,
            # Coverage is proven up to the audit instant. The reader extends a
            # still-open claim by one validity window, so a read that starts
            # right after the audit is served without overstating coverage.
            "fresh_until": now,
            "reconciled_until": None,
            "last_event_synced_at": newest,
            "valid_until": now + MARKER_VALIDITY,
            "coverage_basis": OBSERVED_ONLY_BASIS,
            "source": OBSERVED_MARKER_SOURCE,
            "updated_at": now,
            "schema_version": 1,
        }
        await collection.update_one(
            {"_id": marker_id, "seller_id": seller, "read_model": read_model},
            {"$set": marker},
            upsert=True,
        )
        published.append(read_model)
    return tuple(published)


async def _edge_observation(
    collection: Any,
    *,
    seller_id: str,
    field: str,
    newest: bool,
) -> datetime | None:
    rows = (
        await collection.find({"seller_id": seller_id, field: {"$exists": True}}, {field: 1})
        .sort(field, -1 if newest else 1)
        .limit(1)
        .to_list(1)
    )
    if not rows:
        return None
    return _utc_or_none(rows[0].get(field))


def _utc_or_none(value: Any) -> datetime | None:
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


def _marker_already_productive(marker: Any, *, now: datetime) -> bool:
    """Whether an existing marker already certifies a live read.

    Mirrors the reader's productive gate: a reconciled source claim must not be
    downgraded by the observed heartbeat.
    """
    if not isinstance(marker, Mapping):
        return False
    if str(marker.get("state") or "").strip().casefold() not in PRODUCTIVE_MARKER_STATES:
        return False
    fresh_until = _utc_or_none(marker.get("fresh_until"))
    if fresh_until is None or fresh_until < now:
        return False
    valid_until = _utc_or_none(marker.get("valid_until"))
    return valid_until is None or valid_until > now
