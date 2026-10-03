"""Automatic policy authority reuses exact quota contracts, never manual pilot flags."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from zeler_sheets import devoluciones_runner as runner

NOW = datetime(2026, 10, 2, tzinfo=UTC)
START = NOW - timedelta(days=365)


def plan(**changes: Any) -> dict[str, Any]:
    value = {
        "_id": "999",
        "seller_id": "999",
        "state": "active",
        "eligible": True,
        "policy_version": "history-on-link-v1",
        "authority": {"kind": "account_link_policy"},
        "date_from": START,
        "date_to": NOW,
        "cutoff": NOW,
        "sources": ["claims_returns"],
        "budget": {"claims_returns": {"physical_attempts": 20000, "consumed": 0}},
    }
    value.update(changes)
    return value


class Collection:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []
        self.writes: list[Any] = []

    async def find_one(self, query: dict[str, Any], **_: Any) -> Any:
        for row in self.rows:
            if all(row.get(key) == value for key, value in query.items()):
                return deepcopy(row)
        return None

    async def update_one(self, query: Any, change: Any, **_: Any) -> Any:
        self.writes.append((query, change))
        return SimpleNamespace(matched_count=1, acknowledged=True)


class Db:
    def __init__(self, value: Any) -> None:
        self.cols = {
            runner.ONBOARDING_PLANS_COLLECTION: Collection([deepcopy(value)]),
            "sheets_devoluciones_operations": Collection(
                [
                    {
                        "seller_id": value["seller_id"],
                        "scope": "devoluciones",
                        "coverage_mode": "active",
                        "coverage_ack_fence": 1,
                        "fence": 1,
                        "coverage_epoch": 0,
                    }
                ]
            ),
        }

    def __getitem__(self, name: str) -> Collection:
        return self.cols.setdefault(name, Collection())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"seller_id": "111"},
        {"eligible": False},
        {"state": "paused"},
        {"sources": ["orders"]},
        {"budget": {"claims_returns": {"physical_attempts": 0}}},
        {"budget": {"claims_returns": {"physical_attempts": 20000, "consumed": 20000}}},
        {"authority": {"kind": "operator"}},
    ],
)
async def test_automatic_admission_rejects_unpersisted_or_out_of_policy(changes: Any) -> None:
    original = plan()
    db = Db(
        plan(**changes)
        if changes.get("budget", {}).get("claims_returns", {}).get("consumed")
        else original
    )
    requested = plan(**changes)
    with pytest.raises(ValueError):
        await runner.admit_onboarding_devoluciones(db, requested, now=lambda: NOW)
    assert not db["sheets_devoluciones_runs"].writes


@pytest.mark.asyncio
async def test_admission_reuses_binding_without_touching_existing_proof(monkeypatch: Any) -> None:
    value = plan()
    db = Db(value)
    created: list[Any] = []
    operations: list[Any] = []

    async def acquire(**kwargs: Any) -> Any:
        operations.append(kwargs)
        return SimpleNamespace(seller_id="999", scope="devoluciones")

    async def finish(**_: Any) -> None:
        pass

    class Repository:
        def __init__(self, _: Any) -> None:
            pass

        async def create(self, binding: Any, **_: Any) -> bool:
            created.append(binding)
            return True

    monkeypatch.setattr(runner, "_acquire_onboarding_operation", acquire)
    monkeypatch.setattr(runner, "_finish_onboarding_operation", finish)
    monkeypatch.setattr(runner, "_OnboardingRepository", Repository)
    first = await runner.admit_onboarding_devoluciones(db, value, now=lambda: NOW)
    second = await runner.admit_onboarding_devoluciones(db, value, now=lambda: NOW)
    assert first == second == created[0].run_id
    assert created[0].end == START + timedelta(days=10)
    assert created[0].seller_id == "999"
    assert created[0].authorization_id == "onboarding:999"
    assert all(call["invalidate_readiness"] is False for call in operations)
    assert not db["sheets_read_model_freshness"].writes
    assert not db["sheets_devoluciones_certificates"].writes


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "start,end",
    [
        (START - timedelta(days=1), START + timedelta(days=1)),
        (NOW - timedelta(days=1), NOW + timedelta(days=1)),
        (START, START + timedelta(days=11)),
    ],
)
async def test_admission_refuses_foreign_range_or_unbounded_unit(start: Any, end: Any) -> None:
    with pytest.raises(ValueError):
        await runner.admit_onboarding_devoluciones(
            Db(plan()), plan(), start=start, end=end, now=lambda: NOW
        )


@pytest.mark.asyncio
async def test_legacy_marker_never_becomes_automatic_certificate() -> None:
    db = Db(plan())
    db["sheets_devoluciones_operations"].rows[0]["coverage_mode"] = "legacy"
    with pytest.raises(ValueError, match="migration"):
        await runner.admit_onboarding_devoluciones(db, plan(), now=lambda: NOW)
    assert not db["sheets_read_model_freshness"].writes


@pytest.mark.asyncio
async def test_revocation_between_attempts_stops_source_before_send() -> None:
    value = plan()
    db = Db(value)
    sends: list[Any] = []
    charged: list[bool] = []

    async def charge() -> None:
        charged.append(True)

    class Gateway:
        async def fetch_resource_once(self, **kwargs: Any) -> Any:
            sends.append(kwargs)
            return {"results": []}

    client = runner.OnboardingDevolucionesGateway(db, value, Gateway(), charge=charge)
    await client.fetch_resource_once(seller_id="999", path="/post-purchase/v1/claims/search")
    db[runner.ONBOARDING_PLANS_COLLECTION].rows[0]["eligible"] = False
    with pytest.raises(ValueError):
        await client.fetch_resource_once(seller_id="999", path="/orders/10")
    assert len(sends) == len(charged) == 1


@pytest.mark.asyncio
async def test_wrapper_refuses_foreign_seller_and_non_acquisition_route() -> None:
    async def charge() -> None:
        raise AssertionError("invalid request must not be charged")

    client = runner.OnboardingDevolucionesGateway(Db(plan()), plan(), object(), charge=charge)
    for seller, path in [("other", "/orders/10"), ("999", "/messages/1")]:
        with pytest.raises(ValueError):
            await client.fetch_resource_once(seller_id=seller, path=path)


@pytest.mark.asyncio
async def test_last_budgeted_request_is_sent_but_next_attempt_is_refused() -> None:
    value = plan(budget={"claims_returns": {"physical_attempts": 1, "consumed": 0}})
    db = Db(value)
    sends: list[str] = []

    async def charge() -> None:
        db[runner.ONBOARDING_PLANS_COLLECTION].rows[0]["budget"]["claims_returns"]["consumed"] += 1

    class Gateway:
        async def fetch_resource_once(self, **_: Any) -> Any:
            sends.append("sent")
            return {}

    client = runner.OnboardingDevolucionesGateway(db, value, Gateway(), charge=charge)
    await client.fetch_resource_once(seller_id="999", path="/orders/10")
    with pytest.raises(ValueError, match="budget"):
        await client.fetch_resource_once(seller_id="999", path="/orders/10")
    assert sends == ["sent"]


@pytest.mark.asyncio
async def test_existing_refresh_advancer_routes_policy_runs_without_pilot_cli(
    monkeypatch: Any,
) -> None:
    import infra.operations.zelerdata_read_model_reconcile as runtime

    import zeler_sheets.history_onboarding as onboarding

    value = plan()
    db = Db(value)
    row = {
        "_id": "b" * 64,
        "seller_id": "999",
        "scope": "devoluciones",
        "authorization_id": "onboarding:999",
        "start": START,
        "end": START + timedelta(days=10),
    }
    db["sheets_devoluciones_runs"].rows.append(row)
    seen: list[Any] = []

    async def advance(database: Any, planned: Any, **kwargs: Any) -> Any:
        seen.append((database, planned, kwargs))
        return {"advanced": 1, "finalized": 0, "state": "active", "run_id": row["_id"]}

    monkeypatch.setattr(runner, "advance_onboarding_devoluciones", advance)
    monkeypatch.setattr(
        runtime,
        "create_runtime_historical_meli_gateways",
        lambda: SimpleNamespace(order_detail_gateway=object()),
    )
    monkeypatch.setattr(onboarding, "PlanBudgetGateway", lambda *args: args)
    assert await runner._runtime_advance(db=db, run_id=str(row["_id"])) == {
        "advanced": 1,
        "finalized": 0,
    }
    assert seen[0][1]["_id"] == "999"
    assert seen[0][2]["start"] == row["start"]


def test_incremental_authority_is_separate_bounded_scope_not_initial_cutoff_expansion() -> None:
    start, end = NOW - timedelta(minutes=5), NOW + timedelta(hours=2)
    value = plan(
        incremental_scopes={
            "claims_returns": {
                "date_from": start,
                "date_to": end,
                "policy_version": "history-on-link-v1",
            }
        }
    )
    bound = runner._onboarding_binding(value, start, end)
    assert bound.start == start and bound.end == end
    assert value["date_to"] == value["cutoff"] == NOW
    with pytest.raises(ValueError):
        runner._onboarding_binding(value, start, end + timedelta(seconds=1))
    with pytest.raises(ValueError):
        runner._onboarding_binding(value, start - timedelta(seconds=1), end)
    value["incremental_scopes"]["claims_returns"]["date_to"] = NOW + timedelta(days=2)
    with pytest.raises(ValueError):
        runner._onboarding_binding(value, start, end)


@pytest.mark.asyncio
async def test_scope_revocation_stops_incremental_source_before_send() -> None:
    start, end = NOW - timedelta(minutes=5), NOW + timedelta(hours=2)
    value = plan(
        incremental_scopes={
            "claims_returns": {
                "date_from": start,
                "date_to": end,
                "policy_version": "history-on-link-v1",
            }
        }
    )
    db = Db(value)

    async def charge() -> None:
        raise AssertionError("revoked scope must not dispatch")

    client = runner.OnboardingDevolucionesGateway(
        db, value, object(), charge=charge, start=start, end=end
    )
    db[runner.ONBOARDING_PLANS_COLLECTION].rows[0]["incremental_scopes"] = {}
    with pytest.raises(ValueError):
        await client.fetch_resource_once(seller_id="999", path="/orders/10")


@pytest.mark.asyncio
async def test_standing_incremental_budget_is_independent_of_spent_initial_budget() -> None:
    start, end = NOW - timedelta(minutes=5), NOW + timedelta(hours=2)
    value = plan(
        budget={"claims_returns": {"physical_attempts": 20000, "consumed": 20000}},
        incremental_policy={"max_daily_total": 2000, "max_daily_source": 1000},
        incremental_day=NOW.date().isoformat(),
        incremental_consumed=2,
        incremental_source_consumed={"claims_returns": 2},
        incremental_scopes={
            "claims_returns": {
                "date_from": start,
                "date_to": end,
                "policy_version": "history-on-link-v1",
            }
        },
    )
    db = Db(value)
    checked = await runner._validated_onboarding_plan(db, value, start=start, end=end, now=NOW)
    assert checked["budget"]["claims_returns"]["consumed"] == 20000
    with pytest.raises(ValueError, match="budget"):
        await runner._validated_onboarding_plan(db, value, now=NOW)
    persisted = db[runner.ONBOARDING_PLANS_COLLECTION].rows[0]
    persisted["incremental_source_consumed"]["claims_returns"] = 1000
    with pytest.raises(ValueError, match="budget"):
        await runner._validated_onboarding_plan(db, value, start=start, end=end, now=NOW)
    await runner._validated_onboarding_plan(db, value, start=start, end=end, now=NOW, charged=True)
    checked = await runner._validated_onboarding_plan(
        db, value, start=start, end=end, now=NOW + timedelta(days=1)
    )
    assert checked["incremental_source_consumed"]["claims_returns"] == 1000
