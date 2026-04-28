from __future__ import annotations

from zeler_platform_core.runtime.manifest import validate_manifest


def test_fulldock_manifest_includes_stock_locations_wildcard() -> None:
    manifest = validate_manifest("modules/fulldock/manifest.yaml")

    assert "stock_locations.*" in manifest.routing_keys
