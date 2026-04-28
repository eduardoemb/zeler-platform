"""Unified Mercado Libre gateway proxy client."""

from __future__ import annotations

from typing import Any

import httpx

from zeler_platform_core.auth.meli_gateway_auth import MeliGatewayAuth


class GatewayRateLimitError(Exception):
    def __init__(self, *, retry_after_seconds: int, response: httpx.Response) -> None:
        self.retry_after_seconds = retry_after_seconds
        self.response = response
        super().__init__(f"gateway rate limit; retry_after={retry_after_seconds}s")


class MeliGatewayClient:
    """Fetch Mercado Libre resources through the gateway proxy."""

    def __init__(
        self,
        base_url: str,
        auth: MeliGatewayAuth,
        *,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 10.0,
    ) -> None:
        if "/proxy/meli" not in base_url:
            raise ValueError("Meli gateway base_url must include the /proxy/meli prefix")
        self._base_url = base_url.rstrip("/")
        self._auth = auth
        self._http_client = http_client or httpx.AsyncClient(timeout=timeout)

    async def fetch_resource(self, *, seller_id: str, path: str) -> dict[str, Any]:
        response = await self.request(method="GET", seller_id=seller_id, path=path)
        return response.json()  # type: ignore[no-any-return]

    async def request(
        self,
        *,
        method: str,
        seller_id: str,
        path: str,
        json: Any | None = None,
    ) -> httpx.Response:
        token = await self._auth.get_token_for_seller(seller_id)  # type: ignore[arg-type]
        response = await self._http_client.request(
            method,
            f"{self._base_url}/{path.lstrip('/')}",
            headers={"Authorization": f"Bearer {token}"},
            json=json,
        )
        if response.status_code == 429:
            retry_after = self._parse_retry_after(response.headers.get("Retry-After"))
            raise GatewayRateLimitError(
                retry_after_seconds=retry_after,
                response=response,
            )
        response.raise_for_status()
        return response

    @staticmethod
    def _parse_retry_after(value: str | None) -> int:
        """Parse Retry-After header. Returns seconds, capped 1-30, default 5."""
        if value is None:
            return 5
        try:
            secs = int(value)
            return max(1, min(secs, 30))
        except ValueError:
            try:
                from datetime import UTC, datetime
                from email.utils import parsedate_to_datetime

                target = parsedate_to_datetime(value)
                delta = (target - datetime.now(UTC)).total_seconds()
                return max(1, min(int(delta), 30))
            except (TypeError, ValueError, OverflowError):
                return 5
