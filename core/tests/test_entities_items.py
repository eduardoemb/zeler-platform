from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from zeler_platform_core.models import (
    Item,
    ListingFeeProjection,
    ListingPriceFixedFeeProjection,
    PromoPriceProjection,
)

NOW = datetime(2026, 6, 4, 12, 0, tzinfo=UTC)


def listing_fee_payload(**overrides: object) -> dict[str, object]:
    return {
        "source": "/sites/{site}/listing_prices",
        "site_id": "MLA",
        "currency_id": "ARS",
        "price": "1299.90",
        "listing_type_id": "gold_special",
        "category_id": "MLA1055",
        "sale_fee_amount": "155.99",
        "percentage_fee": "12.00",
        "synced_at": NOW,
        **overrides,
    }


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


def test_listing_fee_projection_accepts_bounded_listing_price_source() -> None:
    projection = ListingFeeProjection.model_validate(
        listing_fee_payload(
            currency_id="ars",
            gross_amount="160.00",
            fixed_fee="0.00",
            meli_percentage_fee="10.00",
            financing_add_on_fee="2.00",
        )
    )

    assert projection.source == "/sites/{site}/listing_prices"
    assert projection.site_id == "MLA"
    assert projection.currency_id == "ARS"
    assert projection.price == Decimal("1299.90")
    assert projection.sale_fee_amount == Decimal("155.99")
    assert projection.percentage_fee == Decimal("12.00")
    assert projection.gross_amount == Decimal("160.00")
    assert projection.fixed_fee == Decimal("0.00")
    assert projection.meli_percentage_fee == Decimal("10.00")
    assert projection.financing_add_on_fee == Decimal("2.00")


def test_listing_fee_projection_rejects_raw_or_realized_fee_payload_fields() -> None:
    payload = listing_fee_payload()

    for forbidden_field, forbidden_value in {
        "raw_payload": {"sale_fee_details": {"percentage_fee": 12}},
        "sale_fee": {"gross": "999.99", "net": "888.88"},
        "details": [{"charge_info": {"detail_sub_type": "CV"}}],
    }.items():
        with pytest.raises(ValidationError) as exc_info:
            ListingFeeProjection.model_validate({**payload, forbidden_field: forbidden_value})

        assert "Extra inputs are not permitted" in str(exc_info.value)


def test_listing_fee_projection_rejects_missing_required_listing_context() -> None:
    payload = listing_fee_payload()

    for required_field in ("site_id", "currency_id", "listing_type_id", "category_id"):
        with pytest.raises(ValidationError) as exc_info:
            ListingFeeProjection.model_validate({**payload, required_field: None})

        assert "listing fee" in str(exc_info.value)


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


def test_listing_price_fixed_fee_projection_accepts_sanitized_meli_source() -> None:
    projection = ListingPriceFixedFeeProjection.model_validate(
        {
            "source": "/sites/{site}/listing_prices",
            "fixed_fee": "1350.00",
            "currency_id": "ars",
            "synced_at": NOW,
            "params": {
                "site_id": "MLA",
                "category_id": "MLA-CAT",
                "price": "12345.67",
                "currency_id": "ARS",
                "listing_type_id": "gold_special",
                "shipping_mode": "me2",
                "logistic_type": "fulfillment",
                "billable_weight": "500",
                "tags": ["campaign-a"],
            },
        }
    )

    assert projection.fixed_fee == Decimal("1350.00")
    assert projection.currency_id == "ARS"
    assert projection.params.price == Decimal("12345.67")
    assert projection.params.billable_weight == Decimal("500")


