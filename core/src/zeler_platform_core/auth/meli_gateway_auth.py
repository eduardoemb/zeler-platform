"""Per-seller Mercado Libre gateway JWT helper."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from zeler_platform_core.auth.jwt import (
    JWT_AUDIENCE,
    KmsSigningClient,
    _mint_es256_jwt,
    set_kms_client,
)


class KMSSignError(Exception):
    """Raised when KMS cannot sign a module JWT."""


class MeliGatewayAuth:
    """Mint and cache module JWTs used by workers to call the Meli gateway proxy."""

    def __init__(
        self,
        module_id: str,
        kms_client: KmsSigningClient,
        *,
        jwt_ttl_s: int = 60,
        cache_ttl_s: int = 50,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._module_id = module_id
        self._kms_client = kms_client
        self._jwt_ttl_s = jwt_ttl_s
        self._cache_ttl_s = cache_ttl_s
        self._clock = clock
        self._cache: dict[int, tuple[str, float]] = {}
        self._locks: dict[int, asyncio.Lock] = {}

    async def get_token_for_seller(self, seller_id: int) -> str:
        lock = self._locks.setdefault(seller_id, asyncio.Lock())
        async with lock:
            return self._get_or_mint_token_for_seller(seller_id)

    def _get_or_mint_token_for_seller(self, seller_id: int) -> str:
        now = self._clock()
        cached = self._cache.get(seller_id)
        if cached is not None:
            token, expires_at = cached
            if expires_at > now:
                return token

        set_kms_client(self._kms_client)
        try:
            token = self._mint_token(seller_id)
        except Exception as exc:  # noqa: BLE001 - KMS clients raise provider-specific errors.
            raise KMSSignError("KMS failed to sign Meli gateway JWT") from exc
        self._cache[seller_id] = (token, now + self._cache_ttl_s)
        return token

    def _mint_token(self, seller_id: int) -> str:
        now = int(time.time())
        payload = {
            "iss": f"module:{self._module_id}",
            "aud": JWT_AUDIENCE,
            "module_id": self._module_id,
            "sub": str(seller_id),
            "iat": now,
            "exp": now + self._jwt_ttl_s,
        }
        return _mint_es256_jwt(payload)
