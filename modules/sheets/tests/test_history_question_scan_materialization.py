"""Verified v4 scan materialization/provenance and stale-cursor transport fakes."""

from __future__ import annotations

import copy
import importlib.util
import socket
import sys
from datetime import timedelta
from importlib.machinery import ModuleSpec, SourceFileLoader
from pathlib import Path
from typing import Any, cast

import pytest

from zeler_platform_core.models import SheetsHistoryAcquisition, SheetsHistoryReceipt
from zeler_sheets.formulas.read_models import (
    FormulaReadModelRepository,
    read_model_reconciliation_marker_covers,
)
from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker
from zeler_sheets.history_acquisition import HistoryAcquisitionStore, HistoryConflictError
from zeler_sheets.history_continuation import HistoryContinuation
from zeler_sheets.history_question_publication import HistoryQuestionPublisher
from zeler_sheets.history_question_worker import HistoryQuestionsWorker
from zeler_sheets.history_questions import QuestionScanStaging
from zeler_sheets.item_projection import item_source_fingerprint

spec = cast(
    ModuleSpec,
    importlib.util.spec_from_file_location(
        "_readmission_fakes", Path(__file__).with_name("test_history_question_readmission.py")
    ),
)
f = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = f
cast(SourceFileLoader, spec.loader).exec_module(f)


def question(identity: int) -> dict[str, Any]:
    created = f.START + timedelta(days=20)
    return {
        "id": identity,
        "seller_id": int(f.SELLER),
        "item_id": "MLM123",
        "from": {"id": 888},
        "status": "ANSWERED",
        "text": "synthetic question",
        "answer": {
            "text": "synthetic answer",
            "status": "ACTIVE",
            "date_created": (created + timedelta(minutes=1)).isoformat(),
        },
        "date_created": created.isoformat(),
    }


class Gateway:
    def __init__(self, resources: dict[str, dict[str, Any]]) -> None:
        self.resources = resources
        self.calls: list[str] = []

    async def fetch_resource(self, *, seller_id: str, path: str) -> dict[str, Any]:
        self.calls.append(path)
        if path.startswith("/questions/search"):
            return {"total": 1, "questions": [question(999)], "scroll_id": "synthetic-new"}
        identity = path.split("/questions/", 1)[1].split("?", 1)[0]
        return copy.deepcopy(self.resources[identity])


def prepared(count: int = 210) -> tuple[Any, Any, Any, QuestionScanStaging, Gateway]:
    db, queue, request = f.seeded()
    head = SheetsHistoryAcquisition.model_validate(
        {
            **db["sheets_history_acquisitions"].docs[0],
            "phase": "verify",
            "pass_number": 2,
            "page_sequence": 10,
            "next_cursor": None,
            "source_total": count,
            "discovered_count": count,
            "observed_from": f.NOW - timedelta(seconds=10),
            "observed_until": f.NOW,
            "updated_at": f.NOW,
        }
    )
    db["sheets_history_acquisitions"].docs = [f.normalized(head.model_dump(by_alias=True))]
    job = db["sheets_formula_recovery_jobs"].docs[0]
    job.update(
        state="running",
        attempt_token="synthetic-owner",  # noqa: S106 -- noncredential synthetic claim owner.
        lease_until=f.NOW + timedelta(minutes=10),
        attempts=1,
        history_pass_number=2,
    )
    resources = {str(i): question(i) for i in range(1, count + 1)}
    for pass_number in (1, 2):
        for identity, resource in resources.items():
            receipt = SheetsHistoryReceipt(
                _id=f"{head.id}:1:{pass_number}:membership:{identity}",
                acquisition_id=head.id,
                seller_id=f.SELLER,
                read_model="questions",
                generation=1,
                pass_number=pass_number,
                page_sequence=pass_number,
                kind="membership",
                resource_id=identity,
                observed_at=f.NOW - timedelta(seconds=10 if pass_number == 1 else 0),
                source_payload=resource,
                source_hash=item_source_fingerprint(resource),
            )
            db["sheets_history_receipts"].docs.append(
                f.normalized(receipt.model_dump(by_alias=True))
            )
    runner = QuestionScanStaging(HistoryContinuation(HistoryAcquisitionStore(db, queue)))
    return db, queue, head, runner, Gateway(resources)


async def claimed(queue: Any) -> dict[str, Any]:
    result = await queue.claim(history=True)
    assert result is not None
    return cast(dict[str, Any], result)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("sockets forbidden")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


