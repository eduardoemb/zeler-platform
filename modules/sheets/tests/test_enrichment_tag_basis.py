from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, datetime
from typing import Any

import pytest

from zeler_sheets import enrichment
from zeler_sheets.event_persistence import _seller_shipping_basis_matches
from zeler_sheets.sheetseller_backfill import (
    _existing_enrichment_basis_matches,
    _listing_fixed_fee_basis_matches,
)


def basis(tags: object) -> dict[str, Any]:
    return {
        "site_id": "MLM",
        "currency_id": "MXN",
        "category_id": "MLM123",
        "listing_type_id": "gold_special",
        "price": 100,
        "shipping_mode": "me2",
        "logistic_type": "fulfillment",
        "tags": tags,
    }


def legacy_state() -> dict[str, Any]:
    raw = basis(["b", "a"])
    # Persisted pre-fix hash encodes tag order. It must not need a DB migration.
    hashed = {**raw, "price": "100"}
    old_hash = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(hashed, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    return {
        "source": "/users/{id}/shipping_options/free",
        "status": "trusted",
        "synced_at": datetime(2026, 9, 14, tzinfo=UTC),
        "basis": raw,
        "basis_hash": old_hash,
    }


@pytest.mark.parametrize("tags", [["a", "b"], ["b", "a", "a"], [" a ", "b"]])
def test_old_shipping_hash_reuses_same_tag_members_without_mutating_observation(
    tags: list[str],
) -> None:
    state = legacy_state()
    original = copy.deepcopy(state)
    assert _existing_enrichment_basis_matches(
        {"enrichment_state": {"seller_shipping_cost": state}},
        field="seller_shipping_cost",
        basis=basis(tags),
    )
    assert _seller_shipping_basis_matches({"seller_shipping_cost": state}, basis=basis(tags))
    assert state == original


def test_new_basis_hash_and_storage_canonicalize_tag_set() -> None:
    assert enrichment.basis_hash(basis(["b", "a", "a"])) == enrichment.basis_hash(basis(["a", "b"]))
    assert enrichment.bounded_basis(basis(["b", "a", "a"]))["tags"] == ["a", "b"]


@pytest.mark.parametrize("tags", [["a", "c"], ["a", None], "a,b", [{"unknown": "a"}]])
def test_different_or_malformed_tag_members_do_not_match(tags: object) -> None:
    state = legacy_state()
    assert not _existing_enrichment_basis_matches(
        {"enrichment_state": {"seller_shipping_cost": state}},
        field="seller_shipping_cost",
        basis=basis(tags),
    )
    assert not _seller_shipping_basis_matches({"seller_shipping_cost": state}, basis=basis(tags))
    assert not enrichment.listing_fee_basis_matches(basis(["a", "b"]), basis(tags))


@pytest.mark.parametrize(
    "key,value",
    [
        ("price", 101),
        ("category_id", "MLM999"),
        ("currency_id", "USD"),
        ("shipping_mode", "custom"),
    ],
)
def test_other_basis_changes_still_invalidate(key: str, value: object) -> None:
    changed = {**basis(["a", "b"]), key: value}
    state = legacy_state()
    assert not _existing_enrichment_basis_matches(
        {"enrichment_state": {"seller_shipping_cost": state}},
        field="seller_shipping_cost",
        basis=changed,
    )
    assert not _seller_shipping_basis_matches({"seller_shipping_cost": state}, basis=changed)


def test_fee_and_fixed_fee_use_same_unordered_tags() -> None:
    assert enrichment.listing_fee_basis_matches(basis(["b", "a"]), basis(["a", "b", "a"]))
    fixed = {
        "source": "/sites/{site}/listing_prices",
        "fixed_fee": 5,
        "currency_id": "MXN",
        "synced_at": datetime(2026, 9, 14, tzinfo=UTC),
        "params": basis(["b", "a"]),
    }
    assert _listing_fixed_fee_basis_matches(fixed, basis(["a", "b"]))


def test_unverifiable_legacy_hash_only_does_not_gain_trust() -> None:
    state = legacy_state()
    state.pop("basis")
    assert not _seller_shipping_basis_matches(
        {"seller_shipping_cost": state}, basis=basis(["a", "b"])
    )


def test_fee_request_contexts_canonicalize_tags_without_reordering_other_lists() -> None:
    from zeler_sheets.sheetseller_backfill import (
        _listing_price_fixed_fee_params,
        build_listing_fee_projection_context,
    )

    detail = {
        **basis(["b", "a", "a"]),
        "shipping": {"mode": "me2", "logistic_type": "fulfillment"},
        "shipping_modes": ["z", "a"],
    }
    context = build_listing_fee_projection_context(site_id="MLM", detail=detail)
    fixed = _listing_price_fixed_fee_params(item_id="MLM123", detail=detail)
    assert context is not None and fixed is not None
    assert context["tags"] == fixed["tags"] == ["a", "b"]
    assert context["shipping_modes"] == ["z", "a"]


def test_incoming_event_preserves_cost_and_original_observation_on_tag_reorder() -> None:
    from zeler_sheets.event_persistence import _item_with_preserved_enrichment

    state = legacy_state()
    incoming = {
        **basis(["a", "b"]),
        "shipping": {"mode": "me2", "logistic_type": "fulfillment"},
    }
    existing = {"seller_shipping_cost": 12, "enrichment_state": {"seller_shipping_cost": state}}
    result = _item_with_preserved_enrichment(incoming, existing)
    assert result["seller_shipping_cost"] == 12
    preserved = result["enrichment_state"]["seller_shipping_cost"]
    for key in ("status", "source", "synced_at", "basis_hash"):
        assert preserved[key] == state[key]
    assert preserved["basis"]["tags"] == state["basis"]["tags"]
