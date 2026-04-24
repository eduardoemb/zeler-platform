from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI


class FakeCollection:
    def __init__(self) -> None:
        self.docs: list[dict[str, Any]] = []

    def find(self, query: dict[str, Any]) -> Any:
        docs = [
            doc for doc in self.docs if all(doc.get(key) == value for key, value in query.items())
        ]

        class Cursor:
            async def to_list(self, length: int) -> list[dict[str, Any]]:
                return docs[:length]

        return Cursor()

    async def insert_one(self, doc: dict[str, Any]) -> None:
        self.docs.append(doc)

    async def update_one(self, query: dict[str, Any], update: dict[str, Any]) -> None:
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                doc.update(update["$set"])


class FakeDb:
    def __init__(self) -> None:
        self.repricer_rules = FakeCollection()

    def __getitem__(self, name: str) -> FakeCollection:
        assert name == "repricer_rules"
        return self.repricer_rules


@pytest.mark.asyncio
async def test_create_rule_returns_201(monkeypatch: pytest.MonkeyPatch) -> None:
    app, db = _app(monkeypatch)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/repricer/rules",
            headers={"Authorization": "Bearer valid"},
            json=_rule_payload(),
        )

    assert response.status_code == 201
    assert response.json()["item_id"] == "MLA123"
    assert db.repricer_rules.docs[0]["seller_id"] == "123456789"


@pytest.mark.asyncio
async def test_below_floor_validation_error(monkeypatch: pytest.MonkeyPatch) -> None:
    app, _db = _app(monkeypatch)
    payload = _rule_payload(min_price="250", max_price="200")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/repricer/rules",
            headers={"Authorization": "Bearer valid"},
            json=payload,
        )

    assert response.status_code == 422
    assert response.json() == {"error": "min_price_above_max_price"}


@pytest.mark.asyncio
async def test_only_module_jwt_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    from zeler_platform_core.auth.jwt import InvalidJWTError

    app, _db = _app(monkeypatch, jwt_error=InvalidJWTError("bad token"))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/repricer/rules?seller_id=123456789", headers={"Authorization": "Bearer invalid"}
        )

    assert response.status_code == 401
    assert response.json() == {"error": "invalid_token", "detail": "bad token"}


def _app(
    monkeypatch: pytest.MonkeyPatch, jwt_error: Exception | None = None
) -> tuple[FastAPI, FakeDb]:
    import zeler_repricer.api as api
    from zeler_repricer.api import build_router

    db = FakeDb()
    app = FastAPI()
    app.state.mongo_db = db
    app.include_router(build_router())

    def fake_verify(_token: str) -> object:
        if jwt_error is not None:
            raise jwt_error
        return object()

    monkeypatch.setattr(api, "verify_module_jwt", fake_verify)
    return app, db


def _rule_payload(*, min_price: str = "100", max_price: str = "200") -> dict[str, Any]:
    return {
        "_id": "rule-1",
        "seller_id": "123456789",
        "item_id": "MLA123",
        "strategy": "competitive",
        "min_price": min_price,
        "max_price": max_price,
        "active": True,
        "updated_at": datetime(2026, 4, 24, 12, 0, tzinfo=UTC).isoformat(),
    }
