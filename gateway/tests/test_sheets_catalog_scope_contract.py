from __future__ import annotations

from zeler_gateway.proxy.router import _scope_matches
from zeler_platform_core.runtime.manifest import validate_manifest


def test_sheets_catalog_scopes_cover_product_and_price_to_win_paths() -> None:
    manifest = validate_manifest("modules/sheets/manifest.yaml")
    scopes = manifest.allowed_meli_scopes

    assert "GET /products/*" in scopes
    assert _scope_matches(method="GET", path="/products/CAT-PII-1", allowed_scopes=scopes)
    assert _scope_matches(method="GET", path="/products/CAT-PII-1/items", allowed_scopes=scopes)
    assert _scope_matches(
        method="GET", path="/products/CAT-PII-1/items?limit=50", allowed_scopes=scopes
    )
    assert _scope_matches(
        method="GET", path="/items/ITEM-PII-1/price_to_win?version=v2", allowed_scopes=scopes
    )


def test_sheets_catalog_scopes_reject_unrelated_or_wrong_method_paths() -> None:
    scopes = validate_manifest("modules/sheets/manifest.yaml").allowed_meli_scopes

    assert not _scope_matches(method="POST", path="/products/CAT-PII-1", allowed_scopes=scopes)
    assert not _scope_matches(
        method="GET", path="/catalog_suggestions/SUG-PII-1", allowed_scopes=scopes
    )
