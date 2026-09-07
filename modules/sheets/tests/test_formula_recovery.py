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
@pytest.mark.parametrize("missing_field", ["buyer", "shipping"])
async def test_missing_identity_keeps_sales_but_rejects_consumers_that_require_it(
    recovery_db: Any,
    missing_field: str,
) -> None:
    import json
    from pathlib import Path

    import httpx
    from pymongo.errors import WriteError

    from zeler_sheets.formulas.dispatcher import (
        FormulaDataUnavailableError,
        FormulaExecutionContext,
    )
    from zeler_sheets.formulas.handlers_orders_questions import OrderQuestionFormulaHandlers
    from zeler_sheets.formulas.read_models import FormulaReadModelRepository
    from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker
    from zeler_sheets.formulas.registry import FormulaRegistry

    schema = json.loads(Path("infra/mongo/schemas/orders.json").read_text())
    await recovery_db.create_collection("orders", validator={"$jsonSchema": schema["$jsonSchema"]})
    requested = RecoveryRequest(
        seller_id="pilot",
        read_model="orders",
        date_from=request().date_from,
        date_to=request().date_to,
    )
    queue = FormulaRecoveryQueue(recovery_db, enabled_models=frozenset({"orders"}))
    await queue.enqueue(requested)
    resource = {
        "id": 42,
        "seller": {"id": "pilot"},
        "buyer": {} if missing_field == "buyer" else {"id": 123},
        "status": "paid",
        "date_created": "2026-08-20T10:00:00Z",
        "last_updated": "2026-08-20T11:00:00Z",
        "total_amount": 30,
        "order_items": [
            {"item": {"id": "MLM42", "seller_sku": "sku-42"}, "quantity": 1, "unit_price": 30}
        ],
    }
    calls: list[str] = []

    class Gateway:
        async def fetch_resource(self, **kwargs: Any) -> dict[str, Any]:
            calls.append(kwargs["path"])
            return {"paging": {"total": 1}, "results": [resource]}

        async def request(self, **kwargs: Any) -> httpx.Response:
            calls.append(kwargs["path"])
            return httpx.Response(206, headers={"X-Content-Missing": missing_field}, json=resource)

    await FormulaRecoveryWorker(db=recovery_db, gateway=Gateway(), queue=queue).process_one()
    job = await queue.collection.find_one({"_id": requested.key})
    assert job["state"] == "completed", job.get("failure_reason")
    stored = await recovery_db.orders.find_one({"_id": "42"})
    identity_field = "buyer_id" if missing_field == "buyer" else "shipment_id"
    assert identity_field not in stored
    assert stored["unavailable_fields"] == [identity_field]
    undeclared = {key: value for key, value in stored.items() if key != "unavailable_fields"}
    for invalid in (
        ()
        if missing_field == "shipping"
        else (
            undeclared,
            {**undeclared, "unavailable_fields": ["feedback"]},
            {**stored, "buyer_id": "123"},
            {**stored, "unavailable_fields": ["buyer_id", "unexpected"]},
        )
    ):
        with pytest.raises(WriteError):
            await recovery_db.orders.insert_one({**invalid, "_id": "invalid"})
    handlers = OrderQuestionFormulaHandlers(FormulaReadModelRepository(db=recovery_db))

    def context(name: str, **args: Any) -> FormulaExecutionContext:
        return FormulaExecutionContext(
            contract=FormulaRegistry.default().find_required(name),
            cuenta="pilot",
            seller_id="pilot",
            seller_nickname="pilot",
            token_id=uuid4().hex,
            request_id=None,
            args={"fecha_inicial": "2026-08-08", "fecha_final": "2026-09-06", **args},
        )

    result = await handlers.sheetseller_ventas_totales(context("ZELERDATA_VENTASTOTALES"))
    assert result.values == [[30]]
    if missing_field == "buyer":
        with pytest.raises(FormulaDataUnavailableError) as missing:
            await handlers.sheetseller_ordenes(context("ZELERDATA_ORDENES", compradores="123"))
        assert missing.value.read_model == "orders"
    else:
        for method, name, args in (
            (handlers.sheetseller_ordenes, "ORDENES", {}),
            (handlers.sheetseller_ordenes_por_sku, "ORDENESPORSKU", {"skus": ["sku-42"]}),
            (handlers.sheetseller_compradores, "COMPRADORES", {"id_ordenes": ["42"]}),
        ):
            with pytest.raises(FormulaDataUnavailableError) as missing:
                await method(context("ZELERDATA_" + name, **args))
            assert missing.value.read_model == "orders"
            assert missing.value.date_from is not None and missing.value.date_to is not None
        # An unrelated SKU has no displayed order; it must not require this shipment.
        await handlers.sheetseller_ordenes_por_sku(
            context("ZELERDATA_ORDENESPORSKU", skus=["unrelated"], compradores="si")
        )
    assert len(calls) == 2  # Formula evaluation never re-fetches the source.
    assert calls[-1] == "/orders/42"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        None,
        "empty",
        "missing_total",
        "foreign_detail",
        "extra_mongo_row",
        "partial_response",
        "partial_recovered",
    ],
)
async def test_order_recovery_publishes_only_complete_owned_inventory(
    recovery_db: Any, failure: str | None
) -> None:
    import httpx

    from zeler_sheets.formulas.read_models import read_model_reconciliation_marker_covers
    from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker

    requested = RecoveryRequest(
        seller_id="pilot",
        read_model="orders",
        date_from=request().date_from,
        date_to=request().date_to,
    )
    queue = FormulaRecoveryQueue(recovery_db, enabled_models=frozenset({"orders"}))
    await queue.enqueue(requested)
    resources = [
        {
            "id": identity,
            "seller": {"id": "pilot"},
            "buyer": {"id": 123},
            "status": "paid",
            "date_created": "2026-08-20T10:00:00Z",
            "last_updated": "2026-08-20T11:00:00Z",
            "total_amount": 30,
            "order_items": [{"item": {"id": "MLM42"}, "quantity": 1, "unit_price": 30}],
        }
        for identity in (42, 43)
    ]
    if failure == "extra_mongo_row":
        await recovery_db.orders.insert_one(
            {"_id": "999", "seller_id": "pilot", "date_created": datetime(2026, 8, 20)}
        )
    if failure == "partial_recovered":
        from zeler_sheets.event_persistence import _canonical_order_document

        for resource in resources:
            await recovery_db.orders.insert_one(
                _canonical_order_document(
                    {
                        **resource,
                        "shipping": {"id": 456},
                        "feedback": {"sale": {"fulfilled": True}},
                    },
                    seller_id="pilot",
                    sale_fee_synced_at=datetime.now(UTC),
                )
            )
    before = await recovery_db.orders.find({}).to_list(None)
    calls: list[str] = []

    class Gateway:
        async def fetch_resource(self, *, seller_id: str, path: str) -> dict[str, Any]:
            from urllib.parse import parse_qs, urlsplit

            assert seller_id == "pilot"
            calls.append(path)
            offset = int(parse_qs(urlsplit(path).query)["offset"][0])
            if failure == "empty":
                return {"paging": {"total": 0}, "results": []}
            return {
                "paging": {} if failure == "missing_total" else {"total": 2},
                "results": resources[offset : offset + 1],
            }

        async def request(self, *, method: str, seller_id: str, path: str) -> httpx.Response:
            assert method == "GET" and seller_id == "pilot"
            calls.append(path)
            resource = resources[int(path.rsplit("/", 1)[1]) - 42]
            if failure == "foreign_detail":
                resource = {**resource, "seller": {"id": "foreign"}}
            if failure == "partial_response":
                return httpx.Response(206, headers={"X-Content-Missing": "buyer"}, json=resource)
            if failure == "partial_recovered":
                return httpx.Response(
                    206,
                    headers={"X-Content-Missing": "buyer, shipping, feedback, seller"},
                    json={
                        **resource,
                        "buyer": {},
                        "shipping": {},
                        "seller": {},
                        "feedback": {},
                        "status": "cancelled",
                        "last_updated": "2026-08-20T12:00:00Z",
                    },
                )
            return httpx.Response(200, json=resource)

    await FormulaRecoveryWorker(db=recovery_db, gateway=Gateway(), queue=queue).process_one()
    assert calls, "order source acquisition must actually run"
    job = await queue.collection.find_one({"_id": requested.key})
    marker = await recovery_db.sheets_read_model_freshness.find_one({"_id": "pilot:orders"})
    if failure not in {None, "empty", "partial_recovered", "partial_response"}:
        assert job["state"] == "failed"
        assert await recovery_db.orders.find({}).to_list(None) == before
        assert marker is None
    else:
        assert job["state"] == "completed", job.get("failure_reason")
        assert await recovery_db.orders.count_documents({"seller_id": "pilot"}) == (
            0 if failure == "empty" else 2
        )
        assert len(calls) == (1 if failure == "empty" else 4)
        assert read_model_reconciliation_marker_covers(
            marker, date_from=requested.date_from, date_to=requested.date_to
        )
        operation = await recovery_db.sheets_devoluciones_operations.find_one(
            {"_id": "pilot:devoluciones"}
        )
        assert operation["state"] == "succeeded"
        if failure == "partial_response":
            for stored in await recovery_db.orders.find({}).to_list(None):
                assert "buyer_id" not in stored
                assert stored["unavailable_fields"] == ["buyer_id"]
        if failure == "partial_recovered":
            for stored in await recovery_db.orders.find({}).to_list(None):
                assert stored["status"] == "cancelled"
                assert stored["buyer_id"] == "123"
                assert stored["shipment_id"] == "456"
                assert stored["feedback"] == {"sale": {"fulfilled": True}}


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
        read_model="shipments",
        date_from=request().date_from,
        date_to=request().date_to,
    )
    with pytest.raises(ValueError):
        await queue.enqueue(unsupported)
    assert await queue.collection.count_documents({}) == 1
    disabled = build_app(mongo_db=recovery_db)
    assert not hasattr(disabled.state, "formula_recovery_queue")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("read_model", "partial"),
    [
        ("questions", False),
        ("orders", False),
        ("orders", True),
        ("order_ids", False),
        ("order_ids", True),
    ],
)
async def test_http_missing_data_recovers_in_background_and_next_http_succeeds(
    recovery_db: Any,
    read_model: str,
    partial: bool,
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
    order = {
        "id": 42,
        "seller": {"id": "123456789"},
        "buyer": {} if partial and read_model == "orders" else {"id": 123},
        "status": "paid",
        "date_created": "2026-08-20T10:00:00Z",
        "last_updated": "2026-08-20T11:00:00Z",
        "total_amount": 30,
        "order_items": [{"item": {"id": "MLM42"}, "quantity": 1, "unit_price": 30}],
    }

    class Gateway:
        async def fetch_resource(self, **kwargs: Any) -> dict[str, Any]:
            calls.append(kwargs["path"])
            if read_model in {"orders", "order_ids"}:
                return {"paging": {"total": 1}, "results": [order]}
            return {"total": 0, "questions": []}

        async def request(self, **kwargs: Any) -> httpx.Response:
            calls.append(kwargs["path"])
            if partial and read_model == "order_ids":
                return httpx.Response(
                    206, headers={"X-Content-Missing": "seller"}, json={**order, "seller": {}}
                )
            if partial:
                return httpx.Response(206, headers={"X-Content-Missing": "buyer"}, json=order)
            return httpx.Response(200, json=order)

    queue = app.state.formula_recovery_queue
    await queue.ensure_indexes()
    worker = SyncJobsPollerSupervisor(
        FormulaRecoveryWorker(db=recovery_db, gateway=Gateway(), queue=queue),
        poll_interval=0.01,
    )
    payload = {
        "formula": {
            "questions": "ZELERDATA_PREGUNTAS",
            "orders": "ZELERDATA_VENTASTOTALES",
            "order_ids": "ZELERDATA_COMPRADORES",
        }[read_model],
        "cuenta": "PILOT",
        "args": {
            "fecha_inicial": "2026-08-08",
            "fecha_final": "2026-09-06",
            "horario_inicial": "00:00",
            "horario_final": "23:59",
        },
    }
    if read_model == "order_ids":
        payload["args"] = {"id_ordenes": ["42"]}
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
            assert len(calls) == {"questions": 1, "orders": 2, "order_ids": 3}[read_model]
            if read_model == "orders":
                assert ready.json()["values"] == [[30]]
            elif read_model == "order_ids":
                assert len(ready.json()["values"]) == 1
                assert await recovery_db.orders.count_documents({"_id": "42"}) == 1
        finally:
            await worker.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["foreign", "missing_owner", "wrong_id", "missing_search"])
