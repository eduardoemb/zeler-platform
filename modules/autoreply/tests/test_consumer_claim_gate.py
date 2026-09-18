"""Focused AutoreplyEventHandler tests for the atomic event claim gate.

Mirrors the Repricer/Sheets adoption: one exclusive claim per delivery key in
front of the gateway read and any Mongo access, terminal outcomes complete the
claim, failures release it without masking the original exception, and a lost
lease surfaces through ``worker.event_claim.lost_lease``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from zeler_autoreply import consumer
from zeler_autoreply.consumer import AutoreplyEvent, AutoreplyEventHandler
from zeler_platform_core.events.claims import ClaimOutcome


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
    def __init__(self, templates: list[dict[str, Any]]) -> None:
        self.autoreply_templates = FakeCollection(templates)
        self.autoreply_history = FakeCollection([])

    def __getitem__(self, name: str) -> FakeCollection:
        if name == "autoreply_templates":
            return self.autoreply_templates
        if name == "autoreply_history":
            return self.autoreply_history
        raise AssertionError(f"unexpected Mongo access: {name}")


class FakeGatewayClient:
    def __init__(self, resource: dict[str, Any] | None = None, error: Exception | None = None):
        self.resource = resource or {}
        self.error = error
        self.requests: list[tuple[str, str, str, dict[str, Any] | None]] = []

    async def request(
        self, method: str, path: str, *, seller_id: str, json: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self.requests.append((method, path, seller_id, json))
        if self.error is not None:
            raise self.error
        return self.resource


class FakeIdempotencyStore:
    async def is_duplicate(self, key: str) -> bool:
        return False

    async def mark_processed(self, key: str) -> None:
        raise AssertionError("legacy mark_processed must not run under the claim gate")


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


def _template(pattern: str = "envio") -> dict[str, Any]:
    return {
        "_id": "template-1",
        "seller_id": "123456789",
        "template_name": "shipping",
        "match_type": "keyword",
        "pattern": pattern,
        "answer_text": "Hola, hacemos envíos a todo el país.",
        "enabled": True,
    }


def _claim_handler(
    db: FakeDb,
    gateway: FakeGatewayClient,
    store: FakeClaimStore,
) -> AutoreplyEventHandler:
    return AutoreplyEventHandler(
        db=db,
        gateway_client=gateway,
        idempotency_store=FakeIdempotencyStore(),
        event_claim_store=store,
    )


def _event(idempotency_key: str) -> AutoreplyEvent:
    return AutoreplyEvent(
        event_id="event-1",
        event_type="questions.new",
        seller_id=123456789,
        resource="/questions/987",
        idempotency_key=idempotency_key,
    )


@pytest.mark.asyncio
async def test_claim_gate_duplicate_short_circuits_without_gateway_call() -> None:
    db = FakeDb([_template()])
    gateway = FakeGatewayClient({"id": 987, "text": "Tienen envio?"})
    store = FakeClaimStore(outcome=ClaimOutcome.COMPLETED)
    handler = _claim_handler(db, gateway, store)

    result = await handler.handle(_event("idem-dup"))

    assert result == "duplicate"
    assert gateway.requests == []
    assert db.autoreply_history.docs == []
    assert store.completed == []
    assert store.released == []


@pytest.mark.asyncio
async def test_claim_gate_no_match_completes_claim_once() -> None:
    db = FakeDb([])
    gateway = FakeGatewayClient({"id": 987, "text": "Es color azul?"})
    store = FakeClaimStore()
    handler = _claim_handler(db, gateway, store)

    result = await handler.handle(_event("idem-1"))

    assert result == "no_match"
    assert store.claimed == ["idem-1"]
    assert store.completed == [("idem-1", store._tokens["idem-1"])]
    assert store.released == []
    assert gateway.requests == [("GET", "/questions/987", "123456789", None)]


@pytest.mark.asyncio
async def test_claim_gate_answered_completes_claim_once() -> None:
    db = FakeDb([_template()])
    gateway = FakeGatewayClient({"id": 987, "text": "Tienen envio a Córdoba?"})
    store = FakeClaimStore()
    handler = _claim_handler(db, gateway, store)

    result = await handler.handle(_event("idem-1"))

    assert result == "answered"
    assert store.completed == [("idem-1", store._tokens["idem-1"])]
    assert store.released == []
    assert db.autoreply_history.docs[0]["outcome"] == "answered"


@pytest.mark.asyncio
async def test_lost_lease_completion_warns_and_still_returns_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_spy = _LogSpy()
    monkeypatch.setattr(consumer, "logger", log_spy, raising=False)
    store = FakeClaimStore(complete_result=False)
    handler = _claim_handler(
        FakeDb([_template()]), FakeGatewayClient({"id": 987, "text": "Tienen envio?"}), store
    )

    result = await handler.handle(_event("idem-1"))

    assert result == "answered"
    assert store.completed == [("idem-1", store._tokens["idem-1"])]
    assert log_spy.warning_calls == [
        (
            "worker.event_claim.lost_lease",
            {"idempotency_key": "idem-1", "module": "autoreply"},
        )
    ]


@pytest.mark.asyncio
async def test_normal_completion_does_not_warn_about_lost_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_spy = _LogSpy()
    monkeypatch.setattr(consumer, "logger", log_spy, raising=False)
    store = FakeClaimStore()
    handler = _claim_handler(
        FakeDb([_template()]),
        FakeGatewayClient({"id": 987, "text": "Tienen envio?"}),
        store,
    )

    result = await handler.handle(_event("idem-1"))

    assert result == "answered"
    assert log_spy.warning_calls == []


@pytest.mark.asyncio
async def test_claim_gate_failure_releases_claim_and_preserves_original_exception() -> None:
    db = FakeDb([_template()])
    gateway = FakeGatewayClient(error=RuntimeError("gateway exploded"))
    store = FakeClaimStore()
    handler = _claim_handler(db, gateway, store)

    with pytest.raises(RuntimeError, match="gateway exploded"):
        await handler.handle(_event("idem-1"))

    assert store.released == [("idem-1", store._tokens["idem-1"])]
    assert store.completed == []
    assert db.autoreply_history.docs == []


@pytest.mark.asyncio
async def test_legacy_path_still_marks_processed_through_idempotency_store() -> None:
    class MarkingIdempotencyStore:
        def __init__(self) -> None:
            self.processed: list[str] = []

        async def is_duplicate(self, key: str) -> bool:
            return False

        async def mark_processed(self, key: str) -> None:
            self.processed.append(key)

    idempotency = MarkingIdempotencyStore()
    handler = AutoreplyEventHandler(
        db=FakeDb([]),
        gateway_client=FakeGatewayClient({"id": 987, "text": "Es color azul?"}),
        idempotency_store=idempotency,
        clock=lambda: datetime(2026, 4, 24, 12, 0, tzinfo=UTC),
    )

    result = await handler.handle(_event("idem-legacy"))

    assert result == "no_match"
    assert idempotency.processed == ["idem-legacy"]
