from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from infra.operations import preflight
from infra.rabbitmq.topology import build_topology_definitions

ROOT = Path(__file__).resolve().parents[1]
ADMIN_CLIENT_SEED_PATH = ROOT / "infra/mongo/seeds/module_registry.admin_clients.json"
COMPOSE_PATH = ROOT / "infra/gce/docker-compose.yml"
CADDYFILE_PATH = ROOT / "infra/gce/Caddyfile"
ACTIVE_FULLDOCK_REFERENCE_FILES = (
    ROOT / "pyproject.toml",
    ROOT / "uv.lock",
    ROOT / "tests/test_package_imports.py",
    ROOT / "tests/test_module_app_health_real.py",
    ROOT / "tests/test_module_make_app.py",
    ROOT / "tests/test_consumer_heartbeat.py",
    ROOT / "tests/test_consumer_rate_limit_isolation.py",
    ROOT / "tests/test_module_dockerfiles.py",
    ROOT / "tests/test_dockerfile_healthcheck.py",
    ROOT / "tests/operations/smoke_helpers.py",
    ROOT / "README.md",
    ROOT / "AGENTS.md",
)
ARCHIVED_FULLDOCK_DOCS = (
    ROOT / "docs/operations/pilot-runbooks/fulldock.md",
    ROOT / "docs/runbooks/pilot-fulldock.md",
    ROOT / "docs/operations/fulldock-archive-policy.md",
)


def test_fulldock_module_package_tree_is_physically_absent() -> None:
    package_tree = ROOT / "modules/fulldock"

    assert not package_tree.exists(), "modules/fulldock must be restored from git/image history"
    assert importlib.util.find_spec("zeler_fulldock") is None


def test_workspace_metadata_has_no_active_fulldock_package_references() -> None:
    forbidden_tokens = ("modules/fulldock", "zeler-fulldock", "zeler_fulldock")

    offenders = _paths_containing(ACTIVE_FULLDOCK_REFERENCE_FILES[:2], forbidden_tokens)

    assert offenders == []


def test_active_tests_and_docs_do_not_keep_fulldock_buildable_or_importable() -> None:
    forbidden_tokens = (
        "zeler_fulldock",
        "modules/fulldock",
        '"fulldock"',
        "'fulldock'",
        "fulldock-api",
        "fulldock-worker",
    )

    offenders = _paths_containing(ACTIVE_FULLDOCK_REFERENCE_FILES[2:], forbidden_tokens)

    assert offenders == []


def test_zeler_app_admin_seed_excludes_retired_fulldock_scope() -> None:
    seed = json.loads(ADMIN_CLIENT_SEED_PATH.read_text(encoding="utf-8"))
    zeler_app = next(document for document in seed["documents"] if document["_id"] == "zeler-app")

    assert zeler_app["allowed_meli_scopes"] == [
        "admin:repricer",
        "admin:sheets",
        "admin:publicador",
        "admin:autoreply",
    ]
    assert "admin:fulldock" not in zeler_app["allowed_meli_scopes"]


def test_zelerstock_identity_is_retired_metadata_only() -> None:
    from zeler_platform_core.runtime.module_identity import (
        active_module_display_identities,
        retired_module_display_identities,
    )

    active_identities = active_module_display_identities()
    retired_identity = retired_module_display_identities()["fulldock"]

    assert "fulldock" not in active_identities
    assert all(identity.display_name != "ZelerStock" for identity in active_identities.values())
    assert retired_identity.display_name == "ZelerStock"
    assert retired_identity.legacy_display_name == "FullDockManager"
    assert retired_identity.availability == "retired"


@pytest.mark.asyncio
async def test_zeler_app_seed_rejects_retired_fulldock_module_admin_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gateway.tests.test_internal_tokens_issue import (
        BROKER_SECRET,
        FakeAsyncDb,
        _broker_headers,
        _json_body,
    )

    import zeler_gateway.internal.router as internal_router
    from zeler_gateway.internal.router import router

    mint_calls: list[dict[str, object]] = []
    seed = json.loads(ADMIN_CLIENT_SEED_PATH.read_text(encoding="utf-8"))
    app = FastAPI()
    app.state.mongo_db = FakeAsyncDb()
    app.state.mongo_db["module_registry"].documents.extend(seed["documents"])
    app.include_router(router)

    def record_mint_call(*args: Any, **kwargs: Any) -> str:
        mint_calls.append({"args": args, "kwargs": kwargs})
        return "bad"

    monkeypatch.setenv("ZELER_APP_BROKER_SECRET", BROKER_SECRET)
    monkeypatch.setattr(
        internal_router,
        "mint_module_jwt",
        record_mint_call,
    )
    body = _json_body(
        {
            "seller_id": 82453304,
            "scopes": ["admin:fulldock"],
            "ttl_s": 120,
            "token_kind": "module_admin",
            "target_module_id": "fulldock",
        }
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/internal/tokens/issue",
            content=body,
            headers=_broker_headers(body),
        )

    assert response.status_code == 403
    assert response.json() == {"error": "out_of_scope"}
    assert mint_calls == []


