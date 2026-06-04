from __future__ import annotations

import pytest
from pydantic import ValidationError

from zeler_platform_core.models.entities import ReceiverAddressSnapshot, Shipment


def test_receiver_address_snapshot_keeps_only_allowlisted_trimmed_fields() -> None:
    snapshot = ReceiverAddressSnapshot.model_validate(
        {
            "name": "  Synthetic Buyer  ",
            "street_name": "  Sentinel Street  ",
            "street_number": 123,
            "neighborhood": " Test Neighborhood ",
            "zip_code": " 1000 ",
            "city": " Test City ",
            "state": " Test State ",
            "country": " AR ",
            "phone": "+54-PII-PHONE",
            "email": "pii@example.invalid",
            "document": "PII-DOCUMENT",
            "comment": "PII-COMMENT",
            "latitude": "PII-GEO-LAT",
            "longitude": "PII-GEO-LON",
        }
    )

    assert snapshot.model_dump(exclude_none=True) == {
        "name": "Synthetic Buyer",
        "street_name": "Sentinel Street",
        "street_number": "123",
        "neighborhood": "Test Neighborhood",
        "zip_code": "1000",
        "city": "Test City",
        "state": "Test State",
        "country": "AR",
    }


def test_receiver_address_snapshot_drops_blank_values_and_rejects_oversized_strings() -> None:
    snapshot = ReceiverAddressSnapshot.model_validate(
        {
            "name": "   ",
            "city": "Ciudad Sintética",
        }
    )

    assert snapshot.model_dump(exclude_none=True) == {"city": "Ciudad Sintética"}

    with pytest.raises(ValidationError) as exc_info:
        ReceiverAddressSnapshot.model_validate({"street_name": "x" * 121})

    assert "PII" not in str(exc_info.value)


def test_receiver_address_snapshot_drops_nested_string_field_values() -> None:
    snapshot = ReceiverAddressSnapshot.model_validate(
        {
            "name": {"raw": "PII-NESTED-NAME"},
            "street_name": ["PII-NESTED-STREET"],
            "city": " Safe City ",
            "state": {"name": ["PII-NESTED-STATE"]},
        }
    )

    serialized_snapshot = repr(snapshot.model_dump(exclude_none=True))
    assert snapshot.model_dump(exclude_none=True) == {"city": "Safe City"}
    for forbidden in (
        "PII-NESTED-NAME",
        "PII-NESTED-STREET",
        "PII-NESTED-STATE",
    ):
        assert forbidden not in serialized_snapshot


def test_shipment_embeds_optional_receiver_address_snapshot() -> None:
    shipment = Shipment.model_validate(
        {
            "_id": "3001",
            "seller_id": "82453304",
            "order_id": "2001",
            "status": "ready_to_ship",
            "logistic_type": "fulfillment",
            "date_created": "2026-05-29T10:00:00+00:00",
            "last_updated": "2026-05-30T11:00:00+00:00",
            "receiver_address": {
                "name": "Synthetic Buyer",
                "street_name": "Sentinel Street",
                "phone": "+54-PII-PHONE",
            },
        }
    )

    assert shipment.receiver_address is not None
    assert shipment.receiver_address.model_dump(exclude_none=True) == {
        "name": "Synthetic Buyer",
        "street_name": "Sentinel Street",
    }
