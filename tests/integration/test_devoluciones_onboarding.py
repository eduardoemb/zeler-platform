"""Exact onboarding gates against a dedicated disposable loopback replica set.

No production URI is accepted. The fixture never calls Mercado Libre.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace
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
    ORDINARY_TAIL_AUTHORIZATION,
    admit_onboarding_devoluciones,
    advance_due_devoluciones_run,
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


@pytest.mark.asyncio
async def test_paused_pilot_coverage_is_extended_by_the_ordinary_tail(
    onboarding_claims_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from infra.operations import zelerdata_read_model_reconcile as reconcile

    db = onboarding_claims_db
    plan = await seed_plan(db)
    today = datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)
    start = today - timedelta(days=12)
    await acquire_unit(db, plan, start, EmptyGateway())
    await db[ONBOARDING_PLANS_COLLECTION].update_one({"_id": "999"}, {"$set": {"state": "paused"}})
    charged = (await db[ONBOARDING_PLANS_COLLECTION].find_one({"_id": "999"}))["budget"]
    source = EmptyGateway()
    monkeypatch.setattr(
        reconcile,
        "create_runtime_historical_meli_gateways",
        lambda: SimpleNamespace(order_detail_gateway=source),
    )

    assert await advance_due_devoluciones_run(db, "999", history_work_enabled=False) is True

    tail = await db.sheets_devoluciones_runs.find_one(
        {"authorization_id": ORDINARY_TAIL_AUTHORIZATION}
    )
    assert tail is not None and tail["state"] == "completed"
    assert tail["start"] == start + timedelta(days=10)
    assert source.attempts > 0
    now = datetime.now(UTC)
    settled = datetime.combine((now - timedelta(hours=1)).date(), time.min, tzinfo=UTC)
    assert tail["end"] == settled
    covering = await select_covering_proofs(db, "999", start, settled, now)
    assert len(covering.proofs) == 2
    # The paused plan is never charged for ordinary work.
    stored = await db[ONBOARDING_PLANS_COLLECTION].find_one({"_id": "999"})
    assert stored["budget"] == charged and stored["state"] == "paused"
    # Coverage now reaches the settled midnight: nothing else is due today.
    assert await advance_due_devoluciones_run(db, "999", history_work_enabled=False) is False
    assert (
        await db.sheets_devoluciones_runs.count_documents(
            {"authorization_id": ORDINARY_TAIL_AUTHORIZATION}
        )
        == 1
    )


QUARANTINE = "sheets_devoluciones_claim_quarantine"


def legacy_claim(claim_id: str, created: datetime, seller: str = "999") -> dict[str, Any]:
    # Pre-v2 projection: no productive flag, return basis or source version.
    return {
        "_id": claim_id,
        "seller_id": seller,
        "order_id": "20000000" + claim_id[-2:],
        "status": "closed",
        "stage": "claim",
        "type": "returns",
        "date_created": created,
        "schema_version": 1,
    }


async def paused_pilot_with_tail_due(
    db: Any, monkeypatch: pytest.MonkeyPatch
) -> tuple[datetime, datetime, datetime]:
    """Certify one pilot unit, pause the pilot, and return the tail bounds."""
    from infra.operations import zelerdata_read_model_reconcile as reconcile

    schema = json.loads(
        (Path(__file__).resolve().parents[2] / f"infra/mongo/schemas/{QUARANTINE}.json").read_text()
    )
    await db.create_collection(
        QUARANTINE,
        validator={"$jsonSchema": schema["$jsonSchema"]},
        validationLevel="strict",
        validationAction="error",
    )
    plan = await seed_plan(db)
    today = datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)
    start = today - timedelta(days=12)
    await acquire_unit(db, plan, start, EmptyGateway())
    await db[ONBOARDING_PLANS_COLLECTION].update_one({"_id": "999"}, {"$set": {"state": "paused"}})
    monkeypatch.setattr(
        reconcile,
        "create_runtime_historical_meli_gateways",
        lambda: SimpleNamespace(order_detail_gateway=EmptyGateway()),
    )
    settled = datetime.combine(
        (datetime.now(UTC) - timedelta(hours=1)).date(), time.min, tzinfo=UTC
    )
    return start, start + timedelta(days=10), settled


@pytest.mark.asyncio
async def test_tail_quarantines_a_legacy_claim_its_inventory_does_not_report(
    onboarding_claims_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """2026-10-08: the tail for 06-11..06-21 certified its window (9 claims) but
    its final readback counted a tenth, pre-v2 row the source no longer reports.
    The run failed and retried once a day forever, freezing coverage. Every
    certified reader rejects such a row, so the window must retire it.
    """
    import hashlib

    from bson import BSON
    from bson.codec_options import CodecOptions

    db = onboarding_claims_db
    start, tail_start, settled = await paused_pilot_with_tail_due(db, monkeypatch)
    legacy = legacy_claim("5000000001", tail_start + timedelta(hours=6))
    other_seller = legacy_claim("5000000002", tail_start + timedelta(hours=6), seller="998")
    after_tail = legacy_claim("5000000003", settled + timedelta(minutes=30))
    await db.claims.insert_many([dict(legacy), other_seller, after_tail])

    assert await advance_due_devoluciones_run(db, "999", history_work_enabled=False) is True

    tail = await db.sheets_devoluciones_runs.find_one(
        {"authorization_id": ORDINARY_TAIL_AUTHORIZATION}
    )
    assert tail is not None and tail["state"] == "completed"
    covering = await select_covering_proofs(db, "999", start, settled, datetime.now(UTC))
    assert len(covering.proofs) == 2
    assert await db.claims.find_one({"_id": legacy["_id"]}) is None
    archived = await db[QUARANTINE].find_one({"_id": legacy["_id"]})
    assert archived is not None
    assert archived["seller_id"] == "999"
    assert archived["run_id"] == tail["_id"]
    assert archived["window_id"] == f"{tail['_id']}:0"
    assert archived["reason"] == "not_in_authoritative_inventory"
    assert archived["claim_sha256"] == hashlib.sha256(archived["claim_bson"]).hexdigest()
    original = BSON(archived["claim_bson"]).decode(CodecOptions(tz_aware=True, tzinfo=UTC))
    assert original == legacy
    # Only this seller's non-canonical rows inside the acquired window move.
    assert await db.claims.count_documents({"_id": {"$in": ["5000000002", "5000000003"]}}) == 2
    assert await db[QUARANTINE].count_documents({}) == 1


@pytest.mark.asyncio
async def test_tail_keeps_an_unreported_canonical_claim_and_fails_closed(
    onboarding_claims_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A v2 row the source omits is a membership disagreement, not a stale
    format: it stays in place and the run must not certify the range.
    """
    db = onboarding_claims_db
    start, tail_start, settled = await paused_pilot_with_tail_due(db, monkeypatch)
    created = tail_start + timedelta(hours=6)
    canonical = legacy_claim("5000000004", created) | {
        "status": "opened",
        "item_id": "MLM1",
        "productive": True,
        "returned_quantity": 1,
        "return_quantity_basis": "v2_return_order",
        "claim_version": 1,
        "last_updated": created,
        "return_last_updated": created,
    }
    await db.claims.insert_one(dict(canonical))

    assert await advance_due_devoluciones_run(db, "999", history_work_enabled=False) is True

    tail = await db.sheets_devoluciones_runs.find_one(
        {"authorization_id": ORDINARY_TAIL_AUTHORIZATION}
    )
    assert tail is not None and tail["state"] == "failed"
    assert await db.claims.find_one({"_id": canonical["_id"]}) == canonical
    assert await db[QUARANTINE].count_documents({}) == 0
    with pytest.raises(CoverageUnavailableError):
        await select_covering_proofs(db, "999", start, settled, datetime.now(UTC))


