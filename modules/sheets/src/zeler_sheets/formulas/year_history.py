"""Twelve months of history for every eligible ZelerData seller (2026-10-12).

A new seller had what its bootstrap acquired at link time plus what refresh
added from then on, so order and question ranges older than about 90 days
stayed ``DATA_UNAVAILABLE``. The refresh loop now walks each range source
backwards from the start of its proven coverage until that coverage reaches a
full year. It plans existing recovery work; the recovery worker acquires it.

- One portion per cycle for the whole fleet, and only while no portion is
  running or ready and no renewal pass is in flight, so it never competes with
  renewal or sweeps. A portion waiting for its retry holds no other seller.
- Progress is the proof itself: each portion ends where proven coverage
  starts and is kept as a retained interval of the marker. A restart or a
  second worker computes the same portion from the same marker, and its key
  coalesces in the queue.
- Each source is judged on its own proofs. A seller with a legacy history
  plan (the paused pilot, included on 2026-10-13) walks the sources short of a
  year like any other; its plan is neither read nor resumed.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime, time, timedelta
from typing import Any

import structlog

from zeler_sheets.formulas.recovery import YEAR_HISTORY_MODELS, YearHistoryRecoveryRequest

logger = structlog.get_logger(__name__)

# A year back from any day, leap days included, from UTC midnight.
YEAR_HISTORY_DAYS = 366
# A portion must finish inside the recovery job's 240-second deadline even
# when the ranges lane gets a quarter of the 180-per-minute pacer (45 per
# minute, 180 calls). An order costs one detail call and a question one detail
# call; search pages come on top.
PORTION_ROWS: Mapping[str, int] = {"orders": 120, "questions": 100}
MAX_PORTION: Mapping[str, timedelta] = {
    "orders": timedelta(days=30),
    "questions": timedelta(days=90),
}
MIN_PORTION = timedelta(hours=1)
# A portion fails only after its three attempts (a deadline, a 429 or 5xx, or a
# source answer that cannot be proven whole), and the next one at the same edge
# has half its span, so the walk narrows down to the hour the source refuses.
# Until 2026-10-13 ``source_incomplete`` failed at the first attempt and the
# same portion was reopened whole after every cooldown, without end. Only a
# portion closed because the seller was not eligible is retried whole.
RETRY_WHOLE = frozenset({"seller_not_eligible"})
# A minimal portion that keeps failing is retried at most this often.
RETRY_AT_MINIMUM = timedelta(hours=6)
FRESHNESS = "sheets_read_model_freshness"


def year_history_target(now: datetime) -> datetime:
    """The UTC midnight a full year back, leap days included."""
    day = (now.astimezone(UTC) - timedelta(days=YEAR_HISTORY_DAYS)).date()
    return datetime.combine(day, time.min, tzinfo=UTC)


def _utc(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def proven_edge(marker: Mapping[str, Any] | None) -> datetime | None:
    """Where the most recent block of proven coverage starts, or ``None``.

    The marker's own interval and its retained proofs are merged where they
    touch; the block that ends last is the one the sweeps keep current. A
    gap below it is filled by walking back from its start.
    """
    blocks = _proven_blocks(marker)
    return blocks[-1][0] if blocks else None


def _proven_blocks(marker: Mapping[str, Any] | None) -> list[list[datetime]]:
    """The marker's proven intervals merged where they touch, oldest first."""
    if not isinstance(marker, Mapping) or marker.get("state") != "reconciled":
        return []
    proofs: list[Any] = [marker]
    retained = marker.get("retained_intervals")
    if isinstance(retained, list):
        proofs.extend(retained)
    intervals = []
    for proof in proofs:
        if not isinstance(proof, Mapping) or proof.get("state") != "reconciled":
            continue
        start = _utc(proof.get("date_from")) or _utc(proof.get("last_event_synced_at"))
        end = _utc(proof.get("reconciled_until"))
        if start is not None and end is not None and start < end:
            intervals.append((start, end))
    intervals.sort()
    blocks: list[list[datetime]] = []
    for start, end in intervals:
        if blocks and start <= blocks[-1][1]:
            blocks[-1][1] = max(blocks[-1][1], end)
        else:
            blocks.append([start, end])
    return blocks


