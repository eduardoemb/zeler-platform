from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from zeler_gateway.cli.replay_events import (
    CliOptions,
    PlannedEvent,
    PlanOptions,
    QueueSnapshot,
    ReplayAbortError,
    build_replay_plan,
    execute_replay_plan,
)


class UpdateResult:
    def __init__(self, *, matched_count: int = 1, modified_count: int = 1) -> None:
        self.matched_count = matched_count
        self.modified_count = modified_count


class FakeCursor:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.documents = documents

    def sort(self, _field: str, _direction: int) -> FakeCursor:
        self.documents = sorted(self.documents, key=lambda document: document["received_at"])
        return self

    def max_time_ms(self, _max_time_ms: int) -> FakeCursor:
        return self

    def __aiter__(self) -> FakeCursor:
        return self

    async def __anext__(self) -> dict[str, Any]:
        if not self.documents:
            raise StopAsyncIteration
        return self.documents.pop(0)


class FakeWebhookEvents:
    def __init__(self, documents: list[dict[str, Any]], update_result: UpdateResult) -> None:
        self.documents = documents
        self.update_result = update_result
        self.update_calls: list[tuple[dict[str, Any], dict[str, Any]]] = []

    def find(
        self, query: dict[str, Any], _projection: dict[str, int] | None = None
    ) -> FakeCursor:
        return FakeCursor(
            [
                document
                for document in self.documents
                if document["topic"] == query["topic"] and document["published_at"] is None
            ]
        )

    async def count_documents(self, _query: dict[str, Any]) -> int:
        return len(self.documents)

    async def update_one(self, filter_: dict[str, Any], update: dict[str, Any]) -> UpdateResult:
        self.update_calls.append((filter_, update))
        return self.update_result


class FakeDatabase:
    def __init__(
        self, documents: list[dict[str, Any]], update_result: UpdateResult | None = None
    ) -> None:
        self.webhook_events = FakeWebhookEvents(
            documents, update_result or UpdateResult()
        )

    def __getitem__(self, collection_name: str) -> FakeWebhookEvents:
        assert collection_name == "webhook_events"
        return self.webhook_events


