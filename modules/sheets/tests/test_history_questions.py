"""Shared admission and explicit restart signals, not a provider scan adapter."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from infra.mongo.apply_validators import apply_validators
from motor.motor_asyncio import AsyncIOMotorClient

from zeler_platform_core.models import SheetsHistoryAcquisition, SheetsHistoryReceipt
from zeler_sheets.formulas.recovery import (
    FormulaRecoveryQueue,
    QuestionScanRecoveryRequest,
    RecoveryCapacityError,
    RecoveryRequest,
)
from zeler_sheets.history_acquisition import HistoryAcquisitionStore
from zeler_sheets.history_continuation import HistoryContinuation
from zeler_sheets.history_questions import initialize_question_scan

NOW = datetime(2026, 9, 15, 12, tzinfo=UTC)
START = NOW.replace(year=2025)


def request(**changes: Any) -> QuestionScanRecoveryRequest:
    return QuestionScanRecoveryRequest(
        **{
            "seller_id": "82453304",
            "plan_id": "fixed-plan",
            "date_from": START,
            "date_to": NOW,
            **changes,
        }
    )


@pytest_asyncio.fixture
async def queue(tmp_path: Path) -> AsyncIterator[FormulaRecoveryQueue]:
    name = f"zeler_question_scan_{uuid4().hex}"
    uri = f"mongodb://127.0.0.1:27028/{name}?directConnection=true"
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(uri, tz_aware=True)
    hello = await client.admin.command("hello")
    assert hello["isWritablePrimary"] and hello["setName"] == "rs0"
    root = Path(__file__).resolve().parents[3] / "infra/mongo"
    for directory in ("schemas", "indexes"):
        (tmp_path / directory).mkdir()
        for collection in ("sheets_history_acquisitions", "sheets_history_receipts"):
            filename = f"{collection}.json"
            (tmp_path / directory / filename).write_text((root / directory / filename).read_text())
    try:
        await asyncio.to_thread(apply_validators, uri, tmp_path / "schemas")
        yield FormulaRecoveryQueue(client[name], now=lambda: NOW, max_active_jobs_per_seller=2)
    finally:
        await client.drop_database(name)
        client.close()


@pytest.mark.parametrize(
    "changes",
    [
        {"date_from": NOW - timedelta(days=90)},
        {"date_to": NOW.replace(tzinfo=None)},
        {"seller_id": " "},
        {"plan_id": " "},
        {"read_model": "orders"},
    ],
)
def test_scan_request_rejects_non_plan_scope(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        request(**changes)


def test_calendar_leap_cutoff_and_ordinary_range_contract() -> None:
    cutoff = datetime(2024, 2, 29, tzinfo=UTC)
    scan = request(date_to=cutoff, date_from=datetime(2023, 2, 28, tzinfo=UTC))
    assert scan.date_to == cutoff
    with pytest.raises(ValueError):
        RecoveryRequest(scan.seller_id, "questions", scan.date_from, scan.date_to)


@pytest.mark.asyncio
async def test_twelve_consumers_share_one_history_only_admission(
    queue: FormulaRecoveryQueue,
) -> None:
    scan = request()
    keys = await asyncio.gather(*(queue.enqueue(scan) for _ in range(12)))
    assert set(keys) == {scan.key}
    assert await queue.collection.count_documents({}) == 1
    assert await queue.claim() is None
    job = await queue.claim(history=True)
    assert job is not None
    store = HistoryAcquisitionStore(queue.collection.database, queue)
    head = await initialize_question_scan(store, job, scan)
    assert head.scope_id == "seller_scan" and head.date_from == START and head.date_to == NOW
    assert head.plan_id == scan.plan_id and head.id == scan.key
    assert job["history_acquisition_id"] == head.id
    assert await initialize_question_scan(store, job, scan) == head


@pytest.mark.asyncio
async def test_reused_plan_cannot_change_fixed_bounds(queue: FormulaRecoveryQueue) -> None:
    await queue.enqueue(request())
    shifted = request(date_from=START + timedelta(days=1), date_to=NOW + timedelta(days=1))
    assert shifted.key == request().key
    with pytest.raises(ValueError, match="plan"):
        await queue.enqueue(shifted)


@pytest.mark.asyncio
async def test_seller_and_capacity_guards_still_apply(queue: FormulaRecoveryQueue) -> None:
    queue.allowed_sellers = frozenset({"82453304"})
    with pytest.raises(ValueError, match="seller"):
        await queue.enqueue(request(seller_id="123"))
    await queue.enqueue(request())
    await queue.enqueue(request(plan_id="other"))
    with pytest.raises(RecoveryCapacityError):
        await queue.enqueue(request(plan_id="third"))


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", ["failed", "completed"])
async def test_readmission_does_not_reopen_scan_manifest(
    queue: FormulaRecoveryQueue, terminal: str
) -> None:
    scan = request()
    await queue.enqueue(scan)
    await queue.collection.update_one(
        {"_id": scan.key}, {"$set": {"state": terminal, "attempts": 3}}
    )
    before = await queue.collection.find_one({"_id": scan.key})
    await queue.enqueue(scan)
    assert await queue.collection.find_one({"_id": scan.key}) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["cursor_expired", "source_drift"])
async def test_restart_preserves_receipts_and_rotates_manifest(
    queue: FormulaRecoveryQueue, reason: str
) -> None:
    scan = request()
    await queue.enqueue(scan)
    job = await queue.claim(history=True)
    assert job is not None
    store = HistoryAcquisitionStore(queue.collection.database, queue)
    runner = HistoryContinuation(store)
    head = await initialize_question_scan(store, job, scan)
    receipt = SheetsHistoryReceipt(
        _id="first-membership",
        acquisition_id=head.id,
        seller_id=head.seller_id,
        read_model="questions",
        generation=1,
        pass_number=1,
        page_sequence=1,
        kind="membership",
        resource_id="123",
        observed_at=NOW,
    )
    proposed = SheetsHistoryAcquisition.model_validate(
        {
            **head.model_dump(by_alias=True),
            "checkpoint_revision": 1,
            "page_sequence": 1,
            "next_cursor": "opaque-test-cursor",
            "discovered_count": 1,
            "observed_from": NOW,
            "observed_until": NOW,
        }
    )
    saved = await runner.progress(job, head, proposed, [receipt])
    claimed = await queue.claim(history=True)
    assert claimed is not None
    assert await initialize_question_scan(store, claimed, scan) == saved
    restarted = await runner.release(claimed, saved, reason=reason)
    assert restarted.pass_number == 2 and restarted.next_cursor is None
    assert restarted.drift_restarts == 1 and restarted.discovered_count == 0
    assert await store.receipts.count_documents({"pass_number": 1}) == 1
    assert restarted.date_from == START and restarted.date_to == NOW
    for _ in range(3):
        claimed = await queue.claim(history=True)
        assert claimed is not None
        restarted = await runner.release(claimed, restarted, reason=reason)
    final = await queue.collection.find_one({"_id": scan.key})
    assert final is not None and final["state"] == "failed"
    assert restarted.drift_restarts == 3
