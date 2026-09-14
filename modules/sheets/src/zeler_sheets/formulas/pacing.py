"""Budget-paced Mercado Libre acquisition for the scheduled ZelerData refresh.

The gateway already enforces a hard per-module, per-seller limit. This module
adds a client-side reservation so background acquisition cannot drain the whole
budget and starve interactive formula queries.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import ceil
from typing import Any

# The gateway allows 600 requests/minute per module and seller. Background
# acquisition keeps about 30% of that so a user recalculation still finds room.
GATEWAY_REQUESTS_PER_MINUTE = 600
DEFAULT_RECOVERY_REQUESTS_PER_MINUTE = 180
WINDOW = timedelta(minutes=1)
LANE_ROTATION = ("inventory", "ids", "ids", "ranges")
_quota_deadline: ContextVar[float | None] = ContextVar("recovery_quota_deadline", default=None)


class LocalQuotaTimeoutError(Exception):
    """The local acquisition budget exhausted this job's available time."""


@dataclass
class RecoveryQuotaScope:
    """Per-job quota evidence shared by its nested scopes and child tasks."""

    expired: bool = False


_quota_scope: ContextVar[RecoveryQuotaScope | None] = ContextVar(
    "recovery_quota_scope", default=None
)


@contextmanager
def recovery_quota_deadline(deadline: float) -> Iterator[RecoveryQuotaScope]:
    """Apply a loop-clock deadline only to quota waits within this job."""
    parent = _quota_deadline.get()
    scope = _quota_scope.get() or RecoveryQuotaScope()
    scope_token = _quota_scope.set(scope)
    token = _quota_deadline.set(min(parent, deadline) if parent is not None else deadline)
    try:
        yield scope
    finally:
        _quota_deadline.reset(token)
        _quota_scope.reset(scope_token)


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
    """Shared budget with spaced lane admission and fair pending selection."""

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
        self._spread_requests = False
        self._next_grant_at: datetime | None = None
        self._pending: dict[str, deque[asyncio.Future[bool]]] = {
            lane: deque() for lane in LANE_ROTATION
        }
        self._cursor = 0
        self._driver: asyncio.Task[None] | None = None

    async def acquire(self, lane: str | None = None) -> bool:
        """Reserve a slot fairly among waiting lanes, borrowing unused shares.

        Lane-aware callers spread the budget over time so a producer returning
        from persistence cannot find the whole minute spent in an earlier burst.
        Legacy-only instances retain fixed-window admission. Mixed callers share
        the spaced budget once a lane-aware caller arrives. Only actual waiting
        is reported as backpressure; cancellation joins the last pending timer.
        """
        explicit_lane = lane is not None
        lane = lane or "ids"
        if lane not in self._pending:
            raise ValueError("unknown recovery pacing lane")
        self._spread_requests = self._spread_requests or explicit_lane
        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self._pending[lane].append(future)
        if self._driver is None or self._driver.done():
            self._driver = asyncio.create_task(self._serve())
        try:
            async with asyncio.timeout_at(_quota_deadline.get()):
                return await future
        except TimeoutError as exc:
            scope = _quota_scope.get()
            if scope is not None:
                scope.expired = True
            raise LocalQuotaTimeoutError from exc
        finally:
            if future in self._pending[lane]:
                self._pending[lane].remove(future)
            if not any(self._pending.values()) and self._driver is not None:
                driver = self._driver
                self._driver = None
                if not driver.done():
                    driver.cancel()
                await asyncio.gather(driver, return_exceptions=True)

    async def _serve(self) -> None:
        try:
            while any(self._pending.values()):
                # Let simultaneously ready lanes register before selecting a
                # slot; producers can enqueue their next request after a grant.
                await asyncio.sleep(0)
                waited = await self._wait_for_slot()
                for _ in LANE_ROTATION:
                    lane = LANE_ROTATION[self._cursor]
                    self._cursor = (self._cursor + 1) % len(LANE_ROTATION)
                    queue = self._pending[lane]
                    while queue and queue[0].cancelled():
                        queue.popleft()
                    if queue:
                        future = queue.popleft()
                        self._used += 1
                        # Round upward: datetime microsecond resolution must
                        # not make 180 spaced intervals shorter than a minute.
                        interval = timedelta(
                            microseconds=ceil(WINDOW.total_seconds() * 1_000_000 / self._budget)
                        )
                        self._next_grant_at = self._now().astimezone(UTC) + interval
                        future.set_result(waited)
                        break
        except Exception as exc:  # noqa: BLE001 - propagate timer failure to every waiter
            for queue in self._pending.values():
                while queue:
                    future = queue.popleft()
                    if not future.done():
                        future.set_exception(exc)

    async def _wait_for_slot(self) -> bool:
        now = self._now().astimezone(UTC)
        if self._window_start is None or now - self._window_start >= WINDOW:
            self._window_start = now
            self._used = 0
        exhausted = self._used >= self._budget
        remaining = (
            max(0.0, (self._window_start + WINDOW - now).total_seconds()) if exhausted else 0.0
        )
        if self._spread_requests and self._next_grant_at is not None:
            remaining = max(remaining, (self._next_grant_at - now).total_seconds())
        if remaining > 0:
            await self._sleep(remaining)
        now = self._now().astimezone(UTC)
        if exhausted or now - self._window_start >= WINDOW:
            self._window_start = now
            self._used = 0
        return remaining > 0


class PacedMeliGateway:
    """Wrap a gateway client so every acquisition call respects the budget."""

    def __init__(self, *, inner: Any, pacer: RecoveryRequestPacer, lane: str | None = None) -> None:
        self._inner = inner
        self._pacer = pacer
        self._lane = lane

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def _call(self, method: str, kwargs: dict[str, Any]) -> Any:
        timeout = kwargs.pop("request_timeout", 10 if self._lane is not None else None)
        await self._pacer.acquire(lane=self._lane)
        async with asyncio.timeout(timeout):
            return await getattr(self._inner, method)(**kwargs)

    async def request(self, **kwargs: Any) -> Any:
        return await self._call("request", kwargs)

    async def fetch_resource(self, **kwargs: Any) -> Any:
        return await self._call("fetch_resource", kwargs)

    async def fetch_resource_once(self, **kwargs: Any) -> Any:
        return await self._call("fetch_resource_once", kwargs)


async def recovery_fetch_resource(
    gateway: Any, *, request_timeout: float = 5, **kwargs: Any
) -> Any:
    """Bound provider time while excluding a paced client's local quota wait."""
    if isinstance(gateway, PacedMeliGateway):
        return await gateway.fetch_resource(request_timeout=request_timeout, **kwargs)
    async with asyncio.timeout(request_timeout):
        return await gateway.fetch_resource(**kwargs)


async def recovery_request(gateway: Any, *, request_timeout: float = 5, **kwargs: Any) -> Any:
    """Bound an HTTP response request after any shared quota reservation."""
    if isinstance(gateway, PacedMeliGateway):
        return await gateway.request(request_timeout=request_timeout, **kwargs)
    async with asyncio.timeout(request_timeout):
        return await gateway.request(**kwargs)