@pytest.mark.asyncio
async def test_210_two_complete_manifests_materialize_with_zero_extra_detail_gets() -> None:
    db, queue, head, runner, gateway = prepared()
    job = copy.deepcopy(db["sheets_formula_recovery_jobs"].docs[0])
    for _ in range(11):
        head = await runner.fetch_and_hydrate(job, head, gateway)
        if head.fetched_count == 210:
            break
        job = await claimed(queue)
    assert gateway.calls == [] and head.fetched_count == 210
    details = [r for r in db["sheets_history_receipts"].docs if r["kind"] == "detail"]
    assert len(details) == 210 and all(
        r["source_version"] == "questions.scan.v4.verified" for r in details
    )


@pytest.mark.asyncio
async def test_exact_reader_fields_and_year_proof_after_real_publisher_fakes() -> None:
    db, queue, head, runner, gateway = prepared()
    job = copy.deepcopy(db["sheets_formula_recovery_jobs"].docs[0])
    for _ in range(11):
        head = await runner.fetch_and_hydrate(job, head, gateway)
        job = await claimed(queue)
        if head.fetched_count == 210:
            break
    assert gateway.calls == []
    head = await runner.begin_publication(job, head)
    job = await claimed(queue)
    publisher = HistoryQuestionPublisher(runner.continuation)
    for _ in range(11):
        head = await publisher.batch(job, head)
        job = await claimed(queue)
        if head.published_count == 210:
            break
    head = await publisher.finalize(job, head)
    assert head.phase == "completed"
    marker = db["sheets_read_model_freshness"].docs[0]
    assert read_model_reconciliation_marker_covers(
        marker, date_from=f.START, date_to=f.END, now=f.NOW
    )
    repo = FormulaReadModelRepository(db=db)
    await repo.require_questions_read_model_productive(
        seller_id=f.SELLER, date_from=f.START, date_to=f.END, formula="ZELERDATA_PREGUNTAS"
    )
    rows = await repo.find_questions(seller_id=f.SELLER, date_from=f.START, date_to=f.END)
    assert len(rows) == 210 and all(
        r["text"] == "synthetic question"
        and r["answer"]["text"] == "synthetic answer"
        and r["from_user_id"] == "888"
        for r in rows
    )


@pytest.mark.asyncio
async def test_missing_field_fetches_only_that_identity_under_existing_gateway() -> None:
    db, queue, head, runner, gateway = prepared(3)
    for receipt in db["sheets_history_receipts"].docs:
        if receipt["resource_id"] == "1":
            receipt["source_payload"].pop("text")
            receipt["source_hash"] = item_source_fingerprint(receipt["source_payload"])
    result = await runner.fetch_and_hydrate(
        copy.deepcopy(db["sheets_formula_recovery_jobs"].docs[0]), head, gateway
    )
    assert result.fetched_count == 3 and gateway.calls == ["/questions/1?api_version=4"]


@pytest.mark.asyncio
@pytest.mark.parametrize("guard", ["old_partial", "hash_drift", "malformed_answer", "wrong_seller"])
async def test_unproven_or_malformed_scan_has_no_detail_requests(guard: str) -> None:
    db, queue, head, runner, gateway = prepared()
    if guard == "old_partial":
        db["sheets_history_receipts"].docs = [
            r
            for r in db["sheets_history_receipts"].docs
            if not (r["pass_number"] == 1 and int(r["resource_id"]) > 150)
        ]
    else:
        for receipt in db["sheets_history_receipts"].docs:
            if receipt["resource_id"] == "1":
                if guard == "hash_drift" and receipt["pass_number"] == 2:
                    receipt["source_hash"] = "0" * 64
                elif guard == "malformed_answer":
                    receipt["source_payload"]["answer"] = False
                    receipt["source_hash"] = item_source_fingerprint(receipt["source_payload"])
                elif guard == "wrong_seller":
                    receipt["source_payload"]["seller_id"] = 123
                    receipt["source_hash"] = item_source_fingerprint(receipt["source_payload"])
    before = copy.deepcopy(db["sheets_history_receipts"].docs)
    with pytest.raises(ValueError):
        await runner.fetch_and_hydrate(
            copy.deepcopy(db["sheets_formula_recovery_jobs"].docs[0]), head, gateway
        )
    assert gateway.calls == [] and db["sheets_history_receipts"].docs == before