async def test_id_recovery_never_publishes_unproven_requested_orders(
    recovery_db: Any, failure: str
) -> None:
    import httpx

    from zeler_sheets.formulas.recovery import OrderIdsRecoveryRequest
    from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker

    queue = FormulaRecoveryQueue(recovery_db)
    requested = OrderIdsRecoveryRequest("pilot", ("42",))
    await queue.enqueue(requested)
    detail = {
        "id": 43 if failure == "wrong_id" else 42,
        "seller": {}
        if failure == "missing_owner"
        else {"id": "foreign" if failure == "foreign" else "pilot"},
        "date_created": "2026-08-20T10:00:00Z",
    }
    calls: list[str] = []

    class Gateway:
        async def request(self, **kwargs: Any) -> httpx.Response:
            calls.append(kwargs["path"])
            return httpx.Response(200, json=detail)

        async def fetch_resource(self, **kwargs: Any) -> dict[str, Any]:
            calls.append(kwargs["path"])
            return {"paging": {"total": 0}, "results": []}

    await FormulaRecoveryWorker(db=recovery_db, gateway=Gateway(), queue=queue).process_one()
    job = await queue.collection.find_one({"_id": requested.key})
    assert job["state"] == "failed"
    assert job["failure_reason"] == "source_incomplete"
    assert await recovery_db.orders.count_documents({}) == 0
    assert await recovery_db.sheets_read_model_freshness.count_documents({}) == 0
    assert len(calls) == (2 if failure == "missing_search" else 1)


