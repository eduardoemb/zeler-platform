"""Neutral modification-page admission; never advances a source watermark or coverage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

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
