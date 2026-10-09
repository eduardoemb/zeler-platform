from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from infra.operations.zelerdata_partial_diagnose import (
    ReadOnlyDatabase,
    ReadOnlyViolationError,
    age_bucket,
    classify_item_source,
    diagnose,
)
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ServerSelectionTimeoutError

from zeler_sheets.formulas.recovery import ItemInventoryRecoveryRequest
from zeler_sheets.item_projection import stamp_item_projection

SELLER = "999000111"
NOW = datetime(2026, 10, 8, 4, 0, tzinfo=UTC)
SECRETS = ("MLA900001", "MLA900002", "MLA900003", "SKU-SECRET", "Titulo secreto", SELLER)


@pytest_asyncio.fixture
async def diag_db() -> AsyncIterator[Any]:
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        "mongodb://127.0.0.1:27028/?directConnection=true", serverSelectionTimeoutMS=1000
    )
    db = client[f"zeler_partial_diag_test_{uuid4().hex}"]
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


def _item(item_id: str, *, synced: datetime, **extra: Any) -> dict[str, Any]:
    return {
        "_id": item_id,
        "seller_id": SELLER,
        "title": "Titulo secreto",
        "status": "active",
        "available_quantity": 3,
        "price": 10,
        "base_price": 10,
        "category_id": "MLA1",
        "last_meli_sync_at": synced,
        "catalog_listing": False,
        "attributes": [{"id": "SELLER_SKU", "value_name": "SKU-SECRET"}],
        "variations": [],
        **extra,
    }


def _row(item: dict[str, Any]) -> dict[str, Any]:
    row = {
        "_id": f"{SELLER}:sku-secret:{item['_id']}",
        "seller_id": SELLER,
        "sku": "SKU-SECRET",
        "normalized_sku": "sku-secret",
        "item_id": item["_id"],
        "variation_id": None,
        "inventory_id": None,
        "current": {
            "title": item["title"],
            "status": item["status"],
            "available_quantity": item["available_quantity"],
            "base_price": 10,
            "price": 10,
        },
    }
    stamp_item_projection([row], item)
    return row


def test_age_bucket_names_every_window_without_values() -> None:
    assert age_bucket(None) == "none"
    assert age_bucket(-1) == "future"
    assert age_bucket(0) == "le_15m"
    assert age_bucket(14.9) == "le_15m"
    assert age_bucket(15) == "15_30m"
    assert age_bucket(45) == "30_60m"
    assert age_bucket(120) == "1_4h"
    assert age_bucket(600) == "gt_4h"


def test_classify_item_source_follows_the_reader_order() -> None:
    fresh = _item("MLA900001", synced=NOW - timedelta(minutes=3))
    rows = [_row(fresh)]
    assert classify_item_source(None, rows, seller_id=SELLER, now=NOW) == "no_item_source"
    assert classify_item_source(fresh, [], seller_id=SELLER, now=NOW) == "no_formula_rows"
    assert classify_item_source(fresh, rows, seller_id=SELLER, now=NOW) == "ok"
    assert classify_item_source(fresh, rows, seller_id="other", now=NOW) == "other_seller"

    stale = _item("MLA900001", synced=NOW - timedelta(minutes=20))
    assert (
        classify_item_source(stale, [_row(stale)], seller_id=SELLER, now=NOW)
        == "sync_older_than_15m_projection_consistent"
    )
    assert (
        classify_item_source(stale, rows, seller_id=SELLER, now=NOW)
        == "sync_older_than_15m_projection_changed"
    )

    changed = {**fresh, "title": "otro"}
    assert classify_item_source(changed, rows, seller_id=SELLER, now=NOW) == "fingerprint_mismatch"
    unsealed = [{k: v for k, v in rows[0].items() if k != "source_snapshot"}]
    assert (
        classify_item_source(fresh, unsealed, seller_id=SELLER, now=NOW)
        == "row_without_source_snapshot"
    )
    no_sync = {k: v for k, v in fresh.items() if k != "last_meli_sync_at"}
    assert classify_item_source(no_sync, rows, seller_id=SELLER, now=NOW) == "no_sync_timestamp"
    future = _item("MLA900001", synced=NOW + timedelta(minutes=5))
    assert (
        classify_item_source(future, [_row(future)], seller_id=SELLER, now=NOW) == "sync_in_future"
    )


