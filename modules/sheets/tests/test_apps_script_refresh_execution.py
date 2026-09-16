# ruff: noqa: S603
"""Run a fixed local Node harness with enumerated scenarios, never shell input."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "scenario",
    [
        "tabs",
        "scan",
        "changed",
        "busy",
        "no-document",
        "failure",
        "deadline",
        "removed-tab",
        "empty",
        "property-failure",
        "corrupt-cursor",
        "processing",
        "manual-retry",
    ],
)
def test_actual_apps_script_refresh_in_local_service_harness(scenario: str) -> None:
    node = shutil.which("node")
    assert node is not None, "Node is required for executable Apps Script tests"
    tests = Path(__file__).parent
    result = subprocess.run(
        [
            node,
            str(tests / "apps_script_refresh_harness.cjs"),
            scenario,
            str(tests.parent / "apps_script/sheetseller/Client.gs"),
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
