from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from zeler_gateway.cli.replay_events import (
    ALLOWED_TOPICS,
    PlanOptions,
    QueueSnapshot,
    ReplayConfigError,
    build_replay_plan,
    evaluate_rabbit_gates,
    parse_replay_args,
)


class FakeCursor:
    def __init__(self, documents: list[dict[str, Any]], recorder: dict[str, Any]) -> None:
        self.documents = documents
        self.recorder = recorder

    def sort(self, field: str, direction: int) -> FakeCursor:
        self.recorder["sort"] = (field, direction)
        self.documents = sorted(self.documents, key=lambda doc: doc[field])
        return self

    def limit(self, limit: int) -> FakeCursor:
        self.recorder["limit"] = limit
        self.documents = self.documents[:limit]
        return self

    def max_time_ms(self, max_time_ms: int) -> FakeCursor:
        self.recorder["max_time_ms"] = max_time_ms
        return self

    def __aiter__(self) -> FakeCursor:
        return self

    async def __anext__(self) -> dict[str, Any]:
        if not self.documents:
            raise StopAsyncIteration
        return self.documents.pop(0)


class FakeWebhookEvents:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.documents = documents
        self.find_calls: list[dict[str, Any]] = []
        self.count_calls: list[dict[str, Any]] = []
        self.update_calls: list[tuple[dict[str, Any], dict[str, Any]]] = []
        self.recorder: dict[str, Any] = {}

    def find(
        self, query: dict[str, Any], projection: dict[str, int] | None = None
    ) -> FakeCursor:
        self.find_calls.append({"query": query, "projection": projection})
        filtered = [
            document
            for document in self.documents
            if document.get("topic") == query.get("topic")
            and document.get("published_at") is query.get("published_at")
        ]
        return FakeCursor(filtered, self.recorder)

    async def count_documents(self, query: dict[str, Any]) -> int:
        self.count_calls.append(query)
        return sum(
            1
            for document in self.documents
            if document.get("topic") == query.get("topic")
            and document.get("published_at") is query.get("published_at")
        )

    async def update_one(
        self, filter_: dict[str, Any], update: dict[str, Any]
    ) -> object:
        self.update_calls.append((filter_, update))
        raise AssertionError("dry-run planning must not write to MongoDB")


class FakeDatabase:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.webhook_events = FakeWebhookEvents(documents)

    def __getitem__(self, collection_name: str) -> FakeWebhookEvents:
        assert collection_name == "webhook_events"
        return self.webhook_events


def _event(
    event_id: str,
    *,
    topic: str = "price_suggestion",
    resource: str = "/marketplace/benchmarks/items/MLM1/details",
    minutes: int = 0,
) -> dict[str, Any]:
    return {
        "_id": event_id,
        "topic": topic,
        "resource": resource,
        "user_id": 82453304,
        "received_at": datetime(2026, 4, 28, 12, minutes, tzinfo=UTC),
        "published_at": None,
        "raw_body": {"secret": "must-not-be-in-plan"},
        "source_ip": "127.0.0.1",
        "schema_version": 1,
    }


def _coalescing_baseline() -> list[dict[str, Any]]:
    base = datetime(2026, 4, 28, 12, 0, tzinfo=UTC)
    documents: list[dict[str, Any]] = []
    for index in range(21):
        documents.append(
            _event(
                f"price-{index}",
                topic="price_suggestion",
                resource=f"/marketplace/benchmarks/items/MLM{index}/details",
                minutes=index,
            )
        )
    for duplicate_index in range(14):
        documents.append(
            {
                **_event(
                    f"price-duplicate-{duplicate_index}",
                    topic="price_suggestion",
                    resource=f"/marketplace/benchmarks/items/MLM{duplicate_index}/details",
                ),
                "received_at": base - timedelta(minutes=duplicate_index + 1),
            }
        )
    for index in range(18):
        documents.append(
            _event(
                f"stock-{index}",
                topic="stock-locations",
                resource=f"/user-products/MLMU{index}/stock",
                minutes=index,
            )
        )
    for duplicate_index in range(35):
        documents.append(
            {
                **_event(
                    f"stock-duplicate-{duplicate_index}",
                    topic="stock-locations",
                    resource=f"/user-products/MLMU{duplicate_index % 18}/stock",
                ),
                "received_at": base - timedelta(minutes=duplicate_index + 1),
            }
        )
    documents.extend(
        _event(
            f"families-{index}",
            topic="user-products-families",
            resource=f"/sites/MLM/user-products-families/{index}",
            minutes=index,
        )
        for index in range(5)
    )
    return documents


def test_safety_cli_defaults_to_dry_run_and_validates_execute_run_id() -> None:
    dry_run = parse_replay_args([])

    assert dry_run.execute is False
    assert dry_run.run_id.startswith("dry-run-")
    assert dry_run.topics == tuple(ALLOWED_TOPICS)
    assert dry_run.rate_per_sec == 1.0
    assert dry_run.concurrency == 1
    assert dry_run.dedupe_policy == "latest-per-resource"

    with pytest.raises(ReplayConfigError, match="--run-id is required"):
        parse_replay_args(["--execute"])


