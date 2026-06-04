from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from bson import encode as bson_encode
from bson.decimal128 import Decimal128
from fastapi import FastAPI


class FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs

    def sort(self, *_args: Any) -> FakeCursor:
        return self

    async def to_list(self, length: int) -> list[dict[str, Any]]:
        return self._docs[:length]


class FakeCollection:
    def __init__(self, docs: list[dict[str, Any]] | None = None) -> None:
        self.docs = docs or []

    def find(self, query: dict[str, Any]) -> FakeCursor:
        docs = [
            doc for doc in self.docs if all(doc.get(key) == value for key, value in query.items())
        ]
        return FakeCursor(docs)

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                return doc
        return None

    async def replace_one(
        self, query: dict[str, Any], replacement: dict[str, Any], *, upsert: bool
    ) -> None:
        assert upsert is True
        bson_encode(replacement)
        for index, doc in enumerate(self.docs):
            if all(doc.get(key) == value for key, value in query.items()):
                self.docs[index] = replacement
                return
        self.docs.append(replacement)

    async def insert_one(self, doc: dict[str, Any]) -> None:
        self.docs.append(doc)

    async def update_one(self, query: dict[str, Any], update: dict[str, Any]) -> None:
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                doc.update(update.get("$set", {}))
                return
        raise AssertionError(query)


class FakeDb:
    def __init__(self) -> None:
        self.sheets_exports = FakeCollection(
            [
                {
                    "_id": "export-123456789",
                    "seller_id": "123456789",
                    "spreadsheet_id": "sheet-old",
                    "worksheet_name": "Items",
                    "enabled": True,
                    "created_at": "2026-04-24T12:00:00+00:00",
                    "updated_at": "2026-04-24T12:00:00+00:00",
                    "schema_version": 1,
                }
            ]
        )
        self.sheets_sync_jobs = FakeCollection(
            [
                {
                    "_id": "sync-1",
                    "seller_id": "123456789",
                    "spreadsheet_id": "sheet-old",
                    "state": "succeeded",
                    "requested_at": "2026-04-24T12:05:00+00:00",
                    "updated_at": "2026-04-24T12:06:00+00:00",
                    "completed_at": "2026-04-24T12:06:00+00:00",
                    "error": None,
                    "schema_version": 1,
                }
            ]
        )
        self.seller_unit_costs = FakeCollection()

    def __getitem__(self, name: str) -> FakeCollection:
        if name == "sheets_exports":
            return self.sheets_exports
        if name == "sheets_sync_jobs":
            return self.sheets_sync_jobs
        if name == "seller_unit_costs":
            return self.seller_unit_costs
        raise AssertionError(name)


@pytest.mark.asyncio
async def test_list_export_config_and_last_sync_status(monkeypatch: pytest.MonkeyPatch) -> None:
    app, _db = _app(monkeypatch)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/sheets/exports?seller_id=123456789",
            headers={"Authorization": "Bearer valid"},
        )

    assert response.status_code == 200
    assert response.json() == [
        {
            "_id": "export-123456789",
            "seller_id": "123456789",
            "spreadsheet_id": "sheet-old",
            "worksheet_name": "Items",
            "enabled": True,
            "created_at": "2026-04-24T12:00:00+00:00",
            "updated_at": "2026-04-24T12:00:00+00:00",
            "schema_version": 1,
            "last_sync_state": "succeeded",
            "last_sync_updated_at": "2026-04-24T12:06:00+00:00",
        }
    ]


@pytest.mark.asyncio
async def test_configure_export_upserts_spreadsheet(monkeypatch: pytest.MonkeyPatch) -> None:
    app, db = _app(monkeypatch)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.put(
            "/sheets/exports/123456789",
            headers={"Authorization": "Bearer valid"},
            json={"spreadsheet_id": "sheet-new", "worksheet_name": "Orders", "enabled": False},
        )

    assert response.status_code == 200
    assert response.json()["spreadsheet_id"] == "sheet-new"
    assert response.json()["worksheet_name"] == "Orders"
    assert response.json()["enabled"] is False
    assert db.sheets_exports.docs[0]["_id"] == "export-123456789"
    assert db.sheets_exports.docs[0]["spreadsheet_id"] == "sheet-new"


