from __future__ import annotations

from pathlib import Path


def test_gateway_readme_documents_cloud_run_health_probes() -> None:
    readme = Path("gateway/README.md")

    content = readme.read_text(encoding="utf-8")

    for expected in (
        "startupProbe",
        "livenessProbe",
        "readinessProbe",
        "/health",
        "/ready",
        "READY_MONGO_TIMEOUT_S",
        "READY_RABBITMQ_TIMEOUT_S",
    ):
        assert expected in content
