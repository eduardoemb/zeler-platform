from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

SCHEMA_VERSION = 1
COUNTER_COLLECTION = "rate_limit_counters"


class FormulaRateLimitService:
    def __init__(
        self,
        *,
        db: Any,
        max_requests: int,
        window_seconds: int,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        if max_requests < 1:
            raise ValueError("max_requests must be positive")
        if window_seconds < 1:
            raise ValueError("window_seconds must be positive")
        self._collection = db[COUNTER_COLLECTION]
        self._max_requests = max_requests
        self._window = timedelta(seconds=window_seconds)
        self._window_seconds = window_seconds
        self._now = now_fn or (lambda: datetime.now(UTC))

    async def allow(self, context: dict[str, Any]) -> bool:
        now = self._now()
        window_start = _window_start(now, self._window_seconds)
        counter_id = _counter_id(context, window_start)
        existing = await self._collection.find_one({"_id": counter_id})
        if existing is not None and int(existing.get("count", 0)) >= self._max_requests:
            return False

        count = int(existing.get("count", 0)) + 1 if existing else 1
        doc = {
            "_id": counter_id,
            "scope": "sheets_formula",
            "token_id": str(context["token_id"]),
            "seller_id": str(context["seller_id"]),
            "seller_nickname": context.get("seller_nickname"),
            "formula": str(context["formula"]),
            "count": count,
            "window_start": window_start,
            "window_end": window_start + self._window,
            "updated_at": now,
            "schema_version": SCHEMA_VERSION,
        }
        await self._collection.replace_one({"_id": counter_id}, doc, upsert=True)
        return True


def _window_start(now: datetime, window_seconds: int) -> datetime:
    timestamp = int(now.timestamp())
    bucket = timestamp - (timestamp % window_seconds)
    return datetime.fromtimestamp(bucket, tz=UTC)


def _counter_id(context: dict[str, Any], window_start: datetime) -> str:
    return ":".join(
        [
            "sheets-formula",
            str(context["token_id"]),
            str(context["seller_id"]),
            str(context["formula"]),
            str(int(window_start.timestamp())),
        ]
    )
