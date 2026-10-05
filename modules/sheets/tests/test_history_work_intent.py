"""Offline integration of durable work intent, physical charge and deferred WAIT.

No sockets, real Mongo, provider, broker or shared worker client mutations.
The coordinator owns real transaction/fencing verification in a fresh replica set.
"""

from __future__ import annotations

import asyncio
import copy
import re
import socket
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from zeler_platform_core.history_work_intent import HistoryWorkWaitError
from zeler_sheets import consumer
from zeler_sheets.consumer import SheetsEvent, SheetsEventHandler
from zeler_sheets.formulas.pacing import HistoryPolicyWaitError, PacedMeliGateway
from zeler_sheets.history_onboarding import PlanBudgetGateway
from zeler_sheets.sync_jobs_processor import SyncJobsProcessor

NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)
SELLER = "82453304"
EXECUTION = "a" * 32
SOURCES = ("orders", "questions", "shipments", "messages", "claims_returns", "full_withdrawals")


def lookup(row: dict[str, Any], path: str) -> Any:
    value: Any = row
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def expression(row: dict[str, Any], value: Any) -> Any:
    if isinstance(value, str) and value.startswith("$"):
        return lookup(row, value[1:])
    if not isinstance(value, dict):
        return value
    if "$ifNull" in value:
        first, second = value["$ifNull"]
        result = expression(row, first)
        return second if result is None else result
    if "$and" in value:
        return all(expression(row, part) for part in value["$and"])
    for operator in ("$lt", "$lte"):
        if operator in value:
            first, second = [expression(row, part) for part in value[operator]]
            return first < second if operator == "$lt" else first <= second
    raise AssertionError("unsupported fake expression")


def matches(row: dict[str, Any], query: dict[str, Any]) -> bool:
    for key, expected in query.items():
        if key == "$and":
            if not all(matches(row, part) for part in expected):
                return False
        elif key == "$or":
            if not any(matches(row, part) for part in expected):
                return False
        elif key == "$expr":
            if not expression(row, expected):
                return False
        else:
            actual = lookup(row, key)
            if isinstance(expected, dict):
                for operator, bound in expected.items():
                    if operator == "$exists" and (actual is not None) != bound:
                        return False
                    if operator == "$type":
                        kind = dict if bound == "object" else int
                        if type(actual) is not kind:
                            return False
                    if operator == "$in" and actual not in bound:
                        return False
                    if operator == "$gte" and (actual is None or actual < bound):
                        return False
                    if operator == "$gt":
                        normalized = (
                            actual.replace(tzinfo=UTC)
                            if isinstance(actual, datetime) and actual.tzinfo is None
                            else actual
                        )
                        if normalized is None or normalized <= bound:
                            return False
            elif isinstance(actual, list):
                if expected not in actual:
                    return False
            elif actual != expected:
                return False
    return True


def allocation_plan(**changes: Any) -> dict[str, Any]:
    return {
        "_id": SELLER,
        "seller_id": SELLER,
        "policy_version": "history-on-link-v1",
        "authority": {"kind": "account_link_policy"},
        "state": "active",
        "eligible": True,
        "sources": list(SOURCES[:-1]),
        "execution_id": EXECUTION,
        "execution_until": NOW + timedelta(minutes=90),
        "execution_utc_day": NOW.date().isoformat(),
        "execution_attempt_limit": 2500,
        "execution_consumed": 0,
        "execution_sent": 0,
        "total_consumed": 17,
        "total_budget": 2017,
        "budget": {source: {"consumed": 3, "physical_attempts": 1003} for source in SOURCES},
        "incremental_day": NOW.date().isoformat(),
        "incremental_consumed": 19,
        "incremental_source_consumed": dict.fromkeys(SOURCES, 3),
        "incremental_policy": {"max_daily_total": 519, "max_daily_source": 303},
        "checkpoints": {"orders": 8},
        "cutoff": NOW - timedelta(days=2),
        "lease_token": "synthetic-plan-owner",
        "lease_until": NOW + timedelta(minutes=1),
        **changes,
    }


class Account:
    async def find_one(self, query: dict[str, Any]) -> Any:
        return {"seller_id": int(SELLER), "status": "active"}


