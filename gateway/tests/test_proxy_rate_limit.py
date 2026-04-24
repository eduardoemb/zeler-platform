from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from bson import Int64
from dotenv import load_dotenv
from infra.mongo.apply_validators import DEFAULT_MONGO_URI, apply_validators
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from zeler_gateway.proxy.rate_limit import RateLimitCounter, RateLimitExceeded

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS_DIR = ROOT / "infra" / "mongo" / "schemas"
load_dotenv(ROOT / ".env")


@pytest.fixture
def rate_limit_db() -> Iterator[Any]:
    mongo_uri = os.environ.get("MONGO_URI", DEFAULT_MONGO_URI)
    sync_client: MongoClient[dict[str, Any]] = MongoClient(
        mongo_uri, serverSelectionTimeoutMS=1000, tz_aware=True
    )
    try:
        sync_client.admin.command("ping")
    except PyMongoError as exc:  # pragma: no cover - only for machines without local Docker Mongo
        pytest.skip(f"local Mongo is not available: {exc}")

    sync_db = sync_client.get_default_database()
    sync_db.drop_collection("rate_limit_counters")
    apply_validators(mongo_uri, SCHEMAS_DIR)
    async_client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        mongo_uri, serverSelectionTimeoutMS=1000, tz_aware=True
    )

    yield async_client.get_default_database(), sync_db

    sync_db.drop_collection("rate_limit_counters")
    async_client.close()
    sync_client.close()


@pytest.mark.asyncio
async def test_first_request_creates_counter(rate_limit_db: Any) -> None:
    async_db, sync_db = rate_limit_db
    counter = RateLimitCounter(async_db)

    await counter.check_and_increment(module_id="repricer", seller_id=123456789)

    doc = sync_db.rate_limit_counters.find_one({"_id": "repricer:123456789"})
    assert doc is not None
    assert doc["module_id"] == "repricer"
    assert doc["seller_id"] == 123456789
    assert doc["count"] == 1


@pytest.mark.asyncio
async def test_count_increments_within_window(rate_limit_db: Any) -> None:
    async_db, sync_db = rate_limit_db
    now = datetime(2026, 4, 24, 12, 0, 5, tzinfo=UTC)
    counter = RateLimitCounter(async_db, now_fn=lambda: now)

    await counter.check_and_increment(module_id="repricer", seller_id=123456789)
    await counter.check_and_increment(module_id="repricer", seller_id=123456789)

    doc = sync_db.rate_limit_counters.find_one({"_id": "repricer:123456789"})
    assert doc["count"] == 2


@pytest.mark.asyncio
async def test_window_rollover_resets_count(rate_limit_db: Any) -> None:
    async_db, sync_db = rate_limit_db
    current = datetime(2026, 4, 24, 12, 0, 59, tzinfo=UTC)
    counter = RateLimitCounter(async_db, now_fn=lambda: current)

    await counter.check_and_increment(module_id="repricer", seller_id=123456789)
    await counter.check_and_increment(module_id="repricer", seller_id=123456789)
    current = current + timedelta(seconds=2)
    await counter.check_and_increment(module_id="repricer", seller_id=123456789)

    doc = sync_db.rate_limit_counters.find_one({"_id": "repricer:123456789"})
    assert doc["count"] == 1
    assert doc["window_start"] == datetime(2026, 4, 24, 12, 1, tzinfo=UTC)


@pytest.mark.asyncio
async def test_exceeding_limit_raises_with_retry_after(rate_limit_db: Any) -> None:
    async_db, _ = rate_limit_db
    now = datetime(2026, 4, 24, 12, 0, 30, tzinfo=UTC)
    counter = RateLimitCounter(async_db, default_limit=60, now_fn=lambda: now)

    for _ in range(60):
        await counter.check_and_increment(module_id="repricer", seller_id=123456789)

    with pytest.raises(RateLimitExceeded) as exc_info:
        await counter.check_and_increment(module_id="repricer", seller_id=123456789)

    assert 0 < exc_info.value.retry_after_s <= 60


@pytest.mark.asyncio
async def test_different_keys_have_independent_counters(rate_limit_db: Any) -> None:
    async_db, sync_db = rate_limit_db
    counter = RateLimitCounter(async_db)

    await counter.check_and_increment(module_id="repricer", seller_id=123456789)
    await counter.check_and_increment(module_id="repricer", seller_id=987654321)

    first = sync_db.rate_limit_counters.find_one({"_id": "repricer:123456789"})
    second = sync_db.rate_limit_counters.find_one({"_id": "repricer:987654321"})
    assert first["count"] == 1
    assert second["count"] == 1
    assert isinstance(first["seller_id"], Int64)
