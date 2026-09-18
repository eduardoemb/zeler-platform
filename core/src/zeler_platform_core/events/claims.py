"""Atomic event claim leases guarding the completed-event marker.

Design D2 of the atomic-event-claim-lease feature: ``processed_events`` keeps
meaning **completed**, and a separate short-lived ``processed_event_claims``
collection is the exclusive lease per scoped idempotency key. ``claim`` uses a
single atomic ``find_one_and_update`` upsert so two concurrent deliveries of
one key cannot both run external side effects; ``complete`` writes the completed
marker while the claim is still live (so a concurrent claimant collides on
acquire and observes the marker) and then releases the lease, fencing a stalled
owner out via the ownership check.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from math import ceil
from typing import Any, Protocol

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError

from zeler_platform_core.events.idempotency import (
    IdempotencyStore,
    scoped_processed_event_id,
)

__all__ = ["ClaimOutcome", "EventClaimStore"]


class ClaimOutcome(StrEnum):
    """Outcome of a claim attempt; the internal busy state is never returned."""

    CLAIMED = "claimed"
    COMPLETED = "completed"
    TIMED_OUT = "timed_out"


class ProcessedEventClaimsCollection(Protocol):
    """The exact claim-collection surface ``EventClaimStore`` uses."""

    async def find_one_and_update(
        self,
        filter_spec: dict[str, Any],
        update: dict[str, Any],
        *,
        upsert: bool,
        return_document: bool,
    ) -> dict[str, Any] | None: ...

    async def find_one(self, filter_spec: dict[str, Any]) -> dict[str, Any] | None: ...

    async def delete_one(self, filter_spec: dict[str, Any]) -> Any: ...


class EventClaimStore:
    """Exclusive short-lived lease per scoped idempotency key.

    The lease identity reuses ``scoped_processed_event_id`` so a claim and its
    completed marker share one scoped key. All time comes from ``now_fn`` so
    tests can advance a fake clock without sleeping.
    """

    def __init__(
        self,
        claims: ProcessedEventClaimsCollection,
        completed: IdempotencyStore,
        *,
        lease: timedelta = timedelta(seconds=120),
        wait: timedelta = timedelta(seconds=30),
        poll: timedelta = timedelta(milliseconds=250),
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._claims = claims
        self._completed = completed
        self._lease = lease
        self._wait = wait
        self._poll = poll
        self._now_fn = now_fn or (lambda: datetime.now(UTC))

    async def claim(
        self,
        idempotency_key: str,
        *,
        module_id: str,
        consumer_id: str | None = None,
        owner_token: str,
        lease: timedelta | None = None,
        wait: timedelta | None = None,
    ) -> ClaimOutcome:
        effective_lease = self._lease if lease is None else lease
        effective_wait = self._wait if wait is None else wait
        deadline = self._now_fn() + effective_wait
        # Deterministic attempt budget: a frozen injected clock never reaches
        # the deadline, so the poll loop must also stop after a bounded number
        # of attempts to keep misbehaving tests failing instead of hanging.
        if self._poll > timedelta(0):
            max_attempts = max(1, ceil(effective_wait / self._poll)) + 1
        else:
            max_attempts = 1
        attempts = 0
        while True:
            if await self._completed.is_duplicate(
                idempotency_key, module_id=module_id, consumer_id=consumer_id
            ):
                return ClaimOutcome.COMPLETED
            collided = not await self._acquire(
                idempotency_key,
                module_id=module_id,
                consumer_id=consumer_id,
                owner_token=owner_token,
                lease=effective_lease,
            )
            if await self._completed.is_duplicate(
                idempotency_key, module_id=module_id, consumer_id=consumer_id
            ):
                # Another owner completed between the two checks: drop the
                # lease this call just acquired and report completion.
                await self.release(
                    idempotency_key,
                    module_id=module_id,
                    consumer_id=consumer_id,
                    owner_token=owner_token,
                )
                return ClaimOutcome.COMPLETED
            if not collided:
                return ClaimOutcome.CLAIMED
            attempts += 1
            if attempts >= max_attempts or self._now_fn() >= deadline:
                return ClaimOutcome.TIMED_OUT
            await asyncio.sleep(self._poll.total_seconds())

    async def complete(
        self,
        idempotency_key: str,
        *,
        module_id: str,
        consumer_id: str | None = None,
        owner_token: str,
    ) -> bool:
        existing = await self._claims.find_one(
            self._owned_claim_filter(
                idempotency_key,
                module_id=module_id,
                consumer_id=consumer_id,
                owner_token=owner_token,
            )
        )
        if existing is None:
            # The lease was lost, so a stalled owner must not write the marker.
            return False
        # Marker-before-delete: the claim stays live while the marker writes so
        # any concurrent claimant collides on acquire and then observes the
        # completed marker instead of re-running the side effects. The delete
        # below is best-effort cleanup: a crash or failure here leaves the
        # claim to the TTL index while the marker already suppresses
        # duplicates. Do not reorder these two writes.
        marked = await self._completed.mark_processed(
            idempotency_key, module_id=module_id, consumer_id=consumer_id
        )
        with suppress(PyMongoError):
            # Best-effort cleanup only: the completed marker is already
            # written, so the delivery is complete and duplicates are
            # suppressed. A Mongo failure here must not fail the delivery; the
            # orphaned claim is left to the TTL index. Deliberately narrow: a
            # non-Mongo error still escapes so real defects stay visible.
            await self._claims.delete_one(
                self._owned_claim_filter(
                    idempotency_key,
                    module_id=module_id,
                    consumer_id=consumer_id,
                    owner_token=owner_token,
                )
            )
        return marked

    async def release(
        self,
        idempotency_key: str,
        *,
        module_id: str,
        consumer_id: str | None = None,
        owner_token: str,
    ) -> bool:
        removal = await self._claims.delete_one(
            self._owned_claim_filter(
                idempotency_key,
                module_id=module_id,
                consumer_id=consumer_id,
                owner_token=owner_token,
            )
        )
        return bool(removal.deleted_count)

    async def _acquire(
        self,
        idempotency_key: str,
        *,
        module_id: str,
        consumer_id: str | None,
        owner_token: str,
        lease: timedelta,
    ) -> bool:
        now = self._now_fn()
        scope_id = consumer_id or module_id
        try:
            await self._claims.find_one_and_update(
                {
                    "_id": scoped_processed_event_id(idempotency_key, scope_id),
                    "expires_at": {"$lte": now},
                },
                {
                    "$set": {
                        "idempotency_key": idempotency_key,
                        "module_id": module_id,
                        "consumer_id": scope_id,
                        "owner_token": owner_token,
                        "claimed_at": now,
                        "expires_at": now + lease,
                    }
                },
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError:
            # A live (unexpired) lease does not match the filter, so the upsert
            # collides on the scoped _id: another owner still holds the lease.
            return False
        return True

    @staticmethod
    def _owned_claim_filter(
        idempotency_key: str,
        *,
        module_id: str,
        consumer_id: str | None,
        owner_token: str,
    ) -> dict[str, Any]:
        scope_id = consumer_id or module_id
        return {
            "_id": scoped_processed_event_id(idempotency_key, scope_id),
            "owner_token": owner_token,
        }
