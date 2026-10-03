from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient

from zeler_gateway.oauth.events import emit_accounts_linked
from zeler_platform_core.history_onboarding import admit_history_onboarding
from zeler_sheets.history_onboarding import HistoryOnboardingWorker, PlanBudgetGateway


@pytest_asyncio.fixture
async def db() -> AsyncIterator[Any]:
    client: AsyncIOMotorClient[Any] = AsyncIOMotorClient(
        "mongodb://127.0.0.1:27028/?directConnection=true", tz_aware=True
    )
    hello = await client.admin.command("hello")
    assert hello["isWritablePrimary"] and hello["setName"] == "rs0"
    database = client["zeler_onboarding_" + uuid4().hex]
    try:
        from pathlib import Path

        from infra.mongo.apply_validators import _desired_validator, _load_schema

        for collection in (
            "orders",
            "questions",
            "sheets_history_acquisitions",
            "sheets_history_receipts",
            "sheets_history_order_ranges",
        ):
            path = Path(__file__).parents[3] / "infra/mongo/schemas" / f"{collection}.json"
            await database.create_collection(
                collection, validator=_desired_validator(_load_schema(path))
            )
        yield database
    finally:
        await client.drop_database(database.name)
        client.close()


class Publisher:
    async def publish(self, **kwargs: Any) -> None:
        pass


@pytest.mark.asyncio
async def test_oauth_relink_preserves_bootstrap_and_admits_fixed_plan(db: Any) -> None:
    now = datetime(2024, 2, 29, 12, tzinfo=UTC)
    await db.bootstrap_jobs.insert_one(
        {
            "_id": "bootstrap-123-oauth",
            "seller_id": "123",
            "state": "succeeded",
            "checkpoints": {"orders": 99},
        }
    )
    await emit_accounts_linked(
        "123", "user", mongo_db=db, amqp_publisher=Publisher(), clock=lambda: now
    )
    plan = await db.sheets_history_backfill_plans.find_one({"_id": "123"})
    assert plan["date_from"] == datetime(2023, 2, 28, 12, tzinfo=UTC)
    await emit_accounts_linked(
        "123",
        "user",
        mongo_db=db,
        amqp_publisher=Publisher(),
        clock=lambda: now + timedelta(days=3),
    )
    assert (await db.sheets_history_backfill_plans.find_one({"_id": "123"}))["cutoff"] == now
    assert (await db.bootstrap_jobs.find_one({"seller_id": "123"}))["checkpoints"] == {"orders": 99}


@pytest.mark.asyncio
async def test_admission_race_preserves_existing_cutoff_and_progress(db: Any) -> None:
    cutoff = datetime(2026, 1, 31, tzinfo=UTC)
    await db.sheets_history_backfill_plans.insert_one(
        {
            "_id": "123",
            "seller_id": "123",
            "cutoff": cutoff,
            "progress": {"orders": {"completed": 1}},
        }
    )
    await asyncio.gather(
        *(admit_history_onboarding(db, "123", now=cutoff + timedelta(days=i)) for i in range(4))
    )
    plan = await db.sheets_history_backfill_plans.find_one({"_id": "123"})
    assert plan["cutoff"] == cutoff
    assert plan["progress"]["orders"]["completed"] == 1
    assert plan["date_from"] == datetime(2025, 1, 31, tzinfo=UTC)


class Gateway:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def fetch_resource(self, *, seller_id: Any, path: str) -> dict[str, Any]:
        self.calls.append((seller_id, path))
        return {"ok": True}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sources", "expected"),
    [
        ({"orders": {"state": "blocked"}}, "running_with_observations"),
        (
            {
                name: {"state": "blocked"}
                for name in (
                    "orders",
                    "questions",
                    "shipments",
                    "messages",
                    "claims_returns",
                    "full_withdrawals",
                )
            },
            "temporarily_inaccessible",
        ),
        (
            {"orders": {"state": "ready_with_observations", "partial": {"persisted": 1}}},
            "ready_with_observations",
        ),
    ],
)
async def test_aggregate_available_status_requires_a_demonstrably_useful_source(
    db: Any, sources: dict[str, Any], expected: str
) -> None:
    now = datetime(2026, 1, 31, tzinfo=UTC)
    await admit_history_onboarding(db, "123", now=now)
    await db.meli_accounts.insert_one({"_id": "a", "seller_id": 123, "status": "active"})
    await db.sheets_history_backfill_plans.update_one(
        {"_id": "123"}, {"$set": {"onboarding_sources": sources}}
    )

    class Worker(HistoryOnboardingWorker):
        async def advance_source(self, *args: Any) -> dict[str, Any]:
            return dict(sources["orders"])

    await Worker(db, Gateway(), Gateway(), now=lambda: now).process_once()
    assert (await db.sheets_history_backfill_plans.find_one({"_id": "123"}))[
        "onboarding_status"
    ] == expected


