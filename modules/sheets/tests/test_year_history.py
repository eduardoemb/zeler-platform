"""Twelve months of history: planner, worker and loop rules (real Mongo where it matters)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ServerSelectionTimeoutError
from structlog.testing import capture_logs

from zeler_sheets.formulas.recovery import (
    FormulaRecoveryQueue,
    RecoveryRequest,
    RenewalRecoveryRequest,
    YearHistoryRecoveryRequest,
)
from zeler_sheets.formulas.year_history import (
    MAX_PORTION,
    MIN_PORTION,
    RETRY_AT_MINIMUM,
    YearHistoryPlanner,
    proven_edge,
    year_history_target,
)

SELLER = "90000001"
OTHER = "90000002"
NOW = datetime(2026, 10, 12, 14, 7, tzinfo=UTC)
JOBS = "sheets_formula_recovery_jobs"
FRESHNESS = "sheets_read_model_freshness"


@pytest_asyncio.fixture
async def year_db() -> AsyncIterator[Any]:
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        "mongodb://127.0.0.1:27028/?directConnection=true",
        serverSelectionTimeoutMS=1000,
        tz_aware=True,
    )
    db = client[f"zeler_year_history_unit_{uuid4().hex}"]
    connected = False
    try:
        try:
            await client.admin.command("ping")
            connected = True
        except ServerSelectionTimeoutError:
            pytest.skip("dedicated local Mongo on port 27028 is unavailable")
        yield db
    finally:
        if connected:
            await client.drop_database(db.name)
        client.close()


def _marker(
    start: datetime, end: datetime, *, retained: tuple[tuple[datetime, datetime], ...] = ()
) -> dict[str, Any]:
    return {
        "state": "reconciled",
        "date_from": start,
        "reconciled_until": end,
        "valid_until": end + timedelta(minutes=30),
        "retained_intervals": [
            {
                "state": "reconciled",
                "date_from": left,
                "reconciled_until": right,
                "valid_until": right,
            }
            for left, right in retained
        ],
    }


def test_the_target_is_a_full_year_back_from_utc_midnight() -> None:
    assert year_history_target(NOW) == datetime(2025, 10, 11, tzinfo=UTC)
    # Leap years keep a full calendar year: 2028-02-29 is inside.
    assert year_history_target(datetime(2029, 2, 28, 23, tzinfo=UTC)) <= datetime(
        2028, 2, 28, tzinfo=UTC
    )


def test_the_edge_is_where_the_most_recent_proven_block_starts() -> None:
    live = NOW - timedelta(hours=1)
    # The live interval touches a retained week; an older month is apart.
    marker = _marker(
        live,
        NOW,
        retained=(
            (NOW - timedelta(days=7), live),
            (NOW - timedelta(days=90), NOW - timedelta(days=60)),
        ),
    )
    assert proven_edge(marker) == NOW - timedelta(days=7)
    # A formula range acquired for an old interval is the marker's own
    # interval for a moment; the edge stays at the recent block.
    old = _marker(
        NOW - timedelta(days=200),
        NOW - timedelta(days=190),
        retained=((NOW - timedelta(days=7), NOW),),
    )
    assert proven_edge(old) == NOW - timedelta(days=7)
    assert proven_edge({**marker, "state": "stale"}) is None
    assert proven_edge(None) is None


async def _seed_marker(db: Any, seller_id: str, read_model: str, start: datetime) -> None:
    await db[FRESHNESS].insert_one(
        {
            "_id": f"{seller_id}:{read_model}",
            "seller_id": seller_id,
            "read_model": read_model,
            "state": "reconciled",
            "date_from": start,
            "reconciled_until": NOW,
            "fresh_until": NOW,
            "updated_at": NOW,
            "valid_until": NOW + timedelta(minutes=30),
            "schema_version": 1,
        }
    )


def _planner(
    db: Any, *, now: datetime = NOW, eligible: bool = True, **options: Any
) -> YearHistoryPlanner:
    async def gate(seller_id: str) -> bool:
        return eligible

    return YearHistoryPlanner(
        db=db,
        queue=FormulaRecoveryQueue(db, now=lambda: now),
        eligible=gate,
        now=lambda: now,
        **options,
    )


async def _year_jobs(db: Any) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = (
        await db[JOBS].find({"year_history": True}).sort("created_at", 1).to_list(None)
    )
    return jobs


@pytest.mark.asyncio
async def test_a_portion_ends_on_the_hour_at_the_edge_and_holds_about_120_orders(
    year_db: Any,
) -> None:
    edge = NOW - timedelta(days=7, minutes=17)
    await _seed_marker(year_db, SELLER, "orders", edge)
    # The pilot's density: 18 orders a day (one every 80 minutes).
    first = NOW - timedelta(days=60)
    await year_db.orders.insert_many(
        [
            {
                "_id": str(index),
                "seller_id": SELLER,
                "date_created": first + timedelta(minutes=80 * index),
            }
            for index in range(60 * 18)
        ]
    )
    assert await _planner(year_db, models=("orders",)).plan((SELLER,))

    (job,) = await _year_jobs(year_db)
    end = edge.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    assert job["date_to"] == end
    span = job["date_to"] - job["date_from"]
    assert timedelta(days=6) <= span <= timedelta(days=7)
    assert span % timedelta(hours=1) == timedelta(0)
    # A portion is an ordinary range job in the ranges lane.
    assert job["state"] == "pending" and "order_ids" not in job


@pytest.mark.asyncio
async def test_without_local_rows_a_portion_takes_the_longest_span(year_db: Any) -> None:
    await _seed_marker(year_db, SELLER, "questions", NOW - timedelta(days=7))
    assert await _planner(year_db, models=("questions",)).plan((SELLER,))
    (job,) = await _year_jobs(year_db)
    assert job["date_to"] - job["date_from"] == MAX_PORTION["questions"]


@pytest.mark.asyncio
async def test_nothing_is_planned_while_a_renewal_or_a_ready_portion_is_in_flight(
    year_db: Any,
) -> None:
    for seller_id in (SELLER, OTHER):
        await _seed_marker(year_db, seller_id, "orders", NOW - timedelta(days=7))
    queue = FormulaRecoveryQueue(year_db, now=lambda: NOW)
    renewal = RenewalRecoveryRequest(OTHER, "catalog_buybox_snapshots", ("MLM1",), NOW)
    await queue.enqueue(renewal)
    planner = _planner(year_db, models=("orders",))
    assert not await planner.plan((SELLER, OTHER))
    await year_db[JOBS].update_one({"_id": renewal.key}, {"$set": {"state": "completed"}})

    assert await planner.plan((SELLER, OTHER))
    # One portion at a time for the fleet.
    assert not await planner.plan((SELLER, OTHER))
    (first,) = await _year_jobs(year_db)
    assert first["seller_id"] == SELLER
    # A portion waiting out a retry backoff holds no one else.
    await year_db[JOBS].update_one(
        {"_id": first["_id"]},
        {"$set": {"attempts": 1, "available_at": NOW + timedelta(seconds=30)}},
    )
    assert await planner.plan((SELLER, OTHER))
    assert [job["seller_id"] for job in await _year_jobs(year_db)] == [SELLER, OTHER]


@pytest.mark.asyncio
async def test_a_legacy_plan_seller_walks_only_the_sources_short_of_a_year(year_db: Any) -> None:
    """The paused pilot (decision of 2026-10-13): judged per source, its plan left alone."""
    target = year_history_target(NOW)
    # Like production: orders already proven past the target, questions from July.
    await _seed_marker(year_db, SELLER, "orders", target - timedelta(days=18))
    await _seed_marker(year_db, SELLER, "questions", NOW - timedelta(days=90))
    plan = {"_id": SELLER, "seller_id": SELLER, "state": "paused", "flags": {"history": False}}
    await year_db.sheets_history_backfill_plans.insert_one(plan)
    planner = _planner(year_db)
    with capture_logs() as logs:
        assert await planner.plan((SELLER,))
        # One portion per cycle; the next cycle asks nothing while it is pending.
        assert not await planner.plan((SELLER,))

    (job,) = await _year_jobs(year_db)
    assert job["read_model"] == "questions"
    assert job["date_to"] == NOW - timedelta(days=90) + timedelta(minutes=53)
    events = [log["event"] for log in logs]
    assert "zelerdata.year_history_excluded" not in events
    assert events.count("zelerdata.year_history_covered") == 1
    # The legacy plan is neither edited nor resumed.
    assert await year_db.sheets_history_backfill_plans.find_one({"_id": SELLER}) == plan


@pytest.mark.asyncio
async def test_a_gap_under_the_live_block_is_filled_without_rereading_older_proofs(
    year_db: Any,
) -> None:
    """The pilot's old proofs stop just short of a fresh sweep: read only the gap."""
    target = year_history_target(NOW)
    older_end = NOW - timedelta(hours=2, minutes=20)
    await year_db[FRESHNESS].insert_one(
        {
            "_id": f"{SELLER}:orders",
            "seller_id": SELLER,
            "read_model": "orders",
            **_marker(
                NOW - timedelta(hours=1, minutes=10),
                NOW,
                retained=((target - timedelta(days=18), older_end),),
            ),
            "schema_version": 1,
        }
    )
    assert await _planner(year_db, models=("orders",)).plan((SELLER,))
    (job,) = await _year_jobs(year_db)
    # From the hour of the older proof's end to the hour after the live edge.
    assert job["date_from"] == older_end.replace(minute=0)
    assert job["date_to"] == (NOW - timedelta(hours=1)).replace(minute=0)