@pytest.mark.asyncio
async def test_outside_range_is_excluded_without_fetch_or_false_publication() -> None:
    db, queue, head, runner, gateway = prepared(3)
    for receipt in db["sheets_history_receipts"].docs:
        if receipt["resource_id"] == "1":
            receipt["source_payload"]["date_created"] = (f.START - timedelta(days=1)).isoformat()
            receipt["source_hash"] = item_source_fingerprint(receipt["source_payload"])
    head = await runner.fetch_and_hydrate(
        copy.deepcopy(db["sheets_formula_recovery_jobs"].docs[0]), head, gateway
    )
    assert (
        gateway.calls == []
        and head.source_total == 3
        and head.discovered_count == 3
        and head.fetched_count == 2
    )
    exclusions = [r for r in db["sheets_history_receipts"].docs if r["kind"] == "exclusion"]
    assert len(exclusions) == 1 and exclusions[0]["resource_id"] == "1"
    head = await runner.begin_publication(await claimed(queue), head)
    publisher = HistoryQuestionPublisher(runner.continuation)
    head = await publisher.batch(await claimed(queue), head)
    head = await publisher.finalize(await claimed(queue), head)
    assert head.phase == "completed" and len(db.questions.docs) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("age", [300, None, -1])
async def test_cursor_age_unknown_future_or_expired_blocks_transport(age: int | None) -> None:
    db, queue, request = f.seeded()
    raw = db["sheets_history_acquisitions"].docs[0]
    raw["observed_from"] = raw["observed_until"] = (
        None if age is None else f.NOW - timedelta(seconds=age)
    )
    head = SheetsHistoryAcquisition.model_validate(raw)
    job = db["sheets_formula_recovery_jobs"].docs[0]
    job.update(
        state="running",
        attempt_token="owner",  # noqa: S106 -- noncredential synthetic claim owner.
        lease_until=f.NOW + timedelta(minutes=10),
        updated_at=f.NOW,
    )
    runner = QuestionScanStaging(HistoryContinuation(HistoryAcquisitionStore(db, queue)))
    gateway = Gateway({})
    with pytest.raises(HistoryConflictError):
        await runner.fetch_and_stage(copy.deepcopy(job), head, gateway)
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_new_pass_keeps_global_page_sequence_and_requires_its_own_observation() -> None:
    db, queue, head, runner, gateway = prepared(3)
    raw = head.model_dump(by_alias=True)
    raw.update(pass_number=1, phase="hydrate", page_sequence=5)
    head = SheetsHistoryAcquisition.model_validate(raw)
    db["sheets_history_acquisitions"].docs = [raw]
    db["sheets_history_receipts"].docs = [
        r for r in db["sheets_history_receipts"].docs if r["pass_number"] == 1
    ]
    job = db["sheets_formula_recovery_jobs"].docs[0]
    job["history_pass_number"] = 1
    next_head = await runner.begin_verification(copy.deepcopy(job), head)
    assert next_head.page_sequence == 5 and next_head.observed_until is None


@pytest.mark.asyncio
async def test_worker_classifies_stale_cursor_without_http_or_automatic_restart() -> None:
    db, queue, request = f.seeded()
    db["sheets_formula_recovery_jobs"].docs[0]["state"] = "pending"
    gateway = Gateway({})
    worker = HistoryQuestionsWorker(
        FormulaRecoveryWorker(db=db, queue=queue, gateway=gateway, detail_gateway=gateway)
    )
    await worker.process_once()
    job = db["sheets_formula_recovery_jobs"].docs[0]
    assert (
        job["state"] == "failed"
        and job["failure_reason"] == "source_cursor_expired"
        and gateway.calls == []
    )
    assert db["sheets_history_acquisitions"].docs[0]["page_sequence"] == 3


@pytest.mark.asyncio
async def test_nanosecond_iso_is_materialized_and_not_discarded() -> None:
    db, queue, head, runner, gateway = prepared(1)
    for receipt in db["sheets_history_receipts"].docs:
        receipt["source_payload"]["date_created"] = "2026-05-05T12:00:00.830123456+00:00"
        receipt["source_payload"]["answer"]["date_created"] = "2026-05-05T12:01:00.830123456+00:00"
        receipt["source_hash"] = item_source_fingerprint(receipt["source_payload"])
    head = await runner.fetch_and_hydrate(
        copy.deepcopy(db["sheets_formula_recovery_jobs"].docs[0]), head, gateway
    )
    assert head.fetched_count == 1 and gateway.calls == []


@pytest.mark.asyncio
async def test_question_source_drift_release_does_not_reset_head_or_attempts() -> None:
    db, queue, head, runner, gateway = prepared(1)
    before = copy.deepcopy(db["sheets_history_acquisitions"].docs)
    job = copy.deepcopy(db["sheets_formula_recovery_jobs"].docs[0])
    await runner.continuation.release(job, head, reason="source_drift")
    assert db["sheets_history_acquisitions"].docs == before
    assert db["sheets_formula_recovery_jobs"].docs[0]["attempts"] == 1
    assert db["sheets_formula_recovery_jobs"].docs[0]["state"] == "failed"