@pytest.mark.asyncio
async def test_budget_charges_before_call_and_revocation_stops_source(db: Any) -> None:
    now = datetime(2026, 1, 31, tzinfo=UTC)
    await admit_history_onboarding(db, "123", now=now)
    await db.meli_accounts.insert_one({"_id": "a", "seller_id": 123, "status": "active"})
    await db.sheets_history_backfill_plans.update_one(
        {"_id": "123"}, {"$set": {"budget.orders.physical_attempts": 1}}
    )
    gateway = Gateway()
    guarded = PlanBudgetGateway(db, gateway, "123", "orders")
    await guarded.fetch_resource(seller_id="123", path="/orders/1")
    with pytest.raises(ValueError, match="budget"):
        await guarded.fetch_resource(seller_id="123", path="/orders/2")
    assert len(gateway.calls) == 1
    await db.meli_accounts.update_one({"_id": "a"}, {"$set": {"status": "revoked"}})
    with pytest.raises(ValueError, match="eligible"):
        await PlanBudgetGateway(db, gateway, "123", "questions").fetch_resource(
            seller_id="123", path="/questions/1"
        )
    with pytest.raises(ValueError, match="seller"):
        await guarded.fetch_resource(seller_id="456", path="/orders/1")


@pytest.mark.asyncio
async def test_worker_paused_account_no_requests_and_sources_do_not_block_each_other(
    db: Any,
) -> None:
    now = datetime(2026, 1, 31, tzinfo=UTC)
    await admit_history_onboarding(db, "123", now=now)
    await db.meli_accounts.insert_one({"_id": "a", "seller_id": 123, "status": "revoked"})
    gateway = Gateway()
    worker = HistoryOnboardingWorker(db, gateway, gateway, now=lambda: now)
    assert await worker.process_once() == "processed"
    assert gateway.calls == []
    plan = await db.sheets_history_backfill_plans.find_one({"_id": "123"})
    assert plan["onboarding_status"] == "temporarily_inaccessible"


@pytest.mark.asyncio
async def test_sources_rotate_and_failure_is_durable_without_reset(db: Any) -> None:
    now = datetime(2026, 1, 31, tzinfo=UTC)
    await admit_history_onboarding(db, "123", now=now)
    await db.meli_accounts.insert_one({"_id": "a", "seller_id": 123, "status": "active"})

    class Worker(HistoryOnboardingWorker):
        seen: list[str] = []

        async def advance_source(
            self, plan: dict[str, Any], source: str, gateway: Any, detail: Any
        ) -> dict[str, Any]:
            self.seen.append(source)
            if source == "orders":
                raise RuntimeError("private source error text must not leak")
            return {"state": "ready", "persisted": 100}

    worker = Worker(db, Gateway(), Gateway(), now=lambda: now)
    await worker.process_once()
    now += timedelta(seconds=6)
    await worker.process_once()
    assert worker.seen == ["orders", "questions"]
    plan = await db.sheets_history_backfill_plans.find_one({"_id": "123"})
    assert plan["onboarding_sources"]["orders"]["reason"] == "RuntimeError"
    assert plan["onboarding_sources"]["questions"]["persisted"] == 100
    assert "private source" not in str(plan)


