from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest


class FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs

    async def to_list(self, length: int) -> list[dict[str, Any]]:
        return self._docs[:length]


class FakeCollection:
    def __init__(self, docs: list[dict[str, Any]] | None = None) -> None:
        self.docs = docs or []

    def find(self, query: dict[str, Any]) -> FakeCursor:
        return FakeCursor(
            [doc for doc in self.docs if all(doc.get(key) == value for key, value in query.items())]
        )

    async def insert_one(self, doc: dict[str, Any]) -> None:
        self.docs.append(doc)


class FakeDb:
    def __init__(self, rules: list[dict[str, Any]]) -> None:
        self.fulldock_inventory_rules = FakeCollection(rules)
        self.fulldock_history = FakeCollection([])

    def __getitem__(self, name: str) -> FakeCollection:
        if name == "fulldock_inventory_rules":
            return self.fulldock_inventory_rules
        if name == "fulldock_history":
            return self.fulldock_history
        raise AssertionError(name)


class FakeGatewayClient:
    def __init__(self, resources: dict[str, dict[str, Any]]) -> None:
        self.resources = resources
        self.requests: list[tuple[str, str, str, dict[str, Any] | None]] = []

    async def request(
        self, method: str, path: str, *, seller_id: str, json: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self.requests.append((method, path, seller_id, json))
        if method == "GET":
            return self.resources[path]
        return {"status": "updated"}


class FakeIdempotencyStore:
    def __init__(self, duplicates: set[str] | None = None) -> None:
        self.duplicates = duplicates or set()
        self.processed: list[str] = []

    async def is_duplicate(self, key: str) -> bool:
        return key in self.duplicates

    async def mark_processed(self, key: str) -> None:
        self.processed.append(key)


@pytest.mark.asyncio
async def test_shipment_triggers_stock_update() -> None:
    from zeler_fulldock.consumer import FulldockEvent, FulldockEventHandler

    db = FakeDb(
        [
            {
                "_id": "rule-1",
                "seller_id": "123456789",
                "item_id": "MLA1",
                "enabled": True,
                "stock_locations": [
                    {"location_id": "AR-FULL-1", "quantity": 7},
                    {"location_id": "AR-FULL-2", "quantity": 3},
                ],
            }
        ]
    )
    gateway = FakeGatewayClient(
        {
            "/shipments/ship-1": {
                "id": "ship-1",
                "items": [{"id": "MLA1"}, {"item_id": "MLA2"}],
            }
        }
    )
    idempotency = FakeIdempotencyStore()
    handler = FulldockEventHandler(
        db=db,
        gateway_client=gateway,
        idempotency_store=idempotency,
        clock=lambda: datetime(2026, 4, 24, 14, 0, tzinfo=UTC),
    )

    outcome = await handler.handle(
        FulldockEvent(
            event_id="event-1",
            event_type="shipments.updated",
            seller_id=123456789,
            resource="/shipments/ship-1",
            idempotency_key="idem-1",
        )
    )

    assert outcome == "updated"
    assert gateway.requests == [
        ("GET", "/shipments/ship-1", "123456789", None),
        (
            "PUT",
            "/items/MLA1/stock_locations",
            "123456789",
            {
                "locations": [
                    {"location_id": "AR-FULL-1", "quantity": 7},
                    {"location_id": "AR-FULL-2", "quantity": 3},
                ]
            },
        ),
    ]
    assert db.fulldock_history.docs[0]["outcome"] == "updated"
    assert db.fulldock_history.docs[0]["item_id"] == "MLA1"
    assert idempotency.processed == ["idem-1"]


@pytest.mark.asyncio
async def test_no_rule_skips_update_and_records_history() -> None:
    from zeler_fulldock.consumer import FulldockEvent, FulldockEventHandler

    db = FakeDb([])
    gateway = FakeGatewayClient({"/items/MLA9": {"id": "MLA9"}})
    idempotency = FakeIdempotencyStore()
    handler = FulldockEventHandler(
        db=db,
        gateway_client=gateway,
        idempotency_store=idempotency,
        clock=lambda: datetime(2026, 4, 24, 14, 5, tzinfo=UTC),
    )

    outcome = await handler.handle(
        FulldockEvent(
            event_id="event-2",
            event_type="items.updated",
            seller_id=123456789,
            resource="/items/MLA9",
            idempotency_key="idem-2",
        )
    )

    assert outcome == "no_rule"
    assert gateway.requests == [("GET", "/items/MLA9", "123456789", None)]
    assert db.fulldock_history.docs[0]["outcome"] == "no_rule"
    assert idempotency.processed == ["idem-2"]


@pytest.mark.asyncio
async def test_duplicate_event_skipped_without_gateway_calls() -> None:
    from zeler_fulldock.consumer import FulldockEvent, FulldockEventHandler

    gateway = FakeGatewayClient({"/items/MLA1": {"id": "MLA1"}})
    handler = FulldockEventHandler(
        db=FakeDb([]),
        gateway_client=gateway,
        idempotency_store=FakeIdempotencyStore({"idem-duplicate"}),
    )

    outcome = await handler.handle(
        FulldockEvent(
            event_id="event-3",
            event_type="items.updated",
            seller_id=123456789,
            resource="/items/MLA1",
            idempotency_key="idem-duplicate",
        )
    )

    assert outcome == "duplicate"
    assert gateway.requests == []
