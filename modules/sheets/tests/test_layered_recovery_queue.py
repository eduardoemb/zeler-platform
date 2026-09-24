# ruff: noqa: F811 -- imported pytest fixture
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from test_formula_recovery import recovery_db  # noqa: F401

from zeler_sheets.formulas.recovery import (
    FormulaRecoveryQueue,
    ItemIdsRecoveryRequest,
    ItemInventoryRecoveryRequest,
    RecoveryRequest,
)

NOW = datetime(2026, 9, 14, tzinfo=UTC)


@pytest.mark.asyncio
async def test_inventory_has_reserved_admission_without_evicting_work(recovery_db: Any) -> None:
    queue = FormulaRecoveryQueue(recovery_db, reserved_inventory_slots=1)
    requests = [ItemIdsRecoveryRequest("123", (f"MLM{i}",)) for i in range(20)]
    for request in requests[:19]:
        await queue.enqueue(request)
    with pytest.raises(ValueError, match="capacity"):
        await queue.enqueue(requests[19])
    inventory = ItemInventoryRecoveryRequest("123")
    await queue.enqueue(inventory)
    assert await recovery_db.sheets_formula_recovery_jobs.count_documents({}) == 20
    assert await queue.enqueue(requests[0]) == requests[0].key
    # Another seller remains independent.
    await queue.enqueue(ItemIdsRecoveryRequest("456", ("MLM20",)))


@pytest.mark.asyncio
async def test_active_dedup_does_not_write_admission_guard(recovery_db: Any) -> None:
    queue = FormulaRecoveryQueue(recovery_db)
    request = ItemInventoryRecoveryRequest("123")
    await queue.enqueue(request)
    before = await recovery_db.sheets_formula_recovery_admission.find_one({"_id": "123"})
    await queue.enqueue(request)
    assert await recovery_db.sheets_formula_recovery_admission.find_one({"_id": "123"}) == before
    disabled = FormulaRecoveryQueue(recovery_db, allowed_sellers=frozenset())
    with pytest.raises(ValueError, match="seller"):
        await disabled.enqueue(request)


@pytest.mark.asyncio
async def test_claim_lanes_are_disjoint_and_cleanup_is_scoped(recovery_db: Any) -> None:
    clock = [NOW]
    queue = FormulaRecoveryQueue(recovery_db, now=lambda: clock[0])
    requests: dict[str, Any] = {
        "inventory": ItemInventoryRecoveryRequest("123"),
        "ids": ItemIdsRecoveryRequest("123", ("MLM1",)),
        "ranges": RecoveryRequest("123", "orders", NOW - timedelta(days=1), NOW),
    }
    for request in requests.values():
        await queue.enqueue(request)
    for lane, request in requests.items():
        job = await queue.claim(lane=lane)
        assert job is not None and job["_id"] == request.key
        assert await queue.claim(lane=lane) is None
    await recovery_db.sheets_formula_recovery_jobs.update_many(
        {}, {"$set": {"attempts": 3, "lease_until": NOW - timedelta(seconds=1)}}
    )
    assert await queue.claim(lane="inventory") is None
    assert (await recovery_db.sheets_formula_recovery_jobs.find_one({"_id": requests["ids"].key}))[
        "state"
    ] == "running"
    assert (
        await recovery_db.sheets_formula_recovery_jobs.find_one({"_id": requests["inventory"].key})
    )["state"] == "failed"


@pytest.mark.asyncio
async def test_range_claim_gives_recent_orders_one_turn_before_old_ranges(
    recovery_db: Any,
) -> None:
    queue = FormulaRecoveryQueue(recovery_db, now=lambda: NOW)
    old_order = RecoveryRequest("123", "orders", NOW - timedelta(days=31), NOW - timedelta(days=30))
    old_question = RecoveryRequest(
        "123", "questions", NOW - timedelta(days=7), NOW - timedelta(days=6)
    )
    recent_order = RecoveryRequest("123", "orders", NOW - timedelta(hours=1), NOW)
    for request in (old_order, old_question, recent_order):
        await queue.enqueue(request)
    for request in (old_order, old_question):
        await recovery_db.sheets_formula_recovery_jobs.update_one(
            {"_id": request.key}, {"$set": {"available_at": NOW - timedelta(minutes=1)}}
        )

    first = await queue.claim(lane="ranges")
    assert first is not None and first["_id"] == recent_order.key
    second = await queue.claim(lane="ranges")
    assert second is not None and second["_id"] in {old_order.key, old_question.key}