def test_runtime_topology_and_preflight_exclude_retired_fulldock() -> None:
    topology = build_topology_definitions()
    serialized_topology = json.dumps(topology, sort_keys=True)

    assert "zeler.fulldock" not in serialized_topology
    assert set(preflight.MODULES) == {"repricer", "sheets", "publicador", "autoreply"}
    assert set(preflight.RABBITMQ_WORKER_TOPOLOGY) == {
        "repricer",
        "sheets",
        "publicador",
        "autoreply",
    }


def test_gce_runtime_artifacts_have_no_active_fulldock_services_or_hosts() -> None:
    compose = COMPOSE_PATH.read_text(encoding="utf-8")
    caddyfile = CADDYFILE_PATH.read_text(encoding="utf-8")

    assert "fulldock-api" not in compose
    assert "fulldock-worker" not in compose
    assert "fulldock-api" not in caddyfile
    assert "fulldock.zeler.ai" in caddyfile
    assert 'respond "Fulldock is decommissioned" 410' in caddyfile


def test_fulldock_docs_are_archived_not_active_runbooks() -> None:
    active_docs = [
        *ARCHIVED_FULLDOCK_DOCS,
        ROOT / "docs/operations/alerts.md",
        ROOT / "docs/ops/webhook-backlog-replay.md",
    ]

    combined = "\n".join(path.read_text(encoding="utf-8") for path in active_docs)

    assert "docker compose ps fulldock-worker" not in combined
    assert "curl https://fulldock.zeler.ai/health" not in combined
    assert "fulldock-health" not in combined
    assert "active Fulldock consumer" not in combined
    assert "Fulldock is decommissioned" in combined


def test_fulldock_archive_docs_explain_code_deletion_rollback_boundary() -> None:
    combined = "\n".join(path.read_text(encoding="utf-8") for path in ARCHIVED_FULLDOCK_DOCS)

    assert "git history" in combined
    assert "previously built image" in combined
    assert "UI catalog/route" in combined
    assert "admin:fulldock" in combined
    assert "runtime services" in combined
    assert "RabbitMQ" in combined


def test_fulldock_historical_collections_are_retained_as_archive_contracts() -> None:
    retained_paths = [
        ROOT / "infra/mongo/schemas/fulldock_inventory_rules.json",
        ROOT / "infra/mongo/schemas/fulldock_history.json",
        ROOT / "infra/mongo/indexes/fulldock_inventory_rules.json",
        ROOT / "infra/mongo/indexes/fulldock_history.json",
    ]

    for retained_path in retained_paths:
        relative_path = retained_path.relative_to(ROOT)
        assert retained_path.exists(), f"{relative_path} should remain for archive/history"


def test_fulldock_archive_policy_formalizes_read_only_retention() -> None:
    policy = (ROOT / "docs/operations/fulldock-archive-policy.md").read_text(encoding="utf-8")

    assert "read-only archive" in policy
    assert "fulldock_inventory_rules" in policy
    assert "fulldock_history" in policy
    assert "Do not run delete, drop, rewrite, or migration operations" in policy
    assert "separate approved SDD" in policy


def test_fulldock_decommission_does_not_add_productive_data_deletion_scripts() -> None:
    destructive_tokens = (
        'drop_collection("fulldock_',
        "drop_collection('fulldock_",
        '.drop("fulldock_',
        ".drop('fulldock_",
        "delete_many({})",
        "deleteMany({})",
    )
    scanned_paths = [
        *ROOT.glob("infra/**/*.py"),
        *ROOT.glob("infra/**/*.sh"),
        *ROOT.glob("infra/**/*.md"),
        *ROOT.glob("docs/**/*.md"),
    ]

    offenders = _paths_containing(scanned_paths, destructive_tokens)

    assert offenders == []


def _paths_containing(paths: list[Path] | tuple[Path, ...], tokens: tuple[str, ...]) -> list[str]:
    offenders: list[str] = []
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        content = path.read_text(encoding="utf-8")
        matched_tokens = [token for token in tokens if token in content]
        if matched_tokens:
            relative = path.relative_to(ROOT)
            offenders.append(f"{relative}: {', '.join(matched_tokens)}")
    return sorted(offenders)