@pytest.mark.asyncio
async def test_manual_sync_creates_pending_job_from_config(monkeypatch: pytest.MonkeyPatch) -> None:
    app, db = _app(monkeypatch)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/sheets/sync-jobs",
            headers={"Authorization": "Bearer valid"},
            json={"seller_id": "123456789"},
        )

    assert response.status_code == 201
    assert response.json()["seller_id"] == "123456789"
    assert response.json()["spreadsheet_id"] == "sheet-old"
    assert response.json()["state"] == "pending"
    assert response.json()["_id"].startswith("sheets-sync-123456789-")
    assert db.sheets_sync_jobs.docs[-1]["state"] == "pending"


@pytest.mark.asyncio
async def test_unit_cost_config_endpoints_are_seller_scoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, db = _app(monkeypatch)
    payload = {
        "normalized_sku": " sku-1 ",
        "unit_cost": "10.50",
        "currency": "ars",
        "source": "manual",
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        upsert = await client.put(
            "/sheets/unit-costs/123456789",
            headers={"Authorization": "Bearer valid"},
            json=payload,
        )
        listed = await client.get(
            "/sheets/unit-costs?seller_id=123456789",
            headers={"Authorization": "Bearer valid"},
        )
        deactivated = await client.post(
            f"/sheets/unit-costs/123456789/{upsert.json()['_id']}:deactivate",
            headers={"Authorization": "Bearer valid"},
        )

    assert upsert.status_code == 200
    assert upsert.json() == upsert.json() | {
        "seller_id": "123456789",
        "normalized_sku": "SKU-1",
        "unit_cost": 10.5,
        "currency": "ARS",
        "source": "manual",
        "status": "active",
    }
    assert listed.status_code == 200
    assert listed.json()[0]["_id"] == upsert.json()["_id"]
    assert isinstance(db.seller_unit_costs.docs[0]["unit_cost"], Decimal128)
    assert db.seller_unit_costs.docs[0]["unit_cost"].to_decimal().is_finite()
    assert deactivated.json()["status"] == "inactive"
    assert db.seller_unit_costs.docs[0]["status"] == "inactive"


@pytest.mark.asyncio
async def test_only_module_jwt_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    from zeler_platform_core.auth.jwt import InvalidJWTError

    app, _db = _app(monkeypatch, jwt_error=InvalidJWTError("bad token"))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/sheets/exports?seller_id=123456789",
            headers={"Authorization": "Bearer invalid"},
        )

    assert response.status_code == 401
    assert response.json() == {"error": "invalid_token", "detail": "bad token"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "claims_kwargs",
    [
        {"token_type": "module"},
        {"module_id": "repricer", "scopes": ["admin:repricer"]},
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
            "/sheets/exports?seller_id=123456789",
            headers={"Authorization": "Bearer invalid"},
        )

    assert response.status_code == 403
    assert response.json()["error"] == "forbidden"


def _app(
    monkeypatch: pytest.MonkeyPatch,
    jwt_error: Exception | None = None,
    claims: object | None = None,
) -> tuple[FastAPI, FakeDb]:
    import zeler_sheets.api as api
    from zeler_sheets.api import build_router

    db = FakeDb()
    app = FastAPI()
    app.state.mongo_db = db
    app.include_router(build_router(clock=lambda: datetime(2026, 4, 24, 12, 30, tzinfo=UTC)))

    def fake_verify(_token: str) -> object:
        if jwt_error is not None:
            raise jwt_error
        return claims or _claims()

    monkeypatch.setattr(api, "verify_module_jwt", fake_verify)
    return app, db


def _claims(**overrides: Any) -> object:
    from zeler_platform_core.auth.jwt import ModuleClaims

    module_id = str(overrides.pop("module_id", "sheets"))
    seller_id = int(overrides.pop("seller_id", 123456789))
    return ModuleClaims(
        module_id=module_id,
        seller_id=seller_id,
        iss=f"module:{module_id}",
        aud="gateway",
        iat=1,
        exp=2,
        token_type=str(overrides.pop("token_type", "module_admin")),
        scopes=list(overrides.pop("scopes", ["admin:sheets"])),
        issued_by="zeler-app",
    )
