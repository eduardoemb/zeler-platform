"""Which sellers ZelerData refresh and formula recovery may serve.

A comma-separated numeric allowlist names sellers explicitly, as before. The
value ``all`` serves every eligible seller instead; an empty value stays
closed. Eligible means a linked Mercado Libre account that is not paused,
revoked or failed, with ZelerData enabled through an active extension token
scoped to that seller. Eligibility is read from storage on every use, so pausing
an account or revoking its token takes effect without a restart.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

ALL_ELIGIBLE_SELLERS = "all"
# `refresh_pending` is a token refresh in flight: the gateway waits for it.
# Every other status (paused, revoked, invalid_grant, error, ...) is excluded.
ELIGIBLE_ACCOUNT_STATUSES: tuple[str, ...] = ("active", "refresh_pending")
DEFAULT_GATE_TTL_SECONDS = 30.0

SellerGate = Callable[[str], Awaitable[bool]]


def parse_seller_scope(value: str | None, *, error: str) -> frozenset[str] | None:
    """Return the explicit sellers, ``None`` for every eligible seller, or a closed scope."""
    if not value or not value.strip():
        return frozenset()
    if value.strip().casefold() == ALL_ELIGIBLE_SELLERS:
        return None
    sellers = frozenset(part.strip() for part in value.split(","))
    if any(not seller.isascii() or not seller.isdecimal() for seller in sellers):
        raise ValueError(error)
    return sellers


async def eligible_sellers(db: Any, *, now: datetime | None = None) -> tuple[str, ...]:
    """Linked, unpaused sellers with an active ZelerData extension token."""
    current = (now or datetime.now(UTC)).astimezone(UTC)
    enabled: set[str] = set()
    async for token in db["sheets_extension_tokens"].find(
        {"status": "active", "deleted_at": None},
        {"seller_scopes": 1, "expires_at": 1},
    ):
        expires_at = token.get("expires_at")
        if isinstance(expires_at, datetime):
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at <= current:
                continue
        for scope in token.get("seller_scopes") or ():
            if isinstance(scope, dict):
                enabled.add(str(scope.get("seller_id") or "").strip())
    sellers: set[str] = set()
    async for account in db["meli_accounts"].find(
        {"status": {"$in": list(ELIGIBLE_ACCOUNT_STATUSES)}},
        {"seller_id": 1},
    ):
        seller_id = str(account.get("seller_id") or "").strip()
        if seller_id in enabled and seller_id.isascii() and seller_id.isdecimal():
            sellers.add(seller_id)
    return tuple(sorted(sellers))


class EligibleSellerGate:
    """Admit only eligible sellers, caching the set so admission stays cheap."""

    def __init__(
        self,
        db: Any,
        *,
        ttl_seconds: float = DEFAULT_GATE_TTL_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._db = db
        self._ttl = ttl_seconds
        self._monotonic = monotonic
        self._sellers: frozenset[str] | None = None
        self._loaded_at = 0.0

    async def __call__(self, seller_id: str) -> bool:
        now = self._monotonic()
        if self._sellers is None or now - self._loaded_at > self._ttl:
            self._sellers = frozenset(await eligible_sellers(self._db))
            self._loaded_at = now
        return seller_id in self._sellers


def seller_gate_for(db: Any, sellers: frozenset[str] | None) -> SellerGate | None:
    """``all`` checks eligibility on admission; an explicit list needs no lookup."""
    return EligibleSellerGate(db) if sellers is None else None
