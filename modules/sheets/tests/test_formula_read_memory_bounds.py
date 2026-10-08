"""Whole-inventory reads must hold memory proportional to the evidence, not the documents.

A seller with ~1.9k publications has ~30 KB canonical item documents. Reading them all
into lists peaked near 300 MB per formula read in the long-lived worker; glibc keeps
that fragmented memory, so each sweep ratcheted the process up until the VM froze.
"""

from __future__ import annotations

import gc
import tracemalloc
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ServerSelectionTimeoutError

from zeler_sheets.formulas.read_models import FormulaReadModelRepository, ItemReadAcquisitions
from zeler_sheets.item_projection import stamp_item_projection

SELLER = "82453304"
NOW = datetime.now(UTC).replace(microsecond=0)


@pytest_asyncio.fixture
async def memory_db() -> AsyncIterator[Any]:
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        "mongodb://127.0.0.1:27028/?directConnection=true", serverSelectionTimeoutMS=1000
    )
    db = client[f"zeler_read_memory_test_{uuid4().hex}"]
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


def _item(index: int) -> dict[str, Any]:
    return {
        "_id": f"MLA{index:06d}",
        "seller_id": SELLER,
        "title": f"Publicacion {index}",
        "status": "active",
        "price": 100,
        "available_quantity": 1,
        "last_meli_sync_at": NOW,
        "catalog_listing": False,
        "attributes": [
            {"id": f"A{k}", "name": "n" * 30, "value_name": "v" * 40, "values": [{"id": str(k)}]}
            for k in range(120)
        ],
        "pictures": [{"id": f"P{k}", "url": "http://x/" + "u" * 80} for k in range(30)],
        "variations": [],
    }


async def _seed(db: Any, count: int) -> list[str]:
    items = [_item(index) for index in range(count)]
    rows = []
    for item in items:
        row = {
            "_id": f"{SELLER}:sku{item['_id']}:{item['_id']}",
            "seller_id": SELLER,
            "sku": f"SKU{item['_id']}",
            "normalized_sku": f"sku{item['_id']}".lower(),
            "item_id": item["_id"],
            "variation_id": None,
            "inventory_id": None,
            "current": {"title": item["title"], "status": "active"},
        }
        stamp_item_projection([row], item)
        rows.append(row)
    await db["items"].insert_many(items)
    await db["sheets_item_formula_rows"].insert_many(rows)
    return [item["_id"] for item in items]


async def _peak_of(call: Any) -> int:
    gc.collect()
    tracemalloc.start()
    try:
        result = await call()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    del result
    return peak


@pytest.mark.asyncio
async def test_inventory_item_read_peak_does_not_scale_with_source_documents(
    memory_db: Any,
) -> None:
    identities = await _seed(memory_db, 300)
    acquisitions = ItemReadAcquisitions(db=memory_db)

    async def read() -> Any:
        return await acquisitions.acquire(seller_id=SELLER, item_ids=identities)

    peak = await _peak_of(read)
    cut = await read()

    # 300 documents of ~30 KB hold ~45 MB once decoded; evidence and rows need far less.
    assert len(cut.sources) == 300 and len(cut.fingerprints) == 300
    assert peak < 12_000_000


@pytest.mark.asyncio
async def test_catalog_source_verification_streams_item_documents(memory_db: Any) -> None:
    identities = await _seed(memory_db, 300)
    repository = FormulaReadModelRepository(db=memory_db)
    rows = await memory_db["sheets_item_formula_rows"].find({"seller_id": SELLER}).to_list(None)

    async def verify() -> Any:
        return await repository.find_recent_catalog_buybox_inventory(
            seller_id=SELLER,
            formula="ZELERDATA_CATALOGOBUYBOX",
            now=NOW,
            inventory=(rows, identities, (), True),
        )

    peak = await _peak_of(verify)

    assert peak < 12_000_000


@pytest.mark.asyncio
async def test_inventory_sweep_retains_nothing_between_passes(memory_db: Any) -> None:
    from urllib.parse import parse_qs, urlparse

    from zeler_sheets.formulas.recovery import (
        IMPLEMENTED_MODELS,
        FormulaRecoveryQueue,
        ItemInventoryRecoveryRequest,
    )
    from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker

    identities = [f"MLA{index:06d}" for index in range(100)]

    class Gateway:
        async def fetch_resource(self, *, seller_id: str, path: str) -> Any:
            if path.startswith(f"/users/{SELLER}/items/search?"):
                return {"paging": {"total": len(identities)}, "results": identities}
            assert path.startswith("/items?ids=")
            batch = parse_qs(urlparse(path).query)["ids"][0].split(",")
            return [
                {
                    "code": 200,
                    "body": {
                        "id": identity,
                        "seller_id": int(SELLER),
                        "title": f"Publicacion {identity}",
                        "price": 100,
                        "base_price": 100,
                        "currency_id": "ARS",
                        "category_id": "MLA123",
                        "available_quantity": 1,
                        "status": "active",
                        "listing_type_id": "gold_special",
                        "date_created": "2026-09-01T00:00:00Z",
                        "last_updated": "2026-09-01T00:00:00Z",
                        "attributes": _item(0)["attributes"],
                        "variations": [],
                        "shipping": {"free_shipping": False},
                    },
                }
                for identity in batch
            ]

    queue = FormulaRecoveryQueue(
        memory_db, enabled_models=IMPLEMENTED_MODELS, allowed_sellers=frozenset({SELLER})
    )
    worker = FormulaRecoveryWorker(db=memory_db, gateway=Gateway(), queue=queue)
    request = ItemInventoryRecoveryRequest(SELLER)

    async def sweep() -> None:
        await queue.enqueue(request)
        for _ in range(len(identities) // 20 + 3):
            await worker.process_one()
        job = await queue.collection.find_one({"_id": request.key})
        assert job is not None and job["state"] == "completed"
        await queue.collection.delete_one({"_id": request.key})

    await sweep()  # warm lazy imports and driver state
    gc.collect()
    tracemalloc.start()
    try:
        retained = []
        for _ in range(3):
            await sweep()
            gc.collect()
            retained.append(tracemalloc.get_traced_memory()[0])
    finally:
        tracemalloc.stop()

    assert retained[2] - retained[0] < 300_000
