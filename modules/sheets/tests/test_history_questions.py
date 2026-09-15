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
from zeler_sheets.history_questions import (
    QuestionDetailObservation,
    QuestionScanPage,
    QuestionScanStaging,
    initialize_question_scan,
    question_subscriptions,
)

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


def question(identity: int, **changes: Any) -> dict[str, Any]:
    return {
        "id": identity,
        "seller_id": 82453304,
        "status": "UNANSWERED",
        "date_created": (START - timedelta(days=400)).isoformat(),
        **changes,
    }


async def scan_state(
    queue: FormulaRecoveryQueue,
) -> tuple[QuestionScanStaging, dict[str, Any], SheetsHistoryAcquisition]:
    scan = request()
    await queue.enqueue(scan)
    job = await queue.claim(history=True)
    assert job is not None
    store = HistoryAcquisitionStore(queue.collection.database, queue)
    return (
        QuestionScanStaging(HistoryContinuation(store)),
        job,
        await initialize_question_scan(store, job, scan),
    )


async def claim(queue: FormulaRecoveryQueue) -> dict[str, Any]:
    job = await queue.claim(history=True)
    assert job is not None
    return job


@pytest.mark.asyncio
async def test_normalized_scan_resumes_and_verifies_without_certification(
    queue: FormulaRecoveryQueue,
) -> None:
    runner, job, head = await scan_state(queue)
    head = await runner.page(job, head, QuestionScanPage([question(1)], 2, "opaque", False, NOW))
    assert head.next_cursor == "opaque"
    runner = QuestionScanStaging(HistoryContinuation(runner.store))
    head = await runner.page(
        await claim(queue), head, QuestionScanPage([question(2)], 2, None, True, NOW)
    )
    head = await runner.begin_verification(await claim(queue), head)
    assert head.pass_number == 2
    head = await runner.page(
        await claim(queue), head, QuestionScanPage([question(2), question(1)], 2, None, True, NOW)
    )
    assert head.phase == "verify" and head.next_cursor is None and head.page_sequence == 1
    assert head.fetched_count == 0 and await runner.store.receipts.count_documents({}) == 4
    assert await runner.store.db.sheets_read_model_freshness.count_documents({}) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rows,total",
    [
        ([question(1), question(3)], 2),
        ([question(1), question(2, status="ANSWERED")], 2),
        ([question(1)], 1),
        ([question(1)], 2),
    ],
)
async def test_verification_detects_manifest_drift(
    queue: FormulaRecoveryQueue, rows: list[dict[str, Any]], total: int
) -> None:
    runner, job, head = await scan_state(queue)
    head = await runner.page(
        job, head, QuestionScanPage([question(1), question(2)], 2, None, True, NOW)
    )
    head = await runner.begin_verification(await claim(queue), head)
    head = await runner.page(
        await claim(queue), head, QuestionScanPage(rows, total, None, True, NOW)
    )
    assert head.phase == "discover" and head.drift_restarts == 1 and head.pass_number == 3
    assert await runner.store.receipts.count_documents({}) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("expired", [True, False])
async def test_expiry_or_duplicate_restarts_without_discarding_receipts(
    queue: FormulaRecoveryQueue, expired: bool
) -> None:
    runner, job, head = await scan_state(queue)
    head = await runner.page(job, head, QuestionScanPage([question(1)], 2, "same", False, NOW))
    job = await claim(queue)
    if expired:
        head = await runner.cursor_expired(job, head)
    else:
        head = await runner.page(job, head, QuestionScanPage([question(1)], 2, None, True, NOW))
    assert head.next_cursor is None and head.pass_number == 2 and head.drift_restarts == 1
    assert await runner.store.receipts.count_documents({}) == 1