class RecordingPublisher:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure
        self.calls: list[tuple[str, dict[str, Any], dict[str, str]]] = []

    async def publish(
        self, routing_key: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> None:
        self.calls.append((routing_key, payload, headers))
        if self.failure is not None:
            raise self.failure


class RecordingLedger:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def write(self, row: dict[str, Any]) -> None:
        self.rows.append(row)


def _options() -> CliOptions:
    return CliOptions(
        execute=True,
        run_id="ops-20260428-price",
        topics=("price_suggestion",),
        limits={},
        rate_per_sec=1,
        concurrency=1,
        dedupe_policy="latest-per-resource",
    )


def _healthy_gate_state() -> list[QueueSnapshot]:
    return [
        QueueSnapshot(
            name="zeler.repricer.items",
            ready=0,
            unacked=0,
            consumers=1,
            dlq_ready=0,
            routing_keys=("price_suggestion.updated",),
            healthy=True,
        ),
        QueueSnapshot(
            name="zeler.repricer.price_suggestion",
            ready=0,
            unacked=0,
            consumers=1,
            dlq_ready=0,
            routing_keys=("price_suggestion.updated",),
            healthy=True,
        ),
    ]


def _event(event_id: str = "event-1") -> dict[str, Any]:
    return {
        "_id": event_id,
        "topic": "price_suggestion",
        "resource": "/marketplace/benchmarks/items/MLM1/details",
        "user_id": 82453304,
        "received_at": datetime(2026, 4, 28, 12, 0, tzinfo=UTC),
        "published_at": None,
        "schema_version": 1,
        "raw_body": {"access_token": "must-not-leak"},
        "source_ip": "127.0.0.1",
    }


async def _plan(database: FakeDatabase) -> Any:
    return await build_replay_plan(
        database,
        PlanOptions(
            run_id="ops-20260428-price",
            topics=("price_suggestion",),
            expected_counts={"price_suggestion": len(database.webhook_events.documents)},
        ),
    )


@pytest.mark.asyncio
async def test_publish_confirm_precedes_published_at_mark_and_success_ledger() -> None:
    database = FakeDatabase([_event()])
    plan = await _plan(database)
    publisher = RecordingPublisher()
    ledger = RecordingLedger()

    await execute_replay_plan(
        database,
        plan,
        publisher=publisher,
        options=_options(),
        ledger=ledger,
        gate_provider=_healthy_gate_state,
    )

    assert [call[0] for call in publisher.calls] == ["price_suggestion.updated"]
    assert publisher.calls[0][2] == {
        "idempotency_key": "price_suggestion:/marketplace/benchmarks/items/MLM1/details:event-1",
        "exchange": "meli.events",
    }
    assert len(database.webhook_events.update_calls) == 1
    update_filter, update_doc = database.webhook_events.update_calls[0]
    assert update_filter == {"_id": "event-1", "published_at": None}
    assert update_doc["$set"]["classification"] == "price_suggestion.updated"
    assert update_doc["$set"]["replay_run_id"] == "ops-20260428-price"
    assert update_doc["$set"]["published_at"] <= datetime.now(UTC)
    assert ledger.rows[0]["status"] == "published"
    assert ledger.rows[0]["run_id"] == "ops-20260428-price"
    assert ledger.rows[0]["_id"] == "event-1"
    assert "raw_body" not in ledger.rows[0]
    assert "access_token" not in str(ledger.rows[0])


@pytest.mark.asyncio
async def test_publish_failure_is_sanitized_and_leaves_document_unmarked() -> None:
    database = FakeDatabase([_event()])
    plan = await _plan(database)
    publisher = RecordingPublisher(ConnectionError("connection reset with amqp://secret"))
    ledger = RecordingLedger()

    await execute_replay_plan(
        database,
        plan,
        publisher=publisher,
        options=_options(),
        ledger=ledger,
        gate_provider=_healthy_gate_state,
    )

    assert database.webhook_events.update_calls == []
    assert ledger.rows[0]["status"] == "failed"
    assert ledger.rows[0]["error_class"] == "ConnectionError"
    assert "secret" not in ledger.rows[0]["error"]
    assert len(publisher.calls) == 2
    assert ledger.rows[0]["attempt"] == 2


@pytest.mark.asyncio
async def test_schema_failure_is_quarantined_without_raw_body_or_marking() -> None:
    corrupt = PlannedEvent(
        id="bad-1",
        topic="price_suggestion",
        user_id=82453304,
        resource="/marketplace/benchmarks/items/MLM1/details",
        received_at=datetime(2026, 4, 28, 12, 0, tzinfo=UTC),
        routing_key="price_suggestion.updated",
        idempotency_key="price_suggestion:/marketplace/benchmarks/items/MLM1/details:bad-1",
        event={"_id": "bad-1", "topic": "price_suggestion", "raw_body": {"token": "hidden"}},
    )
    database = FakeDatabase([])
    plan = await _plan(database)
    plan = type(plan)(
        run_id=plan.run_id,
        selected=(corrupt,),
        skipped=plan.skipped,
        topic_counts=plan.topic_counts,
        created_at=plan.created_at,
    )
    ledger = RecordingLedger()

    await execute_replay_plan(
        database,
        plan,
        publisher=RecordingPublisher(),
        options=_options(),
        ledger=ledger,
        gate_provider=_healthy_gate_state,
    )

    assert database.webhook_events.update_calls == []
    assert ledger.rows[0]["status"] == "quarantined"
    assert ledger.rows[0]["error_class"] == "schema"
    assert "raw_body" not in ledger.rows[0]
    assert "hidden" not in str(ledger.rows[0])


@pytest.mark.asyncio
async def test_mark_ambiguity_records_ledger_and_stops() -> None:
    database = FakeDatabase(
        [_event()], update_result=UpdateResult(matched_count=0, modified_count=0)
    )
    plan = await _plan(database)
    ledger = RecordingLedger()

    with pytest.raises(ReplayAbortError, match="ambiguous Mongo mark"):
        await execute_replay_plan(
            database,
            plan,
            publisher=RecordingPublisher(),
            options=_options(),
            ledger=ledger,
            gate_provider=_healthy_gate_state,
        )

    assert ledger.rows[0]["status"] == "mark_ambiguous"
    assert ledger.rows[0]["_id"] == "event-1"
