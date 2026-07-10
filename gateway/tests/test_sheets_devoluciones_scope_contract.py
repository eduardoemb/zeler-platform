from __future__ import annotations

import json
from pathlib import Path

from zeler_gateway.proxy.router import _scope_matches
from zeler_platform_core.runtime.manifest import validate_manifest

ROOT = Path(__file__).resolve().parents[2]
REQUIRED_SCOPES = {
    "GET /post-purchase/v1/claims/search",
    "GET /post-purchase/v1/claims/*",
    "GET /post-purchase/v2/claims/*/returns",
    "GET /orders/*",
}


def test_sheets_manifest_and_registry_seed_authorize_exact_devoluciones_reads() -> None:
    manifest_scopes = set(validate_manifest("modules/sheets/manifest.yaml").allowed_meli_scopes)
    seed = json.loads(
        (ROOT / "infra/mongo/seeds/module_registry.admin_clients.json").read_text(encoding="utf-8")
    )
    sheets_seed = next(document for document in seed["documents"] if document["_id"] == "sheets")

    assert manifest_scopes >= REQUIRED_SCOPES
    assert set(sheets_seed["allowed_meli_scopes"]) >= REQUIRED_SCOPES


def test_bootstrap_registry_seed_authorizes_full_devoluciones_hydration_chain() -> None:
    seed = json.loads(
        (ROOT / "infra/mongo/seeds/module_registry.admin_clients.json").read_text(encoding="utf-8")
    )
    bootstrap_seed = next(
        document for document in seed["documents"] if document["_id"] == "bootstrap"
    )

    assert set(bootstrap_seed["allowed_meli_scopes"]) >= REQUIRED_SCOPES


def test_sheets_devoluciones_scopes_allow_canonical_paths_but_never_detail() -> None:
    scopes = validate_manifest("modules/sheets/manifest.yaml").allowed_meli_scopes

    assert _scope_matches(
        method="GET",
        path="/post-purchase/v1/claims/search?players.user_id=82453304",
        allowed_scopes=scopes,
    )
    assert _scope_matches(
        method="GET", path="/post-purchase/v1/claims/519988001", allowed_scopes=scopes
    )
    assert _scope_matches(
        method="GET",
        path="/post-purchase/v2/claims/519988001/returns",
        allowed_scopes=scopes,
    )
    assert _scope_matches(method="GET", path="/orders/2001", allowed_scopes=scopes)
    assert not _scope_matches(
        method="GET",
        path="/post-purchase/v1/claims/519988001/detail",
        allowed_scopes=scopes,
    )
    assert not _scope_matches(
        method="POST", path="/post-purchase/v1/claims/519988001", allowed_scopes=scopes
    )
