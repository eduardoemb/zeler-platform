from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_DIR = ROOT / "infra" / "gce" / "env-templates"
API_TEMPLATES = (
    "gateway.env.template",
    "repricer-api.env.template",
    "sheets-api.env.template",
    "publicador-api.env.template",
    "autoreply-api.env.template",
)
WORKER_TEMPLATES = (
    "repricer-worker.env.template",
    "sheets-worker.env.template",
    "autoreply-worker.env.template",
)
RETIRED_FULLDOCK_TEMPLATES = (
    "fulldock-api.env.template",
    "fulldock-worker.env.template",
)


def test_otel_metrics_enabled_in_all_api_templates() -> None:
    missing = [name for name in API_TEMPLATES if "OTEL_METRICS_ENABLED=true" not in _read(name)]

    assert missing == []


def test_worker_health_port_in_all_worker_templates() -> None:
    missing = [name for name in WORKER_TEMPLATES if "WORKER_HEALTH_PORT=8080" not in _read(name)]

    assert missing == []


def test_retired_fulldock_env_templates_are_absent() -> None:
    assert [name for name in RETIRED_FULLDOCK_TEMPLATES if (ENV_DIR / name).exists()] == []


def test_sheets_worker_declares_zelerdata_freshness_flags_and_sanitized_vm_check() -> None:
    template = _read("sheets-worker.env.template")
    secrets_script = (ROOT / "infra" / "gce" / "zeler-platform-secrets.sh").read_text(
        encoding="utf-8"
    )
    deploy_doc = (ROOT / "docs" / "deploy.md").read_text(encoding="utf-8")
    required_flags = {
        "ZELERDATA_ENRICHMENT_ENABLED=true",
        "ZELERDATA_SALE_PRICE_ENABLED=true",
        "ZELERDATA_LISTING_FIXED_FEE_ENABLED=true",
    }

    assert required_flags <= set(template.splitlines())
    assert all(flag in secrets_script for flag in required_flags)
    assert all(flag in deploy_doc for flag in required_flags)
    assert "VM-only sanitized ZELERDATA flag check" in deploy_doc
    assert "Do not print secret values" in deploy_doc


def _read(name: str) -> str:
    return (ENV_DIR / name).read_text(encoding="utf-8")
