"""A newly linked ZelerData seller gets DEVOLUCIONES without an operator (real Mongo).

Until 2026-10-12 only the pilot advanced: the bootstrap leaves a new seller's
coverage control in legacy mode, the onboarding initializer needs no control at
all, and the daily tail needs a certificate to extend. The only way in was an
operator quota run (pilot-only) followed by ``devoluciones_certificate_migrate``.

Here the pilot is already in certificate mode with its daily tail due, and a
new eligible seller has only what its bootstrap left. The refresh loop alone
must give the new seller its initial window, activate certificate coverage
from that window's proof, and catch up the rest with the daily tail, one
window per cycle in total, while the pilot keeps exactly its behavior.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
import pytest_asyncio

from zeler_platform_core.devoluciones_certificates import (
    CERTIFICATES,
    CoverageUnavailableError,
    select_covering_proofs,
)
from zeler_platform_core.devoluciones_readiness import (
    acquire_devoluciones_operation,
    finish_devoluciones_operation,
    new_devoluciones_attempt_token,
)
from zeler_sheets.devoluciones_runner import (
    INITIAL_COVERAGE_AUTHORIZATION,
    ONBOARDING_PLANS_COLLECTION,
    ORDINARY_TAIL_AUTHORIZATION,
    advance_onboarding_devoluciones,
)

PILOT = "82453304"
NEW_SELLER = "90000001"
PAUSED_SELLER = "90000002"
RUNS = "sheets_devoluciones_runs"


@pytest_asyncio.fixture
async def new_sellers_db() -> AsyncIterator[Any]:
    from motor.motor_asyncio import AsyncIOMotorClient

    client: Any = AsyncIOMotorClient(
        "mongodb://127.0.0.1:27028/?directConnection=true",
        tz_aware=True,
        serverSelectionTimeoutMS=1000,
    )
    hello = await client.admin.command("hello")
    assert hello["isWritablePrimary"] is True and hello["setName"] == "rs0"
    name = "zeler_devoluciones_new_sellers_" + uuid4().hex
    db = client[name]
    try:
        for collection in (
            "sheets_devoluciones_operations",
            RUNS,
            "sheets_devoluciones_run_windows",
            CERTIFICATES,
            "sheets_devoluciones_claim_quarantine",
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


def _meli_time(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _parse_meli_time(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%f%z")


class SellersGateway:
    """Each seller has one productive return; Mercado Libre is never called."""

    def __init__(self, returns: Mapping[str, datetime]) -> None:
        self.calls: list[str] = []
        self._returns = dict(returns)

    def _resources(self, seller_id: str) -> dict[str, Any]:
        created = _meli_time(self._returns[seller_id])
        suffix = seller_id[-4:]
        claim_id, order_id, item_id = f"55{suffix}01", f"20{suffix}01", f"MLM{suffix}"
        players = [
            {"user_id": int(seller_id), "role": "respondent", "type": "seller"},
            {"user_id": 90001, "role": "complainant", "type": "buyer"},
        ]
        return {
            "row": {
                "id": claim_id,
                "date_created": created,
                "last_updated": created,
                "type": "returns",
                "status": "closed",
            },
            "claim": {
                "id": claim_id,
                "claim_version": 1,
                "date_created": created,
                "last_updated": created,
                "order_id": order_id,
                "item_id": item_id,
                "status": "closed",
                "stage": "claim",
                "type": "returns",
                "players": players,
                "related_entities": [{"type": "return", "id": f"RETURN-{claim_id}"}],
            },
            "returns": {
                "id": f"RETURN-{claim_id}",
                "status": "delivered",
                "subtype": "return_total",
                "last_updated": created,
                "orders": [
                    {
                        "order_id": order_id,
                        "item_id": item_id,
                        "context_type": "total",
                        "return_quantity": "2.0",
                        "total_quantity": 2,
                    }
                ],
            },
            "order": {
                "id": int(order_id),
                "seller": {"id": int(seller_id)},
                "buyer": {"id": 90001},
                "status": "paid",
                "date_created": created,
                "last_updated": created,
                "total_amount": 200,
                "items": [
                    {
                        "item": {"id": item_id, "seller_sku": f"SKU-{suffix}", "title": "Title"},
                        "quantity": 2,
                        "unit_price": 100,
                    }
                ],
            },
        }

    async def fetch_resource_once(self, *, seller_id: str, path: str, **_: Any) -> dict[str, Any]:
        self.calls.append(seller_id)
        resources = self._resources(seller_id)
        if path.startswith("/post-purchase/v1/claims/search?"):
            query = parse_qs(urlsplit(path).query)
            start = _parse_meli_time(query["date_created"][0])
            end = _parse_meli_time(query["range"][0].rsplit("before:", 1)[1])
            rows = [resources["row"]] if start <= self._returns[seller_id] < end else []
            return {"data": rows, "paging": {"offset": 0, "limit": 100, "total": len(rows)}}
        if path.startswith("/orders/"):
            return dict(resources["order"])
        if path.endswith("/returns"):
            return dict(resources["returns"])
        return dict(resources["claim"])

    async def fetch_resource(self, *, seller_id: str, path: str) -> dict[str, Any]:
        return await self.fetch_resource_once(seller_id=seller_id, path=path)


async def _link(db: Any, seller_id: str, *, status: str = "active") -> None:
    """A linked seller with ZelerData enabled (an active extension token)."""
    await db.meli_accounts.insert_one({"seller_id": seller_id, "status": status})
    await db.sheets_extension_tokens.insert_one(
        {
            "status": "active",
            "seller_scopes": [{"seller_id": seller_id, "nickname": f"n{seller_id}"}],
            "expires_at": datetime.now(UTC) + timedelta(days=30),
        }
    )


async def _certify_paused_pilot(db: Any, gateway: SellersGateway, start: datetime) -> None:
    """The pilot reached certificate mode through its history plan, now paused."""
    now = datetime.now(UTC)
    now = now.replace(microsecond=now.microsecond // 1000 * 1000)
    plan = {
        "_id": PILOT,
        "seller_id": PILOT,
        "state": "active",
        "eligible": True,
        "policy_version": "history-on-link-v1",
        "authority": {"kind": "account_link_policy"},
        "date_from": start - timedelta(days=30),
        "date_to": now,
        "cutoff": now,
        "sources": ["claims_returns"],
        "budget": {"claims_returns": {"physical_attempts": 20000, "consumed": 0}},
        "incremental_policy": {"max_daily_total": 2000, "max_daily_source": 1000},
    }
    await db[ONBOARDING_PLANS_COLLECTION].insert_one(plan)

    async def charge() -> None:
        await db[ONBOARDING_PLANS_COLLECTION].update_one(
            {"_id": PILOT}, {"$inc": {"budget.claims_returns.consumed": 1}}
        )

    end = start + timedelta(days=10)
    first = await advance_onboarding_devoluciones(
        db, plan, start=start, end=end, gateway=gateway, charge=charge
    )
    assert first["state"] == "active" and first["advanced"] == 1
    await db[RUNS].update_one({"_id": first["run_id"]}, {"$set": {"not_before": now}})
    final = await advance_onboarding_devoluciones(
        db, plan, start=start, end=end, gateway=gateway, charge=charge
    )
    assert final["state"] == "completed" and final["finalized"] == 1
    await db[ONBOARDING_PLANS_COLLECTION].update_one({"_id": PILOT}, {"$set": {"state": "paused"}})


async def _bootstrap_claims_stage(db: Any, seller_id: str) -> None:
    """What the bootstrap claims stage leaves: a legacy control and a stale marker."""
    operation = await acquire_devoluciones_operation(
        db=db,
        seller_id=seller_id,
        scope="devoluciones",
        operation_id="bootstrap-claims",
        attempt_token=new_devoluciones_attempt_token(),
    )
    await finish_devoluciones_operation(db=db, operation=operation, succeeded=True)


def _enable_all_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "ZELERDATA_SCHEDULED_BULK_REFRESH_ENABLED",
        "ZELERDATA_SCHEDULED_INVENTORY_REFRESH_ENABLED",
        "ZELERDATA_SCHEDULED_CATALOG_REFRESH_ENABLED",
        "ZELERDATA_REFRESH_INTERVAL_SECONDS",
        "ZELERDATA_PRECALCULATED_FORMULAS_ENABLED",
        "ZELERDATA_FRESHNESS_ALERTS_ENABLED",
        "ZELERDATA_DLQ_ARCHIVE_ENABLED",
        "ZELERDATA_ORDER_HISTORY_PROTOCOL_ENABLED",
        "ZELERDATA_QUESTION_HISTORY_PROTOCOL_ENABLED",
        "ZELERDATA_ORDER_MODIFICATION_SCAN_ENABLED",
        # Unset: automatic initial coverage is on by default.
        "ZELERDATA_DEVOLUCIONES_INITIAL_COVERAGE_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ZELERDATA_SCHEDULED_RENEWAL_REFRESH_ENABLED", "false")
    monkeypatch.setenv("ZELERDATA_HISTORY_ON_LINK_ENABLED", "false")
    monkeypatch.setenv("ZELERDATA_DEVOLUCIONES_ADVANCE_ENABLED", "true")
    monkeypatch.setenv("ZELERDATA_REFRESH_ENABLED", "true")
    monkeypatch.setenv("ZELERDATA_REFRESH_SELLERS", "all")
    monkeypatch.setenv("ZELERDATA_FORMULA_RECOVERY_ENABLED", "true")
    monkeypatch.setenv("ZELERDATA_FORMULA_RECOVERY_SELLERS", "all")


async def _devoluciones(db: Any, seller_id: str, date_from: datetime, date_to: datetime) -> Any:
    from zeler_sheets.formulas.dispatcher import FormulaExecutionContext
    from zeler_sheets.formulas.handlers_returns_histories_withdrawals import (
        ReturnsHistoriesWithdrawalsFormulaHandlers,
    )
    from zeler_sheets.formulas.read_models import FormulaReadModelRepository
    from zeler_sheets.formulas.registry import FormulaRegistry

    handlers = ReturnsHistoriesWithdrawalsFormulaHandlers(FormulaReadModelRepository(db=db))
    return await handlers.sheetseller_devoluciones(
        FormulaExecutionContext(
            contract=FormulaRegistry.default().find_required("ZELERDATA_DEVOLUCIONES"),
            cuenta="seller",
            seller_id=seller_id,
            seller_nickname="seller",
            token_id="token-1",  # noqa: S106 - a fake extension token id
            args={
                "fecha_inicio": date_from.date().isoformat(),
                "fecha_final": (date_to - timedelta(days=1)).date().isoformat(),
            },
            request_id="req-1",
        )
    )


@pytest.mark.asyncio
async def test_a_new_eligible_seller_gets_devoluciones_without_an_operator(
    new_sellers_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from infra.operations import zelerdata_read_model_reconcile as reconcile

    from zeler_sheets.consumer import build_zelerdata_refresh_supervisor
    from zeler_sheets.formulas.dispatcher import FormulaDataUnavailableError

    db = new_sellers_db
    settled = datetime.combine(
        (datetime.now(UTC) - timedelta(hours=1)).date(), time.min, tzinfo=UTC
    )
    pilot_start = settled - timedelta(days=12)
    initial_start = settled - timedelta(days=90)
    gateway = SellersGateway(
        {
            # The pilot's return arrives in its due tail window.
            PILOT: settled - timedelta(days=1, hours=-6),
            # The new seller's return is in a window the tail catches up.
            NEW_SELLER: settled - timedelta(days=5, hours=-6),
            PAUSED_SELLER: settled - timedelta(days=5, hours=-6),
        }
    )
    await _certify_paused_pilot(db, gateway, pilot_start)
    pilot_control = await db.sheets_devoluciones_operations.find_one({"seller_id": PILOT})
    assert pilot_control["coverage_mode"] == "active"
    pilot_certificates = await db[CERTIFICATES].count_documents({"seller_id": PILOT})
    assert pilot_certificates == 1
    gateway.calls.clear()

    for seller_id in (PILOT, NEW_SELLER):
        await _link(db, seller_id)
    await _link(db, PAUSED_SELLER, status="paused")
    for seller_id in (NEW_SELLER, PAUSED_SELLER):
        await _bootstrap_claims_stage(db, seller_id)
    control = await db.sheets_devoluciones_operations.find_one({"seller_id": NEW_SELLER})
    assert control["coverage_mode"] == "legacy"
    marker = await db.sheets_read_model_freshness.find_one({"_id": f"{NEW_SELLER}:devoluciones"})
    assert marker["state"] == "stale"

    monkeypatch.setattr(
        reconcile,
        "create_runtime_historical_meli_gateways",
        lambda: SimpleNamespace(order_detail_gateway=gateway),
    )
    _enable_all_mode(monkeypatch)
    supervisor = await build_zelerdata_refresh_supervisor(db=db)
    assert await supervisor._explorer.discover_sellers() == (PILOT, NEW_SELLER)

    # Before: the new seller's DEVOLUCIONES is unavailable.
    with pytest.raises(FormulaDataUnavailableError):
        await _devoluciones(db, NEW_SELLER, settled - timedelta(days=30), settled)

    served: list[tuple[str, ...]] = []
    for _ in range(12):
        runs_before = {run["_id"] async for run in db[RUNS].find({}, {"_id": 1})}
        await supervisor.run_cycle()
        new_runs = [run async for run in db[RUNS].find({"_id": {"$nin": list(runs_before)}})]
        # At most one window of source work per cycle, for the whole fleet.
        assert len(new_runs) <= 1
        served.append(tuple(f"{run['seller_id']}:{run['authorization_id']}" for run in new_runs))

    # The pilot's due tail took the first cycle; the new seller waited its turn.
    assert served[0] == (f"{PILOT}:{ORDINARY_TAIL_AUTHORIZATION}",)
    assert served[1] == (f"{NEW_SELLER}:{INITIAL_COVERAGE_AUTHORIZATION}",)
    assert all(run == (f"{NEW_SELLER}:{ORDINARY_TAIL_AUTHORIZATION}",) for run in served[2:10])
    # Once covered up to the settled midnight, nothing else is due.
    assert served[10:] == [(), ()]

    # The new seller: certificate coverage from 90 days back to the settled midnight.
    control = await db.sheets_devoluciones_operations.find_one({"seller_id": NEW_SELLER})
    assert control["coverage_mode"] == "active"
    assert control["coverage_ack_fence"] == control["fence"]
    initial = await db[RUNS].find_one(
        {"seller_id": NEW_SELLER, "authorization_id": INITIAL_COVERAGE_AUTHORIZATION}
    )
    assert initial["state"] == "completed"
    assert (initial["start"], initial["end"]) == (
        initial_start,
        initial_start + timedelta(days=10),
    )
    now = datetime.now(UTC)
    covering = await select_covering_proofs(db, NEW_SELLER, initial_start, settled, now)
    assert len(covering.proofs) == 9
    # The formula reader serves DEVOLUCIONES for the new seller.
    result = await _devoluciones(db, NEW_SELLER, settled - timedelta(days=30), settled)
    assert result.values == [["MLM0001", "SKU-0001", 2, "Title"]]

    # The pilot: same epoch, one daily tail, no initial run, coverage readable.
    after = await db.sheets_devoluciones_operations.find_one({"seller_id": PILOT})
    assert after["coverage_mode"] == "active"
    assert after["coverage_epoch"] == pilot_control["coverage_epoch"]
    assert (
        await db[RUNS].count_documents(
            {"seller_id": PILOT, "authorization_id": ORDINARY_TAIL_AUTHORIZATION}
        )
        == 1
    )
    assert (
        await db[RUNS].count_documents(
            {"seller_id": PILOT, "authorization_id": INITIAL_COVERAGE_AUTHORIZATION}
        )
        == 0
    )
    pilot_covering = await select_covering_proofs(db, PILOT, pilot_start, settled, now)
    assert len(pilot_covering.proofs) == pilot_certificates + 1
    pilot_result = await _devoluciones(db, PILOT, pilot_start, settled)
    assert pilot_result.values == [["MLM3304", "SKU-3304", 2, "Title"]]

    # A seller that is not eligible gets nothing.
    assert PAUSED_SELLER not in gateway.calls
    assert await db[RUNS].count_documents({"seller_id": PAUSED_SELLER}) == 0
    paused = await db.sheets_devoluciones_operations.find_one({"seller_id": PAUSED_SELLER})
    assert paused["coverage_mode"] == "legacy"
    with pytest.raises(CoverageUnavailableError):
        await select_covering_proofs(db, PAUSED_SELLER, initial_start, settled, now)


@pytest.mark.asyncio
async def test_two_workers_and_a_restart_acquire_and_activate_the_initial_window_once(
    new_sellers_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    from infra.operations import zelerdata_read_model_reconcile as reconcile

    from zeler_sheets.devoluciones_runner import (
        admit_initial_devoluciones_coverage,
        advance_due_devoluciones_run,
    )
    from zeler_sheets.formulas.seller_scope import EligibleSellerGate

    db = new_sellers_db
    settled = datetime.combine(
        (datetime.now(UTC) - timedelta(hours=1)).date(), time.min, tzinfo=UTC
    )
    initial_start = settled - timedelta(days=90)
    gateway = SellersGateway({NEW_SELLER: initial_start + timedelta(days=3)})
    monkeypatch.setattr(
        reconcile,
        "create_runtime_historical_meli_gateways",
        lambda: SimpleNamespace(order_detail_gateway=gateway),
    )
    await _link(db, NEW_SELLER)
    await _bootstrap_claims_stage(db, NEW_SELLER)
    gate = EligibleSellerGate(db)

    async def admit_initial(db: Any, seller_id: str, *, now: Any = None) -> str | None:
        return await admit_initial_devoluciones_coverage(db, seller_id, eligible=gate, now=now)

    async def worker() -> str:
        try:
            return str(
                await advance_due_devoluciones_run(
                    db,
                    NEW_SELLER,
                    history_work_enabled=False,
                    admit_initial=admit_initial,
                    renew=False,
                )
            )
        except Exception as exc:  # noqa: BLE001 - the refresh cycle logs and moves on
            return type(exc).__name__

    # Two workers reach the same seller at once.
    await asyncio.gather(worker(), worker())

    initial = [
        run
        async for run in db[RUNS].find(
            {"seller_id": NEW_SELLER, "authorization_id": INITIAL_COVERAGE_AUTHORIZATION}
        )
    ]
    assert len(initial) == 1 and initial[0]["state"] == "completed"
    assert (
        await db.sheets_devoluciones_run_windows.count_documents({"run_id": initial[0]["_id"]}) == 1
    )
    control = await db.sheets_devoluciones_operations.find_one({"seller_id": NEW_SELLER})
    assert control["coverage_mode"] == "active"
    certificates = [row async for row in db[CERTIFICATES].find({"seller_id": NEW_SELLER})]
    assert [row["source_identity"] for row in certificates] == [initial[0]["_id"]]
    assert await db.claims.count_documents({"seller_id": NEW_SELLER}) == 1

    # After a restart nothing initial is admitted again; the tail owns the seller.
    assert await admit_initial(db, NEW_SELLER) is None
    assert (
        await db[RUNS].count_documents(
            {"seller_id": NEW_SELLER, "authorization_id": INITIAL_COVERAGE_AUTHORIZATION}
        )
        == 1
    )
    covering = await select_covering_proofs(
        db, NEW_SELLER, initial_start, initial_start + timedelta(days=10), datetime.now(UTC)
    )
    assert len(covering.proofs) == 1
