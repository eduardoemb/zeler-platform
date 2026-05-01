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
    "fulldock-api.env.template",
)
WORKER_TEMPLATES = (
    "repricer-worker.env.template",
    "sheets-worker.env.template",
    "autoreply-worker.env.template",
    "fulldock-worker.env.template",
)


def test_otel_metrics_enabled_in_all_api_templates() -> None:
    missing = [name for name in API_TEMPLATES if "OTEL_METRICS_ENABLED=true" not in _read(name)]

    assert missing == []


def test_worker_health_port_in_all_worker_templates() -> None:
    missing = [name for name in WORKER_TEMPLATES if "WORKER_HEALTH_PORT=8080" not in _read(name)]

    assert missing == []


def _read(name: str) -> str:
    return (ENV_DIR / name).read_text(encoding="utf-8")