@pytest.mark.asyncio
async def test_read_only_database_rejects_every_write(diag_db: Any) -> None:
    guarded = ReadOnlyDatabase(diag_db)
    await diag_db.items.insert_one({"_id": "x", "seller_id": SELLER})
    assert await guarded["items"].find_one({"_id": "x"}) is not None
    assert await guarded.items.count_documents({}) == 1
    assert [doc async for doc in guarded["items"].aggregate([{"$match": {}}])]
    attempts: list[Callable[[], Any]] = [
        lambda: guarded["items"].insert_one({"_id": "y"}),
        lambda: guarded["items"].update_one({"_id": "x"}, {"$set": {"a": 1}}),
        lambda: guarded["items"].delete_many({}),
        lambda: guarded["items"].drop(),
        lambda: guarded.command("ping"),
    ]
    for attempt in attempts:
        with pytest.raises(ReadOnlyViolationError):
            attempt()
    with pytest.raises(ReadOnlyViolationError):
        guarded["items"].aggregate([{"$out": "copy"}])
    with pytest.raises(ReadOnlyViolationError):
        guarded["items"].aggregate([{"$merge": "copy"}])
    assert await diag_db.items.count_documents({}) == 1


@pytest.mark.asyncio
async def test_diagnose_counts_causes_without_leaking_identities(diag_db: Any) -> None:
    fresh = _item("MLA900001", synced=NOW - timedelta(minutes=3))
    stale = _item("MLA900002", synced=NOW - timedelta(minutes=40), status="paused")
    orphan = _item("MLA900003", synced=NOW - timedelta(minutes=2))
    await diag_db.items.insert_many([fresh, stale, orphan])
    await diag_db.sheets_item_formula_rows.insert_many([_row(fresh), _row(stale)])
    request = ItemInventoryRecoveryRequest(SELLER)
    await diag_db.sheets_formula_recovery_jobs.insert_one(
        {
            "_id": request.key,
            "seller_id": SELLER,
            "read_model": "item_formula_rows",
            "inventory_scope": True,
            "state": "completed",
            "inventory_ids": ["MLA900001", "MLA900002", "MLA900003"],
            "inventory_observed_at": NOW - timedelta(minutes=50),
            "inventory_offset": 3,
        }
    )

    report = await diagnose(diag_db, seller_id=SELLER, now=NOW)

    enumeration = report["inventory_enumeration"]
    assert enumeration["present"] is True
    assert enumeration["identities"] == 3
    assert enumeration["current"] is False
    assert enumeration["observed_age_bucket"] == "30_60m"
    verification = report["item_verification"]
    assert verification["universe"] == 3
    assert verification["reasons"] == {
        "ok": 1,
        "sync_older_than_15m_projection_consistent": 1,
        "no_formula_rows": 1,
    }
    assert verification["reasons_by_status"]["paused"] == {
        "sync_older_than_15m_projection_consistent": 1
    }
    assert verification["inventory_rows_complete_now"] is False
    assert sum(report["item_sync_ages"]["buckets"].values()) == 3
    assert set(report["inventory_replay"]) >= {
        "ZELERDATA_CALIDAD",
        "ZELERDATA_CATALOGO",
        "ZELERDATA_CATALOGOBUYBOX",
        "ZELERDATA_CATALOGO_COMPLETO",
        "ZELERDATA_OBTENER_CATALOGO",
        "ZELERDATA_PUBLICACIONESDESCUIDADAS",
        "ZELERDATA_CATALOGOSINVINCULAR",
    }
    assert set(report["single_identity_replay"]) >= {"spread"}

    serialized = json.dumps(report, default=str)
    for secret in SECRETS:
        assert secret not in serialized


@pytest.mark.asyncio
async def test_diagnose_survives_an_empty_seller(diag_db: Any) -> None:
    report = await diagnose(diag_db, seller_id=SELLER, now=NOW)
    assert report["inventory_enumeration"]["present"] is False
    assert report["item_verification"]["universe"] == 0
    assert "error" not in report["item_verification"]


@pytest.mark.asyncio
async def test_diagnose_classifies_buybox_with_the_reader_cache_limit(diag_db: Any) -> None:
    from zeler_sheets.formulas.read_models import CATALOG_BUYBOX_CACHE_MAX_AGE

    ages = {
        "MLA900001": timedelta(minutes=5),
        "MLA900002": timedelta(hours=6),
        "MLA900003": CATALOG_BUYBOX_CACHE_MAX_AGE + timedelta(minutes=1),
    }
    items = [
        _item(
            item_id,
            synced=NOW - timedelta(minutes=1),
            catalog_listing=True,
            catalog_product_id="MLA77",
        )
        for item_id in ages
    ]
    await diag_db.items.insert_many(items)
    await diag_db.sheets_catalog_buybox_snapshots.insert_many(
        [
            {
                "_id": f"{SELLER}:{item_id}",
                "seller_id": SELLER,
                "item_id": item_id,
                "catalog_product_id": "MLA77",
                "title": "Titulo secreto",
                "available_quantity": 3,
                "buybox_status": "winning",
                "snapshot_at": NOW - age,
                "source": "sheets_backfill",
            }
            for item_id, age in ages.items()
        ]
    )

    report = await diagnose(diag_db, seller_id=SELLER, now=NOW)

    assert report["catalog"]["buybox_by_reader_state"] == {
        "ready_current": 1,
        "ready_cached": 1,
        "snapshot_older_than_cache_limit": 1,
    }
