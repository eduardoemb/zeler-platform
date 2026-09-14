from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
import pytest_asyncio
from bson import BSON
from motor.motor_asyncio import AsyncIOMotorClient

from zeler_sheets.formulas import read_models
from zeler_sheets.formulas.dispatcher import FormulaDataUnavailableError
from zeler_sheets.item_projection import item_source_fingerprint

NOW = datetime(2026, 9, 14, 20, tzinfo=UTC)


class CountedDb:
    def __init__(self, db: Any) -> None:
        self.db = db
        self.source_reads = 0
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.finished = 0
        self.fail = False

    def __getitem__(self, name: str) -> Any:
        collection = self.db[name]
        if name != "items":
            return collection
        owner = self

        class Collection:
            def find(self, query: Any) -> Any:
                cursor = collection.find(query)
                owner.source_reads += 1

                class Cursor:
                    async def to_list(self, length: int) -> Any:
                        owner.entered.set()
                        try:
                            await owner.release.wait()
                            if owner.fail:
                                raise RuntimeError("source unavailable")
                            return await cursor.to_list(length=length)
                        finally:
                            owner.finished += 1

                return Cursor()

        return Collection()


@pytest_asyncio.fixture
async def database(default_mongo_uri: str) -> Any:
    # Follow the verified test target while rejecting every non-loopback Mongo host.
    parsed = urlsplit(default_mongo_uri)
    assert parsed.scheme == "mongodb" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    assert "," not in parsed.netloc
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        default_mongo_uri, serverSelectionTimeoutMS=3000
    )
    assert (await client.admin.command("hello"))["isWritablePrimary"]
    db = client[f"item_read_acquisition_test_{uuid4().hex}"]
    try:
        yield CountedDb(db)
    finally:
        await client.drop_database(db.name)
        client.close()


async def seed(db: CountedDb, count: int = 2, payload: bool = False) -> list[str]:
    sources = []
    rows = []
    for i in range(count):
        source = {"_id": f"ITEM{i}", "seller_id": "seller", "last_meli_sync_at": NOW}
        if payload:
            source["attributes"] = [
                {"id": str(j), "value_name": "x" * 80, "values": [{"name": "value"}]}
                for j in range(65)
            ]
        sources.append(source)
        variants = 2 if payload and i < 973 else 1
        for variation in range(variants):
            current: dict[str, Any] = {"price": 10, "nested": {"value": "original"}}
            if payload:
                # Match measured production projections: ~4.45 KB, nested acquisition states.
                current["enrichment_state"] = {
                    f"field{j}": {
                        "status": "trusted",
                        "source": "/synthetic/resource",
                        "synced_at": NOW,
                        "reason": "observed",
                        "basis": {"title": "t" * 80, "value": "v" * 140},
                    }
                    for j in range(10)
                }
                current["title"] = "Synthetic owned publication " + "t" * 270
            rows.append(
                {
                    "_id": f"row{i}-{variation}",
                    "seller_id": "seller",
                    "item_id": source["_id"],
                    "variation_id": variation,
                    "current": current,
                    "source_snapshot": {
                        "fingerprint": item_source_fingerprint(source),
                        "observed_at": NOW,
                        "rows_count": variants,
                    },
                }
            )
    if payload:
        assert 18_000_000 < sum(len(BSON.encode(s)) for s in sources) < 23_000_000
        assert 12_000_000 < sum(len(BSON.encode(row)) for row in rows) < 14_000_000
    await db.db.items.insert_many(sources)
    await db.db.sheets_item_formula_rows.insert_many(rows)
    return [str(s["_id"]) for s in sources]


def repository(db: CountedDb, acquisitions: Any = None) -> Any:
    kwargs: dict[str, Any] = {"db": db}
    if acquisitions is not None:
        kwargs["item_acquisitions"] = acquisitions
    return read_models.FormulaReadModelRepository(**kwargs)


async def read(repo: Any, ids: list[str], now: datetime = NOW, seller: str = "seller") -> Any:
    return await repo.find_recent_item_formula_rows(
        seller_id=seller,
        item_ids=ids,
        formula="CALIDAD",
        now=now,
    )


