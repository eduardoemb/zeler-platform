"""Generic delivery gates in front of the completed-event marker.

Extracted from the Sheets consumer (S3a) so every module shares one delivery
gate: ``LegacyEventGate`` is the non-concurrent check-then-act fallback used by
unit doubles, and ``EventClaimGate`` composes the atomic ``EventClaimStore``
lease so two concurrent deliveries of one idempotency key cannot both run the
external side effects. ``EventClaimTimeoutError`` is the retryable signal a
busy lease raises so the broker path can requeue the delivery.
"""

from __future__ import annotations

from typing import Protocol
from uuid import uuid4

from zeler_platform_core.events.claims import ClaimOutcome

__all__ = [
    "ClaimHandle",
    "EventClaimGate",
    "EventClaimStoreLike",
    "EventClaimTimeoutError",
    "EventGate",
    "LegacyEventGate",
    "ModuleIdempotencyStore",
]


class EventClaimTimeoutError(Exception):
    """Raised when the event claim lease stays busy past its retry window."""


class ModuleIdempotencyStore(Protocol):
    """The module idempotency-adapter shape ``LegacyEventGate`` wraps.

    This is the scoped-adapter shape (``is_duplicate(key)`` /
    ``mark_processed(key)``), not the core ``IdempotencyStore``.
    """

    async def is_duplicate(self, key: str) -> bool: ...

    async def mark_processed(self, key: str) -> None: ...


class ClaimHandle(Protocol):
    """A claimed delivery: complete on terminal outcomes, release otherwise."""

    async def complete(self) -> bool: ...

    async def release(self) -> bool: ...


class EventGate(Protocol):
    """One exclusive claim per delivery key; ``None`` means already done."""

    async def claim(self, key: str) -> ClaimHandle | None: ...


class _LegacyClaimHandle:
    def __init__(self, store: ModuleIdempotencyStore, key: str) -> None:
        self._store = store
        self._key = key

    async def complete(self) -> bool:
        await self._store.mark_processed(self._key)
        return True

    async def release(self) -> bool:
        return False


class LegacyEventGate:
    """Non-concurrent check-then-act fallback used by unit doubles.

    Duplicates are suppressed only by the completed marker, which is not
    atomic under concurrent deliveries. In production wiring the wrapped store
    is the module's idempotency adapter; a real worker must receive an
    ``EventClaimStore`` instead (the ``EventClaimGate``).
    """

    def __init__(self, store: ModuleIdempotencyStore) -> None:
        self._store = store

    async def claim(self, key: str) -> ClaimHandle | None:
        if await self._store.is_duplicate(key):
            return None
        return _LegacyClaimHandle(self._store, key)


class _EventClaimHandle:
    def __init__(
        self,
        store: EventClaimStoreLike,
        key: str,
        *,
        module_id: str,
        consumer_id: str,
        owner_token: str,
    ) -> None:
        self._store = store
        self._key = key
        self._module_id = module_id
        self._consumer_id = consumer_id
        self._owner_token = owner_token

    async def complete(self) -> bool:
        return await self._store.complete(
            self._key,
            module_id=self._module_id,
            consumer_id=self._consumer_id,
            owner_token=self._owner_token,
        )

    async def release(self) -> bool:
        return await self._store.release(
            self._key,
            module_id=self._module_id,
            consumer_id=self._consumer_id,
            owner_token=self._owner_token,
        )


class EventClaimStoreLike(Protocol):
    """Lease surface ``EventClaimGate`` needs, so any store double fits."""

    async def claim(
        self,
        idempotency_key: str,
        *,
        module_id: str,
        consumer_id: str | None = None,
        owner_token: str,
    ) -> ClaimOutcome: ...

    async def complete(
        self,
        idempotency_key: str,
        *,
        module_id: str,
        consumer_id: str | None = None,
        owner_token: str,
    ) -> bool: ...

    async def release(
        self,
        idempotency_key: str,
        *,
        module_id: str,
        consumer_id: str | None = None,
        owner_token: str,
    ) -> bool: ...


class EventClaimGate:
    """Exclusive-lease gate over ``EventClaimStore``.

    ``claim`` returns a handle only for ``CLAIMED``. ``COMPLETED`` means a
    previous delivery already ran the side effects (the caller skips), and a
    lease that stays busy past the wait window raises the retryable
    ``EventClaimTimeoutError`` so the broker path can requeue the delivery.
    """

    def __init__(self, store: EventClaimStoreLike, *, module_id: str, consumer_id: str) -> None:
        self._store = store
        self._module_id = module_id
        self._consumer_id = consumer_id

    async def claim(self, key: str) -> ClaimHandle | None:
        owner_token = uuid4().hex
        outcome = await self._store.claim(
            key,
            module_id=self._module_id,
            consumer_id=self._consumer_id,
            owner_token=owner_token,
        )
        if outcome is ClaimOutcome.CLAIMED:
            return _EventClaimHandle(
                self._store,
                key,
                module_id=self._module_id,
                consumer_id=self._consumer_id,
                owner_token=owner_token,
            )
        if outcome is ClaimOutcome.COMPLETED:
            return None
        raise EventClaimTimeoutError("event claim lease stayed busy; retry the delivery later")
