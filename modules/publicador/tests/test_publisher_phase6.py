from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest


class FakeCollection:
    def __init__(self, docs: list[dict[str, Any]] | None = None) -> None:
        self.docs = docs or []

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                return doc
        return None

    async def replace_one(
        self, query: dict[str, Any], replacement: dict[str, Any], *, upsert: bool
    ) -> None:
        assert upsert is True
        for index, doc in enumerate(self.docs):
            if all(doc.get(key) == value for key, value in query.items()):
                self.docs[index] = replacement
                return
        self.docs.append(replacement)

    async def insert_one(self, doc: dict[str, Any]) -> None:
        self.docs.append(doc)


class FakeDb:
    def __init__(self) -> None:
        self.publicador_drafts = FakeCollection(
            [
                {
                    "_id": "draft-1",
                    "seller_id": "123456789",
                    "source_product": {"sku": "SKU-1", "price": 1999},
                    "generated_listing": {
                        "title": "Zapatillas urbanas",
                        "description": "Detalle listo para publicar",
                        "attributes": {"BRAND": "Zeler"},
                    },
                    "status": "draft",
                    "created_at": datetime(2026, 4, 24, 12, tzinfo=UTC),
                    "updated_at": datetime(2026, 4, 24, 12, tzinfo=UTC),
                    "schema_version": 1,
                }
            ]
        )
        self.publicador_history = FakeCollection()

    def __getitem__(self, name: str) -> FakeCollection:
        if name == "publicador_drafts":
            return self.publicador_drafts
        if name == "publicador_history":
            return self.publicador_history
        raise AssertionError(name)


class FakeGatewayClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def request(
        self, method: str, path: str, *, seller_id: str, json: dict[str, Any]
    ) -> dict[str, Any]:
        self.calls.append((method, path, {"seller_id": seller_id, "json": json}))
        if path == "/items/validate":
            return {"status": "valid"}
        return {"id": "MLA123", "status": "active"}


@pytest.mark.asyncio
async def test_publish_calls_gateway_proxy_and_records_success_history() -> None:
    from zeler_publicador.publisher import PublicadorPublisher

    db = FakeDb()
    gateway = FakeGatewayClient()
    publisher = PublicadorPublisher(
        mongo_db=db,
        gateway_client=gateway,
        clock=lambda: datetime(2026, 4, 24, 12, 30, tzinfo=UTC),
    )

    result = await publisher.publish("draft-1")

    assert result.item_id == "MLA123"
    assert result.outcome == "published"
    assert gateway.calls == [
        (
            "POST",
            "/items/validate",
            {"seller_id": "123456789", "json": result.payload},
        ),
        ("POST", "/items", {"seller_id": "123456789", "json": result.payload}),
    ]
    assert db.publicador_drafts.docs[0]["status"] == "published"
    assert db.publicador_history.docs == [
        {
            "_id": "publicador-history-draft-1-1777033800",
            "seller_id": "123456789",
            "draft_id": "draft-1",
            "action": "publish",
            "outcome": "published",
            "meli_item_id": "MLA123",
            "gateway_response": {"id": "MLA123", "status": "active"},
            "error": None,
            "created_at": datetime(2026, 4, 24, 12, 30, tzinfo=UTC),
            "schema_version": 1,
        }
    ]


@pytest.mark.asyncio
async def test_publish_records_validation_failure_without_creating_item() -> None:
    from zeler_publicador.publisher import PublicadorPublisher, PublishValidationError

    class InvalidGateway(FakeGatewayClient):
        async def request(
            self, method: str, path: str, *, seller_id: str, json: dict[str, Any]
        ) -> dict[str, Any]:
            self.calls.append((method, path, {"seller_id": seller_id, "json": json}))
            return {"status": "invalid", "errors": ["missing category"]}

    db = FakeDb()
    gateway = InvalidGateway()
    publisher = PublicadorPublisher(
        mongo_db=db,
        gateway_client=gateway,
        clock=lambda: datetime(2026, 4, 24, 12, 30, tzinfo=UTC),
    )

    with pytest.raises(PublishValidationError, match="missing category"):
        await publisher.publish("draft-1")

    assert [call[1] for call in gateway.calls] == ["/items/validate"]
    assert db.publicador_drafts.docs[0]["status"] == "validation_failed"
    assert db.publicador_history.docs[0]["outcome"] == "validation_failed"
