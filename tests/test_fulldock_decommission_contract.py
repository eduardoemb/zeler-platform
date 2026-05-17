from __future__ import annotations

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


@pytest.mark.asyncio
async def test_zeler_app_seed_rejects_retired_fulldock_module_admin_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gateway.tests.test_internal_tokens_issue import FakeAsyncDb, FakeClaims

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

    monkeypatch.setattr(
        internal_router,
        "verify_module_jwt",
        lambda token: FakeClaims(module_id="zeler-app", seller_id=82453304),
    )
    monkeypatch.setattr(
        internal_router,
        "mint_module_jwt",
        record_mint_call,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/internal/tokens/issue",
            headers={"Authorization": "Bearer zeler-app-gateway-token"},
            json={
                "seller_id": 82453304,
                "scopes": ["admin:fulldock"],
                "ttl_s": 120,
                "token_kind": "module_admin",
                "target_module_id": "fulldock",
            },
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
    assert "fulldock.zeler.ai" not in caddyfile
    assert "fulldock-api" not in caddyfile


def test_fulldock_docs_are_archived_not_active_runbooks() -> None:
    active_docs = [
        ROOT / "docs/operations/pilot-runbooks/fulldock.md",
        ROOT / "docs/runbooks/pilot-fulldock.md",
        ROOT / "docs/operations/alerts.md",
        ROOT / "docs/ops/webhook-backlog-replay.md",
    ]

    combined = "\n".join(path.read_text(encoding="utf-8") for path in active_docs)

    assert "docker compose ps fulldock-worker" not in combined
    assert "curl https://fulldock.zeler.ai/health" not in combined
    assert "fulldock-health" not in combined
    assert "active Fulldock consumer" not in combined
    assert "Fulldock is decommissioned" in combined


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
