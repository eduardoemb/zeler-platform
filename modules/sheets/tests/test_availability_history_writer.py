from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import ServerSelectionTimeoutError, WriteError

from zeler_sheets.availability_history import (
    AVAILABILITY_TRANSITIONS_COLLECTION,
    record_availability_observation,
)

ROOT = Path(__file__).resolve().parents[3]
SELLER = "82453304"
T0 = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def db() -> AsyncIterator[AsyncIOMotorDatabase[dict[str, Any]]]:
    # Dedicated loopback test instance; never inherit a production connection.
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        "mongodb://127.0.0.1:27028/?directConnection=true", serverSelectionTimeoutMS=1000
    )
    database = client[f"zeler_availability_test_{uuid4().hex}"]
    try:
        try:
            await client.admin.command("ping")
        except ServerSelectionTimeoutError:
            pytest.skip("dedicated local Mongo on port 27028 is unavailable")
        validator = json.loads(
            (ROOT / "infra/mongo/schemas/sheets_item_availability_transitions.json").read_text()
        )
        await database.create_collection(
            AVAILABILITY_TRANSITIONS_COLLECTION,
            validator={"$jsonSchema": validator["$jsonSchema"]},
            validationLevel=validator["validationLevel"],
            validationAction=validator["validationAction"],
        )
        for index in json.loads(
            (ROOT / "infra/mongo/indexes/sheets_item_availability_transitions.json").read_text()
        ):
            await database[AVAILABILITY_TRANSITIONS_COLLECTION].create_index(
                list(index["keys"].items()), **index["options"]
            )
        yield database
    finally:
        await client.drop_database(database.name)
        client.close()


def _item(
    *, status: str = "active", stock: int | None = 3, variations: list[Any] | None = None
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "_id": "MLM1",
        "seller_id": SELLER,
        "status": status,
        "available_quantity": stock,
        "attributes": [{"id": "SELLER_SKU", "value_name": "SKU-1"}],
    }
    if variations is not None:
        item["variations"] = variations
    return item


def _variation(variation_id: int, *, stock: int, sku: str) -> dict[str, Any]:
    return {
        "id": variation_id,
        "available_quantity": stock,
        "attributes": [{"id": "SELLER_SKU", "value_name": sku}],
    }


async def _record(db: Any, item: dict[str, Any], observed_at: datetime) -> int:
    return await record_availability_observation(
        db, item, seller_id=SELLER, observed_at=observed_at, source="sheets_event_persistence"
    )


async def _rows(db: Any) -> list[dict[str, Any]]:
    cursor = db[AVAILABILITY_TRANSITIONS_COLLECTION].find({}, {"_id": 0})
    rows = await cursor.sort([("variation_id", 1), ("observed_at", 1)]).to_list(length=None)
    return [
        {**row, "observed_at": row["observed_at"].replace(tzinfo=UTC)}
        for row in rows
        if isinstance(row["observed_at"], datetime)
    ]


@pytest.mark.asyncio
async def test_only_availability_changes_append_rows(db: Any) -> None:
    observations = [
        (_item(stock=3), 1),  # first observation opens the series
        (_item(stock=5), 0),  # more stock, still available
        (_item(stock=0), 1),  # stock out
        (_item(status="paused", stock=4), 0),  # paused: still unavailable
        (_item(status="active", stock=4), 1),  # available again
        (_item(status="under_review", stock=4), 1),
    ]
    for minutes, (item, expected) in enumerate(observations):
        assert await _record(db, item, T0 + timedelta(minutes=10 * minutes)) == expected

    rows = await _rows(db)

    assert [(row["available"], row["status"], row["available_quantity"]) for row in rows] == [
        (True, "active", 3),
        (False, "active", 0),
        (True, "active", 4),
        (False, "under_review", 4),
    ]
    assert rows[0] == {
        "seller_id": SELLER,
        "item_id": "MLM1",
        "variation_id": None,
        "sku": "SKU-1",
        "available": True,
        "status": "active",
        "available_quantity": 3,
        "observed_at": T0,
        "source": "sheets_event_persistence",
        "schema_version": 1,
    }


@pytest.mark.asyncio
async def test_retried_and_concurrent_observations_write_one_row(db: Any) -> None:
    out_of_stock = _item(stock=0)

    written = await asyncio.gather(*(_record(db, out_of_stock, T0) for _ in range(4)))
    assert await _record(db, out_of_stock, T0) == 0

    assert sum(written) == 1
    assert len(await _rows(db)) == 1


@pytest.mark.asyncio
async def test_observation_not_newer_than_the_log_is_ignored(db: Any) -> None:
    assert await _record(db, _item(stock=0), T0) == 1

    assert await _record(db, _item(stock=9), T0 - timedelta(minutes=1)) == 0
    assert await _record(db, _item(stock=9), T0) == 0

    assert [row["available"] for row in await _rows(db)] == [False]


@pytest.mark.asyncio
async def test_unknown_stock_or_status_is_not_recorded(db: Any) -> None:
    assert await _record(db, _item(stock=None), T0) == 0
    assert await _record(db, _item(status=""), T0) == 0
    assert await _record(db, {"_id": "", "status": "active", "available_quantity": 1}, T0) == 0

    assert await _rows(db) == []


@pytest.mark.asyncio
async def test_variations_keep_one_series_each(db: Any) -> None:
    def item(status: str, red: int, blue: int) -> dict[str, Any]:
        return _item(
            status=status,
            stock=red + blue,
            variations=[
                _variation(11, stock=red, sku="SKU-RED"),
                _variation(22, stock=blue, sku="SKU-BLUE"),
                {"available_quantity": 4},  # no identity: never a series
            ],
        )

    assert await _record(db, item("active", 2, 0), T0) == 2
    assert await _record(db, item("active", 1, 0), T0 + timedelta(minutes=10)) == 0
    assert await _record(db, item("active", 1, 6), T0 + timedelta(minutes=20)) == 1
    assert await _record(db, item("paused", 1, 6), T0 + timedelta(minutes=30)) == 2

    rows = await _rows(db)

    assert [(row["variation_id"], row["sku"], row["available"]) for row in rows] == [
        ("11", "SKU-RED", True),
        ("11", "SKU-RED", False),
        ("22", "SKU-BLUE", False),
        ("22", "SKU-BLUE", True),
        ("22", "SKU-BLUE", False),
    ]
    assert all(row["variation_id"] is not None for row in rows)


@pytest.mark.asyncio
async def test_rows_satisfy_the_strict_exported_validator(db: Any) -> None:
    assert await _record(db, _item(stock=2), T0) == 1

    with pytest.raises(WriteError):
        await db[AVAILABILITY_TRANSITIONS_COLLECTION].insert_one(
            {"_id": "bad", "seller_id": SELLER, "item_id": "MLM1", "observed_at": T0}
        )
