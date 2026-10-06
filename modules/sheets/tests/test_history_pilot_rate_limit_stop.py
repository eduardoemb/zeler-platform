"""Scoped pilot 429 stops before another charged dispatch; ordinary stays ordinary."""

from __future__ import annotations

import copy
import os
import socket
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from gateway.tests.test_pilot_get_budget import NOW, matches
from gateway.tests.test_pilot_get_budget_allocation import (
    INITIAL,
    PATHS,
    AllocationPlans,
    Physical,
    allocation_plan,
    guard,
)

from zeler_platform_core.clients.meli_gateway_client import GatewayRateLimitError
from zeler_sheets.formulas.pacing import HistoryPolicyWaitError


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(os, "environ", {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path)})

    def denied(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("no sockets")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)


class PausingPlans(AllocationPlans):
    def __init__(self, row: dict[str, Any]) -> None:
        super().__init__(row)
        self.pauses: list[dict[str, Any]] = []
        self.replace_epoch = False

    async def update_one(self, query: dict[str, Any], update: dict[str, Any]) -> Any:
        if update == {"$set": {"state": "paused"}}:
            async with self.lock:
                if self.replace_epoch:
                    assert self.row is not None
                    self.row["execution_id"] = "b" * 32
                if self.row is None or not matches(self.row, query):
                    return SimpleNamespace(matched_count=0)
                self.row["state"] = "paused"
                self.pauses.append(copy.deepcopy(query))
                return SimpleNamespace(matched_count=1)
        return await super().update_one(query, update)


class Remote(Physical):
    def __init__(self, metadata: str | None = "1") -> None:
        self.clock = NOW
        self.calls = 0
        self.metadata = metadata

    async def fetch_resource(self, **kwargs: Any) -> Any:
        return await self.fetch_resource_once(**kwargs)

    async def fetch_resource_once(self, **kwargs: Any) -> Any:
        return await self.request(**kwargs)

    async def request(self, **kwargs: Any) -> Any:
        self.calls += 1
        response = httpx.Response(
            429,
            headers={
                "Retry-After": "1",
                **(
                    {"X-Zeler-Upstream-Attempts": self.metadata}
                    if self.metadata is not None
                    else {}
                ),
            },
            request=httpx.Request("GET", "https://offline.invalid/"),
        )
        raise GatewayRateLimitError(retry_after_seconds=1, response=response)


@pytest.mark.asyncio
@pytest.mark.parametrize("source", INITIAL)
@pytest.mark.parametrize("interface", ["fetch", "request"])
async def test_pilot_each_source_stops_on_first_remote_429(source: str, interface: str) -> None:
    plans, remote = PausingPlans(allocation_plan()), Remote()
    worker = guard(plans, remote, source, "initial")
    before = copy.deepcopy(plans.row)
    with pytest.raises(HistoryPolicyWaitError):
        if interface == "fetch":
            await worker.fetch_resource(seller_id=worker.seller, path="/" + PATHS[source])
        else:
            await worker.request(method="GET", seller_id=worker.seller, path="/" + PATHS[source])
    assert remote.calls == 1 and len(plans.pauses) == 1
    assert plans.row is not None and before is not None
    assert plans.row["state"] == "paused" and plans.row["execution_consumed"] == 1
    assert plans.row["budget"][source]["consumed"] == before["budget"][source]["consumed"] + 1
    assert plans.row["execution_until"] == before["execution_until"]


@pytest.mark.asyncio
@pytest.mark.parametrize("metadata", [None, "0", "2", "bad"])
async def test_unproven_or_local_429_never_becomes_remote_proof_or_retry(
    metadata: str | None,
) -> None:
    plans, remote = PausingPlans(allocation_plan()), Remote(metadata)
    worker = guard(plans, remote, "orders", "initial")
    with pytest.raises(HistoryPolicyWaitError) as caught:
        await worker.fetch_resource(seller_id=worker.seller, path="/orders/1")
    assert "remote_429" not in str(caught.value)
    assert remote.calls == 1


@pytest.mark.asyncio
async def test_new_epoch_race_is_not_paused_by_old_response() -> None:
    plans, remote = PausingPlans(allocation_plan()), Remote()
    plans.replace_epoch = True
    worker = guard(plans, remote, "orders", "initial")
    with pytest.raises(HistoryPolicyWaitError):
        await worker.fetch_resource(seller_id=worker.seller, path="/orders/1")
    assert plans.row is not None and plans.row["execution_id"] == "b" * 32
    assert plans.row["state"] == "active" and plans.pauses == [] and remote.calls == 1


@pytest.mark.asyncio
async def test_ordinary_plan_without_execution_id_keeps_original_exception() -> None:
    row = allocation_plan()
    del row["execution_id"]
    plans, remote = PausingPlans(row), Remote()
    worker = guard(plans, remote, "orders", "initial")
    with pytest.raises(GatewayRateLimitError):
        await worker.fetch_resource(seller_id=worker.seller, path="/orders/1")
    assert plans.pauses == [] and remote.calls == 1


@pytest.mark.asyncio
async def test_last_execution_credit_remains_consumed_after_stop() -> None:
    plans, remote = PausingPlans(allocation_plan(execution_attempt_limit=1)), Remote()
    worker = guard(plans, remote, "orders", "initial")
    with pytest.raises(HistoryPolicyWaitError):
        await worker.fetch_resource(seller_id=worker.seller, path="/orders/1")
    assert plans.row is not None and plans.row["execution_consumed"] == 1
    assert plans.row["execution_attempt_limit"] == 1 and plans.row["state"] == "paused"
    assert remote.calls == 1


@pytest.mark.asyncio
async def test_response_after_deadline_cannot_renew_execution_or_retry() -> None:
    class LateRemote(Remote):
        async def request(self, **kwargs: Any) -> Any:
            from datetime import timedelta

            self.clock = NOW + timedelta(hours=2)
            return await super().request(**kwargs)

    plans, remote = PausingPlans(allocation_plan()), LateRemote()
    before = copy.deepcopy(plans.row)
    worker = guard(plans, remote, "orders", "initial")
    with pytest.raises(HistoryPolicyWaitError):
        await worker.fetch_resource(seller_id=worker.seller, path="/orders/1")
    assert plans.row is not None and before is not None
    assert plans.row["execution_until"] == before["execution_until"]
    assert plans.row["state"] == "paused" and remote.calls == 1
