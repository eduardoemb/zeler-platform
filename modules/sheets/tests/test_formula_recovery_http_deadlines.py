# ruff: noqa: F811 -- imported isolated Mongo pytest fixture
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from test_formula_recovery import recovery_db  # noqa: F401

from zeler_sheets.formulas import pacing, recovery_worker
from zeler_sheets.formulas.recovery import (
    IMPLEMENTED_MODELS,
    CatalogProductIdsRecoveryRequest,
    FormulaRecoveryQueue,
    ItemIdsRecoveryRequest,
)
from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker


def shorten_http_deadlines(monkeypatch: pytest.MonkeyPatch) -> None:
    original = asyncio.timeout
    monkeypatch.setattr(
        asyncio, "timeout", lambda seconds: original(0.01 if seconds in (5, 10) else seconds)
    )


async def exhausted_pacer() -> pacing.RecoveryRequestPacer:
    async def sleep(seconds: float) -> None:
        await asyncio.sleep(0.03)

    pacer = pacing.RecoveryRequestPacer(requests_per_minute=1, sleep=sleep)
    await pacer.acquire(lane="ids")
    return pacer


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_slow", [False, True])
async def test_order_shipment_caller_excludes_quota_but_bounds_http(
    monkeypatch: pytest.MonkeyPatch, provider_slow: bool
) -> None:
    shorten_http_deadlines(monkeypatch)
    calls: list[str] = []

    class Gateway:
        async def request(self, **kwargs: Any) -> httpx.Response:
            calls.append(kwargs["path"])
            if provider_slow:
                await asyncio.sleep(1)
            return httpx.Response(200, json=[{"id": "123", "type": "forward"}])

    gateway = pacing.PacedMeliGateway(inner=Gateway(), pacer=await exhausted_pacer(), lane="ids")
    worker = FormulaRecoveryWorker(db=None, queue=None, gateway=gateway)  # type: ignore[arg-type]
    detail, missing = await worker._recover_order_shipment("82453304", "42", {}, frozenset())
    assert calls == ["/orders/42/shipments?hosted=true"]
    assert detail == ({} if provider_slow else {"shipping": {"id": "123"}})
    assert missing == (frozenset({"shipping"}) if provider_slow else frozenset())


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["catalog_product_snapshots", "catalog_buybox_snapshots"])
async def test_catalog_callers_exclude_wait_for_each_provider_endpoint(
    recovery_db: Any, monkeypatch: pytest.MonkeyPatch, model: str
) -> None:
    shorten_http_deadlines(monkeypatch)
    seller = "82453304"
    await recovery_db.items.insert_one(
        {
            "_id": "MLA1",
            "seller_id": seller,
            "catalog_product_id": "MLA9",
            "catalog_listing": True,
            "title": "Item",
            "available_quantity": 2,
            "last_meli_sync_at": datetime.now(UTC),
        }
    )
    queue = FormulaRecoveryQueue(recovery_db, enabled_models=IMPLEMENTED_MODELS)
    request = (
        CatalogProductIdsRecoveryRequest(seller, ("MLA9",))
        if model == "catalog_product_snapshots"
        else ItemIdsRecoveryRequest(seller, ("MLA1",), read_model=model)
    )
    await queue.enqueue(request)
    calls: list[str] = []
    responses: dict[str, dict[str, Any]] = {
        "/products/MLA9": {"id": "MLA9", "name": "Product"},
        "/items/MLA1/price_to_win?version=v2": {
            "item_id": "MLA1",
            "status": "winning",
            "current_price": 100,
            "competitors_sharing_first_place": 0,
            "winner": {"item_id": "MLA2", "price": 99},
        },
        "/products/MLA9/items": {"paging": {"total": 0, "offset": 0, "limit": 100}, "results": []},
        "/items/MLA2": {"id": "MLA2", "catalog_product_id": "MLA9", "seller_id": "42"},
    }

    class Gateway:
        async def fetch_resource(self, *, seller_id: str, path: str) -> dict[str, Any]:
            assert seller_id == seller
            calls.append(path)
            return responses[path]

    gateway = pacing.PacedMeliGateway(inner=Gateway(), pacer=await exhausted_pacer(), lane="ids")
    assert await FormulaRecoveryWorker(db=recovery_db, queue=queue, gateway=gateway).process_one()
    job = await queue.collection.find_one({"_id": request.key})
    assert job["state"] == "completed"
    if model == "catalog_product_snapshots":
        assert calls == ["/products/MLA9"]
        snapshot = await recovery_db.sheets_catalog_product_snapshots.find_one({})
        assert snapshot["title"] == "Product"
    else:
        assert calls == list(responses)[1:]
        snapshot = await recovery_db.sheets_catalog_buybox_snapshots.find_one({})
        assert snapshot["winning_user_id"] == "42"
        assert snapshot["competitor_count"] == 0


@pytest.mark.asyncio
async def test_catalog_batch_propagates_quota_expiry_after_joining_siblings() -> None:
    worker = FormulaRecoveryWorker(db=None, queue=None, gateway=None)  # type: ignore[arg-type]
    finished: list[str] = []

    async def acquire(identity: str) -> None:
        if identity == "MLA1":
            raise pacing.LocalQuotaTimeoutError
        await asyncio.sleep(0)
        finished.append(identity)

    with pytest.raises(pacing.LocalQuotaTimeoutError):
        await worker._finish_catalog_batch({}, ["MLA1", "MLA2"], acquire)
    assert finished == ["MLA2"]


