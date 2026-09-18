from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import httpx
import pytest

from zeler_platform_core.clients.meli_gateway_client import GatewayRateLimitError
from zeler_platform_core.events.claim_gate import EventClaimTimeoutError
from zeler_platform_core.events.claims import ClaimOutcome
from zeler_platform_core.models import RepricerRule
from zeler_repricer import consumer
from zeler_repricer.consumer import (
    GatewayPriceClient,
    RepricerAmqpConsumerRunner,
    RepricerEvent,
    RepricerEventHandler,
)

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
    def __init__(self, *, status_code: int = 200, error: Exception | None = None) -> None:
        self.calls: list[tuple[int, str, Decimal, str]] = []
        self.status_code = status_code
        self.error = error

    async def update_price(
        self, *, seller_id: int, item_id: str, new_price: Decimal, idempotency_key: str
    ) -> tuple[int, int]:
        self.calls.append((seller_id, item_id, new_price, idempotency_key))
        if self.error is not None:
            raise self.error
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
            event_type="items.price_updated",
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
            event_type="items.price_updated",
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
            event_type="items.price_updated",
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
        db=db,
        gateway_client=FakeGatewayClient(error=_rate_limit_error(retry_after_seconds=5)),
        idempotency_store=idempotency,
    )

    with pytest.raises(GatewayRateLimitError):
        await handler.handle(
            RepricerEvent(
                event_id="event-3",
                event_type="items.price_updated",
                seller_id=123456789,
                resource="/items/MLA123/prices",
                idempotency_key="idem-3",
                buybox_price=Decimal("180"),
            )
        )

    assert idempotency.marked == []


# --- S3a: atomic event claim gate adoption (delivery-gate semantics) -------


class CountingCollection(FakeCollection):
    """FakeCollection that counts find_one probes to prove short-circuiting."""

    def __init__(self, docs: list[dict[str, Any]] | None = None) -> None:
        super().__init__(docs)
        self.find_one_calls = 0

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        self.find_one_calls += 1
        return await super().find_one(query)


class _LogSpy:
    """Structured-logging spy pattern used by the sheets consumer tests."""

    def __init__(self) -> None:
        self.warning_calls: list[tuple[str, dict[str, Any]]] = []

    def warning(self, event: str, **fields: Any) -> None:
        self.warning_calls.append((event, fields))

    def info(self, event: str, **fields: Any) -> None:
        pass

    def error(self, event: str, **fields: Any) -> None:
        pass


class FakeClaimStore:
    """``EventClaimStore`` double recording owner tokens per call."""

    def __init__(
        self,
        outcome: ClaimOutcome = ClaimOutcome.CLAIMED,
        *,
        complete_result: bool = True,
    ) -> None:
        self.outcome = outcome
        self.complete_result = complete_result
        self.claimed: list[str] = []
        self.completed: list[tuple[str, str]] = []
        self.released: list[tuple[str, str]] = []
        self._tokens: dict[str, str] = {}

    async def claim(
        self,
        idempotency_key: str,
        *,
        module_id: str,
        consumer_id: str | None = None,
        owner_token: str,
        **kwargs: Any,
    ) -> ClaimOutcome:
        self.claimed.append(idempotency_key)
        self._tokens[idempotency_key] = owner_token
        return self.outcome

    async def complete(
        self,
        idempotency_key: str,
        *,
        module_id: str,
        consumer_id: str | None = None,
        owner_token: str,
    ) -> bool:
        self.completed.append((idempotency_key, owner_token))
        return self.complete_result

    async def release(
        self,
        idempotency_key: str,
        *,
        module_id: str,
        consumer_id: str | None = None,
        owner_token: str,
    ) -> bool:
        self.released.append((idempotency_key, owner_token))
        return True


def _claim_handler(
    db: FakeDb,
    gateway: FakeGatewayClient,
    store: FakeClaimStore,
) -> RepricerEventHandler:
    return RepricerEventHandler(
        db=db,
        gateway_client=gateway,
        idempotency_store=FakeIdempotency(),
        event_claim_store=store,
    )