@pytest.mark.asyncio
async def test_an_ineligible_seller_or_no_marker_get_nothing(year_db: Any) -> None:
    await _seed_marker(year_db, OTHER, "orders", NOW - timedelta(days=30))
    assert not await _planner(year_db, models=("orders",), eligible=False).plan((OTHER,))
    # Without a marker the sweeps establish coverage first.
    assert not await _planner(year_db, models=("questions",)).plan((OTHER,))
    assert await _year_jobs(year_db) == []


@pytest.mark.asyncio
async def test_a_covered_seller_is_not_requested_again(year_db: Any) -> None:
    await _seed_marker(year_db, SELLER, "orders", year_history_target(NOW) - timedelta(hours=1))
    with capture_logs() as logs:
        planner = _planner(year_db, models=("orders",))
        assert not await planner.plan((SELLER,))
        assert not await planner.plan((SELLER,))
    assert [log["event"] for log in logs] == ["zelerdata.year_history_covered"]


async def _fail(db: Any, reason: str, *, updated: datetime = NOW) -> dict[str, Any]:
    (job,) = [job for job in await _year_jobs(db) if job["state"] == "pending"]
    await db[JOBS].update_one(
        {"_id": job["_id"]},
        {
            "$set": {
                "state": "failed",
                "failure_reason": reason,
                "updated_at": updated,
                "available_at": updated + timedelta(minutes=15),
            }
        },
    )
    return job


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason",
    [
        "source_temporarily_unavailable",
        # Production, 2026-10-13: the pilot's last question portion failed this
        # way 53 times, reopened whole after every cooldown and never halved.
        "source_incomplete",
        "attempts_exhausted",
        "storage_unavailable",
        "recovery_failed",
    ],
)
async def test_a_failed_portion_is_retried_at_half_its_span(year_db: Any, reason: str) -> None:
    """A portion fails only after its three attempts; whatever the reason, the next is halved."""
    await _seed_marker(year_db, SELLER, "orders", NOW - timedelta(days=7))
    assert await _planner(year_db, models=("orders",)).plan((SELLER,))
    failed = await _fail(year_db, reason)

    # Not before its cooldown.
    assert not await _planner(year_db, models=("orders",)).plan((SELLER,))
    later = NOW + timedelta(minutes=20)
    assert await _planner(year_db, models=("orders",), now=later).plan((SELLER,))
    retry = (await _year_jobs(year_db))[-1]
    assert retry["date_to"] == failed["date_to"]
    assert retry["date_to"] - retry["date_from"] == (failed["date_to"] - failed["date_from"]) / 2


