"""Paced, opt-in modification traversal for pilot seller order projections."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from zeler_platform_core.clients.meli_gateway_client import GatewayRateLimitError
from zeler_sheets.formulas.pacing import LocalQuotaTimeoutError
from zeler_sheets.history_acquisition import HistoryLimitError
from zeler_sheets.modification_recovery import (
    ModificationEnumerationDriftError,
    fetch_modification_page,
)
from zeler_sheets.modification_scan_store import (
    ModificationScan,
    ModificationScanBlockedError,
    ModificationScanStore,
)

logger = logging.getLogger(__name__)


class ModificationScanWorker:
    def __init__(
        self,
        store: ModificationScanStore,
        gateway: Any,
        *,
        sellers: frozenset[str],
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not sellers or any(not seller.isascii() or not seller.isdecimal() for seller in sellers):
            raise ValueError("modification worker requires explicit numeric sellers")
        self.store = store
        self.gateway = gateway
        self.sellers = tuple(sorted(sellers))
        self.now = now
        self._next_seller = 0

    async def process_once(self) -> str:
        seller = self.sellers[self._next_seller]
        self._next_seller = (self._next_seller + 1) % len(self.sellers)
        scan: ModificationScan | None = None
        try:
            scan = await self.store.begin(seller, cutoff=self.now())
            if scan.phase in {"completed", "failed"}:
                return "idle"
            page = await fetch_modification_page(
                self.gateway,
                seller_id=seller,
                watermark=scan.watermark,
                cutoff=scan.cutoff,
                offset=scan.next_offset,
                expected_total=scan.source_total,
            )
            updated = await self.store.advance(scan, page)
            return "processed" if updated != scan else "idle"
        except ModificationEnumerationDriftError:
            if scan is None:
                return "idle"
            updated = await self.store.restart(scan)
            if updated.phase == "failed":
                logger.error(
                    "modification scan exhausted source drift budget for seller %s", seller
                )
            return "processed"
        except (ModificationScanBlockedError, HistoryLimitError, ValueError):
            logger.error("modification scan blocked for seller %s", seller)
            return "idle"
        except (httpx.HTTPError, GatewayRateLimitError, LocalQuotaTimeoutError, TimeoutError):
            logger.warning("modification source temporarily unavailable for seller %s", seller)
            return "idle"
