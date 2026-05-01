from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_playbook_exists_at_canonical_path() -> None:
    assert (ROOT / "docs" / "operations" / "rollout-playbook.md").exists()


def test_playbook_documents_each_wave_0_through_4() -> None:
    content = (ROOT / "docs" / "operations" / "rollout-playbook.md").read_text(encoding="utf-8")

    for wave in range(5):
        assert f"Wave {wave}" in content
    assert "Rollback procedures per wave" in content


def test_playbook_references_wave_gate_and_kill_switch() -> None:
    content = (ROOT / "docs" / "operations" / "rollout-playbook.md").read_text(encoding="utf-8")

    assert "infra/rollout/wave_gate.py" in content
    assert "docs/runbooks/account-kill-switch.md" in content