@pytest.mark.asyncio
async def test_once_the_newer_half_is_proven_only_the_rest_of_the_failed_portion_is_tried(
    year_db: Any,
) -> None:
    """What the source refused lies in the rest: a whole span would fail again."""
    await _seed_marker(year_db, SELLER, "orders", NOW - timedelta(days=7))
    assert await _planner(year_db, models=("orders",)).plan((SELLER,))
    failed = await _fail(year_db, "source_incomplete")
    later = NOW + timedelta(minutes=20)
    assert await _planner(year_db, models=("orders",), now=later).plan((SELLER,))
    half = (await _year_jobs(year_db))[-1]
    # As the worker does: the newer half is proven and moves the edge.
    await year_db[JOBS].update_one({"_id": half["_id"]}, {"$set": {"state": "completed"}})
    await year_db[FRESHNESS].update_one(
        {"_id": f"{SELLER}:orders"}, {"$set": {"date_from": half["date_from"]}}
    )
    assert await _planner(year_db, models=("orders",), now=later).plan((SELLER,))
    rest = (await _year_jobs(year_db))[-1]
    assert (rest["date_from"], rest["date_to"]) == (failed["date_from"], half["date_from"])


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["source_temporarily_unavailable", "source_incomplete"])
async def test_a_minimal_portion_that_keeps_failing_waits_hours(year_db: Any, reason: str) -> None:
    edge = (NOW - timedelta(days=7)).replace(minute=0)
    await _seed_marker(year_db, SELLER, "orders", edge)
    request = YearHistoryRecoveryRequest(SELLER, "orders", edge - MIN_PORTION, edge)
    await FormulaRecoveryQueue(year_db, now=lambda: NOW).enqueue(request)
    await _fail(year_db, reason)

    assert not await _planner(year_db, models=("orders",), now=NOW + timedelta(hours=1)).plan(
        (SELLER,)
    )
    assert await _planner(year_db, models=("orders",), now=NOW + RETRY_AT_MINIMUM).plan((SELLER,))
    jobs = await _year_jobs(year_db)
    assert len(jobs) == 1 and jobs[0]["state"] == "pending"