@pytest.mark.asyncio
async def test_seven_concurrent_real_inventory_reads_share_19mb_acquisition(
    database: Any, monkeypatch: Any
) -> None:
    ids = await seed(database, 1900, payload=True)
    fingerprint_calls = 0
    original_fingerprint = item_source_fingerprint

    def fingerprint(source: Any) -> str:
        nonlocal fingerprint_calls
        fingerprint_calls += 1
        return original_fingerprint(source)

    monkeypatch.setattr(read_models, "item_source_fingerprint", fingerprint)
    factory = getattr(read_models, "ItemReadAcquisitions", lambda **_: None)
    acquisitions = factory(db=database)
    database.release.clear()
    tasks = [asyncio.create_task(read(repository(database, acquisitions), ids)) for _ in range(7)]
    await database.entered.wait()
    # Model the measured slow VM read while retaining a real ~19 MB Mongo payload.
    async with asyncio.timeout(25):
        await asyncio.sleep(13)
        database.release.set()
        results = await asyncio.gather(*tasks)
    assert all(len(rows) == 2873 and missing == () for rows, missing in results)
    assert database.source_reads == 1
    assert fingerprint_calls == 1900
    results[0][0][0]["current"]["nested"]["value"] = "changed"
    assert results[1][0][0]["current"]["nested"]["value"] == "original"


@pytest.mark.asyncio
async def test_per_request_freshness_and_no_completed_cache(database: Any) -> None:
    ids = await seed(database)
    acquisitions = read_models.ItemReadAcquisitions(db=database)
    repo = repository(database, acquisitions)
    database.release.clear()
    good = asyncio.create_task(read(repo, ids))
    expired = asyncio.create_task(read(repo, ids, NOW + timedelta(minutes=15)))
    future = asyncio.create_task(read(repo, ids, NOW - timedelta(seconds=1)))
    await database.entered.wait()
    database.release.set()
    assert len((await good)[0]) == 2
    for task in (expired, future):
        with pytest.raises(FormulaDataUnavailableError):
            await task
    assert database.source_reads == 1
    await database.db.items.update_one({"_id": ids[0]}, {"$set": {"changed": True}})
    rows, missing = await read(repo, ids)
    assert missing == (ids[0],) and len(rows) == 1
    assert database.source_reads == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_last", [False, True])
async def test_cancellation_one_waiter_preserves_other_last_drains(
    database: Any, cancel_last: bool
) -> None:
    ids = await seed(database)
    acquisitions = read_models.ItemReadAcquisitions(db=database)
    repo = repository(database, acquisitions)
    database.release.clear()
    first = asyncio.create_task(read(repo, ids))
    second = asyncio.create_task(read(repo, ids))
    await database.entered.wait()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert database.finished == 0 and not second.done()
    if not cancel_last:
        database.release.set()
        assert len((await second)[0]) == 2
        assert database.source_reads == 1 and database.finished == 1
        return
    second.cancel()
    with pytest.raises(asyncio.CancelledError):
        await second
    assert database.finished == 1
    database.release.set()
    assert len((await read(repo, ids))[0]) == 2
    assert database.source_reads == 2


@pytest.mark.asyncio
async def test_errors_release_flight_and_different_keys_do_not_share(database: Any) -> None:
    ids = await seed(database)
    acquisitions = read_models.ItemReadAcquisitions(db=database)
    repo = repository(database, acquisitions)
    database.release.clear()
    database.fail = True
    tasks = [asyncio.create_task(read(repo, ids)) for _ in range(2)]
    await database.entered.wait()
    database.release.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    assert all(isinstance(result, RuntimeError) for result in results)
    assert database.finished == 1
    database.fail = False
    distinct_results: Any = await asyncio.gather(
        read(repo, ids[:1]),
        read(repo, ids[1:]),
        read(repo, ids, seller="other"),
        return_exceptions=True,
    )
    assert len(distinct_results[0][0]) == len(distinct_results[1][0]) == 1
    assert isinstance(distinct_results[2], FormulaDataUnavailableError)
    assert database.source_reads == 4


