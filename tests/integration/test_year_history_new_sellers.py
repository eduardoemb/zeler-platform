"""A newly linked ZelerData seller gets twelve months of history on its own (real Mongo).

Until 2026-10-12 a new seller in `all` mode had only what its bootstrap
acquired at link time plus what refresh added from then on: ranges older than
about 90 days stayed ``DATA_UNAVAILABLE`` for orders, questions and
DEVOLUCIONES. The refresh loop now walks each source backwards, one portion per
cycle for the whole fleet, until the proven coverage reaches a full year.

The pilot keeps its paused history plan, which is neither edited nor resumed,
and since 2026-10-13 walks the sources still short of a year like any other
seller: questions and DEVOLUCIONES, not its already proven orders.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio

from zeler_platform_core.devoluciones_certificates import CERTIFICATES, select_covering_proofs
from zeler_platform_core.devoluciones_readiness import (
    acquire_devoluciones_operation,
    finish_devoluciones_operation,
    new_devoluciones_attempt_token,
)

PILOT = "82453304"
NEW_SELLER = "90000001"
SECOND_SELLER = "90000002"
RUNS = "sheets_devoluciones_runs"
JOBS = "sheets_formula_recovery_jobs"
FRESHNESS = "sheets_read_model_freshness"
PLANS = "sheets_history_backfill_plans"
ORDER_SPACING = timedelta(days=5)
QUESTION_SPACING = timedelta(days=9)


@pytest_asyncio.fixture
async def year_db() -> AsyncIterator[Any]:
    from motor.motor_asyncio import AsyncIOMotorClient

    client: Any = AsyncIOMotorClient(
        "mongodb://127.0.0.1:27028/?directConnection=true",
        tz_aware=True,
        serverSelectionTimeoutMS=1000,
    )
    hello = await client.admin.command("hello")
    assert hello["isWritablePrimary"] is True and hello["setName"] == "rs0"
    name = "zeler_year_history_" + uuid4().hex
    db = client[name]
    try:
        for collection in (
            "sheets_devoluciones_operations",
            RUNS,
            "sheets_devoluciones_run_windows",
            CERTIFICATES,
            "sheets_devoluciones_claim_quarantine",
            FRESHNESS,
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


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class YearGateway:
    """Mercado Libre for every seller: orders, questions and one old return.

    Order search has hour precision, like the source: ``to`` includes its whole
    hour. Every call is recorded by seller and path.
    """

    def __init__(self, *, now: datetime, sellers: tuple[str, ...], first: datetime) -> None:
        self.calls: list[tuple[str, str]] = []
        self.failures: dict[tuple[str, str], int] = {}
        self.orders: dict[str, list[dict[str, Any]]] = {}
        self.questions: dict[str, list[dict[str, Any]]] = {}
        self.returns: dict[str, datetime] = {}
        settled = now - timedelta(hours=3)
        for number, seller_id in enumerate(sellers, start=1):
            suffix = seller_id[-4:]
            created = first.replace(hour=12, minute=30)
            self.orders[seller_id] = []
            while created < settled:
                index = len(self.orders[seller_id])
                self.orders[seller_id].append(self._order(seller_id, number, index, created))
                created += ORDER_SPACING
            created = first.replace(hour=15, minute=10)
            self.questions[seller_id] = []
            while created < settled:
                index = len(self.questions[seller_id])
                self.questions[seller_id].append(
                    {
                        "id": int(f"7{number}{index:05d}"),
                        "seller_id": int(seller_id),
                        "item_id": f"MLM{suffix}",
                        "text": "Disponible?",
                        "status": "ANSWERED",
                        "from": {"id": 4242},
                        "date_created": _iso(created),
                        "answer": {"text": "Sí", "status": "ACTIVE", "date_created": _iso(created)},
                    }
                )
                created += QUESTION_SPACING
            self.returns[seller_id] = datetime.combine(
                (now - timedelta(days=200)).date(), time(10), tzinfo=UTC
            )

    @staticmethod
    def _order(seller_id: str, number: int, index: int, created: datetime) -> dict[str, Any]:
        suffix = seller_id[-4:]
        return {
            "id": int(f"2{number}{index:05d}"),
            "seller": {"id": int(seller_id)},
            "buyer": {"id": 4242},
            "status": "paid",
            "date_created": _iso(created),
            "last_updated": _iso(created),
            "total_amount": 100,
            "shipping": {"id": int(f"4{number}{index:05d}")},
            "order_items": [
                {
                    "item": {"id": f"MLM{suffix}", "seller_sku": f"SKU-{suffix}", "title": "T"},
                    "quantity": 1,
                    "unit_price": 100,
                }
            ],
        }

    def fail(self, seller_id: str, path_prefix: str, times: int) -> None:
        self.failures[(seller_id, path_prefix)] = times

    def _maybe_fail(self, seller_id: str, path: str) -> None:
        for (seller, prefix), remaining in self.failures.items():
            if seller == seller_id and path.startswith(prefix) and remaining > 0:
                self.failures[(seller, prefix)] = remaining - 1
                raise httpx.HTTPStatusError(
                    "unavailable",
                    request=httpx.Request("GET", "https://gateway.test" + path),
                    response=httpx.Response(503),
                )

    def _order_search(self, seller_id: str, path: str) -> dict[str, Any]:
        query = parse_qs(urlsplit(path).query)
        lower = _parse(query["order.date_created.from"][0])
        upper = _parse(query["order.date_created.to"][0]) + timedelta(hours=1)
        rows = [
            row for row in self.orders[seller_id] if lower <= _parse(row["date_created"]) < upper
        ]
        offset = int(query["offset"][0])
        return {"paging": {"total": len(rows)}, "results": rows[offset : offset + 50]}

    def _claims(self, seller_id: str, path: str) -> dict[str, Any]:
        returned = self.returns[seller_id]
        suffix = seller_id[-4:]
        claim_id, order_id, item_id = f"55{suffix}01", f"20{suffix}01", f"MLM{suffix}"
        created = _iso(returned)
        if path.startswith("/post-purchase/v1/claims/search?"):
            query = parse_qs(urlsplit(path).query)
            start = _parse(query["date_created"][0])
            end = _parse(query["range"][0].rsplit("before:", 1)[1])
            row = {
                "id": claim_id,
                "date_created": created,
                "last_updated": created,
                "type": "returns",
                "status": "closed",
            }
            rows = [row] if start <= returned < end else []
            return {"data": rows, "paging": {"offset": 0, "limit": 100, "total": len(rows)}}
        if path.startswith("/orders/"):
            return {
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
            }
        if path.endswith("/returns"):
            return {
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
            }
        return {
            "id": claim_id,
            "claim_version": 1,
            "date_created": created,
            "last_updated": created,
            "order_id": order_id,
            "item_id": item_id,
            "status": "closed",
            "stage": "claim",
            "type": "returns",
            "players": [
                {"user_id": int(seller_id), "role": "respondent", "type": "seller"},
                {"user_id": 90001, "role": "complainant", "type": "buyer"},
            ],
            "related_entities": [{"type": "return", "id": f"RETURN-{claim_id}"}],
        }

    async def fetch_resource(self, *, seller_id: str, path: str) -> dict[str, Any]:
        self.calls.append((seller_id, path))
        self._maybe_fail(seller_id, path)
        if path.startswith("/orders/search?"):
            return self._order_search(seller_id, path)
        if path.startswith("/questions/search?"):
            rows = self.questions[seller_id]
            return {"total": len(rows), "questions": rows}
        if path.startswith("/questions/"):
            identity = int(path.rsplit("/", 1)[-1])
            return next(row for row in self.questions[seller_id] if row["id"] == identity)
        return self._claims(seller_id, path)

    async def fetch_resource_once(self, *, seller_id: str, path: str, **_: Any) -> dict[str, Any]:
        return await self.fetch_resource(seller_id=seller_id, path=path)

    async def request(
        self, *, method: str, seller_id: str, path: str, headers: Any = None
    ) -> httpx.Response:
        assert method == "GET"
        self.calls.append((seller_id, path))
        self._maybe_fail(seller_id, path)
        identity = path.split("/")[2].split("?")[0]
        order = next(row for row in self.orders[seller_id] if str(row["id"]) == identity)
        return httpx.Response(200, json=order)


async def _link(db: Any, seller_id: str) -> None:
    await db.meli_accounts.insert_one({"seller_id": seller_id, "status": "active"})
    await db.sheets_extension_tokens.insert_one(
        {
            "status": "active",
            "seller_scopes": [{"seller_id": seller_id, "nickname": f"n{seller_id}"}],
            "expires_at": datetime.now(UTC) + timedelta(days=30),
        }
    )


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


async def _paused_pilot(
    db: Any, gateway: YearGateway, now: datetime, *, devoluciones_days_back: int = 12
) -> None:
    """The pilot as in production on 2026-10-13, with its paused history plan.

    Certificate mode from one window of that plan ``devoluciones_days_back``
    days ago (production: 2026-06-01); orders proven past the year target by
    the old pilot's retained proofs (production: 2025-09-24); questions proven
    for the last 90 days only (production: 2026-07-14).
    """
    from zeler_sheets.devoluciones_runner import advance_onboarding_devoluciones
    from zeler_sheets.formulas.year_history import year_history_target

    settled = datetime.combine((now - timedelta(hours=1)).date(), time.min, tzinfo=UTC)
    start = settled - timedelta(days=devoluciones_days_back)
    cutoff = now.replace(microsecond=now.microsecond // 1000 * 1000)
    plan = {
        "_id": PILOT,
        "seller_id": PILOT,
        "state": "active",
        "eligible": True,
        "policy_version": "history-on-link-v1",
        "authority": {"kind": "account_link_policy"},
        "date_from": start - timedelta(days=30),
        "date_to": cutoff,
        "cutoff": cutoff,
        "sources": ["claims_returns"],
        "budget": {"claims_returns": {"physical_attempts": 20000, "consumed": 0}},
        "incremental_policy": {"max_daily_total": 2000, "max_daily_source": 1000},
    }
    await db[PLANS].insert_one(plan)

    async def charge() -> None:
        await db[PLANS].update_one({"_id": PILOT}, {"$inc": {"budget.claims_returns.consumed": 1}})

    end = start + timedelta(days=10)
    first = await advance_onboarding_devoluciones(
        db, plan, start=start, end=end, gateway=gateway, charge=charge
    )
    assert first["state"] == "active" and first["advanced"] == 1
    await db[RUNS].update_one({"_id": first["run_id"]}, {"$set": {"not_before": cutoff}})
    final = await advance_onboarding_devoluciones(
        db, plan, start=start, end=end, gateway=gateway, charge=charge
    )
    assert final["state"] == "completed" and final["finalized"] == 1
    await db[PLANS].update_one({"_id": PILOT}, {"$set": {"state": "paused"}})
    control = await db.sheets_devoluciones_operations.find_one({"seller_id": PILOT})
    assert control["coverage_mode"] == "active"
    old_orders = year_history_target(now) - timedelta(days=18)
    for read_model, live_from in (
        ("orders", now - timedelta(days=30)),
        ("questions", now - timedelta(days=90)),
    ):
        marker: dict[str, Any] = {
            "_id": f"{PILOT}:{read_model}",
            "seller_id": PILOT,
            "read_model": read_model,
            "state": "reconciled",
            "date_from": live_from,
            # Kept current by the sweeps, as in production.
            "reconciled_until": now - timedelta(minutes=5),
            "fresh_until": now - timedelta(minutes=5),
            "updated_at": now - timedelta(minutes=5),
            "valid_until": now + timedelta(minutes=25),
            "source": "zelerdata_read_model_reconcile",
            "schema_version": 1,
        }
        if read_model == "orders":
            marker["retained_intervals"] = [
                {
                    "state": "reconciled",
                    "date_from": old_orders,
                    "reconciled_until": live_from,
                    "valid_until": now + timedelta(minutes=25),
                }
            ]
        await db[FRESHNESS].insert_one(marker)
    # The old pilot's twelve-month question scan, pending since 2026-10-06
    # under its own authority: only its owning workers could run it.
    await db[JOBS].insert_one(
        {
            "_id": "legacy-question-scan",
            "seller_id": PILOT,
            "read_model": "questions",
            "state": "pending",
            "attempts": 0,
            "policy_authority": "history-on-link-v1",
            "history_protocol_version": 1,
            "date_from": year_history_target(now) - timedelta(days=18),
            "date_to": now - timedelta(days=19),
            "created_at": now - timedelta(days=7),
            "updated_at": now - timedelta(days=7),
            "available_at": now - timedelta(days=7),
        }
    )


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
        "ZELERDATA_DEVOLUCIONES_INITIAL_COVERAGE_ENABLED",
        "ZELERDATA_DEVOLUCIONES_INTRADAY_ENABLED",
        # Unset: the year history is on by default.
        "ZELERDATA_YEAR_HISTORY_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ZELERDATA_SCHEDULED_RENEWAL_REFRESH_ENABLED", "false")
    monkeypatch.setenv("ZELERDATA_HISTORY_ON_LINK_ENABLED", "false")
    monkeypatch.setenv("ZELERDATA_DEVOLUCIONES_ADVANCE_ENABLED", "true")
    monkeypatch.setenv("ZELERDATA_REFRESH_ENABLED", "true")
    monkeypatch.setenv("ZELERDATA_REFRESH_SELLERS", "all")
    monkeypatch.setenv("ZELERDATA_FORMULA_RECOVERY_ENABLED", "true")
    monkeypatch.setenv("ZELERDATA_FORMULA_RECOVERY_SELLERS", "all")


def _ranges_worker(db: Any, gateway: YearGateway, **queue_options: Any) -> Any:
    from zeler_sheets.formulas.recovery import FormulaRecoveryQueue
    from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker

    return FormulaRecoveryWorker(
        db=db,
        queue=FormulaRecoveryQueue(db, **queue_options),
        gateway=gateway,
        detail_gateway=gateway,
        lane="ranges",
    )


async def _drain(*workers: Any) -> None:
    """Run every ready range job, as the worker's ranges lane does between cycles."""
    for _ in range(200):
        results = await asyncio.gather(*(worker.process_one() for worker in workers))
        if not any(results):
            return
    raise AssertionError("the ranges lane did not drain")


