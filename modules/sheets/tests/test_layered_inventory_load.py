"""Deterministic source workload, real Mongo projections; not a production SLA."""

from __future__ import annotations

import asyncio
import time
from collections import Counter
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from test_formula_recovery import recovery_db  # noqa: F401
from test_sheetseller_backfill import _item_detail

from zeler_sheets.formulas.pacing import PacedMeliGateway, RecoveryRequestPacer
from zeler_sheets.formulas.read_models import FormulaReadModelRepository
from zeler_sheets.formulas.recovery import (
    FormulaRecoveryQueue,
    ItemIdsRecoveryRequest,
    ItemInventoryRecoveryRequest,
    RecoveryRequest,
)
from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker

SELLER = "82453304"


@pytest.mark.asyncio
async def test_1900_basic_items_remain_fresh_with_competing_lanes(
    recovery_db: Any,  # noqa: F811 - imported pytest fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = datetime.now(UTC)
    wall_start = time.monotonic()
    elapsed_virtual = 0.0

    def now() -> datetime:
        # Count real Mongo, history and projection execution as well as simulated
        # provider latency and quota sleeps. No persistence work is stubbed out.
        return started + timedelta(seconds=elapsed_virtual + time.monotonic() - wall_start)

    async def advance(seconds: float) -> None:
        nonlocal elapsed_virtual
        elapsed_virtual += seconds
        await asyncio.sleep(0)

    class ClockMeta(type):
        def __instancecheck__(cls, instance: Any) -> bool:
            return isinstance(instance, datetime)

    class AcquisitionClock(datetime, metaclass=ClockMeta):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> Any:
            current = now()
            return current.astimezone(tz) if tz is not None else current.replace(tzinfo=None)

    monkeypatch.setattr("zeler_sheets.sheetseller_backfill.datetime", AcquisitionClock)
    identities = sorted(f"MLA{index}" for index in range(1900))
    calls: Counter[str] = Counter()
    batch_sizes: list[int] = []
    producer_progress: dict[str, int] = {}

    class Gateway:
        async def fetch_resource(self, *, seller_id: str, path: str) -> Any:
            assert seller_id == SELLER
            await advance(0.1)
            parsed = urlparse(path)
            query = parse_qs(parsed.query)
            if parsed.path == f"/users/{SELLER}/items/search":
                calls["discovery"] += 1
                offset = int(query.get("scroll_id", ["0"])[0])
                return {
                    "paging": {"total": 1900},
                    "results": identities[offset : offset + 100],
                    "scroll_id": str(offset + 100),
                }
            if parsed.path == "/items":
                calls["items"] += 1
                batch = query["ids"][0].split(",")
                batch_sizes.append(len(batch))
                response = []
                for identity in batch:
                    detail = _item_detail(identity)
                    detail["shipping"] = {"mode": "me2", "free_shipping": True}
                    if int(identity[3:]) % 10 == 0:
                        detail["variations"] = [{"id": 1, "available_quantity": 7}]
                    response.append({"code": 200, "body": detail})
                return response
            if "/variations/" in parsed.path:
                calls["variations"] += 1
                identity = parsed.path.split("/")[2]
                return {"id": 1, "attributes": [{"id": "SELLER_SKU", "value_name": identity}]}
            if parsed.path in {"/load/ids", "/load/ranges"}:
                calls[parsed.path] += 1
                return {}
            pytest.fail(f"Base sweep requested optional enrichment: {parsed.path}")

    queue = FormulaRecoveryQueue(recovery_db, now=now)
    pacer = RecoveryRequestPacer(now=now, sleep=advance)
    clients = {
        lane: PacedMeliGateway(inner=Gateway(), pacer=pacer, lane=lane)
        for lane in ("inventory", "ids", "ranges")
    }
    inventory = ItemInventoryRecoveryRequest(SELLER)
    await queue.enqueue(inventory)
    await queue.enqueue(ItemIdsRecoveryRequest(SELLER, ("MLA9999",)))
    await queue.enqueue(RecoveryRequest(SELLER, "orders", started - timedelta(days=90), started))
    worker = FormulaRecoveryWorker(
        db=recovery_db,
        queue=queue,
        gateway=clients["inventory"],
        lane="inventory",
    )
    # Enumerate before competing acquisitions so discovery age includes their
    # entire workload, rather than starting the freshness clock after the load.
    assert await worker.process_one()
    producer_started = {lane: asyncio.Event() for lane in ("ids", "ranges")}
    release = asyncio.Event()

    async def competing_producer(lane: str) -> None:
        job = await queue.claim(lane=lane)
        assert job is not None
        producer_started[lane].set()
        await release.wait()
        for index in range(300):
            await clients[lane].fetch_resource(seller_id=SELLER, path=f"/load/{lane}")
            producer_progress[lane] = index + 1
        assert await queue.finish(job, succeeded=True)

    async with asyncio.TaskGroup() as group:
        for lane in ("ids", "ranges"):
            group.create_task(competing_producer(lane))
        await asyncio.gather(*(event.wait() for event in producer_started.values()))
        # Two occupied lanes do not prevent a real inventory acquisition.
        assert await worker.process_one()
        assert await recovery_db.items.count_documents({"seller_id": SELLER}) == 20
        release.set()
        for _ in range(94):
            assert await worker.process_one()

    finished = now()
    job = await queue.collection.find_one({"_id": inventory.key})
    assert job["state"] == "completed" and job["inventory_offset"] == 1900
    observed = job["inventory_observed_at"].replace(tzinfo=UTC)
    assert timedelta(0) < finished - observed < timedelta(minutes=15)
    rows, membership, missing, current = await FormulaReadModelRepository(
        db=recovery_db
    ).find_recent_item_inventory(seller_id=SELLER, formula="ZELERDATA_CALCULADORA", now=finished)
    assert current and not missing
    assert set(membership) == set(identities)
    assert {row["item_id"] for row in rows} == set(identities)
    assert batch_sizes == [20] * 95
    assert calls == Counter(
        {"discovery": 19, "items": 95, "variations": 190, "/load/ids": 300, "/load/ranges": 300}
    )
    assert producer_progress == {"ids": 300, "ranges": 300}
    for collection in (
        "item_status_states",
        "sheets_price_history_snapshots",
        "sheets_stockout_snapshots",
    ):
        assert await recovery_db[collection].count_documents({"seller_id": SELLER}) == 1900
    sources = await recovery_db.items.find({"seller_id": SELLER}, {"last_meli_sync_at": 1}).to_list(
        None
    )
    assert all(
        timedelta(0)
        <= finished - item["last_meli_sync_at"].replace(tzinfo=UTC)
        < timedelta(minutes=15)
        for item in sources
    )
