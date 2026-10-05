"""Real transaction proof. A skip is non-acceptance, never a passing CAS claim."""

from __future__ import annotations

import asyncio
import ipaddress
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from pymongo import monitoring
from pymongo.errors import ConfigurationError
from pymongo.uri_parser import parse_uri

from zeler_platform_core import history_work_intent as work
from zeler_platform_core.events.idempotency import scoped_processed_event_id
from zeler_platform_core.history_onboarding import PLAN_COLLECTION

NOW = datetime(2026, 10, 5, 20, tzinfo=UTC)
EXECUTION, NONCE, OWNER = "a" * 32, "b" * 32, "c" * 32
KEY = "orders_v2:/orders/42:event-1"


class Listener(monitoring.CommandListener):
    snapshot = False
    majority = False

    def started(self, event: Any) -> None:
        self.snapshot |= event.command.get("readConcern", {}).get("level") == "snapshot"
        if event.command_name == "commitTransaction":
            self.majority |= event.command.get("writeConcern", {}).get("w") == "majority"

    def succeeded(self, event: Any) -> None:
        pass

    failed = succeeded


@asynccontextmanager
async def database() -> AsyncIterator[tuple[Any, Listener]]:
    if "MONGO_URI" in os.environ:
        pytest.skip("ambient Mongo target rejected; non-acceptance")
    uri = os.environ.get("ZELER_RS0_TEST_URI")
    if not uri:
        pytest.skip("explicit local rs0 target required; non-acceptance")
    try:
        hosts = parse_uri(uri).get("nodelist", [])
        assert hosts and all(ipaddress.ip_address(host).is_loopback for host, _ in hosts)
    except (ConfigurationError, ValueError, AssertionError):
        pytest.skip("non-loopback target rejected before connection; non-acceptance")
    from motor.motor_asyncio import AsyncIOMotorClient

    listener = Listener()
    client: Any = AsyncIOMotorClient(uri, event_listeners=[listener], serverSelectionTimeoutMS=2000)
    name = "zeler_work_rs0_" + uuid4().hex
    try:
        hello = await client.admin.command("hello")
        assert hello.get("isWritablePrimary") and hello.get("setName") == "rs0"
        assert hello.get("logicalSessionTimeoutMinutes") is not None
        db = client[name]
        claim_id = scoped_processed_event_id(KEY, "zeler.sheets.events")
        await db["webhook_events"].insert_one(
            {
                "_id": "event-1",
                "topic": "orders_v2",
                "classification": "orders_v2",
                "resource": "/orders/42",
                "user_id": 82,
                "received_at": NOW,
            }
        )
        await db["processed_event_claims"].insert_one(
            {
                "_id": claim_id,
                "idempotency_key": KEY,
                "module_id": "sheets",
                "consumer_id": "zeler.sheets.events",
                "owner_token": OWNER,
                "expires_at": NOW + timedelta(minutes=2),
            }
        )
        intent = await work.resolve_history_work_intent(
            db,
            event_id="event-1",
            seller_id="82",
            event_type="orders.updated",
            resource="/orders/42",
            claim_identity={
                "processing_key": KEY,
                "module_id": "sheets",
                "consumer_id": "zeler.sheets.events",
                "owner_token": OWNER,
            },
            now=NOW,
        )
        await db[PLAN_COLLECTION].insert_one(
            {
                "_id": "82",
                "seller_id": "82",
                "policy_version": "history-on-link-v1",
                "authority": {"kind": "account_link_policy"},
                "state": "active",
                "eligible": True,
                "sources": ["orders"],
                "execution_id": EXECUTION,
                "execution_consumed": 1,
                "execution_attempt_limit": 1,
                "execution_until": NOW + timedelta(minutes=3),
                "execution_utc_day": "2026-10-05",
                "execution_work": {NONCE: {**intent.receipt("/orders/42"), "credit": 1, "sent": 0}},
                "incremental_consumed": 1,
                "incremental_source_consumed": {"orders": 1},
                "cutoff": NOW - timedelta(days=1),
            }
        )
        yield db, listener
    finally:
        await client.drop_database(name)
        client.close()


async def send(db: Any) -> Any:
    return await work.reserve_history_work_send(
        db,
        seller_id="82",
        execution=EXECUTION,
        source="orders",
        phase="maintenance",
        work_id=NONCE,
        path="/orders/42",
        now=NOW,
    )


