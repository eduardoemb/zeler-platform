from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI


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

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                return doc
        return None

    async def insert_one(self, doc: dict[str, Any]) -> None:
        self.docs.append(doc)

    async def replace_one(
        self, query: dict[str, Any], replacement: dict[str, Any], *, upsert: bool
    ) -> None:
        assert upsert is True
        for index, doc in enumerate(self.docs):
            if all(doc.get(key) == value for key, value in query.items()):
                self.docs[index] = replacement
                return
        self.docs.append(replacement)


class FakeDb:
    def __init__(self) -> None:
        self.publicador_drafts = FakeCollection(
            [
                {
                    "_id": "draft-1",
                    "seller_id": "123456789",
                    "source_product": {"name": "Zapatillas", "category_id": "MLA1", "price": 1999},
                    "generated_listing": {},
                    "status": "draft",
                    "created_at": "2026-04-24T12:00:00+00:00",
                    "updated_at": "2026-04-24T12:00:00+00:00",
                    "schema_version": 1,
                }
            ]
        )
        self.publicador_history = FakeCollection(
            [
                {
                    "_id": "history-1",
                    "seller_id": "123456789",
                    "draft_id": "draft-1",
                    "action": "publish",
                    "outcome": "published",
                    "created_at": "2026-04-24T12:30:00+00:00",
                    "schema_version": 1,
                }
            ]
        )

    def __getitem__(self, name: str) -> FakeCollection:
        if name == "publicador_drafts":
            return self.publicador_drafts
        if name == "publicador_history":
            return self.publicador_history
        raise AssertionError(name)


class FakeGenerator:
    async def generate(self, _product: object) -> object:
        class Listing:
            def model_dump(self) -> dict[str, Any]:
                return {
                    "title": "Zapatillas urbanas",
                    "description": "Detalle generado por IA",
                    "attributes": {"BRAND": "Zeler"},
                }

        return Listing()


class FakePublisher:
    def __init__(self) -> None:
        self.published: list[str] = []

    async def publish(self, draft_id: str) -> object:
        self.published.append(draft_id)

        class Result:
            item_id = "MLA123"
            outcome = "published"
            payload = {"title": "Zapatillas urbanas"}

        return Result()


@pytest.mark.asyncio
async def test_list_drafts_includes_history(monkeypatch: pytest.MonkeyPatch) -> None:
    app, _db, _publisher = _app(monkeypatch)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/publicador/drafts?seller_id=123456789",
            headers={"Authorization": "Bearer valid"},
        )

    assert response.status_code == 200
    assert response.json()[0]["_id"] == "draft-1"
    assert response.json()[0]["history"][0]["outcome"] == "published"


@pytest.mark.asyncio
async def test_create_draft_persists_source_product(monkeypatch: pytest.MonkeyPatch) -> None:
    app, db, _publisher = _app(monkeypatch)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/publicador/drafts",
            headers={"Authorization": "Bearer valid"},
            json={
                "seller_id": "123456789",
                "source_product": {"name": "Campera", "category_id": "MLA2", "price": 4500},
            },
        )

    assert response.status_code == 201
    assert response.json()["status"] == "draft"
    assert db.publicador_drafts.docs[-1]["source_product"]["name"] == "Campera"


@pytest.mark.asyncio
async def test_generate_updates_draft_with_llm_listing(monkeypatch: pytest.MonkeyPatch) -> None:
    app, db, _publisher = _app(monkeypatch)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/publicador/drafts/draft-1/generate",
            headers={"Authorization": "Bearer valid"},
        )

    assert response.status_code == 200
    assert response.json()["generated_listing"]["title"] == "Zapatillas urbanas"
    assert db.publicador_drafts.docs[0]["status"] == "generated"


@pytest.mark.asyncio
async def test_publish_endpoint_delegates_to_gateway_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    app, _db, publisher = _app(monkeypatch)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/publicador/drafts/draft-1/publish",
            headers={"Authorization": "Bearer valid"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "item_id": "MLA123",
        "outcome": "published",
        "payload": {"title": "Zapatillas urbanas"},
    }
    assert publisher.published == ["draft-1"]


@pytest.mark.asyncio
async def test_only_module_jwt_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    from zeler_platform_core.auth.jwt import InvalidJWTError

    app, _db, _publisher = _app(monkeypatch, jwt_error=InvalidJWTError("bad token"))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/publicador/drafts?seller_id=123456789",
            headers={"Authorization": "Bearer invalid"},
        )

    assert response.status_code == 401
    assert response.json() == {"error": "invalid_token", "detail": "bad token"}


def _app(
    monkeypatch: pytest.MonkeyPatch, jwt_error: Exception | None = None
) -> tuple[FastAPI, FakeDb, FakePublisher]:
    import zeler_publicador.api as api
    from zeler_publicador.api import build_router

    db = FakeDb()
    publisher = FakePublisher()
    app = FastAPI()
    app.state.mongo_db = db
    app.include_router(
        build_router(
            generator=FakeGenerator(),
            publisher=publisher,
            clock=lambda: datetime(2026, 4, 24, 12, 30, tzinfo=UTC),
        )
    )

    def fake_verify(_token: str) -> object:
        if jwt_error is not None:
            raise jwt_error
        return object()

    monkeypatch.setattr(api, "verify_module_jwt", fake_verify)
    return app, db, publisher