@pytest.mark.asyncio
async def test_two_workers_claim_one_logical_plan(db: Any) -> None:
    now = datetime(2026, 1, 31, tzinfo=UTC)
    await admit_history_onboarding(db, "123", now=now)
    await db.meli_accounts.insert_one({"_id": "a", "seller_id": 123, "status": "active"})
    gate = asyncio.Event()

    class Worker(HistoryOnboardingWorker):
        async def advance_source(self, *args: Any) -> dict[str, Any]:
            await gate.wait()
            return {"state": "ready"}

    worker = Worker(db, Gateway(), Gateway(), now=lambda: now)
    task = asyncio.create_task(worker.process_once())
    while not await db.sheets_history_backfill_plans.find_one({"lease_token": {"$exists": True}}):
        await asyncio.sleep(0.01)
    assert (
        await HistoryOnboardingWorker(db, Gateway(), Gateway(), now=lambda: now).process_once()
        == "idle"
    )
    gate.set()
    assert await task == "processed"


@pytest.mark.asyncio
async def test_lost_plan_lease_fences_source_and_checkpoint(db: Any) -> None:
    now = datetime(2026, 1, 31, tzinfo=UTC)
    await admit_history_onboarding(db, "123", now=now)
    await db.meli_accounts.insert_one({"_id": "a", "seller_id": 123, "status": "active"})
    await db.sheets_history_backfill_plans.update_one(
        {"_id": "123"}, {"$set": {"lease_token": "new", "lease_until": now + timedelta(minutes=6)}}
    )
    guard = PlanBudgetGateway(
        db, Gateway(), "123", "orders", lease_token=uuid4().hex, now=lambda: now
    )
    with pytest.raises(ValueError, match="budget|lease"):
        await guard.fetch_resource(seller_id="123", path="/orders/1")


@pytest.mark.asyncio
async def test_collector_response_cannot_checkpoint_after_its_plan_lease_is_replaced(
    db: Any,
) -> None:
    now = datetime(2026, 1, 31, tzinfo=UTC)
    await admit_history_onboarding(db, "123", now=now)
    await db.meli_accounts.insert_one({"_id": "a", "seller_id": 123, "status": "active"})
    await db.sheets_history_backfill_plans.update_one(
        {"_id": "123"}, {"$set": {"source_cursor": 3}}
    )
    await db.orders.insert_one(
        {
            "_id": "o",
            "seller_id": "123",
            "meli_pack_id": "400",
            "buyer_id": "321",
            "status": "paid",
            "date_created": now,
            "total_amount": 1.0,
            "schema_version": 1,
        }
    )

    class Source(Gateway):
        async def fetch_resource(self, **kwargs: Any) -> dict[str, Any]:
            await db.sheets_history_backfill_plans.update_one(
                {"_id": "123"},
                {
                    "$set": {
                        "lease_token": "new-owner",
                        "collector_checkpoints.messages": {"new": True},
                    }
                },
            )
            return {"paging": {"total": 0, "offset": 0}, "messages": []}

    source = Source()
    await HistoryOnboardingWorker(db, source, source, now=lambda: now).process_once()
    plan = await db.sheets_history_backfill_plans.find_one({"_id": "123"})
    assert plan["collector_checkpoints"]["messages"] == {"new": True}


@pytest.mark.asyncio
async def test_guarded_request_charges_and_disables_proxy_retries(db: Any) -> None:
    import httpx

    now = datetime(2026, 1, 31, tzinfo=UTC)
    await admit_history_onboarding(db, "123", now=now)
    await db.meli_accounts.insert_one({"_id": "a", "seller_id": 123, "status": "active"})

    class RawGateway(Gateway):
        async def request(self, **kwargs: Any) -> httpx.Response:
            self.calls.append(kwargs)
            return httpx.Response(206, json={"id": 1}, headers={"X-Zeler-Upstream-Attempts": "1"})

    raw = RawGateway()
    guard = PlanBudgetGateway(db, raw, "123", "orders")
    response = await guard.request(method="GET", seller_id="123", path="/orders/1")
    assert response.status_code == 206
    assert raw.calls[0]["headers"]["X-Zeler-Proxy-Retry"] == "disabled"
    assert (await db.sheets_history_backfill_plans.find_one({"_id": "123"}))["budget"]["orders"][
        "consumed"
    ] == 1