@pytest.mark.asyncio
async def test_a_portion_closed_for_an_ineligible_seller_is_retried_whole(
    year_db: Any,
) -> None:
    """Closing it at claim says nothing about the portion: it is reopened whole."""
    await _seed_marker(year_db, SELLER, "orders", NOW - timedelta(days=7))
    assert await _planner(year_db, models=("orders",)).plan((SELLER,))
    failed = await _fail(year_db, "seller_not_eligible")
    assert await _planner(year_db, models=("orders",), now=NOW + timedelta(minutes=16)).plan(
        (SELLER,)
    )
    jobs = await _year_jobs(year_db)
    # The same portion is reopened, not a smaller one.
    assert len(jobs) == 1 and jobs[0]["_id"] == failed["_id"] and jobs[0]["state"] == "pending"


@pytest.mark.asyncio
async def test_sellers_and_sources_take_turns(year_db: Any) -> None:
    for seller_id in (SELLER, OTHER):
        for read_model in ("orders", "questions"):
            await _seed_marker(year_db, seller_id, read_model, NOW - timedelta(days=7))
    planner = _planner(year_db)
    served = []
    for _ in range(5):
        assert await planner.plan((SELLER, OTHER))
        job = (await _year_jobs(year_db))[-1]
        served.append((job["seller_id"], job["read_model"]))
        # As the worker does: complete it and move the proven edge back.
        await year_db[JOBS].update_one({"_id": job["_id"]}, {"$set": {"state": "completed"}})
        await year_db[FRESHNESS].update_one(
            {"_id": f"{job['seller_id']}:{job['read_model']}"},
            {"$set": {"date_from": job["date_from"]}},
        )
    assert served == [
        (SELLER, "orders"),
        (SELLER, "questions"),
        (OTHER, "orders"),
        (OTHER, "questions"),
        (SELLER, "orders"),
    ]