def test_id_requests_coalesce_and_reject_non_order_or_unbounded_targets() -> None:
    from zeler_sheets.formulas.recovery import OrderIdsRecoveryRequest

    request_a = OrderIdsRecoveryRequest("pilot", ("43", "42", "42"))
    assert request_a.order_ids == ("42", "43")
    assert request_a.key == OrderIdsRecoveryRequest("pilot", ("42", "43")).key
    assert request_a.key != OrderIdsRecoveryRequest("other", ("42", "43")).key
    for identities in ((), ("../42",), ("４２",), tuple(str(i) for i in range(101))):
        with pytest.raises(ValueError):
            OrderIdsRecoveryRequest("pilot", identities)
    with pytest.raises(ValueError):
        OrderIdsRecoveryRequest("pilot", ("42",), read_model="questions")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "formula",
    [
        "ORDENES",
        "VENTASTOTALES",
        "UNIDADESVENDIDAS",
        "ORDENESPORSKU",
        "PRODUCTOSINVENTA",
        "VENTAPORDIAS",
        "VENTASYSTOCK",
        "TOPVENTASUNIDADES",
        "TOPVENTASDINERO",
    ],
)
async def test_bounded_order_formulas_cannot_present_unproven_inventory_as_complete(
    recovery_db: Any,
    formula: str,
) -> None:
    from zeler_sheets.formulas.dispatcher import (
        FormulaDataUnavailableError,
        FormulaDispatcher,
        FormulaExecutionContext,
    )
    from zeler_sheets.formulas.handlers_orders_questions import (
        build_order_question_formula_handlers,
    )
    from zeler_sheets.formulas.read_models import FormulaReadModelRepository
    from zeler_sheets.formulas.registry import FormulaRegistry

    name = "ZELERDATA_" + formula
    context = FormulaExecutionContext(
        contract=FormulaRegistry.default().find_required(name),
        cuenta="pilot",
        seller_id="pilot",
        seller_nickname="pilot",
        token_id=uuid4().hex,
        request_id=None,
        args={
            "fecha_inicial": "2026-08-08",
            "fecha_final": "2026-09-06",
            "skus": ["sku-42"],
            "id_publicaciones": ["MLM42"],
            "cantidad_top": 10,
            "rango_dias": 30,
        },
    )
    dispatcher = FormulaDispatcher(
        build_order_question_formula_handlers(
            FormulaReadModelRepository(db=recovery_db),
            now_fn=lambda: datetime(2026, 9, 7, tzinfo=UTC),
        )
    )
    with pytest.raises(FormulaDataUnavailableError) as missing:
        await dispatcher.execute(context)
    assert missing.value.read_model == "orders"
    assert missing.value.date_from is not None and missing.value.date_to is not None


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
@pytest.mark.parametrize("succeeded", [True, False])
async def test_terminal_request_stays_scheduled_through_cooldown_without_another_recalculation(
    recovery_db: Any,
    succeeded: bool,
) -> None:
    clock = [datetime(2026, 9, 7, tzinfo=UTC)]
    queue = FormulaRecoveryQueue(recovery_db, now=lambda: clock[0])
    await queue.enqueue(request())
    claimed = await queue.claim()
    assert claimed is not None
    assert await queue.finish(claimed, succeeded=succeeded)
    terminal = await queue.collection.find_one({"_id": request().key})
    await asyncio.gather(*(queue.enqueue(request()) for _ in range(20)))
    scheduled = await queue.collection.find_one({"_id": request().key})
    assert scheduled["state"] == "pending"
    assert scheduled["available_at"] == terminal["available_at"]
    assert await queue.collection.count_documents({}) == 1
    assert await queue.claim() is None
    clock[0] += timedelta(minutes=16)
    next_attempt = await queue.claim()
    assert next_attempt is not None
    assert next_attempt["attempts"] == 1


def test_unrecoverable_history_is_not_scheduled() -> None:
    with pytest.raises(ValueError, match="recoverable"):
        RecoveryRequest(
            seller_id="pilot",
            read_model="stock_time_metrics",
            date_from=datetime(2026, 8, 8, tzinfo=UTC),
            date_to=datetime(2026, 9, 7, tzinfo=UTC),
        )
