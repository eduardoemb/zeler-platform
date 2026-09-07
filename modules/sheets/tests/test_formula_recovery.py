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
@pytest.mark.parametrize("outcome", ["commit", "abort", "expired_lease", "no_transaction"])
async def test_order_write_joins_recovery_transaction_without_losing_lease_guard(
    recovery_db: Any, outcome: str
) -> None:
    from zeler_platform_core.devoluciones_readiness import (
        DevolucionesLeaseLostError,
        acquire_devoluciones_operation,
    )
    from zeler_sheets.event_persistence import SheetsEventPersistence

    operation = await acquire_devoluciones_operation(
        db=recovery_db,
        seller_id="pilot",
        scope="devoluciones",
        operation_id=uuid4().hex,
        attempt_token=uuid4().hex,
    )
    if outcome == "expired_lease":
        await recovery_db.sheets_devoluciones_operations.update_one(
            {"_id": "pilot:devoluciones"}, {"$set": {"lease_until": datetime(2000, 1, 1)}}
        )
    writer = SheetsEventPersistence(db=recovery_db)
    resource = {
        "id": 42,
        "seller": {"id": "pilot"},
        "buyer": {"id": 123},
        "status": "paid",
        "date_created": "2026-08-20T10:00:00Z",
        "last_updated": "2026-08-20T11:00:00Z",
        "total_amount": 30,
        "order_items": [
            {"item": {"id": "MLM42", "seller_sku": "sku-42"}, "quantity": 1, "unit_price": 30}
        ],
    }

    async def write(session: Any) -> None:
        await writer.persist(
            event_type="orders.updated",
            seller_id="pilot",
            resource=resource,
            operation=operation,
            session=session,
        )
        await recovery_db.sheets_formula_recovery_jobs.insert_one(
            {"_id": "atomic-completion", "state": "completed"}, session=session
        )

    async with await recovery_db.client.start_session() as session:
        if outcome == "no_transaction":
            with pytest.raises(ValueError, match="active transaction"):
                await write(session)
        elif outcome == "commit":
            async with session.start_transaction():
                await write(session)
        else:
            error = DevolucionesLeaseLostError if outcome == "expired_lease" else RuntimeError
            with pytest.raises(error):
                async with session.start_transaction():
                    await write(session)
                    raise RuntimeError("abort the entire recovery publication")
    expected = 1 if outcome == "commit" else 0
    assert await recovery_db.orders.count_documents({}) == expected
    assert await recovery_db.sheets_item_sku_index.count_documents({}) == expected
    assert await recovery_db.sheets_formula_recovery_jobs.count_documents({}) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source_owner",
    [
        {"seller": {"id": 999}},
        {"seller_id": "999"},
        {"seller_id": "pilot", "seller": {"id": 999}},
        {"seller_id": "999", "seller": {"id": "pilot"}},
    ],
)
async def test_foreign_order_cannot_create_or_replace_seller_data(
    recovery_db: Any, source_owner: dict[str, Any]
) -> None:
    from zeler_platform_core.devoluciones_readiness import acquire_devoluciones_operation
    from zeler_sheets.event_persistence import SheetsEventPersistence

    operation = await acquire_devoluciones_operation(
        db=recovery_db,
        seller_id="pilot",
        scope="devoluciones",
        operation_id=uuid4().hex,
        attempt_token=uuid4().hex,
    )
    writer = SheetsEventPersistence(db=recovery_db)
    resource = {
        "id": 42,
        "seller_id": "pilot",
        "seller": {"id": "pilot"},
        "buyer": {"id": 123},
        "shipping": {"id": 456},
        "status": "paid",
        "date_created": "2026-08-20T10:00:00Z",
        "last_updated": "2026-08-20T11:00:00Z",
        "total_amount": 30,
        "order_items": [],
    }
    for preexisting in (False, True):
        if preexisting:
            await writer.persist(
                event_type="orders.updated",
                seller_id="pilot",
                resource=resource,
                operation=operation,
            )
        before = await recovery_db.orders.find({}).to_list(None)
        with pytest.raises(ValueError, match="order seller scope mismatch"):
            await writer.persist(
                event_type="orders.updated",
                seller_id="pilot",
                operation=operation,
                resource={
                    **{
                        key: value
                        for key, value in resource.items()
                        if key not in {"seller_id", "seller"}
                    },
                    **source_owner,
                    "status": "cancelled",
                    "last_updated": "2026-08-20T12:00:00Z",
                },
            )
        assert await recovery_db.orders.find({}).to_list(None) == before


