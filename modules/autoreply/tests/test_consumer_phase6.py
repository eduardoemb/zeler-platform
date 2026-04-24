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
    def __init__(self, templates: list[dict[str, Any]]) -> None:
        self.autoreply_templates = FakeCollection(templates)
        self.autoreply_history = FakeCollection([])

    def __getitem__(self, name: str) -> FakeCollection:
        if name == "autoreply_templates":
            return self.autoreply_templates
        if name == "autoreply_history":
            return self.autoreply_history
        raise AssertionError(name)


class FakeGatewayClient:
    def __init__(self, resource: dict[str, Any]) -> None:
        self.resource = resource
        self.requests: list[tuple[str, str, str, dict[str, Any] | None]] = []

    async def request(
        self, method: str, path: str, *, seller_id: str, json: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self.requests.append((method, path, seller_id, json))
        if method == "GET":
            return self.resource
        return {"id": "answer-1", "status": "created"}


class FakeIdempotencyStore:
    def __init__(self, duplicates: set[str] | None = None) -> None:
        self.duplicates = duplicates or set()
        self.processed: list[str] = []

    async def is_duplicate(self, key: str) -> bool:
        return key in self.duplicates

    async def mark_processed(self, key: str) -> None:
        self.processed.append(key)


@pytest.mark.asyncio
async def test_matched_template_triggers_answer() -> None:
    from zeler_autoreply.consumer import AutoreplyEvent, AutoreplyEventHandler

    db = FakeDb(
        [
            {
                "_id": "template-1",
                "seller_id": "123456789",
                "template_name": "shipping",
                "match_type": "keyword",
                "pattern": "envio",
                "answer_text": "Hola, hacemos envíos a todo el país.",
                "enabled": True,
            }
        ]
    )
    gateway = FakeGatewayClient({"id": 987, "text": "Tienen envio a Córdoba?"})
    idempotency = FakeIdempotencyStore()
    handler = AutoreplyEventHandler(
        db=db,
        gateway_client=gateway,
        idempotency_store=idempotency,
        clock=lambda: datetime(2026, 4, 24, 12, 0, tzinfo=UTC),
    )

    outcome = await handler.handle(
        AutoreplyEvent(
            event_id="event-1",
            event_type="questions.new",
            seller_id=123456789,
            resource="/questions/987",
            idempotency_key="idem-1",
        )
    )

    assert outcome == "answered"
    assert gateway.requests == [
        ("GET", "/questions/987", "123456789", None),
        (
            "POST",
            "/answers",
            "123456789",
            {"question_id": "987", "text": "Hola, hacemos envíos a todo el país."},
        ),
    ]
    assert db.autoreply_history.docs[0]["outcome"] == "answered"
    assert db.autoreply_history.docs[0]["template_id"] == "template-1"
    assert idempotency.processed == ["idem-1"]


@pytest.mark.asyncio
async def test_regex_template_matches_message_text() -> None:
    from zeler_autoreply.consumer import AutoreplyEvent, AutoreplyEventHandler

    db = FakeDb(
        [
            {
                "_id": "template-returns",
                "seller_id": "123456789",
                "template_name": "returns",
                "match_type": "regex",
                "pattern": "devoluci[oó]n",
                "answer_text": "Podés iniciar la devolución desde tu compra.",
                "enabled": True,
            }
        ]
    )
    gateway = FakeGatewayClient({"id": "msg-77", "text": "Necesito una devolución"})
    handler = AutoreplyEventHandler(
        db=db,
        gateway_client=gateway,
        idempotency_store=FakeIdempotencyStore(),
        clock=lambda: datetime(2026, 4, 24, 12, 5, tzinfo=UTC),
    )

    outcome = await handler.handle(
        AutoreplyEvent(
            event_id="event-2",
            event_type="messages.new",
            seller_id=123456789,
            resource="/messages/msg-77",
            idempotency_key="idem-2",
        )
    )

    assert outcome == "answered"
    assert gateway.requests[-1] == (
        "POST",
        "/answers",
        "123456789",
        {"message_id": "msg-77", "text": "Podés iniciar la devolución desde tu compra."},
    )


@pytest.mark.asyncio
async def test_no_match_skips_and_records_history() -> None:
    from zeler_autoreply.consumer import AutoreplyEvent, AutoreplyEventHandler

    db = FakeDb(
        [
            {
                "_id": "template-1",
                "seller_id": "123456789",
                "template_name": "shipping",
                "match_type": "keyword",
                "pattern": "envio",
                "answer_text": "Hola, hacemos envíos a todo el país.",
                "enabled": True,
            }
        ]
    )
    gateway = FakeGatewayClient({"id": 987, "text": "Es color azul?"})
    idempotency = FakeIdempotencyStore()
    handler = AutoreplyEventHandler(
        db=db,
        gateway_client=gateway,
        idempotency_store=idempotency,
        clock=lambda: datetime(2026, 4, 24, 12, 10, tzinfo=UTC),
    )

    outcome = await handler.handle(
        AutoreplyEvent(
            event_id="event-3",
            event_type="questions.new",
            seller_id=123456789,
            resource="/questions/987",
            idempotency_key="idem-3",
        )
    )

    assert outcome == "no_match"
    assert gateway.requests == [("GET", "/questions/987", "123456789", None)]
    assert db.autoreply_history.docs[0]["outcome"] == "no_match"
    assert idempotency.processed == ["idem-3"]


@pytest.mark.asyncio
async def test_duplicate_event_skipped_without_gateway_calls() -> None:
    from zeler_autoreply.consumer import AutoreplyEvent, AutoreplyEventHandler

    gateway = FakeGatewayClient({"id": 987, "text": "Tienen envio?"})
    handler = AutoreplyEventHandler(
        db=FakeDb([]),
        gateway_client=gateway,
        idempotency_store=FakeIdempotencyStore({"idem-duplicate"}),
    )

    outcome = await handler.handle(
        AutoreplyEvent(
            event_id="event-4",
            event_type="questions.new",
            seller_id=123456789,
            resource="/questions/987",
            idempotency_key="idem-duplicate",
        )
    )

    assert outcome == "duplicate"
    assert gateway.requests == []
