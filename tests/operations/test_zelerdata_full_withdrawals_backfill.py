"""Backfill of Full operations from stored fbm_stock_operations notifications."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from infra.operations import zelerdata_full_withdrawals_backfill as backfill
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import ServerSelectionTimeoutError

from zeler_platform_core.clients.meli_gateway_client import GatewayRateLimitError

ROOT = Path(__file__).resolve().parents[2]
SELLER = "82453304"
NOW = datetime(2026, 10, 12, 19, 0, tzinfo=UTC)


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
    db = client[f"zeler_test_full_backfill_{uuid4().hex}"]
    for index in json.loads((ROOT / "infra/mongo/indexes/sheets_full_operations.json").read_text()):
        await db.sheets_full_operations.create_index(
            list(index["keys"].items()), **index["options"]
        )
    try:
        yield db
    finally:
        await client.drop_database(db.name)
        client.close()


def operation(operation_id: int, kind: str, created: str, quantity: int) -> dict[str, Any]:
    sign = 1 if kind == "WITHDRAWAL_RESERVATION" else -1
    return {
        "id": operation_id,
        "seller_id": int(SELLER),
        "date_created": created,
        "type": kind,
        "inventory_id": "INVABC",
        "detail": {
            "not_available_quantity": sign * quantity,
            "not_available_detail": [{"status": "withdrawal", "quantity": sign * quantity}],
        },
        "result": {},
        "external_references": [],
    }


class Gateway:
    def __init__(self, failures: dict[str, Exception] | None = None) -> None:
        self.operations = {
            "11": operation(11, "SALE_CONFIRMATION", "2026-08-29T16:15:00Z", 1),
            "12": operation(12, "WITHDRAWAL_RESERVATION", "2026-09-02T15:00:00Z", 6),
            "13": operation(13, "WITHDRAWAL_DELIVERY", "2026-09-04T15:00:00Z", 6),
        }
        self.failures = failures or {}
        self.paths: list[str] = []

    async def fetch_resource(self, *, seller_id: Any, path: str) -> dict[str, Any]:
        assert str(seller_id) == SELLER
        self.paths.append(path)
        operation_id = path.rsplit("/", 1)[-1]
        if operation_id in self.failures:
            raise self.failures[operation_id]
        return self.operations[operation_id]


async def seed_notifications(db: AsyncIOMotorDatabase[dict[str, Any]]) -> None:
    received = datetime(2026, 8, 29, 16, 16, tzinfo=UTC)
    rows = [
        ("n1", SELLER, "/stock/fulfillment/operations/11", received),
        ("n2", SELLER, "/stock/fulfillment/operations/12", received + timedelta(days=4)),
        # Mercado Libre may notify the same operation twice.
        ("n3", SELLER, "/stock/fulfillment/operations/12", received + timedelta(days=4)),
        ("n4", SELLER, "/stock/fulfillment/operations/13", received + timedelta(days=6)),
        ("n5", SELLER, "/stock/fulfillment/operations/search", received + timedelta(days=7)),
        ("n6", "42", "/stock/fulfillment/operations/99", received + timedelta(days=7)),
    ]
    await db.webhook_events.insert_many(
        [
            {
                "_id": event_id,
                "topic": "fbm_stock_operations",
                "user_id": int(seller),
                "resource": resource,
                "received_at": received_at,
                "published_at": None,
                "raw_body": {"resource": resource},
                "schema_version": 1,
            }
            for event_id, seller, resource, received_at in rows
        ]
        + [
            {
                "_id": "items-1",
                "topic": "items",
                "user_id": int(SELLER),
                "resource": "/items/MLM1",
                "received_at": received,
            }
        ]
    )


async def run(
    db: AsyncIOMotorDatabase[dict[str, Any]], gateway: Gateway, *, execute: bool, limit: int = 50
) -> dict[str, Any]:
    async def no_sleep(_seconds: float) -> None:
        return None

    return await backfill.backfill_full_withdrawals(
        db=db,
        gateway=gateway,
        seller_id=SELLER,
        limit=limit,
        execute=execute,
        now_fn=lambda: NOW,
        sleep=no_sleep,
    )


@pytest.mark.asyncio
async def test_dry_run_plans_from_stored_notifications_without_reading_or_writing(
    database: AsyncIOMotorDatabase[dict[str, Any]],
) -> None:
    await seed_notifications(database)
    gateway = Gateway()

    report = await run(database, gateway, execute=False)

    assert gateway.paths == []
    assert await database.sheets_full_operations.count_documents({}) == 0
    assert await database.sheets_read_model_freshness.count_documents({}) == 0
    assert report["mode"] == "dry_run"
    assert report["notifications"] == 5
    assert report["operations"] == 3
    assert report["invalid_resources"] == 1
    assert report["already_stored"] == 0
    assert report["truncated"] is False
    assert report["oldest_notification_at"] == "2026-08-29T16:16:00+00:00"
    assert report["fetched"] == 0
    assert report["summary"]["coverage_from"] is None


@pytest.mark.asyncio
async def test_execute_reads_each_operation_once_and_is_idempotent(
    database: AsyncIOMotorDatabase[dict[str, Any]],
) -> None:
    await seed_notifications(database)
    gateway = Gateway()

    first = await run(database, gateway, execute=True)
    stored_first = await database.sheets_full_operations.find({}, {"_id": 1}).to_list(None)
    marker_first = await database.sheets_read_model_freshness.find_one({})
    second = await run(database, gateway, execute=True)

    assert (
        gateway.paths
        == [
            "/stock/fulfillment/operations/11",
            "/stock/fulfillment/operations/12",
            "/stock/fulfillment/operations/13",
        ]
        * 2
    )
    assert first["outcomes"] == {"ignored": 1, "stored": 2}
    assert first["errors"] == {}
    assert first["stopped_reason"] is None
    assert second["already_stored"] == 2
    assert second["outcomes"] == first["outcomes"]
    assert await database.sheets_full_operations.find({}, {"_id": 1}).to_list(None) == (
        stored_first
    )
    marker_second = await database.sheets_read_model_freshness.find_one({})
    assert marker_first is not None and marker_second is not None
    assert marker_second["date_from"] == marker_first["date_from"]
    assert first["summary"] == {
        "coverage_from": "2026-08-29T16:15:00+00:00",
        "operations_by_type": {"WITHDRAWAL_DELIVERY": 1, "WITHDRAWAL_RESERVATION": 1},
        "withdrawals_by_status": {"Entregado": 1},
        "unmatched_by_type": {},
        "approximate_rows": 0,
    }


@pytest.mark.asyncio
async def test_execute_counts_missing_operations_and_stops_at_the_quota(
    database: AsyncIOMotorDatabase[dict[str, Any]],
) -> None:
    await seed_notifications(database)
    request = httpx.Request("GET", "http://gateway/proxy/meli/stock/fulfillment/operations/x")
    gateway = Gateway(
        {
            "11": httpx.HTTPStatusError(
                "missing", request=request, response=httpx.Response(404, request=request)
            ),
            "12": GatewayRateLimitError(
                retry_after_seconds=5, response=httpx.Response(429, request=request)
            ),
        }
    )

    report = await run(database, gateway, execute=True)

    assert gateway.paths == [
        "/stock/fulfillment/operations/11",
        "/stock/fulfillment/operations/12",
    ]
    assert report["errors"] == {"http_404": 1}
    assert report["stopped_reason"] == "rate_limited"
    assert report["fetched"] == 2
    assert await database.sheets_full_operations.count_documents({}) == 0


@pytest.mark.asyncio
async def test_selection_is_bounded_and_reports_truncation(
    database: AsyncIOMotorDatabase[dict[str, Any]],
) -> None:
    await seed_notifications(database)

    report = await run(database, Gateway(), execute=False, limit=2)

    assert report["notifications"] == 2
    assert report["truncated"] is True


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["--seller-id", SELLER], "APPROVED_RUNTIME_CONFIRMATION_REQUIRED"),
        (
            ["--seller-id", SELLER, "--confirm-approved-runtime", "--execute"],
            "PRODUCTION_WRITE_CONFIRMATION_REQUIRED",
        ),
        (
            ["--seller-id", SELLER, "--confirm-approved-runtime", "--confirm-production-write"],
            "PRODUCTION_WRITE_CONFIRMATION_REQUIRES_EXECUTE",
        ),
        (["--seller-id", "abc", "--confirm-approved-runtime"], "INVALID_SELLER"),
        (["--seller-id", SELLER, "--confirm-approved-runtime", "--limit", "0"], "INVALID_LIMIT"),
        (
            ["--seller-id", SELLER, "--confirm-approved-runtime", "--limit", "5001"],
            "INVALID_LIMIT",
        ),
    ],
)
def test_cli_refuses_before_touching_any_runtime(
    argv: list[str], message: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert backfill.main(argv) == 2
    assert capsys.readouterr().err.strip() == message
