"""DEVOLUCIONES covers the current UTC day up to an intraday cut (real Mongo).

Until 2026-10-12 the ordinary tail certified only closed UTC days, so every
range that ends today (``fecha_final`` = today) answered ``DATA_UNAVAILABLE``
all day. The refresh loop now acquires ``[today 00:00, cut)`` once per hourly
cut with the tail's executor, publishes it as an ordinary quota certificate,
and the daily tail replaces it with the full day in the same transaction.

The clock is simulated two days in the past. Every proof in the read range is
acquired at a simulated time, so the reader can be asked at those times; only
the seller's oldest window (its initial activation) carries wall-clock time.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
import pytest_asyncio

from zeler_platform_core.devoluciones_certificates import CERTIFICATES
from zeler_platform_core.devoluciones_readiness import (
    acquire_devoluciones_operation,
    finish_devoluciones_operation,
    new_devoluciones_attempt_token,
)

SELLER = "82453304"
RUNS = "sheets_devoluciones_runs"
# Two days back, so every simulated instant up to "tomorrow" is in the past.
TODAY = datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC) - timedelta(days=2)


@pytest_asyncio.fixture
async def intraday_db(default_mongo_uri: str) -> AsyncIterator[Any]:
    from motor.motor_asyncio import AsyncIOMotorClient

    client: Any = AsyncIOMotorClient(
        default_mongo_uri, tz_aware=True, serverSelectionTimeoutMS=1000
    )
    hello = await client.admin.command("hello")
    assert hello["isWritablePrimary"] is True
    name = "zeler_devoluciones_intraday_" + uuid4().hex
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


class Clock:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at


def _meli_time(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _parse_meli_time(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%f%z")


class DayGateway:
    """Mercado Libre for one seller: productive returns at fixed instants."""

    def __init__(self, returns: dict[str, tuple[datetime, int]]) -> None:
        # claim suffix -> (date_created, returned quantity)
        self.returns = returns
        self.calls: list[str] = []
        self.order_titles: dict[str, str] = {}

    def _resources(self, suffix: str) -> dict[str, Any]:
        created_at, quantity = self.returns[suffix]
        created = _meli_time(created_at)
        claim_id, order_id, item_id = f"55{suffix}", f"20{suffix}", f"MLM{suffix}"
        players = [
            {"user_id": int(SELLER), "role": "respondent", "type": "seller"},
            {"user_id": 90001, "role": "complainant", "type": "buyer"},
        ]
        order_updated = created
        title = self.order_titles.get(order_id, f"Title {suffix}")
        if order_id in self.order_titles:
            order_updated = _meli_time(created_at + timedelta(hours=1))
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
                        "return_quantity": f"{quantity}.0",
                        "total_quantity": quantity,
                    }
                ],
            },
            "order": {
                "id": int(order_id),
                "seller": {"id": int(SELLER)},
                "buyer": {"id": 90001},
                "status": "paid",
                "date_created": created,
                "last_updated": order_updated,
                "total_amount": 100 * quantity,
                "items": [
                    {
                        "item": {"id": item_id, "seller_sku": f"SKU-{suffix}", "title": title},
                        "quantity": quantity,
                        "unit_price": 100,
                    }
                ],
            },
        }

    def _suffix(self, identity: str, prefix: str) -> str:
        return identity.removeprefix(prefix)

    async def fetch_resource_once(self, *, seller_id: str, path: str, **_: Any) -> dict[str, Any]:
        assert seller_id == SELLER
        self.calls.append(path.split("?", 1)[0])
        if path.startswith("/post-purchase/v1/claims/search?"):
            query = parse_qs(urlsplit(path).query)
            start = _parse_meli_time(query["date_created"][0])
            end = _parse_meli_time(query["range"][0].rsplit("before:", 1)[1])
            rows = [
                self._resources(suffix)["row"]
                for suffix, (created, _) in sorted(self.returns.items(), key=lambda row: row[1])
                if start <= created < end
            ]
            return {"data": rows, "paging": {"offset": 0, "limit": 100, "total": len(rows)}}
        if path.startswith("/orders/"):
            return dict(self._resources(self._suffix(path.rsplit("/", 1)[1], "20"))["order"])
        if path.endswith("/returns"):
            claim_id = path.removesuffix("/returns").rsplit("/", 1)[1]
            return dict(self._resources(self._suffix(claim_id, "55"))["returns"])
        claim_id = path.rsplit("/", 1)[1]
        return dict(self._resources(self._suffix(claim_id, "55"))["claim"])

    async def fetch_resource(self, *, seller_id: str, path: str) -> dict[str, Any]:
        return await self.fetch_resource_once(seller_id=seller_id, path=path)


async def _link(db: Any) -> None:
    await db.meli_accounts.insert_one({"seller_id": SELLER, "status": "active"})
    await db.sheets_extension_tokens.insert_one(
        {
            "status": "active",
            "seller_scopes": [{"seller_id": SELLER, "nickname": "pilot"}],
            "expires_at": datetime.now(UTC) + timedelta(days=30),
        }
    )
    operation = await acquire_devoluciones_operation(
        db=db,
        seller_id=SELLER,
        scope="devoluciones",
        operation_id="bootstrap-claims",
        attempt_token=new_devoluciones_attempt_token(),
    )
    await finish_devoluciones_operation(db=db, operation=operation, succeeded=True)


async def _certified_through_yesterday(
    db: Any, monkeypatch: pytest.MonkeyPatch, clock: Clock
) -> None:
    """Certificate mode with full days certified up to TODAY 00:00.

    The initial window [TODAY-20, TODAY-10) is activated by the operator's
    migration logic, which stamps wall-clock time; the daily tail then
    certifies [TODAY-10, TODAY) at simulated time, which is what reads use.
    """
    from zeler_sheets import devoluciones_runner as runner
    from zeler_sheets.devoluciones_runner import (
        admit_initial_devoluciones_coverage,
        advance_due_devoluciones_run,
    )
    from zeler_sheets.formulas.seller_scope import EligibleSellerGate

    monkeypatch.setattr(runner, "INITIAL_COVERAGE_DAYS", 20)
    await _link(db)
    gate = EligibleSellerGate(db)

    async def admit_initial(db: Any, seller_id: str, *, now: Any = None) -> str | None:
        return await admit_initial_devoluciones_coverage(db, seller_id, eligible=gate, now=now)

    clock.at = TODAY + timedelta(hours=1, minutes=10)
    for _ in range(2):
        assert await advance_due_devoluciones_run(
            db,
            SELLER,
            history_work_enabled=False,
            admit_initial=admit_initial,
            renew=False,
            now=clock,
        )
        clock.at += timedelta(minutes=1)
    control = await db.sheets_devoluciones_operations.find_one({"seller_id": SELLER})
    assert control["coverage_mode"] == "active"
    latest = await db[CERTIFICATES].find_one({"seller_id": SELLER}, sort=[("date_to", -1)])
    assert latest["date_to"] == TODAY


async def _renew(db: Any, clock: Clock) -> None:
    """What every refresh cycle does for every seller before any source work."""
    from zeler_sheets.devoluciones_runner import renew_due_certificates

    summary = await renew_due_certificates(db, SELLER, now=clock)
    assert summary["reason"] in (None, "budget_exhausted")


async def _devoluciones(
    db: Any, clock: Callable[[], datetime], date_from: datetime, last_day: datetime
) -> Any:
    from zeler_sheets.formulas.dispatcher import FormulaExecutionContext
    from zeler_sheets.formulas.handlers_returns_histories_withdrawals import (
        ReturnsHistoriesWithdrawalsFormulaHandlers,
    )
    from zeler_sheets.formulas.read_models import FormulaReadModelRepository
    from zeler_sheets.formulas.registry import FormulaRegistry

    handlers = ReturnsHistoriesWithdrawalsFormulaHandlers(
        FormulaReadModelRepository(db=db), now_fn=clock
    )
    return await handlers.sheetseller_devoluciones(
        FormulaExecutionContext(
            contract=FormulaRegistry.default().find_required("ZELERDATA_DEVOLUCIONES"),
            cuenta="seller",
            seller_id=SELLER,
            seller_nickname="seller",
            token_id="token-1",  # noqa: S106 - a fake extension token id
            args={
                "fecha_inicio": date_from.date().isoformat(),
                "fecha_final": last_day.date().isoformat(),
            },
            request_id="req-1",
        )
    )


def _gateway(monkeypatch: pytest.MonkeyPatch) -> DayGateway:
    from infra.operations import zelerdata_read_model_reconcile as reconcile

    from zeler_sheets.devoluciones_reconciliation import ReturnsAttemptPacer

    # The 1.75 s spacing between return reads has its own tests.
    monkeypatch.setattr(ReturnsAttemptPacer, "INTERVAL", 0.0)
    gateway = DayGateway(
        {
            # Certified by yesterday's tail.
            "0001": (TODAY - timedelta(days=3, hours=-12), 2),
            # Today, before the 14:00 cut.
            "0002": (TODAY + timedelta(hours=9), 1),
            # Today, after the 14:00 cut and before 15:00.
            "0003": (TODAY + timedelta(hours=14, minutes=20), 3),
        }
    )
    monkeypatch.setattr(
        reconcile,
        "create_runtime_historical_meli_gateways",
        lambda: SimpleNamespace(order_detail_gateway=gateway),
    )
    return gateway


@pytest.mark.asyncio
async def test_a_range_ending_today_is_served_up_to_the_intraday_cut(
    intraday_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from zeler_sheets.formulas.dispatcher import FormulaDataUnavailableError

    db = intraday_db
    gateway = _gateway(monkeypatch)
    clock = Clock(TODAY)
    await _certified_through_yesterday(db, monkeypatch, clock)

    clock.at = TODAY + timedelta(hours=14, minutes=35)
    await _renew(db, clock)
    # Before: a range that ends today has no coverage for today.
    with pytest.raises(FormulaDataUnavailableError):
        await _devoluciones(db, clock, TODAY - timedelta(days=6), TODAY)

    from zeler_sheets.devoluciones_runner import (
        INTRADAY_AUTHORIZATION,
        advance_intraday_devoluciones,
    )

    gateway.calls.clear()
    assert await advance_intraday_devoluciones(db, SELLER, now=clock) is True
    run = await db[RUNS].find_one({"seller_id": SELLER, "authorization_id": INTRADAY_AUTHORIZATION})
    assert run["state"] == "completed"
    assert (run["start"], run["end"]) == (TODAY, TODAY + timedelta(hours=14))
    # One pass, counted: two inventory passes per snapshot, then claim, return
    # and order details for the one claim, all twice (snapshot + revalidation).
    assert sorted(gateway.calls) == sorted(
        2
        * [
            "/post-purchase/v1/claims/search",
            "/post-purchase/v1/claims/search",
            "/post-purchase/v1/claims/550002",
            "/post-purchase/v2/claims/550002/returns",
            "/orders/200002",
        ]
    )

    clock.at += timedelta(minutes=1)
    result = await _devoluciones(db, clock, TODAY - timedelta(days=6), TODAY)
    # The claim after the cut is not served; the one before it is.
    assert result.values == [
        ["MLM0001", "SKU-0001", 2, "Title 0001"],
        ["MLM0002", "SKU-0002", 1, "Title 0002"],
    ]
    assert result.meta["coverage"] == {
        "exact": True,
        "scope": "certified_until_cut",
        "date_from": (TODAY - timedelta(days=6)).isoformat(),
        "date_to": (TODAY + timedelta(days=1)).isoformat(),
        "covered_until": (TODAY + timedelta(hours=14)).isoformat(),
        "reason": "current_day_in_progress",
    }
    # A range ending today 00:00 is fully certified: no partial coverage.
    closed = await _devoluciones(db, clock, TODAY - timedelta(days=6), TODAY - timedelta(days=1))
    assert closed.values == [["MLM0001", "SKU-0001", 2, "Title 0001"]]
    assert "coverage" not in closed.meta
    # A range that ends after tomorrow 00:00 stays unavailable.
    with pytest.raises(FormulaDataUnavailableError):
        await _devoluciones(db, clock, TODAY - timedelta(days=6), TODAY + timedelta(days=1))

    # The same cut is acquired once: a later cycle in the same hour does nothing.
    gateway.calls.clear()
    clock.at = TODAY + timedelta(hours=15, minutes=20)
    assert await advance_intraday_devoluciones(db, SELLER, now=clock) is False
    assert gateway.calls == []

    # A cut older than the reader's limit is unavailable, even with valid proofs.
    clock.at = TODAY + timedelta(hours=17, minutes=5)
    await _renew(db, clock)
    with pytest.raises(FormulaDataUnavailableError):
        await _devoluciones(db, clock, TODAY - timedelta(days=6), TODAY)


async def _intraday_certificates(db: Any) -> list[dict[str, Any]]:
    from zeler_sheets.devoluciones_runner import INTRADAY_AUTHORIZATION

    runs = {
        run["_id"]
        async for run in db[RUNS].find(
            {"seller_id": SELLER, "authorization_id": INTRADAY_AUTHORIZATION}, {"_id": 1}
        )
    }
    return [
        row
        async for row in db[CERTIFICATES]
        .find({"seller_id": SELLER, "source_identity": {"$in": list(runs)}})
        .sort("date_to", 1)
    ]


@pytest.mark.asyncio
async def test_the_daily_tail_replaces_the_intraday_cut_without_a_gap(
    intraday_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from zeler_sheets.devoluciones_runner import (
        ORDINARY_TAIL_AUTHORIZATION,
        advance_due_devoluciones_run,
        advance_intraday_devoluciones,
    )

    db = intraday_db
    _gateway(monkeypatch)
    clock = Clock(TODAY)
    await _certified_through_yesterday(db, monkeypatch, clock)
    tomorrow = TODAY + timedelta(days=1)

    # Two cuts of today: the later one replaces the earlier one.
    for at in (timedelta(hours=14, minutes=35), timedelta(hours=23, minutes=35)):
        clock.at = TODAY + at
        await _renew(db, clock)
        assert await advance_intraday_devoluciones(db, SELLER, now=clock) is True
    cuts = await _intraday_certificates(db)
    assert [(row["date_from"], row["date_to"]) for row in cuts] == [
        (TODAY, TODAY + timedelta(hours=23))
    ]

    # After midnight, before the tail: the last cut of the day still serves it.
    clock.at = tomorrow + timedelta(minutes=40)
    await _renew(db, clock)
    assert await advance_intraday_devoluciones(db, SELLER, now=clock) is False
    partial = await _devoluciones(db, clock, TODAY - timedelta(days=6), TODAY)
    assert partial.meta["coverage"]["covered_until"] == (TODAY + timedelta(hours=23)).isoformat()
    assert [row[0] for row in partial.values] == ["MLM0003", "MLM0001", "MLM0002"]

    # The tail closes today and removes the cut in the same transaction.
    clock.at = tomorrow + timedelta(hours=1, minutes=10)
    await _renew(db, clock)
    assert await advance_due_devoluciones_run(
        db, SELLER, history_work_enabled=False, renew=False, now=clock
    )
    tail = await db[RUNS].find_one(
        {"seller_id": SELLER, "authorization_id": ORDINARY_TAIL_AUTHORIZATION},
        sort=[("created_at", -1)],
    )
    assert (tail["start"], tail["end"], tail["state"]) == (TODAY, tomorrow, "completed")
    assert await _intraday_certificates(db) == []
    clock.at += timedelta(minutes=1)
    closed = await _devoluciones(db, clock, TODAY - timedelta(days=6), TODAY)
    assert "coverage" not in closed.meta
    assert closed.values == partial.values

    # The next day's first cut starts exactly where the tail ended.
    clock.at = tomorrow + timedelta(hours=1, minutes=40)
    await _renew(db, clock)
    assert await advance_intraday_devoluciones(db, SELLER, now=clock) is True
    cuts = await _intraday_certificates(db)
    assert [(row["date_from"], row["date_to"]) for row in cuts] == [
        (tomorrow, tomorrow + timedelta(hours=1))
    ]
    clock.at += timedelta(minutes=1)
    current = await _devoluciones(db, clock, TODAY - timedelta(days=6), tomorrow)
    assert current.meta["coverage"]["covered_until"] == (tomorrow + timedelta(hours=1)).isoformat()
    assert current.values == closed.values


@pytest.mark.asyncio
async def test_an_order_mutation_of_today_invalidates_the_cut_until_the_next_pass(
    intraday_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from zeler_sheets.devoluciones_runner import advance_intraday_devoluciones
    from zeler_sheets.event_persistence import SheetsEventPersistence
    from zeler_sheets.formulas.dispatcher import FormulaDataUnavailableError

    db = intraday_db
    gateway = _gateway(monkeypatch)
    clock = Clock(TODAY)
    await _certified_through_yesterday(db, monkeypatch, clock)
    clock.at = TODAY + timedelta(hours=14, minutes=35)
    await _renew(db, clock)
    assert await advance_intraday_devoluciones(db, SELLER, now=clock) is True
    (cut,) = await _intraday_certificates(db)
    assert cut["state"] == "reconciled"

    # Mercado Libre changes today's returned order; an unproven write reaches it.
    gateway.order_titles["200002"] = "Renamed"
    order = gateway._resources("0002")["order"]
    operation = await acquire_devoluciones_operation(
        db=db,
        seller_id=SELLER,
        scope="devoluciones",
        operation_id="order-event",
        attempt_token=new_devoluciones_attempt_token(),
        invalidate_readiness=False,
    )
    await SheetsEventPersistence(db=db).persist(
        event_type="orders.updated", seller_id=SELLER, resource=order, operation=operation
    )
    await finish_devoluciones_operation(db=db, operation=operation, succeeded=True)
    (cut,) = await _intraday_certificates(db)
    assert (cut["state"], cut["needs_reacquisition"], cut["invalidation_reason"]) == (
        "stale",
        True,
        "order_mutation",
    )
    clock.at += timedelta(minutes=5)
    await _renew(db, clock)
    with pytest.raises(FormulaDataUnavailableError):
        await _devoluciones(db, clock, TODAY - timedelta(days=6), TODAY)

    # The next cut re-acquires the day and replaces the stale proof.
    clock.at = TODAY + timedelta(hours=15, minutes=35)
    await _renew(db, clock)
    assert await advance_intraday_devoluciones(db, SELLER, now=clock) is True
    (cut,) = await _intraday_certificates(db)
    assert (cut["date_to"], cut["state"]) == (TODAY + timedelta(hours=15), "reconciled")
    clock.at += timedelta(minutes=1)
    result = await _devoluciones(db, clock, TODAY - timedelta(days=6), TODAY)
    assert result.values == [
        ["MLM0003", "SKU-0003", 3, "Title 0003"],
        ["MLM0001", "SKU-0001", 2, "Title 0001"],
        ["MLM0002", "SKU-0002", 1, "Renamed"],
    ]
    assert result.meta["coverage"]["covered_until"] == (TODAY + timedelta(hours=15)).isoformat()


@pytest.mark.asyncio
async def test_two_workers_and_a_restart_acquire_each_cut_once(
    intraday_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    from zeler_sheets.devoluciones_runner import (
        INTRADAY_AUTHORIZATION,
        advance_intraday_devoluciones,
    )

    db = intraday_db
    gateway = _gateway(monkeypatch)
    clock = Clock(TODAY)
    await _certified_through_yesterday(db, monkeypatch, clock)

    async def worker() -> str:
        try:
            return str(await advance_intraday_devoluciones(db, SELLER, now=clock))
        except Exception as exc:  # noqa: BLE001 - the refresh cycle logs and moves on
            return type(exc).__name__

    for at in (timedelta(hours=14, minutes=35), timedelta(hours=15, minutes=35)):
        clock.at = TODAY + at
        await asyncio.gather(worker(), worker())
        # A restarted worker in the same hour finds the cut done.
        gateway.calls.clear()
        assert await advance_intraday_devoluciones(db, SELLER, now=clock) is False
        assert gateway.calls == []

    runs = [
        run
        async for run in db[RUNS]
        .find({"seller_id": SELLER, "authorization_id": INTRADAY_AUTHORIZATION})
        .sort("end", 1)
    ]
    assert [(run["end"], run["state"]) for run in runs] == [
        (TODAY + timedelta(hours=14), "completed"),
        (TODAY + timedelta(hours=15), "completed"),
    ]
    for run in runs:
        assert await db.sheets_devoluciones_run_windows.count_documents({"run_id": run["_id"]}) == 1
    cuts = await _intraday_certificates(db)
    assert [row["source_identity"] for row in cuts] == [runs[-1]["_id"]]
    today = {"seller_id": SELLER, "date_created": {"$gte": TODAY}}
    assert await db.claims.count_documents(today) == 2
