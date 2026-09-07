from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ServerSelectionTimeoutError

from zeler_sheets.formulas.recovery import FormulaRecoveryQueue, RecoveryRequest


@pytest.mark.asyncio
async def test_question_recovery_persists_data_and_unlocks_next_query(recovery_db: Any) -> None:
    from zeler_sheets.formulas.read_models import FormulaReadModelRepository
    from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker

    now = datetime.now(UTC)
    queue = FormulaRecoveryQueue(recovery_db, now=lambda: now)
    await queue.enqueue(request())
    calls: list[str] = []
    resource = {
        "id": 42,
        "seller_id": "pilot",
        "item_id": "MLM42",
        "text": "Is it available?",
        "status": "UNANSWERED",
        "from": {"id": 123},
        "date_created": "2026-08-20T10:00:00Z",
        "answer": None,
    }

    class Gateway:
        async def fetch_resource(self, *, seller_id: str, path: str) -> dict[str, Any]:
            assert seller_id == "pilot"
            calls.append(path)
            if path.startswith("/questions/search?"):
                return {"total": 1, "questions": [resource]}
            raise AssertionError("search identity must not fetch question details")

    class Details:
        async def fetch_resource(self, *, seller_id: str, path: str) -> dict[str, Any]:
            assert seller_id == "pilot"
            calls.append(path)
            return resource

    worker = FormulaRecoveryWorker(
        db=recovery_db, gateway=Gateway(), detail_gateway=Details(), queue=queue
    )
    assert await worker.process_one()
    repository = FormulaReadModelRepository(db=recovery_db)
    await repository.require_questions_read_model_productive(
        seller_id="pilot",
        date_from=request().date_from,
        date_to=request().date_to,
        formula="ZELERDATA_PREGUNTAS",
    )
    rows = await repository.find_questions(
        seller_id="pilot",
        date_from=request().date_from,
        date_to=request().date_to,
    )
    assert len(rows) == 1
    assert rows[0]["text"] == resource["text"]
    assert len(calls) == 2
    assert not await worker.process_one()


@pytest.mark.asyncio
async def test_incomplete_remote_search_cannot_publish_coverage(recovery_db: Any) -> None:
    from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker

    queue = FormulaRecoveryQueue(recovery_db)
    await queue.enqueue(request())

    class Gateway:
        async def fetch_resource(self, **kwargs: Any) -> dict[str, Any]:
            return {"total": 12, "questions": []}

    worker = FormulaRecoveryWorker(db=recovery_db, gateway=Gateway(), queue=queue)
    assert await worker.process_one()
    marker = await recovery_db.sheets_read_model_freshness.find_one({"_id": "pilot:questions"})
    assert marker is None or marker["state"] != "reconciled"
    job = await recovery_db.sheets_formula_recovery_jobs.find_one({"_id": request().key})
    assert job["state"] == "failed"


@pytest.mark.asyncio
async def test_local_rows_absent_from_remote_inventory_do_not_become_verified(
    recovery_db: Any,
) -> None:
    from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker

    queue = FormulaRecoveryQueue(recovery_db)
    await queue.enqueue(request())
    await recovery_db.questions.insert_one(
        {"_id": "99", "seller_id": "pilot", "date_created": request().date_from}
    )

    class Gateway:
        async def fetch_resource(self, **kwargs: Any) -> dict[str, Any]:
            return {"total": 0, "questions": []}

    await FormulaRecoveryWorker(db=recovery_db, gateway=Gateway(), queue=queue).process_one()
    marker = await recovery_db.sheets_read_model_freshness.find_one({"_id": "pilot:questions"})
    assert marker is None or marker["state"] != "reconciled"


@pytest_asyncio.fixture
async def recovery_db() -> AsyncIterator[Any]:
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        "mongodb://127.0.0.1:27028/?directConnection=true", serverSelectionTimeoutMS=1000
    )
    db = client[f"zeler_recovery_test_{uuid4().hex}"]
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


@pytest.mark.asyncio
async def test_scan_continues_when_server_reuses_cursor_with_new_rows(recovery_db: Any) -> None:
    from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker

    queue = FormulaRecoveryQueue(recovery_db)
    await queue.enqueue(request())

    class Gateway:
        pages = 0

        async def fetch_resource(self, **kwargs: Any) -> dict[str, Any]:
            self.pages += 1
            return {
                "total": 3,
                "scroll_id": "same-cursor",
                "questions": [{"id": self.pages, "date_created": "2026-07-01T00:00:00Z"}],
            }

    gateway = Gateway()
    await FormulaRecoveryWorker(db=recovery_db, gateway=gateway, queue=queue).process_one()
    job = await queue.collection.find_one({"_id": request().key})
    assert job["state"] == "completed"
    assert gateway.pages == 3


def request(seller_id: str = "pilot") -> RecoveryRequest:
    return RecoveryRequest(
        seller_id=seller_id,
        read_model="questions",
        date_from=datetime(2026, 8, 8, tzinfo=UTC),
        date_to=datetime(2026, 9, 7, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_concurrent_cells_share_one_persisted_recovery(recovery_db: Any) -> None:
    now = datetime(2026, 9, 7, tzinfo=UTC)
    queue = FormulaRecoveryQueue(recovery_db, now=lambda: now)
    ids = await asyncio.gather(*(queue.enqueue(request()) for _ in range(20)))
    assert len(set(ids)) == 1
    assert await recovery_db.sheets_formula_recovery_jobs.count_documents({}) == 1
    assert await queue.enqueue(request("other")) != ids[0]


@pytest.mark.asyncio
async def test_claim_excludes_other_workers_and_fences_expired_attempt(recovery_db: Any) -> None:
    clock = [datetime(2026, 9, 7, tzinfo=UTC)]
    queue = FormulaRecoveryQueue(recovery_db, now=lambda: clock[0])
    await queue.enqueue(request())
    first = await queue.claim()
    assert first is not None
    assert await queue.claim() is None
    clock[0] += timedelta(minutes=11)
    replacement = await queue.claim()
    assert replacement is not None
    assert replacement["attempt_token"] != first["attempt_token"]
    assert not await queue.finish(first, succeeded=True)
    assert await queue.finish(replacement, succeeded=True)


@pytest.mark.asyncio
async def test_completed_request_has_cooldown_then_can_repair_again(recovery_db: Any) -> None:
    clock = [datetime(2026, 9, 7, tzinfo=UTC)]
    queue = FormulaRecoveryQueue(recovery_db, now=lambda: clock[0])
    await queue.enqueue(request())
    claimed = await queue.claim()
    assert claimed is not None
    assert await queue.finish(claimed, succeeded=True)
    await queue.enqueue(request())
    assert await queue.claim() is None
    clock[0] += timedelta(minutes=16)
    await queue.enqueue(request())
    assert await queue.claim() is not None


def test_unrecoverable_history_is_not_scheduled() -> None:
    with pytest.raises(ValueError, match="recoverable"):
        RecoveryRequest(
            seller_id="pilot",
            read_model="stock_time_metrics",
            date_from=datetime(2026, 8, 8, tzinfo=UTC),
            date_to=datetime(2026, 9, 7, tzinfo=UTC),
        )