async def _year_jobs(db: Any, seller_id: str) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = (
        await db[JOBS].find({"seller_id": seller_id, "year_history": True}).to_list(length=None)
    )
    return jobs


async def _year_runs(db: Any, seller_id: str) -> int:
    from zeler_sheets.devoluciones_runner import YEAR_HISTORY_AUTHORIZATION

    return int(
        await db[RUNS].count_documents(
            {"seller_id": seller_id, "authorization_id": YEAR_HISTORY_AUTHORIZATION}
        )
    )


def _context(formula: str, seller_id: str, args: Mapping[str, Any]) -> Any:
    from zeler_sheets.formulas.dispatcher import FormulaExecutionContext
    from zeler_sheets.formulas.registry import FormulaRegistry

    return FormulaExecutionContext(
        contract=FormulaRegistry.default().find_required(formula),
        cuenta="seller",
        seller_id=seller_id,
        seller_nickname="seller",
        token_id="token-1",  # noqa: S106 - a fake extension token id
        args=args,
        request_id="req-1",
    )


async def _sales(db: Any, seller_id: str, first: datetime, last: datetime) -> Any:
    from zeler_sheets.formulas.handlers_orders_questions import OrderQuestionFormulaHandlers
    from zeler_sheets.formulas.read_models import FormulaReadModelRepository

    handlers = OrderQuestionFormulaHandlers(FormulaReadModelRepository(db=db))
    return await handlers.sheetseller_ventas_totales(
        _context(
            "ZELERDATA_VENTASTOTALES",
            seller_id,
            {"fecha_inicial": first.date().isoformat(), "fecha_final": last.date().isoformat()},
        )
    )


