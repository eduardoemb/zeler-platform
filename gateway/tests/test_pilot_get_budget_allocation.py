"""No inferred allocation: selected ordinary traffic must wait, h1 needs authority."""

from __future__ import annotations

import asyncio
import copy
import socket
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from gateway.tests.test_pilot_get_budget import (
    ENV,
    EXECUTION,
    NOW,
    SELLER,
    TEST_ACCESS,
    Plans,
    matches,
    plan,
    recording_transport,
    request,
)

from zeler_gateway.proxy import router as proxy
from zeler_platform_core.history_onboarding import SOURCES
from zeler_sheets.formulas.pacing import HistoryPolicyWaitError
from zeler_sheets.history_onboarding import PlanBudgetGateway


@pytest.fixture(autouse=True)
def forbid_external_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("CUOTAS tests must not open external sockets")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "orders/1",  # Ambiguous: orders initial, upkeep or a claims dependency.
        "questions/1",
        "shipments/1/costs",
        "messages/packs/1/sellers/82453304",
        "post-purchase/v1/claims/1",
        "items/MLA1",  # Not a sixth pilot source.
        "stock/fulfillment/operations/search",  # Full stays excluded.
    ],
)
@pytest.mark.parametrize("disabled", [False, True])
async def test_unattributed_normal_or_event_never_sends_or_changes_any_counter(
    monkeypatch: pytest.MonkeyPatch, path: str, disabled: bool
) -> None:
    monkeypatch.setenv(ENV, SELLER)
    plans = Plans(plan())
    before = copy.deepcopy(plans.row)
    # Arbitrary headers cannot create trusted source/phase context.
    req = request(
        plans,
        headers={
            "X-Zeler-Source": "orders",
            "X-Zeler-Phase": "initial",
            **({"X-Zeler-Proxy-Retry": "disabled"} if disabled else {}),
        },
    )
    req._body = b""
    sent: list[str] = []
    req.app.state.proxy_http_client_factory = lambda: httpx.AsyncClient(
        transport=recording_transport(sent, 502)
    )
    with pytest.raises(proxy.PilotGetBudgetWaitError) as caught:
        await proxy._forward_to_meli(request=req, full_path=path, access_token=TEST_ACCESS)
    assert caught.value.code == "pilot_execution_unavailable"
    assert sent == [] and plans.updates == [] and plans.row == before


@pytest.mark.asyncio
@pytest.mark.parametrize("drift", ["authority", "identity"])
async def test_prepaid_h1_rechecks_current_authority_and_seller_at_send_cas(
    monkeypatch: pytest.MonkeyPatch, drift: str
) -> None:
    monkeypatch.setenv(ENV, SELLER)
    credit = {EXECUTION: {"orders": {"initial": 1}}}
    plans = Plans(plan(execution_consumed=1, execution_charged=credit))
    plans.before_cas = lambda row: row.update(
        **({"authority": {"kind": "other"}} if drift == "authority" else {"seller_id": "99"})
    )
    req = request(
        plans,
        headers={
            "X-Zeler-History-Trace": f"h1-{EXECUTION}:orders:initial",
            "X-Zeler-Proxy-Retry": "disabled",
        },
    )
    req._body = b""
    sent: list[str] = []
    req.app.state.proxy_http_client_factory = lambda: httpx.AsyncClient(
        transport=recording_transport(sent)
    )
    with pytest.raises(proxy.HistoryPolicyRejectedError):
        await proxy._forward_to_meli(request=req, full_path="orders/1", access_token=TEST_ACCESS)
    assert sent == [] and plans.updates == []
    assert plans.row is not None and plans.row["execution_consumed"] == 1
    assert plans.row["execution_charged"] == credit


INITIAL = {
    "orders": 800,
    "questions": 150,
    "shipments": 250,
    "messages": 300,
    "claims_returns": 500,
}
OWN_LEASE = "own-cuotas-lease"  # Synthetic local fence, not a credential.
PATHS = {
    "orders": "orders/1",
    "questions": "questions/1",
    "shipments": "shipments/1/costs",
    "messages": "messages/packs/1/sellers/82453304",
    "claims_returns": "post-purchase/v1/claims/1",
}


class AllocationPlans(Plans):
    """Atomic in-memory inc plus the worker's existing natural rollover operation."""

    async def update_one(self, query: dict[str, Any], update: dict[str, Any]) -> Any:
        async with self.lock:
            day = query["incremental_day"]["$ne"]
            owned = {key: value for key, value in query.items() if key != "incremental_day"}
            if (
                self.row is None
                or not matches(self.row, owned)
                or self.row.get("incremental_day") == day
            ):
                return SimpleNamespace(modified_count=0)
            assert set(update) == {"$set"}
            self.row.update(copy.deepcopy(update["$set"]))
            self.updates.append(copy.deepcopy(update))
            return SimpleNamespace(modified_count=1)


