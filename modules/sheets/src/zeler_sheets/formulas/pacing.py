"""Budget-paced Mercado Libre acquisition for the scheduled ZelerData refresh.

The gateway already enforces a hard per-module, per-seller limit. This module
adds a client-side reservation so background acquisition cannot drain the whole
budget and starve interactive formula queries.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

# The gateway allows 600 requests/minute per module and seller. Background
# acquisition keeps about 30% of that so a user recalculation still finds room.
GATEWAY_REQUESTS_PER_MINUTE = 600
DEFAULT_RECOVERY_REQUESTS_PER_MINUTE = 180
WINDOW = timedelta(minutes=1)


def recovery_requests_per_minute(value: str | None) -> int:
    """Resolve the reserved acquisition budget from runtime configuration."""
    if value is None or not value.strip():
        return DEFAULT_RECOVERY_REQUESTS_PER_MINUTE
    try:
        budget = int(value.strip())
    except ValueError as exc:
        raise ValueError("recovery budget must be an integer") from exc
    if not 1 <= budget <= GATEWAY_REQUESTS_PER_MINUTE:
        raise ValueError("recovery budget must fit inside the gateway limit")
    return budget


class RecoveryRequestPacer:
    """Fixed-window client-side limiter for background acquisition."""

    def __init__(
        self,
        *,
        requests_per_minute: int = DEFAULT_RECOVERY_REQUESTS_PER_MINUTE,
        now: Callable[[], datetime] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        if not 1 <= requests_per_minute <= GATEWAY_REQUESTS_PER_MINUTE:
            raise ValueError("recovery budget must fit inside the gateway limit")
        self._budget = requests_per_minute
        self._now = now or (lambda: datetime.now(UTC))
        self._sleep = sleep or asyncio.sleep
        self._window_start: datetime | None = None
        self._used = 0
        self._lock = asyncio.Lock()

    async def acquire(self) -> bool:
        """Consume one slot; wait once when the current window is exhausted.

        Returns ``True`` only when the caller actually had to wait, so a window
        that already rolled over on its own is not reported as backpressure.
        """
        async with self._lock:
            if self._window_start is None:
                self._window_start = self._now().astimezone(UTC)
                self._used = 0
            waited = False
            if self._used >= self._budget:
                waited = await self._roll_window()
            self._used += 1
            return waited

    async def _roll_window(self) -> bool:
        now = self._now().astimezone(UTC)
        start = self._window_start or now
        elapsed = (now - start).total_seconds()
        remaining = max(0.0, WINDOW.total_seconds() - elapsed)
        if remaining > 0:
            await self._sleep(remaining)
        self._window_start = self._now().astimezone(UTC)
        self._used = 0
        return remaining > 0


class PacedMeliGateway:
    """Wrap a gateway client so every acquisition call respects the budget."""

    def __init__(self, *, inner: Any, pacer: RecoveryRequestPacer) -> None:
        self._inner = inner
        self._pacer = pacer

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def request(self, **kwargs: Any) -> Any:
        await self._pacer.acquire()
        return await self._inner.request(**kwargs)

    async def fetch_resource(self, **kwargs: Any) -> Any:
        await self._pacer.acquire()
        return await self._inner.fetch_resource(**kwargs)
