from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from zeler_platform_core.models import RepricerRule
from zeler_repricer.consumer import GatewayPriceClient, RepricerEvent, RepricerEventHandler

NOW = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)


class FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self.docs = docs

    def sort(self, _sort_spec: list[tuple[str, int]]) -> FakeCursor:
        return self

    def skip(self, _count: int) -> FakeCursor:
        return self

    def limit(self, _count: int) -> FakeCursor:
        return self

    async def to_list(self, *, length: int) -> list[dict[str, Any]]:
        return self.docs[:length]


class FakeCollection:
    def __init__(self, docs: list[dict[str, Any]] | None = None) -> None:
        self.docs = docs or []

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                return doc
        return None

    def find(self, query: dict[str, Any]) -> FakeCursor:
        return FakeCursor(
            [doc for doc in self.docs if all(doc.get(key) == value for key, value in query.items())]
        )

    async def insert_one(self, doc: dict[str, Any]) -> None:
        self.docs.append(doc)


class FakeDb:
    def __init__(self) -> None:
        self.collections = {
            "items": FakeCollection([_item_doc()]),
            "repricer_rules": FakeCollection([_rule().model_dump(mode="python", by_alias=True)]),
            "repricer_history": FakeCollection(),
        }

    def __getitem__(self, name: str) -> FakeCollection:
        return self.collections[name]

    def get_default_database(self) -> FakeDb:
        return self


class FakeIdempotency:
    def __init__(self, duplicate: bool = False) -> None:
        self.duplicate = duplicate
        self.marked: list[str] = []

    async def is_duplicate(self, key: str) -> bool:
        return self.duplicate

    async def mark_processed(self, key: str) -> None:
        self.marked.append(key)


class FakeGatewayClient(GatewayPriceClient):
    def __init__(self, *, status_code: int = 200) -> None:
        self.calls: list[tuple[int, str, Decimal, str]] = []
        self.status_code = status_code

    async def update_price(
        self, *, seller_id: int, item_id: str, new_price: Decimal, idempotency_key: str
    ) -> tuple[int, int]:
        self.calls.append((seller_id, item_id, new_price, idempotency_key))
        return self.status_code, 17


@pytest.mark.asyncio
async def test_price_changed_event_triggers_rule_eval_and_gateway_update() -> None:
    db = FakeDb()
    gateway = FakeGatewayClient()
    idempotency = FakeIdempotency()
    handler = RepricerEventHandler(db=db, gateway_client=gateway, idempotency_store=idempotency)

    result = await handler.handle(
        RepricerEvent(
            event_id="event-1",
            event_type="items_prices.updated",
            seller_id=123456789,
            resource="/items/MLA123/prices",
            idempotency_key="idem-1",
            buybox_price=Decimal("180"),
        )
    )

    assert result == "set_price"
    assert gateway.calls == [(123456789, "MLA123", Decimal("180"), "idem-1")]
    assert idempotency.marked == ["idem-1"]


@pytest.mark.asyncio
async def test_idempotent_event_skipped() -> None:
    db = FakeDb()
    gateway = FakeGatewayClient()
    handler = RepricerEventHandler(
        db=db, gateway_client=gateway, idempotency_store=FakeIdempotency(duplicate=True)
    )

    result = await handler.handle(
        RepricerEvent(
            event_id="event-1",
            event_type="items_prices.updated",
            seller_id=123456789,
            resource="/items/MLA123/prices",
            idempotency_key="idem-1",
            buybox_price=Decimal("180"),
        )
    )

    assert result == "duplicate"
    assert gateway.calls == []
    assert db["repricer_history"].docs == []


@pytest.mark.asyncio
async def test_history_written_for_every_decision() -> None:
    db = FakeDb()
    db["repricer_rules"].docs = [
        _rule(min_price="100", max_price="200").model_dump(mode="python", by_alias=True)
    ]
    handler = RepricerEventHandler(
        db=db, gateway_client=FakeGatewayClient(), idempotency_store=FakeIdempotency()
    )

    result = await handler.handle(
        RepricerEvent(
            event_id="event-2",
            event_type="items_prices.updated",
            seller_id=123456789,
            resource="/items/MLA123/prices",
            idempotency_key="idem-2",
            buybox_price=Decimal("90"),
        )
    )

    assert result == "no_action"
    history_doc = db["repricer_history"].docs[0]
    assert history_doc["seller_id"] == "123456789"
    assert history_doc["item_id"] == "MLA123"
    assert history_doc["old_price"] == Decimal("150")
    assert history_doc["new_price"] == Decimal("150")
    assert history_doc["reason"] == "below_floor"
    assert history_doc["gateway_status"] is None


@pytest.mark.asyncio
async def test_gateway_429_requests_backoff_without_marking_processed() -> None:
    db = FakeDb()
    idempotency = FakeIdempotency()
    handler = RepricerEventHandler(
        db=db, gateway_client=FakeGatewayClient(status_code=429), idempotency_store=idempotency
    )

    with pytest.raises(RuntimeError, match="gateway_backpressure"):
        await handler.handle(
            RepricerEvent(
                event_id="event-3",
                event_type="items_prices.updated",
                seller_id=123456789,
                resource="/items/MLA123/prices",
                idempotency_key="idem-3",
                buybox_price=Decimal("180"),
            )
        )

    assert idempotency.marked == []


def _rule(*, min_price: str = "100", max_price: str = "200") -> RepricerRule:
    return RepricerRule(
        _id="rule-1",
        seller_id="123456789",
        item_id="MLA123",
        strategy="competitive",
        min_price=Decimal(min_price),
        max_price=Decimal(max_price),
        active=True,
        updated_at=NOW,
    )


def _item_doc() -> dict[str, Any]:
    return {
        "_id": "MLA123",
        "seller_id": "123456789",
        "title": "Test item",
        "price": Decimal("150"),
        "base_price": Decimal("150"),
        "available_quantity": 5,
        "status": "active",
        "category_id": "MLA1",
        "variations": [],
        "attributes": [],
        "shipping": None,
        "health": None,
        "last_meli_sync_at": NOW,
        "date_created": NOW,
        "last_updated": NOW,
        "schema_version": 1,
    }