@pytest.mark.asyncio
async def test_range_claim_leaves_not_ready_recent_orders_in_queue(recovery_db: Any) -> None:
    queue = FormulaRecoveryQueue(recovery_db, now=lambda: NOW)
    old_order = RecoveryRequest("123", "orders", NOW - timedelta(days=31), NOW - timedelta(days=30))
    recent_order = RecoveryRequest("123", "orders", NOW - timedelta(hours=1), NOW)
    await queue.enqueue(old_order)
    await queue.enqueue(recent_order)
    await recovery_db.sheets_formula_recovery_jobs.update_one(
        {"_id": recent_order.key},
        {"$set": {"available_at": NOW + timedelta(minutes=1)}},
    )

    claimed = await queue.claim(lane="ranges")
    assert claimed is not None and claimed["_id"] == old_order.key
    assert (await recovery_db.sheets_formula_recovery_jobs.find_one({"_id": recent_order.key}))[
        "state"
    ] == "pending"


@pytest.mark.asyncio
async def test_quota_deferral_retains_progress_and_does_not_consume_attempt(
    recovery_db: Any,
) -> None:
    clock = [NOW]
    queue = FormulaRecoveryQueue(recovery_db, now=lambda: clock[0])
    request = ItemInventoryRecoveryRequest("123")
    await queue.enqueue(request)
    job = await queue.claim(lane="inventory")
    assert job is not None
    await queue.checkpoint_inventory(job, item_ids=["MLM1"], offset=0)
    job = await queue.claim(lane="inventory")
    assert job is not None
    assert await queue.defer_quota(job)
    saved = await recovery_db.sheets_formula_recovery_jobs.find_one({"_id": request.key})
    assert saved["state"] == "pending" and saved["attempts"] == 0
    assert saved["inventory_offset"] == 0 and saved["inventory_ids"] == ["MLM1"]
    assert saved["available_at"].replace(tzinfo=UTC) > NOW
    assert not await queue.defer_quota(job)


@pytest.mark.asyncio
async def test_inventory_worker_fetches_one_basic_batch_and_projects_history(
    recovery_db: Any,
) -> None:
    from urllib.parse import parse_qs, urlparse

    from test_sheetseller_backfill import _item_detail

    from zeler_sheets.formulas.read_models import FormulaReadModelRepository
    from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker

    identities = [f"MLA{i}" for i in range(20)]
    requested: list[list[str]] = []

    class Gateway:
        async def fetch_resource(self, *, seller_id: str, path: str) -> Any:
            if path.startswith("/users/"):
                return {"paging": {"total": len(identities)}, "results": identities}
            assert path.startswith("/items?"), f"Unexpected enrichment request: {path}"
            batch = parse_qs(urlparse(path).query)["ids"][0].split(",")
            requested.append(batch)
            return [{"code": 200, "body": _item_detail(identity)} for identity in batch]

    queue = FormulaRecoveryQueue(recovery_db)
    request = ItemInventoryRecoveryRequest("82453304")
    await queue.enqueue(request)
    worker = FormulaRecoveryWorker(db=recovery_db, queue=queue, gateway=Gateway())
    assert await worker.process_one()  # real discovery/checkpoint
    assert await worker.process_one()  # real acquisition/history/projection
    job = await recovery_db.sheets_formula_recovery_jobs.find_one({"_id": request.key})
    assert job["state"] == "completed"
    assert requested == [sorted(identities)]
    rows, membership, missing, current = await FormulaReadModelRepository(
        db=recovery_db
    ).find_recent_item_inventory(
        seller_id="82453304", formula="ZELERDATA_CALCULADORA", now=datetime.now(UTC)
    )
    assert current and not missing and len(membership) == 20 and len(rows) == 20
    assert await recovery_db.item_status_states.count_documents({"seller_id": "82453304"}) == 20


def test_api_factory_reserves_inventory_capacity() -> None:
    from collections import defaultdict

    from zeler_sheets.app import build_app

    app = build_app(
        mongo_db=defaultdict(lambda: None),
        formula_recovery_enabled=True,
        formula_recovery_sellers=frozenset({"123"}),
    )
    assert app.state.formula_recovery_queue.reserved_inventory_slots == 1
