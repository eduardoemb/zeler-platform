from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
UPTIME_DIR = ROOT / "infra" / "monitoring" / "uptime"
SERVICES = ("gateway", "repricer", "sheets", "publicador", "autoreply", "fulldock")


def test_six_uptime_check_files_exist() -> None:
    assert sorted(path.name for path in UPTIME_DIR.glob("*.yaml")) == sorted(
        f"{service}.yaml" for service in SERVICES
    )


def test_each_uptime_check_targets_health_path() -> None:
    for service in SERVICES:
        config = yaml.safe_load((UPTIME_DIR / f"{service}.yaml").read_text())
        assert config["displayName"] == f"{service}-health"
        assert config["monitoredResource"]["labels"]["host"] == f"{service}.zeler.ai"
        assert config["httpCheck"]["path"] == "/health"
        assert config["period"] == "30s"
        assert config["timeout"] == "10s"
