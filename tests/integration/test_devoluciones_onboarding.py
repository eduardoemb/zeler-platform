"""Exact onboarding gates against a dedicated disposable loopback replica set.

No production URI is accepted. The fixture never calls Mercado Libre.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio

from zeler_platform_core.devoluciones_certificates import (
    CERTIFICATES,
    CoverageUnavailableError,
    select_covering_proofs,
)
from zeler_sheets.devoluciones_runner import (
    ONBOARDING_PLANS_COLLECTION,
    admit_onboarding_devoluciones,
    advance_onboarding_devoluciones,
)


@pytest_asyncio.fixture
async def onboarding_claims_db() -> AsyncIterator[Any]:
    from motor.motor_asyncio import AsyncIOMotorClient

    client: Any = AsyncIOMotorClient(
        "mongodb://127.0.0.1:27028/?directConnection=true",
        tz_aware=True,
        serverSelectionTimeoutMS=1000,
    )
    hello = await client.admin.command("hello")
    assert hello["isWritablePrimary"] is True and hello["setName"] == "rs0"
    name = "zeler_onboarding_claims_" + uuid4().hex
    db = client[name]
    try:
        for collection in (
            "sheets_devoluciones_operations",
            "sheets_devoluciones_runs",
            "sheets_devoluciones_run_windows",
            CERTIFICATES,
        ):
            schema = json.loads(
                (
                    Path(__file__).resolve().parents[2]
                    / "infra/mongo/schemas"
                    / f"{collection}.json"
                ).read_text()
            )
            await db.create_collection(
                collection,
                validator={"$jsonSchema": schema["$jsonSchema"]},
                validationLevel="strict",
                validationAction="error",
            )
        yield db
    finally:
        await client.drop_database(name)
        client.close()


async def seed_plan(db: Any, seller: str = "999") -> dict[str, Any]:
    now = datetime.now(UTC)
    now = now.replace(microsecond=now.microsecond // 1000 * 1000)
    document = {
        "_id": seller,
        "seller_id": seller,
        "state": "active",
        "eligible": True,
        "policy_version": "history-on-link-v1",
        "authority": {"kind": "account_link_policy"},
        "date_from": datetime(2025, 10, 3, tzinfo=UTC),
        "date_to": now,
        "cutoff": now,
        "sources": ["claims_returns"],
        "budget": {"claims_returns": {"physical_attempts": 20000, "consumed": 0}},
        "incremental_policy": {"max_daily_total": 2000, "max_daily_source": 1000},
    }
    await db[ONBOARDING_PLANS_COLLECTION].insert_one(document)
    return document


class EmptyGateway:
    def __init__(self) -> None:
        self.attempts = 0

    async def fetch_resource_once(self, **kwargs: Any) -> dict[str, Any]:
        self.attempts += 1
        assert kwargs["seller_id"] == "999"
        assert kwargs["path"].startswith("/post-purchase/v1/claims/search?")
        return {"data": [], "paging": {"offset": 0, "limit": 100, "total": 0}}


def charge_for(db: Any, plan: Any) -> Any:
    async def charge() -> None:
        await db[ONBOARDING_PLANS_COLLECTION].update_one(
            {"_id": plan["_id"]}, {"$inc": {"budget.claims_returns.consumed": 1}}
        )

    return charge


async def acquire_unit(db: Any, plan: Any, start: datetime, gateway: Any) -> Any:
    end = start + timedelta(days=10)
    first = await advance_onboarding_devoluciones(
        db,
        plan,
        start=start,
        end=end,
        gateway=gateway,
        charge=charge_for(db, plan),
    )
    assert first["state"] == "active" and first["advanced"] == 1
    # Model the next due cadence without waiting 12 real minutes.
    await db.sheets_devoluciones_runs.update_one(
        {"_id": first["run_id"]}, {"$set": {"not_before": datetime.now(UTC)}}
    )
    finalized = await advance_onboarding_devoluciones(
        db,
        plan,
        start=start,
        end=end,
        gateway=gateway,
        charge=charge_for(db, plan),
    )
    assert finalized["state"] == "completed" and finalized["finalized"] == 1
    return finalized


@pytest.mark.asyncio
async def test_empty_account_admission_is_idempotent_and_real_transactional(
    onboarding_claims_db: Any,
) -> None:
    db = onboarding_claims_db
    plan = await seed_plan(db)
    run_id = await admit_onboarding_devoluciones(db, plan)
    assert await admit_onboarding_devoluciones(db, plan) == run_id
    assert await db.sheets_devoluciones_runs.count_documents({}) == 1
    control = await db.sheets_devoluciones_operations.find_one({"seller_id": "999"})
    assert control["coverage_mode"] == "active"
    assert control["coverage_ack_fence"] == control["fence"]
    assert await db[CERTIFICATES].count_documents({}) == 0
    assert await db.sheets_read_model_freshness.count_documents({}) == 0


@pytest.mark.asyncio
async def test_two_real_exact_runs_preserve_june_and_reject_the_gap(
    onboarding_claims_db: Any,
) -> None:
    db = onboarding_claims_db
    plan = await seed_plan(db)
    gateway = EmptyGateway()
    june = datetime(2026, 6, 1, tzinfo=UTC)
    august = datetime(2026, 8, 1, tzinfo=UTC)
    await acquire_unit(db, plan, june, gateway)
    before = await select_covering_proofs(
        db, "999", june, june + timedelta(days=10), datetime.now(UTC)
    )
    await acquire_unit(db, plan, august, gateway)
    after = await select_covering_proofs(
        db, "999", june, june + timedelta(days=10), datetime.now(UTC)
    )
    assert len(before.proofs) == len(after.proofs) == 1
    assert await db[CERTIFICATES].count_documents({"state": "reconciled"}) == 2
    assert gateway.attempts > 1
    latest = await db[ONBOARDING_PLANS_COLLECTION].find_one({"_id": "999"})
    assert latest["budget"]["claims_returns"]["consumed"] == gateway.attempts
    with pytest.raises(CoverageUnavailableError):
        await select_covering_proofs(
            db, "999", june, august + timedelta(days=10), datetime.now(UTC)
        )


@pytest.mark.asyncio
async def test_failed_exact_unit_does_not_poison_next_unit(onboarding_claims_db: Any) -> None:
    db = onboarding_claims_db
    plan = await seed_plan(db)
    start = datetime(2026, 6, 1, tzinfo=UTC)

    class MissingDetail:
        async def fetch_resource_once(self, **_: Any) -> Any:
            raise RuntimeError("fixture source missing")

    failed = await advance_onboarding_devoluciones(
        db,
        plan,
        start=start,
        end=start + timedelta(days=10),
        gateway=MissingDetail(),
        charge=charge_for(db, plan),
    )
    assert failed["state"] == "failed"
    assert await db[CERTIFICATES].count_documents({}) == 0
    await acquire_unit(db, plan, start + timedelta(days=10), EmptyGateway())
    assert await db[CERTIFICATES].count_documents({}) == 1
    with pytest.raises(CoverageUnavailableError):
        await select_covering_proofs(
            db, "999", start, start + timedelta(days=20), datetime.now(UTC)
        )


@pytest.mark.asyncio
async def test_real_legacy_marker_requires_explicit_migration(onboarding_claims_db: Any) -> None:
    db = onboarding_claims_db
    plan = await seed_plan(db)
    await db.sheets_read_model_freshness.insert_one(
        {
            "_id": "999:devoluciones",
            "seller_id": "999",
            "read_model": "devoluciones",
            "state": "reconciled",
            "revision": "legacy-genuine",
        }
    )
    with pytest.raises(ValueError, match="migration"):
        await admit_onboarding_devoluciones(db, plan)
    assert await db[CERTIFICATES].count_documents({}) == 0
    assert await db.sheets_devoluciones_operations.count_documents({}) == 0
    marker = await db.sheets_read_model_freshness.find_one({"_id": "999:devoluciones"})
    assert marker["revision"] == "legacy-genuine"


@pytest.mark.asyncio
async def test_initial_cutoff_is_not_widened_by_incremental_admission(
    onboarding_claims_db: Any,
) -> None:
    db = onboarding_claims_db
    plan = await seed_plan(db)
    cutoff = plan["cutoff"] - timedelta(hours=2)
    plan["date_to"] = plan["cutoff"] = cutoff
    start, end = cutoff - timedelta(minutes=5), cutoff + timedelta(hours=1)
    plan["incremental_scopes"] = {
        "claims_returns": {
            "date_from": start,
            "date_to": end,
            "policy_version": "history-on-link-v1",
        }
    }
    await db[ONBOARDING_PLANS_COLLECTION].replace_one({"_id": "999"}, plan)
    gateway = EmptyGateway()
    result = await advance_onboarding_devoluciones(
        db,
        plan,
        start=start,
        end=end,
        gateway=gateway,
        charge=charge_for(db, plan),
    )
    assert result["state"] == "active" and result["advanced"] == 1
    stored = await db[ONBOARDING_PLANS_COLLECTION].find_one({"_id": "999"})
    assert stored["date_to"] == stored["cutoff"] == cutoff
    await db[ONBOARDING_PLANS_COLLECTION].update_one(
        {"_id": "999"}, {"$unset": {"incremental_scopes": ""}}
    )
    with pytest.raises(ValueError):
        await admit_onboarding_devoluciones(db, plan, start=start, end=end)


@pytest.mark.asyncio
async def test_hydration_volume_returns_bounded_subdivision_reason(
    onboarding_claims_db: Any,
) -> None:
    db = onboarding_claims_db
    plan = await seed_plan(db)
    start, end = datetime(2026, 6, 1, tzinfo=UTC), datetime(2026, 6, 11, tzinfo=UTC)

    class DenseInventory:
        async def fetch_resource_once(self, **kwargs: Any) -> dict[str, Any]:
            assert "/claims/search?" in kwargs["path"], "capacity rejects before hydration"
            rows = [
                {
                    "id": str(1000 + i),
                    "type": "returns",
                    "status": "closed",
                    "date_created": "2026-06-02T00:00:00.000Z",
                    "last_updated": "2026-06-02T00:00:00.000Z",
                }
                for i in range(35)
            ]
            return {"data": rows, "paging": {"offset": 0, "limit": 100, "total": 35}}

    result = await advance_onboarding_devoluciones(
        db,
        plan,
        start=start,
        end=end,
        gateway=DenseInventory(),
        charge=charge_for(db, plan),
    )
    assert result["state"] == "failed"
    assert result["reason"] == "physical_budget_exceeded"
    assert await db[CERTIFICATES].count_documents({}) == 0


@pytest.mark.asyncio
async def test_finalization_requires_no_extra_physical_budget(onboarding_claims_db: Any) -> None:
    db = onboarding_claims_db
    plan = await seed_plan(db)
    gateway = EmptyGateway()
    start = datetime(2026, 6, 1, tzinfo=UTC)
    first = await advance_onboarding_devoluciones(
        db,
        plan,
        start=start,
        end=start + timedelta(days=10),
        gateway=gateway,
        charge=charge_for(db, plan),
    )
    assert first["state"] == "active"
    sends = gateway.attempts
    await db[ONBOARDING_PLANS_COLLECTION].update_one(
        {"_id": "999"}, {"$set": {"budget.claims_returns.consumed": 20000}}
    )
    await db.sheets_devoluciones_runs.update_one(
        {"_id": first["run_id"]}, {"$set": {"not_before": datetime.now(UTC)}}
    )
    result = await advance_onboarding_devoluciones(
        db,
        plan,
        start=start,
        end=start + timedelta(days=10),
        gateway=gateway,
        charge=charge_for(db, plan),
    )
    assert result["state"] == "completed" and gateway.attempts == sends


@pytest.mark.asyncio
async def test_bootstrap_facts_without_any_proof_do_not_block_initial_admission(
    onboarding_claims_db: Any,
) -> None:
    db = onboarding_claims_db
    plan = await seed_plan(db)
    baseline = {"_id": "bootstrap-claim", "seller_id": "999", "type": "returns", "status": "open"}
    await db.claims.insert_one(baseline)
    await admit_onboarding_devoluciones(db, plan)
    assert await db.claims.find_one({"_id": "bootstrap-claim"}) == baseline
    assert await db[CERTIFICATES].count_documents({}) == 0
    with pytest.raises(CoverageUnavailableError):
        await select_covering_proofs(
            db,
            "999",
            datetime(2026, 6, 1, tzinfo=UTC),
            datetime(2026, 6, 11, tzinfo=UTC),
            datetime.now(UTC),
        )


@pytest.mark.asyncio
async def test_standing_incremental_charge_works_after_initial_budget_is_spent(
    onboarding_claims_db: Any,
) -> None:
    from zeler_sheets.history_onboarding import PlanBudgetGateway

    db = onboarding_claims_db
    plan = await seed_plan(db)
    cutoff = plan["cutoff"] - timedelta(hours=2)
    start, end = cutoff - timedelta(minutes=5), cutoff + timedelta(hours=1)
    plan["date_to"] = plan["cutoff"] = cutoff
    plan["budget"]["claims_returns"]["consumed"] = 20000
    plan["total_budget"] = plan["total_consumed"] = 100000
    plan["incremental_scopes"] = {
        "claims_returns": {
            "date_from": start,
            "date_to": end,
            "policy_version": "history-on-link-v1",
        }
    }
    await db[ONBOARDING_PLANS_COLLECTION].replace_one({"_id": "999"}, plan)
    await db.meli_accounts.insert_one({"_id": "999", "seller_id": "999", "status": "active"})
    source = EmptyGateway()
    gateway = PlanBudgetGateway(db, source, "999", "claims_returns")
    gateway.incremental = True
    first = await advance_onboarding_devoluciones(db, plan, start=start, end=end, gateway=gateway)
    assert first["state"] == "active" and first["advanced"] == 1
    stored = await db[ONBOARDING_PLANS_COLLECTION].find_one({"_id": "999"})
    assert stored["budget"]["claims_returns"]["consumed"] == 20000
    assert stored["total_consumed"] == 100000
    assert stored["incremental_source_consumed"]["claims_returns"] == source.attempts
    assert stored["incremental_consumed"] == source.attempts > 0
    await db.sheets_devoluciones_runs.update_one(
        {"_id": first["run_id"]}, {"$set": {"not_before": datetime.now(UTC)}}
    )
    final = await advance_onboarding_devoluciones(db, plan, start=start, end=end, gateway=gateway)
    assert final["state"] == "completed"
    assert await db[CERTIFICATES].count_documents({}) == 1
