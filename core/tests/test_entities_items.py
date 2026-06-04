from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from zeler_platform_core.models import Item, PromoPriceProjection

NOW = datetime(2026, 6, 4, 12, 0, tzinfo=UTC)


def test_promo_price_projection_accepts_bounded_discount_source() -> None:
    projection = PromoPriceProjection.model_validate(
        {
            "source": "/items/{id}/sale_price",
            "sale_amount": "99.90",
            "regular_amount": "149.90",
            "discount_percent": "33.36",
            "currency_id": "MXN",
            "promotion_id": "PROMO-1",
            "promotion_type": "deal",
            "reference_at": NOW.isoformat(),
            "synced_at": NOW,
        }
    )

    assert projection.sale_amount == Decimal("99.90")
    assert projection.regular_amount == Decimal("149.90")
    assert projection.currency_id == "MXN"
    assert projection.reference_at == NOW


def test_promo_price_projection_rejects_non_discount_and_raw_payload() -> None:
    payload = {
        "source": "/items/{id}/sale_price",
        "sale_amount": "149.90",
        "regular_amount": "149.90",
        "currency_id": "MXN",
        "reference_at": NOW,
        "synced_at": NOW,
        "raw_payload": {"must": "not persist"},
    }

    with pytest.raises(ValidationError) as exc_info:
        PromoPriceProjection.model_validate(
            {key: value for key, value in payload.items() if key != "raw_payload"}
        )

    assert "sale_amount must be less than regular_amount" in str(exc_info.value)

    with pytest.raises(ValidationError) as raw_exc_info:
        PromoPriceProjection.model_validate({**payload, "sale_amount": "99.90"})

    assert "Extra inputs are not permitted" in str(raw_exc_info.value)


def test_item_accepts_optional_current_promotion_projection() -> None:
    item = Item.model_validate(
        {
            "_id": "MLA1",
            "seller_id": 82453304,
            "title": "Listing",
            "price": "99.90",
            "base_price": "149.90",
            "available_quantity": 3,
            "status": "active",
            "category_id": "MLA-CAT",
            "last_meli_sync_at": NOW,
            "date_created": NOW,
            "last_updated": NOW,
            "current_promotion": {
                "source": "/items/{id}/sale_price",
                "sale_amount": "99.90",
                "regular_amount": "149.90",
                "discount_percent": "33.36",
                "currency_id": "MXN",
                "reference_at": NOW,
                "synced_at": NOW,
            },
        }
    )

    assert item.current_promotion is not None
    assert item.current_promotion.sale_amount == Decimal("99.90")
