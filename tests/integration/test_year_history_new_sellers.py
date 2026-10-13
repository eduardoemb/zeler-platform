"""A newly linked ZelerData seller gets twelve months of history on its own (real Mongo).

Until 2026-10-12 a new seller in `all` mode had only what its bootstrap
acquired at link time plus what refresh added from then on: ranges older than
about 90 days stayed ``DATA_UNAVAILABLE`` for orders, questions and
DEVOLUCIONES. The refresh loop now walks each source backwards, one portion per
cycle for the whole fleet, until the proven coverage reaches a full year.

The pilot keeps its paused history plan and must not change: no year-history
job, no year-history DEVOLUCIONES run.
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


async def _paused_pilot(db: Any, gateway: YearGateway, now: datetime) -> None:
    """The pilot: certificate mode from its paused history plan, 30 days of orders and questions."""
    from zeler_sheets.devoluciones_runner import advance_onboarding_devoluciones

    settled = datetime.combine((now - timedelta(hours=1)).date(), time.min, tzinfo=UTC)
    start = settled - timedelta(days=12)
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
    for read_model in ("orders", "questions"):
        await db[FRESHNESS].insert_one(
            {
                "_id": f"{PILOT}:{read_model}",
                "seller_id": PILOT,
                "read_model": read_model,
                "state": "reconciled",
                "date_from": now - timedelta(days=30),
                "reconciled_until": now - timedelta(hours=2),
                "fresh_until": now - timedelta(hours=2),
                "updated_at": now - timedelta(hours=2),
                "valid_until": now - timedelta(hours=1),
                "source": "zelerdata_read_model_reconcile",
                "schema_version": 1,
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
async def test_a_new_seller_gets_twelve_months_and_the_pilot_does_not_change(
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
    for _ in range(90):
        before = len(await _year_jobs(db, NEW_SELLER))
        runs_before = await db[RUNS].count_documents({})
        await supervisor.run_cycle()
        admitted_per_cycle.append(len(await _year_jobs(db, NEW_SELLER)) - before)
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

    # The pilot: no year-history work. Its only order requests are the
    # ordinary sweeps (at most the weekly 90 days), and its proofs reach no
    # further back than those sweeps.
    assert await _year_jobs(db, PILOT) == []
    assert await _year_runs(db, PILOT) == 0
    ordinary_reach = now - timedelta(days=91)
    assert not any(
        "order.date_created.from" in path
        and _parse(parse_qs(urlsplit(path).query)["order.date_created.from"][0]) < ordinary_reach
        for seller_id, path in gateway.calls
        if seller_id == PILOT
    )
    for read_model, before_marker in pilot_markers.items():
        after = await db[FRESHNESS].find_one({"_id": f"{PILOT}:{read_model}"})
        starts = [
            after["date_from"],
            *(row["date_from"] for row in after.get("retained_intervals", [])),
        ]
        assert min(starts) >= min(before_marker["date_from"], ordinary_reach)


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
async def test_switched_off_acquires_nothing_new(
    year_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from zeler_sheets.consumer import build_zelerdata_refresh_supervisor
    from zeler_sheets.formulas.recovery import FormulaRecoveryQueue, YearHistoryRecoveryRequest

    db = year_db
    now = datetime.now(UTC)
    gateway = YearGateway(now=now, sellers=(NEW_SELLER,), first=now - timedelta(days=400))
    await _link(db, NEW_SELLER)
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
    assert not any(
        "order.date_created.from" in path
        and _parse(parse_qs(urlsplit(path).query)["order.date_created.from"][0])
        < now - timedelta(days=91)
        for _, path in gateway.calls
    )

    # Turned back on, the queued portion runs.
    await _drain(_ranges_worker(db, gateway))
    assert (await db[JOBS].find_one({"_id": queued.key}))["state"] == "completed"
