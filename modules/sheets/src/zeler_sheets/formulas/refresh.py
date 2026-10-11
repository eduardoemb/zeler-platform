"""Scheduled ZelerData read-model refresh that keeps markers productive.

The refresh never touches Mercado Libre on the formula path. It plans bounded
recovery requests onto the existing durable queue, and the recovery worker
performs the acquisition. Enabling is explicit, for named sellers or every
eligible one, and every knob is a runtime flag so the loop can be stopped
without a deploy.
"""

from __future__ import annotations

import asyncio
import inspect
import re
import time
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
    RenewalRecoveryRequest,
    ShipmentIdsRecoveryRequest,
)
from zeler_sheets.formulas.seller_scope import eligible_sellers, parse_seller_scope

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

# Range refreshes have a bounded source window. Full-seller identity sweeps
# may take longer than the 15-minute cycle, so the runtime schedules them only
# when an operator explicitly enables that capacity-intensive mode. Formula
# reads can still enqueue the same recoveries on demand.
SCHEDULED_RANGE_REFRESH_MODELS: frozenset[str] = frozenset({"orders", "questions"})

if not IMPLEMENTED_REFRESH_MODELS <= RECOVERABLE_MODELS:  # pragma: no cover - import guard
    raise RuntimeError("refresh models must be recoverable read models")

# Planning acquisition is not the same as publishing a freshness claim. Only
# these models end a refresh cycle with a renewed marker the alert evaluator can
# read: orders and questions through their reconciled range publication. The
# observed-only heartbeats renew their own markers, and the catalog/item inline
# projections keep the legacy reconciliation claim that the loop does not own.
# Alerting on a claim the loop never republishes would page an operator forever.
MARKER_RENEWED_REFRESH_MODELS: frozenset[str] = frozenset({"orders", "questions"})

if not MARKER_RENEWED_REFRESH_MODELS <= IMPLEMENTED_REFRESH_MODELS:  # pragma: no cover
    raise RuntimeError("marker-renewing models must be a subset of the refresh set")

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

# Renewal sweeps keep the acquisitions that only recovery makes (buybox,
# quality and costs) inside the 24 hours their readers serve them (L-044), so a
# sheet opened after a quiet day is already filled. Each maps to the read model
# its recovery jobs use.
ITEM_ENRICHMENT_SWEEP = "item_enrichment"
RENEWAL_SWEEP_READ_MODELS: Mapping[str, str] = {
    "catalog_buybox_snapshots": "catalog_buybox_snapshots",
    ITEM_ENRICHMENT_SWEEP: "item_formula_rows",
}
DEFAULT_RENEWAL_INTERVAL = timedelta(hours=12)
# A pass renews what is at least half an interval old, so an acquisition waits
# at most 1.5 intervals plus two passes (about 75 minutes each) before it is
# renewed: about 21 hours at 12, under the readers' 24. Longer intervals would
# let a slow pass cross that limit.
MAX_RENEWAL_INTERVAL = timedelta(hours=12)
# Slots are fixed in UTC. At 12 hours they start at 01:00 and 13:00 UTC, which
# is 19:00 and 07:00 in Mexico City: a buybox pass pauses the base inventory
# sweep while it runs (L-037), so it starts outside most selling hours.
RENEWAL_SLOT_ORIGIN = datetime(2026, 1, 1, 1, tzinfo=UTC)