@pytest.mark.asyncio
async def test_switched_off_the_queue_leaves_queued_portions_unclaimed(year_db: Any) -> None:
    request = YearHistoryRecoveryRequest(
        SELLER, "orders", NOW - timedelta(days=30), NOW - timedelta(days=7)
    )
    await FormulaRecoveryQueue(year_db, now=lambda: NOW).enqueue(request)
    await FormulaRecoveryQueue(year_db, now=lambda: NOW).enqueue(
        RecoveryRequest(SELLER, "orders", NOW - timedelta(hours=1), NOW)
    )
    off = FormulaRecoveryQueue(year_db, now=lambda: NOW, year_history_enabled=False)
    claimed = await off.claim(lane="ranges")
    assert claimed is not None and "year_history" not in claimed
    assert await off.claim(lane="ranges") is None
    on = FormulaRecoveryQueue(year_db, now=lambda: NOW)
    assert (await on.claim(lane="ranges"))["_id"] == request.key  # type: ignore[index]


@pytest.mark.asyncio
async def test_a_year_portion_out_of_time_uses_an_attempt_instead_of_waiting_forever(
    year_db: Any,
) -> None:
    from zeler_sheets.formulas.pacing import LocalQuotaTimeoutError
    from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker

    class Gateway:
        async def fetch_resource(self, **_: Any) -> dict[str, Any]:
            raise LocalQuotaTimeoutError

    queue = FormulaRecoveryQueue(year_db, now=lambda: NOW)
    year = YearHistoryRecoveryRequest(
        SELLER, "orders", NOW - timedelta(days=30), NOW - timedelta(days=7)
    )
    ordinary = RecoveryRequest(OTHER, "orders", NOW - timedelta(hours=1), NOW)
    for request in (year, ordinary):
        await queue.enqueue(request)
    worker = FormulaRecoveryWorker(db=year_db, queue=queue, gateway=Gateway(), lane="ranges")
    assert await worker.process_one()
    assert await worker.process_one()

    year_job = await year_db[JOBS].find_one({"_id": year.key})
    ordinary_job = await year_db[JOBS].find_one({"_id": ordinary.key})
    assert year_job["attempts"] == 1 and year_job["state"] == "pending"
    assert year_job["failure_reason"] == "source_temporarily_unavailable"
    # Ordinary work keeps the deferral that costs no attempt.
    assert ordinary_job["attempts"] == 0 and ordinary_job["state"] == "pending"


QUESTION = {
    "id": 77,
    "seller_id": SELLER,
    "item_id": "MLM1",
    "text": "Disponible?",
    "status": "UNANSWERED",
    "from": {"id": 4242},
}


class _QuestionGateway:
    def __init__(self, created: list[datetime]) -> None:
        self.rows = [
            {**QUESTION, "id": 70 + index, "date_created": value.strftime("%Y-%m-%dT%H:%M:%S.000Z")}
            for index, value in enumerate(created)
        ]
        self.details: list[int] = []

    async def fetch_resource(self, *, seller_id: str, path: str) -> dict[str, Any]:
        if path.startswith("/questions/search?"):
            return {"total": len(self.rows), "questions": self.rows}
        identity = int(path.rsplit("/", 1)[-1])
        self.details.append(identity)
        return next(row for row in self.rows if row["id"] == identity)