async def year_history_status(db: Any, seller_id: str, now: datetime) -> dict[str, Any]:
    """Where each source's proven coverage starts, against the year target.

    Read-only and sanitized: dates, flags and counts for the requested seller.
    A source held at its edge by a failed portion or window says so in
    ``retrying``; its edge stays where the proofs end, never covered.
    """
    from zeler_platform_core.devoluciones_certificates import CERTIFICATES, coverage_control
    from zeler_sheets.devoluciones_runner import (
        year_history_pending_windows,
        year_history_retrying,
    )

    target = year_history_target(now)
    sources: dict[str, dict[str, Any]] = {}
    for model in ("orders", "questions"):
        edge = proven_edge(
            await db[FRESHNESS].find_one({"_id": f"{seller_id}:{model}", "seller_id": seller_id})
        )
        sources[model] = {
            "edge": edge.isoformat() if edge else None,
            "covered": edge is not None and edge <= target,
        }
        if edge is not None and edge > target:
            retrying = await _portion_retrying(db, seller_id, model, edge)
            if retrying is not None:
                sources[model]["retrying"] = retrying
    control = await coverage_control(db, seller_id)
    oldest = None
    if control.get("coverage_mode") == "active":
        row = await db[CERTIFICATES].find_one(
            {"seller_id": seller_id, "coverage_epoch": control.get("coverage_epoch")},
            {"date_from": 1},
            sort=[("date_from", 1)],
        )
        oldest = _utc(row.get("date_from")) if row else None
    sources["devoluciones"] = {
        "edge": oldest.isoformat() if oldest else None,
        "covered": oldest is not None and oldest <= target,
    }
    window = await year_history_retrying(db, seller_id, oldest, now=now)
    if window is not None:
        sources["devoluciones"]["retrying"] = window
    if control.get("coverage_mode") == "active":
        # Open mediations certified windows leave out as pending, watched
        # until they close or get a return: a count, never an identity.
        pending = sum(
            int(window["counters"]["pending_open_mediations"])
            for window in await year_history_pending_windows(
                db, seller_id, control.get("coverage_epoch")
            )
        )
        if pending:
            sources["devoluciones"]["pending_open_mediations"] = pending
    portions: dict[str, int] = {}
    async for job in db["sheets_formula_recovery_jobs"].find(
        {"seller_id": seller_id, "year_history": True}, {"state": 1}
    ):
        state = str(job.get("state"))
        portions[state] = portions.get(state, 0) + 1
    return {
        "target": target.isoformat(),
        "covered": all(source["covered"] for source in sources.values()),
        "sources": sources,
        "portions": portions,
    }


async def _portion_retrying(
    db: Any, seller_id: str, model: str, edge: datetime
) -> dict[str, Any] | None:
    """The latest portion at ``edge`` when it failed or waits for a retry."""
    rows = (
        await db["sheets_formula_recovery_jobs"]
        .find(
            {"seller_id": seller_id, "read_model": model, "year_history": True},
            {"state": 1, "date_from": 1, "date_to": 1, "failure_reason": 1, "attempts": 1},
        )
        .sort([("updated_at", -1), ("_id", 1)])
        .limit(1)
        .to_list(length=1)
    )
    if not rows:
        return None
    job = rows[0]
    start, end = _utc(job.get("date_from")), _utc(job.get("date_to"))
    if (
        job.get("state") not in {"pending", "failed"}
        or not job.get("failure_reason")
        or start is None
        or end is None
        or not start < edge <= end
    ):
        return None
    return {
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "state": str(job["state"]),
        "failure_reason": str(job["failure_reason"]),
        "attempts": int(job.get("attempts", 0)),
    }


def _floor_hour(value: datetime) -> datetime:
    return value.replace(minute=0, second=0, microsecond=0)


def _ceil_hour(value: datetime) -> datetime:
    floor = _floor_hour(value)
    return floor if floor == value else floor + timedelta(hours=1)


def _whole_hours(value: timedelta) -> timedelta:
    return timedelta(hours=max(1, math.floor(value / timedelta(hours=1))))


