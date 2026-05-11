from __future__ import annotations

from zeler_platform_core.runtime.manifest import validate_manifest


def test_fulldock_manifest_includes_stock_locations_wildcard() -> None:
    manifest = validate_manifest("modules/fulldock/manifest.yaml")

    assert "items.*" not in manifest.routing_keys
    assert "stock_locations.*" in manifest.routing_keys


def test_fulldock_manifest_includes_stock_location_read_and_write_scopes() -> None:
    manifest = validate_manifest("modules/fulldock/manifest.yaml")

    assert "GET /user-products/*/stock" in manifest.allowed_meli_scopes
    assert "PUT /items/*/stock_locations" in manifest.allowed_meli_scopes