@pytest.mark.asyncio
async def test_order_partial_update_uses_same_seller_state_in_real_transaction(
    recovery_db: Any,
) -> None:
    from zeler_platform_core.devoluciones_readiness import acquire_devoluciones_operation
    from zeler_sheets.event_persistence import SheetsEventPersistence

    operation = await acquire_devoluciones_operation(
        db=recovery_db,
        seller_id="pilot",
        scope="devoluciones",
        operation_id=uuid4().hex,
        attempt_token=uuid4().hex,
    )
    writer = SheetsEventPersistence(db=recovery_db)
    resource = {
        "id": 42,
        "seller_id": "pilot",
        "buyer": {"id": 123},
        "shipping": {"id": 456},
        "status": "paid",
        "date_created": "2026-08-20T10:00:00Z",
        "last_updated": "2026-08-20T11:00:00Z",
        "total_amount": 30,
        "order_items": [],
    }
    await writer.persist(
        event_type="orders.updated", seller_id="pilot", resource=resource, operation=operation
    )
    await writer.persist(
        event_type="orders.updated",
        seller_id="pilot",
        operation=operation,
        resource={
            **resource,
            "buyer": {},
            "shipping": {},
            "status": "cancelled",
            "last_updated": "2026-08-20T12:00:00Z",
        },
    )
    stored = await recovery_db.orders.find_one({"_id": "42", "seller_id": "pilot"})
    assert (stored["status"], stored["buyer_id"], stored["shipment_id"]) == (
        "cancelled",
        "123",
        "456",
    )


@pytest.mark.asyncio
async def test_app_wires_only_implemented_recovery_sources(recovery_db: Any) -> None:
    from zeler_sheets.app import build_app

    app = build_app(mongo_db=recovery_db, formula_recovery_enabled=True)
    queue = app.state.formula_recovery_queue
    await queue.enqueue(request())
    unsupported = RecoveryRequest(
        seller_id="pilot",
        read_model="orders",
        date_from=request().date_from,
        date_to=request().date_to,
    )
    with pytest.raises(ValueError):
        await queue.enqueue(unsupported)
    assert await queue.collection.count_documents({}) == 1
    disabled = build_app(mongo_db=recovery_db)
    assert not hasattr(disabled.state, "formula_recovery_queue")


@pytest.mark.asyncio
async def test_http_missing_data_recovers_in_background_and_next_http_succeeds(
    recovery_db: Any,
) -> None:
    import httpx

    from zeler_sheets.app import build_app
    from zeler_sheets.consumer import SyncJobsPollerSupervisor
    from zeler_sheets.extension_tokens import ExtensionTokenService, SellerScope
    from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker

    app = build_app(mongo_db=recovery_db, formula_recovery_enabled=True)
    app.state.extension_token_pepper = uuid4().hex
    token = await ExtensionTokenService(
        db=recovery_db,
        token_pepper=app.state.extension_token_pepper,
    ).create_token(
        owner_user_id="test-user",
        label="Local recovery integration",
        seller_scopes=[SellerScope(seller_id="123456789", nickname="PILOT")],
    )
    calls: list[str] = []

    class Gateway:
        async def fetch_resource(self, **kwargs: Any) -> dict[str, Any]:
            calls.append(kwargs["path"])
            return {"total": 0, "questions": []}

    queue = app.state.formula_recovery_queue
    await queue.ensure_indexes()
    worker = SyncJobsPollerSupervisor(
        FormulaRecoveryWorker(db=recovery_db, gateway=Gateway(), queue=queue),
        poll_interval=0.01,
    )
    payload = {
        "formula": "ZELERDATA_PREGUNTAS",
        "cuenta": "PILOT",
        "args": {
            "fecha_inicial": "2026-08-08",
            "fecha_final": "2026-09-06",
            "horario_inicial": "00:00",
            "horario_final": "23:59",
        },
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        headers = {"Authorization": f"Bearer {token.token_once}"}
        missing = await client.post("/sheets/formulas:execute", headers=headers, json=payload)
        assert missing.json()["error"]["code"] == "DATA_UNAVAILABLE"
        assert missing.json()["meta"]["recovery_requested"] is True
        assert calls == []
        await worker.start()
        try:
            async with asyncio.timeout(3):
                while not await queue.collection.find_one({"state": "completed"}):
                    await asyncio.sleep(0.01)
            ready = await client.post("/sheets/formulas:execute", headers=headers, json=payload)
            assert ready.json()["ok"] is True, ready.json()
            assert len(calls) == 1
        finally:
            await worker.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["expired_lease", "invalid_second_row", "newer_recovery"])
