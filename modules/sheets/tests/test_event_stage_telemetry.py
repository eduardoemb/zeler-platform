"""TDD: durable per-event stage telemetry for the ZelerData pilot.

The pilot plan requires four measurable stages per event:
1. received_at — event entered the handler and passed dedup
2. fetched_at — resource response received from the gateway
3. persisted_at — projection/source write completed
4. visible_at — a later read/refresh proves the formula-cell result

Stage records must survive a worker restart (durable in Mongo) and must not
create duplicates when the same event is re-delivered.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from zeler_sheets.consumer import SheetsEvent, SheetsEventHandler
from zeler_sheets.event_stage_telemetry import EventStageTelemetry


class FakeStageCollection:
    def __init__(self) -> None:
        self.docs: dict[str, dict[str, Any]] = {}

    async def find_one(
        self, query: dict[str, Any], projection: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        doc = self.docs.get(query["_id"])
        if doc is None:
            return None
        return dict(doc)

    async def update_one(
        self, query: dict[str, Any], update: dict[str, Any], *, upsert: bool = False
    ) -> object:
        doc = self.docs.setdefault(query["_id"], {"_id": query["_id"]})
        if "$set" in update:
            for key, value in update["$set"].items():
                doc[key] = value
        if "$min" in update:
            for key, value in update["$min"].items():
                existing = doc.get(key)
                if existing is None or value < existing:
                    doc[key] = value
        return type("R", (), {"matched_count": 1, "modified_count": 1})()


class FakeDevolucionesCollection:
    def __init__(self) -> None:
        self.docs: list[dict[str, Any]] = []

    async def find_one(self, *args: object, **kwargs: object) -> dict[str, Any] | None:
        return None

    async def insert_one(self, doc: dict[str, Any]) -> object:
        self.docs.append(doc)
        return type("R", (), {"inserted_id": len(self.docs)})()

    async def update_one(self, *args: object, **kwargs: object) -> object:
        return type("R", (), {"matched_count": 1, "modified_count": 1})()

    async def replace_one(self, *args: object, **kwargs: object) -> object:
        return type("R", (), {"matched_count": 1, "modified_count": 1})()


class FakeDb:
    def __init__(self) -> None:
        self.stages = FakeStageCollection()
        self.devops = FakeDevolucionesCollection()

    def __getitem__(self, name: str) -> FakeStageCollection | FakeDevolucionesCollection:
        if name == "sheets_event_stages":
            return self.stages
        if name == "sheets_devoluciones_operations":
            return self.devops
        if name == "sheets_read_model_freshness":
            return self.devops
        return self.devops  # any other collection: return a no-op stub


@pytest.mark.asyncio
async def test_records_all_four_stages() -> None:
    db = FakeDb()
    telemetry = EventStageTelemetry(db=db)
    event_key = "evt-001"
    now = datetime.now(UTC)

    await telemetry.record(event_key=event_key, stage="received", timestamp=now)
    await telemetry.record(event_key=event_key, stage="fetched", timestamp=now)
    await telemetry.record(event_key=event_key, stage="persisted", timestamp=now)
    await telemetry.record(event_key=event_key, stage="visible", timestamp=now)

    doc = await db["sheets_event_stages"].find_one({"_id": event_key})
    assert doc is not None
    assert doc["received_at"] is not None
    assert doc["fetched_at"] is not None
    assert doc["persisted_at"] is not None
    assert doc["visible_at"] is not None


@pytest.mark.asyncio
async def test_duplicate_delivery_keeps_earliest_received() -> None:
    db = FakeDb()
    telemetry = EventStageTelemetry(db=db)
    event_key = "evt-002"
    first = datetime(2026, 9, 14, 14, 0, 0, tzinfo=UTC)
    requeue = datetime(2026, 9, 14, 14, 5, 0, tzinfo=UTC)

    await telemetry.record(event_key=event_key, stage="received", timestamp=first)
    await telemetry.record(event_key=event_key, stage="received", timestamp=requeue)

    doc = await db["sheets_event_stages"].find_one({"_id": event_key})
    assert doc is not None
    assert doc["received_at"] == first  # earliest receipt wins


@pytest.mark.asyncio
async def test_stage_records_are_durable() -> None:
    """A second instance (new worker) sees the same data from the same db."""
    db = FakeDb()
    event_key = "evt-003"
    now = datetime.now(UTC)
    telemetry1 = EventStageTelemetry(db=db)
    await telemetry1.record(event_key=event_key, stage="received", timestamp=now)
    await telemetry1.record(event_key=event_key, stage="fetched", timestamp=now)

    telemetry2 = EventStageTelemetry(db=db)
    doc = await telemetry2.get_stage(event_key=event_key)
    assert doc is not None
    assert doc["received_at"] is not None
    assert doc["fetched_at"] is not None


@pytest.mark.asyncio
async def test_handler_creates_stage_document_without_export() -> None:
    """The no-export handler path creates a stage document."""
    from unittest.mock import AsyncMock

    from zeler_sheets.consumer import SheetsEventHandler

    db = FakeDb()
    gateway = AsyncMock()
    gateway.fetch_resource = AsyncMock(
        return_value={"id": "1", "seller_id": "1", "last_updated": "2026-09-14T14:00:00Z"}
    )
    persistence = AsyncMock()
    idempotency = AsyncMock()
    idempotency.is_duplicate = AsyncMock(return_value=False)

    class FakeEnrichment:
        async def append_row(self, **kwargs: object) -> None:
            return None

    handler = SheetsEventHandler(
        db=db,
        gateway_client=gateway,
        sheets_client=FakeEnrichment(),
        idempotency_store=idempotency,
        event_persistence=persistence,
        stage_telemetry=EventStageTelemetry(db=db),
    )
    event = type("E", (), {})()
    event.event_id = "evt-100"
    event.event_type = "questions.updated"
    event.seller_id = 1
    event.resource = "/orders/1"
    event.idempotency_key = "evt-100"

    # The handler must not crash; the telemetry must be called internally.
    await handler.handle(event)

    doc = await db["sheets_event_stages"].find_one({"_id": "evt-100"})
    assert doc is not None, "handler did not record stage telemetry"


@pytest_asyncio.fixture
async def stage_db(default_mongo_uri: str) -> AsyncIterator[AsyncIOMotorDatabase[dict[str, Any]]]:
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        default_mongo_uri, tz_aware=True, serverSelectionTimeoutMS=2000
    )
    database = client[f"zeler_event_stage_{uuid4().hex}"]
    await client.admin.command("ping")
    try:
        yield database
    finally:
        await client.drop_database(database.name)
        client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("export_enabled", [True, False])
async def test_handler_persists_resource_without_claiming_formula_visibility(
    stage_db: AsyncIOMotorDatabase[dict[str, Any]], export_enabled: bool
) -> None:
    if export_enabled:
        await stage_db.sheets_exports.insert_one(
            {"seller_id": "82453304", "enabled": True, "spreadsheet_id": "sheet-pilot"}
        )
    resource = {
        "id": "42",
        "seller_id": "82453304",
        "item_id": "MLM42",
        "from_user_id": "123",
        "text": "Is it available?",
        "status": "UNANSWERED",
        "date_created": "2026-09-15T10:00:00Z",
    }
    gateway = AsyncMock()
    gateway.fetch_resource.return_value = resource
    sheets = AsyncMock()
    idempotency = AsyncMock()
    idempotency.is_duplicate.return_value = False
    telemetry = EventStageTelemetry(db=stage_db)
    handler = SheetsEventHandler(
        db=stage_db,
        gateway_client=gateway,
        sheets_client=sheets,
        idempotency_store=idempotency,
        stage_telemetry=telemetry,
    )
    event = SheetsEvent(
        event_id="event-42",
        event_type="questions.updated",
        seller_id=82453304,
        resource="/questions/42",
        idempotency_key="question-42",
    )
    started_at = datetime.now(UTC)
    result = await handler.handle(event)
    finished_at = datetime.now(UTC)

    assert result == ("appended" if export_enabled else "no_export")
    question = await stage_db.questions.find_one({"_id": "42"})
    assert question is not None
    assert question["seller_id"] == "82453304"
    assert question["text"] == "Is it available?"
    gateway.fetch_resource.assert_awaited_once_with(seller_id=82453304, path="/questions/42")
    assert sheets.append_row.await_count == int(export_enabled)
    idempotency.mark_processed.assert_awaited_once_with("question-42")
    stages = await EventStageTelemetry(db=stage_db).get_stage(event_key="question-42")
    assert stages is not None
    assert set(stages) == {"_id", "received_at", "fetched_at", "persisted_at"}
    started_at = started_at.replace(microsecond=started_at.microsecond // 1000 * 1000)
    assert started_at <= stages["received_at"] <= stages["fetched_at"]
    assert stages["fetched_at"] <= stages["persisted_at"] <= finished_at

    idempotency.is_duplicate.return_value = True
    assert await handler.handle(event) == "duplicate"
    assert await telemetry.get_stage(event_key="question-42") == stages
    assert await stage_db.questions.count_documents({"_id": "42"}) == 1
    gateway.fetch_resource.assert_awaited_once()
    assert sheets.append_row.await_count == int(export_enabled)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected_stages", "persisted_count", "append_count"),
    [
        ("fetch", {"_id", "received_at"}, 0, 0),
        ("persist", {"_id", "received_at", "fetched_at"}, 0, 0),
        ("append", {"_id", "received_at", "fetched_at", "persisted_at"}, 1, 1),
    ],
)
async def test_handler_failure_records_only_completed_stages(
    stage_db: AsyncIOMotorDatabase[dict[str, Any]],
    failure: str,
    expected_stages: set[str],
    persisted_count: int,
    append_count: int,
) -> None:
    await stage_db.sheets_exports.insert_one(
        {"seller_id": "82453304", "enabled": True, "spreadsheet_id": "sheet-pilot"}
    )
    telemetry = EventStageTelemetry(db=stage_db)
    resource = {
        "id": "43",
        "seller_id": "different-seller" if failure == "persist" else "82453304",
        "item_id": "MLM43",
        "from_user_id": "123",
        "text": "Can you ship today?",
        "status": "UNANSWERED",
        "date_created": "2026-09-15T10:00:00Z",
    }

    async def fetch_resource(**kwargs: Any) -> dict[str, Any]:
        assert kwargs == {"seller_id": 82453304, "path": "/questions/43"}
        stages = await telemetry.get_stage(event_key="question-43")
        assert stages is not None
        assert set(stages) == {"_id", "received_at"}
        if failure == "fetch":
            raise RuntimeError("gateway unavailable")
        return resource

    async def append_row(**kwargs: Any) -> None:
        assert kwargs["spreadsheet_id"] == "sheet-pilot"
        stages = await telemetry.get_stage(event_key="question-43")
        assert stages is not None
        assert set(stages) == {"_id", "received_at", "fetched_at", "persisted_at"}
        question = await stage_db.questions.find_one({"_id": "43"})
        assert question is not None
        assert question["text"] == "Can you ship today?"
        raise RuntimeError("Sheets unavailable")

    gateway = AsyncMock()
    gateway.fetch_resource.side_effect = fetch_resource
    sheets = AsyncMock()
    sheets.append_row.side_effect = append_row
    idempotency = AsyncMock()
    idempotency.is_duplicate.return_value = False
    handler = SheetsEventHandler(
        db=stage_db,
        gateway_client=gateway,
        sheets_client=sheets,
        idempotency_store=idempotency,
        stage_telemetry=telemetry,
    )
    event = SheetsEvent(
        event_id="event-43",
        event_type="questions.updated",
        seller_id=82453304,
        resource="/questions/43",
        idempotency_key="question-43",
    )
    error = ValueError if failure == "persist" else RuntimeError
    message = {
        "fetch": "gateway unavailable",
        "persist": "question seller scope mismatch",
        "append": "Sheets unavailable",
    }[failure]
    with pytest.raises(error, match=message):
        await handler.handle(event)

    stages = await telemetry.get_stage(event_key="question-43")
    assert stages is not None
    assert set(stages) == expected_stages
    assert await stage_db.questions.count_documents({"_id": "43"}) == persisted_count
    assert sheets.append_row.await_count == append_count
    idempotency.mark_processed.assert_not_awaited()
