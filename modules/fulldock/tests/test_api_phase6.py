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
        self.fulldock_inventory_rules = FakeCollection(
            [
                {
                    "_id": "rule-1",
                    "seller_id": "123456789",
                    "item_id": "MLA1",
                    "enabled": True,
                    "stock_locations": [{"location_id": "AR-FULL-1", "quantity": 5}],
                    "created_at": "2026-04-24T14:00:00+00:00",
                    "updated_at": "2026-04-24T14:00:00+00:00",
                    "schema_version": 1,
                }
            ]
        )
        self.fulldock_history = FakeCollection(
            [
                {
                    "_id": "history-1",
                    "seller_id": "123456789",
                    "event_id": "event-1",
                    "idempotency_key": "idem-1",
                    "item_id": "MLA1",
                    "outcome": "updated",
                    "created_at": "2026-04-24T14:30:00+00:00",
                    "schema_version": 1,
                }
            ]
        )

    def __getitem__(self, name: str) -> FakeCollection:
        if name == "fulldock_inventory_rules":
            return self.fulldock_inventory_rules
        if name == "fulldock_history":
            return self.fulldock_history
        raise AssertionError(name)


@pytest.mark.asyncio
async def test_list_rules_includes_history(monkeypatch: pytest.MonkeyPatch) -> None:
    app, _db = _app(monkeypatch)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/fulldock/inventory-rules?seller_id=123456789",
            headers={"Authorization": "Bearer valid"},
        )

    assert response.status_code == 200
    assert response.json()[0]["item_id"] == "MLA1"
    assert response.json()[0]["recent_history"][0]["outcome"] == "updated"


@pytest.mark.asyncio
async def test_create_rule_persists_stock_locations(monkeypatch: pytest.MonkeyPatch) -> None:
    app, db = _app(monkeypatch)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/fulldock/inventory-rules",
            headers={"Authorization": "Bearer valid"},
            json={
                "seller_id": "123456789",
                "item_id": "MLA2",
                "enabled": True,
                "stock_locations": [{"location_id": "AR-FULL-2", "quantity": 9}],
            },
        )

    assert response.status_code == 201
    assert response.json()["item_id"] == "MLA2"
    assert db.fulldock_inventory_rules.docs[-1]["stock_locations"] == [
        {"location_id": "AR-FULL-2", "quantity": 9}
    ]


@pytest.mark.asyncio
async def test_update_rule_replaces_existing(monkeypatch: pytest.MonkeyPatch) -> None:
    app, db = _app(monkeypatch)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.patch(
            "/fulldock/inventory-rules/rule-1",
            headers={"Authorization": "Bearer valid"},
            json={
                "enabled": False,
                "stock_locations": [{"location_id": "AR-FULL-1", "quantity": 2}],
            },
        )

    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert db.fulldock_inventory_rules.docs[0]["stock_locations"][0]["quantity"] == 2


@pytest.mark.asyncio
async def test_only_module_jwt_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    from zeler_platform_core.auth.jwt import InvalidJWTError

    app, _db = _app(monkeypatch, jwt_error=InvalidJWTError("bad token"))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/fulldock/inventory-rules?seller_id=123456789",
            headers={"Authorization": "Bearer invalid"},
        )

    assert response.status_code == 401
    assert response.json() == {"error": "invalid_token", "detail": "bad token"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "claims_kwargs",
    [
        {"token_type": "module"},
        {"module_id": "autoreply", "scopes": ["admin:autoreply"]},
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
            "/fulldock/inventory-rules?seller_id=123456789",
            headers={"Authorization": "Bearer invalid"},
        )

    assert response.status_code == 403
    assert response.json()["error"] == "forbidden"


def _app(
    monkeypatch: pytest.MonkeyPatch,
    jwt_error: Exception | None = None,
    claims: object | None = None,
) -> tuple[FastAPI, FakeDb]:
    import zeler_fulldock.api as api
    from zeler_fulldock.api import build_router

    db = FakeDb()
    app = FastAPI()
    app.state.mongo_db = db
    app.include_router(build_router(clock=lambda: datetime(2026, 4, 24, 14, 30, tzinfo=UTC)))

    def fake_verify(_token: str) -> object:
        if jwt_error is not None:
            raise jwt_error
        return claims or _claims()

    monkeypatch.setattr(api, "verify_module_jwt", fake_verify)
    return app, db


def _claims(**overrides: Any) -> object:
    from zeler_platform_core.auth.jwt import ModuleClaims

    module_id = str(overrides.pop("module_id", "fulldock"))
    seller_id = int(overrides.pop("seller_id", 123456789))
    return ModuleClaims(
        module_id=module_id,
        seller_id=seller_id,
        iss=f"module:{module_id}",
        aud="gateway",
        iat=1,
        exp=2,
        token_type=str(overrides.pop("token_type", "module_admin")),
        scopes=list(overrides.pop("scopes", ["admin:fulldock"])),
        issued_by="zeler-app",
    )
