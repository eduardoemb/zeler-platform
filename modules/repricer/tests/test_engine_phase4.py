from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from zeler_platform_core.models import RepricerRule
from zeler_repricer.engine import NoAction, SetPrice, evaluate_rule

NOW = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)


def test_track_buybox_sets_price_to_buybox_bounded_by_ceiling() -> None:
    rule = _rule(strategy="competitive", min_price="100", max_price="200")

    decision = evaluate_rule(rule, current_price=Decimal("150"), buybox_price=Decimal("250"))

    assert decision == SetPrice(new_price=Decimal("200"), reason="track_buybox")


def test_below_floor_returns_no_action() -> None:
    rule = _rule(strategy="competitive", min_price="100", max_price="200")

    decision = evaluate_rule(rule, current_price=Decimal("150"), buybox_price=Decimal("90"))

    assert decision == NoAction(reason="below_floor", candidate_price=Decimal("90"))


def test_maximize_returns_ceiling() -> None:
    rule = _rule(strategy="maximize", min_price="100", max_price="200")

    decision = evaluate_rule(rule, current_price=Decimal("150"), buybox_price=Decimal("180"))

    assert decision == SetPrice(new_price=Decimal("200"), reason="maximize")


def test_min_price_returns_floor_when_below() -> None:
    rule = _rule(strategy="min_price", min_price="100", max_price="200")

    decision = evaluate_rule(rule, current_price=Decimal("80"), buybox_price=None)

    assert decision == SetPrice(new_price=Decimal("100"), reason="min_price")


def test_engine_is_deterministic() -> None:
    rule = _rule(strategy="competitive", min_price="100", max_price="200")

    first = evaluate_rule(rule, current_price=Decimal("150"), buybox_price=Decimal("180"))
    second = evaluate_rule(rule, current_price=Decimal("150"), buybox_price=Decimal("180"))

    assert first == second == SetPrice(new_price=Decimal("180"), reason="track_buybox")


def _rule(*, strategy: str, min_price: str, max_price: str) -> RepricerRule:
    return RepricerRule(
        _id=f"rule-{strategy}",
        seller_id="123456789",
        item_id="MLA123",
        strategy=strategy,  # type: ignore[arg-type]
        min_price=Decimal(min_price),
        max_price=Decimal(max_price),
        active=True,
        updated_at=NOW,
    )
