from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

import zeler_gateway.app as app_module

NOW = datetime(2026, 5, 13, 19, 0, tzinfo=UTC)


class FakeCursor:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self._documents = documents

    def sort(self, _sort_spec: list[tuple[str, int]]) -> FakeCursor:
        return self

    async def to_list(self, length: int) -> list[dict[str, Any]]:
        return self._documents[:length]


class FakeCollection:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.documents = documents
        self.filters: list[dict[str, Any]] = []

    def find(self, filter_spec: dict[str, Any]) -> FakeCursor:
        self.filters.append(filter_spec)
        return FakeCursor(
            [
                document
                for document in self.documents
                if all(document.get(key) == value for key, value in filter_spec.items())
            ]
        )


class FakeDb:
    def __init__(self, catalog_rules: list[dict[str, Any]]) -> None:
        self.repricer_catalog_rules = FakeCollection(catalog_rules)

    def __getitem__(self, name: str) -> FakeCollection:
        if name == "repricer_catalog_rules":
            return self.repricer_catalog_rules
        raise AssertionError(name)


class FakePublisher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], dict[str, str]]] = []

    async def publish(
        self, routing_key: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> None:
        self.calls.append((routing_key, payload, headers))


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[dict[str, Any]] = []

    def add_job(self, func: Any, trigger: str, **kwargs: Any) -> None:
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})


@pytest.mark.asyncio
async def test_sweep_publisher_emits_seller_account_jobs_from_catalog_rules() -> None:
    db = FakeDb(
        [
            _catalog_rule("catalog-1", seller_id="123456789", account_id="acc-1", active=True),
            _catalog_rule("catalog-2", seller_id="123456789", account_id="acc-1", active=True),
            _catalog_rule("catalog-3", seller_id="123456789", account_id="acc-2", active=True),
            _catalog_rule("catalog-4", seller_id="987654321", account_id="acc-1", active=False),
        ]
    )
    publisher = FakePublisher()

    result = await app_module.publish_repricer_sweep_requests(
        db=db,
        publisher=publisher,
        clock=lambda: NOW,
    )

    assert result == {"published": 2, "seller_accounts": ["123456789:acc-1", "123456789:acc-2"]}
    assert db.repricer_catalog_rules.filters == [{"active": True}]
    assert [call[0] for call in publisher.calls] == [
        "repricer.sweep.requested",
        "repricer.sweep.requested",
    ]
    assert publisher.calls[0][1] == {
        "event_id": "repricer-sweep-123456789-acc-1-20260513T190000Z",
        "event_type": "repricer.sweep.requested",
        "occurred_at": "2026-05-13T19:00:00Z",
        "seller_id": "123456789",
        "account_id": "acc-1",
        "schema_version": 1,
    }
    assert publisher.calls[0][2] == {
        "idempotency_key": "repricer-sweep:123456789:acc-1:20260513T190000Z",
        "exchange": "meli.events",
    }


def test_repricer_sweep_scheduler_registers_interval_job_without_running_live_calls() -> None:
    scheduler = FakeScheduler()
    db = FakeDb([])
    publisher = FakePublisher()

    app_module.configure_repricer_sweep_scheduler(
        scheduler=scheduler,
        db=db,
        publisher=publisher,
        interval_minutes=7,
        clock=lambda: NOW,
    )

    assert len(scheduler.jobs) == 1
    assert scheduler.jobs[0]["trigger"] == "interval"
    assert scheduler.jobs[0]["minutes"] == 7
    assert scheduler.jobs[0]["id"] == "repricer-sweep-publisher"
    assert scheduler.jobs[0]["replace_existing"] is True
    assert scheduler.jobs[0]["max_instances"] == 1
    assert scheduler.jobs[0]["coalesce"] is True


def _catalog_rule(rule_id: str, *, seller_id: str, account_id: str, active: bool) -> dict[str, Any]:
    return {
        "_id": rule_id,
        "seller_id": seller_id,
        "account_id": account_id,
        "item_id": "MLA123",
        "active": active,
    }