@pytest.mark.asyncio
async def test_last_nonce_concurrency_is_one_send_without_second_charge() -> None:
    async with database() as (db, listener):
        results = await asyncio.gather(send(db), send(db), return_exceptions=True)
        assert sum(isinstance(v, dict) for v in results) == 1
        assert sum(isinstance(v, work.HistoryWorkWaitError) for v in results) == 1
        plan = await db[PLAN_COLLECTION].find_one({"_id": "82"})
        assert plan["execution_sent"] == plan["execution_consumed"] == 1
        assert plan["incremental_consumed"] == plan["incremental_source_consumed"]["orders"] == 1
        assert plan["execution_work"][NONCE]["sent"] == 1
        assert "execution_charged" not in plan and "execution_sent_by_source" not in plan
        claim = await db["processed_event_claims"].find_one({"idempotency_key": KEY})
        assert claim["history_dispatch_fence"] == 1
        assert claim["expires_at"] == (NOW + timedelta(minutes=2)).replace(tzinfo=None)
        assert listener.snapshot and listener.majority


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"state": "paused"},
        {"execution_until": NOW},
        {"execution_utc_day": "2026-10-04"},
        {"execution_attempt_limit": 0},
        {f"execution_work.{NONCE}.credit": True},
        {"execution_sent": -1},
    ],
)
async def test_failed_plan_cas_rolls_back_owner_touch_preserving_charge(
    changes: dict[str, Any],
) -> None:
    async with database() as (db, _):
        await db[PLAN_COLLECTION].update_one({"_id": "82"}, {"$set": changes})
        with pytest.raises(work.HistoryWorkWaitError):
            await send(db)
        plan = await db[PLAN_COLLECTION].find_one({"_id": "82"})
        claim = await db["processed_event_claims"].find_one({"idempotency_key": KEY})
        assert plan["execution_consumed"] == plan["incremental_consumed"] == 1
        assert plan["execution_work"][NONCE]["sent"] == 0
        assert "history_dispatch_fence" not in claim


@pytest.mark.asyncio
async def test_takeover_after_snapshot_read_conflicts_before_send_reservation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = work.validate_history_work_receipt
    read_done, replaced = asyncio.Event(), asyncio.Event()

    async def pause(db: Any, receipt: Any, **kwargs: Any) -> Any:
        await original(db, receipt, **{**kwargs, "touch": False})
        read_done.set()
        await asyncio.wait_for(replaced.wait(), timeout=3)
        return await original(db, receipt, **kwargs)

    async with database() as (db, _):
        monkeypatch.setattr(work, "validate_history_work_receipt", pause)
        task = asyncio.create_task(send(db))
        await asyncio.wait_for(read_done.wait(), timeout=3)
        await db["processed_event_claims"].update_one(
            {"idempotency_key": KEY}, {"$set": {"owner_token": "d" * 32}}
        )
        replaced.set()
        with pytest.raises(work.HistoryWorkWaitError):
            await task
        plan = await db[PLAN_COLLECTION].find_one({"_id": "82"})
        assert plan["execution_work"][NONCE]["sent"] == 0 and plan.get("execution_sent", 0) == 0
        assert plan["execution_consumed"] == 1


@pytest.mark.asyncio
async def test_h1_without_work_reference_cannot_use_a_work_prepayment() -> None:
    from types import SimpleNamespace

    from starlette.requests import Request

    from zeler_gateway.proxy.router import HistoryPolicyRejectedError, _reserve_history_send

    async with database() as (db, _):
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/proxy/meli/orders/42",
                "headers": [
                    (b"x-zeler-history-trace", f"h1-{EXECUTION}:orders:maintenance".encode()),
                    (b"x-zeler-proxy-retry", b"disabled"),
                ],
                "app": SimpleNamespace(
                    state=SimpleNamespace(mongo_db=db, proxy_wait_now=lambda: NOW)
                ),
            }
        )
        request.state.history_module_id = "sheets"
        request.state.history_seller_id = "82"
        with pytest.raises(HistoryPolicyRejectedError):
            await _reserve_history_send(request, "orders/42")
        await send(db)
        plan = await db[PLAN_COLLECTION].find_one({"_id": "82"})
        assert plan["execution_sent"] == plan["execution_consumed"] == 1