async def _question_kpi(db: Any, seller_id: str, first: datetime, last: datetime) -> Any:
    from zeler_sheets.formulas.handlers_orders_questions import OrderQuestionFormulaHandlers
    from zeler_sheets.formulas.read_models import FormulaReadModelRepository

    handlers = OrderQuestionFormulaHandlers(FormulaReadModelRepository(db=db))
    return await handlers.sheetseller_preguntas_kpi(
        _context(
            "ZELERDATA_PREGUNTASKPI",
            seller_id,
            {"fecha_inicio": first.date().isoformat(), "fecha_final": last.date().isoformat()},
        )
    )


async def _devoluciones(db: Any, seller_id: str, first: datetime, last: datetime) -> Any:
    from zeler_sheets.formulas.handlers_returns_histories_withdrawals import (
        ReturnsHistoriesWithdrawalsFormulaHandlers,
    )
    from zeler_sheets.formulas.read_models import FormulaReadModelRepository

    handlers = ReturnsHistoriesWithdrawalsFormulaHandlers(FormulaReadModelRepository(db=db))
    return await handlers.sheetseller_devoluciones(
        _context(
            "ZELERDATA_DEVOLUCIONES",
            seller_id,
            {"fecha_inicio": first.date().isoformat(), "fecha_final": last.date().isoformat()},
        )
    )


def _expected_total(gateway: YearGateway, seller_id: str, first: datetime, last: datetime) -> int:
    end = datetime.combine(last.date() + timedelta(days=1), time.min, tzinfo=UTC)
    start = datetime.combine(first.date(), time.min, tzinfo=UTC)
    return 100 * sum(
        start <= _parse(row["date_created"]) < end for row in gateway.orders[seller_id]
    )


async def _covered(db: Any, seller_id: str) -> bool:
    from zeler_platform_core.devoluciones_certificates import CoverageUnavailableError
    from zeler_sheets.devoluciones_runner import _settled_midnight
    from zeler_sheets.formulas.read_models import read_model_reconciliation_marker_covers
    from zeler_sheets.formulas.year_history import year_history_target

    now = datetime.now(UTC)
    # The target moves forward a day at a time; check the current one.
    target = year_history_target(now)
    for read_model in ("orders", "questions"):
        marker = await db[FRESHNESS].find_one({"_id": f"{seller_id}:{read_model}"})
        if not read_model_reconciliation_marker_covers(
            marker, date_from=target, date_to=now - timedelta(hours=6), allow_live_claim=False
        ):
            return False
    try:
        await select_covering_proofs(db, seller_id, target, _settled_midnight(now), now)
    except CoverageUnavailableError:
        return False
    return True