async def test_failed_recovery_cannot_leave_partial_writes_or_change_prior_proof(
    recovery_db: Any,
    failure: str,
) -> None:
    from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker

    clock = [datetime.now(UTC)]
    queue = FormulaRecoveryQueue(recovery_db, now=lambda: clock[0])
    await queue.enqueue(request())
    await recovery_db.sheets_read_model_freshness.insert_one(
        {"_id": "pilot:questions", "seller_id": "pilot", "state": "reconciled", "proof": "prior"}
    )
    resource = {
        "id": 42,
        "seller_id": "pilot",
        "item_id": "MLM42",
        "text": "Available?",
        "status": "UNANSWERED",
        "from": {"id": 123},
        "date_created": "2026-08-20T10:00:00Z",
    }

    class Gateway:
        async def fetch_resource(self, **kwargs: Any) -> dict[str, Any]:
            if "search?" in kwargs["path"]:
                if failure == "newer_recovery":
                    await recovery_db.sheets_read_model_freshness.update_one(
                        {"_id": "pilot:questions"},
                        {"$set": {"proof": "newer"}},
                    )
                rows = (
                    [resource, {**resource, "id": 43}]
                    if failure == "invalid_second_row"
                    else [resource]
                )
                return {"total": len(rows), "questions": rows}
            if failure == "expired_lease":
                clock[0] += timedelta(minutes=11)
            if kwargs["path"].endswith("/43"):
                return {**resource, "id": 43, "status": "INVALID"}
            return resource

    await FormulaRecoveryWorker(db=recovery_db, gateway=Gateway(), queue=queue).process_one()
    assert await recovery_db.questions.count_documents({}) == 0
    marker = await recovery_db.sheets_read_model_freshness.find_one({"_id": "pilot:questions"})
    assert marker["state"] == "reconciled"
    assert marker["proof"] == ("newer" if failure == "newer_recovery" else "prior")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("search_date", "succeeds"),
    [
        ("2026-08-20T10:00:00Z", True),
        ("2026-08-20T10:00:00.000435Z", True),
        ("2026-08-20T10:00:00.001435Z", False),
    ],
)
async def test_question_recovery_persists_data_and_unlocks_next_query(
    recovery_db: Any, search_date: str, succeeds: bool
) -> None:
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
                return {"total": 1, "questions": [{**resource, "date_created": search_date}]}
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
    if not succeeds:
        job = await queue.collection.find_one({"_id": request().key})
        assert job["state"] == "failed"
        assert job["failure_reason"] == "source_incomplete"
        assert await recovery_db.questions.count_documents({}) == 0
        return
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
@pytest.mark.parametrize("prior_is_later", [False, True])
async def test_question_recovery_rechecks_prior_coverage_and_the_gap(
    recovery_db: Any, prior_is_later: bool
) -> None:
    from zeler_sheets.formulas.read_models import FormulaReadModelRepository
    from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker

    prior_start = datetime(2026, 6, 1, tzinfo=UTC)
    prior_end = datetime(2026, 7, 11, tzinfo=UTC)
    earliest = prior_start
    requested = request()
    if prior_is_later:
        requested = RecoveryRequest("pilot", "questions", prior_start, prior_end)
        prior_start, prior_end = request().date_from, request().date_to
    await recovery_db.sheets_read_model_freshness.insert_one(
        {
            "_id": "pilot:questions",
            "seller_id": "pilot",
            "read_model": "questions",
            "state": "reconciled",
            "date_from": prior_start,
            "reconciled_until": prior_end,
        }
    )
    resources = [
        {
            "id": 40 + month,
            "seller_id": "pilot",
            "item_id": "MLM42",
            "text": "Available?",
            "status": "UNANSWERED",
            "from": {"id": 123},
            "date_created": f"2026-{month:02d}-20T10:00:00Z",
        }
        for month in (6, 7, 8)
    ]
    fetched: list[int] = []

    class Gateway:
        async def fetch_resource(self, *, seller_id: str, path: str) -> dict[str, Any]:
            assert seller_id == "pilot"
            if path.startswith("/questions/search?"):
                return {"total": 3, "questions": resources}
            question_id = int(path.rsplit("/", 1)[-1])
            fetched.append(question_id)
            return next(row for row in resources if row["id"] == question_id)

    queue = FormulaRecoveryQueue(recovery_db)
    await queue.enqueue(requested)
    await FormulaRecoveryWorker(db=recovery_db, queue=queue, gateway=Gateway()).process_one()
    assert fetched == [46, 47, 48]
    assert await recovery_db.questions.count_documents({"seller_id": "pilot"}) == 3
    await FormulaReadModelRepository(db=recovery_db).require_questions_read_model_productive(
        seller_id="pilot",
        date_from=earliest,
        date_to=request().date_to,
        formula="ZELERDATA_PREGUNTAS",
    )


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
@pytest.mark.parametrize("failure", ["connection", "gateway_quota"])
async def test_transient_source_failure_retries_without_another_formula(
    recovery_db: Any,
    failure: str,
) -> None:
    import httpx

    from zeler_platform_core.clients.meli_gateway_client import GatewayRateLimitError
    from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker

    clock = [datetime.now(UTC)]
    queue = FormulaRecoveryQueue(recovery_db, now=lambda: clock[0])
    await queue.enqueue(request())

    class Gateway:
        calls = 0

        async def fetch_resource(self, **kwargs: Any) -> dict[str, Any]:
            self.calls += 1
            if self.calls == 1:
                if failure == "gateway_quota":
                    raise GatewayRateLimitError(
                        retry_after_seconds=30,
                        response=httpx.Response(
                            429, request=httpx.Request("GET", "https://example.test")
                        ),
                    )
                raise httpx.ConnectError("sensitive upstream diagnostic")
            return {"total": 0, "questions": []}

    worker = FormulaRecoveryWorker(db=recovery_db, gateway=Gateway(), queue=queue)
    assert await worker.process_one()
    job = await queue.collection.find_one({"_id": request().key})
    assert job["state"] == "pending"
    assert job["failure_reason"] == "source_temporarily_unavailable"
    assert "sensitive" not in str(job)
    assert not await worker.process_one()
    clock[0] += timedelta(minutes=5)
    assert await worker.process_one()
    job = await queue.collection.find_one({"_id": request().key})
    assert job["state"] == "completed"
    assert "failure_reason" not in job