@pytest.mark.asyncio
async def test_claim_gate_duplicate_short_circuits_before_any_read_or_side_effect() -> None:
    db = FakeDb()
    db.collections["items"] = CountingCollection(db.collections["items"].docs)
    gateway = FakeGatewayClient()
    store = FakeClaimStore(outcome=ClaimOutcome.COMPLETED)
    handler = _claim_handler(db, gateway, store)

    result = await handler.handle(
        RepricerEvent(
            event_id="event-dup",
            event_type="items.price_updated",
            seller_id=123456789,
            resource="/items/MLA123/prices",
            idempotency_key="idem-dup",
            buybox_price=Decimal("180"),
        )
    )

    assert result == "duplicate"
    assert cast(Any, db["items"]).find_one_calls == 0
    assert gateway.calls == []
    assert db["repricer_history"].docs == []
    assert store.completed == []
    assert store.released == []


@pytest.mark.asyncio
async def test_claim_gate_terminal_set_price_completes_claim_once() -> None:
    db = FakeDb()
    gateway = FakeGatewayClient()
    store = FakeClaimStore()
    handler = _claim_handler(db, gateway, store)

    result = await handler.handle(
        RepricerEvent(
            event_id="event-1",
            event_type="items.price_updated",
            seller_id=123456789,
            resource="/items/MLA123/prices",
            idempotency_key="idem-1",
            buybox_price=Decimal("180"),
        )
    )

    assert result == "set_price"
    assert store.completed == [("idem-1", store._tokens["idem-1"])]
    assert store.released == []


@pytest.mark.asyncio
async def test_claim_gate_terminal_no_action_completes_claim_once() -> None:
    db = FakeDb()
    gateway = FakeGatewayClient()
    store = FakeClaimStore()
    handler = _claim_handler(db, gateway, store)

    result = await handler.handle(
        RepricerEvent(
            event_id="event-2",
            event_type="items.price_updated",
            seller_id=123456789,
            resource="/items/MLA123/prices",
            idempotency_key="idem-2",
            buybox_price=Decimal("90"),
        )
    )

    assert result == "no_action"
    assert store.completed == [("idem-2", store._tokens["idem-2"])]
    assert store.released == []


@pytest.mark.asyncio
async def test_claim_gate_item_missing_releases_claim_for_redelivery() -> None:
    db = FakeDb()
    db.collections["items"] = CountingCollection([])
    gateway = FakeGatewayClient()
    store = FakeClaimStore()
    handler = _claim_handler(db, gateway, store)

    result = await handler.handle(
        RepricerEvent(
            event_id="event-3",
            event_type="items.price_updated",
            seller_id=123456789,
            resource="/items/MLA123/prices",
            idempotency_key="idem-3",
            buybox_price=Decimal("180"),
        )
    )

    assert result == "item_missing"
    assert store.released == [("idem-3", store._tokens["idem-3"])]
    assert store.completed == []


@pytest.mark.asyncio
async def test_claim_gate_rule_missing_releases_claim_for_redelivery() -> None:
    db = FakeDb()
    db.collections["repricer_rules"] = FakeCollection([])
    gateway = FakeGatewayClient()
    store = FakeClaimStore()
    handler = _claim_handler(db, gateway, store)

    result = await handler.handle(
        RepricerEvent(
            event_id="event-4",
            event_type="items.price_updated",
            seller_id=123456789,
            resource="/items/MLA123/prices",
            idempotency_key="idem-4",
            buybox_price=Decimal("180"),
        )
    )

    assert result == "rule_missing"
    assert store.released == [("idem-4", store._tokens["idem-4"])]
    assert store.completed == []


@pytest.mark.asyncio
async def test_claim_gate_failure_releases_claim_and_preserves_original_exception() -> None:
    db = FakeDb()
    gateway = FakeGatewayClient(error=RuntimeError("gateway exploded"))
    store = FakeClaimStore()
    handler = _claim_handler(db, gateway, store)

    with pytest.raises(RuntimeError, match="gateway exploded"):
        await handler.handle(
            RepricerEvent(
                event_id="event-5",
                event_type="items.price_updated",
                seller_id=123456789,
                resource="/items/MLA123/prices",
                idempotency_key="idem-5",
                buybox_price=Decimal("180"),
            )
        )

    assert store.released == [("idem-5", store._tokens["idem-5"])]
    assert store.completed == []


