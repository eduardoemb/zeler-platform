"""Full stock operation notifications feed the RETIROS read model."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import ServerSelectionTimeoutError

from zeler_sheets.full_operations import (
    FBM_STOCK_OPERATIONS_EVENT_TYPE,
    FULL_OPERATIONS_COLLECTION,
    FULL_WITHDRAWALS_MARKER_SOURCE,
    acquire_full_operation,
    full_operation_id_from_resource,
)

ROOT = Path(__file__).resolve().parents[3]
SELLER = "82453304"
NOW = datetime(2026, 10, 12, 18, 0, tzinfo=UTC)
MARKER_ID = f"{SELLER}:full_withdrawals"


@pytest_asyncio.fixture
async def database() -> AsyncIterator[AsyncIOMotorDatabase[dict[str, Any]]]:
    # Dedicated loopback test instance; never inherit a production connection.
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        "mongodb://127.0.0.1:27028/?directConnection=true", serverSelectionTimeoutMS=1000
    )
    try:
        await client.admin.command("ping")
    except ServerSelectionTimeoutError:
        client.close()
        pytest.skip("dedicated local Mongo on port 27028 is unavailable")
    db = client[f"zeler_test_full_operations_{uuid4().hex}"]
    for index in json.loads((ROOT / "infra/mongo/indexes/sheets_full_operations.json").read_text()):
        await db[FULL_OPERATIONS_COLLECTION].create_index(
            list(index["keys"].items()), **index["options"]
        )
    # The freshness marker must satisfy the checked-in strict validator.
    schema = json.loads((ROOT / "infra/mongo/schemas/sheets_read_model_freshness.json").read_text())
    await db.create_collection(
        "sheets_read_model_freshness",
        validator={"$jsonSchema": schema["$jsonSchema"]},
        validationLevel=schema["validationLevel"],
        validationAction=schema["validationAction"],
    )
    try:
        yield db
    finally:
        await client.drop_database(db.name)
        client.close()


def operation(
    operation_id: int,
    kind: str,
    *,
    quantity: int = 4,
    created: str = "2026-09-01T10:00:00.000-04:00",
    inventory: str = "INVABC",
    seller: int = int(SELLER),
) -> dict[str, Any]:
    if kind == "WITHDRAWAL_RESERVATION":
        detail = {
            "available_quantity": -quantity,
            "not_available_quantity": quantity,
            "not_available_detail": [{"status": "withdrawal", "quantity": quantity}],
        }
    elif kind.startswith("WITHDRAWAL_"):
        detail = {
            "available_quantity": quantity if kind == "WITHDRAWAL_CANCELATION" else 0,
            "not_available_quantity": -quantity,
            "not_available_detail": [{"status": "withdrawal", "quantity": -quantity}],
        }
    else:
        detail = {"available_quantity": -1, "not_available_quantity": 0, "not_available_detail": []}
    return {
        "id": operation_id,
        "seller_id": seller,
        "date_created": created,
        "type": kind,
        "inventory_id": inventory,
        "detail": detail,
        "result": {"total": 10, "available_quantity": 6, "not_available_quantity": 4},
        "external_references": [],
    }


class Gateway:
    def __init__(self, *operations: dict[str, Any]) -> None:
        self.operations = {str(row["id"]): row for row in operations}
        self.paths: list[str] = []

    async def fetch_resource(self, *, seller_id: Any, path: str) -> dict[str, Any]:
        assert str(seller_id) == SELLER
        self.paths.append(path)
        return self.operations[path.rsplit("/", 1)[-1]]


def test_resource_must_name_one_operation_by_numeric_id() -> None:
    assert full_operation_id_from_resource("/stock/fulfillment/operations/123") == "123"
    for resource in (
        "/stock/fulfillment/operations/search",
        "/stock/fulfillment/operations/12/x",
        "/items/MLM1",
        "",
    ):
        with pytest.raises(ValueError):
            full_operation_id_from_resource(resource)


@pytest.mark.asyncio
async def test_reservation_and_delivery_are_stored_with_observed_coverage(
    database: AsyncIOMotorDatabase[dict[str, Any]],
) -> None:
    gateway = Gateway(
        operation(1001, "WITHDRAWAL_RESERVATION", created="2026-09-01T10:00:00.000-04:00"),
        operation(1002, "WITHDRAWAL_DELIVERY", created="2026-09-03T12:30:00.000-04:00"),
    )

    for operation_id in ("1001", "1002"):
        outcome = await acquire_full_operation(
            db=database,
            gateway=gateway,
            seller_id=SELLER,
            resource=f"/stock/fulfillment/operations/{operation_id}",
            now=NOW,
        )
        assert outcome == "stored"

    assert gateway.paths == [
        "/stock/fulfillment/operations/1001",
        "/stock/fulfillment/operations/1002",
    ]
    rows = await database[FULL_OPERATIONS_COLLECTION].find({}).sort("operation_id").to_list(None)
    assert [(row["_id"], row["type"]) for row in rows] == [
        (f"{SELLER}:1001", "WITHDRAWAL_RESERVATION"),
        (f"{SELLER}:1002", "WITHDRAWAL_DELIVERY"),
    ]
    reservation = rows[0]
    assert reservation["seller_id"] == SELLER
    assert reservation["operation_id"] == "1001"
    assert reservation["inventory_id"] == "INVABC"
    assert reservation["date_created"].replace(tzinfo=UTC) == datetime(2026, 9, 1, 14, tzinfo=UTC)
    assert reservation["detail"]["not_available_detail"] == [
        {"status": "withdrawal", "quantity": 4}
    ]
    assert reservation["source"] == "meli_fbm_stock_operations"
    marker = await database.sheets_read_model_freshness.find_one({"_id": MARKER_ID})
    assert marker is not None
    assert marker["read_model"] == "full_withdrawals"
    assert marker["state"] == "fresh"
    assert marker["coverage_basis"] == "observed_only"
    assert marker["source"] == FULL_WITHDRAWALS_MARKER_SOURCE
    assert marker["date_from"].replace(tzinfo=UTC) == datetime(2026, 9, 1, 14, tzinfo=UTC)
    assert marker["last_event_synced_at"].replace(tzinfo=UTC) == NOW


@pytest.mark.asyncio
async def test_other_operation_types_are_not_stored_but_extend_observed_coverage(
    database: AsyncIOMotorDatabase[dict[str, Any]],
) -> None:
    gateway = Gateway(
        operation(2001, "WITHDRAWAL_RESERVATION", created="2026-09-05T10:00:00Z"),
        operation(2002, "SALE_CONFIRMATION", created="2026-08-29T15:00:00Z"),
    )
    assert (
        await acquire_full_operation(
            db=database,
            gateway=gateway,
            seller_id=SELLER,
            resource="/stock/fulfillment/operations/2001",
            now=NOW,
        )
        == "stored"
    )
    later = NOW + timedelta(hours=1)

    outcome = await acquire_full_operation(
        db=database,
        gateway=gateway,
        seller_id=SELLER,
        resource="/stock/fulfillment/operations/2002",
        now=later,
    )

    assert outcome == "ignored"
    assert await database[FULL_OPERATIONS_COLLECTION].count_documents({}) == 1
    marker = await database.sheets_read_model_freshness.find_one({"_id": MARKER_ID})
    assert marker is not None
    # Any Full notification proves the stream was observed from its creation on.
    assert marker["date_from"].replace(tzinfo=UTC) == datetime(2026, 8, 29, 15, tzinfo=UTC)
    assert marker["last_event_synced_at"].replace(tzinfo=UTC) == later


@pytest.mark.asyncio
async def test_operation_of_another_seller_is_neither_stored_nor_counted_as_coverage(
    database: AsyncIOMotorDatabase[dict[str, Any]],
) -> None:
    gateway = Gateway(operation(3001, "WITHDRAWAL_RESERVATION", seller=42))

    outcome = await acquire_full_operation(
        db=database,
        gateway=gateway,
        seller_id=SELLER,
        resource="/stock/fulfillment/operations/3001",
        now=NOW,
    )

    assert outcome == "seller_mismatch"
    assert await database[FULL_OPERATIONS_COLLECTION].count_documents({}) == 0
    assert await database.sheets_read_model_freshness.count_documents({}) == 0


@pytest.mark.asyncio
async def test_operation_identity_must_match_the_notified_resource(
    database: AsyncIOMotorDatabase[dict[str, Any]],
) -> None:
    class Swapped(Gateway):
        async def fetch_resource(self, *, seller_id: Any, path: str) -> dict[str, Any]:
            return operation(9999, "WITHDRAWAL_RESERVATION")

    with pytest.raises(ValueError):
        await acquire_full_operation(
            db=database,
            gateway=Swapped(),
            seller_id=SELLER,
            resource="/stock/fulfillment/operations/4001",
            now=NOW,
        )
    assert await database[FULL_OPERATIONS_COLLECTION].count_documents({}) == 0


@pytest.mark.asyncio
async def test_repeated_notifications_are_idempotent_and_keep_the_earliest_coverage(
    database: AsyncIOMotorDatabase[dict[str, Any]],
) -> None:
    gateway = Gateway(
        operation(5001, "WITHDRAWAL_RESERVATION", created="2026-09-02T10:00:00Z"),
        operation(5002, "WITHDRAWAL_DELIVERY", created="2026-09-01T10:00:00Z"),
    )
    for resource, now in (
        ("/stock/fulfillment/operations/5001", NOW),
        ("/stock/fulfillment/operations/5002", NOW + timedelta(minutes=1)),
        ("/stock/fulfillment/operations/5001", NOW + timedelta(minutes=2)),
    ):
        await acquire_full_operation(
            db=database, gateway=gateway, seller_id=SELLER, resource=resource, now=now
        )

    assert await database[FULL_OPERATIONS_COLLECTION].count_documents({}) == 2
    marker = await database.sheets_read_model_freshness.find_one({"_id": MARKER_ID})
    assert marker is not None
    assert marker["date_from"].replace(tzinfo=UTC) == datetime(2026, 9, 1, 10, tzinfo=UTC)
    assert marker["last_event_synced_at"].replace(tzinfo=UTC) == NOW + timedelta(minutes=2)


@pytest.mark.asyncio
async def test_a_foreign_marker_is_replaced_by_observed_coverage(
    database: AsyncIOMotorDatabase[dict[str, Any]],
) -> None:
    await database.sheets_read_model_freshness.insert_one(
        {
            "_id": MARKER_ID,
            "seller_id": SELLER,
            "read_model": "full_withdrawals",
            "state": "reconciled",
            "date_from": datetime(2025, 1, 1, tzinfo=UTC),
            "fresh_until": datetime(2025, 2, 1, tzinfo=UTC),
            "coverage_basis": "legacy_imported",
            "source": "zelerdata_read_model_reconcile",
            "updated_at": datetime(2025, 2, 1, tzinfo=UTC),
            "schema_version": 1,
        }
    )

    await acquire_full_operation(
        db=database,
        gateway=Gateway(operation(6001, "WITHDRAWAL_RESERVATION", created="2026-09-02T10:00:00Z")),
        seller_id=SELLER,
        resource="/stock/fulfillment/operations/6001",
        now=NOW,
    )

    marker = await database.sheets_read_model_freshness.find_one({"_id": MARKER_ID})
    assert marker is not None
    assert marker["source"] == FULL_WITHDRAWALS_MARKER_SOURCE
    assert marker["coverage_basis"] == "observed_only"
    assert marker["date_from"].replace(tzinfo=UTC) == datetime(2026, 9, 2, 10, tzinfo=UTC)


@pytest.mark.asyncio
async def test_worker_records_a_full_operation_event_without_history_or_export_work(
    database: AsyncIOMotorDatabase[dict[str, Any]],
) -> None:
    from zeler_sheets.consumer import SheetsEvent, SheetsEventHandler

    gateway = Gateway(operation(7001, "WITHDRAWAL_RESERVATION", created="2026-09-02T10:00:00Z"))
    store = AsyncMock()
    store.is_duplicate.return_value = False
    sheets = AsyncMock()
    handler = SheetsEventHandler(
        db=database, gateway_client=gateway, sheets_client=sheets, idempotency_store=store
    )
    event = SheetsEvent(
        "notification-7001",
        FBM_STOCK_OPERATIONS_EVENT_TYPE,
        int(SELLER),
        "/stock/fulfillment/operations/7001",
        "fbm_stock_operations:/stock/fulfillment/operations/7001:notification-7001",
    )

    assert await handler.handle(event) == "observed"

    assert gateway.paths == ["/stock/fulfillment/operations/7001"]
    assert await database[FULL_OPERATIONS_COLLECTION].count_documents({}) == 1
    store.mark_processed.assert_called_once_with(event.idempotency_key)
    sheets.append_row.assert_not_called()


@pytest.mark.asyncio
async def test_worker_acknowledges_an_operation_of_another_seller_without_storing_it(
    database: AsyncIOMotorDatabase[dict[str, Any]],
) -> None:
    from zeler_sheets.consumer import SheetsEvent, SheetsEventHandler

    store = AsyncMock()
    store.is_duplicate.return_value = False
    handler = SheetsEventHandler(
        db=database,
        gateway_client=Gateway(operation(7002, "WITHDRAWAL_DELIVERY", seller=42)),
        sheets_client=AsyncMock(),
        idempotency_store=store,
    )

    result = await handler.handle(
        SheetsEvent(
            "notification-7002",
            FBM_STOCK_OPERATIONS_EVENT_TYPE,
            int(SELLER),
            "/stock/fulfillment/operations/7002",
            "fbm-7002",
        )
    )

    assert result == "ignored"
    assert await database[FULL_OPERATIONS_COLLECTION].count_documents({}) == 0
    store.mark_processed.assert_called_once_with("fbm-7002")