@pytest.mark.asyncio
async def test_pilot_windows_still_leave_legacy_claims_to_the_operator(
    onboarding_claims_db: Any,
) -> None:
    """Only the ordinary tail retires rows. Operator and pilot runs share the
    window executor and keep failing closed on any non-canonical row.
    """
    db = onboarding_claims_db
    plan = await seed_plan(db)
    start = datetime(2026, 6, 11, tzinfo=UTC)
    legacy = legacy_claim("5000000005", start + timedelta(days=2))
    await db.claims.insert_one(dict(legacy))
    gateway = EmptyGateway()

    first = await advance_onboarding_devoluciones(
        db,
        plan,
        start=start,
        end=start + timedelta(days=10),
        gateway=gateway,
        charge=charge_for(db, plan),
    )
    assert first["state"] == "active" and first["advanced"] == 1
    await db.sheets_devoluciones_runs.update_one(
        {"_id": first["run_id"]}, {"$set": {"not_before": datetime.now(UTC)}}
    )
    final = await advance_onboarding_devoluciones(
        db,
        plan,
        start=start,
        end=start + timedelta(days=10),
        gateway=gateway,
        charge=charge_for(db, plan),
    )

    assert final["state"] == "failed" and final["finalized"] == 0
    assert await db.claims.find_one({"_id": legacy["_id"]}) == legacy
    assert await db[QUARANTINE].count_documents({}) == 0
    assert await db[CERTIFICATES].count_documents({}) == 0
