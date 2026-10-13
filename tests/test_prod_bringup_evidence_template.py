from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

TEMPLATE = Path("infra/docker/PROD_BRINGUP_EVIDENCE.template.md")


def test_gitignore_excludes_filled_evidence_but_keeps_template_tracked() -> None:
    git = shutil.which("git")
    assert git is not None

    filled = subprocess.run(  # noqa: S603 - fixed git command with static test paths
        [git, "check-ignore", "infra/docker/PROD_BRINGUP_EVIDENCE_2026-04-25.md"],
        check=False,
        capture_output=True,
        text=True,
    )
    template = subprocess.run(  # noqa: S603 - fixed git command with static test paths
        [git, "check-ignore", "infra/docker/PROD_BRINGUP_EVIDENCE.template.md"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert filled.returncode == 0
    assert filled.stdout.strip() == "infra/docker/PROD_BRINGUP_EVIDENCE_2026-04-25.md"
    assert template.returncode == 1
    assert template.stdout == ""
