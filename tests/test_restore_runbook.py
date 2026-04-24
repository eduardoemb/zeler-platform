from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNBOOK_PATH = ROOT / "infra" / "runbooks" / "mongo-restore.md"
REQUIRED_HEADERS = [
    "## Prerequisites",
    "## Restore Procedure",
    "## Post-Restore: Re-apply Schema Validators",
    "## Verification",
    "## Monthly Drill",
]


def test_restore_runbook_contains_required_sections() -> None:
    assert RUNBOOK_PATH.exists()

    content = RUNBOOK_PATH.read_text(encoding="utf-8")

    for header in REQUIRED_HEADERS:
        assert header in content

    assert "apply_validators" in content
