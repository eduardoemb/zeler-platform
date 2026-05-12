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
        self.repricer_history = FakeCollection()

    def __getitem__(self, name: str) -> FakeCollection:
        if name == "repricer_rules":
            return self.repricer_rules
        if name == "repricer_history":
            return self.repricer_history
        raise AssertionError(name)


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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "claims_kwargs",
    [
        {"token_type": "module"},
        {"module_id": "sheets", "scopes": ["admin:sheets"]},
        {"seller_id": 987654321},
        {"scopes": []},
    ],
    ids=["wrong-token-type", "wrong-module", "wrong-seller", "missing-scope"],
)
async def test_module_admin_claims_enforced(
    monkeypatch: pytest.MonkeyPatch, claims_kwargs: dict[str, Any]
) -> None:
    app, _db = _app(monkeypatch, claims=_claims(**claims_kwargs))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/repricer/rules?seller_id=123456789", headers={"Authorization": "Bearer invalid"}
        )

    assert response.status_code == 403
    assert response.json()["error"] == "forbidden"


@pytest.mark.asyncio
async def test_list_history_returns_latest_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    app, db = _app(monkeypatch)
    db.repricer_history.docs.append(
        {
            "seller_id": "123456789",
            "item_id": "MLA123",
            "old_price": "150.00",
            "new_price": "149.00",
            "reason": "competition_match",
            "applied_at": datetime(2026, 4, 24, 12, 30, tzinfo=UTC).isoformat(),
        }
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/repricer/history?seller_id=123456789", headers={"Authorization": "Bearer valid"}
        )

    assert response.status_code == 200
    assert response.json() == [
        {
            "seller_id": "123456789",
            "item_id": "MLA123",
            "old_price": "150.00",
            "new_price": "149.00",
            "reason": "competition_match",
            "applied_at": "2026-04-24T12:30:00+00:00",
        }
    ]


def _app(
    monkeypatch: pytest.MonkeyPatch,
    jwt_error: Exception | None = None,
    claims: object | None = None,
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
        return claims or _claims()

    monkeypatch.setattr(api, "verify_module_jwt", fake_verify)
    return app, db


def _claims(**overrides: Any) -> object:
    from zeler_platform_core.auth.jwt import ModuleClaims

    module_id = str(overrides.pop("module_id", "repricer"))
    seller_id = int(overrides.pop("seller_id", 123456789))
    return ModuleClaims(
        module_id=module_id,
        seller_id=seller_id,
        iss=f"module:{module_id}",
        aud="gateway",
        iat=1,
        exp=2,
        token_type=str(overrides.pop("token_type", "module_admin")),
        scopes=list(overrides.pop("scopes", ["admin:repricer"])),
        issued_by="zeler-app",
    )


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
