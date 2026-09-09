"""Persist acquired competition states without asserting historical coverage."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any


async def record_catalog_observation(db: Any, snapshot: dict[str, Any]) -> None:
    seller, identity, product = (
        snapshot.get("seller_id"),
        snapshot.get("item_id"),
        snapshot.get("catalog_product_id"),
    )
    observed, status, quantity = (
        snapshot.get("snapshot_at"),
        snapshot.get("buybox_status"),
        snapshot.get("available_quantity"),
    )
    if (
        not isinstance(seller, str)
        or not seller.isascii()
        or not seller.isdecimal()
        or any(
            not isinstance(value, str) or re.fullmatch(r"ML[A-Z][0-9]+", value) is None
            for value in (identity, product)
        )
        or not isinstance(observed, datetime)
        or observed.tzinfo is None
        or not isinstance(status, str)
        or not status.strip()
        or type(quantity) is not int
        or quantity < 0
    ):
        raise ValueError("catalog observation requires acquired identity, time, status and stock")
    observed = observed.astimezone(UTC).replace(microsecond=observed.microsecond // 1000 * 1000)
    key = hashlib.sha256(f"{seller}:{identity}:{observed.isoformat()}".encode()).hexdigest()
    document = {
        "_id": key,
        "seller_id": seller,
        "item_id": identity,
        "catalog_product_id": product,
        "observed_at": observed,
        "status": status.strip(),
        "available_quantity": quantity,
        "coverage_basis": "observed_only",
        "source": "meli_price_to_win",
        "schema_version": 1,
    }
    # Identical retries are no-ops. A conflicting state at the same source cut
    # raises DuplicateKeyError instead of silently rewriting the observation.
    await db["sheets_catalog_competition_observations"].update_one(
        document, {"$setOnInsert": document}, upsert=True
    )
