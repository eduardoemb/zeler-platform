from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from infra.mongo.apply_validators import apply_validators
from infra.operations import devoluciones_quota_advance as advance
from infra.operations.zelerdata_read_model_reconcile import execute_devoluciones_quota_window
from motor.motor_asyncio import AsyncIOMotorClient

from zeler_platform_core.devoluciones_readiness import (
    acquire_devoluciones_operation,
    finish_devoluciones_operation,
)
from zeler_platform_core.devoluciones_runs import MongoRunWindowRepository, RunBinding


@pytest_asyncio.fixture
async def database(tmp_path: Path) -> AsyncIterator[Any]:
    name = f"zeler_returns_authority_{uuid4().hex}"
    uri = f"mongodb://127.0.0.1:27028/{name}?directConnection=true"
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(uri, tz_aware=True)
    hello = await client.admin.command("hello")
    assert hello["isWritablePrimary"] and hello["setName"] == "rs0"
    root = Path(__file__).resolve().parents[3] / "infra/mongo"
    for directory in ("schemas", "indexes"):
        (tmp_path / directory).mkdir()
        for collection in (
            "sheets_devoluciones_runs",
            "sheets_devoluciones_run_windows",
            "sheets_devoluciones_operations",
            "sheets_read_model_freshness",
            "claims",
            "orders",
        ):
            source = root / directory / f"{collection}.json"
            if source.exists():
                (tmp_path / directory / source.name).write_text(source.read_text())
    try:
        await asyncio.to_thread(apply_validators, uri, tmp_path / "schemas")
        yield client[name]
    finally:
        await client.drop_database(name)
        client.close()


async def authorized(database: Any, seller: str = "82453304") -> str:
    operation = await acquire_devoluciones_operation(
        db=database,
        seller_id=seller,
        scope="devoluciones",
        operation_id=uuid4().hex,
        attempt_token=uuid4().hex,
    )
    binding = RunBinding(
        "test-authorization",
        uuid4().hex,
        seller,
        "devoluciones",
        datetime(2026, 6, 1, tzinfo=UTC),
        datetime(2026, 6, 2, tzinfo=UTC),
        "v1",
        {"sheets": "test-release"},
    )
    assert await MongoRunWindowRepository(database).create(binding, operation=operation)
    await finish_devoluciones_operation(db=database, operation=operation, succeeded=True)
    return binding.run_id


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["expired", "not_due", "authorization"])
async def test_invalid_authority_does_not_acquire_or_invalidate(
    database: Any, invalid: str
) -> None:
    run_id = await authorized(database)
    now = datetime.now(UTC)
    changes: dict[str, Any] = {"expires_at": now - timedelta(seconds=1)}
    if invalid == "not_due":
        changes = {"not_before": now + timedelta(hours=1)}
    if invalid == "authorization":
        changes = {"authorization_id": ""}
    await database.sheets_devoluciones_runs.update_one({"_id": run_id}, {"$set": changes})
    before_operation = await database.sheets_devoluciones_operations.find_one({})
    before_marker = await database.sheets_read_model_freshness.find_one({})
    assert await advance.advance_authorized_quota_run(db=database, run_id=run_id) == {
        "advanced": 0,
        "finalized": 0,
    }
    assert await database.sheets_devoluciones_operations.find_one({}) == before_operation
    assert await database.sheets_read_model_freshness.find_one({}) == before_marker


class EmptySource:
    def __init__(self, database: Any, *, lose_lease: bool = False, fail: bool = False) -> None:
        self.database, self.lose_lease, self.fail = database, lose_lease, fail
        self.calls = 0

    async def search_claims(self, *, seller_id: str, params: Mapping[str, Any]) -> dict[str, Any]:
        self.calls += 1
        assert seller_id == "82453304"
        if self.fail:
            raise RuntimeError("source unavailable")
        if self.lose_lease:
            await self.database.sheets_devoluciones_operations.update_one(
                {"seller_id": seller_id},
                {"$set": {"lease_until": datetime(2000, 1, 1, tzinfo=UTC)}},
            )
        return {
            "paging": {"offset": params["offset"], "limit": params["limit"], "total": 0},
            "data": [],
        }


def use_source(monkeypatch: pytest.MonkeyPatch, source: EmptySource) -> None:
    async def execute(**kwargs: Any) -> dict[str, Any]:
        return await execute_devoluciones_quota_window(**kwargs, source=source)

    monkeypatch.setattr(advance, "execute_devoluciones_quota_window", execute)


@pytest.mark.asyncio
async def test_authorized_window_uses_real_source_readback_and_finalization(
    database: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = await authorized(database)
    source = EmptySource(database)
    use_source(monkeypatch, source)
    first = await advance.advance_authorized_quota_run(db=database, run_id=run_id)
    assert first == {"advanced": 1, "finalized": 0} and source.calls >= 2
    window = await database.sheets_devoluciones_run_windows.find_one({"run_id": run_id})
    assert (
        window["state"] == "completed" and window["expected_count"] == window["complete_count"] == 0
    )
    final = await advance.advance_authorized_quota_run(
        db=database, run_id=run_id, now=lambda: datetime.now(UTC) + timedelta(minutes=13)
    )
    assert final == {"advanced": 0, "finalized": 1}
    marker = await database.sheets_read_model_freshness.find_one({"_id": "82453304:devoluciones"})
    assert marker["state"] == "reconciled" and marker["revision"] == run_id


@pytest.mark.asyncio
@pytest.mark.parametrize("lease_loss", [True, False])
async def test_lease_or_source_failure_never_finalizes(
    database: Any, monkeypatch: pytest.MonkeyPatch, lease_loss: bool
) -> None:
    run_id = await authorized(database)
    use_source(monkeypatch, EmptySource(database, lose_lease=lease_loss, fail=not lease_loss))
    with pytest.raises(RuntimeError):
        await advance.advance_authorized_quota_run(db=database, run_id=run_id)
    assert await database.sheets_read_model_freshness.count_documents({"state": "reconciled"}) == 0
    assert await database.sheets_devoluciones_runs.count_documents({"state": "completed"}) == 0


@pytest.mark.asyncio
async def test_bounded_batch_isolates_foreign_seller_without_authorizing_it(
    database: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    foreign = await authorized(database, "123")
    pilot = await authorized(database)
    use_source(monkeypatch, EmptySource(database))
    before = await database.sheets_devoluciones_operations.find_one({"seller_id": "123"})
    outcomes = await advance.advance_authorized_quota_runs(db=database, run_ids=[foreign, pilot])
    assert outcomes[0]["status"] == "failed" and outcomes[1]["advanced"] == 1
    assert await database.sheets_devoluciones_operations.find_one({"seller_id": "123"}) == before
    with pytest.raises(ValueError):
        await advance.advance_authorized_quota_runs(db=database, run_ids=[pilot] * 8)
