from __future__ import annotations

from pathlib import Path

import yaml

from zeler_gateway.proxy.router import _scope_matches

ROOT = Path(__file__).resolve().parents[2]


def test_publicador_manifest_allows_only_required_meli_proxy_contracts() -> None:
    manifest = yaml.safe_load((ROOT / "modules/publicador/manifest.yaml").read_text())
    allowed_scopes = manifest["allowed_meli_scopes"]

    allowed_calls = [
        ("GET", "/categories/MLM1055"),
        ("GET", "/sites/MLM/domain_discovery/search"),
        ("GET", "/categories/MLM1055/attributes"),
        ("POST", "/items/validate"),
        ("POST", "/items"),
        ("POST", "/pictures"),
        ("GET", "/sites/MLM/listing_types"),
        ("GET", "/products/search"),
        ("POST", "/catalog_suggestions/validate"),
        ("POST", "/catalog_suggestions"),
        ("GET", "/catalog_suggestions/SUG-1"),
        ("GET", "/users/82453304/brands"),
        ("GET", "/users/82453304/stores/search"),
        ("GET", "/users/82453304/shipping_preferences"),
    ]

    for method, path in allowed_calls:
        assert _scope_matches(method=method, path=path, allowed_scopes=allowed_scopes)

    assert not _scope_matches(method="DELETE", path="/items/MLM123", allowed_scopes=allowed_scopes)
    assert not _scope_matches(method="GET", path="/orders/search", allowed_scopes=allowed_scopes)
