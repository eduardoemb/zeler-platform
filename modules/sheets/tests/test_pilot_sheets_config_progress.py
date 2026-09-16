"""ASGI progress retrieval with real Mongo and a stubbed JWT signature boundary."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, NoReturn
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from zeler_platform_core.auth.jwt import InvalidJWTError, ModuleClaims
from zeler_sheets import api
from zeler_sheets.extension_tokens import ExtensionTokenService, SellerScope
from zeler_sheets.formulas.dispatcher import FormulaDataUnavailableError, FormulaExecutionContext
from zeler_sheets.formulas.recovery import FormulaRecoveryQueue
from zeler_sheets.pilot_history_backfill import PLAN_COLLECTION, build_pilot_history_backfill

SELLER = "82453304"
OTHER_SELLER = "98765432"
NOW = datetime(2026, 9, 15, tzinfo=UTC)


@pytest_asyncio.fixture
async def progress_db() -> AsyncIterator[AsyncIOMotorDatabase[dict[str, Any]]]:
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        "mongodb://127.0.0.1:27028/?directConnection=true",
        tz_aware=True,
        serverSelectionTimeoutMS=2000,
    )
    database = client[f"zeler_progress_api_{uuid4().hex}"]
    hello = await client.admin.command("hello")
    assert hello["isWritablePrimary"] and hello["setName"] == "rs0"
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


@pytest.mark.asyncio
async def test_polling_real_callback_snapshot_cannot_duplicate_or_reset_jobs(
    monkeypatch: pytest.MonkeyPatch,
    progress_db: AsyncIOMotorDatabase[dict[str, Any]],
) -> None:
    queue = FormulaRecoveryQueue(progress_db, max_active_jobs_per_seller=4)
    callback = build_pilot_history_backfill(db=progress_db, recovery_queue=queue)
    assert await callback(SELLER)
    claimed = await queue.claim()
    assert claimed is not None
    assert await queue.finish(claimed, succeeded=False)
    terminal = await queue.collection.find_one({"_id": claimed["_id"]})
    await asyncio.gather(callback(SELLER), callback(SELLER))
    before = await queue.collection.find({}).sort("_id", 1).to_list(length=100)
    assert len(before) == 5
    app = _app(monkeypatch, progress_db)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        responses = await asyncio.gather(
            *(
                client.get(
                    "/sheets/backfill/progress",
                    params={"seller_id": SELLER},
                    headers={"Authorization": "Bearer valid"},
                )
                for _ in range(5)
            )
        )
    for response in responses:
        assert response.status_code == 200
        resources = response.json()["progress"]
        chunks = [chunk for resource in resources.values() for chunk in resource["chunks"]]
        assert len(chunks) == 48
        assert sum(chunk["state"] == "blocked" for chunk in chunks) == 24
        assert sum(chunk["state"] == "failed" for chunk in chunks) == 1
        assert sum(chunk["state"] == "queued" for chunk in chunks) == 4
        assert sum(chunk["state"] == "pending" for chunk in chunks) == 19
        assert all(chunk["state"] != "completed" for chunk in chunks)
    assert await queue.collection.find({}).sort("_id", 1).to_list(length=100) == before
    assert await queue.collection.find_one({"_id": claimed["_id"]}) == terminal


@pytest.mark.asyncio
async def test_repeated_formula_http_requests_coalesce_pending_and_running_recovery(
    progress_db: AsyncIOMotorDatabase[dict[str, Any]],
) -> None:
    async def unavailable(context: FormulaExecutionContext) -> NoReturn:
        raise FormulaDataUnavailableError(
            context.contract.name, read_model="orders", order_ids=("123",)
        )

    pepper = uuid4().hex
    issued = await ExtensionTokenService(
        db=progress_db, token_pepper=pepper, now_fn=lambda: NOW
    ).create_token(
        owner_user_id="local-test",
        label="local-test",
        seller_scopes=[SellerScope(seller_id=SELLER, nickname="LOCAL")],
    )
    queue = FormulaRecoveryQueue(progress_db, now=lambda: NOW)
    app = FastAPI()
    app.state.mongo_db = progress_db
    app.state.formula_recovery_queue = queue
    app.include_router(
        api.build_router(
            clock=lambda: NOW, extension_token_pepper=pepper, formula_dispatcher=unavailable
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:

        async def request() -> httpx.Response:
            return await client.post(
                "/sheets/formulas:execute",
                headers={"Authorization": "Bearer " + issued.token_once},
                json={
                    "formula": "ZELERDATA_SKU",
                    "cuenta": "LOCAL",
                    "args": {},
                    "request_id": uuid4().hex,
                },
            )

        for attempt_index in range(2):
            responses = await asyncio.gather(*(request() for _ in range(5)))
            for response in responses:
                assert response.status_code == 200
                body = response.json()
                assert body["ok"] is False
                assert body["error"]["code"] == "DATA_UNAVAILABLE"
                assert body["meta"]["recovery_requested"] is True
            assert await queue.collection.count_documents({"seller_id": SELLER}) == 1
            if attempt_index == 0:
                claimed = await queue.claim()
                assert claimed is not None
        assert claimed is not None
        persisted = await queue.collection.find_one({"_id": claimed["_id"]})
        assert persisted is not None
        assert persisted["state"] == "running" and persisted["attempts"] == 1
