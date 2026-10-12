"""The pilot and a newly linked seller share sweeps, renewal and refresh (real Mongo).

Both sellers are eligible in `all` mode. The runtime factory wires the same
inventory, catalog and renewal sweeps the pilot runs, and the recovery lanes
claim one chunk at a time in arrival order, so a large seller's pass never
holds a small seller's work until it ends.
"""

from __future__ import annotations

import itertools
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ServerSelectionTimeoutError

from zeler_sheets.formulas.recovery import FormulaRecoveryQueue, ItemInventoryRecoveryRequest

PILOT = "82453304"
NEW_SELLER = "90000001"
JOBS = "sheets_formula_recovery_jobs"


@pytest_asyncio.fixture
async def sweeps_db() -> AsyncIterator[Any]:
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        "mongodb://127.0.0.1:27028/?directConnection=true",
        serverSelectionTimeoutMS=1000,
        tz_aware=True,
    )
    db = client[f"zeler_all_sellers_sweeps_test_{uuid4().hex}"]
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


def _identities(seller_id: str, count: int) -> list[str]:
    return [f"MLM{seller_id}{index:03d}" for index in range(count)]


async def _link_with_inventory(db: Any, seller_id: str, *, items: int, now: datetime) -> None:
    """A linked seller with ZelerData enabled and a completed inventory pass."""
    await db.meli_accounts.insert_one({"seller_id": seller_id, "status": "active"})
    await db.sheets_extension_tokens.insert_one(
        {
            "status": "active",
            "seller_scopes": [{"seller_id": seller_id, "nickname": f"n{seller_id}"}],
            "expires_at": now + timedelta(days=30),
        }
    )
    identities = _identities(seller_id, items)
    discovered = now - timedelta(minutes=20)
    await db[JOBS].insert_one(
        {
            "_id": ItemInventoryRecoveryRequest(seller_id).key,
            "seller_id": seller_id,
            "read_model": "item_formula_rows",
            "state": "completed",
            "attempts": 0,
            "inventory_scope": True,
            "inventory_ids": identities,
            "inventory_offset": len(identities),
            "inventory_unavailable_ids": [],
            "inventory_observed_at": discovered,
            "created_at": discovered,
            "updated_at": discovered + timedelta(minutes=1),
            "available_at": discovered + timedelta(minutes=10),
        }
    )
    await db.items.insert_many(
        [
            {
                "_id": identity,
                "seller_id": seller_id,
                "catalog_listing": True,
                "catalog_product_id": f"MLM9{identity[3:]}",
                "title": f"Item {identity}",
                "available_quantity": 3,
                "last_meli_sync_at": discovered + timedelta(seconds=30),
                "price": 100.0,
                "currency_id": "MXN",
            }
            for identity in identities
        ]
    )


def _enable_all_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "ZELERDATA_SCHEDULED_BULK_REFRESH_ENABLED",
        "ZELERDATA_SCHEDULED_RENEWAL_REFRESH_ENABLED",
        "ZELERDATA_RENEWAL_REFRESH_HOURS",
        "ZELERDATA_INVENTORY_REFRESH_MINUTES",
        "ZELERDATA_CATALOG_REFRESH_HOURS",
        "ZELERDATA_REFRESH_INTERVAL_SECONDS",
        "ZELERDATA_DEVOLUCIONES_ADVANCE_ENABLED",
        "ZELERDATA_PRECALCULATED_FORMULAS_ENABLED",
        "ZELERDATA_FRESHNESS_ALERTS_ENABLED",
        "ZELERDATA_DLQ_ARCHIVE_ENABLED",
        "ZELERDATA_HISTORY_ON_LINK_ENABLED",
        "ZELERDATA_ORDER_HISTORY_PROTOCOL_ENABLED",
        "ZELERDATA_QUESTION_HISTORY_PROTOCOL_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ZELERDATA_REFRESH_ENABLED", "true")
    monkeypatch.setenv("ZELERDATA_REFRESH_SELLERS", "all")
    monkeypatch.setenv("ZELERDATA_FORMULA_RECOVERY_ENABLED", "true")
    monkeypatch.setenv("ZELERDATA_FORMULA_RECOVERY_SELLERS", "all")
    monkeypatch.setenv("ZELERDATA_SCHEDULED_INVENTORY_REFRESH_ENABLED", "true")
    monkeypatch.setenv("ZELERDATA_SCHEDULED_CATALOG_REFRESH_ENABLED", "true")


def _ticking(start: datetime) -> Callable[[], datetime]:
    """A clock that moves one second per read, like a worker between chunks."""
    seconds = itertools.count()
    return lambda: start + timedelta(seconds=next(seconds))


async def _jobs(db: Any, seller_id: str, **query: Any) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = (
        await db[JOBS].find({"seller_id": seller_id, **query}).to_list(length=None)
    )
    return jobs


async def _renewals(db: Any, seller_id: str) -> list[dict[str, Any]]:
    return await _jobs(
        db,
        seller_id,
        read_model={"$in": ["catalog_buybox_snapshots", "item_formula_rows"]},
        item_ids={"$exists": True},
        catalog_offset={"$exists": True},
    )


async def _inventory_state(db: Any, seller_id: str) -> str:
    job = await db[JOBS].find_one({"_id": ItemInventoryRecoveryRequest(seller_id).key})
    return str(job["state"])


