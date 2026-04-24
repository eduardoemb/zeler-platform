from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from zeler_platform_core.models import RepricerRule


@dataclass(frozen=True)
class SetPrice:
    new_price: Decimal
    reason: str


@dataclass(frozen=True)
class NoAction:
    reason: str
    candidate_price: Decimal | None = None


Decision = SetPrice | NoAction


def evaluate_rule(
    rule: RepricerRule,
    *,
    current_price: Decimal,
    buybox_price: Decimal | None,
) -> Decision:
    candidate = _candidate_price(rule=rule, current_price=current_price, buybox_price=buybox_price)
    if candidate is None:
        return NoAction(reason="missing_buybox", candidate_price=None)
    if candidate < rule.min_price:
        return NoAction(reason="below_floor", candidate_price=candidate)
    bounded_candidate = min(candidate, rule.max_price)
    if bounded_candidate == current_price:
        return NoAction(reason="already_optimal", candidate_price=bounded_candidate)
    return SetPrice(new_price=bounded_candidate, reason=_reason(rule.strategy))


def _candidate_price(
    *, rule: RepricerRule, current_price: Decimal, buybox_price: Decimal | None
) -> Decimal | None:
    if rule.strategy == "min_price":
        return rule.min_price if current_price < rule.min_price else current_price
    if rule.strategy == "maximize":
        return rule.max_price
    if buybox_price is None:
        return None
    return buybox_price


def _reason(strategy: str) -> str:
    if strategy == "competitive":
        return "track_buybox"
    return strategy
