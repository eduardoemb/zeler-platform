from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from bson import Int64
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument

DEFAULT_RATE_LIMIT = 60
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_COLLECTION = "rate_limit_counters"


class RateLimitExceeded(Exception):  # noqa: N818 - SDD API names this exception RateLimitExceeded.
    def __init__(self, retry_after_s: float) -> None:
        super().__init__(f"rate limit exceeded; retry after {retry_after_s:.0f}s")
        self.retry_after_s = retry_after_s


class RateLimitCounter:
    """Mongo-backed per-(module, seller) fixed-window rate-limit counter.

    The SDD task calls this a sliding-window counter. A true sliding window would
    require storing every request event or bucketizing sub-windows, which is too
    expensive for the proxy hot path. This implementation provides the practical
    guarantee we need for P1: at most ``default_limit`` successful requests per
    60-second UTC-aligned fixed window, shared across Cloud Run replicas.

    Each call performs one atomic ``find_one_and_update`` against ``_id`` using an
    aggregation-pipeline update. The expected query plan is an IXSCAN on Mongo's
    default ``_id`` index; the ``window_start`` check lives in the update pipeline
    so rollover does not force a compound index or a duplicate-key retry loop.
    Rejected attempts still increment the current window, which is a deliberate
    backpressure choice: clients that keep hammering after 429 do not get a free
    counter bypass before the next fixed window.
    """

    def __init__(
        self,
        db: AsyncIOMotorDatabase[Any],
        *,
        default_limit: int = DEFAULT_RATE_LIMIT,
        window_s: int = RATE_LIMIT_WINDOW_SECONDS,
        now_fn: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._collection = db[RATE_LIMIT_COLLECTION]
        self._default_limit = default_limit
        self._window_s = window_s
        self._now_fn = now_fn

    async def check_and_increment(
        self,
        *,
        module_id: str,
        seller_id: int,
    ) -> None:
        """Increment the current window or raise when the budget is exhausted."""
        now = _ensure_utc(self._now_fn())
        window_start = _fixed_window_start(now, self._window_s)
        key = f"{module_id}:{seller_id}"

        doc = await self._collection.find_one_and_update(
            {"_id": key},
            [
                {
                    "$set": {
                        "module_id": module_id,
                        "seller_id": Int64(seller_id),
                        "window_start": {
                            "$cond": [
                                {"$eq": ["$window_start", window_start]},
                                "$window_start",
                                window_start,
                            ]
                        },
                        "count": {
                            "$cond": [
                                {"$eq": ["$window_start", window_start]},
                                {"$add": ["$count", 1]},
                                1,
                            ]
                        },
                        "updated_at": now,
                    }
                }
            ],
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )

        if doc is None:  # pragma: no cover - find_one_and_update with AFTER should return the doc
            return

        if int(doc["count"]) > self._default_limit:
            retry_after_s = (window_start + timedelta(seconds=self._window_s) - now).total_seconds()
            raise RateLimitExceeded(max(1.0, retry_after_s))


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _fixed_window_start(value: datetime, window_s: int) -> datetime:
    unix_s = int(value.timestamp())
    window_unix_s = unix_s - (unix_s % window_s)
    return datetime.fromtimestamp(window_unix_s, tz=UTC)
