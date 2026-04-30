from __future__ import annotations

import json
from pathlib import Path

from zeler_gateway.proxy.router import _scope_matches

ROOT = Path(__file__).resolve().parents[2]


def test_bootstrap_module_registry_seed_authorizes_bootstrap_read_paths() -> None:
    seed = json.loads(
        (ROOT / "infra" / "mongo" / "seeds" / "module_registry.admin_clients.json").read_text(
            encoding="utf-8"
        )
    )
    bootstrap = next(doc for doc in seed["documents"] if doc["_id"] == "bootstrap")
    scopes = bootstrap["allowed_meli_scopes"]

    assert bootstrap["status"] == "enabled"
    assert _scope_matches(method="GET", path="/users/123", allowed_scopes=scopes)
    assert _scope_matches(method="GET", path="/users/123/items/search", allowed_scopes=scopes)
    assert _scope_matches(method="GET", path="/items", allowed_scopes=scopes)
    assert _scope_matches(method="GET", path="/orders/search", allowed_scopes=scopes)
    assert _scope_matches(method="GET", path="/questions/search", allowed_scopes=scopes)
    assert _scope_matches(method="GET", path="/messages/packs/200", allowed_scopes=scopes)
    assert _scope_matches(method="GET", path="/shipments/300", allowed_scopes=scopes)
    assert _scope_matches(method="GET", path="/claims/search", allowed_scopes=scopes)
    assert not _scope_matches(method="POST", path="/items/MLA123", allowed_scopes=scopes)
