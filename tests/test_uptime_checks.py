from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
UPTIME_DIR = ROOT / "infra" / "monitoring" / "uptime"
SERVICES = ("gateway", "repricer", "sheets", "publicador", "autoreply")
RETIRED_SERVICE = "fulldock"


def test_five_active_uptime_check_files_exist() -> None:
    uptime_files = sorted(path.name for path in UPTIME_DIR.glob("*.yaml"))

    assert uptime_files == sorted(f"{service}.yaml" for service in SERVICES)
    assert f"{RETIRED_SERVICE}.yaml" not in uptime_files


def test_each_uptime_check_targets_health_path() -> None:
    for service in SERVICES:
        config = yaml.safe_load((UPTIME_DIR / f"{service}.yaml").read_text())
        assert config["displayName"] == f"{service}-health"
        assert config["monitoredResource"]["labels"]["host"] == f"{service}.zeler.ai"
        assert config["httpCheck"]["path"] == "/health"
        assert config["period"] == "30s"
        assert config["timeout"] == "10s"
