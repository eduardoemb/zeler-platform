"""Scheduled ZelerData read-model refresh that keeps markers productive.

The refresh never touches Mercado Libre on the formula path. It plans bounded
recovery requests onto the existing durable queue, and the recovery worker
performs the acquisition. Enabling is explicit per seller and every knob is a
runtime flag so the loop can be stopped without a deploy.
"""

from __future__ import annotations

import asyncio
import inspect
import re
from collections.abc import Awaitable, Callable, Iterable, Mapping
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import structlog

from zeler_platform_core.read_model_freshness import READ_MODEL_MARKER_VALIDITY
from zeler_sheets.formulas.recovery import (
    RECOVERABLE_MODELS,
    CatalogRecoveryRequest,
    ItemInventoryRecoveryRequest,
    RecoveryRequest,
    ShipmentIdsRecoveryRequest,
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

# These models cannot be addressed by a date range: acquisition needs explicit
# publications, catalog products, or shipments. Planning them as range requests
# is silently rejected by the recovery queue, which is how the first version of
# this loop ended up refreshing only two of its six declared models.
EXPLICIT_IDENTITY_MODELS: frozenset[str] = frozenset(
    {
        "catalog_product_snapshots",
        "catalog_buybox_snapshots",
        "shipments",
    }
)

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
# Shared with the formula reader and the status report through core so the
# tolerance cannot drift between the three consumers.
MARKER_VALIDITY = READ_MODEL_MARKER_VALIDITY
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


# A proven interval is durable history, so retained proofs are compacted
# instead of expiring. The cap bounds the marker document; formulas only read
# the last 90 days, and dropping an old proof fails closed (DATA_UNAVAILABLE)
# rather than presenting unproven data.
MAX_RETAINED_INTERVALS = 32


def merge_interval_proofs(
    proofs: Iterable[Mapping[str, Any]],
    *,
    keep: int = MAX_RETAINED_INTERVALS,
) -> list[dict[str, Any]]:
    """Merge overlapping or contiguous reconciled intervals into durable proofs.

    Two proofs that touch were each acquired and verified against the source, so
    their union is equally proven; a real gap between them is preserved. Proofs
    without a concrete validity boundary cannot be retained safely and are
    dropped, because the marker validator requires one.
    """
    if keep < 1:
        raise ValueError("retained proof cap must be positive")
    normalized: list[dict[str, Any]] = []
    for proof in proofs:
        if not isinstance(proof, Mapping):
            continue
        start = proof.get("date_from")
        end = proof.get("reconciled_until")
        valid_until = proof.get("valid_until")
        if (
            proof.get("state") != "reconciled"
            or not isinstance(start, datetime)
            or not isinstance(end, datetime)
            or not isinstance(valid_until, datetime)
            or end < start
        ):
            continue
        normalized.append(
            {
                "state": "reconciled",
                "date_from": start,
                "reconciled_until": end,
                "valid_until": valid_until,
            }
        )
    normalized.sort(key=lambda proof: (proof["date_from"], proof["reconciled_until"]))
    merged: list[dict[str, Any]] = []
    for proof in normalized:
        if merged and proof["date_from"] <= merged[-1]["reconciled_until"]:
            previous = merged[-1]
            previous["reconciled_until"] = max(
                previous["reconciled_until"], proof["reconciled_until"]
            )
            previous["valid_until"] = max(previous["valid_until"], proof["valid_until"])
            continue
        merged.append(dict(proof))
    return merged[-keep:]


class RefreshIdentitySource(Protocol):
    """Resolve the explicit identities a bounded refresh needs.

    Three of the six refreshable models cannot be addressed by a date range:
    item rows need a whole-seller inventory sweep, and both catalog models need
    explicit publication or product identities. The source reads them from the
    already-acquired local read models, so planning never calls Mercado Libre.
    """

    async def catalog_product_ids(self, seller_id: str) -> tuple[str, ...]: ...

    async def buybox_item_ids(self, seller_id: str) -> tuple[str, ...]: ...

    async def shipment_ids(self, seller_id: str) -> tuple[str, ...]: ...


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
        identity_source: RefreshIdentitySource | None = None,
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
        needs_identities = enabled & EXPLICIT_IDENTITY_MODELS
        if needs_identities and identity_source is None:
            raise ValueError(
                "an identity source is required to refresh " + ", ".join(sorted(needs_identities))
            )
        self._queue = queue
        self._enabled_models = enabled
        self._identity_source = identity_source
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
            requests = await self._requests_for(
                seller_id=seller_id,
                read_model=read_model,
                date_from=date_from,
                date_to=date_to,
            )
            for request in requests:
                try:
                    async with asyncio.timeout(2):
                        await self._queue.enqueue(request)
                except (ValueError, TimeoutError):
                    # Capacity and dedup rejections are expected. One model must
                    # not stop the rest of the cycle.
                    continue
                except Exception:  # noqa: BLE001 - storage errors must not stop the loop
                    logger.warning("zelerdata.refresh_enqueue_failed", read_model=read_model)
                    continue
                admitted = True
        return admitted

    async def _requests_for(
        self,
        *,
        seller_id: str,
        read_model: str,
        date_from: datetime,
        date_to: datetime,
    ) -> tuple[Any, ...]:
        """Build the admissible requests for one model.

        The queue rejects a generic range request for four of the six
        refreshable models because those sources need explicit identities.
        Planning the wrong shape silently produced a refresh loop that only
        ever served two models, so the shape is now chosen per model.
        """
        if read_model == "orders" or read_model == "questions":
            return (
                RecoveryRequest(
                    seller_id=seller_id,
                    read_model=read_model,
                    date_from=date_from,
                    date_to=date_to,
                ),
            )
        if read_model == "item_formula_rows":
            # A whole-seller inventory sweep is the only honest way to certify
            # current item rows; a windowed range cannot prove membership.
            return (ItemInventoryRecoveryRequest(seller_id),)
        source = self._identity_source
        if source is None:  # pragma: no cover - constructor guards this
            return ()
        if read_model == "catalog_product_snapshots":
            identities = await source.catalog_product_ids(seller_id)
            return (
                (CatalogRecoveryRequest(seller_id, read_model, tuple(identities)),)
                if identities
                else ()
            )
        if read_model == "catalog_buybox_snapshots":
            identities = await source.buybox_item_ids(seller_id)
            return (
                (CatalogRecoveryRequest(seller_id, read_model, tuple(identities)),)
                if identities
                else ()
            )
        if read_model == "shipments":
            identities = await source.shipment_ids(seller_id)
            # One intent admits at most 100 explicit shipment IDs, so a seller
            # with a longer recent history needs several intents to be covered.
            return tuple(
                ShipmentIdsRecoveryRequest(
                    seller_id, tuple(identities[offset : offset + SHIPMENT_INTENT_SIZE])
                )
                for offset in range(0, len(identities), SHIPMENT_INTENT_SIZE)
            )
        return ()  # pragma: no cover - enabled models are exhaustive


# One explicit-intent request admits at most 10,000 identities. Every acquired
# identity is planned: a fixed truncation would renew the same first N forever
# and leave the rest of the seller permanently stale.
MAX_EXPLICIT_IDENTITIES = 10000
# One shipment intent admits at most 100 explicit IDs.
SHIPMENT_INTENT_SIZE = 100
# Buybox acquisition only accepts publications whose canonical item was synced
# within this window, so planning anything older would fail every job.
BUYBOX_FRESHNESS = timedelta(minutes=15)
# Shipments are refreshed for the same horizon the shipping formulas read.
SHIPMENT_LOOKBACK = timedelta(days=30)
_IDENTITY_PATTERN = re.compile(r"ML[A-Z][0-9]+")


class MongoRefreshIdentitySource:
    """Resolve explicit refresh identities from already-acquired read models.

    This only reads local collections; the refresh never calls Mercado Libre
    while planning. Missing or malformed identities are dropped rather than
    guessed, and each cycle is bounded so a very large seller cannot starve the
    interactive formula budget.
    """

    def __init__(
        self,
        *,
        db: Any,
        now: Callable[[], datetime] | None = None,
        max_identities: int = MAX_EXPLICIT_IDENTITIES,
    ) -> None:
        if max_identities < 1:
            raise ValueError("identity limit must be positive")
        self._db = db
        self._now = now or (lambda: datetime.now(UTC))
        self._max_identities = max_identities

    async def catalog_product_ids(self, seller_id: str) -> tuple[str, ...]:
        rows = await self._db["items"].distinct("catalog_product_id", {"seller_id": seller_id})
        identities = {
            str(value)
            for value in rows
            if isinstance(value, str) and _IDENTITY_PATTERN.fullmatch(value)
        }
        return tuple(sorted(identities)[: self._max_identities])

    async def buybox_item_ids(self, seller_id: str) -> tuple[str, ...]:
        cursor = (
            self._db["items"]
            .find(
                {"seller_id": seller_id, "catalog_listing": True},
                {
                    "_id": 1,
                    "catalog_product_id": 1,
                    "last_meli_sync_at": 1,
                },
            )
            .sort([("_id", 1)])
            .limit(self._max_identities)
        )
        now = self._now().astimezone(UTC)
        identities: set[str] = set()
        async for row in cursor:
            identity = str(row.get("_id") or "").strip()
            synced = row.get("last_meli_sync_at")
            if synced is not None and synced.tzinfo is None:
                synced = synced.replace(tzinfo=UTC)
            if (
                _IDENTITY_PATTERN.fullmatch(identity)
                and isinstance(row.get("catalog_product_id"), str)
                and _IDENTITY_PATTERN.fullmatch(str(row["catalog_product_id"]))
                and isinstance(synced, datetime)
                and now - BUYBOX_FRESHNESS < synced <= now
            ):
                identities.add(identity)
        return tuple(sorted(identities))

    async def shipment_ids(self, seller_id: str) -> tuple[str, ...]:
        cutoff = self._now().astimezone(UTC) - SHIPMENT_LOOKBACK
        cursor = (
            self._db["shipments"]
            .find(
                {"seller_id": seller_id, "date_created": {"$gte": cutoff}},
                {"_id": 1},
            )
            .sort([("date_created", -1)])
            .limit(self._max_identities)
        )
        identities: set[str] = set()
        async for row in cursor:
            identity = str(row.get("_id") or "").strip()
            if identity.isascii() and identity.isdecimal():
                identities.add(identity)
        return tuple(sorted(identities))


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
        observed_marker_publisher: Callable[[str], Awaitable[tuple[str, ...]]] | None = None,
        devoluciones_runner: Callable[[str], Awaitable[bool]] | None = None,
        precalculated_warmer: Callable[[str], Awaitable[int]] | None = None,
        freshness_alarm_reporter: Callable[[str], Awaitable[tuple[Any, ...]]] | None = None,
        refresh_failure_reporter: Callable[[int], Awaitable[None]] | None = None,
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
        self._observed_marker_publisher = observed_marker_publisher
        self._devoluciones_runner = devoluciones_runner
        self._precalculated_warmer = precalculated_warmer
        self._freshness_alarm_reporter = freshness_alarm_reporter
        self._refresh_failure_reporter = refresh_failure_reporter
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
                if self._refresh_failure_reporter is not None:
                    try:
                        # Q21-a also covers the loop failing repeatedly, which is
                        # a different failure from one slow read model.
                        await self._refresh_failure_reporter(failures)
                    except Exception:  # noqa: BLE001 - alerting must not stop recovery
                        logger.warning("zelerdata.freshness_alarm_failed", seller_id="")
                if failures >= 3:
                    raise RuntimeError("zelerdata refresh restart budget exhausted") from exc
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
            if self._observed_marker_publisher is not None:
                try:
                    # Observed-only models cannot be certified by a source
                    # reconciliation. Their heartbeat is renewed once per cycle
                    # and expires like any other claim, so a stopped refresh
                    # loop still fails those formulas closed.
                    await self._observed_marker_publisher(seller_id)
                except Exception:  # noqa: BLE001 - markers must not stop the loop
                    logger.warning("zelerdata.observed_marker_failed", seller_id=seller_id)
            if self._devoluciones_runner is not None:
                try:
                    # DEVOLUCIONES is absorbed into this loop (Q2-b/Q7-a). The
                    # runner only advances a run an operator already authorized;
                    # it never creates or widens coverage.
                    if await self._devoluciones_runner(seller_id):
                        admitted = True
                except Exception:  # noqa: BLE001 - one model must not stop the loop
                    logger.warning("zelerdata.devoluciones_run_failed", seller_id=seller_id)
            if self._precalculated_warmer is not None:
                try:
                    # Q3/Q8/Q16: the heavy aggregate formulas are computed here,
                    # where the refresh already reads the same data, so the sheet
                    # call is a bounded document read instead of a 20s aggregation.
                    if await self._precalculated_warmer(seller_id):
                        admitted = True
                except Exception:  # noqa: BLE001 - one formula must not stop the loop
                    logger.warning("zelerdata.precalculated_warm_failed", seller_id=seller_id)
            if self._freshness_alarm_reporter is not None:
                try:
                    # Q21-a: a model that stopped refreshing past its own marker
                    # window, or that an operator invalidated, becomes an explicit
                    # operator-visible alert instead of a log line nobody reads.
                    await self._freshness_alarm_reporter(seller_id)
                except Exception:  # noqa: BLE001 - alerting must not stop the loop
                    logger.warning("zelerdata.freshness_alarm_failed", seller_id=seller_id)
        if DAILY_MODE in modes:
            self._last_daily_date = now.date()
        if FULL_MODE in modes:
            self._last_full_date = now.date()
        self.health_status = "ok"
        self._cycle.set()
        return admitted
