"""Old-order convergence: legacy unit checks plus guarded consumer/Mongo/dispatcher evidence.

The integration case acquires real coverage through the recovery worker before
delivering newer, duplicate and stale events. It proves dispatcher-visible values,
not actual Sheets-cell visibility. Legacy unit cases retain their explicit guard
substitute; that fixture never applies to the integration case.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from zeler_platform_core.events.idempotency import IdempotencyStore, ProcessedEventsCollection
from zeler_sheets.consumer import SheetsEvent, SheetsEventHandler, _SheetsIdempotencyAdapter
from zeler_sheets.event_persistence import SheetsEventPersistence
from zeler_sheets.formulas.dispatcher import FormulaDispatcher, FormulaExecutionContext
from zeler_sheets.formulas.handlers_orders_questions import build_order_question_formula_handlers
from zeler_sheets.formulas.read_models import FormulaReadModelRepository
from zeler_sheets.formulas.recovery import FormulaRecoveryQueue, RecoveryRequest
from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker
from zeler_sheets.formulas.registry import FormulaRegistry

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
OLD_ORDER_DATE = NOW - timedelta(days=120)


def _order_resource(
    *,
    order_id: int,
    status: str,
    date_created: str,
    last_updated: str,
    total_amount: str = "100.00",
) -> dict[str, Any]:
    return {
        "id": order_id,
        "status": status,
        "date_created": date_created,
        "last_updated": last_updated,
        "total_amount": total_amount,
        "buyer": {"id": 123},
        "shipping": {"id": 555},
        "order_items": [
            {
                "item": {"id": "MLA1", "seller_sku": "sku-1", "title": "Old product"},
                "quantity": 2,
                "unit_price": total_amount,
            },
        ],
    }


@pytest.fixture
def _fenced_order(monkeypatch: pytest.MonkeyPatch) -> None:
    import inspect
    from uuid import uuid4

    import zeler_sheets.event_persistence as event_persistence_module
    from zeler_platform_core.devoluciones_readiness import DevolucionesOperationContext
    from zeler_sheets.event_persistence import SheetsEventPersistence

    original_persist = SheetsEventPersistence.persist

    async def persist_with_operation(self: SheetsEventPersistence, **kwargs: Any) -> None:
        if str(kwargs.get("event_type", "")).startswith("orders."):
            kwargs.setdefault(
                "operation",
                DevolucionesOperationContext(
                    seller_id=str(kwargs["seller_id"]),
                    scope="devoluciones",
                    operation_id="unit-test-operation",
                    attempt_token=uuid4().hex,
                    fence=1,
                    owns_lease=True,
                ),
            )
        await original_persist(self, **kwargs)

    async def guarded_write(**kwargs: Any) -> None:
        result = kwargs["writer"](None)
        if inspect.isawaitable(result):
            await result

    monkeypatch.setattr(SheetsEventPersistence, "persist", persist_with_operation)
    monkeypatch.setattr(event_persistence_module, "guarded_devoluciones_write", guarded_write)


@pytest.fixture
def moments() -> Callable[[], datetime]:

    counter = [0]

    def next_moment() -> datetime:
        counter[0] += 1
        return NOW + timedelta(seconds=counter[0])

    return next_moment


class FakeDb:
    def __init__(self) -> None:
        self.docs: dict[str, dict[str, Any]] = {}

    def __getitem__(self, name: str) -> Any:
        return _FakeCollection(name, self.docs)


class _FakeCollection:
    def __init__(self, name: str, docs: dict[str, dict[str, Any]]) -> None:
        self._name = name
        self._docs = docs

    async def find_one(self, query: dict[str, Any], **kwargs: Any) -> Any:
        key = f"{self._name}:{query.get('_id')}:{query.get('seller_id')}"
        return self._docs.get(key)

    async def update_one(self, query: dict[str, Any], update: dict[str, Any], **kwargs: Any) -> Any:
        key = f"{self._name}:{query.get('_id')}:{query.get('seller_id')}"
        doc = self._docs.setdefault(key, dict(query))
        if "$set" in update:
            doc.update(update["$set"])
        if "$setOnInsert" in update:
            for field, value in update["$setOnInsert"].items():
                doc.setdefault(field, value)
        return type("R", (), {"upserted_id": key if "upserted_id" in kwargs else None})()

    async def replace_one(
        self, query: dict[str, Any], replacement: dict[str, Any], **kwargs: Any
    ) -> Any:
        key = f"{self._name}:{query.get('_id')}:{query.get('seller_id')}"
        self._docs[key] = dict(replacement)
        return type("R", (), {"matched_count": 1})()

    async def count_documents(self, query: dict[str, Any], **kwargs: Any) -> int:
        return sum(1 for key in self._docs if key.startswith(f"{self._name}:"))

    async def distinct(self, field: str, query: dict[str, Any], **kwargs: Any) -> list[Any]:
        return []

    def find(self, query: dict[str, Any], projection: dict[str, Any] | None = None) -> Any:
        return self

    async def to_list(self, *, length: int | None = None) -> list[Any]:
        return [v for k, v in self._docs.items() if k.startswith(f"{self._name}:")]


@pytest.mark.asyncio
@pytest.mark.usefixtures("_fenced_order")
async def test_old_order_modification_updates_projection(moments: Callable[[], datetime]) -> None:
    """An event for an order created 120 days ago, with a newer last_updated,
    must overwrite the stored projection (monotonic guard passes)."""
    db = FakeDb()
    persistence = SheetsEventPersistence(db=db, clock=moments)

    # First: the original order (created 120 days ago).
    original = _order_resource(
        order_id=2001,
        status="paid",
        date_created=OLD_ORDER_DATE.isoformat(),
        last_updated=(OLD_ORDER_DATE + timedelta(days=1)).isoformat(),
        total_amount="100.00",
    )
    await persistence.persist(event_type="orders.updated", seller_id=82453304, resource=original)

    # Now: a modification arrives with a newer last_updated.
    modified = _order_resource(
        order_id=2001,
        status="cancelled",
        date_created=OLD_ORDER_DATE.isoformat(),
        last_updated=NOW.isoformat(),
        total_amount="100.00",
    )
    await persistence.persist(event_type="orders.updated", seller_id=82453304, resource=modified)

    # The stored order must reflect the modification, not the original.
    stored = await db["orders"].find_one({"_id": 2001, "seller_id": 82453304})
    assert stored is not None
    assert stored["status"] == "cancelled"


@pytest_asyncio.fixture
async def event_formula_db(
    default_mongo_uri: str,
) -> AsyncIterator[AsyncIOMotorDatabase[dict[str, Any]]]:
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        default_mongo_uri, tz_aware=True, serverSelectionTimeoutMS=2000
    )
    database = client[f"zeler_old_event_formula_{uuid4().hex}"]
    hello = await client.admin.command("hello")
    assert hello["isWritablePrimary"] is True
    assert hello["setName"] == "rs0"
    try:
        yield database
    finally:
        await client.drop_database(database.name)
        client.close()


@pytest.mark.asyncio
async def test_old_order_event_converges_through_guarded_consumer_and_formula(
    event_formula_db: AsyncIOMotorDatabase[dict[str, Any]],
) -> None:
    database = event_formula_db
    observed = datetime.now(UTC).replace(microsecond=0)
    start = (observed - timedelta(days=40)).replace(hour=0, minute=0, second=0)
    end = start + timedelta(days=1)
    resources = {
        seller: {
            **_order_resource(
                order_id=identity,
                status="paid",
                date_created=(start + timedelta(hours=12)).isoformat(),
                last_updated=(start + timedelta(hours=13)).isoformat(),
                total_amount=amount,
            ),
            "seller": {"id": seller},
        }
        for seller, identity, amount in [("82453304", 2001, "100"), ("98765432", 2002, "900")]
    }

    class Gateway:
        def __init__(self) -> None:
            self.event_fetches: list[tuple[str, str]] = []

        async def fetch_resource(self, *, seller_id: str | int, path: str) -> dict[str, Any]:
            resource = resources[str(seller_id)]
            if path.startswith("/orders/search?"):
                return {"paging": {"total": 1}, "results": [resource]}
            assert path == f"/orders/{resource['id']}"
            self.event_fetches.append((str(seller_id), path))
            return resource

        async def request(self, *, method: str, seller_id: str, path: str) -> httpx.Response:
            assert method == "GET"
            resource = resources[seller_id]
            assert path == f"/orders/{resource['id']}"
            return httpx.Response(200, json=resource)

    class NoExportSheets:
        async def append_row(self, **kwargs: Any) -> None:
            raise AssertionError("no export is configured")

    gateway = Gateway()
    queue = FormulaRecoveryQueue(database, allowed_sellers=frozenset(resources))
    await queue.ensure_indexes()
    worker = FormulaRecoveryWorker(db=database, gateway=gateway, queue=queue)
    for seller in resources:
        request = RecoveryRequest(
            seller_id=seller, read_model="orders", date_from=start, date_to=end
        )
        await queue.enqueue(request)
        assert await worker.process_one() is True
        job = await queue.collection.find_one({"_id": request.key})
        assert job is not None
        assert job["state"] == "completed", job.get("failure_reason")

    dispatcher = FormulaDispatcher(
        build_order_question_formula_handlers(FormulaReadModelRepository(db=database))
    )

    async def sales(seller: str, status: str) -> list[list[Any]]:
        result = await dispatcher.execute(
            FormulaExecutionContext(
                contract=FormulaRegistry.default().find_required("ZELERDATA_VENTASTOTALES"),
                cuenta=seller,
                seller_id=seller,
                seller_nickname=seller,
                token_id=uuid4().hex,
                request_id=None,
                args={
                    "fecha_inicial": start.date().isoformat(),
                    "fecha_final": start.date().isoformat(),
                    "estado": status,
                },
            )
        )
        assert result.recovery is None
        return result.values

    assert await sales("82453304", "paid") == [[100]]
    assert await sales("98765432", "paid") == [[900]]
    handler = SheetsEventHandler(
        db=database,
        gateway_client=gateway,
        sheets_client=NoExportSheets(),
        idempotency_store=_SheetsIdempotencyAdapter(
            IdempotencyStore(cast(ProcessedEventsCollection, database.processed_events))
        ),
    )
    newer = SheetsEvent(
        event_id="newer",
        event_type="orders.updated",
        seller_id=82453304,
        resource="/orders/2001",
        idempotency_key="newer",
    )
    resources["82453304"] = {
        **resources["82453304"],
        "status": "cancelled",
        "last_updated": observed.isoformat(),
    }
    assert await handler.handle(newer) == "no_export"
    assert await sales("82453304", "paid") == [[0]]
    assert await sales("82453304", "cancelled") == [[100]]
    assert await handler.handle(newer) == "duplicate"
    assert gateway.event_fetches == [("82453304", "/orders/2001")]
    resources["82453304"] = {
        **resources["82453304"],
        "status": "paid",
        "last_updated": (observed - timedelta(days=10)).isoformat(),
    }
    stale = SheetsEvent(
        event_id="stale",
        event_type="orders.updated",
        seller_id=82453304,
        resource="/orders/2001",
        idempotency_key="stale",
    )
    assert await handler.handle(stale) == "no_export"
    assert gateway.event_fetches == [("82453304", "/orders/2001")] * 2
    assert await sales("82453304", "paid") == [[0]]
    assert await sales("82453304", "cancelled") == [[100]]
    assert await sales("98765432", "paid") == [[900]]
    assert await database.orders.count_documents({}) == 2
    assert await database.processed_events.count_documents({"module_id": "sheets"}) == 2
    operations = await database.sheets_devoluciones_operations.find({}).to_list(length=None)
    assert len(operations) == 2
    assert all(operation["state"] == "succeeded" for operation in operations)
    assert {operation["seller_id"]: operation["fence"] for operation in operations} == {
        "82453304": 3,
        "98765432": 1,
    }


@pytest.mark.asyncio
@pytest.mark.usefixtures("_fenced_order")
async def test_old_order_stale_event_does_not_regress_projection(
    moments: Callable[[], datetime],
) -> None:
    """A stale event (older last_updated) for the same old order must be
    rejected by the monotonic guard, preserving the newer projection."""
    db = FakeDb()
    persistence = SheetsEventPersistence(db=db, clock=moments)

    # Newer version arrives first.
    newer = _order_resource(
        order_id=2002,
        status="cancelled",
        date_created=OLD_ORDER_DATE.isoformat(),
        last_updated=NOW.isoformat(),
    )
    await persistence.persist(event_type="orders.updated", seller_id=82453304, resource=newer)

    # Then a stale version (same order, older last_updated). The real
    # monotonic guard in event_persistence rejects this; our fake replace
    # does not implement the filter, so we assert the guard function
    # directly on the canonical documents.
    stale = _order_resource(
        order_id=2002,
        status="paid",
        date_created=OLD_ORDER_DATE.isoformat(),
        last_updated=(NOW - timedelta(days=10)).isoformat(),
    )
    from zeler_sheets.event_persistence import _canonical_order_document

    stale_doc = _canonical_order_document(stale, seller_id="82453304", sale_fee_synced_at=NOW)
    # The stored "newer" doc has last_updated=NOW; the stale doc has
    # last_updated=NOW-10d. The guard must reject the stale one.
    from zeler_sheets.event_persistence import _resource_freshness_allows_write

    stored_doc = await db["orders"].find_one({"_id": 2002, "seller_id": 82453304})
    allows = _resource_freshness_allows_write(
        stored_doc,
        stale_doc,
        freshness_fields=("last_updated", "date_closed", "date_created"),
    )
    assert allows is False  # stale event is rejected by the guard
    # The stored projection still shows the newer state.
    stored = await db["orders"].find_one({"_id": 2002, "seller_id": 82453304})
    assert stored["status"] == "cancelled"
