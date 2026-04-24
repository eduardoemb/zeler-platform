from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNBOOK_PATH = ROOT / "infra" / "runbooks" / "on-prem-mongo-setup.md"
REQUIRED_HEADERS = [
    "## Prerequisites",
    "## OS Hardening",
    "## Mongo Install",
    "## Mongo Config",
    "## systemd Verification",
    "## Initial Users",
    "## Firewall",
    "## TLS Strategy",
    "## Backups",
    "## Restore Drills",
]


def test_on_prem_runbook_contains_required_sections() -> None:
    assert RUNBOOK_PATH.exists()

    content = RUNBOOK_PATH.read_text(encoding="utf-8")

    for header in REQUIRED_HEADERS:
        assert header in content
