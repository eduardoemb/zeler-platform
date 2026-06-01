from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from zeler_platform_core.models import RepricerAllies, RepricerCatalogRule, RepricerLimits
from zeler_platform_core.models.operational import RepricerAllyAccount, RepricerRuleExecutionState
from zeler_repricer.engine import NoAction, SetPrice, evaluate_catalog_rule

NOW = datetime(2026, 5, 13, 20, 0, tzinfo=UTC)


def test_catalog_rule_tracks_buybox_with_ceiling_bound() -> None:
    rule = _catalog_rule(strategy="competitive", min_price="100", max_price="120")

    decision = evaluate_catalog_rule(
        rule,
        current_price=Decimal("150"),
        buybox_price=Decimal("130"),
    )

    assert decision == SetPrice(new_price=Decimal("120"), reason="track_buybox")


def test_catalog_rule_records_no_action_when_candidate_is_below_floor() -> None:
    rule = _catalog_rule(strategy="competitive", min_price="100", max_price="120")

    decision = evaluate_catalog_rule(
        rule,
        current_price=Decimal("150"),
        buybox_price=Decimal("90"),
    )

    assert decision == NoAction(reason="below_floor", candidate_price=Decimal("90"))


def test_inactive_catalog_rule_is_paused_without_live_price_decision() -> None:
    rule = _catalog_rule(
        strategy="competitive",
        min_price="100",
        max_price="120",
        active=False,
    )

    decision = evaluate_catalog_rule(
        rule,
        current_price=Decimal("150"),
        buybox_price=Decimal("110"),
    )

    assert decision == NoAction(reason="paused", candidate_price=None)


def test_catalog_rule_applies_limit_undercut_and_effective_ceiling() -> None:
    rule = _catalog_rule(strategy="competitive", min_price="100", max_price="130")
    limits = _limits(min_price_limit="105", max_price_limit="115", undercut_delta="2")

    decision = evaluate_catalog_rule(
        rule,
        current_price=Decimal("150"),
        buybox_price=Decimal("118"),
        limits=limits,
    )

    assert decision == SetPrice(new_price=Decimal("115"), reason="track_buybox")


def test_catalog_rule_blocks_when_limit_floor_would_be_violated() -> None:
    rule = _catalog_rule(strategy="competitive", min_price="100", max_price="130")
    limits = _limits(min_price_limit="105", max_price_limit="130", undercut_delta="2")

    decision = evaluate_catalog_rule(
        rule,
        current_price=Decimal("150"),
        buybox_price=Decimal("106"),
        limits=limits,
    )

    assert decision == NoAction(reason="below_floor", candidate_price=Decimal("104"))


def test_catalog_rule_pause_and_escalation_flags_block_mutation() -> None:
    rule = _catalog_rule(strategy="competitive", min_price="100", max_price="130")

    paused = evaluate_catalog_rule(
        rule,
        current_price=Decimal("150"),
        buybox_price=Decimal("118"),
        limits=_limits(pause_competition=True),
    )
    escalated = evaluate_catalog_rule(
        rule,
        current_price=Decimal("150"),
        buybox_price=Decimal("118"),
        limits=_limits(escalate_to_manual_review=True),
    )

    assert paused == NoAction(reason="competition_paused", candidate_price=None)
    assert escalated == NoAction(reason="manual_review_required", candidate_price=None)


def test_catalog_rule_excludes_allied_competitor_from_price_decision() -> None:
    rule = _catalog_rule(strategy="competitive", min_price="100", max_price="130")
    allies = RepricerAllies(
        _id="allies-123456789",
        seller_id="123456789",
        allies=[RepricerAllyAccount(account_id="ally-1", nickname="ALLY SHOP")],
        created_at=NOW,
        updated_at=NOW,
    )

    decision = evaluate_catalog_rule(
        rule,
        current_price=Decimal("150"),
        buybox_price=Decimal("118"),
        competitor_account_id="ally-1",
        allies=allies,
    )

    assert decision == NoAction(reason="ally_competitor", candidate_price=Decimal("118"))


def _catalog_rule(
    *,
    strategy: str,
    min_price: str,
    max_price: str,
    active: bool = True,
) -> RepricerCatalogRule:
    return RepricerCatalogRule(
        _id=f"catalog-{strategy}",
        seller_id="123456789",
        account_id="acc-1",
        item_id="MLA123",
        title="Catalog item",
        sku="SKU-123",
        strategy=strategy,  # type: ignore[arg-type]
        min_price=Decimal(min_price),
        max_price=Decimal(max_price),
        active=active,
        execution_state=RepricerRuleExecutionState(),
        created_at=NOW,
        updated_at=NOW,
        created_by="operator-1",
        updated_by="operator-1",
    )


def _limits(
    *,
    min_price_limit: str = "90",
    max_price_limit: str = "140",
    undercut_delta: str = "0",
    pause_competition: bool = False,
    escalate_to_manual_review: bool = False,
) -> RepricerLimits:
    return RepricerLimits(
        _id="limits-123456789-acc-1",
        seller_id="123456789",
        account_id="acc-1",
        enabled=True,
        min_price_limit=Decimal(min_price_limit),
        max_price_limit=Decimal(max_price_limit),
        undercut_delta=Decimal(undercut_delta),
        pause_competition=pause_competition,
        escalate_to_manual_review=escalate_to_manual_review,
        created_at=NOW,
        updated_at=NOW,
    )
