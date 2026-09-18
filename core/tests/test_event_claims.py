"""Contract tests for the atomic event claim lease primitive (S1).

The atomic-collision cases run against the disposable loopback Mongo replica
set on port 27028 (see ``docs/lessons/README.md`` L-012). The completed-marker
side runs against the same instance so every store interaction is exercised
the way production runs it; only the deliberate race-window hook below wraps a
collection to make a concurrent completion deterministic.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

import pytest
import pytest_asyncio
from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import PyMongoError

from zeler_platform_core.events.claims import (
    ClaimOutcome,
    EventClaimStore,
    ProcessedEventClaimsCollection,
)
from zeler_platform_core.events.idempotency import (
    IdempotencyStore,
    ProcessedEventsCollection,
    scoped_processed_event_id,
)

CLAIMS_COLLECTION = "processed_event_claims"
COMPLETED_COLLECTION = "processed_events"
LOOPBACK_URI = "mongodb://127.0.0.1:27028/{name}?directConnection=true"
KEY = "items:/items/MLA1:notif-1"
OWNER_A = "owner-a"
OWNER_B = "owner-b"


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now = self.now + delta


class MarkerLandsDuringFirstProbe:
    """Completed collection that lands a marker while the first probe misses.

    The first ``is_duplicate`` read sees nothing, but the marker is already
    visible to every later read. That models another owner completing between
    the duplicate check and the lease acquire, deterministically.
    """

    def __init__(self, inner: ProcessedEventsCollection, marker: dict[str, Any]) -> None:
        self._inner = inner
        self._marker = marker
        self.probes = 0

    async def find_one(self, filter_spec: dict[str, Any]) -> dict[str, Any] | None:
        self.probes += 1
        if self.probes == 1:
            await self._inner.insert_one(self._marker)
            return None
        return await self._inner.find_one(filter_spec)

    async def insert_one(self, document: dict[str, Any]) -> Any:
        return await self._inner.insert_one(document)


@pytest_asyncio.fixture
async def claims_db() -> AsyncIterator[AsyncDatabase[dict[str, Any]]]:
    name = f"zeler_event_claims_{uuid4().hex}"
    client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(
        LOOPBACK_URI.format(name=name),
        serverSelectionTimeoutMS=2000,
        tz_aware=True,
    )
    try:
        try:
            hello = await client.admin.command("hello")
        except PyMongoError:
            pytest.skip("disposable loopback Mongo on port 27028 is unavailable")
        assert hello["isWritablePrimary"] and hello["setName"] == "rs0"
        yield client[name]
    finally:
        await client.drop_database(name)
        await client.close()


def completed_store(db: AsyncDatabase[dict[str, Any]], clock: FakeClock) -> IdempotencyStore:
    return IdempotencyStore(cast(Any, db[COMPLETED_COLLECTION]), now_fn=clock)


def claim_store(
    db: AsyncDatabase[dict[str, Any]],
    clock: FakeClock,
    completed: IdempotencyStore,
    *,
    lease: timedelta = timedelta(seconds=120),
    wait: timedelta = timedelta(seconds=30),
    poll: timedelta = timedelta(milliseconds=250),
) -> EventClaimStore:
    return EventClaimStore(
        cast(Any, db[CLAIMS_COLLECTION]),
        completed,
        lease=lease,
        wait=wait,
        poll=poll,
        now_fn=clock,
    )


def completed_marker(clock: FakeClock, key: str, module_id: str) -> dict[str, Any]:
    now = clock()
    return {
        "_id": scoped_processed_event_id(key, module_id),
        "idempotency_key": key,
        "module_id": module_id,
        "consumer_id": module_id,
        "processed_at": now,
        "expires_at": now + timedelta(hours=48),
        "schema_version": 2,
    }


@pytest.mark.asyncio
async def test_first_claim_writes_one_scoped_live_lease(
    claims_db: AsyncDatabase[dict[str, Any]],
) -> None:
    clock = FakeClock()
    store = claim_store(claims_db, clock, completed_store(claims_db, clock))

    outcome = await store.claim(KEY, module_id="sheets", owner_token=OWNER_A)

    assert outcome is ClaimOutcome.CLAIMED
    claims = claims_db[CLAIMS_COLLECTION]
    assert await claims.count_documents({}) == 1
    stored = await claims.find_one({"_id": scoped_processed_event_id(KEY, "sheets")})
    assert stored is not None
    assert stored["owner_token"] == OWNER_A
    assert stored["expires_at"] > clock.now


@pytest.mark.asyncio
async def test_second_owner_times_out_while_lease_is_live(
    claims_db: AsyncDatabase[dict[str, Any]],
) -> None:
    clock = FakeClock()
    store = claim_store(claims_db, clock, completed_store(claims_db, clock))
    await store.claim(KEY, module_id="sheets", owner_token=OWNER_A)

    outcome = await store.claim(KEY, module_id="sheets", owner_token=OWNER_B, wait=timedelta(0))

    assert outcome is ClaimOutcome.TIMED_OUT
    stored = await claims_db[CLAIMS_COLLECTION].find_one(
        {"_id": scoped_processed_event_id(KEY, "sheets")}
    )
    assert stored is not None
    assert stored["owner_token"] == OWNER_A


@pytest.mark.asyncio
async def test_expired_lease_is_reclaimed_by_next_owner(
    claims_db: AsyncDatabase[dict[str, Any]],
) -> None:
    clock = FakeClock()
    store = claim_store(claims_db, clock, completed_store(claims_db, clock))
    await store.claim(KEY, module_id="sheets", owner_token=OWNER_A)

    clock.advance(timedelta(seconds=121))
    outcome = await store.claim(KEY, module_id="sheets", owner_token=OWNER_B)

    assert outcome is ClaimOutcome.CLAIMED
    stored = await claims_db[CLAIMS_COLLECTION].find_one(
        {"_id": scoped_processed_event_id(KEY, "sheets")}
    )
    assert stored is not None
    assert stored["owner_token"] == OWNER_B


@pytest.mark.asyncio
async def test_concurrent_claims_produce_exactly_one_claimed(
    claims_db: AsyncDatabase[dict[str, Any]],
) -> None:
    clock = FakeClock()
    store = claim_store(claims_db, clock, completed_store(claims_db, clock))

    outcomes = await asyncio.gather(
        store.claim(KEY, module_id="sheets", owner_token=OWNER_A, wait=timedelta(0)),
        store.claim(KEY, module_id="sheets", owner_token=OWNER_B, wait=timedelta(0)),
    )

    assert outcomes.count(ClaimOutcome.CLAIMED) == 1
    assert outcomes.count(ClaimOutcome.TIMED_OUT) == 1
    assert await claims_db[CLAIMS_COLLECTION].count_documents({}) == 1


@pytest.mark.asyncio
async def test_claim_returns_completed_when_marker_exists(
    claims_db: AsyncDatabase[dict[str, Any]],
) -> None:
    clock = FakeClock()
    completed = completed_store(claims_db, clock)
    store = claim_store(claims_db, clock, completed)
    await completed.mark_processed(KEY, module_id="sheets")

    outcome = await store.claim(KEY, module_id="sheets", owner_token=OWNER_A)

    assert outcome is ClaimOutcome.COMPLETED
    assert await claims_db[CLAIMS_COLLECTION].count_documents({}) == 0


@pytest.mark.asyncio
async def test_frozen_clock_claim_terminates_within_attempt_budget(
    claims_db: AsyncDatabase[dict[str, Any]],
) -> None:
    clock = FakeClock()  # never advances, so the wait deadline can never be reached
    store = claim_store(
        claims_db,
        clock,
        completed_store(claims_db, clock),
        wait=timedelta(milliseconds=50),
        poll=timedelta(milliseconds=1),
    )
    await store.claim(KEY, module_id="sheets", owner_token=OWNER_A)

    outcome = await asyncio.wait_for(
        store.claim(KEY, module_id="sheets", owner_token=OWNER_B),
        timeout=30,
    )

    assert outcome is ClaimOutcome.TIMED_OUT
    stored = await claims_db[CLAIMS_COLLECTION].find_one(
        {"_id": scoped_processed_event_id(KEY, "sheets")}
    )
    assert stored is not None
    assert stored["owner_token"] == OWNER_A


@pytest.mark.asyncio
async def test_concurrent_claim_sees_marker_while_complete_is_between_marker_and_delete(
    claims_db: AsyncDatabase[dict[str, Any]],
) -> None:
    clock = FakeClock()
    completed = completed_store(claims_db, clock)
    gate = MarkerGate(completed)
    store = EventClaimStore(
        cast(Any, claims_db[CLAIMS_COLLECTION]),
        cast(Any, gate),
        now_fn=clock,
    )
    await store.claim(KEY, module_id="sheets", owner_token=OWNER_A)

    completer = asyncio.create_task(store.complete(KEY, module_id="sheets", owner_token=OWNER_A))
    try:
        await asyncio.wait_for(gate.marked.wait(), timeout=5)

        # Ordering evidence: the claim document must still be live while the
        # marker exists, so a rival claimant collides instead of re-acquiring.
        claim = await claims_db[CLAIMS_COLLECTION].find_one(
            {"_id": scoped_processed_event_id(KEY, "sheets")}
        )
        assert claim is not None
        assert claim["owner_token"] == OWNER_A

        rival = claim_store(claims_db, clock, completed)
        outcome = await asyncio.wait_for(
            rival.claim(KEY, module_id="sheets", owner_token=OWNER_B, wait=timedelta(0)),
            timeout=5,
        )
        assert outcome is ClaimOutcome.COMPLETED
    finally:
        gate.proceed.set()

    assert await completer is True
    assert await claims_db[CLAIMS_COLLECTION].count_documents({}) == 0
    assert await completed.is_duplicate(KEY, module_id="sheets") is True


@pytest.mark.asyncio
async def test_marker_landing_between_check_and_acquire_returns_completed(
    claims_db: AsyncDatabase[dict[str, Any]],
) -> None:
    clock = FakeClock()
    windowed = MarkerLandsDuringFirstProbe(
        cast(Any, claims_db[COMPLETED_COLLECTION]),
        completed_marker(clock, KEY, "sheets"),
    )
    store = EventClaimStore(
        cast(Any, claims_db[CLAIMS_COLLECTION]),
        IdempotencyStore(windowed, now_fn=clock),
        now_fn=clock,
    )

    outcome = await store.claim(KEY, module_id="sheets", owner_token=OWNER_A)

    assert outcome is ClaimOutcome.COMPLETED
    assert await claims_db[CLAIMS_COLLECTION].count_documents({}) == 0


class MarkerGate:
    """Completed-store wrapper that pauses ``complete`` after the marker lands.

    ``mark_processed`` signals ``marked`` once the marker is written and then
    blocks on ``proceed``, so a test can observe the exact window between the
    marker write and the claim delete deterministically.
    """

    def __init__(self, inner: IdempotencyStore) -> None:
        self._inner = inner
        self.marked = asyncio.Event()
        self.proceed = asyncio.Event()

    async def is_duplicate(
        self,
        idempotency_key: str,
        *,
        module_id: str | None = None,
        consumer_id: str | None = None,
    ) -> bool:
        return await self._inner.is_duplicate(
            idempotency_key, module_id=module_id, consumer_id=consumer_id
        )

    async def mark_processed(
        self, idempotency_key: str, *, module_id: str, consumer_id: str | None = None
    ) -> bool:
        result = await self._inner.mark_processed(
            idempotency_key, module_id=module_id, consumer_id=consumer_id
        )
        self.marked.set()
        await self.proceed.wait()
        return result


@pytest.mark.asyncio
async def test_complete_with_owning_token_writes_marker_and_removes_claim(
    claims_db: AsyncDatabase[dict[str, Any]],
) -> None:
    clock = FakeClock()
    completed = completed_store(claims_db, clock)
    store = claim_store(claims_db, clock, completed)
    await store.claim(KEY, module_id="sheets", owner_token=OWNER_A)

    assert await store.complete(KEY, module_id="sheets", owner_token=OWNER_A) is True

    assert await claims_db[CLAIMS_COLLECTION].count_documents({}) == 0
    assert await completed.is_duplicate(KEY, module_id="sheets") is True


@pytest.mark.asyncio
async def test_complete_with_stale_token_returns_false_and_writes_no_marker(
    claims_db: AsyncDatabase[dict[str, Any]],
) -> None:
    clock = FakeClock()
    completed = completed_store(claims_db, clock)
    store = claim_store(claims_db, clock, completed)
    await store.claim(KEY, module_id="sheets", owner_token=OWNER_A)

    assert await store.complete(KEY, module_id="sheets", owner_token=OWNER_B) is False

    assert await claims_db[CLAIMS_COLLECTION].count_documents({}) == 1
    assert await claims_db[COMPLETED_COLLECTION].count_documents({}) == 0


@pytest.mark.asyncio
async def test_release_with_owning_token_removes_claim(
    claims_db: AsyncDatabase[dict[str, Any]],
) -> None:
    clock = FakeClock()
    store = claim_store(claims_db, clock, completed_store(claims_db, clock))
    await store.claim(KEY, module_id="sheets", owner_token=OWNER_A)

    assert await store.release(KEY, module_id="sheets", owner_token=OWNER_A) is True

    assert await claims_db[CLAIMS_COLLECTION].count_documents({}) == 0


@pytest.mark.asyncio
async def test_release_with_stale_token_keeps_foreign_claim(
    claims_db: AsyncDatabase[dict[str, Any]],
) -> None:
    clock = FakeClock()
    store = claim_store(claims_db, clock, completed_store(claims_db, clock))
    await store.claim(KEY, module_id="sheets", owner_token=OWNER_A)

    assert await store.release(KEY, module_id="sheets", owner_token=OWNER_B) is False

    stored = await claims_db[CLAIMS_COLLECTION].find_one(
        {"_id": scoped_processed_event_id(KEY, "sheets")}
    )
    assert stored is not None
    assert stored["owner_token"] == OWNER_A


@pytest.mark.asyncio
async def test_fenced_owner_cannot_complete_after_lease_is_reclaimed(
    claims_db: AsyncDatabase[dict[str, Any]],
) -> None:
    clock = FakeClock()
    completed = completed_store(claims_db, clock)
    store = claim_store(claims_db, clock, completed)
    await store.claim(KEY, module_id="sheets", owner_token=OWNER_A)

    clock.advance(timedelta(seconds=121))
    await store.claim(KEY, module_id="sheets", owner_token=OWNER_B)

    assert await store.complete(KEY, module_id="sheets", owner_token=OWNER_A) is False
    assert await claims_db[COMPLETED_COLLECTION].count_documents({}) == 0

    assert await store.complete(KEY, module_id="sheets", owner_token=OWNER_B) is True
    assert await claims_db[COMPLETED_COLLECTION].count_documents({}) == 1


@pytest.mark.asyncio
async def test_waiter_claims_once_the_lease_is_released_within_budget(
    claims_db: AsyncDatabase[dict[str, Any]],
) -> None:
    clock = FakeClock()
    store = claim_store(
        claims_db,
        clock,
        completed_store(claims_db, clock),
        poll=timedelta(milliseconds=10),
    )
    await store.claim(KEY, module_id="sheets", owner_token=OWNER_A)

    async def release_soon() -> None:
        await asyncio.sleep(0.05)
        await store.release(KEY, module_id="sheets", owner_token=OWNER_A)

    releaser = asyncio.create_task(release_soon())
    outcome = await store.claim(
        KEY,
        module_id="sheets",
        owner_token=OWNER_B,
        wait=timedelta(seconds=5),
    )
    await releaser

    assert outcome is ClaimOutcome.CLAIMED


@pytest.mark.asyncio
async def test_consumer_scope_shares_marker_identity_between_claim_and_marker(
    claims_db: AsyncDatabase[dict[str, Any]],
) -> None:
    clock = FakeClock()
    completed = completed_store(claims_db, clock)
    store = claim_store(claims_db, clock, completed)
    await completed.mark_processed(KEY, module_id="sheets", consumer_id="zeler.sheets.events")

    completed_scope = await store.claim(
        KEY,
        module_id="sheets",
        consumer_id="zeler.sheets.events",
        owner_token=OWNER_A,
    )
    independent_scope = await store.claim(
        KEY,
        module_id="sheets",
        consumer_id="zeler.sheets.replay.audit",
        owner_token=OWNER_A,
    )

    assert completed_scope is ClaimOutcome.COMPLETED
    assert independent_scope is ClaimOutcome.CLAIMED
    stored = await claims_db[CLAIMS_COLLECTION].find_one(
        {"_id": scoped_processed_event_id(KEY, "zeler.sheets.replay.audit")}
    )
    assert stored is not None


class CleanupFailingClaims:
    """Claims-collection wrapper whose ``delete_one`` cleanup always fails.

    It models a Mongo error raised after the completed marker was written, so
    the test can prove the best-effort cleanup never fails the delivery.
    """

    def __init__(self, inner: ProcessedEventClaimsCollection) -> None:
        self._inner = inner

    async def find_one_and_update(
        self,
        filter_spec: dict[str, Any],
        update: dict[str, Any],
        *,
        upsert: bool,
        return_document: bool,
    ) -> dict[str, Any] | None:
        return await self._inner.find_one_and_update(
            filter_spec, update, upsert=upsert, return_document=return_document
        )

    async def find_one(self, filter_spec: dict[str, Any]) -> dict[str, Any] | None:
        return await self._inner.find_one(filter_spec)

    async def delete_one(self, filter_spec: dict[str, Any]) -> Any:
        raise PyMongoError("claim cleanup failed")


@pytest.mark.asyncio
async def test_complete_returns_true_and_keeps_marker_when_cleanup_delete_fails(
    claims_db: AsyncDatabase[dict[str, Any]],
) -> None:
    clock = FakeClock()
    completed = completed_store(claims_db, clock)
    store = EventClaimStore(
        cast(Any, CleanupFailingClaims(cast(Any, claims_db[CLAIMS_COLLECTION]))),
        completed,
        now_fn=clock,
    )
    await store.claim(KEY, module_id="sheets", owner_token=OWNER_A)

    assert await store.complete(KEY, module_id="sheets", owner_token=OWNER_A) is True

    assert await claims_db[COMPLETED_COLLECTION].count_documents({}) == 1
    # The failed best-effort cleanup leaves the claim document for the TTL
    # index; the marker already suppresses duplicates.
    assert await claims_db[CLAIMS_COLLECTION].count_documents({}) == 1


@pytest.mark.asyncio
async def test_legacy_unscoped_marker_suppresses_matching_module_claim(
    claims_db: AsyncDatabase[dict[str, Any]],
) -> None:
    clock = FakeClock()
    store = claim_store(claims_db, clock, completed_store(claims_db, clock))
    now = clock()
    await claims_db[COMPLETED_COLLECTION].insert_one(
        {
            "_id": KEY,
            "module_id": "sheets",
            "processed_at": now,
            "expires_at": now + timedelta(hours=1),
            "schema_version": 1,
        }
    )

    suppressed = await store.claim(KEY, module_id="sheets", owner_token=OWNER_A)
    independent = await store.claim(KEY, module_id="repricer", owner_token=OWNER_A)

    assert suppressed is ClaimOutcome.COMPLETED
    assert independent is ClaimOutcome.CLAIMED
