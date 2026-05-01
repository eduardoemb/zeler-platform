from __future__ import annotations

from pathlib import Path


def test_kill_switch_runbook_exists() -> None:
    content = Path("docs/runbooks/account-kill-switch.md").read_text(encoding="utf-8")

    for keyword in (
        "Meli credential breach",
        "status",
        "paused",
        "423 Locked",
        "worker.message.skipped.paused",
    ):
        assert keyword in content
