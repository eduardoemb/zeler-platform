from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from zeler_platform_core.models import SellerUnitCost
from zeler_sheets.formulas.output_normalization import NA_VALUE
from zeler_sheets.unit_costs import UnitCostLookup, resolve_unit_cost

# fmt: off
NOW = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)


def test_seller_unit_cost_model_normalizes_and_rejects_invalid_config() -> None:
    config = SellerUnitCost(
        _id="cost-1", seller_id="123", normalized_sku=" abc ", item_id="MLA1",
        variation_id="101", unit_cost=Decimal("10.50"), currency="ars", source="manual",
        effective_from=NOW, created_at=NOW, updated_at=NOW,
    )

    assert (config.seller_id, config.normalized_sku, config.variation_id) == ("123", "ABC", "101")
    assert (config.unit_cost, config.currency) == (Decimal("10.50"), "ARS")
    with pytest.raises(ValueError):
        SellerUnitCost(
            _id="bad", seller_id="seller-1", variation_id="101", unit_cost=Decimal("NaN"),
            currency="", source="manual", effective_from=NOW, created_at=NOW, updated_at=NOW,
        )


def test_resolver_prefers_variation_then_item_then_sku_and_is_seller_scoped() -> None:
    docs = [
        _doc("sku", seller_id="seller-1", normalized_sku="ABC", unit_cost="10"),
        _doc("item", seller_id="seller-1", item_id="MLA1", unit_cost="20"),
        _doc("variation", seller_id="seller-1", item_id="MLA1", variation_id="101", unit_cost="25"),
        _doc("other-seller", seller_id="seller-2", normalized_sku="ABC", unit_cost="99"),
    ]

    assert resolve_unit_cost(docs, _lookup(variation_id="101")) == Decimal("25")
    assert resolve_unit_cost(docs, _lookup()) == Decimal("20")


@pytest.mark.parametrize("lookup_sku", ["MISSING", "OLD", "OFF", "USD-SKU", "AMB", "BAD"])
def test_resolver_returns_na_for_missing_invalid_stale_currency_or_ambiguous(
    lookup_sku: str,
) -> None:
    docs = [
        _doc(
            "expired", seller_id="seller-1", normalized_sku="OLD", unit_cost="1", effective_to=NOW
        ),
        _doc(
            "inactive", seller_id="seller-1", normalized_sku="OFF", unit_cost="2", status="inactive"
        ),
        _doc("usd", seller_id="seller-1", normalized_sku="USD-SKU", unit_cost="3", currency="USD"),
        _doc("amb-1", seller_id="seller-1", normalized_sku="AMB", unit_cost="4"),
        _doc("amb-2", seller_id="seller-1", normalized_sku="AMB", unit_cost="5"),
        _doc("invalid", seller_id="seller-1", normalized_sku="BAD", unit_cost="nan"),
    ]

    assert resolve_unit_cost(docs, _lookup(normalized_sku=lookup_sku, currency="ARS")) == NA_VALUE


def _lookup(normalized_sku: str = "ABC", item_id: str = "MLA1", variation_id: str = "", currency: str | None = None) -> UnitCostLookup:  # noqa: E501
    return UnitCostLookup("seller-1", normalized_sku, item_id, variation_id, NOW, currency)


def _doc(doc_id: str, **overrides: object) -> dict[str, object]:
    return {
        "_id": doc_id, "currency": "ARS", "source": "manual", "status": "active",
        "effective_from": datetime(2026, 1, 1, tzinfo=UTC), "schema_version": 1,
    } | overrides
