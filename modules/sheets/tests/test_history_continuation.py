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
from zeler_sheets.formulas.recovery import FormulaRecoveryQueue, RecoveryRequest
from zeler_sheets.history_acquisition import HistoryAcquisitionStore, HistoryConflictError
from zeler_sheets.history_continuation import HistoryContinuation

NOW = datetime(2026, 9, 15, tzinfo=UTC)
ContinuationState = tuple[
    HistoryContinuation, dict[str, Any], SheetsHistoryAcquisition, list[datetime]
]


async def claim_history(runner: HistoryContinuation) -> dict[str, Any]:
    claimed = await runner.store.queue.claim(history=True)
    assert claimed is not None
    return claimed


@pytest_asyncio.fixture
async def continuation(
    tmp_path: Path,
) -> AsyncIterator[
    tuple[HistoryContinuation, dict[str, Any], SheetsHistoryAcquisition, list[datetime]]
]:
    name = f"zeler_history_continuation_{uuid4().hex}"
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
        clock = [NOW]
        queue = FormulaRecoveryQueue(client[name], now=lambda: clock[0])
        request = RecoveryRequest("82453304", "orders", NOW - timedelta(days=31), NOW)
        await queue.enqueue(request)
        job = await queue.claim()
        assert job is not None
        head = SheetsHistoryAcquisition(
            _id="head",
            seller_id="82453304",
            read_model="orders",
            plan_id="plan",
            scope_id="orders:20260815:20260915",
            job_id=job["_id"],
            date_from=request.date_from,
            date_to=request.date_to,
            created_at=NOW,
            updated_at=NOW,
        )
        store = HistoryAcquisitionStore(client[name], queue)
        await store.initialize(job, head)
        yield HistoryContinuation(store), job, head, clock
    finally:
        await client.drop_database(name)
        client.close()


def page(
    head: SheetsHistoryAcquisition,
) -> tuple[SheetsHistoryAcquisition, list[SheetsHistoryReceipt]]:
    sequence = head.page_sequence + 1
    receipt = SheetsHistoryReceipt(
        _id=f"receipt-{head.pass_number}-{sequence}",
        acquisition_id=head.id,
        seller_id=head.seller_id,
        read_model=head.read_model,
        generation=head.generation,
        pass_number=head.pass_number,
        page_sequence=sequence,
        kind="membership",
        resource_id=str(sequence),
        observed_at=NOW,
    )
    proposed = SheetsHistoryAcquisition.model_validate(
        {
            **head.model_dump(by_alias=True),
            "page_sequence": sequence,
            "checkpoint_revision": head.checkpoint_revision + 1,
            "discovered_count": head.discovered_count + 1,
            "next_cursor": sequence * 50,
        }
    )
    return proposed, [receipt]


@pytest.mark.asyncio
async def test_progress_yields_beyond_attempt_budget_and_requires_opt_in(
    continuation: ContinuationState,
) -> None:
    runner, job, head, clock = continuation
    for _ in range(5):
        proposed, records = page(head)
        head = await runner.progress(job, head, proposed, records)
        queued = await runner.store.queue.collection.find_one({"_id": job["_id"]})
        assert queued["state"] == "pending" and queued["attempts"] == 0
        assert queued["history_checkpoint_revision"] == head.checkpoint_revision
        assert await runner.store.queue.claim() is None
        job = await claim_history(runner)
        assert job is not None and job["attempts"] == 1
    assert await runner.store.receipts.count_documents({}) == 5


@pytest.mark.asyncio
async def test_quota_preserves_checkpoint_and_failure_budget_is_finite(
    continuation: ContinuationState,
) -> None:
    runner, job, head, clock = continuation
    for attempt in range(1, 4):
        await runner.release(job, head, reason="quota")
        queued = await runner.store.queue.collection.find_one({"_id": job["_id"]})
        assert queued["attempts"] == attempt - 1
        assert await runner.store.heads.find_one({"_id": head.id}) == head.model_dump(by_alias=True)
        clock[0] += timedelta(seconds=1)
        job = await claim_history(runner)
        assert job["attempts"] == attempt
        await runner.release(job, head, reason="failure")
        queued = await runner.store.queue.collection.find_one({"_id": job["_id"]})
        assert queued["state"] == ("failed" if attempt == 3 else "pending")
        assert queued["attempts"] == attempt
        clock[0] += timedelta(minutes=3)
        if attempt < 3:
            job = await claim_history(runner)
        else:
            assert await runner.store.queue.claim(history=True) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["cursor_expired", "source_drift"])
async def test_restarts_have_separate_budget_and_retain_receipts(
    continuation: ContinuationState, reason: str
) -> None:
    runner, job, initial, clock = continuation
    proposed, records = page(initial)
    head = await runner.progress(job, initial, proposed, records)
    for restart in range(1, 5):
        job = await claim_history(runner)
        assert job is not None
        head = await runner.release(job, head, reason=reason)
        queued = await runner.store.queue.collection.find_one({"_id": job["_id"]})
        assert queued["state"] == ("failed" if restart == 4 else "pending")
        assert head.drift_restarts == min(restart, 3)
        assert head.pass_number == min(restart, 3) + 1
        assert head.next_cursor is None and head.discovered_count == head.fetched_count == 0
        assert await runner.store.receipts.count_documents({}) == 1
    assert await runner.store.queue.claim(history=True) is None