async def _drain_ids_lane(queue: FormulaRecoveryQueue, *, limit: int) -> list[tuple[str, str]]:
    """Process the ids lane chunk by chunk, as its worker does, in claim order."""
    claimed: list[tuple[str, str]] = []
    for _ in range(limit):
        job = await queue.claim(lane="ids")
        if job is None:
            return claimed
        claimed.append((job["seller_id"], job["read_model"]))
        assert await queue.finish(job, succeeded=True)
    raise AssertionError("the ids lane did not drain")


@pytest.mark.asyncio
async def test_pilot_and_new_seller_both_get_sweeps_renewal_and_refresh(
    sweeps_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from zeler_sheets.consumer import build_zelerdata_refresh_supervisor

    now = datetime.now(UTC)
    # The pilot is several chunks larger than the new seller.
    await _link_with_inventory(sweeps_db, PILOT, items=60, now=now)
    await _link_with_inventory(sweeps_db, NEW_SELLER, items=10, now=now)
    _enable_all_mode(monkeypatch)
    supervisor = await build_zelerdata_refresh_supervisor(db=sweeps_db)

    assert await supervisor._explorer.discover_sellers() == (PILOT, NEW_SELLER)

    await supervisor.run_cycle()

    for seller_id in (PILOT, NEW_SELLER):
        # Refresh: bounded order and question ranges for every eligible seller.
        assert {job["read_model"] for job in await _jobs(sweeps_db, seller_id)} >= {
            "orders",
            "questions",
        }
        # Catalog product sweep.
        assert [
            job["state"]
            for job in await _jobs(sweeps_db, seller_id, read_model="catalog_product_snapshots")
        ] == ["pending"]
    # Renewal takes turns: the pilot's passes first, the new seller waits.
    assert sorted(job["read_model"] for job in await _renewals(sweeps_db, PILOT)) == [
        "catalog_buybox_snapshots",
        "item_formula_rows",
    ]
    assert await _renewals(sweeps_db, NEW_SELLER) == []

    await supervisor._run_inventory_cycle()

    # The pilot's inventory waits for its own buybox pass (L-037); the new
    # seller's inventory is not held by it.
    assert await _inventory_state(sweeps_db, PILOT) == "completed"
    assert await _inventory_state(sweeps_db, NEW_SELLER) == "pending"

    # The ids lane claims one chunk per job in arrival order: the new seller's
    # catalog pass completes in the first round, long before the pilot's
    # three-chunk passes end.
    lane = FormulaRecoveryQueue(sweeps_db, now=_ticking(now + timedelta(minutes=1)))
    claims = await _drain_ids_lane(lane, limit=50)
    first_round = claims[:4]
    assert (NEW_SELLER, "catalog_product_snapshots") in first_round
    assert {seller for seller, _ in first_round} == {PILOT, NEW_SELLER}
    assert len(claims) == 3 + 3 + 3 + 1
    assert {job["state"] for job in await _renewals(sweeps_db, PILOT)} == {"completed"}

    # Once the pilot's passes end, the new seller gets its own renewal, and
    # the pilot's slot is not renewed again.
    await supervisor.run_cycle()

    assert sorted(job["read_model"] for job in await _renewals(sweeps_db, NEW_SELLER)) == [
        "catalog_buybox_snapshots",
        "item_formula_rows",
    ]
    assert len(await _renewals(sweeps_db, PILOT)) == 2

    await supervisor._run_inventory_cycle()
    assert await _inventory_state(sweeps_db, PILOT) == "pending"


@pytest.mark.asyncio
async def test_inventory_passes_of_two_sellers_alternate_chunk_by_chunk(
    sweeps_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from zeler_sheets.consumer import build_zelerdata_refresh_supervisor

    now = datetime.now(UTC)
    await _link_with_inventory(sweeps_db, PILOT, items=60, now=now)
    await _link_with_inventory(sweeps_db, NEW_SELLER, items=10, now=now)
    _enable_all_mode(monkeypatch)
    monkeypatch.setenv("ZELERDATA_SCHEDULED_RENEWAL_REFRESH_ENABLED", "false")
    supervisor = await build_zelerdata_refresh_supervisor(db=sweeps_db)

    await supervisor._run_inventory_cycle()
    assert await _inventory_state(sweeps_db, PILOT) == "pending"
    assert await _inventory_state(sweeps_db, NEW_SELLER) == "pending"

    lane = FormulaRecoveryQueue(sweeps_db, now=_ticking(now + timedelta(minutes=1)))
    sequence: list[str] = []
    for _ in range(6):
        job = await lane.claim(lane="inventory")
        assert job is not None
        sequence.append(job["seller_id"])
        identities = _identities(job["seller_id"], 60 if job["seller_id"] == PILOT else 10)
        offset = job.get("inventory_offset")
        # Discovery first, then 20-ID batches, each its own claim.
        next_offset = 0 if offset is None else min(offset + 20, len(identities))
        assert await lane.checkpoint_inventory(job, item_ids=identities, offset=next_offset)

    # Each claim goes to the seller that waited longest: the new seller's
    # whole pass (discovery and one batch) ends while the pilot is mid-pass.
    assert sequence[:4] in (
        [PILOT, NEW_SELLER, PILOT, NEW_SELLER],
        [NEW_SELLER, PILOT, NEW_SELLER, PILOT],
    )
    assert sequence[4:] == [PILOT, PILOT]
    assert await _inventory_state(sweeps_db, NEW_SELLER) == "completed"
    assert await _inventory_state(sweeps_db, PILOT) == "completed"
    assert await lane.claim(lane="inventory") is None
