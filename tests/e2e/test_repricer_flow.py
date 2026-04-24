from __future__ import annotations

from decimal import Decimal

import pytest
from modules.repricer.tests.test_consumer_phase4 import FakeDb, FakeGatewayClient, FakeIdempotency

from zeler_gateway.webhooks.classifier import classify_webhook_topic
from zeler_repricer.consumer import RepricerEvent, RepricerEventHandler


@pytest.mark.asyncio
async def test_webhook_to_repricer_handler_to_gateway_proxy_mock_flow() -> None:
    classification = classify_webhook_topic("items_prices", "/items/MLA123/prices")
    db = FakeDb()
    gateway = FakeGatewayClient()
    handler = RepricerEventHandler(
        db=db, gateway_client=gateway, idempotency_store=FakeIdempotency()
    )

    result = await handler.handle(
        RepricerEvent(
            event_id="webhook-1",
            event_type=classification.routing_key,
            seller_id=123456789,
            resource="/items/MLA123/prices",
            idempotency_key=classification.idempotency_key("webhook-1"),
            buybox_price=Decimal("180"),
        )
    )

    assert result == "set_price"
    assert gateway.calls == [
        (123456789, "MLA123", Decimal("180"), classification.idempotency_key("webhook-1"))
    ]
    assert db["repricer_history"].docs[0]["gateway_status"] == 200