# Whole-seller sweeps that may be scheduled on their own spacing instead of
# every cycle. Each is planned only while no sweep of the same model is in
# flight, so a pass never restarts faster than it finishes (L-021). The base
# inventory is cheap (one discovery plus 20-ID batches) and its readers need
# 15-minute data; catalog products are read from a 4-hour cache. Both wait for
# their own interval after the previous pass. A renewal sweep runs at most one
# pass per fixed slot instead, and never reopens an earlier pass's job.
SPACED_SWEEP_MODELS: frozenset[str] = frozenset(
    {"item_formula_rows", "catalog_product_snapshots", *RENEWAL_SWEEP_READ_MODELS}
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
DEFAULT_INVENTORY_INTERVAL_SECONDS = 30.0
# A marker stays valid for two refresh cycles, so one missed or slow cycle does
# not turn a healthy read model into a visible DATA_UNAVAILABLE result.
# Shared with the formula reader and the status report through core so the
# tolerance cannot drift between the three consumers.
MARKER_VALIDITY = READ_MODEL_MARKER_VALIDITY
DEFAULT_DAILY_HOUR_UTC = 3
DEFAULT_FULL_WEEKDAY = 0  # Monday


def renewal_slot(now: datetime, interval: timedelta) -> datetime:
    """The start of the fixed renewal slot that contains ``now``."""
    return RENEWAL_SLOT_ORIGIN + interval * (
        (now.astimezone(UTC) - RENEWAL_SLOT_ORIGIN) // interval
    )


def refresh_sellers(value: str | None) -> frozenset[str] | None:
    """Runtime refresh is closed unless sellers are configured.

    ``all`` returns ``None``: every eligible seller, rediscovered each cycle.
    """
    return parse_seller_scope(value, error="zelerdata refresh requires explicit numeric seller IDs")


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

    async def buybox_renewal_ids(
        self, seller_id: str, *, renew_after: timedelta
    ) -> tuple[str, ...]: ...

    async def enrichment_renewal_ids(
        self, seller_id: str, *, renew_after: timedelta
    ) -> tuple[str, ...]: ...


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
        sweep_intervals: Mapping[str, timedelta] | None = None,
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
        sweeps = dict(sweep_intervals or {})
        if not set(sweeps) <= SPACED_SWEEP_MODELS or set(sweeps) & enabled:
            raise ValueError(
                "spaced sweeps are limited to inventory, catalog products and renewals, "
                "and are never also planned every cycle"
            )
        if any(interval <= timedelta(0) for interval in sweeps.values()):
            raise ValueError("spaced sweep intervals must be positive")
        if any(
            sweeps[sweep] > MAX_RENEWAL_INTERVAL
            for sweep in RENEWAL_SWEEP_READ_MODELS
            if sweep in sweeps
        ):
            raise ValueError("renewal sweeps must run at least every 12 hours")
        needs_identities = (enabled | set(sweeps)) & (
            EXPLICIT_IDENTITY_MODELS | set(RENEWAL_SWEEP_READ_MODELS)
        )
        if needs_identities and identity_source is None:
            raise ValueError(
                "an identity source is required to refresh " + ", ".join(sorted(needs_identities))
            )
        self._queue = queue
        self._enabled_models = enabled
        self._sweep_intervals = sweeps
        self._identity_source = identity_source
        self._allowed_sellers = allowed_sellers
        self._now = now or (lambda: datetime.now(UTC))
        self._fast_window = fast_window
        self._daily_window = daily_window
        self._full_window = full_window
        # The renewal slot each seller and sweep already settled in this
        # process, so a quiet slot is selected once instead of every cycle.
        self._settled_renewals: dict[tuple[str, str], datetime] = {}

    async def plan_inventory(self, seller_id: str) -> bool:
        """Keep current inventory cycling without creating moving range intents."""
        if self._allowed_sellers is not None and seller_id not in self._allowed_sellers:
            return False
        if "item_formula_rows" in self._sweep_intervals:
            return await self._plan_spaced_sweep(seller_id, "item_formula_rows")
        if "item_formula_rows" not in self._enabled_models:
            return False
        try:
            async with asyncio.timeout(2):
                await self._queue.enqueue(ItemInventoryRecoveryRequest(seller_id))
        except (ValueError, TimeoutError):
            return False
        return True

    async def _plan_spaced_sweep(self, seller_id: str, read_model: str) -> bool:
        """Admit one whole-seller sweep only when its own spacing allows it."""
        if read_model in RENEWAL_SWEEP_READ_MODELS:
            return await self._plan_renewal_sweep(seller_id, read_model)
        try:
            async with asyncio.timeout(2):
                in_flight, anchor = await self._queue.sweep_status(
                    seller_id=seller_id, read_model=read_model
                )
        except Exception:  # noqa: BLE001 - an unreadable status skips only this sweep
            logger.warning("zelerdata.refresh_sweep_status_failed", read_model=read_model)
            return False
        if in_flight:
            return False
        now = self._now().astimezone(UTC)
        if anchor is not None and now - anchor < self._sweep_intervals[read_model]:
            return False
        admitted = False
        for request in await self._identity_requests(seller_id=seller_id, read_model=read_model):
            admitted = await self._admit(request) or admitted
        return admitted

    async def _plan_renewal_sweep(self, seller_id: str, sweep: str) -> bool:
        """Admit this slot's renewal of what readers would stop serving before the next.

        Selection only reads local acquisitions. A slot admits one pass, and
        never while another explicit-ID pass of the same model is in flight.
        """
        read_model = RENEWAL_SWEEP_READ_MODELS[sweep]
        interval = self._sweep_intervals[sweep]
        slot = renewal_slot(self._now(), interval)
        if self._settled_renewals.get((seller_id, sweep)) == slot:
            return False
        try:
            async with asyncio.timeout(2):
                in_flight, taken = await self._queue.renewal_status(
                    seller_id=seller_id,
                    read_model=read_model,
                    slot_key=RenewalRecoveryRequest.slot_key(seller_id, read_model, slot),
                )
        except Exception:  # noqa: BLE001 - an unreadable status skips only this sweep
            logger.warning("zelerdata.refresh_sweep_status_failed", read_model=sweep)
            return False
        if in_flight:
            return False
        if taken:
            self._settled_renewals[(seller_id, sweep)] = slot
            return False
        source = self._identity_source
        if source is None:  # pragma: no cover - constructor guards this
            return False
        select = (
            source.buybox_renewal_ids
            if read_model == "catalog_buybox_snapshots"
            else source.enrichment_renewal_ids
        )
        try:
            identities = await select(seller_id, renew_after=interval / 2)
        except Exception:  # noqa: BLE001 - a failed selection is retried next cycle
            logger.warning("zelerdata.refresh_renewal_selection_failed", read_model=sweep)
            return False
        if not identities:
            self._settled_renewals[(seller_id, sweep)] = slot
            logger.info(
                "zelerdata.refresh_renewal_nothing_due",
                seller_id=seller_id,
                read_model=sweep,
                slot=slot.isoformat(),
            )
            return False
        # Terminal jobs are evidence of earlier passes; never reopen them.
        admitted = await self._admit(
            RenewalRecoveryRequest(seller_id, read_model, identities, slot),
            reopen_terminal=False,
        )
        if admitted:
            self._settled_renewals[(seller_id, sweep)] = slot
            logger.info(
                "zelerdata.refresh_renewal_planned",
                seller_id=seller_id,
                read_model=sweep,
                identities=len(identities),
                slot=slot.isoformat(),
            )
        return admitted

    async def _admit(self, request: Any, **enqueue_options: bool) -> bool:
        try:
            async with asyncio.timeout(2):
                await self._queue.enqueue(request, **enqueue_options)
        except (ValueError, TimeoutError):
            # Capacity and dedup rejections are expected. One model must
            # not stop the rest of the cycle.
            return False
        except Exception:  # noqa: BLE001 - storage errors must not stop the loop
            logger.warning("zelerdata.refresh_enqueue_failed", read_model=request.read_model)
            return False
        return True

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
            if read_model == "orders" or read_model == "questions":
                requests: tuple[Any, ...] = (
                    RecoveryRequest(
                        seller_id=seller_id,
                        read_model=read_model,
                        date_from=date_from,
                        date_to=date_to,
                    ),
                )
            else:
                requests = await self._identity_requests(seller_id=seller_id, read_model=read_model)
            for request in requests:
                admitted = await self._admit(request) or admitted
        # Spaced sweeps ignore the mode window; their own guard decides.
        for read_model in sorted(self._sweep_intervals):
            admitted = await self._plan_spaced_sweep(seller_id, read_model) or admitted
        return admitted

    async def _identity_requests(self, *, seller_id: str, read_model: str) -> tuple[Any, ...]:
        """Build the admissible requests for one model that a range cannot address.

        The queue rejects a generic range request for four of the six
        refreshable models because those sources need explicit identities.
        Planning the wrong shape silently produced a refresh loop that only
        ever served two models, so the shape is now chosen per model.
        """
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
# Renewal selection reads whole inventories in small identity chunks and keeps
# only the selected IDs, so worker memory does not follow seller size (L-041).
RENEWAL_READ_CHUNK = 200
# What the buybox reader binds a snapshot to, and the acquired price it falls
# back on; never the whole item document.
_BUYBOX_SOURCE_PROJECTION = {
    "_id": 1,
    "seller_id": 1,
    "catalog_listing": 1,
    "catalog_product_id": 1,
    "title": 1,
    "available_quantity": 1,
    "last_meli_sync_at": 1,
    "currency_id": 1,
    "price": 1,
    "current_promotion": 1,
    "enrichment_state.current_promotion": 1,
}
_ITEM_ROW_PROJECTION = {
    "_id": 1,
    "item_id": 1,
    "sku": 1,
    "normalized_sku": 1,
    "current": 1,
    "source_snapshot": 1,
}


def _chunks(values: tuple[str, ...], size: int) -> Iterable[tuple[str, ...]]:
    return (values[offset : offset + size] for offset in range(0, len(values), size))


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
        roots, variants = await asyncio.gather(
            self._db["items"].distinct("catalog_product_id", {"seller_id": seller_id}),
            self._db["items"].distinct("variations.catalog_product_id", {"seller_id": seller_id}),
        )
        identities = {
            str(value)
            for value in (*roots, *variants)
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

    async def buybox_renewal_ids(
        self, seller_id: str, *, renew_after: timedelta
    ) -> tuple[str, ...]:
        """Catalog publications whose buybox readers would not serve after ``renew_after``.

        The reader's own rule is evaluated at the end of the renewal horizon:
        absent, mismatched or incomplete snapshots, and those that expire by
        then. A fresh ``not_listed`` answer is served as NA and stays (L-045).
        A stale base row is no reason to skip: the worker re-reads the item.
        """
        # Imported here: the readers import this module's marker validity.
        from zeler_sheets.formulas.handlers_item_shipping_catalog import (
            buybox_snapshot_recoverable,
        )
        from zeler_sheets.formulas.read_models import (
            CATALOG_BUYBOX_CACHE_MAX_AGE,
            is_buybox_participant,
            served_buybox_snapshot,
        )

        horizon = self._now().astimezone(UTC) + CATALOG_BUYBOX_CACHE_MAX_AGE - renew_after
        due: set[str] = set()
        for chunk in _chunks(await self._inventory_ids(seller_id), RENEWAL_READ_CHUNK):
            items = (
                await self._db["items"]
                .find(
                    {"seller_id": seller_id, "_id": {"$in": list(chunk)}, "catalog_listing": True},
                    _BUYBOX_SOURCE_PROJECTION,
                )
                .to_list(length=len(chunk))
            )
            participating = {
                str(item["_id"]): item for item in items if is_buybox_participant(item)
            }
            if not participating:
                continue
            served: set[str] = set()
            async for snapshot in self._db["sheets_catalog_buybox_snapshots"].find(
                {"seller_id": seller_id, "item_id": {"$in": sorted(participating)}}
            ):
                identity = str(snapshot.get("item_id"))
                source = participating.get(identity)
                row = (
                    served_buybox_snapshot(snapshot, source, seller_id=seller_id, now=horizon)
                    if source is not None
                    else None
                )
                if row is not None and not buybox_snapshot_recoverable(row):
                    served.add(identity)
            due.update(set(participating) - served)
        return tuple(sorted(due))

    async def enrichment_renewal_ids(
        self, seller_id: str, *, renew_after: timedelta
    ) -> tuple[str, ...]:
        """Publications whose quality or costs readers would not serve after ``renew_after``.

        CALIDAD and CALCULADORA rules are evaluated at the end of the renewal
        horizon, so a basis mismatch, a failed or aging acquisition, or a row
        never projected is selected, and a fresh declared absence is not.
        """
        from zeler_sheets.formulas.handlers_quality_calculator import (
            item_enrichment_unavailable,
        )
        from zeler_sheets.formulas.read_models import ITEM_ENRICHMENT_CACHE_MAX_AGE

        horizon = self._now().astimezone(UTC) + ITEM_ENRICHMENT_CACHE_MAX_AGE - renew_after
        due: set[str] = set()
        for chunk in _chunks(await self._inventory_ids(seller_id), RENEWAL_READ_CHUNK):
            projected: set[str] = set()
            async for row in self._db["sheets_item_formula_rows"].find(
                {"seller_id": seller_id, "item_id": {"$in": list(chunk)}},
                _ITEM_ROW_PROJECTION,
            ):
                identity = str(row.get("item_id") or "")
                projected.add(identity)
                if identity not in due and item_enrichment_unavailable(row, now=horizon):
                    due.add(identity)
            due.update(set(chunk) - projected)
        return tuple(sorted(due))

    async def _inventory_ids(self, seller_id: str) -> tuple[str, ...]:
        """The latest inventory enumeration, minus what its pass could not read.

        Without an enumeration there is nothing provably current to renew. The
        inventory pass re-reads every enumerated publication; one it already
        reached but did not re-read (Mercado Libre answers 404 for its detail)
        is a partial miss no reader serves, and renewing it would only fail
        its 20-ID chunk three times.
        """
        job = await self._db["sheets_formula_recovery_jobs"].find_one(
            {
                "_id": ItemInventoryRecoveryRequest(seller_id).key,
                "seller_id": seller_id,
                "inventory_scope": True,
            },
            {"inventory_ids": 1, "inventory_offset": 1, "inventory_observed_at": 1},
        )
        enumerated = job.get("inventory_ids") if job else None
        if not isinstance(enumerated, list):
            return ()
        identities = tuple(
            sorted(
                {
                    identity
                    for identity in enumerated
                    if isinstance(identity, str) and _IDENTITY_PATTERN.fullmatch(identity)
                }
            )[: self._max_identities]
        )
        offset = job.get("inventory_offset")
        discovered = job.get("inventory_observed_at")
        if type(offset) is not int or not isinstance(discovered, datetime):
            return identities
        discovered = discovered.replace(tzinfo=UTC) if discovered.tzinfo is None else discovered
        reached = tuple(sorted(set(identities) & set(enumerated[:offset])))
        reread: set[str] = set()
        for chunk in _chunks(reached, RENEWAL_READ_CHUNK):
            async for item in self._db["items"].find(
                {"seller_id": seller_id, "_id": {"$in": list(chunk)}},
                {"_id": 1, "last_meli_sync_at": 1},
            ):
                synced = item.get("last_meli_sync_at")
                if (
                    isinstance(synced, datetime)
                    and (synced if synced.tzinfo is not None else synced.replace(tzinfo=UTC))
                    >= discovered
                ):
                    reread.add(str(item["_id"]))
        unreadable = set(reached) - reread
        return tuple(identity for identity in identities if identity not in unreadable)

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
    """Discover refreshable sellers: the explicit allowlist, or every eligible one."""

    def __init__(self, *, db: Any, allowed_sellers: frozenset[str] | None = None) -> None:
        self._db = db
        self._allowed_sellers = allowed_sellers

    async def discover_sellers(self) -> tuple[str, ...]:
        if self._allowed_sellers is not None:
            return tuple(sorted(self._allowed_sellers))
        # Re-read every cycle so a paused or revoked seller drops out at once.
        return await eligible_sellers(self._db)


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
        dlq_archiver: Callable[[], Awaitable[Any]] | None = None,
        freshness_alarm_reporter: Callable[[str], Awaitable[tuple[Any, ...]]] | None = None,
        refresh_failure_reporter: Callable[[int], Awaitable[None]] | None = None,
        inventory_refresher: Callable[[str], Awaitable[bool]] | None = None,
        history_backfill: Callable[[str], Awaitable[bool]] | None = None,
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
        inventory_interval_seconds: float = DEFAULT_INVENTORY_INTERVAL_SECONDS,
        warm_budget_seconds: float | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] | None = None,
        daily_hour_utc: int = DEFAULT_DAILY_HOUR_UTC,
        full_weekday: int = DEFAULT_FULL_WEEKDAY,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("refresh interval must be positive")
        if inventory_interval_seconds <= 0:
            raise ValueError("inventory refresh interval must be positive")
        if not 0 <= daily_hour_utc <= 23:
            raise ValueError("daily hour must be a valid UTC hour")
        if not 0 <= full_weekday <= 6:
            raise ValueError("full review weekday must be a valid UTC weekday")
        self._explorer = explorer
        self._planner = planner
        self._observed_marker_publisher = observed_marker_publisher
        self._devoluciones_runner = devoluciones_runner
        self._precalculated_warmer = precalculated_warmer
        self._dlq_archiver = dlq_archiver
        self._freshness_alarm_reporter = freshness_alarm_reporter
        self._refresh_failure_reporter = refresh_failure_reporter
        self._interval = interval_seconds
        self._inventory_refresher = inventory_refresher
        self._history_backfill = history_backfill
        self._inventory_interval = inventory_interval_seconds
        # Markers last two intervals and a cycle is followed by one interval of
        # rest, so a cycle must stay under one interval. Warming is the only
        # step whose cost scales with catalog size; give it half an interval.
        self._warm_budget = (
            interval_seconds / 2 if warm_budget_seconds is None else warm_budget_seconds
        )
        if self._warm_budget <= 0:
            raise ValueError("warm budget must be positive")
        self._warm_resume_from: str | None = None
        self._monotonic = monotonic
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
        next_cycle = self._monotonic()
        next_inventory = next_cycle + self._inventory_interval
        while not self._stop_event.is_set():
            broad_cycle = self._monotonic() >= next_cycle
            try:
                if broad_cycle:
                    await self.run_cycle()
                else:
                    await self._run_inventory_cycle()
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
            finished = self._monotonic()
            if broad_cycle:
                # Preserve the full planner's delay after completion. The
                # inventory tick must never accelerate moving range requests.
                next_cycle = finished + self._interval
            next_inventory = finished + self._inventory_interval
            next_wakeup = (
                min(next_cycle, next_inventory)
                if self._inventory_refresher is not None
                else next_cycle
            )
            await self._wait_or_stop(max(0.0, next_wakeup - self._monotonic()))

    async def _run_inventory_cycle(self) -> None:
        if self._inventory_refresher is None:
            return
        for seller_id in await self._explorer.discover_sellers():
            if self._stop_event.is_set():
                break
            try:
                await self._inventory_refresher(seller_id)
            except Exception:  # noqa: BLE001 - isolate each seller's admission
                logger.warning("zelerdata.inventory_refresh_failed", seller_id=seller_id)

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
        started = self._monotonic()
        now = self._now().astimezone(UTC)
        modes = self._due_modes(now)
        sellers = await self._explorer.discover_sellers()
        if self._warm_resume_from in sellers:
            # Resume warming where the last budgeted cycle stopped.
            start = sellers.index(self._warm_resume_from)
            sellers = sellers[start:] + sellers[:start]
        self._warm_resume_from = None
        warm_spent = 0.0
        warm_deferred = 0
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
                    # runner advances an authorized run; with history on link
                    # off it may admit one bounded forward tail of coverage.
                    if await self._devoluciones_runner(seller_id):
                        admitted = True
                except Exception:  # noqa: BLE001 - one model must not stop the loop
                    logger.warning("zelerdata.devoluciones_run_failed", seller_id=seller_id)
            if self._history_backfill is not None:
                try:
                    # Pilot history backfill only enqueues incomplete chunks
                    # through the existing durable recovery queue; it never
                    # calls Mercado Libre or bypasses any lease/capacity guard.
                    if await self._history_backfill(seller_id):
                        admitted = True
                except Exception:  # noqa: BLE001 - one step must not stop the loop
                    logger.warning("zelerdata.history_backfill_failed", seller_id=seller_id)
            if self._precalculated_warmer is not None and warm_spent >= self._warm_budget:
                # Over budget: the seller keeps its other steps, and its cached
                # results fall back to the on-demand path once they expire.
                warm_deferred += 1
                if self._warm_resume_from is None:
                    self._warm_resume_from = seller_id
            elif self._precalculated_warmer is not None:
                warm_started = self._monotonic()
                try:
                    # Q3/Q8/Q16: the heavy aggregate formulas are computed here,
                    # where the refresh already reads the same data, so the sheet
                    # call is a bounded document read instead of a 20s aggregation.
                    if await self._precalculated_warmer(seller_id):
                        admitted = True
                except Exception:  # noqa: BLE001 - one formula must not stop the loop
                    logger.warning("zelerdata.precalculated_warm_failed", seller_id=seller_id)
                warm_spent += self._monotonic() - warm_started
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
            if self._dlq_archiver is not None:
                try:
                    # Q4-b/Q11-c: the queue must not accumulate invisibly again.
                    # The archive rescans the whole DLQ and re-draws every
                    # retained message, so it rides the daily sweep instead of
                    # the 15-minute cycle: automatic, but not broker churn. Only
                    # provably superseded messages are removed, each with a
                    # recorded reason.
                    await self._dlq_archiver()
                except Exception:  # noqa: BLE001 - the loop must not stop for one queue
                    logger.warning("zelerdata.dlq_auto_archive_failed")
        if FULL_MODE in modes:
            self._last_full_date = now.date()
        # Sellers share one recovery budget and run in sequence, so the cycle
        # length is the capacity signal: it must stay well inside the interval.
        logger.info(
            "zelerdata.refresh_cycle_completed",
            sellers=len(sellers),
            warm_deferred=warm_deferred,
            elapsed_seconds=round(self._monotonic() - started, 3),
        )
        self.health_status = "ok"
        self._cycle.set()
        return admitted
