from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from zeler_gateway.cli.replay_events import (
    CliOptions,
    PlannedEvent,
    QueueSnapshot,
    ReplayAbortError,
    ReplayConfigError,
    ReplayPlan,
    evaluate_rabbit_gates,
    execute_replay_plan,
    load_rabbit_gate_state_from_export,
    parse_replay_args,
)


def _options(**overrides: object) -> CliOptions:
    values = {
        "execute": True,
        "run_id": "ops-20260428-price",
        "topics": ("price_suggestion",),
        "limits": {},
        "rate_per_sec": 1,
        "concurrency": 1,
        "dedupe_policy": "latest-per-resource",
        "max_queue_ready": 10,
        "max_dlq_delta": 0,
    }
    values.update(overrides)
    return CliOptions(**values)  # type: ignore[arg-type]


def _healthy_price_state() -> list[QueueSnapshot]:
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
            ready=42,
            unacked=0,
            consumers=0,
            dlq_ready=0,
            routing_keys=("price_suggestion.updated",),
            healthy=True,
        ),
    ]


def _healthy_family_state(*, consumers: int = 1) -> list[QueueSnapshot]:
    return [
        QueueSnapshot(
            name="zeler.sheets.events",
            ready=0,
            unacked=0,
            consumers=consumers,
            dlq_ready=0,
            routing_keys=("user_products.families_updated",),
            healthy=True,
        ),
        QueueSnapshot(
            name="zeler.sheets.user_products",
            ready=0,
            unacked=0,
            consumers=consumers,
            dlq_ready=0,
            routing_keys=("user_products.families_updated",),
            healthy=True,
        ),
    ]


class UpdateResult:
    matched_count = 1
    modified_count = 1


class FakeWebhookEvents:
    def __init__(self) -> None:
        self.update_calls: list[tuple[dict[str, Any], dict[str, Any]]] = []

    async def update_one(self, filter_: dict[str, Any], update: dict[str, Any]) -> UpdateResult:
        self.update_calls.append((filter_, update))
        return UpdateResult()


class FakeDatabase:
    def __init__(self) -> None:
        self.webhook_events = FakeWebhookEvents()

    def __getitem__(self, collection_name: str) -> FakeWebhookEvents:
        assert collection_name == "webhook_events"
        return self.webhook_events


class RecordingPublisher:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def publish(
        self, routing_key: str, _payload: dict[str, Any], _headers: dict[str, str]
    ) -> None:
        self.calls.append(routing_key)


class SequentialGateProvider:
    def __init__(self, states: list[list[QueueSnapshot]]) -> None:
        self.states = states
        self.calls = 0

    def __call__(self) -> list[QueueSnapshot]:
        state = self.states[min(self.calls, len(self.states) - 1)]
        self.calls += 1
        return state


def _planned_event(event_id: str, *, topic: str = "price_suggestion") -> PlannedEvent:
    routing_key = {
        "price_suggestion": "price_suggestion.updated",
        "user-products-families": "user_products.families_updated",
    }[topic]
    resource = f"/resource/{event_id}"
    event: dict[str, Any] = {
        "_id": event_id,
        "topic": topic,
        "resource": resource,
        "user_id": 82453304,
        "received_at": datetime(2026, 4, 28, 12, 0, tzinfo=UTC),
        "published_at": None,
        "schema_version": 1,
    }
    return PlannedEvent(
        id=event_id,
        topic=topic,
        user_id=82453304,
        resource=resource,
        received_at=event["received_at"],
        routing_key=routing_key,
        idempotency_key=f"{topic}:{resource}:{event_id}",
        event=event,
    )


def _plan(*events: PlannedEvent) -> ReplayPlan:
    return ReplayPlan(
        run_id="ops-20260428-gated",
        selected=events,
        skipped=(),
        topic_counts={},
        created_at=datetime(2026, 4, 28, 12, 0, tzinfo=UTC),
    )


def test_rabbit_gates_allow_healthy_required_queues() -> None:
    decision = evaluate_rabbit_gates(_healthy_price_state(), ("price_suggestion",), _options())

    assert decision.allowed is True
    assert decision.reason == "ok"


def test_execute_cli_requires_rabbit_gate_source_unless_url_or_export(tmp_path: Path) -> None:
    with pytest.raises(ReplayConfigError, match="Rabbit management gate source"):
        parse_replay_args(["--execute", "--run-id", "ops-20260428-price"])

    export_path = tmp_path / "rabbit-export.json"
    with_export = parse_replay_args(
        [
            "--execute",
            "--run-id",
            "ops-20260428-price",
            "--rabbit-management-export",
            str(export_path),
        ]
    )
    with_url = parse_replay_args(
        [
            "--execute",
            "--run-id",
            "ops-20260428-price",
            "--rabbit-management-url",
            "http://rabbitmq.local/api/queues",
        ]
    )

    assert with_export.rabbit_management_export == export_path
    assert with_url.rabbit_management_url == "http://rabbitmq.local/api/queues"


