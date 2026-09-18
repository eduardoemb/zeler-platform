"""Contract tests for the generic delivery gate in front of the marker (S3a).

The gate classes are extracted from the Sheets consumer so every module adopts
the same delivery-gate semantics: the legacy check-then-act fallback for unit
doubles and the atomic claim gate over ``EventClaimStore`` for real workers.
These tests use doubles only; the store's own contract lives in
``test_event_claims.py``.
"""

from __future__ import annotations

from typing import Any

import pytest

from zeler_platform_core.events.claim_gate import (
    EventClaimGate,
    EventClaimTimeoutError,
    LegacyEventGate,
)
from zeler_platform_core.events.claims import ClaimOutcome

KEY = "items:/items/MLA1:notif-1"
MODULE_ID = "repricer"
CONSUMER_ID = "zeler.repricer.items"


class FakeAdapterStore:
    """The module idempotency-adapter shape ``LegacyEventGate`` wraps."""

    def __init__(self, *, duplicate: bool = False) -> None:
        self.duplicate = duplicate
        self.checked: list[str] = []
        self.marked: list[str] = []

    async def is_duplicate(self, key: str) -> bool:
        self.checked.append(key)
        return self.duplicate

    async def mark_processed(self, key: str) -> None:
        self.marked.append(key)


class FakeEventClaimStore:
    """``EventClaimStore`` double recording owner tokens per call."""

    def __init__(self, outcome: ClaimOutcome = ClaimOutcome.CLAIMED) -> None:
        self.outcome = outcome
        self.claimed: list[tuple[str, str, str | None, str]] = []
        self.completed: list[tuple[str, str]] = []
        self.released: list[tuple[str, str]] = []
        self._tokens: dict[str, str] = {}

    async def claim(
        self,
        idempotency_key: str,
        *,
        module_id: str,
        consumer_id: str | None = None,
        owner_token: str,
        **kwargs: Any,
    ) -> ClaimOutcome:
        self.claimed.append((idempotency_key, module_id, consumer_id, owner_token))
        self._tokens[idempotency_key] = owner_token
        return self.outcome

    async def complete(
        self,
        idempotency_key: str,
        *,
        module_id: str,
        consumer_id: str | None = None,
        owner_token: str,
    ) -> bool:
        self.completed.append((idempotency_key, owner_token))
        return True

    async def release(
        self,
        idempotency_key: str,
        *,
        module_id: str,
        consumer_id: str | None = None,
        owner_token: str,
    ) -> bool:
        self.released.append((idempotency_key, owner_token))
        return True


@pytest.mark.asyncio
async def test_legacy_gate_claim_returns_none_for_duplicate() -> None:
    store = FakeAdapterStore(duplicate=True)
    gate = LegacyEventGate(store)

    assert await gate.claim(KEY) is None
    assert store.checked == [KEY]


@pytest.mark.asyncio
async def test_legacy_gate_claim_returns_handle_when_not_duplicate() -> None:
    gate = LegacyEventGate(FakeAdapterStore())

    assert await gate.claim(KEY) is not None


@pytest.mark.asyncio
async def test_legacy_gate_complete_marks_processed_with_the_same_key() -> None:
    store = FakeAdapterStore()
    gate = LegacyEventGate(store)
    handle = await gate.claim(KEY)
    assert handle is not None

    assert await handle.complete() is True

    assert store.marked == [KEY]


@pytest.mark.asyncio
async def test_legacy_gate_release_is_a_noop() -> None:
    store = FakeAdapterStore()
    gate = LegacyEventGate(store)
    handle = await gate.claim(KEY)
    assert handle is not None

    assert await handle.release() is False

    assert store.marked == []


@pytest.mark.asyncio
async def test_claim_gate_claimed_returns_handle_scoped_to_module_and_consumer() -> None:
    store = FakeEventClaimStore()
    gate = EventClaimGate(store, module_id=MODULE_ID, consumer_id=CONSUMER_ID)

    handle = await gate.claim(KEY)

    assert handle is not None
    assert store.claimed == [(KEY, MODULE_ID, CONSUMER_ID, store._tokens[KEY])]


@pytest.mark.asyncio
async def test_claim_gate_uses_a_fresh_owner_token_per_claim() -> None:
    store = FakeEventClaimStore()
    gate = EventClaimGate(store, module_id=MODULE_ID, consumer_id=CONSUMER_ID)

    await gate.claim(KEY)
    await gate.claim(KEY)

    assert store._tokens[KEY] != store.claimed[0][3] or store.claimed[0][3] != store.claimed[1][3]
    assert store.claimed[0][3] != store.claimed[1][3]


@pytest.mark.asyncio
async def test_claim_gate_completed_returns_none() -> None:
    store = FakeEventClaimStore(outcome=ClaimOutcome.COMPLETED)
    gate = EventClaimGate(store, module_id=MODULE_ID, consumer_id=CONSUMER_ID)

    assert await gate.claim(KEY) is None


@pytest.mark.asyncio
async def test_claim_gate_timed_out_raises_retryable_error() -> None:
    store = FakeEventClaimStore(outcome=ClaimOutcome.TIMED_OUT)
    gate = EventClaimGate(store, module_id=MODULE_ID, consumer_id=CONSUMER_ID)

    with pytest.raises(EventClaimTimeoutError, match="retry the delivery later"):
        await gate.claim(KEY)


@pytest.mark.asyncio
async def test_claim_gate_handle_reuses_the_claim_owner_token() -> None:
    store = FakeEventClaimStore()
    gate = EventClaimGate(store, module_id=MODULE_ID, consumer_id=CONSUMER_ID)
    handle = await gate.claim(KEY)
    assert handle is not None
    owner_token = store._tokens[KEY]

    await handle.complete()
    await handle.release()

    assert store.completed == [(KEY, owner_token)]
    assert store.released == [(KEY, owner_token)]
