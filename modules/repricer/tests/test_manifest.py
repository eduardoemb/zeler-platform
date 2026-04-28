from __future__ import annotations

from zeler_platform_core.runtime.manifest import validate_manifest


def test_repricer_manifest_includes_price_suggestion_wildcard() -> None:
    manifest = validate_manifest("modules/repricer/manifest.yaml")

    assert "price_suggestion.*" in manifest.routing_keys