def test_onboarding_sources_have_explicit_scopes_in_real_client_seed() -> None:
    import json
    from pathlib import Path

    seed = json.loads(
        (
            Path(__file__).parents[3] / "infra/mongo/seeds/module_registry.admin_clients.json"
        ).read_text()
    )
    sheet = next(doc for doc in seed["documents"] if doc["_id"] == "sheets")
    assert "GET /messages/packs/*" in sheet["allowed_meli_scopes"]
    assert "GET /stock/fulfillment/operations/search" in sheet["allowed_meli_scopes"]


@pytest.mark.asyncio
async def test_empty_dependencies_not_reported_as_complete_while_orders_unknown(db: Any) -> None:
    now = datetime(2026, 1, 31, tzinfo=UTC)
    await admit_history_onboarding(db, "123", now=now)
    plan = await db.sheets_history_backfill_plans.find_one({"_id": "123"})
    worker = HistoryOnboardingWorker(db, Gateway(), Gateway(), now=lambda: now)
    result = await worker.advance_source(plan, "messages", Gateway(), Gateway())
    assert result["state"] == "pending"
    assert result["coverage_complete"] is False
    shipment = await worker.advance_source(plan, "shipments", Gateway(), Gateway())
    assert shipment["state"] == "pending"


@pytest.mark.asyncio
async def test_policy_rejects_out_of_source_reads_and_foreign_query(db: Any) -> None:
    now = datetime(2026, 1, 31, tzinfo=UTC)
    await admit_history_onboarding(db, "123", now=now)
    await db.meli_accounts.insert_one({"_id": "a", "seller_id": 123, "status": "active"})
    guard = PlanBudgetGateway(db, Gateway(), "123", "orders")
    with pytest.raises(ValueError, match="scope"):
        await guard.fetch_resource(seller_id="123", path="/users/123/items_visits")
    with pytest.raises(ValueError, match="seller"):
        await guard.fetch_resource(seller_id="123", path="/orders/search?seller=456")


