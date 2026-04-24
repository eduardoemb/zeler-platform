from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
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
        for index, doc in enumerate(self.docs):
            if all(doc.get(key) == value for key, value in query.items()):
                self.docs[index] = replacement
                return
        self.docs.append(replacement)

    async def insert_one(self, doc: dict[str, Any]) -> None:
        self.docs.append(doc)


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

    def __getitem__(self, name: str) -> FakeCollection:
        if name == "sheets_exports":
            return self.sheets_exports
        if name == "sheets_sync_jobs":
            return self.sheets_sync_jobs
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


def _app(
    monkeypatch: pytest.MonkeyPatch, jwt_error: Exception | None = None
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
        return object()

    monkeypatch.setattr(api, "verify_module_jwt", fake_verify)
    return app, db
