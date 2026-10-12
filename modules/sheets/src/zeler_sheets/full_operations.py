"""Store Full stock operations notified by Mercado Libre for ZELERDATA_RETIROS.

Mercado Libre notifies every Full stock operation (``fbm_stock_operations``)
with a resource ``/stock/fulfillment/operations/<id>``. The worker reads that
operation through the gateway and keeps only the withdrawal ones in
``sheets_full_operations``, the same collection the onboarding collector uses.
No withdrawal identifier exists in the API (``external_references`` comes empty
for withdrawals), so RETIROS pairs operations at read time.

Coverage is observed-only: every notification of the seller, of any type,
extends a ``full_withdrawals`` freshness marker whose ``date_from`` is the
earliest operation the stream showed. Before that instant nothing is known.
The stream changes only when an operation happens, so the marker proves where
coverage starts, not that the stream is alive; ``webhook_events`` keeps every
notification and is the recovery log (``zelerdata_full_withdrawals_backfill``).
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal

from pymongo.errors import DuplicateKeyError

FBM_STOCK_OPERATIONS_TOPIC = "fbm_stock_operations"
FBM_STOCK_OPERATIONS_EVENT_TYPE = "fbm_stock_operations.new"
FULL_OPERATIONS_COLLECTION = "sheets_full_operations"
FULL_OPERATION_NOTIFICATION_SOURCE = "meli_fbm_stock_operations"
FULL_WITHDRAWALS_READ_MODEL = "full_withdrawals"
FULL_WITHDRAWALS_MARKER_SOURCE = "zelerdata_fbm_stock_operations"
READ_MODEL_FRESHNESS_COLLECTION = "sheets_read_model_freshness"
OBSERVED_ONLY_BASIS = "observed_only"
WITHDRAWAL_RESERVATION = "WITHDRAWAL_RESERVATION"
WITHDRAWAL_CANCELATION = "WITHDRAWAL_CANCELATION"
WITHDRAWAL_DELIVERY = "WITHDRAWAL_DELIVERY"
WITHDRAWAL_REMOVAL = "WITHDRAWAL_REMOVAL"
WITHDRAWAL_DISCARDED = "WITHDRAWAL_DISCARDED"
WITHDRAWAL_TYPES = frozenset(
    {
        WITHDRAWAL_RESERVATION,
        WITHDRAWAL_CANCELATION,
        WITHDRAWAL_DELIVERY,
        WITHDRAWAL_REMOVAL,
        WITHDRAWAL_DISCARDED,
    }
)
_OPERATION_RESOURCE = re.compile(r"/stock/fulfillment/operations/([0-9]{1,20})")
_FETCH_TIMEOUT_SECONDS = 10

FullOperationOutcome = Literal["stored", "ignored", "seller_mismatch"]


def full_operation_id_from_resource(resource: str) -> str:
    match = _OPERATION_RESOURCE.fullmatch(resource)
    if match is None:
        raise ValueError("invalid Full stock operation resource")
    return match.group(1)


async def acquire_full_operation(
    *,
    db: Any,
    gateway: Any,
    seller_id: str,
    resource: str,
    now: datetime,
) -> FullOperationOutcome:
    """Read one notified operation through the gateway and record it."""
    operation_id = full_operation_id_from_resource(resource)
    if not seller_id.isascii() or not seller_id.isdecimal():
        raise ValueError("numeric seller required")
    async with asyncio.timeout(_FETCH_TIMEOUT_SECONDS):
        operation = await gateway.fetch_resource(
            seller_id=seller_id, path=f"/stock/fulfillment/operations/{operation_id}"
        )
    return await record_full_operation(
        db, seller_id=seller_id, operation_id=operation_id, operation=operation, now=now
    )


async def record_full_operation(
    db: Any,
    *,
    seller_id: str,
    operation_id: str,
    operation: Any,
    now: datetime,
) -> FullOperationOutcome:
    """Keep a withdrawal operation and extend the seller's observed coverage.

    An operation of another seller is neither stored nor counted as coverage.
    The operation is written before the marker, so the marker never claims an
    operation that is not stored.
    """
    if not isinstance(operation, Mapping) or _text(operation.get("id")) != operation_id:
        raise ValueError("Full stock operation identity mismatch")
    if _text(operation.get("seller_id")) != seller_id:
        return "seller_mismatch"
    kind = _text(operation.get("type")).upper()
    created = _timestamp(operation.get("date_created"))
    if not kind:
        raise ValueError("Full stock operation type is missing")
    observed = _utc(now)
    outcome: FullOperationOutcome = "ignored"
    if kind in WITHDRAWAL_TYPES:
        inventory_id = _text(operation.get("inventory_id"))
        if not inventory_id:
            raise ValueError("Full withdrawal operation inventory is missing")
        await db[FULL_OPERATIONS_COLLECTION].update_one(
            {"_id": f"{seller_id}:{operation_id}", "seller_id": seller_id},
            {
                "$set": {
                    "operation_id": operation_id,
                    "inventory_id": inventory_id,
                    "type": kind,
                    "date_created": created,
                    "detail": operation.get("detail"),
                    "result": operation.get("result"),
                    "external_references": operation.get("external_references"),
                    "source": FULL_OPERATION_NOTIFICATION_SOURCE,
                    "synced_at": observed,
                    "schema_version": 1,
                }
            },
            upsert=True,
        )
        outcome = "stored"
    await _observe_coverage(db, seller_id=seller_id, created=created, now=observed)
    return outcome


async def _observe_coverage(db: Any, *, seller_id: str, created: datetime, now: datetime) -> None:
    markers = db[READ_MODEL_FRESHNESS_COLLECTION]
    marker_id = f"{seller_id}:{FULL_WITHDRAWALS_READ_MODEL}"
    own = {
        "_id": marker_id,
        "seller_id": seller_id,
        "read_model": FULL_WITHDRAWALS_READ_MODEL,
        "source": FULL_WITHDRAWALS_MARKER_SOURCE,
    }
    for _ in range(2):
        result = await markers.update_one(
            own,
            {
                "$min": {"date_from": created},
                "$max": {"fresh_until": now, "last_event_synced_at": now},
                "$set": {
                    "state": "fresh",
                    "coverage_basis": OBSERVED_ONLY_BASIS,
                    "updated_at": now,
                },
            },
        )
        if result.matched_count:
            return
        # No marker yet, or one written by another owner: observed coverage
        # starts over from this operation. A concurrent first writer wins the
        # insert and this one merges into it on the next pass.
        try:
            await markers.replace_one(
                {"_id": marker_id, "source": {"$ne": FULL_WITHDRAWALS_MARKER_SOURCE}},
                {
                    **own,
                    "state": "fresh",
                    "date_from": created,
                    "fresh_until": now,
                    "reconciled_until": None,
                    "last_event_synced_at": now,
                    "valid_until": None,
                    "coverage_basis": OBSERVED_ONLY_BASIS,
                    "updated_at": now,
                    "schema_version": 1,
                },
                upsert=True,
            )
            return
        except DuplicateKeyError:
            continue
    raise RuntimeError("Full withdrawals coverage marker could not be written")


def _text(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return ""
    return str(value).strip()


def _timestamp(value: Any) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Full stock operation date is invalid") from exc
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("Full stock operation date is invalid")
    return value.astimezone(UTC)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