@pytest.mark.asyncio
async def test_user_products_families_execute_aborts_no_go_before_publish_or_mark() -> None:
    database = FakeDatabase()
    publisher = RecordingPublisher()
    options = _options(topics=("user-products-families",), allow_user_products_families=True)

    with pytest.raises(ReplayAbortError, match="topic_no_go"):
        await execute_replay_plan(
            database,
            _plan(_planned_event("families-1", topic="user-products-families")),
            publisher=publisher,
            options=options,
            gate_provider=lambda: _healthy_family_state(consumers=1),
        )

    assert publisher.calls == []
    assert database.webhook_events.update_calls == []


@pytest.mark.asyncio
async def test_execute_rechecks_rabbit_gate_before_each_message_and_aborts_on_flip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("zeler_gateway.cli.replay_events.asyncio.sleep", no_sleep)
    database = FakeDatabase()
    publisher = RecordingPublisher()
    unhealthy_after_first = _healthy_price_state()
    unhealthy_after_first[0] = QueueSnapshot(
        **{**unhealthy_after_first[0].__dict__, "dlq_ready": 1}
    )
    gate_provider = SequentialGateProvider([_healthy_price_state(), unhealthy_after_first])

    with pytest.raises(ReplayAbortError, match="dlq_delta_exceeded"):
        await execute_replay_plan(
            database,
            _plan(_planned_event("price-1"), _planned_event("price-2")),
            publisher=publisher,
            options=_options(),
            gate_provider=gate_provider,
        )

    assert gate_provider.calls == 2
    assert publisher.calls == ["price_suggestion.updated"]
    assert len(database.webhook_events.update_calls) == 1


def test_rabbit_gates_stop_on_queue_cap_dlq_and_missing_consumer() -> None:
    queue_cap = _healthy_price_state()
    queue_cap[0] = QueueSnapshot(**{**queue_cap[0].__dict__, "ready": 11})
    assert evaluate_rabbit_gates(queue_cap, ("price_suggestion",), _options()).reason == (
        "queue_cap_exceeded"
    )

    dlq_growth = _healthy_price_state()
    dlq_growth[0] = QueueSnapshot(**{**dlq_growth[0].__dict__, "dlq_ready": 1})
    assert evaluate_rabbit_gates(dlq_growth, ("price_suggestion",), _options()).reason == (
        "dlq_delta_exceeded"
    )

    missing_consumer = _healthy_price_state()
    missing_consumer[0] = QueueSnapshot(**{**missing_consumer[0].__dict__, "consumers": 0})
    assert (
        evaluate_rabbit_gates(missing_consumer, ("price_suggestion",), _options()).reason
        == "missing_consumer"
    )


def test_rabbit_gates_stop_on_wrong_routing_health_log_failure_and_abort_file(
    tmp_path: Path,
) -> None:
    wildcard_routing = _healthy_price_state()
    wildcard_routing[0] = QueueSnapshot(
        **{**wildcard_routing[0].__dict__, "routing_keys": ("price_suggestion.*",)}
    )
    assert evaluate_rabbit_gates(wildcard_routing, ("price_suggestion",), _options()).reason == "ok"

    wrong_routing = _healthy_price_state()
    wrong_routing[0] = QueueSnapshot(
        **{**wrong_routing[0].__dict__, "routing_keys": ("items.updated",)}
    )
    assert evaluate_rabbit_gates(wrong_routing, ("price_suggestion",), _options()).reason == (
        "wrong_routing"
    )

    unhealthy = _healthy_price_state()
    unhealthy[0] = QueueSnapshot(**{**unhealthy[0].__dict__, "healthy": False})
    assert evaluate_rabbit_gates(unhealthy, ("price_suggestion",), _options()).reason == (
        "consumer_health_failed"
    )

    log_failure = _healthy_price_state()
    log_failure[0] = QueueSnapshot(
        **{**log_failure[0].__dict__, "recent_errors": ("worker.message.dlq",)}
    )
    assert evaluate_rabbit_gates(log_failure, ("price_suggestion",), _options()).reason == (
        "consumer_health_failed"
    )

    abort_file = tmp_path / "abort-replay"
    abort_file.write_text("stop", encoding="utf-8")
    assert (
        evaluate_rabbit_gates(
            _healthy_price_state(), ("price_suggestion",), _options(abort_file=abort_file)
        ).reason
        == "operator_abort"
    )


def test_rabbit_gate_state_loads_sanitized_management_export(tmp_path: Path) -> None:
    export_path = tmp_path / "rabbit-export.json"
    export_path.write_text(
        json.dumps(
            {
                "queues": [
                    {
                        "name": "zeler.repricer.items",
                        "messages_ready": 3,
                        "messages_unacknowledged": 1,
                        "consumers": 2,
                        "dlq_ready": 0,
                        "routing_keys": ["price_suggestion.updated"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    state = load_rabbit_gate_state_from_export(export_path)

    assert state == [
        QueueSnapshot(
            name="zeler.repricer.items",
            ready=3,
            unacked=1,
            consumers=2,
            dlq_ready=0,
            routing_keys=("price_suggestion.updated",),
            healthy=True,
        )
    ]
