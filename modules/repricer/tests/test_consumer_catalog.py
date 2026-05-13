from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from zeler_repricer.consumer import GatewayPriceClient, RepricerEvent, RepricerEventHandler

NOW = datetime(2026, 5, 13, 20, 15, tzinfo=UTC)


class FakeCollection:
    def __init__(self, docs: list[dict[str, Any]] | None = None) -> None:
        self.docs = docs or []
        self.updates: list[tuple[dict[str, Any], dict[str, Any]]] = []

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                return doc
        return None

    async def insert_one(self, doc: dict[str, Any]) -> None:
        self.docs.append(doc)

    async def update_one(self, query: dict[str, Any], update: dict[str, Any]) -> object:
        self.updates.append((query, update))
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                for key, value in update["$set"].items():
                    _assign_dotted(doc, key, value)
                return object()
        return object()


class FakeDb:
    def __init__(
        self,
        catalog_rules: list[dict[str, Any]],
        *,
        limits: list[dict[str, Any]] | None = None,
        allies: list[dict[str, Any]] | None = None,
    ) -> None:
        self.collections = {
            "items": FakeCollection([_item_doc()]),
            "repricer_catalog_rules": FakeCollection(catalog_rules),
            "repricer_limits": FakeCollection(limits or []),
            "repricer_allies": FakeCollection(allies or []),
            "repricer_history": FakeCollection(),
        }

    def __getitem__(self, name: str) -> FakeCollection:
        return self.collections[name]


class FakeIdempotency:
    def __init__(self) -> None:
        self.marked: list[str] = []

    async def is_duplicate(self, _key: str) -> bool:
        return False

    async def mark_processed(self, key: str) -> None:
        self.marked.append(key)


class FakeGatewayClient(GatewayPriceClient):
    def __init__(self) -> None:
        self.calls: list[tuple[int, str, Decimal, str]] = []

    async def update_price(
        self, *, seller_id: int, item_id: str, new_price: Decimal, idempotency_key: str
    ) -> tuple[int, int]:
        self.calls.append((seller_id, item_id, new_price, idempotency_key))
        return 202, 11


@pytest.mark.asyncio
async def test_catalog_rule_live_apply_updates_price_history_and_bounded_execution_state() -> None:
    db = FakeDb([_catalog_rule_doc(rule_id="catalog-1", seller_id="123456789")])
    gateway = FakeGatewayClient()
    idempotency = FakeIdempotency()
    handler = RepricerEventHandler(
        db=db,
        gateway_client=gateway,
        idempotency_store=idempotency,
        clock=lambda: NOW,
    )

    result = await handler.handle(_event(seller_id=123456789, buybox_price=Decimal("118")))

    assert result == "set_price"
    assert gateway.calls == [(123456789, "MLA123", Decimal("118"), "idem-1")]
    assert idempotency.marked == ["idem-1"]
    assert db["repricer_history"].docs == [
        {
            "seller_id": "123456789",
            "account_id": "acc-1",
            "rule_id": "catalog-1",
            "item_id": "MLA123",
            "old_price": Decimal("150"),
            "new_price": Decimal("118"),
            "reason": "track_buybox",
            "applied_at": NOW,
            "gateway_status": 202,
            "gateway_latency_ms": 11,
            "event_id": "event-1",
            "schema_version": 1,
        }
    ]
    assert db["repricer_catalog_rules"].updates == [
        (
            {"_id": "catalog-1", "seller_id": "123456789"},
            {
                "$set": {
                    "execution_state.last_outcome": "applied",
                    "execution_state.last_event_at": NOW,
                    "execution_state.last_applied_price": Decimal("118"),
                    "execution_state.last_competitor": None,
                    "updated_at": NOW,
                }
            },
        )
    ]