@pytest.mark.asyncio
async def test_a_new_seller_gets_twelve_months_beside_the_walking_pilot(
    year_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from infra.operations import zelerdata_read_model_reconcile as reconcile

    from zeler_sheets.consumer import build_zelerdata_refresh_supervisor
    from zeler_sheets.formulas.dispatcher import FormulaDataUnavailableError
    from zeler_sheets.formulas.year_history import year_history_target

    db = year_db
    now = datetime.now(UTC)
    target = year_history_target(now)
    gateway = YearGateway(now=now, sellers=(PILOT, NEW_SELLER), first=target - timedelta(days=40))
    monkeypatch.setattr(
        reconcile,
        "create_runtime_historical_meli_gateways",
        lambda: SimpleNamespace(order_detail_gateway=gateway),
    )
    await _paused_pilot(db, gateway, now)
    gateway.calls.clear()
    for seller_id in (PILOT, NEW_SELLER):
        await _link(db, seller_id)
    await _bootstrap_claims_stage(db, NEW_SELLER)
    pilot_markers = {
        read_model: await db[FRESHNESS].find_one({"_id": f"{PILOT}:{read_model}"})
        for read_model in ("orders", "questions")
    }
    _enable_all_mode(monkeypatch)
    supervisor = await build_zelerdata_refresh_supervisor(db=db)
    assert await supervisor._explorer.discover_sellers() == (PILOT, NEW_SELLER)
    worker = _ranges_worker(db, gateway)

    # Today a new seller has no range older than 90 days.
    old_first, old_last = now - timedelta(days=300), now - timedelta(days=280)
    with pytest.raises(FormulaDataUnavailableError):
        await _sales(db, NEW_SELLER, old_first, old_last)

    admitted_per_cycle: list[int] = []
    for _ in range(120):
        before = await db[JOBS].count_documents({"year_history": True})
        runs_before = await db[RUNS].count_documents({})
        await supervisor.run_cycle()
        admitted_per_cycle.append(await db[JOBS].count_documents({"year_history": True}) - before)
        # At most one window of DEVOLUCIONES source work per cycle, for the fleet.
        assert await db[RUNS].count_documents({}) - runs_before <= 1
        await _drain(worker)
        if await _covered(db, NEW_SELLER):
            break
    else:
        raise AssertionError("twelve months were not acquired")

    # One portion per cycle for the whole fleet.
    assert max(admitted_per_cycle) == 1
    jobs = await _year_jobs(db, NEW_SELLER)
    assert {job["read_model"] for job in jobs} == {"orders", "questions"}
    assert {job["state"] for job in jobs} == {"completed"}
    assert await _year_runs(db, NEW_SELLER) > 0

    # Ranges inside the year are served, from every source.
    sales = await _sales(db, NEW_SELLER, old_first, old_last)
    assert sales.values == [[_expected_total(gateway, NEW_SELLER, old_first, old_last)]]
    kpi = await _question_kpi(db, NEW_SELLER, old_first, old_last)
    assert kpi.meta["questions_count"] > 0
    returned = gateway.returns[NEW_SELLER]
    result = await _devoluciones(db, NEW_SELLER, returned - timedelta(days=3), returned)
    assert result.values == [["MLM0001", "SKU-0001", 2, "Title"]]
    stored = {row["_id"] async for row in db.orders.find({"seller_id": NEW_SELLER}, {"_id": 1})}
    reached = min(job["date_from"] for job in jobs if job["read_model"] == "orders")
    assert target <= reached <= year_history_target(datetime.now(UTC))
    inside = {
        str(row["id"])
        for row in gateway.orders[NEW_SELLER]
        if _parse(row["date_created"]) >= reached
    }
    assert inside <= stored
    # Nothing older than the year was requested.
    assert not {str(row["id"]) for row in gateway.orders[NEW_SELLER]} - inside & stored

    # A range that starts before the year stays unavailable, never empty.
    before_year = reached - timedelta(days=10)
    with pytest.raises(FormulaDataUnavailableError):
        await _sales(db, NEW_SELLER, before_year, before_year + timedelta(days=5))
    with pytest.raises(FormulaDataUnavailableError):
        await _question_kpi(db, NEW_SELLER, before_year, before_year + timedelta(days=5))
    with pytest.raises(FormulaDataUnavailableError):
        await _devoluciones(db, NEW_SELLER, before_year, before_year + timedelta(days=5))

    # Covered: the next cycles plan nothing more for the new seller.
    settled_jobs = len(await _year_jobs(db, NEW_SELLER))
    settled_runs = await _year_runs(db, NEW_SELLER)
    for _ in range(2):
        await supervisor.run_cycle()
        await _drain(worker)
    assert len(await _year_jobs(db, NEW_SELLER)) == settled_jobs
    assert await _year_runs(db, NEW_SELLER) == settled_runs

    # The pilot walked beside it, sharing the one portion and the one window
    # per cycle: questions and DEVOLUCIONES only. Its orders were already
    # proven past the target, so it asked for no order portion and no order
    # search older than the ordinary sweeps (at most the weekly 90 days).
    assert {job["read_model"] for job in await _year_jobs(db, PILOT)} == {"questions"}
    assert await _year_runs(db, PILOT) > 0
    ordinary_reach = now - timedelta(days=91)
    assert not any(
        "order.date_created.from" in path
        and _parse(parse_qs(urlsplit(path).query)["order.date_created.from"][0]) < ordinary_reach
        for seller_id, path in gateway.calls
        if seller_id == PILOT
    )
    orders_after = await db[FRESHNESS].find_one({"_id": f"{PILOT}:orders"})
    assert (
        orders_after["retained_intervals"][0]["date_from"]
        == (pilot_markers["orders"]["retained_intervals"][0]["date_from"])
    )


@pytest.mark.asyncio
async def test_the_paused_pilot_walks_questions_and_devoluciones_once_across_a_restart(
    year_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Production edges of 2026-10-13: orders covered, questions and DEVOLUCIONES short.

    The walk extends the existing proofs without overlapping them, survives a
    restart into two workers without a duplicate, leaves the legacy plan and
    its runs untouched, and costs what the code says.
    """
    from infra.operations import zelerdata_read_model_reconcile as reconcile

    from zeler_platform_core.devoluciones_runs import WINDOW_DAYS
    from zeler_sheets.consumer import build_zelerdata_refresh_supervisor
    from zeler_sheets.devoluciones_runner import _settled_midnight
    from zeler_sheets.formulas.year_history import proven_edge, year_history_target

    db = year_db
    # Milliseconds, as BSON stores them.
    now = datetime.now(UTC).replace(microsecond=datetime.now(UTC).microsecond // 1000 * 1000)
    gateway = YearGateway(
        now=now, sellers=(PILOT,), first=year_history_target(now) - timedelta(days=40)
    )
    monkeypatch.setattr(
        reconcile,
        "create_runtime_historical_meli_gateways",
        lambda: SimpleNamespace(order_detail_gateway=gateway),
    )
    # Production: the oldest certificate on 2026-06-01, 134 days back.
    await _paused_pilot(db, gateway, now, devoluciones_days_back=134)
    gateway.calls.clear()
    await _link(db, PILOT)
    legacy_plan = await db[PLANS].find_one({"_id": PILOT})
    legacy_runs = await db[RUNS].find({"seller_id": PILOT}).to_list(None)
    legacy_scan = await db[JOBS].find_one({"_id": "legacy-question-scan"})
    oldest_before = (
        await db[CERTIFICATES].find_one({"seller_id": PILOT}, sort=[("date_from", 1)])
    )["date_from"]
    question_edge = proven_edge(await db[FRESHNESS].find_one({"_id": f"{PILOT}:questions"}))
    assert question_edge == now - timedelta(days=90)
    _enable_all_mode(monkeypatch)

    supervisors = [await build_zelerdata_refresh_supervisor(db=db)]
    workers = [_ranges_worker(db, gateway)]
    for cycle in range(80):
        if cycle == 5:
            # A restart: new processes, and from now on two of them.
            supervisors = [await build_zelerdata_refresh_supervisor(db=db) for _ in range(2)]
            workers = [_ranges_worker(db, gateway), _ranges_worker(db, gateway)]
        await asyncio.gather(*(each.run_cycle() for each in supervisors))
        await _drain(*workers)
        if await _covered(db, PILOT):
            break
    else:
        raise AssertionError("the pilot's year was not acquired")
    target = year_history_target(datetime.now(UTC))
    pilot_calls = [path for seller_id, path in gateway.calls if seller_id == PILOT]

    # Orders: already a year, so no portion and no search older than the sweeps.
    jobs = await _year_jobs(db, PILOT)
    assert {job["read_model"] for job in jobs} == {"questions"}
    assert not any(
        "order.date_created.from" in path
        and _parse(parse_qs(urlsplit(path).query)["order.date_created.from"][0])
        < now - timedelta(days=91)
        for path in pilot_calls
    )

    # Questions: completed portions tile the gap from the July edge back to the
    # target, without a gap, an overlap or a repeated detail read.
    assert {job["state"] for job in jobs} == {"completed"}
    portions = sorted((job["date_from"], job["date_to"]) for job in jobs)
    assert portions[0][0] <= target
    assert portions[-1][1] == question_edge.replace(minute=0, second=0, microsecond=0) + timedelta(
        hours=1
    )
    assert all(left[1] == right[0] for left, right in zip(portions, portions[1:], strict=False))
    walked = [
        str(row["id"])
        for row in gateway.questions[PILOT]
        if portions[0][0] <= _parse(row["date_created"]) < question_edge
    ]
    stored = {row["_id"] async for row in db.questions.find({"seller_id": PILOT}, {"_id": 1})}
    assert set(walked) <= stored
    details = [path.rsplit("/", 1)[-1] for path in pilot_calls if path.startswith("/questions/7")]
    # Cost from the code: each portion scans the seller's list (one page of 50
    # here) and reads one detail per question in its range, once.
    assert sorted(identity for identity in details if identity in walked) == sorted(walked)

    # DEVOLUCIONES: 10-day windows from the June certificate back to the target,
    # each acquired once, joined to the existing certificates without overlap.
    from zeler_sheets.devoluciones_runner import YEAR_HISTORY_AUTHORIZATION

    year_runs = (
        await db[RUNS]
        .find({"seller_id": PILOT, "authorization_id": YEAR_HISTORY_AUTHORIZATION})
        .to_list(None)
    )
    windows = sorted((run["start"], run["end"]) for run in year_runs)
    assert {run["state"] for run in year_runs} == {"completed"}
    assert len(windows) == len(set(windows))
    assert windows[-1][1] == oldest_before and windows[0][0] <= target
    assert all(left[1] == right[0] for left, right in zip(windows, windows[1:], strict=False))
    assert len(windows) == -(-(oldest_before - windows[0][0]) // timedelta(days=WINDOW_DAYS))
    await select_covering_proofs(
        db, PILOT, target, _settled_midnight(datetime.now(UTC)), datetime.now(UTC)
    )
    old_searches = [
        path
        for path in pilot_calls
        if path.startswith("/post-purchase/v1/claims/search?")
        and _parse(parse_qs(urlsplit(path).query)["date_created"][0]) < oldest_before
    ]
    # 2 x (2 x ceil(I/100) + 2 x H + U): four search pages per window, and the
    # one old return (claim, return and order, twice) in its window.
    assert len(old_searches) == 4 * len(windows)
    claim_reads = [
        path
        for path in pilot_calls
        if path.startswith(("/post-purchase/v1/claims/5", "/post-purchase/v2/", "/orders/20"))
    ]
    assert len(claim_reads) == 6

    # The legacy plan, its runs and its pending question scan are left exactly
    # as they were: the walk neither runs, coalesces with nor counts that scan.
    assert await db[PLANS].find_one({"_id": PILOT}) == legacy_plan
    for run in legacy_runs:
        assert await db[RUNS].find_one({"_id": run["_id"]}) == run
    assert await db[JOBS].find_one({"_id": "legacy-question-scan"}) == legacy_scan


@pytest.mark.asyncio
async def test_a_failed_year_window_left_prepared_is_replaced_and_the_walk_goes_on(
    year_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Production, 2026-10-13: a year window failed at 03:06 with its window prepared.

    The next window ends at the same oldest certificate, so it was the same
    run of the day: no year window was admitted for 16 hours. Now the next free
    cycle replaces it with one new run of that window, and the walk continues
    from its certificate without a duplicate.
    """
    from infra.operations import zelerdata_read_model_reconcile as reconcile

    from zeler_sheets.consumer import build_zelerdata_refresh_supervisor
    from zeler_sheets.devoluciones_runner import (
        YEAR_HISTORY_AUTHORIZATION,
        _settled_midnight,
        advance_year_history_devoluciones,
    )
    from zeler_sheets.formulas.seller_scope import EligibleSellerGate
    from zeler_sheets.formulas.year_history import year_history_status, year_history_target

    db = year_db
    now = datetime.now(UTC).replace(microsecond=datetime.now(UTC).microsecond // 1000 * 1000)
    gateway = YearGateway(
        now=now, sellers=(PILOT,), first=year_history_target(now) - timedelta(days=40)
    )
    monkeypatch.setattr(
        reconcile,
        "create_runtime_historical_meli_gateways",
        lambda: SimpleNamespace(order_detail_gateway=gateway),
    )
    await _paused_pilot(db, gateway, now)
    await _link(db, PILOT)
    _enable_all_mode(monkeypatch)
    oldest = (await db[CERTIFICATES].find_one({"seller_id": PILOT}, sort=[("date_from", 1)]))[
        "date_from"
    ]
    year = {"seller_id": PILOT, "authorization_id": YEAR_HISTORY_AUTHORIZATION}

    # The first year window fails at the source: the run fails, its window stays prepared.
    gateway.fail(PILOT, "/post-purchase/v1/claims/search?", 1)
    assert await advance_year_history_devoluciones(db, PILOT, eligible=EligibleSellerGate(db))
    (failed,) = await db[RUNS].find(year).to_list(None)
    assert failed["state"] == "failed" and failed["end"] == oldest
    # The run keeps which check refused it (2026-10-13: production kept none).
    assert failed["failure_reason"] == "claim_search_server"
    window = await db.sheets_devoluciones_run_windows.find_one({"run_id": failed["_id"]})
    assert window["state"] == "prepared"
    # Sixteen hours later, as in production.
    await db[RUNS].update_one(
        {"_id": failed["_id"]},
        {
            "$set": {
                field: failed[field] - timedelta(hours=16)
                for field in ("created_at", "updated_at", "expires_at")
            }
        },
    )
    failed = await db[RUNS].find_one({"_id": failed["_id"]})
    status = await year_history_status(db, PILOT, datetime.now(UTC))
    assert status["sources"]["devoluciones"]["edge"] == oldest.isoformat()
    assert status["sources"]["devoluciones"]["retrying"] == {
        "date_from": failed["start"].isoformat(),
        "date_to": oldest.isoformat(),
        "state": "failed",
        "runs": 1,
        "failure_reason": "claim_search_server",
    }

    supervisor = await build_zelerdata_refresh_supervisor(db=db)
    for _ in range(12):
        await supervisor.run_cycle()
        if await db[RUNS].count_documents({**year, "state": "completed"}) >= 2:
            break
    else:
        raise AssertionError("the year walk stayed behind the failed window")

    # One replacement of the failed window, then the next window back from it.
    completed = await db[RUNS].find({**year, "state": "completed"}).sort("start", -1).to_list(None)
    assert [(run["start"], run["end"]) for run in completed] == [
        (failed["start"], oldest),
        (completed[1]["start"], failed["start"]),
    ]
    assert await db[RUNS].count_documents({**year, "start": failed["start"]}) == 2
    # The abandoned run and its prepared window are left as they were.
    assert await db[RUNS].find_one({"_id": failed["_id"]}) == failed
    assert await db.sheets_devoluciones_run_windows.find_one({"run_id": failed["_id"]}) == window
    # Each range is certified once, and the certificates join without a gap.
    certificates = await db[CERTIFICATES].find({"seller_id": PILOT}).to_list(None)
    ranges = [(row["date_from"], row["date_to"]) for row in certificates]
    assert len(ranges) == len(set(ranges))
    current = datetime.now(UTC)
    await select_covering_proofs(
        db, PILOT, completed[1]["start"], _settled_midnight(current), current
    )
    status = await year_history_status(db, PILOT, current)
    assert status["sources"]["devoluciones"]["edge"] == completed[1]["start"].isoformat()
    assert "retrying" not in status["sources"]["devoluciones"]


@pytest.mark.asyncio
async def test_a_failed_window_fails_closed_under_the_runs_validator_without_its_reason(
    year_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The worker may run before the runs validator that allows ``failure_reason``.

    Applying a validator is its own production step, so the reason is stored
    only once the collection accepts it; until then the run still fails as
    before and the reason is only in the log.
    """
    from infra.operations import zelerdata_read_model_reconcile as reconcile
    from structlog.testing import capture_logs

    from zeler_sheets.devoluciones_runner import (
        YEAR_HISTORY_AUTHORIZATION,
        advance_year_history_devoluciones,
    )
    from zeler_sheets.formulas.seller_scope import EligibleSellerGate
    from zeler_sheets.formulas.year_history import year_history_target

    db = year_db
    schema = json.loads(
        (Path(__file__).resolve().parents[2] / "infra/mongo/schemas" / f"{RUNS}.json").read_text()
    )["$jsonSchema"]
    assert schema["properties"].pop("failure_reason") == {"bsonType": ["string", "null"]}
    await db.command({"collMod": RUNS, "validator": {"$jsonSchema": schema}})
    now = datetime.now(UTC).replace(microsecond=datetime.now(UTC).microsecond // 1000 * 1000)
    gateway = YearGateway(
        now=now, sellers=(PILOT,), first=year_history_target(now) - timedelta(days=40)
    )
    monkeypatch.setattr(
        reconcile,
        "create_runtime_historical_meli_gateways",
        lambda: SimpleNamespace(order_detail_gateway=gateway),
    )
    await _paused_pilot(db, gateway, now)
    await _link(db, PILOT)
    _enable_all_mode(monkeypatch)
    gateway.fail(PILOT, "/post-purchase/v1/claims/search?", 1)

    with capture_logs() as logs:
        assert await advance_year_history_devoluciones(db, PILOT, eligible=EligibleSellerGate(db))

    (failed,) = (
        await db[RUNS]
        .find({"seller_id": PILOT, "authorization_id": YEAR_HISTORY_AUTHORIZATION})
        .to_list(None)
    )
    assert failed["state"] == "failed"
    assert "failure_reason" not in failed
    (logged,) = [log for log in logs if log["event"] == "zelerdata.devoluciones_tail_failed"]
    assert logged["failure_reason"] == "claim_search_server"


async def _live_markers(db: Any, seller_id: str, now: datetime) -> None:
    """What the ordinary sweeps leave: orders and questions proven for the last week."""
    for read_model in ("orders", "questions"):
        await db[FRESHNESS].insert_one(
            {
                "_id": f"{seller_id}:{read_model}",
                "seller_id": seller_id,
                "read_model": read_model,
                "state": "reconciled",
                "date_from": now - timedelta(days=7, minutes=17),
                "reconciled_until": now,
                "fresh_until": now,
                "updated_at": now,
                "valid_until": now + timedelta(minutes=30),
                "source": "zelerdata_read_model_reconcile",
                "schema_version": 1,
            }
        )


@pytest.mark.asyncio
async def test_restart_two_workers_and_a_failed_portion_leave_no_gap_and_no_duplicate(
    year_db: Any,
) -> None:
    from zeler_sheets.formulas.read_models import read_model_reconciliation_marker_covers
    from zeler_sheets.formulas.recovery import FormulaRecoveryQueue
    from zeler_sheets.formulas.seller_scope import EligibleSellerGate
    from zeler_sheets.formulas.year_history import (
        YearHistoryPlanner,
        proven_edge,
        year_history_target,
    )

    db = year_db
    start = datetime.now(UTC).replace(microsecond=0)
    clock = {"now": start}

    def now() -> datetime:
        return clock["now"]

    target = year_history_target(start)
    sellers = (NEW_SELLER, SECOND_SELLER)
    gateway = YearGateway(now=start, sellers=sellers, first=target - timedelta(days=40))
    for seller_id in sellers:
        await _link(db, seller_id)
        await _live_markers(db, seller_id, start)
    # The new seller's first order portion fails all three attempts.
    gateway.fail(NEW_SELLER, "/orders/search?", 3)
    gate = EligibleSellerGate(db)

    def planner() -> YearHistoryPlanner:
        return YearHistoryPlanner(
            db=db, queue=FormulaRecoveryQueue(db, now=now), eligible=gate, now=now
        )

    def worker() -> Any:
        return _ranges_worker(db, gateway, now=now)

    planners, workers = [planner()], [worker()]
    for cycle in range(60):
        if cycle == 6:
            # A restart: new processes, and from now on two of them.
            planners, workers = [planner(), planner()], [worker(), worker()]
        before = await db[JOBS].count_documents({"year_history": True})
        await asyncio.gather(*(each.plan(sellers) for each in planners))
        assert await db[JOBS].count_documents({"year_history": True}) - before <= 1
        await _drain(*workers)
        clock["now"] += timedelta(minutes=20)
        edges = [
            proven_edge(await db[FRESHNESS].find_one({"_id": f"{seller_id}:{read_model}"}))
            for seller_id in sellers
            for read_model in ("orders", "questions")
        ]
        # The target moves with the clock, a day at a time.
        if all(edge is not None and edge <= year_history_target(now()) for edge in edges):
            break
    else:
        raise AssertionError("both sellers were not covered")
    assert target <= year_history_target(now()) <= target + timedelta(days=1)
    target = year_history_target(now())

    jobs = await db[JOBS].find({"year_history": True}).sort("created_at", 1).to_list(None)
    failed = [job for job in jobs if job["state"] == "failed"]
    assert len(failed) == 1 and failed[0]["seller_id"] == NEW_SELLER
    assert failed[0]["failure_reason"] == "source_temporarily_unavailable"
    # The same edge again, with half the span; meanwhile the other seller went on.
    retry = next(
        job
        for job in jobs
        if job["seller_id"] == NEW_SELLER
        and job["read_model"] == "orders"
        and job["state"] == "completed"
        and job["date_to"] == failed[0]["date_to"]
    )
    assert (
        retry["date_to"] - retry["date_from"] == (failed[0]["date_to"] - failed[0]["date_from"]) / 2
    )
    assert any(
        job["seller_id"] == SECOND_SELLER
        and failed[0]["updated_at"] <= job["created_at"] <= retry["created_at"]
        for job in jobs
    )

    for seller_id in sellers:
        for read_model in ("orders", "questions"):
            # The completed portions tile the year without a gap or an overlap.
            portions = sorted(
                (job["date_from"], job["date_to"])
                for job in jobs
                if job["seller_id"] == seller_id
                and job["read_model"] == read_model
                and job["state"] == "completed"
            )
            assert portions[0][0] <= target
            assert all(
                left[1] == right[0] for left, right in zip(portions, portions[1:], strict=False)
            )
            marker = await db[FRESHNESS].find_one({"_id": f"{seller_id}:{read_model}"})
            assert read_model_reconciliation_marker_covers(
                marker, date_from=target, date_to=start, allow_live_claim=False, now=clock["now"]
            )
        stored = [row["_id"] async for row in db.orders.find({"seller_id": seller_id})]
        assert len(stored) == len(set(stored))
        walked = [
            job for job in jobs if job["seller_id"] == seller_id and job["read_model"] == "orders"
        ]
        reached = min(job["date_from"] for job in walked)
        # The last week was already proven by the sweeps; the walk starts there.
        assert set(stored) == {
            str(row["id"])
            for row in gateway.orders[seller_id]
            if reached <= _parse(row["date_created"]) < max(job["date_to"] for job in walked)
        }


@pytest.mark.asyncio
async def test_a_question_portion_the_source_cannot_complete_stops_at_an_honest_edge(
    year_db: Any,
) -> None:
    """Production, 2026-10-13: the pilot's last question portion failed 53 times.

    It failed ``source_incomplete`` at its first attempt and was reopened whole
    after every 15-minute cooldown with its attempts back at zero, so it was
    never halved and scanned the seller's questions every cycle. Now it uses
    its three attempts, is halved down to the hour that holds the question the
    source cannot give whole, and that hour is retried every 6 hours. The edge
    stops right above it: what is newer is proven, the hour and what is older
    are not, and the status says so.
    """
    from zeler_sheets.formulas.recovery import FormulaRecoveryQueue
    from zeler_sheets.formulas.seller_scope import EligibleSellerGate
    from zeler_sheets.formulas.year_history import (
        YearHistoryPlanner,
        _proven_blocks,
        year_history_status,
        year_history_target,
    )

    db = year_db
    start = datetime.now(UTC).replace(microsecond=0)
    clock = {"now": start}

    def now() -> datetime:
        return clock["now"]

    target = year_history_target(start)
    gateway = YearGateway(now=start, sellers=(NEW_SELLER,), first=target - timedelta(days=40))
    await _link(db, NEW_SELLER)
    await _live_markers(db, NEW_SELLER, start)
    # An answered question well inside the year whose answer the source no
    # longer returns: every acquisition of its hour fails closed.
    bad = next(
        row
        for row in gateway.questions[NEW_SELLER]
        if _parse(row["date_created"]) > target + timedelta(days=20)
    )
    del bad["answer"]
    hour = _parse(bad["date_created"]).replace(minute=0, second=0)
    planner = YearHistoryPlanner(
        db=db,
        queue=FormulaRecoveryQueue(db, now=now),
        eligible=EligibleSellerGate(db),
        now=now,
        models=("questions",),
    )
    worker = _ranges_worker(db, gateway, now=now)

    def scans() -> int:
        return sum(path.startswith("/questions/search?") for _, path in gateway.calls)

    # Three days of 20-minute cycles.
    cycles = 3 * 72
    scanned: list[int] = []
    for _ in range(cycles):
        await planner.plan((NEW_SELLER,))
        await _drain(worker)
        scanned.append(scans())
        clock["now"] += timedelta(minutes=20)

    # The edge stops right above the hour, and everything newer is proven.
    marker = await db[FRESHNESS].find_one({"_id": f"{NEW_SELLER}:questions"})
    blocks = _proven_blocks(marker)
    assert blocks[-1][0] == hour + timedelta(hours=1)
    assert not any(block_start <= hour < block_end for block_start, block_end in blocks)
    stored = {row["_id"] async for row in db.questions.find({"seller_id": NEW_SELLER})}
    assert str(bad["id"]) not in stored
    assert {
        str(row["id"])
        for row in gateway.questions[NEW_SELLER]
        if hour + timedelta(hours=1) <= _parse(row["date_created"]) < start - timedelta(days=7)
    } <= stored

    # The hour used its three attempts and waits; it is not reopened every cycle.
    jobs = await _year_jobs(db, NEW_SELLER)
    (stuck,) = [
        job
        for job in jobs
        if (job["date_from"], job["date_to"]) == (hour, hour + timedelta(hours=1))
    ]
    assert (stuck["state"], stuck["attempts"], stuck["failure_reason"]) == (
        "failed",
        3,
        "source_incomplete",
    )
    # A binary search: one failed portion per halving of the first one that
    # failed, each portion acquired once. Then at most four retries of three
    # attempts a day, one scan each.
    first_failed = min(
        (job for job in jobs if job["state"] == "failed"), key=lambda job: job["created_at"]
    )
    halvings = (first_failed["date_to"] - first_failed["date_from"]) // timedelta(hours=1)
    assert sum(job["state"] == "failed" for job in jobs) <= halvings.bit_length()
    acquired = [(job["date_from"], job["date_to"]) for job in jobs if job["state"] == "completed"]
    assert len(acquired) == len(set(acquired))
    assert scanned[-1] - scanned[-73] <= 12

    # Honest: not covered, with the hour that holds it back.
    status = await year_history_status(db, NEW_SELLER, now())
    questions = status["sources"]["questions"]
    assert questions["covered"] is False
    assert questions["edge"] == (hour + timedelta(hours=1)).isoformat()
    assert questions["retrying"]["date_from"] == hour.isoformat()
    assert questions["retrying"]["failure_reason"] == "source_incomplete"


@pytest.mark.asyncio
async def test_switched_off_acquires_nothing_new(
    year_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from zeler_sheets.consumer import build_zelerdata_refresh_supervisor
    from zeler_sheets.formulas.recovery import FormulaRecoveryQueue, YearHistoryRecoveryRequest

    db = year_db
    now = datetime.now(UTC)
    gateway = YearGateway(now=now, sellers=(PILOT, NEW_SELLER), first=now - timedelta(days=400))
    # The paused pilot, short of a year in questions and DEVOLUCIONES, stops too.
    await _paused_pilot(db, gateway, now, devoluciones_days_back=134)
    gateway.calls.clear()
    for seller_id in (PILOT, NEW_SELLER):
        await _link(db, seller_id)
    await _live_markers(db, NEW_SELLER, now)
    # A portion queued before the switch was turned off.
    queued = YearHistoryRecoveryRequest(
        NEW_SELLER, "orders", now - timedelta(days=37), now - timedelta(days=7)
    )
    await FormulaRecoveryQueue(db).enqueue(queued)
    _enable_all_mode(monkeypatch)
    monkeypatch.setenv("ZELERDATA_YEAR_HISTORY_ENABLED", "false")
    supervisor = await build_zelerdata_refresh_supervisor(db=db)
    assert supervisor._year_history_planner is None
    assert supervisor._devoluciones_year_history_advancer is None

    off = _ranges_worker(db, gateway, year_history_enabled=False)
    for _ in range(3):
        await supervisor.run_cycle()
        await _drain(off)
    job = await db[JOBS].find_one({"_id": queued.key})
    assert job["state"] == "pending" and job["attempts"] == 0
    assert await db[JOBS].count_documents({"year_history": True}) == 1
    assert await _year_runs(db, NEW_SELLER) == 0
    assert await _year_runs(db, PILOT) == 0
    old_questions = {
        f"/questions/{row['id']}"
        for row in gateway.questions[PILOT]
        if _parse(row["date_created"]) < now - timedelta(days=90)
    }
    assert not {path for seller_id, path in gateway.calls if seller_id == PILOT} & old_questions
    assert not any(
        "order.date_created.from" in path
        and _parse(parse_qs(urlsplit(path).query)["order.date_created.from"][0])
        < now - timedelta(days=91)
        for _, path in gateway.calls
    )

    # Turned back on, the queued portion runs.
    await _drain(_ranges_worker(db, gateway))
    assert (await db[JOBS].find_one({"_id": queued.key}))["state"] == "completed"