def test_listing_price_fixed_fee_projection_rejects_invalid_inputs() -> None:
    valid_payload = {
        "source": "/sites/{site}/listing_prices",
        "fixed_fee": "1350",
        "currency_id": "ARS",
        "synced_at": NOW,
        "params": {
            "site_id": "MLA",
            "category_id": "MLA-CAT",
            "price": "12345.67",
            "currency_id": "ARS",
            "listing_type_id": "gold_special",
            "shipping_mode": "me2",
            "logistic_type": "fulfillment",
        },
    }

    with pytest.raises(ValidationError):
        ListingPriceFixedFeeProjection.model_validate(
            {**valid_payload, "source": "/items/{id}/sale_price"}
        )
    with pytest.raises(ValidationError):
        ListingPriceFixedFeeProjection.model_validate({**valid_payload, "fixed_fee": "NaN"})
    with pytest.raises(ValidationError):
        ListingPriceFixedFeeProjection.model_validate({**valid_payload, "raw_payload": {"x": 1}})


@pytest.mark.parametrize(
    "payload",
    [
        {"fixed_fee": "not-a-decimal"},
        {"params": {"price": "not-a-decimal"}},
        {"params": {"billable_weight": "not-a-decimal"}},
    ],
)
def test_listing_price_fixed_fee_projection_invalid_decimal_values_validate_cleanly(
    payload: dict[str, object],
) -> None:
    valid_params = {
        "site_id": "MLA",
        "category_id": "MLA-CAT",
        "price": "12345.67",
        "currency_id": "ARS",
        "listing_type_id": "gold_special",
        "shipping_mode": "me2",
        "logistic_type": "fulfillment",
        "billable_weight": "500",
    }
    params_override = payload.get("params")
    params = valid_params | params_override if isinstance(params_override, dict) else valid_params

    with pytest.raises(ValidationError):
        ListingPriceFixedFeeProjection.model_validate(
            {
                "source": "/sites/{site}/listing_prices",
                "fixed_fee": payload.get("fixed_fee", "1350"),
                "currency_id": "ARS",
                "synced_at": NOW,
                "params": params,
            }
        )


def test_item_accepts_currency_and_listing_price_fixed_fee_projection() -> None:
    item = Item.model_validate(
        {
            "_id": "MLA1",
            "seller_id": 82453304,
            "title": "Listing",
            "price": "12345.67",
            "base_price": "12345.67",
            "currency_id": "ars",
            "site_id": "mla",
            "available_quantity": 3,
            "status": "active",
            "category_id": "MLA-CAT",
            "listing_type_id": "gold_special",
            "last_meli_sync_at": NOW,
            "date_created": NOW,
            "last_updated": NOW,
            "listing_price_fixed_fee": {
                "source": "/sites/{site}/listing_prices",
                "fixed_fee": "1350",
                "currency_id": "ARS",
                "synced_at": NOW,
                "params": {
                    "site_id": "MLA",
                    "category_id": "MLA-CAT",
                    "price": "12345.67",
                    "currency_id": "ARS",
                    "listing_type_id": "gold_special",
                    "shipping_mode": "me2",
                    "logistic_type": "fulfillment",
                },
            },
        }
    )

    assert item.currency_id == "ARS"
    assert item.site_id == "MLA"
    assert item.listing_price_fixed_fee is not None
    assert item.listing_price_fixed_fee.fixed_fee == Decimal("1350")


def test_item_accepts_optional_listing_fee_projection() -> None:
    item = Item.model_validate(
        {
            "_id": "MLA1",
            "seller_id": 82453304,
            "title": "Listing",
            "price": "1299.90",
            "base_price": "1299.90",
            "available_quantity": 3,
            "status": "active",
            "category_id": "MLA1055",
            "currency_id": "ars",
            "last_meli_sync_at": NOW,
            "date_created": NOW,
            "last_updated": NOW,
            "listing_fee_projection": listing_fee_payload(),
        }
    )

    assert item.currency_id == "ARS"
    assert item.listing_fee_projection is not None
    assert item.listing_fee_projection.sale_fee_amount == Decimal("155.99")
    assert item.listing_fee_projection.percentage_fee == Decimal("12.00")