@pytest.mark.asyncio
async def test_replay_job_takeover_between_read_and_touch_aborts_all_fences(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = work.validate_history_work_receipt
    read_done, replaced = asyncio.Event(), asyncio.Event()

    async def pause(db: Any, receipt: Any, **kwargs: Any) -> Any:
        await original(db, receipt, **{**kwargs, "touch": False})
        read_done.set()
        await asyncio.wait_for(replaced.wait(), timeout=3)
        return await original(db, receipt, **kwargs)

    async with database() as (db, _):
        key = "sync-job:job-1:event-1"
        await db["processed_event_claims"].delete_many({})
        await db["processed_event_claims"].insert_one(
            {
                "_id": scoped_processed_event_id(key, "zeler.sheets.events"),
                "idempotency_key": key,
                "module_id": "sheets",
                "consumer_id": "zeler.sheets.events",
                "owner_token": OWNER,
                "expires_at": NOW + timedelta(minutes=2),
            }
        )
        await db["sheets_sync_jobs"].insert_one(
            {
                "_id": "job-1",
                "seller_id": "82",
                "state": "running",
                "attempt_token": "d" * 32,
                "fence": 1,
                "lease_until": NOW + timedelta(minutes=2),
                "requested_at": NOW - timedelta(minutes=1),
                "delta_through_at": NOW,
            }
        )
        receipt = (await db[PLAN_COLLECTION].find_one({"_id": "82"}))["execution_work"][NONCE]
        receipt["claim_identity"]["processing_key"] = key
        receipt["job_identity"] = {"_id": "job-1", "attempt_token": "d" * 32, "fence": 1}
        await db[PLAN_COLLECTION].update_one(
            {"_id": "82"}, {"$set": {f"execution_work.{NONCE}": receipt}}
        )
        monkeypatch.setattr(work, "validate_history_work_receipt", pause)
        task = asyncio.create_task(send(db))
        await asyncio.wait_for(read_done.wait(), timeout=3)
        await db["sheets_sync_jobs"].update_one(
            {"_id": "job-1"}, {"$set": {"attempt_token": "e" * 32}, "$inc": {"fence": 1}}
        )
        replaced.set()
        with pytest.raises(work.HistoryWorkWaitError):
            await task
        plan = await db[PLAN_COLLECTION].find_one({"_id": "82"})
        claim = await db["processed_event_claims"].find_one({"idempotency_key": key})
        job = await db["sheets_sync_jobs"].find_one({"_id": "job-1"})
        assert plan["execution_work"][NONCE]["sent"] == 0 and plan["execution_consumed"] == 1
        assert "history_dispatch_fence" not in claim and "history_dispatch_fence" not in job
        assert job["fence"] == 2 and job["attempt_token"] == "e" * 32


@pytest.mark.asyncio
async def test_work_charge_real_client_and_late_reservation_share_one_budget() -> None:
    from types import SimpleNamespace
    from typing import cast

    import httpx
    from starlette.requests import Request

    from zeler_gateway.proxy.router import HistoryPolicyRejectedError, _reserve_history_send
    from zeler_platform_core.clients.meli_gateway_client import MeliGatewayClient
    from zeler_sheets.formulas.pacing import HistoryPolicyWaitError
    from zeler_sheets.history_onboarding import PlanBudgetGateway

    async with database() as (db, _):
        await db["meli_accounts"].insert_one({"seller_id": 82, "status": "active"})
        await db[PLAN_COLLECTION].update_one(
            {"_id": "82"},
            {
                "$set": {
                    "execution_attempt_limit": 2,
                    "incremental_day": "2026-10-05",
                    "incremental_policy": {"max_daily_total": 500, "max_daily_source": 300},
                }
            },
        )
        identity = {
            "processing_key": KEY,
            "module_id": "sheets",
            "consumer_id": "zeler.sheets.events",
            "owner_token": OWNER,
        }
        intent = await work.resolve_history_work_intent(
            db,
            event_id="event-1",
            seller_id="82",
            event_type="orders.updated",
            resource="/orders/42",
            claim_identity=identity,
            now=NOW,
        )
        proxy_calls: list[httpx.Request] = []
        provider_invocations: list[str] = []

        async def transport(call: httpx.Request) -> httpx.Response:
            proxy_calls.append(call)
            assert call.headers["X-Zeler-Proxy-Retry"] == "disabled"
            request = Request(
                {
                    "type": "http",
                    "method": "GET",
                    "path": "/proxy/meli/orders/42",
                    "headers": [(name.lower(), value) for name, value in call.headers.raw],
                    "app": SimpleNamespace(
                        state=SimpleNamespace(mongo_db=db, proxy_wait_now=lambda: NOW)
                    ),
                }
            )
            request.state.history_module_id = "sheets"
            request.state.history_seller_id = "82"
            try:
                await _reserve_history_send(request, "orders/42")
            except HistoryPolicyRejectedError:
                return httpx.Response(
                    412,
                    json={"error": "history_policy_wait"},
                    headers={
                        "X-Zeler-History-Policy-Status": "wait",
                        "X-Zeler-Upstream-Attempts": "0",
                    },
                )
            assert request.state.history_upstream_attempts == 1
            provider_invocations.append("orders/42")
            return httpx.Response(200, json={"id": 42}, headers={"X-Zeler-Upstream-Attempts": "1"})

        class Auth:
            async def get_token_for_seller(self, seller_id: str) -> str:
                assert seller_id == "82"
                return "synthetic-only"

        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
            client = MeliGatewayClient(
                "https://gateway.test/proxy/meli", cast(Any, Auth()), http_client=http
            )
            guarded = PlanBudgetGateway(
                db, client, "82", "orders", work_intent=intent, now=lambda: NOW
            )
            assert await guarded.fetch_resource(seller_id="82", path="/orders/42") == {"id": 42}
            with pytest.raises(HistoryPolicyWaitError):
                await guarded.fetch_resource(seller_id="82", path="/orders/42")
        assert len(proxy_calls) == len(provider_invocations) == 1
        plan = await db[PLAN_COLLECTION].find_one({"_id": "82"})
        nonce = proxy_calls[0].headers["X-Zeler-History-Work"]
        assert nonce != NONCE and plan["execution_work"][nonce]["sent"] == 1
        assert plan["execution_consumed"] == plan["incremental_consumed"] == 2
        assert plan["incremental_source_consumed"]["orders"] == 2 and plan["execution_sent"] == 1
        assert "execution_charged" not in plan
