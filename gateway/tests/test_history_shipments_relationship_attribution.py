"""Offline h1 shipment ownership relationship: no new registry or work scope."""

from __future__ import annotations

import asyncio
import copy
import json
import os
import socket
from collections.abc import Awaitable, Callable
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from gateway.tests.test_pilot_get_budget import (
    EXECUTION,
    NOW,
    SELLER,
    TEST_ACCESS,
    Plans,
    plan,
    request,
)

from zeler_gateway.proxy import router as proxy

CAPS = dict(orders=800, questions=150, shipments=250, messages=300, claims_returns=500)


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(os, "environ", {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path)})

    def denied(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("shipment purpose tests forbid external sockets")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    # Settings() must not read a developer .env or any ambient credentials.
    monkeypatch.setattr(
        proxy,
        "Settings",
        lambda: SimpleNamespace(
            meli_api_base="https://offline.invalid",
            history_pilot_get_budget_sellers=frozenset({SELLER}),
        ),
    )


def setup(
    *,
    source: str = "shipments",
    phase: str = "initial",
    path: str = "shipments/1/orders",
    credited: bool = True,
    expired: bool = False,
    work: bool = False,
) -> tuple[Plans, list[str], Callable[[], Awaitable[httpx.Response]]]:
    credited_source = source if source in CAPS else "shipments"
    budget = {s: {"physical_attempts": cap, "consumed": 0} for s, cap in CAPS.items()}
    budget["full_withdrawals"] = {"physical_attempts": 0, "consumed": 0}
    incremental = dict.fromkeys((*CAPS, "full_withdrawals"), 0)
    if phase == "maintenance":
        incremental[credited_source] = 1
    else:
        budget[credited_source]["consumed"] = 1
    credit = {EXECUTION: {credited_source if credited else "questions": {phase: 1}}}
    plans = Plans(
        plan(
            execution_consumed=1,
            execution_charged=credit,
            total_budget=2000,
            total_consumed=0 if phase == "maintenance" else 1,
            budget=budget,
            incremental_consumed=1 if phase == "maintenance" else 0,
            incremental_source_consumed=incremental,
            incremental_day=NOW.date().isoformat(),
            incremental_policy={"max_daily_total": 500, "max_daily_source": 300},
            execution_until=NOW - timedelta(seconds=1) if expired else NOW + timedelta(minutes=90),
            cutoff=NOW - timedelta(days=12),
            checkpoints={"shipments": {"synthetic": "preserve"}},
        )
    )
    sends: list[str] = []

    def transport(upstream: httpx.Request) -> httpx.Response:
        assert upstream.headers.get("X-New-Domain") == "true"
        assert "X-Zeler-History-Trace" not in upstream.headers
        assert "X-Zeler-History-Work" not in upstream.headers
        sends.append(upstream.url.path)
        return httpx.Response(200, json=[{"order_id": 1, "seller_id": int(SELLER)}])

    async def forward() -> httpx.Response:
        req = request(
            plans,
            headers={
                "X-Zeler-History-Trace": f"h1-{EXECUTION}:{source}:{phase}",
                "X-Zeler-Proxy-Retry": "disabled",
                "X-New-Domain": "true",
                **({"X-Zeler-History-Work": "b" * 32} if work else {}),
            },
        )
        req._body = b""
        req.app.state.proxy_http_client_factory = lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(transport)
        )
        return await proxy._forward_to_meli(request=req, full_path=path, access_token=TEST_ACCESS)

    return plans, sends, forward


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["initial", "maintenance"])
async def test_h1_relationship_reserves_only_one_existing_shipment_credit(phase: str) -> None:
    # Verify the existing public contract rather than inventing a fifteenth scope.
    seed = json.loads(
        (
            Path(__file__).parents[2] / "infra/mongo/seeds/module_registry.admin_clients.json"
        ).read_text()
    )
    sheets = next(row for row in seed["documents"] if row["_id"] == "sheets")
    scopes = sheets["allowed_meli_scopes"]
    assert len(scopes) == 14 and "GET /shipments/*" in scopes
    assert not any("fulfillment/operations" in scope for scope in scopes)
    assert len(sheets["routing_keys"]) == 6
    assert proxy._scope_matches(method="GET", path="/shipments/1/orders", allowed_scopes=scopes)
    plans, sends, forward = setup(phase=phase)
    before = copy.deepcopy(plans.row)
    results = await asyncio.gather(*(forward() for _ in range(3)), return_exceptions=True)
    assert (
        sum(isinstance(result, httpx.Response) and result.status_code == 200 for result in results)
        == 1
    )
    assert sum(isinstance(result, proxy.HistoryPolicyRejectedError) for result in results) == 2
    assert sends == ["/shipments/1/orders"] and len(plans.updates) == 1
    assert plans.row is not None and before is not None
    assert plans.updates == [
        {
            "$inc": {
                "execution_sent": 1,
                f"execution_sent_by_source.{EXECUTION}.shipments.{phase}": 1,
            }
        }
    ]
    assert plans.row["execution_consumed"] == plans.row["execution_sent"] == 1
    assert plans.row["execution_sent_by_source"] == {EXECUTION: {"shipments": {phase: 1}}}
    assert {
        k: v
        for k, v in plans.row.items()
        if k not in {"execution_sent", "execution_sent_by_source"}
    } == {
        k: v for k, v in before.items() if k not in {"execution_sent", "execution_sent_by_source"}
    }


@pytest.mark.asyncio
async def test_work_relationship_is_rejected_before_resolver_or_reservation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    async def forbidden(*args: Any, **kwargs: Any) -> Any:
        nonlocal called
        called = True
        raise AssertionError("work relationship must remain outside existing purpose")

    monkeypatch.setattr(proxy, "reserve_history_work_send", forbidden)
    plans, sends, forward = setup(work=True)
    before = copy.deepcopy(plans.row)
    with pytest.raises(proxy.HistoryPolicyRejectedError):
        await forward()
    assert called is False and sends == [] and plans.updates == [] and plans.row == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "wrong_source",
        "invalid_phase",
        "no_credit",
        "non_decimal",
        "extra_child",
        "deadline",
        "full",
    ],
)
async def test_relationship_rejects_unowned_unfunded_or_malformed_context(case: str) -> None:
    plans, sends, forward = setup(
        source="orders"
        if case == "wrong_source"
        else "full_withdrawals"
        if case == "full"
        else "shipments",
        phase="refund" if case == "invalid_phase" else "initial",
        path="shipments/abc/orders"
        if case == "non_decimal"
        else "shipments/1/orders/extra"
        if case == "extra_child"
        else "shipments/1/orders",
        credited=case != "no_credit",
        expired=case == "deadline",
    )
    before = copy.deepcopy(plans.row)
    expected = (
        proxy.PilotGetBudgetWaitError
        if case in {"invalid_phase", "full"}
        else proxy.HistoryPolicyRejectedError
    )
    with pytest.raises(expected):
        await forward()
    assert sends == [] and plans.updates == [] and plans.row == before