@pytest.mark.asyncio
async def test_runtime_factories_accept_one_shared_background_pacer(
    db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from zeler_sheets.consumer import build_formula_recovery_poller, build_history_onboarding_poller
    from zeler_sheets.formulas.pacing import RecoveryRequestPacer

    monkeypatch.setenv("ZELERDATA_FORMULA_RECOVERY_SELLERS", "123")
    pacer = RecoveryRequestPacer(requests_per_minute=180)
    regular = await build_formula_recovery_poller(
        db=db, kms_client=None, detail_gateway=Gateway(), pacer=pacer
    )
    history = await build_history_onboarding_poller(
        db=db, kms_client=None, detail_gateway=Gateway(), pacer=pacer
    )
    assert regular is not history
    for lane in regular.lanes:
        assert lane._processor.gateway._pacer is pacer
    assert history.lanes[0]._processor.discovery._pacer is pacer
    assert history.lanes[0]._processor.detail._pacer is pacer


@pytest.mark.asyncio
async def test_incremental_daily_budget_renews_without_reopening_initial_history(db: Any) -> None:
    now = datetime(2026, 1, 31, tzinfo=UTC)
    await admit_history_onboarding(db, "123", now=now)
    await db.meli_accounts.insert_one({"_id": "a", "seller_id": 123, "status": "active"})
    await db.sheets_history_backfill_plans.update_one(
        {"_id": "123"},
        {
            "$set": {
                "incremental_policy.max_daily_total": 1,
                "incremental_policy.max_daily_source": 1,
                "total_consumed": 99999,
            }
        },
    )
    guard = PlanBudgetGateway(db, Gateway(), "123", "questions", now=lambda: now)
    guard.incremental = True
    await guard.fetch_resource(seller_id="123", path="/questions/1")
    with pytest.raises(ValueError, match="budget"):
        await guard.fetch_resource(seller_id="123", path="/questions/2")
    now += timedelta(days=1)
    await guard.fetch_resource(seller_id="123", path="/questions/2")
    plan = await db.sheets_history_backfill_plans.find_one({"_id": "123"})
    assert plan["total_consumed"] == 99999
    assert plan["incremental_consumed"] == 1


@pytest.mark.asyncio
async def test_full_admission_capacity_still_advances_existing_jobs(db: Any) -> None:
    from zeler_sheets.formulas.recovery import OrderHistoryRecoveryRequest
    from zeler_sheets.pilot_history import HistoryPlanner

    cutoff = datetime(2026, 1, 31, tzinfo=UTC)
    await admit_history_onboarding(db, "123", now=cutoff)
    plan = await db.sheets_history_backfill_plans.find_one({"_id": "123"})

    class EmptyGateway(Gateway):
        async def fetch_resource(self, *, seller_id: Any, path: str) -> dict[str, Any]:
            return {"paging": {"total": 0}, "results": []}

    worker = HistoryOnboardingWorker(db, EmptyGateway(), EmptyGateway(), now=lambda: cutoff)
    queue = worker.queue("123", frozenset({"orders"}))
    chunks = HistoryPlanner(cutoff=cutoff, months=12).plan_for("orders").resume(completed_ids=())
    for chunk in chunks[:4]:
        await queue.enqueue(
            OrderHistoryRecoveryRequest(
                "123",
                f"pilot-12m:{cutoff.isoformat(timespec='milliseconds')}",
                chunk.start,
                chunk.end,
            )
        )
    await worker.advance_source(plan, "orders", EmptyGateway(), EmptyGateway())
    assert await db.sheets_history_acquisitions.count_documents({}) == 1


@pytest.mark.asyncio
async def test_legacy_workers_cannot_claim_policy_owned_jobs(db: Any) -> None:
    from zeler_sheets.formulas.recovery import FormulaRecoveryQueue, OrderHistoryRecoveryRequest

    cutoff = datetime(2026, 1, 31, tzinfo=UTC)
    queue = FormulaRecoveryQueue(
        db,
        allowed_sellers=frozenset({"123"}),
        enabled_models=frozenset({"orders"}),
        policy_authority="history-on-link-v1",
    )
    request = OrderHistoryRecoveryRequest("123", "onboarding", cutoff - timedelta(days=1), cutoff)
    await queue.enqueue(request, reopen_terminal=False)
    legacy = FormulaRecoveryQueue(
        db, allowed_sellers=frozenset({"123"}), enabled_models=frozenset({"orders"})
    )
    assert await legacy.claim(history=True) is None
    claimed = await queue.claim(history=True)
    assert claimed is not None and claimed["policy_authority"] == "history-on-link-v1"


@pytest.mark.asyncio
async def test_automatic_annual_units_finish_and_two_incrementals_keep_source_watermarks(
    db: Any,
) -> None:
    from urllib.parse import parse_qs, urlsplit

    from zeler_sheets.formulas.read_models import read_model_reconciliation_marker_covers

    cutoff = datetime(2026, 1, 31, tzinfo=UTC)
    now = cutoff

    def clock() -> datetime:
        return now

    await admit_history_onboarding(db, "123", now=cutoff)
    await db.meli_accounts.insert_one({"_id": "a", "seller_id": 123, "status": "active"})

    class Source(Gateway):
        def current_order(self) -> dict[str, Any]:
            return {
                "id": 1,
                "seller": {"id": 123},
                "buyer": {"id": 321},
                "status": "paid" if now < cutoff + timedelta(minutes=30) else "cancelled",
                "date_created": (cutoff + timedelta(minutes=10)).isoformat(),
                "date_last_updated": (now - timedelta(minutes=5)).isoformat(),
                "total_amount": 10,
                "tags": ["no_shipping"],
                "order_items": [
                    {"item": {"id": "MLM1"}, "quantity": 1, "unit_price": 10, "sale_fee": 1}
                ],
            }

        async def request(self, **kwargs: Any) -> Any:
            import httpx

            self.calls.append(kwargs["path"])
            return httpx.Response(
                200, json=self.current_order(), headers={"X-Zeler-Upstream-Attempts": "1"}
            )

        async def fetch_resource_once(self, *, seller_id: Any, path: str) -> dict[str, Any]:
            self.calls.append(path)
            if path.startswith("/questions/search"):
                return {"total": 0, "questions": [], "scroll_id": None}
            params = parse_qs(urlsplit(path).query)
            return {
                "paging": {
                    "total": int(now > cutoff),
                    "offset": int(params.get("offset", ["0"])[0]),
                    "limit": 50,
                },
                "results": [self.current_order()] if now > cutoff else [],
            }

    source = Source()
    worker = HistoryOnboardingWorker(db, source, source, now=lambda: now)
    for family in ("orders", "questions"):
        result = {}
        for _ in range(80):
            plan = await db.sheets_history_backfill_plans.find_one({"_id": "123"})
            guard = PlanBudgetGateway(db, source, "123", family, now=lambda: now)
            result = await worker.advance_source(plan, family, guard, guard)
            if result["state"] == "ready":
                break
        assert result["state"] == "ready", result
    plan = await db.sheets_history_backfill_plans.find_one({"_id": "123"})
    marker = await db.sheets_read_model_freshness.find_one({"_id": "123:orders"})
    assert read_model_reconciliation_marker_covers(
        marker, date_from=plan["date_from"], date_to=cutoff, now=cutoff
    )
    initial_calls = sum("order.date_created" in path for path in source.calls)
    for _cycle in range(2):
        now += timedelta(minutes=20)
        for _step in range(5):
            plan = await db.sheets_history_backfill_plans.find_one({"_id": "123"})
            guard = PlanBudgetGateway(db, source, "123", "orders", now=clock)
            await worker.advance_source(plan, "orders", guard, guard)
        plan = await db.sheets_history_backfill_plans.find_one({"_id": "123"})
        assert plan["modification_watermark"] >= now - timedelta(minutes=5)
        order_row = await db.orders.find_one({"_id": "1", "seller_id": "123"})
        assert order_row is not None
        assert order_row["status"] == ("paid" if _cycle == 0 else "cancelled")
    creation_paths = [path for path in source.calls if "order.date_created" in path]
    assert (
        len(creation_paths) == initial_calls + 2
    )  # Per changed-ID creation tail, NOT annual reread.
    for path in creation_paths[initial_calls:]:
        assert (
            datetime.fromisoformat(parse_qs(urlsplit(path).query)["order.date_created.from"][0])
            >= cutoff
        )
    assert any("order.date_last_updated" in path for path in source.calls)


@pytest.mark.asyncio
async def test_policy_question_incremental_stops_at_old_boundary_and_retains_annual_proof(
    db: Any,
) -> None:
    from zeler_sheets.formulas.read_models import read_model_reconciliation_marker_covers
    from zeler_sheets.formulas.recovery import RecoveryRequest
    from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker
    from zeler_sheets.formulas.refresh import reconciled_marker

    cutoff = datetime(2026, 1, 31, tzinfo=UTC)
    now = cutoff + timedelta(minutes=20)
    await admit_history_onboarding(db, "123", now=cutoff)
    before = reconciled_marker(
        seller_id="123",
        read_model="questions",
        start=cutoff - timedelta(days=300),
        end=cutoff,
        now=cutoff,
    )
    await db.sheets_read_model_freshness.insert_one(before)
    current = {
        "id": 1,
        "seller_id": 123,
        "item_id": "MLM1",
        "date_created": (cutoff + timedelta(minutes=10)).isoformat(),
        "status": "UNANSWERED",
        "text": "fixture",
        "from": {"id": 321},
    }
    old = {**current, "id": 2, "date_created": (cutoff - timedelta(days=10)).isoformat()}

    class QuestionSource(Gateway):
        async def fetch_resource(self, *, seller_id: Any, path: str) -> dict[str, Any]:
            self.calls.append(path)
            if path.startswith("/questions/search"):
                return {
                    "total": 9999,
                    "questions": [current, old],
                    "scroll_id": "must-not-continue",
                }
            assert path == "/questions/1"
            return current

    source = QuestionSource()
    owner = HistoryOnboardingWorker(db, source, source, now=lambda: now)
    queue = owner.queue("123", frozenset({"questions"}))
    await queue.enqueue(
        RecoveryRequest("123", "questions", cutoff - timedelta(minutes=5), now),
        reopen_terminal=False,
    )
    await FormulaRecoveryWorker(
        db=db, queue=queue, gateway=source, detail_gateway=source, lane="ranges"
    ).process_once()
    assert await db.questions.find_one({"_id": "1"}) is not None
    assert len([path for path in source.calls if path.startswith("/questions/search")]) == 1
    assert "sort_types=DESC" in source.calls[0]
    after = await db.sheets_read_model_freshness.find_one({"_id": "123:questions"})
    assert read_model_reconciliation_marker_covers(
        after, date_from=before["date_from"], date_to=cutoff, now=cutoff
    )


@pytest.mark.asyncio
async def test_plan_rejects_search_outside_authorized_dates_before_charging(db: Any) -> None:
    now = datetime(2026, 1, 31, tzinfo=UTC)
    await admit_history_onboarding(db, "123", now=now)
    await db.meli_accounts.insert_one({"_id": "a", "seller_id": 123, "status": "active"})
    gateway = Gateway()
    guard = PlanBudgetGateway(db, gateway, "123", "orders", now=lambda: now)
    with pytest.raises(ValueError, match="range"):
        await guard.fetch_resource(
            seller_id="123",
            path="/orders/search?seller=123&order.date_created.from=2000-01-01T00%3A00%3A00%2B00%3A00",
        )
    assert not gateway.calls
    assert (await db.sheets_history_backfill_plans.find_one({"_id": "123"}))["total_consumed"] == 0


@pytest.mark.asyncio
async def test_initial_range_remains_fixed_when_clock_advances_but_upkeep_can_advance(
    db: Any,
) -> None:
    cutoff = datetime(2026, 1, 31, tzinfo=UTC)
    await admit_history_onboarding(db, "123", now=cutoff)
    await db.meli_accounts.insert_one({"_id": "a", "seller_id": 123, "status": "active"})
    source = Gateway()
    guard = PlanBudgetGateway(db, source, "123", "orders", now=lambda: cutoff + timedelta(days=30))
    path = "/orders/search?seller=123&order.date_created.from=2026-02-02T00%3A00%3A00%2B00%3A00"
    with pytest.raises(ValueError, match="range"):
        await guard.fetch_resource(seller_id="123", path=path)
    assert not source.calls
    assert (await db.sheets_history_backfill_plans.find_one({"_id": "123"}))["total_consumed"] == 0
    guard.incremental = True
    await guard.fetch_resource(seller_id="123", path=path)
    assert len(source.calls) == 1


@pytest.mark.asyncio
async def test_fresh_relink_resumes_only_access_failures_preserving_acquisition_progress(
    db: Any,
) -> None:
    cutoff = datetime(2026, 1, 31, tzinfo=UTC)
    await admit_history_onboarding(db, "123", now=cutoff)
    await db.meli_accounts.insert_one({"_id": "a", "seller_id": 123, "status": "active"})
    await db.sheets_formula_recovery_jobs.insert_many(
        [
            {
                "_id": "access",
                "seller_id": "123",
                "read_model": "orders",
                "policy_authority": "history-on-link-v1",
                "state": "failed",
                "failure_reason": "source_rejected",
                "updated_at": cutoff,
                "attempts": 3,
                "history_checkpoint_revision": 7,
            },
            {
                "_id": "detail",
                "seller_id": "123",
                "read_model": "orders",
                "policy_authority": "history-on-link-v1",
                "state": "failed",
                "failure_reason": "source_incomplete",
                "updated_at": cutoff,
                "attempts": 3,
            },
        ]
    )
    now = cutoff + timedelta(days=1)
    await admit_history_onboarding(db, "123", now=now)

    class Worker(HistoryOnboardingWorker):
        async def advance_source(self, *args: Any) -> dict[str, Any]:
            return {"state": "pending"}

    await Worker(db, Gateway(), Gateway(), now=lambda: now).process_once()
    access = await db.sheets_formula_recovery_jobs.find_one({"_id": "access"})
    assert access["state"] == "pending"
    assert access["attempts"] == 0 and access["history_checkpoint_revision"] == 7
    assert (await db.sheets_formula_recovery_jobs.find_one({"_id": "detail"}))["state"] == "failed"
