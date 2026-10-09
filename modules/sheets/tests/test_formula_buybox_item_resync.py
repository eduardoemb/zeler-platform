"""A periodic base re-sync of unchanged publications must not discard their buybox snapshots."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ServerSelectionTimeoutError

from zeler_sheets.formulas.read_models import (
    CATALOG_BUYBOX_CACHE_MAX_AGE,
    FormulaReadModelRepository,
)
from zeler_sheets.formulas.recovery import ItemInventoryRecoveryRequest
from zeler_sheets.item_projection import stamp_item_projection

SELLER = "82453304"
NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def buybox_db() -> AsyncIterator[Any]:
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        "mongodb://127.0.0.1:27028/?directConnection=true", serverSelectionTimeoutMS=1000
    )
    db = client[f"zeler_buybox_resync_test_{uuid4().hex}"]
    connected = False
    try:
        try:
            await client.admin.command("ping")
            connected = True
        except ServerSelectionTimeoutError:
            pytest.skip("dedicated local Mongo on port 27028 is unavailable")
        yield db
    finally:
        if connected:
            await client.drop_database(db.name)
        client.close()


async def _seed(
    db: Any,
    *,
    snapshot_title: str = "Producto catalogo",
    snapshot_age: timedelta = timedelta(minutes=8),
) -> None:
    # By default the snapshot was taken 8 minutes ago; a base sweep re-synced
    # the item 2 minutes ago.
    item = {
        "_id": "MLA1",
        "seller_id": SELLER,
        "title": "Producto catalogo",
        "status": "active",
        "price": 100,
        "available_quantity": 3,
        "catalog_listing": True,
        "catalog_product_id": "MLA9",
        "last_meli_sync_at": NOW - timedelta(minutes=2),
        "attributes": [],
        "variations": [],
    }
    row = {
        "_id": f"{SELLER}:sku1:MLA1",
        "seller_id": SELLER,
        "sku": "SKU1",
        "normalized_sku": "sku1",
        "item_id": "MLA1",
        "variation_id": None,
        "inventory_id": None,
        "current": {"title": item["title"], "status": "active"},
    }
    stamp_item_projection([row], item)
    snapshot_at = NOW - snapshot_age
    await db["items"].insert_one(item)
    await db["sheets_item_formula_rows"].insert_one(row)
    await db["sheets_catalog_buybox_snapshots"].insert_one(
        {
            "_id": f"{SELLER}:MLA1",
            "seller_id": SELLER,
            "item_id": "MLA1",
            "catalog_product_id": "MLA9",
            "title": snapshot_title,
            "available_quantity": 3,
            "buybox_status": "winning",
            "price": 100,
            "competitors_sharing_first_place": 0,
            "competitor_count": 2,
            "only_competitor": False,
            "snapshot_at": snapshot_at,
            "offers_snapshot_at": snapshot_at,
            "source": "sheets_backfill",
            "schema_version": 1,
        }
    )
    await db["sheets_formula_recovery_jobs"].insert_one(
        {
            "_id": ItemInventoryRecoveryRequest(SELLER).key,
            "seller_id": SELLER,
            "read_model": "item_formula_rows",
            "inventory_scope": True,
            "state": "completed",
            "inventory_ids": ["MLA1"],
            "inventory_observed_at": NOW - timedelta(minutes=3),
            "inventory_offset": 1,
        }
    )


@pytest.mark.asyncio
async def test_unchanged_publication_resynced_after_snapshot_keeps_its_buybox(
    buybox_db: Any,
) -> None:
    await _seed(buybox_db)

    _, (ready, missing, invalid, _current) = await FormulaReadModelRepository(
        db=buybox_db
    ).find_recent_catalog_inventory(seller_id=SELLER, formula="ZELERDATA_CATALOGOBUYBOX", now=NOW)

    assert [snapshot["item_id"] for snapshot in ready] == ["MLA1"]
    assert missing == () and invalid == ()


@pytest.mark.asyncio
async def test_publication_whose_title_changed_still_discards_its_buybox(buybox_db: Any) -> None:
    await _seed(buybox_db, snapshot_title="Titulo anterior")

    _, (ready, missing, _invalid, _current) = await FormulaReadModelRepository(
        db=buybox_db
    ).find_recent_catalog_inventory(seller_id=SELLER, formula="ZELERDATA_CATALOGOBUYBOX", now=NOW)

    assert ready == [] and missing == ("MLA1",)


@pytest.mark.asyncio
async def test_hours_old_snapshot_of_unchanged_publication_is_served_with_its_offers(
    buybox_db: Any,
) -> None:
    # A full buybox pass over ~940 publications takes hours, so a 15-minute
    # window could never be satisfied for the whole inventory.
    await _seed(buybox_db, snapshot_age=timedelta(hours=6))

    _, (ready, missing, invalid, _current) = await FormulaReadModelRepository(
        db=buybox_db
    ).find_recent_catalog_inventory(seller_id=SELLER, formula="ZELERDATA_CATALOGOBUYBOX", now=NOW)

    assert [snapshot["item_id"] for snapshot in ready] == ["MLA1"]
    assert ready[0]["snapshot_at"].replace(tzinfo=UTC) == NOW - timedelta(hours=6)
    assert ready[0]["competitor_count"] == 2 and ready[0]["only_competitor"] is False
    assert missing == () and invalid == ()


@pytest.mark.asyncio
async def test_snapshot_older_than_the_cache_limit_needs_recovery(buybox_db: Any) -> None:
    await _seed(buybox_db, snapshot_age=CATALOG_BUYBOX_CACHE_MAX_AGE + timedelta(minutes=1))

    _, (ready, missing, _invalid, _current) = await FormulaReadModelRepository(
        db=buybox_db
    ).find_recent_catalog_inventory(seller_id=SELLER, formula="ZELERDATA_CATALOGOBUYBOX", now=NOW)

    assert ready == [] and missing == ("MLA1",)
