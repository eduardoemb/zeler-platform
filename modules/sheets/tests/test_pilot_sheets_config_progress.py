"""ASGI progress retrieval with real Mongo and a stubbed JWT signature boundary."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from zeler_platform_core.auth.jwt import InvalidJWTError, ModuleClaims
from zeler_sheets import api
from zeler_sheets.pilot_history_backfill import PLAN_COLLECTION

SELLER = "82453304"
OTHER_SELLER = "98765432"
NOW = datetime(2026, 9, 15, tzinfo=UTC)


@pytest_asyncio.fixture
async def progress_db(
    default_mongo_uri: str,
) -> AsyncIterator[AsyncIOMotorDatabase[dict[str, Any]]]:
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        default_mongo_uri, tz_aware=True, serverSelectionTimeoutMS=2000
    )
    database = client[f"zeler_progress_api_{uuid4().hex}"]
    await client.admin.command("ping")
    try:
        yield database
    finally:
        await client.drop_database(database.name)
        client.close()


def _app(monkeypatch: pytest.MonkeyPatch, database: object) -> FastAPI:
    def verify(scenario: str) -> ModuleClaims:
        if scenario == "invalid":
            raise InvalidJWTError("invalid test signature")
        return ModuleClaims(
            module_id="repricer" if scenario == "wrong-module" else "sheets",
            seller_id=int(OTHER_SELLER if scenario == "foreign-seller" else SELLER),
            iss="module:sheets",
            aud="gateway",
            iat=1,
            exp=2,
            token_type="module" if scenario == "wrong-type" else "module_admin",
            scopes=["read:sheets"] if scenario == "wrong-scope" else ["admin:sheets"],
            issued_by="zeler-app",
        )

    monkeypatch.setattr(api, "verify_module_jwt", verify)
    app = FastAPI()
    app.state.mongo_db = database
    app.include_router(api.build_router())
    return app


@pytest.mark.asyncio
@pytest.mark.parametrize("has_plan", [True, False])
async def test_progress_reads_only_authorized_seller_plan(
    monkeypatch: pytest.MonkeyPatch,
    progress_db: AsyncIOMotorDatabase[dict[str, Any]],
    has_plan: bool,
) -> None:
    progress = {"orders": {"completed": 10, "failed": 1, "pending": 1, "admitted_this_cycle": 1}}
    await progress_db[PLAN_COLLECTION].insert_one(
        {
            "_id": OTHER_SELLER,
            "seller_id": OTHER_SELLER,
            "cutoff": NOW,
            "progress": {"orders": {"completed": 99}},
            "updated_at": NOW,
        }
    )
    if has_plan:
        await progress_db[PLAN_COLLECTION].insert_one(
            {
                "_id": SELLER,
                "seller_id": SELLER,
                "cutoff": NOW,
                "progress": progress,
                "updated_at": NOW,
                "schema_version": 1,
            }
        )
    app = _app(monkeypatch, progress_db)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/sheets/backfill/progress",
            params={"seller_id": SELLER},
            headers={"Authorization": "Bearer valid"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "seller_id": SELLER,
        "cutoff": NOW.isoformat() if has_plan else None,
        "progress": progress if has_plan else None,
        "updated_at": NOW.isoformat() if has_plan else None,
    }
    assert await progress_db[PLAN_COLLECTION].count_documents({}) == 1 + int(has_plan)
    other = await progress_db[PLAN_COLLECTION].find_one({"_id": OTHER_SELLER})
    assert other is not None
    assert other["progress"] == {"orders": {"completed": 99}}


class ForbiddenDatabase:
    def __getitem__(self, collection: str) -> Any:
        raise AssertionError(f"unauthorized database access: {collection}")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("token", "status", "detail"),
    [
        (None, 401, "missing bearer token"),
        ("invalid", 401, "invalid test signature"),
        ("foreign-seller", 403, "JWT seller_id must match request seller_id"),
        ("wrong-scope", 403, "JWT scopes must include admin:sheets"),
        ("wrong-module", 403, "JWT module_id must be sheets"),
        ("wrong-type", 403, "JWT token_type must be module_admin"),
    ],
)
async def test_progress_rejects_unauthorized_before_database_access(
    monkeypatch: pytest.MonkeyPatch, token: str | None, status: int, detail: str
) -> None:
    app = _app(monkeypatch, ForbiddenDatabase())
    headers = {} if token is None else {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/sheets/backfill/progress", params={"seller_id": SELLER}, headers=headers
        )

    assert response.status_code == status
    assert response.json() == {
        "error": "invalid_token" if status == 401 else "forbidden",
        "detail": detail,
    }
