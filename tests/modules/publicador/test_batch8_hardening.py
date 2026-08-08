from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

ROOT = Path(__file__).resolve().parents[3]


def test_publicador_runtime_config_fails_closed_without_gateway_or_token() -> None:
    from zeler_publicador.ai import PublicadorConfigError
    from zeler_publicador.app import resolve_publicador_runtime_config

    with pytest.raises(PublicadorConfigError, match="GATEWAY_BASE_URL is required"):
        resolve_publicador_runtime_config({"GATEWAY_MODULE_TOKEN": "module-token"})

    with pytest.raises(PublicadorConfigError, match="GATEWAY_MODULE_TOKEN is required"):
        resolve_publicador_runtime_config(
            {"GATEWAY_BASE_URL": "https://gateway.zeler.ai/proxy/meli"}
        )


def test_publicador_runtime_config_rejects_local_legacy_and_normalizes_gateway_proxy() -> None:
    from zeler_publicador.ai import PublicadorConfigError
    from zeler_publicador.app import resolve_publicador_runtime_config

    for unsafe_base in [
        "http://localhost:8080/proxy/meli",
        "http://127.0.0.1:8080/proxy/meli",
        "https://publicadormeli.legacy.example/proxy/meli",
    ]:
        with pytest.raises(PublicadorConfigError, match="live gateway proxy"):
            resolve_publicador_runtime_config(
                {"GATEWAY_BASE_URL": unsafe_base, "GATEWAY_MODULE_TOKEN": "module-token"}
            )

    config = resolve_publicador_runtime_config(
        {
            "GATEWAY_BASE_URL": "https://gateway.zeler.ai/proxy/meli/",
            "GATEWAY_MODULE_TOKEN": "module-token",
        }
    )

    assert config.gateway_base_url == "https://gateway.zeler.ai/proxy/meli"
    assert config.gateway_module_token == "module-token"  # noqa: S105 - fake config fixture


def test_publicador_smoke_plan_is_sanitized_and_covers_parity_routes() -> None:
    from zeler_publicador.hardening import build_publicador_smoke_plan

    plan = build_publicador_smoke_plan(pilot_seller_id="82453304")
    routes = cast(list[str], plan["routes"])
    evidence_contract = cast(str, plan["evidence_contract"])

    assert plan["pilot_seller_id"] == "82453304"
    assert plan["execution_contexts"] == [
        "authenticated zeler-app session",
        "approved VM/VPC/runtime container",
    ]
    assert "/publicador/dashboard" in routes
    assert "/publicador/publications/<publication_id>/process" in routes
    assert "/publicador/batches/<batch_id>" in routes
    assert "/publicador/statistics" in routes
    assert "sanitized" in evidence_contract
    assert "token" not in str(plan).lower()
    assert "secret" not in str(plan).lower()
    assert "mongodb://" not in str(plan).lower()


def test_publicador_batch8_runbooks_forbid_local_prod_mongo_and_document_rollback() -> None:
    docs = [
        ROOT / "docs/runbooks/pilot-publicador.md",
        ROOT / "docs/operations/pilot-runbooks/publicador.md",
        ROOT / "docs/runbooks/publicador-batch8-deploy-smoke-rollback.md",
    ]

    for doc in docs:
        text = doc.read_text(encoding="utf-8")
        assert "82453304" in text
        assert "sanitized" in text.lower()
        assert "rollback" in text.lower()
        assert "approved VM/VPC/runtime" in text
        assert "previous image" in text.lower() or "previous revision" in text.lower()
        assert "module-admin" in text
        assert "MONGO_URI" not in text
        assert "connection string" not in text.lower()
        assert "db.publicador" not in text
        assert "Authorization: Bearer" not in text
        assert "curl -X" not in text