class Account:
    async def find_one(self, query: dict[str, Any]) -> Any:
        assert query == {"seller_id": {"$in": [SELLER, int(SELLER)]}, "status": "active"}
        return {"seller_id": int(SELLER), "status": "active"}


def allocation_plan(**changes: Any) -> dict[str, Any]:
    return plan(
        total_consumed=17,
        total_budget=2017,
        budget={
            source: {"consumed": 3, "physical_attempts": 3 + INITIAL.get(source, 0)}
            for source in SOURCES
        },
        incremental_day=NOW.date().isoformat(),
        incremental_consumed=19,
        incremental_source_consumed=dict.fromkeys(SOURCES, 3),
        incremental_policy={"max_daily_total": 519, "max_daily_source": 303},
        checkpoints={"orders": 8},
        cutoff=NOW - timedelta(days=2),
        lease_token=OWN_LEASE,
        lease_until=NOW + timedelta(minutes=1),
        **changes,
    )


class Physical:
    def __init__(self, plans: Plans, *, status: int = 200, crash: bool = False) -> None:
        self.plans, self.status, self.crash = plans, status, crash
        self.sends: list[str] = []
        self.clock = NOW

    async def fetch_resource(self, **kwargs: Any) -> Any:
        return await self.fetch_resource_once(**kwargs)

    async def fetch_resource_once(self, **kwargs: Any) -> Any:
        req = request(
            self.plans,
            headers={
                **kwargs.get("headers", {}),
                "X-Zeler-Proxy-Retry": "disabled",
            },
        )
        req._body = b""
        req.app.state.proxy_wait_now = lambda: self.clock

        def transport(r: httpx.Request) -> httpx.Response:
            self.sends.append(r.url.path)
            if self.crash:
                raise httpx.ConnectError("offline synthetic transport failure", request=r)
            return httpx.Response(self.status)

        req.app.state.proxy_http_client_factory = lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(transport)
        )
        return await proxy._forward_to_meli(
            request=req,
            full_path=kwargs["path"].lstrip("/"),
            access_token=TEST_ACCESS,
        )


def guard(plans: AllocationPlans, remote: Physical, source: str, phase: str) -> PlanBudgetGateway:
    result = PlanBudgetGateway(
        {"sheets_history_backfill_plans": plans, "meli_accounts": Account()},
        remote,
        SELLER,
        source,
        lease_token=OWN_LEASE,
        now=lambda: remote.clock,
    )
    result.incremental = phase == "maintenance"
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize("source", INITIAL)
@pytest.mark.parametrize("phase", ["initial", "maintenance"])
async def test_real_worker_and_proxy_charge_every_physical_retry_once_in_correct_lane(
    monkeypatch: pytest.MonkeyPatch, source: str, phase: str
) -> None:
    monkeypatch.setenv(ENV, SELLER)
    plans = AllocationPlans(allocation_plan())
    before = copy.deepcopy(plans.row)
    remote = Physical(plans, status=502)
    worker = guard(plans, remote, source, phase)
    # Caller retries are separate physical calls; gateway h1 never retries internally.
    for _ in range(3):
        response = await worker.fetch_resource(seller_id=SELLER, path="/" + PATHS[source])
        assert response.status_code == 502
    row = plans.row
    assert row is not None and before is not None
    assert len(remote.sends) == row["execution_consumed"] == row["execution_sent"] == 3
    assert row["execution_charged"] == {EXECUTION: {source: {phase: 3}}}
    assert row["execution_sent_by_source"] == row["execution_charged"]
    assert row["total_consumed"] == 17 + (3 if phase == "initial" else 0)
    assert row["budget"][source]["consumed"] == 3 + (3 if phase == "initial" else 0)
    assert row["incremental_consumed"] == 19 + (3 if phase == "maintenance" else 0)
    assert row["incremental_source_consumed"][source] == 3 + (3 if phase == "maintenance" else 0)
    for other in INITIAL.keys() - {source}:
        assert row["budget"][other] == before["budget"][other]
        assert row["incremental_source_consumed"][other] == 3
    for field in (
        "cutoff",
        "checkpoints",
        "lease_token",
        "lease_until",
        "execution_until",
        "execution_utc_day",
        "execution_attempt_limit",
        "total_budget",
        "incremental_policy",
    ):
        assert row[field] == before[field]