@pytest.mark.asyncio
async def test_a_year_portion_is_retained_and_the_live_union_never_rereads_it(
    year_db: Any,
) -> None:
    from zeler_sheets.formulas.read_models import read_model_reconciliation_marker_covers
    from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker

    live_start = NOW - timedelta(days=7)
    await _seed_marker(year_db, SELLER, "questions", live_start)
    old, recent = NOW - timedelta(days=60), NOW - timedelta(hours=2)
    gateway = _QuestionGateway([old, recent])
    queue = FormulaRecoveryQueue(year_db, now=lambda: NOW)
    worker = FormulaRecoveryWorker(db=year_db, queue=queue, gateway=gateway, lane="ranges")
    portion = YearHistoryRecoveryRequest(SELLER, "questions", NOW - timedelta(days=97), live_start)
    await queue.enqueue(portion)
    assert await worker.process_one()

    marker = await year_db[FRESHNESS].find_one({"_id": f"{SELLER}:questions"})
    # The live claim is the sweeps'; the portion is an older retained proof.
    assert (marker["date_from"], marker["reconciled_until"]) == (live_start, NOW)
    assert [
        (row["date_from"], row["reconciled_until"]) for row in marker["retained_intervals"]
    ] == [(portion.date_from, live_start)]
    assert gateway.details == [70]

    # The next ordinary sweep rereads only its live union and keeps the portion.
    gateway.details.clear()
    await queue.enqueue(RecoveryRequest(SELLER, "questions", NOW - timedelta(hours=1), NOW))
    assert await worker.process_one()
    assert gateway.details == [71]
    marker = await year_db[FRESHNESS].find_one({"_id": f"{SELLER}:questions"})
    assert read_model_reconciliation_marker_covers(
        marker, date_from=portion.date_from, date_to=NOW, now=NOW
    )
    assert proven_edge(marker) == portion.date_from


@pytest.mark.asyncio
async def test_an_ordinary_question_sweep_without_retained_proofs_is_unchanged(
    year_db: Any,
) -> None:
    from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker

    await _seed_marker(year_db, SELLER, "questions", NOW - timedelta(days=7))
    gateway = _QuestionGateway([NOW - timedelta(days=3)])
    queue = FormulaRecoveryQueue(year_db, now=lambda: NOW)
    await queue.enqueue(RecoveryRequest(SELLER, "questions", NOW - timedelta(hours=1), NOW))
    worker = FormulaRecoveryWorker(db=year_db, queue=queue, gateway=gateway, lane="ranges")
    assert await worker.process_one()
    marker = await year_db[FRESHNESS].find_one({"_id": f"{SELLER}:questions"})
    # The union is reread as before, and no retained list appears.
    assert gateway.details == [70]
    assert marker["date_from"] == NOW - timedelta(days=7)
    assert "retained_intervals" not in marker