@pytest.mark.asyncio
async def test_empty_terminal_needs_second_observation_and_stays_nonterminal(
    queue: FormulaRecoveryQueue,
) -> None:
    runner, job, head = await scan_state(queue)
    head = await runner.page(job, head, QuestionScanPage([], 0, None, True, NOW))
    head = await runner.begin_verification(await claim(queue), head)
    head = await runner.page(await claim(queue), head, QuestionScanPage([], 0, None, True, NOW))
    assert head.phase == "verify" and head.page_sequence == 1 and head.observed_until == NOW
    with pytest.raises(ValueError, match="finished"):
        await runner.page(await claim(queue), head, QuestionScanPage([], 0, None, True, NOW))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "page",
    [
        QuestionScanPage([], 0, "cursor", True, NOW),
        QuestionScanPage([], 1, None, False, NOW),
        QuestionScanPage([question(1, seller_id=42)], 1, None, True, NOW),
        QuestionScanPage([question(1)], True, None, True, NOW),
        QuestionScanPage([question(1)], 1, None, True, NOW.replace(tzinfo=None)),
    ],
)
async def test_invalid_normalized_page_cannot_advance(
    queue: FormulaRecoveryQueue, page: QuestionScanPage
) -> None:
    runner, job, head = await scan_state(queue)
    with pytest.raises(ValueError):
        await runner.page(job, head, page)
    assert await runner.store.receipts.count_documents({}) == 0
    assert (await runner.store.heads.find_one({"_id": head.id}))["checkpoint_revision"] == 0


@pytest.mark.asyncio
async def test_page_interruption_rolls_back_receipts_and_cursor(
    queue: FormulaRecoveryQueue, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner, job, head = await scan_state(queue)
    original = runner.store.checkpoint

    async def interrupted(*args: Any, **kwargs: Any) -> SheetsHistoryAcquisition:
        await original(*args, **kwargs)
        raise RuntimeError("interrupted after staging")

    monkeypatch.setattr(runner.store, "checkpoint", interrupted)
    with pytest.raises(RuntimeError, match="interrupted"):
        await runner.page(job, head, QuestionScanPage([question(1)], 2, "cursor", False, NOW))
    assert await runner.store.receipts.count_documents({}) == 0
    assert (await runner.store.heads.find_one({"_id": head.id}))["next_cursor"] is None


@pytest.mark.asyncio
async def test_lost_lease_does_not_consume_drift_budget(queue: FormulaRecoveryQueue) -> None:
    runner, job, head = await scan_state(queue)
    await queue.collection.update_one({"_id": job["_id"]}, {"$set": {"attempt_token": "other"}})
    with pytest.raises(ValueError, match="lease"):
        await runner.page(job, head, QuestionScanPage([], 0, None, True, NOW))
    assert (await runner.store.heads.find_one({"_id": head.id}))["drift_restarts"] == 0


async def verified_questions(
    queue: FormulaRecoveryQueue, rows: list[dict[str, Any]]
) -> tuple[QuestionScanStaging, SheetsHistoryAcquisition]:
    runner, job, head = await scan_state(queue)
    head = await runner.page(job, head, QuestionScanPage(rows, len(rows), None, True, NOW))
    head = await runner.begin_verification(await claim(queue), head)
    head = await runner.page(
        await claim(queue), head, QuestionScanPage(rows, len(rows), None, True, NOW)
    )
    return runner, head


@pytest.mark.asyncio
async def test_twelve_subscriptions_share_one_verified_manifest(
    queue: FormulaRecoveryQueue,
) -> None:
    rows = [
        question(
            index,
            date_created=datetime(
                2025 + (index > 4), (index + 7) % 12 + 1, 16, tzinfo=UTC
            ).isoformat(),
        )
        for index in range(1, 13)
    ]
    runner, head = await verified_questions(queue, rows)
    subscriptions = question_subscriptions(head)
    assert len(subscriptions) == 12 and len({sub.chunk_id for sub in subscriptions}) == 12
    assert subscriptions[0].date_from == START and subscriptions[-1].date_to == NOW
    assert all(sub.acquisition_id == head.id and sub.pass_number == 2 for sub in subscriptions)
    for left, right in zip(subscriptions, subscriptions[1:], strict=False):
        assert left.date_to == right.date_from
    for row in rows:
        created = datetime.fromisoformat(row["date_created"])
        assert sum(sub.date_from <= created < sub.date_to for sub in subscriptions) == 1
    first = QuestionDetailObservation(rows[0], NOW - timedelta(seconds=5))
    head = await runner.hydrate(await claim(queue), head, [first])
    restarted = QuestionScanStaging(HistoryContinuation(runner.store))
    remaining = [QuestionDetailObservation(row, NOW) for row in rows[1:]]
    head = await restarted.hydrate(await claim(queue), head, remaining)
    assert question_subscriptions(head) == subscriptions
    assert head.fetched_count == 12 and head.phase == "verify" and head.published_count == 0
    detail = await runner.store.receipts.find_one({"kind": "detail", "resource_id": "1"})
    assert detail["observed_at"] == first.observed_at
    assert await runner.store.db.questions.count_documents({}) == 0
    assert await runner.store.db.sheets_read_model_freshness.count_documents({}) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "damage", ["seller", "created", "status", "identity", "outside", "upper", "answered"]
)
async def test_invalid_details_cannot_advance_verified_manifest(
    queue: FormulaRecoveryQueue, damage: str
) -> None:
    row = question(1, date_created=(NOW - timedelta(days=1)).isoformat())
    if damage == "outside":
        row = question(1)
    if damage == "upper":
        row["date_created"] = NOW.isoformat()
    if damage == "answered":
        row["status"] = "ANSWERED"
    runner, head = await verified_questions(queue, [row])
    detail = dict(row)
    if damage == "seller":
        detail["seller_id"] = 42
    elif damage == "created":
        detail["date_created"] = (NOW - timedelta(days=2)).isoformat()
    elif damage == "status":
        detail["status"] = "CLOSED_UNANSWERED"
    elif damage == "identity":
        detail["id"] = 2
    with pytest.raises(ValueError):
        await runner.hydrate(await claim(queue), head, [QuestionDetailObservation(detail, NOW)])
    assert await runner.store.receipts.count_documents({"kind": "detail"}) == 0
    assert (await runner.store.heads.find_one({"_id": head.id}))["fetched_count"] == 0