@pytest.mark.asyncio
async def test_catalog_quota_deadline_defers_without_spending_source_attempt(
    recovery_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    seller = "82453304"
    await recovery_db.items.insert_one(
        {"_id": "MLA1", "seller_id": seller, "catalog_product_id": "MLA9"}
    )
    queue = FormulaRecoveryQueue(recovery_db, enabled_models=IMPLEMENTED_MODELS)
    request = CatalogProductIdsRecoveryRequest(seller, ("MLA9",))
    await queue.enqueue(request)
    calls: list[str] = []

    class Gateway:
        async def fetch_resource(self, **kwargs: Any) -> dict[str, Any]:
            calls.append(kwargs["path"])
            return {"id": "MLA9", "name": "Product"}

    gateway = pacing.PacedMeliGateway(inner=Gateway(), pacer=await exhausted_pacer(), lane="ids")
    monkeypatch.setattr(
        recovery_worker,
        "recovery_quota_deadline",
        lambda deadline: pacing.recovery_quota_deadline(asyncio.get_running_loop().time() + 0.01),
    )
    assert await FormulaRecoveryWorker(db=recovery_db, queue=queue, gateway=gateway).process_one()
    job = await queue.collection.find_one({"_id": request.key})
    assert job["state"] == "pending"
    assert job["attempts"] == 0
    assert calls == []
    assert await recovery_db.sheets_catalog_product_snapshots.count_documents({}) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("quota_wait", [True, False])
async def test_inventory_discovery_deadline_distinguishes_local_wait_from_http(
    recovery_db: Any, monkeypatch: pytest.MonkeyPatch, quota_wait: bool
) -> None:
    from zeler_sheets import sheetseller_backfill
    from zeler_sheets.formulas.recovery import ItemInventoryRecoveryRequest

    original_timeout = asyncio.timeout
    monkeypatch.setattr(
        asyncio,
        "timeout",
        lambda seconds: original_timeout(
            0.03 if seconds == 180 else 0.01 if seconds == 10 else seconds
        ),
    )
    monkeypatch.setattr(
        sheetseller_backfill,
        "recovery_quota_deadline",
        lambda deadline: pacing.recovery_quota_deadline(asyncio.get_running_loop().time() + 0.02),
        raising=False,
    )
    calls: list[str] = []

    class Gateway:
        async def fetch_resource(self, **kwargs: Any) -> dict[str, Any]:
            calls.append(kwargs["path"])
            await asyncio.sleep(1)
            return {"paging": {"total": 0}, "results": []}

    pacer = await exhausted_pacer() if quota_wait else pacing.RecoveryRequestPacer()
    gateway = pacing.PacedMeliGateway(inner=Gateway(), pacer=pacer, lane="inventory")
    queue = FormulaRecoveryQueue(recovery_db)
    request = ItemInventoryRecoveryRequest("82453304")
    await queue.enqueue(request)
    worker = FormulaRecoveryWorker(db=recovery_db, queue=queue, gateway=gateway, lane="inventory")
    assert await worker.process_one()
    saved = await queue.collection.find_one({"_id": request.key})
    assert saved["state"] == "pending"
    assert saved["attempts"] == (0 if quota_wait else 1)
    assert len(calls) == (0 if quota_wait else 1)
    assert saved.get("failure_reason") == (None if quota_wait else "source_temporarily_unavailable")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "local_quota, external_cancel", [(True, False), (False, False), (True, True)]
)
async def test_worker_keeps_quota_classification_when_outer_deadline_interrupts_sibling_join(
    monkeypatch: pytest.MonkeyPatch, local_quota: bool, external_cancel: bool
) -> None:
    original_timeout = asyncio.timeout
    original_quota = pacing.recovery_quota_deadline
    monkeypatch.setattr(
        asyncio, "timeout", lambda seconds: original_timeout(0.04 if seconds == 240 else seconds)
    )
    monkeypatch.setattr(
        recovery_worker,
        "recovery_quota_deadline",
        lambda deadline: original_quota(asyncio.get_running_loop().time() + 0.03),
    )
    drained = asyncio.Event()
    quota_expired = asyncio.Event()
    outcomes: list[str] = []
    job = {"_id": "catalog", "read_model": "catalog_product_snapshots"}

    class Queue:
        async def claim(self) -> dict[str, Any]:
            return job

        async def defer_quota(self, owned: dict[str, Any]) -> bool:
            assert owned == job
            outcomes.append("deferred")
            return True

        async def finish(self, owned: dict[str, Any], **kwargs: Any) -> None:
            assert owned == job
            assert kwargs == {
                "succeeded": False,
                "retryable": True,
                "failure_reason": "source_temporarily_unavailable",
            }
            outcomes.append("source_retry")

    async def never(seconds: float) -> None:
        await asyncio.Event().wait()

    pacer = pacing.RecoveryRequestPacer(requests_per_minute=1, sleep=never)
    await pacer.acquire()

    class Worker(FormulaRecoveryWorker):
        async def _catalog_products(self, owned: dict[str, Any]) -> None:
            async def acquire(identity: str) -> None:
                if identity == "MLA1":
                    if local_quota:
                        try:
                            await pacer.acquire(lane="ids")
                        except pacing.LocalQuotaTimeoutError:
                            quota_expired.set()
                            raise
                    else:
                        await asyncio.sleep(0.03)
                        raise httpx.ReadTimeout("provider timeout")
                else:
                    try:
                        await asyncio.sleep(0.05)
                    finally:
                        drained.set()

            await self._finish_catalog_batch(owned, ["MLA1", "MLA2"], acquire)

    worker = Worker(db=None, gateway=None, queue=Queue())  # type: ignore[arg-type]
    if external_cancel:
        task = asyncio.create_task(worker.process_one())
        await quota_expired.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert outcomes == []
    else:
        assert await worker.process_one()
        assert outcomes == (["deferred"] if local_quota else ["source_retry"])
    assert drained.is_set()
    with original_quota(asyncio.get_running_loop().time() + 1) as fresh_job:
        assert fresh_job.expired is False