def test_safety_cli_validates_allowlist_limits_rate_and_concurrency() -> None:
    options = parse_replay_args(
        [
            "--execute",
            "--run-id",
            "ops-20260428-price",
            "--topics",
            "price_suggestion,stock-locations",
            "--limit",
            "price_suggestion=3",
            "--limit",
            "stock-locations=2",
            "--rate-per-sec",
            "0.5",
            "--dedupe-policy",
            "none",
            "--rabbit-management-url",
            "http://rabbitmq.local/api/queues",
        ]
    )

    assert options.execute is True
    assert options.run_id == "ops-20260428-price"
    assert options.topics == ("price_suggestion", "stock-locations")
    assert options.limits == {"price_suggestion": 3, "stock-locations": 2}
    assert options.rate_per_sec == 0.5
    assert options.concurrency == 1
    assert options.dedupe_policy == "none"
    assert options.rabbit_management_url == "http://rabbitmq.local/api/queues"

    with pytest.raises(ReplayConfigError, match="unsupported topic"):
        parse_replay_args(["--topics", "items"])
    with pytest.raises(ReplayConfigError, match="rate-per-sec must be"):
        parse_replay_args(["--rate-per-sec", "2"])
    with pytest.raises(ReplayConfigError, match="concurrency must be 1"):
        parse_replay_args(["--concurrency", "2"])


def test_stock_locations_replay_gate_requires_only_active_fulldock_consumer() -> None:
    options = parse_replay_args(["--topics", "stock-locations"])

    decision = evaluate_rabbit_gates(
        [
            QueueSnapshot(
                name="zeler.fulldock.events",
                ready=0,
                unacked=0,
                consumers=1,
                dlq_ready=0,
                routing_keys=("stock_locations.updated",),
            )
        ],
        ("stock-locations",),
        options,
    )

    assert decision.allowed is True
    assert decision.reason == "ok"


@pytest.mark.asyncio
async def test_safety_dry_run_plan_reads_only_and_omits_raw_fields() -> None:
    database = FakeDatabase([_event("newer", minutes=2), _event("older", minutes=1)])

    plan = await build_replay_plan(
        database,
        PlanOptions(
            run_id="dry-run-test",
            topics=("price_suggestion",),
            limits={"price_suggestion": 10},
            expected_counts={"price_suggestion": 2},
        ),
    )

    assert database.webhook_events.find_calls == [
        {
            "query": {"published_at": None, "topic": "price_suggestion"},
            "projection": {
                "_id": 1,
                "topic": 1,
                "user_id": 1,
                "resource": 1,
                "received_at": 1,
                "published_at": 1,
                "schema_version": 1,
            },
        }
    ]
    assert database.webhook_events.recorder == {
        "sort": ("received_at", 1),
        "limit": 10,
        "max_time_ms": 5000,
    }
    assert database.webhook_events.update_calls == []
    assert plan.run_id == "dry-run-test"
    assert [event.id for event in plan.selected] == ["newer"]
    assert [event.id for event in plan.skipped] == ["older"]
    assert "raw_body" not in plan.to_sanitized_dict()["selected"][0]
    assert "source_ip" not in plan.to_sanitized_dict()["selected"][0]


@pytest.mark.asyncio
async def test_planner_stops_on_baseline_drift_and_corrupt_required_fields() -> None:
    drifted_database = FakeDatabase([_event("one")])

    with pytest.raises(ReplayConfigError, match="baseline drift"):
        await build_replay_plan(
            drifted_database,
            PlanOptions(
                run_id="dry-run-test",
                topics=("price_suggestion",),
                expected_counts={"price_suggestion": 2},
            ),
        )

    corrupt_database = FakeDatabase([{**_event("bad"), "resource": ""}])
    with pytest.raises(ReplayConfigError, match="corrupt webhook event"):
        await build_replay_plan(
            corrupt_database,
            PlanOptions(
                run_id="dry-run-test",
                topics=("price_suggestion",),
                expected_counts={"price_suggestion": 1},
            ),
        )


@pytest.mark.asyncio
async def test_coalescing_selects_live_targets_and_gates_user_products_families() -> None:
    database = FakeDatabase(_coalescing_baseline())

    plan = await build_replay_plan(
        database,
        PlanOptions(
            run_id="dry-run-baseline",
            topics=tuple(ALLOWED_TOPICS),
            expected_counts={
                "price_suggestion": 35,
                "stock-locations": 53,
                "user-products-families": 5,
            },
        ),
    )

    assert plan.topic_counts["price_suggestion"].selected == 21
    assert plan.topic_counts["price_suggestion"].skipped == 14
    assert plan.topic_counts["stock-locations"].selected == 18
    assert plan.topic_counts["stock-locations"].skipped == 35
    assert plan.topic_counts["user-products-families"].selected == 0
    assert plan.topic_counts["user-products-families"].skipped == 5
    skipped_family_reasons = {
        event.skip_reason for event in plan.skipped if event.topic == "user-products-families"
    }
    assert skipped_family_reasons == {"consumer_not_ready"}


@pytest.mark.asyncio
async def test_user_products_families_selects_when_consumer_is_explicitly_allowed() -> None:
    database = FakeDatabase(
        [
            _event(
                f"families-{index}",
                topic="user-products-families",
                resource=f"/sites/MLM/user-products-families/{index}",
                minutes=index,
            )
            for index in range(5)
        ]
    )

    plan = await build_replay_plan(
        database,
        PlanOptions(
            run_id="dry-run-families",
            topics=("user-products-families",),
            allow_user_products_families=True,
            expected_counts={"user-products-families": 5},
        ),
    )

    assert [event.id for event in plan.selected] == [
        "families-0",
        "families-1",
        "families-2",
        "families-3",
        "families-4",
    ]
    assert plan.skipped == ()