@pytest.mark.asyncio
async def test_lost_lease_completion_warns_and_still_returns_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_spy = _LogSpy()
    monkeypatch.setattr(consumer, "logger", log_spy, raising=False)
    store = FakeClaimStore(complete_result=False)
    handler = _claim_handler(FakeDb(), FakeGatewayClient(), store)

    result = await handler.handle(
        RepricerEvent(
            event_id="event-1",
            event_type="items.price_updated",
            seller_id=123456789,
            resource="/items/MLA123/prices",
            idempotency_key="idem-1",
            buybox_price=Decimal("180"),
        )
    )

    assert result == "set_price"
    assert store.completed == [("idem-1", store._tokens["idem-1"])]
    assert log_spy.warning_calls == [
        (
            "worker.event_claim.lost_lease",
            {"idempotency_key": "idem-1", "module": "repricer"},
        )
    ]


@pytest.mark.asyncio
async def test_normal_completion_does_not_warn_about_lost_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_spy = _LogSpy()
    monkeypatch.setattr(consumer, "logger", log_spy, raising=False)
    store = FakeClaimStore()
    handler = _claim_handler(FakeDb(), FakeGatewayClient(), store)

    result = await handler.handle(
        RepricerEvent(
            event_id="event-1",
            event_type="items.price_updated",
            seller_id=123456789,
            resource="/items/MLA123/prices",
            idempotency_key="idem-1",
            buybox_price=Decimal("180"),
        )
    )

    assert result == "set_price"
    assert store.completed == [("idem-1", store._tokens["idem-1"])]
    assert log_spy.warning_calls == []


class FakeRetryDelayPublisher:
    def __init__(self) -> None:
        self.calls: list[tuple[bytes, str, int]] = []

    async def publish_delay(self, body: bytes, queue_name: str, *, delay_ms: int) -> None:
        self.calls.append((body, queue_name, delay_ms))


class FakeRunnerHandler:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.events: list[RepricerEvent] = []

    async def handle(self, event: RepricerEvent) -> str:
        self.events.append(event)
        if self.error is not None:
            raise self.error
        return "set_price"


class FakeRunnerMessage:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.body = json.dumps(payload).encode("utf-8")
        self.headers: dict[str, Any] = {}
        self.acked = False
        self.nacks: list[bool] = []

    async def ack(self) -> None:
        self.acked = True

    async def nack(self, *, requeue: bool = False) -> None:
        self.nacks.append(requeue)


def _runner_payload() -> dict[str, Any]:
    return {
        "event_id": "evt-claim-1",
        "event_type": "items.price_updated",
        "seller_id": 123456789,
        "resource": "items/MLA123",
    }


@pytest.mark.asyncio
async def test_event_claim_timeout_requeues_through_retry_delay_publisher() -> None:
    publisher = FakeRetryDelayPublisher()
    runner = RepricerAmqpConsumerRunner(
        rabbitmq_url="amqp://unit-test",
        handler=FakeRunnerHandler(error=EventClaimTimeoutError("claim busy")),
        retry_delay_publisher=publisher,
    )
    message = FakeRunnerMessage(_runner_payload())

    await runner.handle_message(message)

    assert message.acked is True
    assert message.nacks == []
    assert publisher.calls == [(message.body, "zeler.repricer.items", 1000)]


@pytest.mark.asyncio
async def test_event_claim_timeout_without_publisher_nacks_with_requeue() -> None:
    runner = RepricerAmqpConsumerRunner(
        rabbitmq_url="amqp://unit-test",
        handler=FakeRunnerHandler(error=EventClaimTimeoutError("claim busy")),
    )
    message = FakeRunnerMessage(_runner_payload())

    await runner.handle_message(message)

    assert message.acked is False
    assert message.nacks == [True]


def _rate_limit_error(*, retry_after_seconds: int) -> GatewayRateLimitError:
    request = httpx.Request("POST", "http://gateway:8080/proxy/meli/items/MLA123/prices")
    response = httpx.Response(429, request=request)
    return GatewayRateLimitError(retry_after_seconds=retry_after_seconds, response=response)


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
