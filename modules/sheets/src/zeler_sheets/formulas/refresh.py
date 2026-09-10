"""Scheduled ZelerData read-model refresh that keeps markers productive.

The refresh never touches Mercado Libre on the formula path. It plans bounded
recovery requests onto the existing durable queue, and the recovery worker
performs the acquisition. Enabling is explicit per seller and every knob is a
runtime flag so the loop can be stopped without a deploy.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable, Iterable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import structlog

from zeler_sheets.formulas.recovery import (
    RECOVERABLE_MODELS,
    RecoveryRequest,
)

logger = structlog.get_logger(__name__)

# Every refresh mode re-plans the whole enabled set; only the window changes.
# The daily and weekly sweeps re-read ranges the fast sweep deliberately skips.
IMPLEMENTED_REFRESH_MODELS: frozenset[str] = frozenset(
    {
        "orders",
        "questions",
        "shipments",
        "item_formula_rows",
        "catalog_product_snapshots",
        "catalog_buybox_snapshots",
    }
)

if not IMPLEMENTED_REFRESH_MODELS <= RECOVERABLE_MODELS:  # pragma: no cover - import guard
    raise RuntimeError("refresh models must be recoverable read models")

FAST_MODE = "fast"
DAILY_MODE = "daily"
FULL_MODE = "full"
REFRESH_MODES: frozenset[str] = frozenset({FAST_MODE, DAILY_MODE, FULL_MODE})

DEFAULT_FAST_WINDOW = timedelta(hours=1)
DEFAULT_DAILY_WINDOW = timedelta(days=7)
# RecoveryRequest caps a single range at 90 days.
DEFAULT_FULL_WINDOW = timedelta(days=90)
DEFAULT_INTERVAL_SECONDS = 900.0
# A marker stays valid for two refresh cycles, so one missed or slow cycle does
# not turn a healthy read model into a visible DATA_UNAVAILABLE result.
MARKER_VALIDITY = timedelta(minutes=30)
DEFAULT_DAILY_HOUR_UTC = 3
DEFAULT_FULL_WEEKDAY = 0  # Monday


def refresh_sellers(value: str | None) -> frozenset[str]:
    """Runtime refresh is closed unless sellers are explicitly configured."""
    if not value or not value.strip():
        return frozenset()
    sellers = frozenset(part.strip() for part in value.split(","))
    if any(not seller.isascii() or not seller.isdecimal() for seller in sellers):
        raise ValueError("zelerdata refresh requires explicit numeric seller IDs")
    return sellers


def reconciled_marker(
    *,
    seller_id: str,
    read_model: str,
    start: datetime,
    end: datetime,
    now: datetime,
) -> dict[str, Any]:
    """Build the reconciled freshness marker for a completed read-model window.

    ``valid_until`` covers two refresh cycles so a single missed or slow cycle
    does not expire a read model that is still authoritative.
    """
    return {
        "_id": f"{seller_id}:{read_model}",
        "seller_id": seller_id,
        "read_model": read_model,
        "state": "reconciled",
        "date_from": start,
        "reconciled_until": end,
        "fresh_until": end,
        "updated_at": now,
        "valid_until": now + MARKER_VALIDITY,
        "source": "zelerdata_read_model_reconcile",
        "schema_version": 1,
    }


class RefreshExplorer(Protocol):
    async def discover_sellers(self) -> tuple[str, ...]: ...


class RefreshPlanner(Protocol):
    async def plan(self, *, seller_id: str, mode: str = FAST_MODE) -> bool: ...


class ZelerDataRefreshPlanner:
    """Plan bounded recovery for one seller without touching Mercado Libre."""

    def __init__(
        self,
        *,
        queue: Any,
        enabled_models: Iterable[str] = IMPLEMENTED_REFRESH_MODELS,
        allowed_sellers: frozenset[str] | None = None,
        now: Callable[[], datetime] | None = None,
        fast_window: timedelta = DEFAULT_FAST_WINDOW,
        daily_window: timedelta = DEFAULT_DAILY_WINDOW,
        full_window: timedelta = DEFAULT_FULL_WINDOW,
    ) -> None:
        if min(fast_window, daily_window, full_window) <= timedelta(0):
            raise ValueError("refresh windows must be positive")
        if full_window > timedelta(days=90):
            raise ValueError("full refresh window cannot exceed the 90-day recovery range")
        enabled = frozenset(enabled_models)
        if not enabled or not enabled <= RECOVERABLE_MODELS:
            raise ValueError("refresh models must be recoverable read models")
        self._queue = queue
        self._enabled_models = enabled
        self._allowed_sellers = allowed_sellers
        self._now = now or (lambda: datetime.now(UTC))
        self._fast_window = fast_window
        self._daily_window = daily_window
        self._full_window = full_window

    async def plan(self, *, seller_id: str, mode: str = FAST_MODE) -> bool:
        if mode not in REFRESH_MODES:
            raise ValueError("refresh mode must be fast, daily, or full")
        if self._allowed_sellers is not None and seller_id not in self._allowed_sellers:
            return False
        now = self._now().astimezone(UTC)
        models = self._enabled_models
        window = {
            FAST_MODE: self._fast_window,
            DAILY_MODE: self._daily_window,
            FULL_MODE: self._full_window,
        }[mode]
        date_to = now
        date_from = now - window
        admitted = False
        for read_model in sorted(models):
            request = RecoveryRequest(
                seller_id=seller_id,
                read_model=read_model,
                date_from=date_from,
                date_to=date_to,
            )
            try:
                async with asyncio.timeout(2):
                    await self._queue.enqueue(request)
            except (ValueError, TimeoutError):
                # Capacity and dedup rejections are expected. One model must not
                # stop the rest of the cycle.
                continue
            except Exception:  # noqa: BLE001 - storage errors must not stop the loop
                logger.warning("zelerdata.refresh_enqueue_failed", read_model=read_model)
                continue
            admitted = True
        return admitted


class MongoSellerExplorer:
    """Discover refreshable sellers from linked accounts, without extra flags."""

    def __init__(self, *, db: Any, allowed_sellers: frozenset[str] | None = None) -> None:
        self._db = db
        self._allowed_sellers = allowed_sellers

    async def discover_sellers(self) -> tuple[str, ...]:
        if self._allowed_sellers is not None:
            return tuple(sorted(self._allowed_sellers))
        cursor = self._db["meli_accounts"].find(
            {"status": "active"},
            {"seller_id": 1},
        )
        sellers: set[str] = set()
        async for row in cursor:
            seller_id = str(row.get("seller_id") or "").strip()
            if seller_id.isascii() and seller_id.isdecimal():
                sellers.add(seller_id)
        return tuple(sorted(sellers))


class ZelerDataRefreshSupervisor:
    """Run the refresh cycle on an interval with bounded failure isolation."""

    def __init__(
        self,
        *,
        explorer: RefreshExplorer,
        planner: RefreshPlanner,
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
        now: Callable[[], datetime] | None = None,
        daily_hour_utc: int = DEFAULT_DAILY_HOUR_UTC,
        full_weekday: int = DEFAULT_FULL_WEEKDAY,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("refresh interval must be positive")
        if not 0 <= daily_hour_utc <= 23:
            raise ValueError("daily hour must be a valid UTC hour")
        if not 0 <= full_weekday <= 6:
            raise ValueError("full review weekday must be a valid UTC weekday")
        self._explorer = explorer
        self._planner = planner
        self._interval = interval_seconds
        self._now = now or (lambda: datetime.now(UTC))
        self._daily_hour = daily_hour_utc
        self._full_weekday = full_weekday
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._cycle = asyncio.Event()
        self._last_daily_date: Any = None
        self._last_full_date: Any = None
        self.health_status = "starting"

    async def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("zelerdata refresh already started")
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run())

    async def wait(self) -> None:
        if self._task is None:
            raise RuntimeError("zelerdata refresh is not started")
        await self._task

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)
        self.health_status = "stopped"

    async def wait_for_cycle(self) -> bool:
        await self._cycle.wait()
        return self.health_status == "ok"

    async def _run(self) -> None:
        failures = 0
        while not self._stop_event.is_set():
            try:
                await self.run_cycle()
            except Exception as exc:  # noqa: BLE001 - the loop owns its own recovery
                failures += 1
                self.health_status = "error"
                logger.warning("zelerdata.refresh_cycle_failed", failures=failures)
                if failures >= 3:
                    raise RuntimeError(
                        "zelerdata refresh restart budget exhausted"
                    ) from exc
            else:
                failures = 0
                self.health_status = "ok"
            await self._wait_or_stop(self._interval)

    async def _wait_or_stop(self, delay: float) -> None:
        with suppress(TimeoutError):
            await asyncio.wait_for(self._stop_event.wait(), timeout=delay)

    def _due_modes(self, now: datetime) -> tuple[str, ...]:
        modes: list[str] = [FAST_MODE]
        if now.hour >= self._daily_hour and self._last_daily_date != now.date():
            modes.append(DAILY_MODE)
        if (
            now.weekday() == self._full_weekday
            and now.hour >= self._daily_hour
            and self._last_full_date != now.date()
        ):
            modes.append(FULL_MODE)
        return tuple(modes)

    async def run_cycle(self) -> bool:
        now = self._now().astimezone(UTC)
        modes = self._due_modes(now)
        sellers = await self._explorer.discover_sellers()
        admitted = False
        for seller_id in sellers:
            for mode in modes:
                try:
                    result = await self._planner.plan(seller_id=seller_id, mode=mode)
                except Exception:  # noqa: BLE001 - one seller must not stop the rest
                    logger.warning("zelerdata.refresh_seller_failed", seller_id=seller_id)
                    continue
                if inspect.isawaitable(result):  # pragma: no cover - defensive
                    result = await result
                admitted = bool(result) or admitted
        if DAILY_MODE in modes:
            self._last_daily_date = now.date()
        if FULL_MODE in modes:
            self._last_full_date = now.date()
        self.health_status = "ok"
        self._cycle.set()
        return admitted