@pytest.mark.asyncio
async def test_a_year_portion_the_source_cannot_complete_uses_its_three_attempts(
    year_db: Any,
) -> None:
    """``source_incomplete`` used to fail a portion at its first attempt.

    The planner then reopened it with its attempts back at zero, so it never
    reached the halving. A year portion now uses its attempts like a 429, and
    the worker names the check that refused it, without identities or text.
    """
    from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker

    clock = {"now": NOW}
    live_start = NOW - timedelta(days=7)
    await _seed_marker(year_db, SELLER, "questions", live_start)
    marker = await year_db[FRESHNESS].find_one({"_id": f"{SELLER}:questions"})
    gateway = _QuestionGateway([NOW - timedelta(days=60)])
    # Answered, but the source no longer returns the answer.
    gateway.rows[0]["status"] = "ANSWERED"
    queue = FormulaRecoveryQueue(year_db, now=lambda: clock["now"])
    worker = FormulaRecoveryWorker(db=year_db, queue=queue, gateway=gateway, lane="ranges")
    portion = YearHistoryRecoveryRequest(SELLER, "questions", NOW - timedelta(days=97), live_start)
    await queue.enqueue(portion)

    with capture_logs() as logs:
        for attempt, backoff in ((1, 30), (2, 60), (3, None)):
            assert await worker.process_one()
            job = await year_db[JOBS].find_one({"_id": portion.key})
            assert (job["attempts"], job["failure_reason"]) == (attempt, "source_incomplete")
            if backoff is None:
                assert job["state"] == "failed"
            else:
                assert job["state"] == "pending"
                assert job["available_at"] == clock["now"] + timedelta(seconds=backoff)
                clock["now"] = job["available_at"]
    incomplete = [
        log for log in logs if log["event"] == "zelerdata.year_history_portion_incomplete"
    ]
    assert [log["attempt"] for log in incomplete] == [1, 2, 3]
    assert {log["check"] for log in incomplete} == {"recovery_worker._questions"}
    assert all(isinstance(log["line"], int) for log in incomplete)
    assert set(incomplete[0]) == {
        "event",
        "log_level",
        "seller_id",
        "read_model",
        "date_from",
        "date_to",
        "attempt",
        "check",
        "line",
    }
    # Nothing was published.
    assert await year_db[FRESHNESS].find_one({"_id": f"{SELLER}:questions"}) == marker

    # Ordinary range work keeps failing closed at once, as before.
    ordinary = RecoveryRequest(SELLER, "questions", NOW - timedelta(days=97), live_start)
    await queue.enqueue(ordinary)
    assert await worker.process_one()
    job = await year_db[JOBS].find_one({"_id": ordinary.key})
    assert (job["state"], job["attempts"]) == ("failed", 1)


@pytest.mark.asyncio
async def test_status_reports_each_source_without_identities(year_db: Any) -> None:
    from zeler_sheets.formulas.year_history import year_history_status

    target = year_history_target(NOW)
    await _seed_marker(year_db, SELLER, "orders", target - timedelta(days=1))
    await _seed_marker(year_db, SELLER, "questions", NOW - timedelta(days=7))
    await year_db.sheets_devoluciones_operations.insert_one(
        {
            "seller_id": SELLER,
            "scope": "devoluciones",
            "coverage_mode": "active",
            "coverage_epoch": 2,
        }
    )
    await year_db.sheets_devoluciones_certificates.insert_one(
        {"seller_id": SELLER, "coverage_epoch": 2, "date_from": NOW - timedelta(days=90)}
    )
    request = YearHistoryRecoveryRequest(
        SELLER, "questions", NOW - timedelta(days=97), NOW - timedelta(days=7)
    )
    await FormulaRecoveryQueue(year_db, now=lambda: NOW).enqueue(request)

    status = await year_history_status(year_db, SELLER, NOW)

    assert status == {
        "target": target.isoformat(),
        "covered": False,
        "sources": {
            "orders": {"edge": (target - timedelta(days=1)).isoformat(), "covered": True},
            "questions": {"edge": (NOW - timedelta(days=7)).isoformat(), "covered": False},
            "devoluciones": {"edge": (NOW - timedelta(days=90)).isoformat(), "covered": False},
        },
        "portions": {"pending": 1},
    }
    # A legacy history plan (the paused pilot) changes nothing: sources speak for themselves.
    await year_db.sheets_history_backfill_plans.insert_one({"_id": SELLER, "seller_id": SELLER})
    assert await year_history_status(year_db, SELLER, NOW) == status

    # A portion that failed at the edge says what holds the source there,
    # without presenting the edge as covered.
    await year_db[JOBS].update_one(
        {"_id": request.key},
        {"$set": {"state": "failed", "attempts": 3, "failure_reason": "source_incomplete"}},
    )
    failed = await year_history_status(year_db, SELLER, NOW)
    assert failed["sources"]["questions"] == {
        "edge": (NOW - timedelta(days=7)).isoformat(),
        "covered": False,
        "retrying": {
            "date_from": request.date_from.isoformat(),
            "date_to": request.date_to.isoformat(),
            "state": "failed",
            "failure_reason": "source_incomplete",
            "attempts": 3,
        },
    }
    assert failed["portions"] == {"failed": 1}