@pytest.mark.asyncio
async def test_catalog_rule_no_action_writes_history_and_does_not_call_gateway() -> None:
    db = FakeDb([_catalog_rule_doc(rule_id="catalog-1", seller_id="123456789")])
    gateway = FakeGatewayClient()
    handler = RepricerEventHandler(
        db=db,
        gateway_client=gateway,
        idempotency_store=FakeIdempotency(),
        clock=lambda: NOW,
    )

    result = await handler.handle(_event(seller_id=123456789, buybox_price=Decimal("90")))

    assert result == "no_action"
    assert gateway.calls == []
    history_doc = db["repricer_history"].docs[0]
    assert history_doc["seller_id"] == "123456789"
    assert history_doc["account_id"] == "acc-1"
    assert history_doc["rule_id"] == "catalog-1"
    assert history_doc["old_price"] == Decimal("150")
    assert history_doc["new_price"] == Decimal("150")
    assert history_doc["reason"] == "below_floor"
    assert history_doc["gateway_status"] is None
    assert db["repricer_catalog_rules"].updates[0][1]["$set"] == {
        "execution_state.last_outcome": "guard_blocked",
        "execution_state.last_event_at": NOW,
        "execution_state.last_applied_price": None,
        "execution_state.last_competitor": None,
        "updated_at": NOW,
    }


@pytest.mark.asyncio
async def test_catalog_rule_lookup_is_seller_scoped_before_live_price_apply() -> None:
    db = FakeDb([_catalog_rule_doc(rule_id="catalog-other", seller_id="987654321")])
    gateway = FakeGatewayClient()
    handler = RepricerEventHandler(
        db=db,
        gateway_client=gateway,
        idempotency_store=FakeIdempotency(),
        clock=lambda: NOW,
    )

    result = await handler.handle(_event(seller_id=123456789, buybox_price=Decimal("118")))

    assert result == "rule_missing"
    assert gateway.calls == []
    assert db["repricer_history"].docs == []
    assert db["repricer_catalog_rules"].updates == []


@pytest.mark.asyncio
async def test_catalog_rule_loads_limits_before_price_decision() -> None:
    db = FakeDb(
        [_catalog_rule_doc(rule_id="catalog-1", seller_id="123456789")],
        limits=[_limits_doc(seller_id="123456789", account_id="acc-1", undercut_delta="2")],
    )
    gateway = FakeGatewayClient()
    handler = RepricerEventHandler(
        db=db,
        gateway_client=gateway,
        idempotency_store=FakeIdempotency(),
        clock=lambda: NOW,
    )

    result = await handler.handle(
        _event(
            seller_id=123456789,
            buybox_price=Decimal("118"),
            competitor_account_id="competitor-1",
        )
    )

    assert result == "set_price"
    assert gateway.calls == [(123456789, "MLA123", Decimal("116"), "idem-1")]
    assert db["repricer_history"].docs[0]["new_price"] == Decimal("116")


@pytest.mark.asyncio
async def test_catalog_rule_excludes_allied_competitor_before_gateway_mutation() -> None:
    db = FakeDb(
        [_catalog_rule_doc(rule_id="catalog-1", seller_id="123456789")],
        allies=[_allies_doc(seller_id="123456789", ally_account_id="ally-1")],
    )
    gateway = FakeGatewayClient()
    handler = RepricerEventHandler(
        db=db,
        gateway_client=gateway,
        idempotency_store=FakeIdempotency(),
        clock=lambda: NOW,
    )

    result = await handler.handle(
        _event(seller_id=123456789, buybox_price=Decimal("118"), competitor_account_id="ally-1")
    )

    assert result == "no_action"
    assert gateway.calls == []
    assert db["repricer_history"].docs[0]["reason"] == "ally_competitor"
    assert (
        db["repricer_catalog_rules"].updates[0][1]["$set"]["execution_state.last_outcome"]
        == "no_action"
    )