@pytest.mark.asyncio
@pytest.mark.parametrize("source", INITIAL)
@pytest.mark.parametrize("phase", ["initial", "maintenance"])
@pytest.mark.parametrize("exhausted", ["source", "phase", "global"])
async def test_exhausted_source_phase_or_global_denied_before_any_charge_or_transport(
    monkeypatch: pytest.MonkeyPatch, source: str, phase: str, exhausted: str
) -> None:
    monkeypatch.setenv(ENV, SELLER)
    value = allocation_plan()
    if exhausted == "global":
        value["execution_attempt_limit"] = 0
    elif phase == "initial":
        if exhausted == "source":
            value["budget"][source]["physical_attempts"] = 3
        else:
            value["total_budget"] = 17
    elif exhausted == "source":
        value["incremental_policy"]["max_daily_source"] = 3
    else:
        value["incremental_policy"]["max_daily_total"] = 19
    plans = AllocationPlans(value)
    remote = Physical(plans)
    with pytest.raises(HistoryPolicyWaitError):
        await guard(plans, remote, source, phase).fetch_resource(
            seller_id=SELLER, path="/" + PATHS[source]
        )
    assert remote.sends == [] and plans.updates == [] and plans.row == value


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["initial", "maintenance"])
@pytest.mark.parametrize("limiter", ["source", "phase", "global"])
async def test_concurrent_last_credit_with_unattributed_normal_and_h1_no_double_charge(
    monkeypatch: pytest.MonkeyPatch, phase: str, limiter: str
) -> None:
    monkeypatch.setenv(ENV, SELLER)
    value = allocation_plan()
    if limiter == "global":
        value["execution_attempt_limit"] = 1
    elif phase == "initial" and limiter == "source":
        value["budget"]["orders"]["physical_attempts"] = 4
    elif phase == "initial":
        value["total_budget"] = 18
    elif limiter == "source":
        value["incremental_policy"]["max_daily_source"] = 4
    else:
        value["incremental_policy"]["max_daily_total"] = 20
    plans = AllocationPlans(value)
    remote = Physical(plans)

    async def normal() -> None:
        req = request(plans)
        req._body = b""
        req.app.state.proxy_http_client_factory = lambda: httpx.AsyncClient(
            transport=recording_transport(remote.sends)
        )
        await proxy._forward_to_meli(request=req, full_path="orders/1", access_token=TEST_ACCESS)

    results = await asyncio.gather(
        *(
            guard(plans, remote, "orders", phase).fetch_resource(seller_id=SELLER, path="/orders/1")
            for _ in range(12)
        ),
        *(normal() for _ in range(12)),
        return_exceptions=True,
    )
    assert sum(isinstance(result, httpx.Response) for result in results) == 1
    assert all(
        isinstance(result, (httpx.Response, HistoryPolicyWaitError, proxy.PilotGetBudgetWaitError))
        for result in results
    )
    assert len(remote.sends) == 1 and plans.row is not None
    assert plans.row["execution_consumed"] == plans.row["execution_sent"] == 1
    assert plans.row["execution_charged"] == {EXECUTION: {"orders": {phase: 1}}}


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["initial", "maintenance"])
@pytest.mark.parametrize("stop", ["paused", "lease", "day", "deadline"])
async def test_stopped_worker_preserves_credit_checkpoint_and_daily_counters(
    monkeypatch: pytest.MonkeyPatch, phase: str, stop: str
) -> None:
    monkeypatch.setenv(ENV, SELLER)
    value = allocation_plan(execution_consumed=7)
    if stop == "paused":
        value["state"] = "paused"
    elif stop == "lease":
        value["lease_token"] = "other-" + OWN_LEASE
    plans = AllocationPlans(value)
    remote = Physical(plans)
    if stop == "day":
        remote.clock += timedelta(days=1)
    elif stop == "deadline":
        remote.clock += timedelta(minutes=90)
    with pytest.raises(HistoryPolicyWaitError):
        await guard(plans, remote, "orders", phase).fetch_resource(
            seller_id=SELLER, path="/orders/1"
        )
    assert remote.sends == [] and plans.updates == [] and plans.row == value


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["initial", "maintenance"])
async def test_failed_physical_h1_send_preserves_source_phase_and_global_charge(
    monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    monkeypatch.setenv(ENV, SELLER)
    plans = AllocationPlans(allocation_plan())
    remote = Physical(plans, crash=True)
    with pytest.raises(httpx.ConnectError):
        await guard(plans, remote, "orders", phase).fetch_resource(
            seller_id=SELLER, path="/orders/1"
        )
    assert len(remote.sends) == 1 and plans.row is not None
    assert plans.row["execution_consumed"] == plans.row["execution_sent"] == 1
    assert plans.row["execution_charged"] == {EXECUTION: {"orders": {phase: 1}}}


@pytest.mark.asyncio
@pytest.mark.parametrize("module", ["sheets", "bootstrap"])
@pytest.mark.parametrize(
    "missing",
    ["execution_until", "execution_utc_day", "execution_attempt_limit", "execution_consumed"],
)
async def test_selected_h1_cannot_bypass_mandatory_pilot_controls(
    monkeypatch: pytest.MonkeyPatch, missing: str, module: str
) -> None:
    monkeypatch.setenv(ENV, SELLER)
    value = plan(execution_consumed=1, execution_charged={EXECUTION: {"orders": {"initial": 1}}})
    del value[missing]
    plans = Plans(value)
    req = request(
        plans,
        module=module,
        headers={
            "X-Zeler-History-Trace": f"h1-{EXECUTION}:orders:initial",
            "X-Zeler-Proxy-Retry": "disabled",
        },
    )
    req._body = b""
    sent: list[str] = []
    req.app.state.proxy_http_client_factory = lambda: httpx.AsyncClient(
        transport=recording_transport(sent)
    )
    with pytest.raises(proxy.HistoryPolicyRejectedError):
        await proxy._forward_to_meli(request=req, full_path="orders/1", access_token=TEST_ACCESS)
    assert sent == [] and plans.updates == [] and plans.row == value


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["initial", "maintenance"])
async def test_prepaid_credit_cannot_be_replayed_or_borrowed_from_other_phase(
    monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    monkeypatch.setenv(ENV, SELLER)
    credit = {EXECUTION: {"orders": {phase: 1}}}
    plans = Plans(plan(execution_consumed=1, execution_charged=credit))
    remote = Physical(plans)

    async def send(tag_phase: str) -> Any:
        return await remote.fetch_resource_once(
            path="/orders/1",
            headers={"X-Zeler-History-Trace": f"h1-{EXECUTION}:orders:{tag_phase}"},
        )

    other = "maintenance" if phase == "initial" else "initial"
    with pytest.raises(proxy.HistoryPolicyRejectedError):
        await send(other)
    results = await asyncio.gather(*(send(phase) for _ in range(12)), return_exceptions=True)
    assert sum(isinstance(result, httpx.Response) for result in results) == 1
    assert all(
        isinstance(result, (httpx.Response, proxy.HistoryPolicyRejectedError)) for result in results
    )
    assert plans.row is not None and len(remote.sends) == 1
    assert plans.row["execution_consumed"] == plans.row["execution_sent"] == 1
    assert plans.row["execution_charged"] == credit


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["orders", "claims_returns"])
async def test_shared_orders_path_uses_prepaid_source_not_endpoint_inference(
    monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    monkeypatch.setenv(ENV, SELLER)
    plans = AllocationPlans(allocation_plan())
    remote = Physical(plans)
    await guard(plans, remote, source, "initial").fetch_resource(seller_id=SELLER, path="/orders/1")
    assert plans.row is not None
    assert plans.row["budget"][source]["consumed"] == 4
    assert plans.row["execution_charged"] == {EXECUTION: {source: {"initial": 1}}}


@pytest.mark.asyncio
@pytest.mark.parametrize("corrupt", ["global_sent", "source_sent", "credit"])
async def test_h1_does_not_repair_corrupt_prepaid_counters_or_send(
    monkeypatch: pytest.MonkeyPatch, corrupt: str
) -> None:
    monkeypatch.setenv(ENV, SELLER)
    value = plan(execution_consumed=1, execution_charged={EXECUTION: {"orders": {"initial": 1}}})
    if corrupt == "global_sent":
        value["execution_sent"] = -1
    elif corrupt == "source_sent":
        value["execution_sent_by_source"] = {EXECUTION: {"orders": {"initial": -1}}}
    else:
        value["execution_charged"][EXECUTION]["orders"]["initial"] = True
    plans = Plans(value)
    req = request(
        plans,
        headers={
            "X-Zeler-History-Trace": f"h1-{EXECUTION}:orders:initial",
            "X-Zeler-Proxy-Retry": "disabled",
        },
    )
    req._body = b""
    sent: list[str] = []
    req.app.state.proxy_http_client_factory = lambda: httpx.AsyncClient(
        transport=recording_transport(sent)
    )
    with pytest.raises(proxy.HistoryPolicyRejectedError):
        await proxy._forward_to_meli(request=req, full_path="orders/1", access_token=TEST_ACCESS)
    assert sent == [] and plans.updates == [] and plans.row == value
