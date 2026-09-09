"""Persist acquired competition states without asserting historical coverage."""

from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import UTC, datetime
from typing import Any


def _event_observation_key(seller: str, identity: str, event_key: str) -> str:
    return hashlib.sha256(f"event:{seller}:{identity}:{event_key}".encode()).hexdigest()


async def acquire_catalog_event(
    *, db: Any, gateway: Any, seller_id: str, resource: str, event_key: str
) -> None:
    match = re.fullmatch(r"/items/(ML[A-Z][0-9]+)/price_to_win(?:\?version=v2)?", resource)
    if match is None or not event_key or not seller_id.isascii() or not seller_id.isdecimal():
        raise ValueError("invalid catalog competition event identity")
    identity = match.group(1)
    key = _event_observation_key(seller_id, identity, event_key)
    if (
        await db["sheets_catalog_competition_observations"].find_one(
            {"_id": key, "seller_id": seller_id, "item_id": identity}
        )
        is not None
    ):
        return
    observed = datetime.now(UTC)
    async with asyncio.timeout(10):
        item = await gateway.fetch_resource(seller_id=seller_id, path=f"/items/{identity}")
    if (
        not isinstance(item, dict)
        or item.get("id") != identity
        or str(item.get("seller_id")) != seller_id
    ):
        raise ValueError("catalog notification publication is not owned")
    async with asyncio.timeout(10):
        competition = await gateway.fetch_resource(
            seller_id=seller_id, path=f"/items/{identity}/price_to_win?version=v2"
        )
    if (
        not isinstance(competition, dict)
        or competition.get("item_id") != identity
        or competition.get("catalog_product_id") != item.get("catalog_product_id")
    ):
        raise ValueError("catalog notification product identity changed")
    await record_catalog_observation(
        db,
        {
            "seller_id": seller_id,
            "item_id": identity,
            "catalog_product_id": item.get("catalog_product_id"),
            "available_quantity": item.get("available_quantity"),
            "buybox_status": competition.get("status"),
            "snapshot_at": observed,
        },
        event_key=event_key,
    )


async def record_catalog_observation(
    db: Any, snapshot: dict[str, Any], *, event_key: str | None = None
) -> None:
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
    if event_key is not None:
        key = _event_observation_key(seller, str(identity), event_key)
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
    # Concurrent notifications retain the first acquired observation. Snapshot
    # retries with conflicting content at the same cut still raise rather than
    # rewriting history. Neither path replaces existing values.
    await db["sheets_catalog_competition_observations"].update_one(
        {"_id": key} if event_key is not None else document, {"$setOnInsert": document}, upsert=True
    )