@pytest.mark.asyncio
async def test_catalog_rule_escalated_limits_block_gateway_mutation() -> None:
    db = FakeDb(
        [_catalog_rule_doc(rule_id="catalog-1", seller_id="123456789")],
        limits=[
            _limits_doc(
                seller_id="123456789",
                account_id="acc-1",
                escalate_to_manual_review=True,
            )
        ],
    )
    gateway = FakeGatewayClient()
    handler = RepricerEventHandler(
        db=db,
        gateway_client=gateway,
        idempotency_store=FakeIdempotency(),
        clock=lambda: NOW,
    )

    result = await handler.handle(_event(seller_id=123456789, buybox_price=Decimal("118")))

    assert result == "no_action"
    assert gateway.calls == []
    assert db["repricer_history"].docs[0]["reason"] == "manual_review_required"
    assert (
        db["repricer_catalog_rules"].updates[0][1]["$set"]["execution_state.last_outcome"]
        == "guard_blocked"
    )


def test_repricer_worker_subscribes_to_scheduler_sweep_requests() -> None:
    from pathlib import Path

    from zeler_repricer.consumer import RepricerAmqpConsumerConfig, _routing_keys_from_manifest

    manifest_path = Path(__file__).resolve().parents[1] / "manifest.yaml"

    assert "repricer.sweep.requested" in RepricerAmqpConsumerConfig(
        rabbitmq_url="amqp://guest:guest@rabbitmq:5672/"
    ).routing_keys
    assert "repricer.sweep.requested" in _routing_keys_from_manifest(manifest_path)


def _event(
    *,
    seller_id: int,
    buybox_price: Decimal,
    competitor_account_id: str | None = None,
) -> RepricerEvent:
    return RepricerEvent(
        event_id="event-1",
        event_type="items.price_updated",
        seller_id=seller_id,
        resource="/items/MLA123/prices",
        idempotency_key="idem-1",
        buybox_price=buybox_price,
        competitor_account_id=competitor_account_id,
    )


def _catalog_rule_doc(*, rule_id: str, seller_id: str) -> dict[str, Any]:
    return {
        "_id": rule_id,
        "seller_id": seller_id,
        "account_id": "acc-1",
        "item_id": "MLA123",
        "title": "Catalog Item",
        "sku": "SKU-123",
        "strategy": "competitive",
        "min_price": Decimal("100"),
        "max_price": Decimal("120"),
        "active": True,
        "execution_state": {},
        "created_at": NOW,
        "updated_at": NOW,
        "created_by": "operator-1",
        "updated_by": "operator-1",
        "schema_version": 1,
    }


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


def _limits_doc(
    *,
    seller_id: str,
    account_id: str,
    min_price_limit: str = "100",
    max_price_limit: str = "120",
    undercut_delta: str = "0",
    pause_competition: bool = False,
    escalate_to_manual_review: bool = False,
) -> dict[str, Any]:
    return {
        "_id": f"limits-{seller_id}-{account_id}",
        "seller_id": seller_id,
        "account_id": account_id,
        "enabled": True,
        "min_price_limit": Decimal(min_price_limit),
        "max_price_limit": Decimal(max_price_limit),
        "undercut_delta": Decimal(undercut_delta),
        "pause_competition": pause_competition,
        "escalate_to_manual_review": escalate_to_manual_review,
        "created_at": NOW,
        "updated_at": NOW,
        "schema_version": 1,
    }


def _allies_doc(*, seller_id: str, ally_account_id: str) -> dict[str, Any]:
    return {
        "_id": f"allies-{seller_id}",
        "seller_id": seller_id,
        "allies": [{"account_id": ally_account_id, "nickname": "ALLY SHOP"}],
        "created_at": NOW,
        "updated_at": NOW,
        "schema_version": 1,
    }


def _assign_dotted(document: dict[str, Any], key: str, value: Any) -> None:
    parts = key.split(".")
    target = document
    for part in parts[:-1]:
        target = target.setdefault(part, {})
    target[parts[-1]] = value
