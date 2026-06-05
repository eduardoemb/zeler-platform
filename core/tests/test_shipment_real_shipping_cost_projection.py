from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from zeler_platform_core.models import Shipment, ShipmentRealShippingCostProjection

NOW = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)


def test_projection_matches_seller_sender_cost_and_preserves_receiver_cost() -> None:
    projection = ShipmentRealShippingCostProjection.from_meli_costs_payload(
        {
            "currency_id": "mxn",
            "senders": [
                {"sender_id": "111", "cost": "9.99"},
                {"sender_id": 82453304, "cost": "24.50"},
            ],
            "receiver": {"cost": "100.00"},
        },
        seller_id="82453304",
        synced_at=NOW,
    )

    assert projection is not None
    assert projection.source == "/shipments/{shipment_id}/costs"
    assert projection.seller_cost == Decimal("24.50")
    assert projection.receiver_cost == Decimal("100.00")
    assert projection.currency_id == "MXN"
    assert projection.matched_sender_id == "82453304"
    assert projection.synced_at == NOW
    serialized = projection.model_dump(exclude_none=True)
    assert "senders" not in serialized
    assert "receiver" not in serialized
    assert "raw_payload" not in serialized


def test_projection_is_embedded_on_shipment_without_raw_cost_payload() -> None:
    shipment = Shipment.model_validate(
        {
            "_id": "3001",
            "seller_id": "82453304",
            "order_id": "2001",
            "status": "ready_to_ship",
            "logistic_type": "fulfillment",
            "date_created": NOW,
            "last_updated": NOW,
            "real_shipping_cost": {
                "source": "/shipments/{shipment_id}/costs",
                "seller_cost": "24.50",
                "receiver_cost": "100.00",
                "currency_id": "MXN",
                "matched_sender_id": "82453304",
                "synced_at": NOW,
            },
        }
    )

    assert shipment.real_shipping_cost is not None
    assert shipment.real_shipping_cost.seller_cost == Decimal("24.50")
    assert "raw_payload" not in shipment.real_shipping_cost.model_dump(exclude_none=True)


def test_projection_does_not_use_receiver_cost_as_seller_fallback() -> None:
    projection = ShipmentRealShippingCostProjection.from_meli_costs_payload(
        {"currency_id": "MXN", "senders": [], "receiver": {"cost": "100.00"}},
        seller_id="82453304",
        synced_at=NOW,
    )

    assert projection is None


@pytest.mark.parametrize(
    "costs_payload",
    [
        {},
        {"senders": "not-a-list", "receiver": {"cost": "100.00"}},
        {"senders": [{"sender_id": "82453304", "cost": "-1.00"}]},
        {"senders": [{"sender_id": "82453304", "cost": "Infinity"}]},
        {"senders": [{"sender_id": "82453304", "cost": "not-a-number"}]},
        {"senders": [{"sender_id": "999", "cost": "24.50"}]},
    ],
)
def test_projection_fails_closed_for_missing_malformed_negative_or_unmatched_cost_data(
    costs_payload: object,
) -> None:
    projection = ShipmentRealShippingCostProjection.from_meli_costs_payload(
        costs_payload,
        seller_id="82453304",
        synced_at=NOW,
    )

    assert projection is None


def test_projection_model_rejects_raw_payload_and_unsafe_cost_values() -> None:
    valid_payload = {
        "source": "/shipments/{shipment_id}/costs",
        "seller_cost": "24.50",
        "receiver_cost": "100.00",
        "currency_id": "MXN",
        "matched_sender_id": "82453304",
        "synced_at": NOW,
    }

    with pytest.raises(ValidationError) as raw_exc_info:
        ShipmentRealShippingCostProjection.model_validate(
            {**valid_payload, "raw_payload": {"senders": [{"cost": "24.50"}]}}
        )
    assert "Extra inputs are not permitted" in str(raw_exc_info.value)

    with pytest.raises(ValidationError) as negative_exc_info:
        ShipmentRealShippingCostProjection.model_validate({**valid_payload, "seller_cost": "-0.01"})
    assert "real shipping cost fields must be finite non-negative numbers" in str(
        negative_exc_info.value
    )