@pytest.mark.asyncio
async def test_database_owner_and_shutdown(database: Any) -> None:
    ids = await seed(database)
    acquisitions = read_models.ItemReadAcquisitions(db=database)
    with pytest.raises(ValueError, match="database"):
        repository(CountedDb(database.db), acquisitions)
    repo = repository(database, acquisitions)
    database.release.clear()
    pending = asyncio.create_task(read(repo, ids))
    await database.entered.wait()
    await acquisitions.aclose()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert database.finished == 1
    with pytest.raises(RuntimeError, match="closed"):
        await read(repo, ids)


@pytest.mark.asyncio
async def test_runtime_dispatchers_share_only_their_app_and_shutdown(
    database: Any, monkeypatch: Any
) -> None:
    from starlette.requests import Request

    from zeler_sheets import api
    from zeler_sheets.app import build_app

    ids = await seed(database)
    captured = []
    original = read_models.FormulaReadModelRepository

    def capture(**kwargs: Any) -> Any:
        repo = original(**kwargs)
        captured.append(repo)
        return repo

    monkeypatch.setattr(api, "FormulaReadModelRepository", capture)
    app = build_app(mongo_db=database)
    other_app = build_app(mongo_db=database)
    for owner in (app, app, other_app):
        api._runtime_dispatcher(Request({"type": "http", "app": owner}), None, now=lambda: NOW)
    database.release.clear()
    tasks = [asyncio.create_task(read(repo, ids)) for repo in captured]
    await database.entered.wait()
    await asyncio.sleep(0.03)
    for shutdown in app.router.on_shutdown:
        await shutdown()
    results = await asyncio.wait_for(asyncio.gather(*tasks[:2], return_exceptions=True), 0.5)
    assert all(isinstance(result, asyncio.CancelledError) for result in results)
    assert not tasks[2].done()
    database.release.set()
    assert len((await tasks[2])[0]) == 2
    assert database.source_reads == 2
    for shutdown in other_app.router.on_shutdown:
        await shutdown()


@pytest.mark.asyncio
async def test_compact_evidence_keeps_price_variants_and_full_fingerprint(database: Any) -> None:
    from zeler_sheets.formulas.pricing import acquired_current_price

    ids = await seed(database)
    for identity in ids:
        source = await database.db.items.find_one({"_id": identity})
        source.update(
            {
                "attributes": [{"value": "large irrelevant attribute"}],
                "catalog_listing": True,
                "catalog_product_id": "MLM123",
                "title": "Owned item",
                "available_quantity": 3,
                "variations": [{"id": 7, "catalog_product_id": "MLM456"}],
                "price": 100,
                "currency_id": "MXN",
                "enrichment_state": {
                    "current_promotion": {
                        "status": "authoritative_absent",
                        "source": "/items/{id}/sale_price",
                        "synced_at": NOW,
                    }
                },
            }
        )
        await database.db.items.replace_one({"_id": identity}, source)
        await database.db.sheets_item_formula_rows.update_one(
            {"item_id": identity},
            {"$set": {"source_snapshot.fingerprint": item_source_fingerprint(source)}},
        )
    repo = repository(database)
    database.release.clear()

    async def evidence() -> Any:
        return await repo._find_recent_item_rows_with_sources(
            seller_id="seller", item_ids=ids, formula="CATALOGO", now=NOW
        )

    first = asyncio.create_task(evidence())
    second = asyncio.create_task(evidence())
    await database.entered.wait()
    database.release.set()
    one, two = await asyncio.gather(first, second)
    source = one[2][0]
    assert "attributes" not in source
    assert source["catalog_product_id"] == "MLM123"
    assert source["variations"][0]["catalog_product_id"] == "MLM456"
    assert source["title"] == "Owned item" and source["available_quantity"] == 3
    assert acquired_current_price(source) == 100
    source["variations"][0]["catalog_product_id"] = "changed"
    assert two[2][0]["variations"][0]["catalog_product_id"] == "MLM456"
    await database.db.items.update_one(
        {"_id": ids[0]}, {"$set": {"attributes": [{"value": "changed omitted field"}]}}
    )
    rows, missing = await read(repo, ids)
    assert len(rows) == 1 and missing == (ids[0],)
