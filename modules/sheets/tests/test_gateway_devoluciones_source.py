from __future__ import annotations

from typing import Any

import pytest

from zeler_sheets.devoluciones_reconciliation import GatewayDevolucionesSource


class RecordingMeliGatewayClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def fetch_resource(self, *, seller_id: str, path: str) -> dict[str, Any]:
        self.calls.append((seller_id, path))
        return {"path": path}


@pytest.mark.asyncio
async def test_gateway_source_uses_only_proven_claim_return_and_order_endpoints() -> None:
    client = RecordingMeliGatewayClient()
    source = GatewayDevolucionesSource(client)

    await source.search_claims(
        seller_id="82453304",
        params={
            "players.user_id": "82453304",
            "players.role": "respondent",
            "offset": 0,
            "limit": 100,
        },
    )
    await source.get_claim(seller_id="82453304", claim_id="519988001")
    await source.get_returns(seller_id="82453304", claim_id="519988001")
    await source.get_order(seller_id="82453304", order_id="2001")

    assert client.calls == [
        (
            "82453304",
            "/post-purchase/v1/claims/search?players.user_id=82453304&players.role=respondent&offset=0&limit=100",
        ),
        ("82453304", "/post-purchase/v1/claims/519988001"),
        ("82453304", "/post-purchase/v2/claims/519988001/returns"),
        ("82453304", "/orders/2001"),
    ]
    assert all(not path.endswith("/detail") for _, path in client.calls)


@pytest.mark.asyncio
async def test_gateway_source_rejects_unsafe_identity_and_page_values() -> None:
    source = GatewayDevolucionesSource(RecordingMeliGatewayClient())

    with pytest.raises(ValueError, match="claim_id"):
        await source.get_claim(seller_id="82453304", claim_id="519988001/detail")
    with pytest.raises(ValueError, match="limit"):
        await source.search_claims(seller_id="82453304", params={"limit": 101, "offset": 0})
