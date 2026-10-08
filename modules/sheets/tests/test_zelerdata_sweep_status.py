"""Whole-seller sweep status read by the spaced refresh planner (real Mongo)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ServerSelectionTimeoutError

from zeler_sheets.formulas.recovery import FormulaRecoveryQueue, ItemInventoryRecoveryRequest

SELLER = "82453304"
NOW = datetime(2026, 10, 7, 12, tzinfo=UTC)
INVENTORY = ItemInventoryRecoveryRequest(SELLER).key


@pytest_asyncio.fixture
async def sweep_db() -> AsyncIterator[Any]:
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        "mongodb://127.0.0.1:27028/?directConnection=true", serverSelectionTimeoutMS=1000
    )
    db = client[f"zeler_sweep_status_test_{uuid4().hex}"]
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


def _job(
    job_id: str, read_model: str, state: str, updated_at: datetime, **fields: Any
) -> dict[str, Any]:
    return {
        "_id": job_id,
        "seller_id": SELLER,
        "read_model": read_model,
        "state": state,
        "attempts": 0,
        "created_at": updated_at,
        "updated_at": updated_at,
        "available_at": updated_at,
        **fields,
    }


async def _status(db: Any, read_model: str) -> tuple[bool, datetime | None]:
    return await FormulaRecoveryQueue(db, now=lambda: NOW).sweep_status(
        seller_id=SELLER, read_model=read_model
    )


@pytest.mark.asyncio
async def test_no_previous_sweep_is_due_immediately(sweep_db: Any) -> None:
    assert await _status(sweep_db, "item_formula_rows") == (False, None)
    assert await _status(sweep_db, "catalog_product_snapshots") == (False, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["pending", "running"])
async def test_inventory_in_flight_is_active(sweep_db: Any, state: str) -> None:
    await sweep_db.sheets_formula_recovery_jobs.insert_one(
        _job(INVENTORY, "item_formula_rows", state, NOW, inventory_scope=True)
    )
    assert await _status(sweep_db, "item_formula_rows") == (True, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["completed", "failed"])
async def test_finished_inventory_is_anchored_on_its_discovery(sweep_db: Any, state: str) -> None:
    discovered = NOW - timedelta(minutes=12)
    await sweep_db.sheets_formula_recovery_jobs.insert_one(
        _job(
            INVENTORY,
            "item_formula_rows",
            state,
            NOW - timedelta(minutes=2),
            inventory_scope=True,
            inventory_ids=["MLM1"],
            inventory_offset=1,
            inventory_observed_at=discovered,
        )
    )
    assert await _status(sweep_db, "item_formula_rows") == (False, discovered)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "previous_pass",
    [{}, {"inventory_observed_at": NOW - timedelta(hours=5)}],
    ids=["never_discovered", "reopened_and_not_rediscovered"],
)
async def test_inventory_failed_before_discovery_is_anchored_on_its_failure(
    sweep_db: Any, previous_pass: dict[str, Any]
) -> None:
    """Without that anchor every 30-second tick would reopen the sweep."""
    failed = NOW - timedelta(minutes=3)
    await sweep_db.sheets_formula_recovery_jobs.insert_one(
        _job(
            INVENTORY,
            "item_formula_rows",
            "failed",
            failed,
            inventory_scope=True,
            failure_reason="source_rejected",
            **previous_pass,
        )
    )
    assert await _status(sweep_db, "item_formula_rows") == (False, failed)


@pytest.mark.asyncio
@pytest.mark.parametrize("item_ids", [["MLM1"], [f"MLM{i}" for i in range(25)]])
async def test_buybox_in_flight_holds_the_inventory_sweep(
    sweep_db: Any, item_ids: list[str]
) -> None:
    """Re-observing items mid-buybox invalidates that acquisition (synced <= observed)."""
    await sweep_db.sheets_formula_recovery_jobs.insert_many(
        [
            _job(
                INVENTORY,
                "item_formula_rows",
                "completed",
                NOW - timedelta(hours=1),
                inventory_scope=True,
                inventory_observed_at=NOW - timedelta(hours=1),
            ),
            _job("buybox", "catalog_buybox_snapshots", "running", NOW, item_ids=item_ids),
        ]
    )
    assert await _status(sweep_db, "item_formula_rows") == (True, None)


@pytest.mark.asyncio
async def test_a_stalled_buybox_job_does_not_freeze_the_inventory(sweep_db: Any) -> None:
    discovered = NOW - timedelta(hours=1)
    await sweep_db.sheets_formula_recovery_jobs.insert_many(
        [
            _job(
                INVENTORY,
                "item_formula_rows",
                "completed",
                discovered,
                inventory_scope=True,
                inventory_ids=["MLM1"],
                inventory_offset=1,
                inventory_observed_at=discovered,
            ),
            # No progress for longer than two leases: nothing is acquiring it.
            _job(
                "buybox",
                "catalog_buybox_snapshots",
                "pending",
                NOW - timedelta(minutes=21),
                item_ids=["MLM1"],
            ),
        ]
    )
    assert await _status(sweep_db, "item_formula_rows") == (False, discovered)


@pytest.mark.asyncio
async def test_catalog_sweep_in_flight_is_active(sweep_db: Any) -> None:
    await sweep_db.sheets_formula_recovery_jobs.insert_one(
        _job(
            "catalog",
            "catalog_product_snapshots",
            "pending",
            NOW,
            catalog_product_ids=[f"MLM{i}" for i in range(25)],
            catalog_offset=20,
        )
    )
    assert await _status(sweep_db, "catalog_product_snapshots") == (True, None)


@pytest.mark.asyncio
async def test_catalog_sweep_is_anchored_on_the_latest_finished_pass(sweep_db: Any) -> None:
    latest = NOW - timedelta(hours=1)
    await sweep_db.sheets_formula_recovery_jobs.insert_many(
        [
            _job(
                "older",
                "catalog_product_snapshots",
                "completed",
                NOW - timedelta(hours=5),
                catalog_product_ids=["MLM1", "MLM2"],
                catalog_offset=2,
            ),
            _job(
                "latest",
                "catalog_product_snapshots",
                "failed",
                latest,
                catalog_product_ids=["MLM1", "MLM3"],
                catalog_offset=2,
            ),
            # A formula-sized batch is not a sweep and never delays one.
            _job(
                "formula_batch",
                "catalog_product_snapshots",
                "running",
                NOW,
                catalog_product_ids=["MLM9"],
            ),
        ]
    )
    assert await _status(sweep_db, "catalog_product_snapshots") == (False, latest)


@pytest.mark.asyncio
async def test_other_sellers_and_authorities_do_not_hold_a_sweep(sweep_db: Any) -> None:
    await sweep_db.sheets_formula_recovery_jobs.insert_many(
        [
            {
                **_job("foreign", "item_formula_rows", "running", NOW, inventory_scope=True),
                "seller_id": "999",
            },
            _job(
                "pilot",
                "catalog_buybox_snapshots",
                "pending",
                NOW,
                item_ids=["MLM1"],
                policy_authority="history-on-link-v1",
            ),
        ]
    )
    assert await _status(sweep_db, "item_formula_rows") == (False, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("read_model", ["orders", "catalog_buybox_snapshots"])
async def test_only_inventory_and_catalog_products_have_spaced_sweeps(read_model: str) -> None:
    queue = FormulaRecoveryQueue(defaultdict(lambda: None), now=lambda: NOW)
    with pytest.raises(ValueError, match="sweep"):
        await queue.sweep_status(seller_id=SELLER, read_model=read_model)
