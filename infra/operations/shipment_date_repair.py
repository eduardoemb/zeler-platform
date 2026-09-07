"""Bounded date-only repair; callers must back up originals in the approved runtime."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern


async def repair_shipment_dates(db: Any, *, seller_id: str, originals: list[dict[str, Any]]) -> int:
    """Convert backed-up ISO dates without changing instants or unrelated fields.

    No connection discovery or CLI: production callers must execute inside the
    approved VM/container. A mismatch aborts the entire bounded transaction.
    """
    if not seller_id or not 1 <= len(originals) <= 100:
        raise ValueError("a seller and 1 to 100 backed-up shipments are required")
    identities: set[str] = set()
    plans = []
    for original in originals:
        if set(original) != {"_id", "seller_id", "date_created", "last_updated"}:
            raise ValueError("repair backup must contain only identity and date fields")
        identity = original["_id"]
        if not isinstance(identity, str) or not identity or identity in identities:
            raise ValueError("repair identities must be distinct nonempty strings")
        if original["seller_id"] != seller_id:
            raise ValueError("repair seller scope mismatch")
        identities.add(identity)
        converted = {}
        for field in ("date_created", "last_updated"):
            value = original[field]
            try:
                parsed = datetime.fromisoformat(value) if isinstance(value, str) else None
            except ValueError:
                parsed = None
            if parsed is None or parsed.tzinfo is None or parsed.microsecond % 1000:
                raise ValueError("repair requires timezone-aware millisecond ISO dates")
            converted[field] = parsed.astimezone(UTC)
        plans.append((original, converted))
    async with (
        await db.client.start_session() as session,
        session.start_transaction(
            read_concern=ReadConcern("snapshot"), write_concern=WriteConcern("majority")
        ),
    ):
        for original, converted in plans:
            result = await db.shipments.update_one(
                original,
                {"$set": converted},
                session=session,
                bypass_document_validation=False,
            )
            if result.matched_count != 1:
                raise RuntimeError("shipment changed since backup; repair aborted")
    return len(plans)