@pytest.mark.asyncio
async def test_restart_resumes_from_original_plan_without_resetting_budget(
    continuation: ContinuationState,
) -> None:
    runner, job, initial, clock = continuation
    restarted = await runner.release(job, initial, reason="cursor_expired")
    job = await claim_history(runner)
    assert job is not None
    assert await runner.store.initialize(job, initial) == restarted
    proposed, records = page(restarted)
    tampered = proposed.model_copy(update={"drift_restarts": 0})
    with pytest.raises(HistoryConflictError):
        await runner.progress(job, restarted, tampered, records)


@pytest.mark.asyncio
async def test_metadata_only_changes_do_not_reset_failures(continuation: ContinuationState) -> None:
    runner, job, head, clock = continuation
    proposed = head.model_copy(
        update={"checkpoint_revision": 1, "page_sequence": 1, "source_total": 20}
    )
    with pytest.raises(HistoryConflictError):
        await runner.progress(job, head, proposed, [])


@pytest.mark.asyncio
async def test_queue_cannot_reference_a_different_checkpoint(
    continuation: ContinuationState,
) -> None:
    runner, job, head, clock = continuation
    proposed, records = page(head)
    head = await runner.progress(job, head, proposed, records)
    job = await claim_history(runner)
    assert job is not None
    await runner.store.queue.collection.update_one(
        {"_id": job["_id"]}, {"$set": {"history_checkpoint_revision": 99}}
    )
    with pytest.raises(HistoryConflictError):
        await runner.release(job, head, reason="quota")


@pytest.mark.asyncio
async def test_progress_and_queue_release_rollback_together(
    continuation: ContinuationState, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner, job, head, clock = continuation
    original = runner.store.queue.collection.update_one

    async def fail_release(query: Any, update: Any, **kwargs: Any) -> Any:
        if update.get("$set", {}).get("state") == "pending":
            raise RuntimeError("interrupted yield")
        return await original(query, update, **kwargs)

    monkeypatch.setattr(runner.store.queue.collection, "update_one", fail_release)
    proposed, records = page(head)
    with pytest.raises(RuntimeError, match="interrupted yield"):
        await runner.progress(job, head, proposed, records)
    assert await runner.store.receipts.count_documents({}) == 0
    assert await runner.store.heads.find_one({"_id": head.id}) == head.model_dump(by_alias=True)
    stored_job = await runner.store.queue.collection.find_one({"_id": job["_id"]})
    assert stored_job["state"] == "running" and stored_job["attempts"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["quota", "failure", "cursor_expired"])
async def test_expired_owner_cannot_release_or_restart(
    continuation: ContinuationState, reason: str
) -> None:
    runner, job, head, clock = continuation
    clock[0] += timedelta(hours=1)
    with pytest.raises(HistoryConflictError):
        await runner.release(job, head, reason=reason)
    assert await runner.store.heads.find_one({"_id": head.id}) == head.model_dump(by_alias=True)


@pytest.mark.asyncio
async def test_empty_revision_does_not_reset_attempts(continuation: ContinuationState) -> None:
    runner, job, head, clock = continuation
    proposed = head.model_copy(update={"checkpoint_revision": 1, "page_sequence": 1})
    with pytest.raises(HistoryConflictError):
        await runner.progress(job, head, proposed, [])
    stored_job = await runner.store.queue.collection.find_one({"_id": job["_id"]})
    assert stored_job["attempts"] == 1 and stored_job["state"] == "running"


@pytest.mark.asyncio
async def test_default_claim_still_serves_unmarked_requests(
    continuation: ContinuationState,
) -> None:
    runner, job, head, clock = continuation
    proposed, records = page(head)
    await runner.progress(job, head, proposed, records)
    ordinary = RecoveryRequest(head.seller_id, "orders", NOW - timedelta(days=1), NOW)
    await runner.store.queue.enqueue(ordinary)
    claimed = await runner.store.queue.claim()
    assert claimed is not None and claimed["_id"] == ordinary.key


@pytest.mark.asyncio
async def test_restart_never_withdraws_partial_publication(continuation: ContinuationState) -> None:
    runner, job, head, clock = continuation
    published = SheetsHistoryAcquisition.model_validate(
        {
            **head.model_dump(by_alias=True),
            "phase": "verify",
            "discovered_count": 1,
            "fetched_count": 1,
            "published_count": 1,
            "publish_after": "published-receipt",
        }
    )
    await runner.store.heads.replace_one({"_id": head.id}, published.model_dump(by_alias=True))
    with pytest.raises(HistoryConflictError):
        await runner.release(job, published, reason="cursor_expired")
    assert await runner.store.heads.find_one({"_id": head.id}) == published.model_dump(
        by_alias=True
    )
