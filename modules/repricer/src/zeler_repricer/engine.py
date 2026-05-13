from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from zeler_platform_core.models import (
    RepricerAllies,
    RepricerCatalogRule,
    RepricerLimits,
    RepricerRule,
)


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


def evaluate_catalog_rule(
    rule: RepricerCatalogRule,
    *,
    current_price: Decimal,
    buybox_price: Decimal | None,
    limits: RepricerLimits | None = None,
    allies: RepricerAllies | None = None,
    competitor_account_id: str | None = None,
) -> Decision:
    if not rule.active:
        return NoAction(reason="paused", candidate_price=None)
    if limits is not None and limits.enabled:
        if limits.pause_competition:
            return NoAction(reason="competition_paused", candidate_price=None)
        if limits.escalate_to_manual_review:
            return NoAction(reason="manual_review_required", candidate_price=None)
    candidate = _catalog_candidate_price(
        rule=rule,
        current_price=current_price,
        buybox_price=buybox_price,
        limits=limits,
    )
    if candidate is None:
        return NoAction(reason="missing_buybox", candidate_price=None)
    if _is_ally_competitor(allies=allies, competitor_account_id=competitor_account_id):
        return NoAction(reason="ally_competitor", candidate_price=candidate)
    floor = _effective_floor(rule=rule, limits=limits)
    ceiling = _effective_ceiling(rule=rule, limits=limits)
    if candidate < floor:
        return NoAction(reason="below_floor", candidate_price=candidate)
    bounded_candidate = min(candidate, ceiling)
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


def _catalog_candidate_price(
    *,
    rule: RepricerCatalogRule,
    current_price: Decimal,
    buybox_price: Decimal | None,
    limits: RepricerLimits | None,
) -> Decimal | None:
    if rule.strategy == "min_price":
        return rule.min_price if current_price < rule.min_price else current_price
    if rule.strategy == "maximize":
        return rule.max_price
    if buybox_price is None:
        return None
    if limits is not None and limits.enabled:
        return buybox_price - limits.undercut_delta
    return buybox_price


def _effective_floor(*, rule: RepricerCatalogRule, limits: RepricerLimits | None) -> Decimal:
    if limits is None or not limits.enabled:
        return rule.min_price
    return max(rule.min_price, limits.min_price_limit)


def _effective_ceiling(*, rule: RepricerCatalogRule, limits: RepricerLimits | None) -> Decimal:
    if limits is None or not limits.enabled:
        return rule.max_price
    return min(rule.max_price, limits.max_price_limit)


def _is_ally_competitor(
    *, allies: RepricerAllies | None, competitor_account_id: str | None
) -> bool:
    if allies is None or competitor_account_id is None:
        return False
    return any(ally.account_id == str(competitor_account_id) for ally in allies.allies)


def _reason(strategy: str) -> str:
    if strategy == "competitive":
        return "track_buybox"
    return strategy
