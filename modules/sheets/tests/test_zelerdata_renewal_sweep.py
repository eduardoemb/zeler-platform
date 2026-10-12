"""Scheduled renewal of on-demand ZelerData acquisitions (real Mongo).

Buybox, quality and costs are acquired only by recovery and served for 24 hours
(L-044). The renewal sweep re-acquires what the readers would stop serving
within its horizon, and leaves a fresh source-declared absence alone (L-045).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ServerSelectionTimeoutError

from zeler_sheets.formulas.recovery import (
    CatalogRecoveryRequest,
    FormulaRecoveryQueue,
    ItemIdsRecoveryRequest,
    ItemInventoryRecoveryRequest,
    RenewalRecoveryRequest,
)
from zeler_sheets.formulas.refresh import MongoRefreshIdentitySource

SELLER = "82453304"
NOW = datetime(2026, 10, 11, 16, tzinfo=UTC)
RENEW_AFTER = timedelta(hours=6)
SLOT = datetime(2026, 10, 11, 8, tzinfo=UTC)


@pytest_asyncio.fixture
async def renewal_db() -> AsyncIterator[Any]:
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        "mongodb://127.0.0.1:27028/?directConnection=true", serverSelectionTimeoutMS=1000
    )
    db = client[f"zeler_renewal_sweep_test_{uuid4().hex}"]
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


async def _enumerate(
    db: Any,
    identities: list[str],
    *,
    observed: datetime = NOW - timedelta(minutes=5),
    offset: int | None = None,
) -> None:
    await db.sheets_formula_recovery_jobs.insert_one(
        {
            "_id": ItemInventoryRecoveryRequest(SELLER).key,
            "seller_id": SELLER,
            "read_model": "item_formula_rows",
            "state": "completed" if offset is None else "running",
            "attempts": 0,
            "inventory_scope": True,
            "inventory_ids": sorted(identities),
            "inventory_offset": len(identities) if offset is None else offset,
            "inventory_unavailable_ids": [],
            "inventory_observed_at": observed,
            "created_at": observed,
            "updated_at": observed,
            "available_at": observed,
        }
    )


def _catalog_item(identity: str, **overrides: Any) -> dict[str, Any]:
    return {
        "_id": identity,
        "seller_id": SELLER,
        "catalog_listing": True,
        "catalog_product_id": f"MLM9{identity[3:]}",
        "title": f"Item {identity}",
        "available_quantity": 3,
        "last_meli_sync_at": NOW - timedelta(minutes=3),
        "price": 100.0,
        "currency_id": "MXN",
        **overrides,
    }


def _buybox(identity: str, age: timedelta, **overrides: Any) -> dict[str, Any]:
    observed = NOW - age
    return {
        "_id": f"{SELLER}:{identity}",
        "seller_id": SELLER,
        "item_id": identity,
        "catalog_product_id": f"MLM9{identity[3:]}",
        "title": f"Item {identity}",
        "available_quantity": 3,
        "source": "sheets_backfill",
        "snapshot_at": observed,
        "offers_snapshot_at": observed,
        "buybox_status": "winning",
        "price": 100.0,
        "winning_price": 100.0,
        "winning_user_id": SELLER,
        "competitors_sharing_first_place": 0,
        "competitor_count": 2,
        "only_competitor": False,
        **overrides,
    }


@pytest.mark.asyncio
async def test_buybox_renewal_selects_absent_aging_and_mismatched_snapshots(
    renewal_db: Any,
) -> None:
    # A long buybox pass has held the inventory sweep for four hours.
    await _enumerate(
        renewal_db,
        ["MLM1", "MLM2", "MLM3", "MLM4", "MLM5", "MLM6", "MLM8", "MLM9"],
        observed=NOW - timedelta(hours=4),
    )
    await renewal_db["items"].insert_many(
        [
            _catalog_item("MLM1"),
            _catalog_item("MLM2"),
            _catalog_item("MLM3"),
            _catalog_item("MLM4"),
            _catalog_item("MLM5"),
            # Not in catalog competition: never a buybox identity.
            _catalog_item("MLM6", catalog_listing=False),
            # Outside the current inventory enumeration.
            _catalog_item("MLM7"),
            _catalog_item("MLM8"),
            # A stale base row is not a reason to skip: the worker re-reads it.
            _catalog_item("MLM9", last_meli_sync_at=NOW - timedelta(hours=3, minutes=50)),
        ]
    )
    await renewal_db["sheets_catalog_buybox_snapshots"].insert_many(
        [
            _buybox("MLM1", timedelta(hours=1)),
            # MLM2 has never been acquired.
            _buybox("MLM3", timedelta(hours=7)),
            _buybox("MLM4", timedelta(hours=1), available_quantity=9),
            _buybox(
                "MLM5",
                timedelta(hours=1),
                offers_snapshot_at=NOW - timedelta(hours=7),
            ),
            _buybox("MLM6", timedelta(days=3)),
            _buybox("MLM7", timedelta(days=3)),
            # Still served now, but expires before the next pass could renew it.
            _buybox("MLM8", timedelta(hours=23)),
            _buybox("MLM9", timedelta(hours=1)),
        ]
    )
    source = MongoRefreshIdentitySource(db=renewal_db, now=lambda: NOW)

    due = await source.buybox_renewal_ids(SELLER, renew_after=RENEW_AFTER)

    assert due == ("MLM2", "MLM3", "MLM4", "MLM5", "MLM8")


@pytest.mark.asyncio
async def test_buybox_renewal_keeps_a_fresh_source_declared_absence(renewal_db: Any) -> None:
    await _enumerate(renewal_db, ["MLM1", "MLM2", "MLM3"])
    await renewal_db["items"].insert_many(
        [_catalog_item("MLM1"), _catalog_item("MLM2"), _catalog_item("MLM3")]
    )
    unnamed_winner = _buybox("MLM3", timedelta(hours=1))
    del unnamed_winner["winning_user_id"]
    not_listed = {
        "buybox_status": "not_listed",
        "winning_user_id": None,
        "competitors_sharing_first_place": None,
        "competitor_count": None,
        "only_competitor": None,
    }
    await renewal_db["sheets_catalog_buybox_snapshots"].insert_many(
        [
            _buybox("MLM1", timedelta(hours=1), **not_listed),
            # A declared absence is renewed like any acquisition before it expires.
            _buybox("MLM2", timedelta(hours=7), **not_listed),
            # A winner the platform could not name is a gap, not a declaration.
            unnamed_winner,
        ]
    )
    source = MongoRefreshIdentitySource(db=renewal_db, now=lambda: NOW)

    assert await source.buybox_renewal_ids(SELLER, renew_after=RENEW_AFTER) == ("MLM2", "MLM3")


@pytest.mark.asyncio
async def test_renewal_skips_what_the_latest_inventory_pass_could_not_read(
    renewal_db: Any,
) -> None:
    """Mercado Libre answers 404 for some enumerated details; readers never serve them.

    Renewing one would only fail its 20-ID chunk three times.
    """
    discovered = NOW - timedelta(minutes=5)
    # The pass in flight has reached the first three publications.
    await _enumerate(renewal_db, ["MLM1", "MLM2", "MLM3", "MLM4"], observed=discovered, offset=3)
    await renewal_db["items"].insert_many(
        [
            _catalog_item("MLM1"),
            # Reached, but its last read is older than this pass's discovery.
            _catalog_item("MLM2", last_meli_sync_at=NOW - timedelta(days=2)),
            # MLM3 was reached and has never been read.
            # Not reached yet: judged by the next pass, not this one.
            _catalog_item("MLM4", last_meli_sync_at=NOW - timedelta(minutes=15)),
        ]
    )
    await renewal_db["sheets_item_formula_rows"].insert_many(
        [_formula_row(identity, age=timedelta(hours=7)) for identity in ("MLM1", "MLM2", "MLM4")]
    )
    source = MongoRefreshIdentitySource(db=renewal_db, now=lambda: NOW)

    assert await source.buybox_renewal_ids(SELLER, renew_after=RENEW_AFTER) == ("MLM1", "MLM4")
    assert await source.enrichment_renewal_ids(SELLER, renew_after=RENEW_AFTER) == (
        "MLM1",
        "MLM4",
    )


@pytest.mark.asyncio
async def test_renewal_needs_a_known_inventory(renewal_db: Any) -> None:
    await renewal_db["items"].insert_one(_catalog_item("MLM1"))
    source = MongoRefreshIdentitySource(db=renewal_db, now=lambda: NOW)

    assert await source.buybox_renewal_ids(SELLER, renew_after=RENEW_AFTER) == ()
    assert await source.enrichment_renewal_ids(SELLER, renew_after=RENEW_AFTER) == ()


COST_FIELDS = (
    "seller_shipping_cost",
    "listing_fee_projection",
    "listing_price_fixed_fee",
)


def _formula_row(identity: str, *, age: timedelta = timedelta(hours=1)) -> dict[str, Any]:
    synced = NOW - age
    return {
        "_id": f"{SELLER}:SKU-{identity}:{identity}",
        "seller_id": SELLER,
        "item_id": identity,
        "sku": f"sku-{identity}",
        "normalized_sku": f"SKU-{identity}",
        "source_snapshot": {"fingerprint": "f", "observed_at": NOW, "rows_count": 1},
        "current": {
            "title": f"Item {identity}",
            "status": "active",
            "available_quantity": 4,
            "price": 100.0,
            "base_price": 100.0,
            "currency_id": "MXN",
            "category_id": "MLM-CAT",
            "catalog_listing": False,
            "listing_type_id": "gold_special",
            "seller_shipping_cost": 10.0,
            "listing_fee_projection": {"sale_fee_amount": 8.0, "percentage_fee": 8.0},
            "listing_price_fixed_fee": {"fixed_fee": 2.0},
            "quality_projection": {
                "source": "/item/{id}/performance",
                "entity_id": identity,
                "observed_at": synced,
                "score": 88.0,
                "level": "good",
                "calculated_at": synced - timedelta(hours=1),
                "components": {},
                "pending_actions": [],
            },
            "enrichment_state": {
                **{field: {"status": "trusted", "synced_at": synced} for field in COST_FIELDS},
                "current_promotion": {"status": "authoritative_absent", "synced_at": synced},
                "quality_projection": {"status": "trusted", "synced_at": synced},
            },
        },
    }


@pytest.mark.asyncio
async def test_enrichment_renewal_selects_quality_and_costs_the_readers_would_drop(
    renewal_db: Any,
) -> None:
    identities = [f"MLM{index}" for index in range(1, 11)]
    await _enumerate(renewal_db, [identity for identity in identities if identity != "MLM8"])
    rows = {identity: _formula_row(identity) for identity in identities if identity != "MLM7"}
    # Quality acquired more than one renewal horizon ago.
    rows["MLM2"]["current"]["quality_projection"].update(
        observed_at=NOW - timedelta(hours=7), calculated_at=NOW - timedelta(hours=8)
    )
    # A cost acquired more than one renewal horizon ago.
    rows["MLM3"]["current"]["enrichment_state"]["seller_shipping_cost"]["synced_at"] = (
        NOW - timedelta(hours=7)
    )
    # A base change invalidated the quality basis.
    rows["MLM4"]["current"]["enrichment_state"]["quality_projection"] = {
        "status": "basis_mismatch",
        "reason": "base_changed",
        "synced_at": NOW - timedelta(minutes=30),
    }
    # Mercado Libre declared the quality absent an hour ago (L-045).
    rows["MLM5"]["current"].pop("quality_projection")
    rows["MLM5"]["current"]["enrichment_state"]["quality_projection"] = {
        "status": "transient",
        "reason": "performance_not_generated",
        "synced_at": NOW - timedelta(hours=1),
    }
    # And a fixed fee declared absent an hour ago.
    rows["MLM6"]["current"]["enrichment_state"]["listing_price_fixed_fee"] = {
        "status": "authoritative_absent",
        "synced_at": NOW - timedelta(hours=1),
    }
    # MLM7 is enumerated but has no projected row; MLM8 is no longer enumerated.
    # A promotion that failed to load is a gap even when recent.
    rows["MLM9"]["current"]["enrichment_state"]["current_promotion"] = {
        "status": "transient",
        "synced_at": NOW - timedelta(minutes=30),
    }
    # A declared quality absence also ages out of its horizon.
    rows["MLM10"]["current"].pop("quality_projection")
    rows["MLM10"]["current"]["enrichment_state"]["quality_projection"] = {
        "status": "malformed",
        "reason": "http_400",
        "synced_at": NOW - timedelta(hours=7),
    }
    await renewal_db["sheets_item_formula_rows"].insert_many(list(rows.values()))
    await renewal_db["items"].insert_many(
        [_catalog_item(identity, catalog_listing=False) for identity in identities]
    )
    source = MongoRefreshIdentitySource(db=renewal_db, now=lambda: NOW)

    due = await source.enrichment_renewal_ids(SELLER, renew_after=RENEW_AFTER)

    assert due == ("MLM10", "MLM2", "MLM3", "MLM4", "MLM7", "MLM9")


def _queue(db: Any) -> FormulaRecoveryQueue:
    return FormulaRecoveryQueue(db, now=lambda: NOW)


def _job(job_id: str, read_model: str, state: str, **fields: Any) -> dict[str, Any]:
    return {
        "_id": job_id,
        "seller_id": SELLER,
        "read_model": read_model,
        "state": state,
        "attempts": 0,
        "created_at": NOW,
        "updated_at": NOW,
        "available_at": NOW,
        **fields,
    }


@pytest.mark.asyncio
async def test_renewal_status_holds_while_any_catalog_pass_of_the_model_runs(
    renewal_db: Any,
) -> None:
    buybox_key = RenewalRecoveryRequest(
        SELLER, "catalog_buybox_snapshots", ("MLM1",), slot=SLOT
    ).key
    items_key = RenewalRecoveryRequest(SELLER, "item_formula_rows", ("MLM1",), slot=SLOT).key
    queue = _queue(renewal_db)

    async def status(read_model: str, key: str) -> tuple[bool, bool]:
        return await queue.renewal_status(seller_id=SELLER, read_model=read_model, slot_key=key)

    assert await status("catalog_buybox_snapshots", buybox_key) == (False, False)

    await renewal_db.sheets_formula_recovery_jobs.insert_many(
        [
            # A formula-sized batch is coalesced at admission, it holds nothing.
            _job("batch", "catalog_buybox_snapshots", "running", item_ids=["MLM1"]),
            # The base inventory is its own sweep.
            _job(
                ItemInventoryRecoveryRequest(SELLER).key,
                "item_formula_rows",
                "running",
                inventory_scope=True,
            ),
            # Another seller's pass never holds this seller.
            {
                **_job(
                    "foreign",
                    "catalog_buybox_snapshots",
                    "running",
                    item_ids=["MLM2"],
                    catalog_offset=0,
                ),
                "seller_id": "999",
            },
        ]
    )
    assert await status("catalog_buybox_snapshots", buybox_key) == (False, False)
    assert await status("item_formula_rows", items_key) == (False, False)

    # An on-demand pass over a whole sheet is in flight: never overlap it.
    await renewal_db.sheets_formula_recovery_jobs.insert_one(
        _job(
            "on_demand",
            "catalog_buybox_snapshots",
            "pending",
            item_ids=[f"MLM{index}" for index in range(30)],
            catalog_offset=20,
        )
    )
    assert await status("catalog_buybox_snapshots", buybox_key) == (True, False)
    assert await status("item_formula_rows", items_key) == (False, False)

    await renewal_db.sheets_formula_recovery_jobs.update_one(
        {"_id": "on_demand"}, {"$set": {"state": "completed"}}
    )
    await renewal_db.sheets_formula_recovery_jobs.insert_one(
        _job(buybox_key, "catalog_buybox_snapshots", "failed", item_ids=["MLM1"], catalog_offset=1)
    )
    # This slot already had its pass, whatever its outcome.
    assert await status("catalog_buybox_snapshots", buybox_key) == (False, True)


@pytest.mark.asyncio
async def test_renewal_passes_reports_the_state_of_each_existing_pass(renewal_db: Any) -> None:
    """The cross-seller renewal turn reads pass states by their slot keys only."""
    other = "90000001"
    pilot = RenewalRecoveryRequest(SELLER, "catalog_buybox_snapshots", ("MLM1",), slot=SLOT).key
    foreign = RenewalRecoveryRequest(other, "item_formula_rows", ("MLM1",), slot=SLOT).key
    missing = RenewalRecoveryRequest(SELLER, "item_formula_rows", ("MLM1",), slot=SLOT).key
    await renewal_db.sheets_formula_recovery_jobs.insert_many(
        [
            _job(pilot, "catalog_buybox_snapshots", "running", item_ids=["MLM1"], catalog_offset=0),
            {
                **_job(foreign, "item_formula_rows", "completed", item_ids=["MLM1"]),
                "seller_id": other,
            },
            # Not a renewal pass: never part of the answer.
            _job("on_demand", "catalog_buybox_snapshots", "pending", item_ids=["MLM2"]),
        ]
    )
    queue = _queue(renewal_db)

    assert await queue.renewal_passes((pilot, foreign, missing)) == {
        pilot: "running",
        foreign: "completed",
    }
    assert await queue.renewal_passes(()) == {}


@pytest.mark.asyncio
async def test_renewal_status_rejects_models_without_renewal(renewal_db: Any) -> None:
    with pytest.raises(ValueError, match="renewal"):
        await _queue(renewal_db).renewal_status(seller_id=SELLER, read_model="orders", slot_key="x")


@pytest.mark.asyncio
async def test_a_renewal_pass_never_reopens_a_terminal_job(renewal_db: Any) -> None:
    ids = ("MLM1", "MLM2")
    queue = _queue(renewal_db)
    jobs = renewal_db.sheets_formula_recovery_jobs
    # An earlier on-demand pass over exactly the same publications.
    on_demand = CatalogRecoveryRequest(SELLER, "catalog_buybox_snapshots", ids)
    await jobs.insert_one(
        _job(
            on_demand.key,
            "catalog_buybox_snapshots",
            "failed",
            item_ids=list(ids),
            catalog_offset=2,
            failure_reason="source_incomplete",
        )
    )

    first = RenewalRecoveryRequest(SELLER, "catalog_buybox_snapshots", ids, slot=SLOT)
    assert await queue.enqueue(first, reopen_terminal=False) == first.key
    admitted = await jobs.find_one({"_id": first.key})
    assert admitted["state"] == "pending"
    assert admitted["item_ids"] == list(ids)
    assert admitted["catalog_offset"] == 0
    assert (await jobs.find_one({"_id": on_demand.key}))["state"] == "failed"

    await jobs.update_one({"_id": first.key}, {"$set": {"state": "completed"}})
    # The same slot admits nothing more, even with other identities.
    again = RenewalRecoveryRequest(SELLER, "catalog_buybox_snapshots", ("MLM3",), slot=SLOT)
    assert again.key == first.key
    await queue.enqueue(again, reopen_terminal=False)
    assert (await jobs.find_one({"_id": first.key}))["state"] == "completed"
    assert (await jobs.find_one({"_id": first.key}))["item_ids"] == list(ids)

    following = RenewalRecoveryRequest(
        SELLER, "catalog_buybox_snapshots", ids, slot=SLOT + timedelta(hours=12)
    )
    assert following.key != first.key
    await queue.enqueue(following, reopen_terminal=False)
    assert (await jobs.find_one({"_id": following.key}))["state"] == "pending"
    assert await jobs.count_documents({}) == 3


@pytest.mark.asyncio
async def test_renewal_coalesces_identities_already_queued_and_keeps_its_slot(
    renewal_db: Any,
) -> None:
    queue = _queue(renewal_db)
    await queue.enqueue(
        ItemIdsRecoveryRequest(SELLER, ("MLM1",), read_model="catalog_buybox_snapshots")
    )
    renewal = RenewalRecoveryRequest(
        SELLER, "catalog_buybox_snapshots", ("MLM1", "MLM2", "MLM3"), slot=SLOT
    )

    assert await queue.enqueue(renewal, reopen_terminal=False) == renewal.key

    admitted = await renewal_db.sheets_formula_recovery_jobs.find_one({"_id": renewal.key})
    assert admitted["item_ids"] == ["MLM2", "MLM3"]


@pytest.mark.parametrize(
    ("read_model", "slot"),
    [
        ("orders", SLOT),
        ("catalog_product_snapshots", SLOT),
        ("catalog_buybox_snapshots", SLOT.replace(tzinfo=None)),
    ],
)
def test_renewal_request_shape(read_model: str, slot: datetime) -> None:
    with pytest.raises(ValueError, match="renewal"):
        RenewalRecoveryRequest(SELLER, read_model, ("MLM1",), slot=slot)