@pytest.mark.asyncio
@pytest.mark.parametrize("status, attempts", [(429, 3), (503, 3), (403, 1)])
async def test_upstream_status_controls_bounded_retries(
    recovery_db: Any, status: int, attempts: int
) -> None:
    import httpx

    from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker

    clock = [datetime.now(UTC)]
    queue = FormulaRecoveryQueue(recovery_db, now=lambda: clock[0])
    await queue.enqueue(request())

    class Gateway:
        async def fetch_resource(self, **kwargs: Any) -> dict[str, Any]:
            response = httpx.Response(status, request=httpx.Request("GET", "https://example.test"))
            response.raise_for_status()
            raise AssertionError("failure response must raise")

    worker = FormulaRecoveryWorker(db=recovery_db, gateway=Gateway(), queue=queue)
    for _ in range(attempts):
        assert await worker.process_one()
        clock[0] += timedelta(minutes=5)
    assert not await worker.process_one()
    job = await queue.collection.find_one({"_id": request().key})
    assert job["state"] == "failed"
    assert job["attempts"] == attempts


@pytest.mark.asyncio
async def test_crashed_recovery_stops_after_three_attempts(recovery_db: Any) -> None:
    clock = [datetime.now(UTC)]
    queue = FormulaRecoveryQueue(recovery_db, now=lambda: clock[0])
    await queue.enqueue(request())
    for expected in range(1, 4):
        job = await queue.claim()
        assert job is not None and job["attempts"] == expected
        clock[0] += timedelta(minutes=11)
    assert await queue.claim() is None
    job = await queue.collection.find_one({"_id": request().key})
    assert job["state"] == "failed"
    assert job["failure_reason"] == "attempts_exhausted"


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