@pytest.mark.asyncio
async def test_hydration_interruption_and_duplicate_preserve_checkpoint(
    queue: FormulaRecoveryQueue, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = question(1, date_created=(NOW - timedelta(days=1)).isoformat(), text="")
    runner, head = await verified_questions(queue, [row])
    job = await claim(queue)
    original = runner.store.checkpoint

    async def interrupted(*args: Any, **kwargs: Any) -> SheetsHistoryAcquisition:
        await original(*args, **kwargs)
        raise RuntimeError("interrupted")

    monkeypatch.setattr(runner.store, "checkpoint", interrupted)
    with pytest.raises(RuntimeError, match="interrupted"):
        await runner.hydrate(job, head, [QuestionDetailObservation(row, NOW)])
    assert await runner.store.receipts.count_documents({"kind": "detail"}) == 0
    monkeypatch.setattr(runner.store, "checkpoint", original)
    head = await runner.hydrate(job, head, [QuestionDetailObservation(row, NOW)])
    with pytest.raises(ValueError, match="already"):
        await runner.hydrate(await claim(queue), head, [QuestionDetailObservation(row, NOW)])
    assert await runner.store.receipts.count_documents({"kind": "detail"}) == 1


@pytest.mark.asyncio
async def test_unverified_head_and_oversized_hydration_are_rejected(
    queue: FormulaRecoveryQueue,
) -> None:
    runner, job, head = await scan_state(queue)
    with pytest.raises(ValueError):
        question_subscriptions(head)
    with pytest.raises(ValueError):
        await runner.hydrate(job, head, [])
    row = question(1, date_created=(NOW - timedelta(days=1)).isoformat())
    head = await runner.page(job, head, QuestionScanPage([row], 1, None, True, NOW))
    head = await runner.begin_verification(await claim(queue), head)
    head = await runner.page(await claim(queue), head, QuestionScanPage([row], 1, None, True, NOW))
    with pytest.raises(ValueError):
        await runner.hydrate(await claim(queue), head, [QuestionDetailObservation(row, NOW)] * 21)
