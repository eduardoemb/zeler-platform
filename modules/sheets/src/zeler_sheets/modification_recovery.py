"""Neutral modification-page admission; never advances a source watermark or coverage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from urllib.parse import urlencode

from bson import BSON
from bson.errors import BSONError
from pymongo.errors import PyMongoError

from zeler_sheets.formulas.recovery import (
    FormulaRecoveryQueue,
    ModifiedOrderIdsRecoveryRequest,
    RecoveryCapacityError,
)
from zeler_sheets.history_acquisition import _safe
from zeler_sheets.item_projection import item_source_fingerprint


@dataclass(frozen=True)
class ModificationPage:
    seller_id: str
    watermark: datetime
    cutoff: datetime
    rows: list[dict[str, Any]]


@dataclass(frozen=True)
class ModificationAdmission:
    """Accepted keys include existing/failed jobs, not new insertions or successful recovery."""

    seller_id: str
    accepted_keys: tuple[str, ...]
    state: Literal["admitted", "deferred", "failed"]
    reason: str | None = None


class ModificationEnumerationDriftError(ValueError):
    """A source page cannot safely advance a modification traversal."""


@dataclass(frozen=True)
class ModificationSearchPage:
    page: ModificationPage
    source_total: int
    next_offset: int | None


async def fetch_modification_page(
    gateway: Any,
    *,
    seller_id: str,
    watermark: datetime,
    cutoff: datetime,
    offset: int = 0,
    expected_total: int | None = None,
) -> ModificationSearchPage:
    """Fetch one bounded provider page without advancing any durable cursor.

    Mercado Libre's date filters resolve to hours. The caller retains the exact
    half-open interval, and ``admit_modifications`` filters boundary-hour rows.
    A later traversal owner must persist admission and cursor progress together.
    """
    if not isinstance(seller_id, str) or not seller_id.isascii() or not seller_id.isdecimal():
        raise ValueError("modification seller is invalid")
    if type(offset) is not int or offset < 0:
        raise ValueError("modification offset must be non-negative")
    if expected_total is not None and (type(expected_total) is not int or expected_total < 0):
        raise ValueError("modification expected total is invalid")
    start, end = modification_window(watermark, cutoff)
    first_hour = start.replace(minute=0, second=0, microsecond=0)
    last_hour = end.replace(minute=0, second=0, microsecond=0)
    if end == last_hour:
        last_hour -= timedelta(hours=1)
    params = {
        "seller": seller_id,
        "order.date_last_updated.from": first_hour.isoformat(timespec="milliseconds"),
        "order.date_last_updated.to": last_hour.isoformat(timespec="milliseconds"),
        "sort": "date_asc",
        "offset": str(offset),
        "limit": "50",
    }
    raw = await gateway.fetch_resource(
        seller_id=seller_id, path="/orders/search?" + urlencode(params)
    )
    if not isinstance(raw, dict) or not isinstance(raw.get("paging"), dict):
        raise ModificationEnumerationDriftError("modification page lacks pagination")
    paging, rows = raw["paging"], raw.get("results")
    total = paging.get("total")
    if (
        type(total) is not int
        or total < 0
        or type(paging.get("offset")) is not int
        or paging.get("offset") != offset
        or type(paging.get("limit")) is not int
        or paging.get("limit") != 50
        or not isinstance(rows, list)
        or len(rows) > 50
        or offset + len(rows) > total
        or (not rows and offset != total)
        or (expected_total is not None and total != expected_total)
    ):
        raise ModificationEnumerationDriftError("modification pagination changed")
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ModificationEnumerationDriftError("modification row is not an object")
        identity = str(row.get("id", ""))
        seller = row.get("seller")
        try:
            raw_modified = row["date_last_updated"]
            modified = datetime.fromisoformat(raw_modified.replace("Z", "+00:00"))
        except (KeyError, AttributeError, TypeError, ValueError):
            raise ModificationEnumerationDriftError("modification timestamp is invalid") from None
        if (
            not identity.isascii()
            or not identity.isdecimal()
            or identity in seen
            or not isinstance(seller, dict)
            or str(seller.get("id")) != seller_id
            or modified.tzinfo is None
            or not first_hour <= modified.astimezone(UTC) < last_hour + timedelta(hours=1)
        ):
            raise ModificationEnumerationDriftError("modification row contradicts query scope")
        seen.add(identity)
    next_offset = offset + len(rows)
    return ModificationSearchPage(
        ModificationPage(seller_id, watermark, cutoff, rows),
        total,
        None if next_offset == total else next_offset,
    )


def modification_window(watermark: datetime, cutoff: datetime) -> tuple[datetime, datetime]:
    if (
        not isinstance(watermark, datetime)
        or not isinstance(cutoff, datetime)
        or watermark.tzinfo is None
        or cutoff.tzinfo is None
        or cutoff < watermark
    ):
        raise ValueError("modification window requires ordered aware instants")
    return watermark.astimezone(UTC) - timedelta(hours=24), cutoff.astimezone(UTC)


async def admit_modifications(
    queue: FormulaRecoveryQueue, pages: list[ModificationPage]
) -> tuple[ModificationAdmission, ...]:
    """Isolate each supplied seller page; callers retain cursors until separately verified."""
    outcomes = []
    for page in pages:
        accepted: dict[str, None] = {}
        state: Literal["admitted", "deferred", "failed"] = "admitted"
        reason = None
        try:
            if queue.allowed_sellers is not None and page.seller_id not in queue.allowed_sellers:
                raise ValueError("modification seller is not enabled")
            if (
                "orders" not in queue.enabled_models
                or not page.seller_id.isascii()
                or not page.seller_id.isdecimal()
            ):
                raise ValueError("modification source or seller is invalid")
            start, end = modification_window(page.watermark, page.cutoff)
            if len(page.rows) > 50:
                raise ValueError("modification page exceeds local record budget")
            for row in page.rows:
                _safe(row)
                if len(BSON.encode(row)) > 1024 * 1024:
                    raise ValueError("modification observation exceeds local byte budget")
                seller = row.get("seller")
                modified = datetime.fromisoformat(
                    str(row.get("date_last_updated", "")).replace("Z", "+00:00")
                )
                if (
                    not isinstance(seller, dict)
                    or str(seller.get("id")) != page.seller_id
                    or modified.tzinfo is None
                ):
                    raise ValueError("modification observation scope is invalid")
                if not start <= modified < end:
                    continue
                request = ModifiedOrderIdsRecoveryRequest(
                    page.seller_id,
                    (str(row.get("id", "")),),
                    modified_version=modified.isoformat(),
                    source_hash=item_source_fingerprint(row),
                )
                accepted[await queue.enqueue(request, reopen_terminal=False)] = None
        except RecoveryCapacityError:
            state, reason = "deferred", "capacity"
        except PyMongoError:
            state, reason = "failed", "storage_unavailable"
        except (ValueError, TypeError, OverflowError, BSONError):
            state, reason = "failed", "invalid_observation_or_scope"
        outcomes.append(ModificationAdmission(page.seller_id, tuple(accepted), state, reason))
    return tuple(outcomes)