@pytest.fixture(autouse=True)
def forbid_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("work intent integration must not open sockets")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


def put(row: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    for part in parts[:-1]:
        row = row.setdefault(part, {})
    row[parts[-1]] = copy.deepcopy(value)


class Plans:
    """Lock-protected CAS shape; mixed inc/set is one operation, not proof of Mongo."""

    def __init__(self, **changes: Any) -> None:
        self.row = allocation_plan(**changes)
        self.lock = asyncio.Lock()
        self.updates: list[dict[str, Any]] = []

    async def find_one(self, query: dict[str, Any], **kwargs: Any) -> Any:
        return copy.deepcopy(self.row) if matches(self.row, query) else None

    async def update_one(self, query: dict[str, Any], update: dict[str, Any]) -> Any:
        day = query["incremental_day"]["$ne"]
        owned = {key: value for key, value in query.items() if key != "incremental_day"}
        async with self.lock:
            if not matches(self.row, owned) or self.row.get("incremental_day") == day:
                return SimpleNamespace(modified_count=0)
            for path, value in update.get("$set", {}).items():
                put(self.row, path, value)
            self.updates.append(copy.deepcopy(update))
            return SimpleNamespace(modified_count=1)

    async def find_one_and_update(
        self, query: dict[str, Any], update: dict[str, Any], **kwargs: Any
    ) -> Any:
        await asyncio.sleep(0)
        async with self.lock:
            if not matches(self.row, query):
                return None
            assert set(update) <= {"$inc", "$set"}
            for path, value in update.get("$inc", {}).items():
                put(self.row, path, (lookup(self.row, path) or 0) + value)
            for path, value in update.get("$set", {}).items():
                put(self.row, path, value)
            self.updates.append(copy.deepcopy(update))
            return copy.deepcopy(self.row)


class Intent:
    """Core interface double only; parent tests the durable resolver separately."""

    def __init__(self, source: str, *, denied: bool = False) -> None:
        self.source = source
        self.denied = denied
        self.live_checks: list[Any] = []

    async def assert_live(self, db: Any, now: Any) -> None:
        self.live_checks.append(now)
        if self.denied:
            raise HistoryWorkWaitError("work ownership unavailable")

    def receipt(self, path: str) -> dict[str, Any]:
        return {
            "event_id": "durable-event",
            "seller_id": SELLER,
            "event_type": "questions.new",
            "resource": "/questions/1",
            "claim_identity": {
                "processing_key": "durable-key",
                "owner_token": "b" * 32,
                "module_id": "sheets",
                "consumer_id": "zeler.sheets.events",
            },
            "source": self.source,
            "phase": "maintenance",
            "path": path,
        }


class Physical:
    def __init__(self, *, crash: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.crash = crash

    async def fetch_resource(self, **kwargs: Any) -> Any:
        raise AssertionError("work acquisitions require fetch_resource_once")

    async def fetch_resource_once(self, **kwargs: Any) -> Any:
        self.calls.append(copy.deepcopy(kwargs))
        if self.crash:
            raise RuntimeError("synthetic physical failure")
        return {"id": kwargs["path"].split("/", 2)[-1], "status": "active"}

    async def request(self, **kwargs: Any) -> Any:
        self.calls.append(copy.deepcopy(kwargs))
        return httpx.Response(200, headers={"X-Zeler-Upstream-Attempts": "1"})


def guard(plans: Plans, physical: Any, intent: Intent, *, now: Any = lambda: NOW) -> Any:
    return PlanBudgetGateway(
        {"sheets_history_backfill_plans": plans, "meli_accounts": Account()},
        physical,
        SELLER,
        intent.source,
        work_intent=cast(Any, intent),
        now=now,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("api", ["fetch", "request"])
async def test_work_charge_is_atomic_nonce_maintenance_and_not_fungible_h1(api: str) -> None:
    plans, physical, intent = Plans(), Physical(), Intent("questions")
    before = copy.deepcopy(plans.row)
    worker = guard(plans, physical, intent)
    if api == "fetch":
        await worker.fetch_resource(seller_id=SELLER, path="/questions/1")
    else:
        await worker.request(method="GET", seller_id=SELLER, path="/questions/1")
    assert intent.live_checks
    headers = physical.calls[0]["headers"]
    assert headers["X-Zeler-History-Trace"] == f"h1-{EXECUTION}:questions:maintenance"
    nonce = headers["X-Zeler-History-Work"]
    assert re.fullmatch(r"[a-f0-9]{32}", nonce)
    receipt = plans.row["execution_work"][nonce]
    assert receipt == {**intent.receipt("/questions/1"), "credit": 1, "sent": 0}
    assert "execution_charged" not in plans.row
    assert plans.row["execution_consumed"] == before["execution_consumed"] + 1
    assert plans.row["incremental_consumed"] == before["incremental_consumed"] + 1
    assert plans.row["incremental_source_consumed"]["questions"] == 4
    for key in ("budget", "total_consumed", "cutoff", "checkpoints", "lease_token", "lease_until"):
        assert plans.row[key] == before[key]
    assert any(
        f"execution_work.{nonce}" in operation.get("$set", {})
        and operation.get("$inc", {}).get("execution_consumed") == 1
        for operation in plans.updates
    )
    if api == "request":
        assert headers["X-Zeler-Proxy-Retry"] == "disabled"


@pytest.mark.asyncio
async def test_failed_attempt_keeps_credit_and_each_caller_retry_has_fresh_nonce() -> None:
    plans, physical, intent = Plans(), Physical(crash=True), Intent("questions")
    worker = guard(plans, physical, intent)
    for _ in range(3):
        with pytest.raises(RuntimeError, match="synthetic physical"):
            await worker.fetch_resource(seller_id=SELLER, path="/questions/1")
    nonces = [call["headers"]["X-Zeler-History-Work"] for call in physical.calls]
    assert len(set(nonces)) == 3 and len(plans.row["execution_work"]) == 3
    assert plans.row["execution_consumed"] == 3
    assert plans.row["incremental_consumed"] == 22
    assert all(receipt["sent"] == 0 for receipt in plans.row["execution_work"].values())
    assert "execution_charged" not in plans.row


@pytest.mark.asyncio
async def test_lost_work_lease_waits_before_charge_and_preserves_everything() -> None:
    plans, physical = Plans(), Physical()
    before = copy.deepcopy(plans.row)
    worker = guard(plans, physical, Intent("questions", denied=True))
    with pytest.raises(HistoryPolicyWaitError):
        await worker.fetch_resource(seller_id=SELLER, path="/questions/1")
    assert physical.calls == [] and plans.updates == [] and plans.row == before


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", ["global", "maintenance", "source"])
async def test_two_work_calls_compete_for_one_credit_without_fungible_refund(limit: str) -> None:
    fields: dict[str, Any] = {}
    if limit == "global":
        fields = {"execution_attempt_limit": 1}
    elif limit == "maintenance":
        fields = {"incremental_policy": {"max_daily_total": 20, "max_daily_source": 303}}
    else:
        fields = {"incremental_policy": {"max_daily_total": 519, "max_daily_source": 4}}
    plans, physical = Plans(**fields), Physical()
    workers = [guard(plans, physical, Intent("questions")) for _ in range(2)]
    outcomes = await asyncio.gather(
        *(worker.fetch_resource(seller_id=SELLER, path="/questions/1") for worker in workers),
        return_exceptions=True,
    )
    assert sum(isinstance(result, HistoryPolicyWaitError) for result in outcomes) == 1
    assert len(physical.calls) == 1 and len(plans.row["execution_work"]) == 1
    assert plans.row["execution_consumed"] == 1


@pytest.mark.asyncio
async def test_work_reserved_before_pacing_is_kept_but_not_sent_after_deadline() -> None:
    clock = [NOW]

    class Pacer:
        async def acquire(self, **kwargs: Any) -> bool:
            clock[0] += timedelta(minutes=91)
            return True

    plans, physical = Plans(), Physical()
    paced = PacedMeliGateway(inner=physical, pacer=cast(Any, Pacer()), lane="ranges")
    worker = guard(plans, paced, Intent("questions"), now=lambda: clock[0])
    with pytest.raises(HistoryPolicyWaitError):
        await worker.fetch_resource(seller_id=SELLER, path="/questions/1")
    assert plans.row["execution_consumed"] == 1
    assert len(plans.row["execution_work"]) == 1 and physical.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fields",
    [
        {"incremental_day": "2026-10-04"},
        {"incremental_consumed": -1},
        {"incremental_consumed": False},
        {"incremental_source_consumed": dict.fromkeys(SOURCES, -1)},
        {"incremental_source_consumed": dict.fromkeys(SOURCES, False)},
        {
            "incremental_source_consumed": dict.fromkeys(SOURCES, 0),
            "incremental_policy": {"max_daily_total": 519, "max_daily_source": True},
        },
        {"execution_id": True},
        {"execution_id": "z" * 32},
        {"execution_until": "not-a-date"},
        {"execution_work": None},
        {"execution_work": []},
        {"execution_work": "malformed"},
    ],
)
async def test_work_control_or_counter_drift_never_resets_or_charges(fields: Any) -> None:
    plans, physical = Plans(**fields), Physical()
    before = copy.deepcopy(plans.row)
    worker = guard(plans, physical, Intent("questions"))
    with pytest.raises(HistoryPolicyWaitError):
        await worker.fetch_resource(seller_id=SELLER, path="/questions/1")
    assert physical.calls == [] and plans.updates == [] and plans.row == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field",
    ["execution_until", "execution_utc_day", "execution_attempt_limit", "execution_consumed"],
)
async def test_work_missing_mandatory_control_never_creates_credit(field: str) -> None:
    plans, physical = Plans(), Physical()
    del plans.row[field]
    before = copy.deepcopy(plans.row)
    worker = guard(plans, physical, Intent("questions"))
    with pytest.raises(HistoryPolicyWaitError):
        await worker.fetch_resource(seller_id=SELLER, path="/questions/1")
    assert physical.calls == [] and plans.updates == [] and plans.row == before


@pytest.mark.asyncio
async def test_one_work_wrapper_never_reuses_nonce_across_concurrent_physical_calls() -> None:
    class Pacer:
        async def acquire(self, **kwargs: Any) -> bool:
            await asyncio.sleep(0)
            return True

    plans, physical = Plans(), Physical()
    paced = PacedMeliGateway(inner=physical, pacer=cast(Any, Pacer()), lane="ranges")
    worker = guard(plans, paced, Intent("questions"))
    await asyncio.gather(
        worker.fetch_resource(seller_id=SELLER, path="/questions/1"),
        worker.fetch_resource(seller_id=SELLER, path="/questions/1"),
    )
    nonces = [call["headers"]["X-Zeler-History-Work"] for call in physical.calls]
    assert len(set(nonces)) == 2
    assert set(nonces) == set(plans.row["execution_work"])


class Claims:
    def __init__(self) -> None:
        self.completed: set[str] = set()
        self.owners: dict[str, str] = {}
        self.rows: dict[str, dict[str, Any]] = {}

    async def claim(self, idempotency_key: str, *, owner_token: str, **kwargs: Any) -> Any:
        from zeler_platform_core.events.claims import ClaimOutcome

        key = idempotency_key
        if key in self.completed:
            return ClaimOutcome.COMPLETED
        assert key not in self.owners
        self.owners[key] = owner_token
        self.rows[key] = {
            "_id": f"zeler.sheets.events:{key}",
            "idempotency_key": key,
            "module_id": "sheets",
            "consumer_id": "zeler.sheets.events",
            "owner_token": owner_token,
            "claimed_at": NOW,
            "expires_at": NOW + timedelta(minutes=2),
        }
        return ClaimOutcome.CLAIMED

    async def complete(self, idempotency_key: str, *, owner_token: str, **kwargs: Any) -> bool:
        key = idempotency_key
        assert self.owners.pop(key) == owner_token
        self.completed.add(key)
        self.rows.pop(key, None)
        return True

    async def release(self, idempotency_key: str, *, owner_token: str, **kwargs: Any) -> bool:
        key = idempotency_key
        assert self.owners.pop(key) == owner_token
        self.rows.pop(key, None)
        return True


@pytest.mark.asyncio
async def test_concurrent_handler_deliveries_keep_local_sources_and_claim_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plans, physical, claims = Plans(), Physical(), Claims()
    resolved: list[dict[str, Any]] = []
    monkeypatch.setattr(consumer, "datetime", SimpleNamespace(now=lambda tz: NOW))

    async def resolve(db: Any, **kwargs: Any) -> Intent:
        resolved.append(copy.deepcopy(kwargs))
        identity = kwargs["claim_identity"]
        raw_topic = "questions" if kwargs["event_type"] == "questions.new" else "shipments"
        assert (
            identity["processing_key"] == f"{raw_topic}:{kwargs['resource']}:{kwargs['event_id']}"
        )
        assert identity["owner_token"] == claims.owners[identity["processing_key"]]
        assert identity["module_id"] == "sheets"
        return Intent("questions" if kwargs["event_type"] == "questions.new" else "shipments")

    monkeypatch.setattr(consumer, "resolve_history_work_intent", resolve)
    db = {
        "sheets_history_backfill_plans": plans,
        "meli_accounts": Account(),
        "sheets_exports": SimpleNamespace(find_one=AsyncMock(return_value=None)),
    }
    handler = SheetsEventHandler(
        db=db,
        gateway_client=physical,
        sheets_client=MagicMock(),
        idempotency_store=MagicMock(),
        event_persistence=SimpleNamespace(persist=AsyncMock()),
        event_claim_store=claims,
    )
    events = [
        SheetsEvent(
            "one", "questions.new", int(SELLER), "/questions/1", "questions:/questions/1:one"
        ),
        SheetsEvent(
            "two", "shipments.updated", int(SELLER), "/shipments/2", "shipments:/shipments/2:two"
        ),
    ]
    assert await asyncio.gather(*(handler.handle(event) for event in events)) == [
        "no_export",
        "no_export",
    ]
    assert handler._gateway_client is physical
    assert {call["headers"]["X-Zeler-History-Trace"] for call in physical.calls} == {
        f"h1-{EXECUTION}:questions:maintenance",
        f"h1-{EXECUTION}:shipments:maintenance",
    }
    assert len(resolved) == 2 and len(plans.row["execution_work"]) == 2
    assert await handler.handle(events[0]) == "duplicate"
    assert len(physical.calls) == 2


@pytest.mark.asyncio
async def test_pilot_legacy_claim_cannot_create_work_authority() -> None:
    plans, physical = Plans(), Physical()
    handler = SheetsEventHandler(
        db={"sheets_history_backfill_plans": plans},
        gateway_client=physical,
        sheets_client=MagicMock(),
        idempotency_store=SimpleNamespace(is_duplicate=AsyncMock(return_value=False)),
    )
    before = copy.deepcopy(plans.row)
    with pytest.raises(HistoryPolicyWaitError):
        await handler.handle(
            SheetsEvent("event", "questions.new", int(SELLER), "/questions/1", "key")
        )
    assert physical.calls == [] and plans.row == before


@pytest.mark.asyncio
async def test_durable_resolver_wait_releases_real_claim_without_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plans, physical, claims = Plans(), Physical(), Claims()

    async def resolve(db: Any, **kwargs: Any) -> Any:
        raise HistoryWorkWaitError("unknown durable source")

    monkeypatch.setattr(consumer, "resolve_history_work_intent", resolve)
    handler = SheetsEventHandler(
        db={"sheets_history_backfill_plans": plans},
        gateway_client=physical,
        sheets_client=MagicMock(),
        idempotency_store=MagicMock(),
        event_claim_store=claims,
    )
    with pytest.raises(HistoryPolicyWaitError):
        await handler.handle(SheetsEvent("event", "items.updated", int(SELLER), "/items/1", "key"))
    assert claims.owners == {} and claims.completed == set() and physical.calls == []


@pytest.mark.asyncio
async def test_real_core_resolver_and_handler_preserve_publisher_key_and_maintenance_charge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(consumer, "datetime", SimpleNamespace(now=lambda tz: NOW))
    plans, physical, claims = Plans(), Physical(), Claims()
    event_row: dict[str, Any] = {
        "_id": "one",
        "topic": "questions",
        "classification": "questions",
        "resource": "/questions/1",
        "user_id": int(SELLER),
        "received_at": NOW,
    }

    async def find_event(query: dict[str, Any], **kwargs: Any) -> Any:
        return event_row if matches(event_row, query) else None

    async def find_claim(query: dict[str, Any], **kwargs: Any) -> Any:
        return next((row for row in claims.rows.values() if matches(row, query)), None)

    handler = SheetsEventHandler(
        db={
            "sheets_history_backfill_plans": plans,
            "meli_accounts": Account(),
            "webhook_events": SimpleNamespace(find_one=find_event),
            "processed_event_claims": SimpleNamespace(find_one=find_claim),
            "sheets_exports": SimpleNamespace(find_one=AsyncMock(return_value=None)),
        },
        gateway_client=physical,
        sheets_client=MagicMock(),
        idempotency_store=MagicMock(),
        event_persistence=SimpleNamespace(persist=AsyncMock()),
        event_claim_store=claims,
    )
    key = "questions:/questions/1:one"
    event = SheetsEvent("one", "questions.new", int(SELLER), "/questions/1", key)
    assert await handler.handle(event) == "no_export"
    assert claims.completed == {key} and claims.rows == {}
    nonce = physical.calls[0]["headers"]["X-Zeler-History-Work"]
    receipt = plans.row["execution_work"][nonce]
    assert receipt["claim_identity"]["processing_key"] == key
    assert receipt["source"] == "questions" and receipt["phase"] == "maintenance"
    assert plans.row["incremental_consumed"] == 20
    assert plans.row["execution_consumed"] == 1 and "execution_charged" not in plans.row
    assert await handler.handle(event) == "duplicate"
    assert len(physical.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source", "path"),
    [
        ("orders", "/orders/1"),
        ("questions", "/questions/1"),
        ("shipments", "/shipments/1/costs"),
        ("messages", "/messages/packs/1/sellers/82453304"),
        ("claims_returns", "/post-purchase/v1/claims/1"),
    ],
)
async def test_work_five_sources_share_maintenance_and_leave_initial_limits_intact(
    source: str, path: str
) -> None:
    plans, physical = Plans(), Physical()
    before = copy.deepcopy(plans.row)
    worker = guard(plans, physical, Intent(source))
    await worker.fetch_resource(seller_id=SELLER, path=path)
    assert plans.row["incremental_consumed"] == before["incremental_consumed"] + 1
    assert plans.row["incremental_source_consumed"][source] == 4
    assert plans.row["budget"] == before["budget"]
    assert plans.row["execution_consumed"] == before["execution_consumed"] + 1
    assert (
        physical.calls[0]["headers"]["X-Zeler-History-Trace"]
        == f"h1-{EXECUTION}:{source}:maintenance"
    )


@pytest.mark.asyncio
async def test_claim_event_order_dependency_stays_claims_returns_not_orders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(consumer, "datetime", SimpleNamespace(now=lambda tz: NOW))
    monkeypatch.setattr(
        consumer, "acquire_devoluciones_operation", AsyncMock(return_value=MagicMock())
    )
    monkeypatch.setattr(consumer, "maintain_devoluciones_heartbeat", lambda **kwargs: nullcontext())
    monkeypatch.setattr(consumer, "finish_devoluciones_operation", AsyncMock())
    monkeypatch.setattr(consumer, "project_claim", AsyncMock(return_value={"id": "1"}))
    monkeypatch.setattr(consumer, "is_terminal_cancellation_claim", lambda resource: False)
    plans, claims = Plans(), Claims()
    event_row: dict[str, Any] = {
        "_id": "one",
        "topic": "post_purchase",
        "classification": "post_purchase",
        "resource": "/post-purchase/v1/claims/1",
        "raw_body": {"actions": ["claims"]},
        "user_id": int(SELLER),
        "received_at": NOW,
    }

    async def find_event(query: dict[str, Any], **kwargs: Any) -> Any:
        return event_row if matches(event_row, query) else None

    async def find_claim(query: dict[str, Any], **kwargs: Any) -> Any:
        return next((row for row in claims.rows.values() if matches(row, query)), None)

    class ClaimPhysical(Physical):
        async def fetch_resource_once(self, **kwargs: Any) -> Any:
            self.calls.append(copy.deepcopy(kwargs))
            return {
                "/post-purchase/v1/claims/1": {"id": "1", "order_id": "2"},
                "/post-purchase/v2/claims/1/returns": {"results": []},
                "/orders/2": {"id": "2"},
            }[kwargs["path"]]

    physical = ClaimPhysical()
    handler = SheetsEventHandler(
        db={
            "sheets_history_backfill_plans": plans,
            "meli_accounts": Account(),
            "webhook_events": SimpleNamespace(find_one=find_event),
            "processed_event_claims": SimpleNamespace(find_one=find_claim),
            "sheets_exports": SimpleNamespace(find_one=AsyncMock(return_value=None)),
        },
        gateway_client=physical,
        sheets_client=MagicMock(),
        idempotency_store=MagicMock(),
        event_persistence=SimpleNamespace(persist=AsyncMock()),
        event_claim_store=claims,
    )
    event = SheetsEvent(
        "one",
        "claims.updated",
        int(SELLER),
        event_row["resource"],
        f"post_purchase:{event_row['resource']}:one",
    )
    assert await handler.handle(event) == "no_export"
    assert [call["path"] for call in physical.calls] == [
        "/post-purchase/v1/claims/1",
        "/post-purchase/v2/claims/1/returns",
        "/orders/2",
    ]
    assert {call["headers"]["X-Zeler-History-Trace"] for call in physical.calls} == {
        f"h1-{EXECUTION}:claims_returns:maintenance"
    }
    assert plans.row["incremental_source_consumed"]["claims_returns"] == 6
    assert plans.row["incremental_source_consumed"]["orders"] == 3
    assert plans.row["execution_consumed"] == 3 and len(plans.row["execution_work"]) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("topic", "resource", "raw_actions", "normalized_type", "normalized_resource"),
    [
        ("orders_v2", "/orders/1", None, "orders.updated", "/orders/1"),
        (
            "post_purchase",
            "/post-purchase/v1/claims/1/actions-history",
            ["claims_actions"],
            "claims.updated",
            "/post-purchase/v1/claims/1",
        ),
    ],
)
async def test_pilot_replay_uses_real_raw_topic_and_passes_fenced_job_identity(
    topic: str,
    resource: str,
    raw_actions: Any,
    normalized_type: str,
    normalized_resource: str,
) -> None:
    jobs = MagicMock()
    jobs.update_many = AsyncMock(return_value=SimpleNamespace(modified_count=0))
    jobs.update_one = AsyncMock(return_value=SimpleNamespace(matched_count=1))
    stored_event = {
        "_id": "event",
        "user_id": int(SELLER),
        "received_at": NOW,
        "topic": topic,
        "classification": topic,
        "resource": resource,
        "raw_body": {"actions": raw_actions},
    }
    events = MagicMock()
    events.find.return_value.sort.return_value.to_list = AsyncMock(return_value=[stored_event])
    selected = {
        "_id": "job",
        "seller_id": SELLER,
        "requested_at": NOW - timedelta(minutes=1),
        "delta_through_at": NOW,
        "attempt_token": "c" * 32,
        "fence": 7,
    }
    handler = SimpleNamespace(handle=AsyncMock(return_value="no_export"))
    processor = SyncJobsProcessor(
        db={
            "sheets_sync_jobs": jobs,
            "webhook_events": events,
            "sheets_history_backfill_plans": Plans(),
        },
        handler=handler,
        activation_cutoff=NOW - timedelta(days=1),
        clock=lambda: NOW,
    )
    processor.claim_next = AsyncMock(return_value=selected)  # type: ignore[method-assign]
    assert await processor.process_once() == "succeeded"
    assert handler.handle.await_count == 1
    call = handler.handle.await_args
    assert call.args[0].event_type == normalized_type
    assert call.args[0].resource == normalized_resource
    assert call.kwargs["job_identity"] == {
        "_id": "job",
        "attempt_token": "c" * 32,
        "fence": 7,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("topic", ["items", "catalog_item_competition_status", "stock", "unknown"])
async def test_pilot_replay_unknown_source_keeps_job_pending_without_fabricating_a_source(
    topic: str,
) -> None:
    jobs = MagicMock()
    jobs.update_many = AsyncMock(return_value=SimpleNamespace(modified_count=0))
    jobs.update_one = AsyncMock(return_value=SimpleNamespace(matched_count=1))
    events = MagicMock()
    events.find.return_value.sort.return_value.to_list = AsyncMock(
        return_value=[
            {
                "_id": "event",
                "user_id": int(SELLER),
                "received_at": NOW,
                "topic": topic,
                "classification": topic,
                "resource": "/items/1",
            }
        ]
    )
    selected = {
        "_id": "job",
        "seller_id": SELLER,
        "requested_at": NOW - timedelta(minutes=1),
        "delta_through_at": NOW,
        "attempt_token": "c" * 32,
        "fence": 7,
        "cursor_event_id": "prior",
    }
    handler = SimpleNamespace(handle=AsyncMock())
    plans = Plans()
    before = copy.deepcopy(plans.row)
    processor = SyncJobsProcessor(
        db={
            "sheets_sync_jobs": jobs,
            "webhook_events": events,
            "sheets_history_backfill_plans": plans,
        },
        handler=handler,
        activation_cutoff=NOW - timedelta(days=1),
        clock=lambda: NOW,
    )
    processor.claim_next = AsyncMock(return_value=selected)  # type: ignore[method-assign]
    assert await processor.process_once() == "pending"
    assert handler.handle.await_count == 0 and plans.row == before
    values = jobs.update_one.await_args.args[1]["$set"]
    assert values["state"] == "pending" and "cursor_event_id" not in values


@pytest.mark.asyncio
async def test_work_without_single_attempt_client_waits_before_charge() -> None:
    plans = Plans()
    before = copy.deepcopy(plans.row)
    remote = SimpleNamespace(fetch_resource=AsyncMock())
    worker = guard(plans, remote, Intent("questions"))
    with pytest.raises(HistoryPolicyWaitError):
        await worker.fetch_resource(seller_id=SELLER, path="/questions/1")
    assert remote.fetch_resource.await_count == 0 and plans.row == before


@pytest.mark.asyncio
async def test_work_real_client_disables_hidden_retry_and_carries_nonce_once() -> None:
    from zeler_platform_core.clients.meli_gateway_client import MeliGatewayClient

    plans, calls = Plans(), []

    def transport(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.headers["X-Zeler-Proxy-Retry"] == "disabled"
        return httpx.Response(200, json={"id": 1}, headers={"X-Zeler-Upstream-Attempts": "1"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
        remote = MeliGatewayClient(
            "https://gateway.test/proxy/meli",
            cast(
                Any, SimpleNamespace(get_token_for_seller=AsyncMock(return_value="synthetic-jwt"))
            ),
            http_client=http,
        )
        worker = guard(plans, remote, Intent("questions"))
        assert await worker.fetch_resource(seller_id=SELLER, path="/questions/1") == {"id": 1}
    assert len(calls) == 1
    nonce = calls[0].headers["X-Zeler-History-Work"]
    assert plans.row["execution_work"][nonce]["path"] == "/questions/1"


@pytest.mark.asyncio
async def test_work_cannot_fall_back_to_hidden_retry_client_after_paced_unwrap() -> None:
    class GenericPhysical:
        def __init__(self) -> None:
            self.calls = 0

        async def fetch_resource(self, **kwargs: Any) -> dict[str, Any]:
            self.calls += 1
            return {"id": 1}

    class Pacer:
        async def acquire(self, **kwargs: Any) -> bool:
            return True

    plans, physical = Plans(), GenericPhysical()
    paced = PacedMeliGateway(inner=physical, pacer=cast(Any, Pacer()), lane="ranges")
    worker = guard(plans, paced, Intent("questions"))
    with pytest.raises(HistoryPolicyWaitError):
        await worker.fetch_resource(seller_id=SELLER, path="/questions/1")
    assert plans.row["execution_consumed"] == 1 and physical.calls == 0