class YearHistoryPlanner:
    """Admit one backward portion of orders or questions per cycle for the fleet."""

    def __init__(
        self,
        *,
        db: Any,
        queue: Any,
        eligible: Callable[[str], Awaitable[bool]],
        now: Callable[[], datetime] | None = None,
        models: Iterable[str] = ("orders", "questions"),
    ) -> None:
        selected = tuple(models)
        if not selected or not set(selected) <= YEAR_HISTORY_MODELS:
            raise ValueError("year history covers orders and questions")
        self._db = db
        self._queue = queue
        self._eligible = eligible
        self._now = now or (lambda: datetime.now(UTC))
        self._models = selected
        # The last seller and source served; the turn starts after it.
        self._last_served: tuple[str, str] | None = None
        # Settled outcomes are logged once per process, not every cycle.
        self._reported: set[tuple[str, str, str]] = set()

    async def plan(self, seller_ids: Sequence[str]) -> bool:
        """Admit at most one portion; ``True`` when one was admitted."""
        pairs = [
            (seller_id, model) for seller_id in dict.fromkeys(seller_ids) for model in self._models
        ]
        if not pairs:
            return False
        try:
            async with asyncio.timeout(5):
                # One portion at a time for the fleet, and none while a renewal
                # pass fills the shared pacer.
                if await self._queue.year_history_in_flight():
                    return False
                if await self._queue.renewal_in_flight():
                    return False
        except Exception:  # noqa: BLE001 - an unreadable queue skips this cycle
            logger.warning("zelerdata.year_history_status_failed")
            return False
        if self._last_served in pairs:
            start = pairs.index(self._last_served) + 1
            pairs = pairs[start:] + pairs[:start]
        for seller_id, model in pairs:
            try:
                async with asyncio.timeout(5):
                    request = await self._next_portion(seller_id, model)
            except Exception:  # noqa: BLE001 - one seller must not stop the others
                logger.warning(
                    "zelerdata.year_history_selection_failed", seller_id=seller_id, read_model=model
                )
                continue
            if request is None:
                continue
            try:
                async with asyncio.timeout(2):
                    await self._queue.enqueue(request)
            except Exception as exc:  # noqa: BLE001 - capacity or storage: next turn
                logger.info(
                    "zelerdata.year_history_not_admitted",
                    seller_id=seller_id,
                    read_model=model,
                    error_type=type(exc).__name__,
                )
                continue
            self._last_served = (seller_id, model)
            logger.info(
                "zelerdata.year_history_planned",
                seller_id=seller_id,
                read_model=model,
                date_from=request.date_from.isoformat(),
                date_to=request.date_to.isoformat(),
            )
            return True
        return False

    def _report_once(self, seller_id: str, model: str, outcome: str) -> None:
        if (seller_id, model, outcome) in self._reported:
            return
        self._reported.add((seller_id, model, outcome))
        logger.info(f"zelerdata.year_history_{outcome}", seller_id=seller_id, read_model=model)

    async def _next_portion(self, seller_id: str, model: str) -> YearHistoryRecoveryRequest | None:
        if not await self._eligible(seller_id):
            return None
        now = self._now().astimezone(UTC)
        target = year_history_target(now)
        marker = await self._db[FRESHNESS].find_one(
            {"_id": f"{seller_id}:{model}", "seller_id": seller_id}
        )
        blocks = _proven_blocks(marker)
        if not blocks:
            # The refresh sweeps establish the live coverage first.
            return None
        edge = blocks[-1][0]
        # An older proof below a gap (the pilot's retained history, say) is
        # not read again: the portion only fills the gap down to its end.
        floor = _floor_hour(blocks[-2][1]) if len(blocks) > 1 else None
        if edge <= target:
            self._report_once(seller_id, model, "covered")
            return None
        end = min(_ceil_hour(edge), _ceil_hour(now))
        span = await self._span(seller_id, model, end, now=now)
        latest = await self._queue.latest_year_history(seller_id=seller_id, read_model=model)
        if latest is not None and latest.get("state") in {"pending", "running"}:
            # Its own portion is still alive, perhaps waiting for a retry.
            return None
        if (
            latest is not None
            and latest.get("state") == "failed"
            and _utc(latest.get("date_to")) == end
        ):
            available = _utc(latest.get("available_at"))
            if available is not None and now < available:
                return None
            previous = _utc(latest["date_to"]) - _utc(latest["date_from"])  # type: ignore[operator]
            if latest.get("failure_reason") in RETRY_WHOLE:
                span = min(span, previous)
            else:
                updated = _utc(latest.get("updated_at"))
                if previous <= MIN_PORTION and (
                    updated is None or now < updated + RETRY_AT_MINIMUM
                ):
                    return None
                span = min(span, max(MIN_PORTION, _whole_hours(previous / 2)))
        # Once the newer half of a failed portion is proven, only the rest of
        # that portion is tried next: what the source refused is in there, so
        # the walk narrows down to it instead of failing a whole span again.
        failed = await self._queue.failed_year_history_across(
            seller_id=seller_id, read_model=model, edge=edge
        )
        narrowed = _utc(failed.get("date_from")) if failed is not None else None
        start = max(target, end - span, floor or target, narrowed or target)
        if start >= end:
            return None
        return YearHistoryRecoveryRequest(seller_id, model, start, end)

    async def _span(self, seller_id: str, model: str, end: datetime, *, now: datetime) -> timedelta:
        """A span that holds about ``PORTION_ROWS`` rows at the density around the edge.

        Rows already stored next to the edge (proven coverage after it, the
        bootstrap's rows before it) are the best local estimate. A failure
        still halves the next portion.
        """
        longest = MAX_PORTION[model]
        lower, upper = end - longest, min(end + longest, now)
        if upper <= lower:
            return longest
        rows = await self._db[model].count_documents(
            {"seller_id": seller_id, "date_created": {"$gte": lower, "$lt": upper}}
        )
        if rows <= 0:
            return longest
        span = (upper - lower) * PORTION_ROWS[model] / rows
        return min(longest, max(MIN_PORTION, _whole_hours(span)))
