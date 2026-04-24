from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from infra.decommission.audit import build_decommission_audit, render_markdown
from infra.decommission.inventory import legacy_inventory

ROOT = Path(__file__).resolve().parents[1]


def test_legacy_inventory_names_five_product_repos_and_zeler_core_separately() -> None:
    inventory = legacy_inventory()

    product_repos = {product.repository for product in inventory.products}

    assert product_repos == {
        "sheetsellerappindividual",
        "publicadormeli",
        "repricer-meli",
        "Autoreplyia",
        "fulldockmanager",
    }
    assert inventory.zeler_core_repository == "zeler-core"
    assert "zeler-platform" not in product_repos


def test_decommission_audit_is_dry_run_and_blocks_destructive_phase7_actions() -> None:
    audit = build_decommission_audit()

    actions_by_task = {action.task_id: action for action in audit.actions}

    assert set(actions_by_task) == {"P7.1", "P7.2", "P7.3", "P7.4", "P7.5", "P7.6"}
    assert audit.mode == "dry-run"
    assert audit.safe_to_execute is False

    for task_id in ("P7.1", "P7.2", "P7.3", "P7.4", "P7.5"):
        action = actions_by_task[task_id]
        assert action.destructive is True
        assert action.status == "manual_approval_required"
        assert "explicit human approval" in action.manual_approval_required

    db_action = actions_by_task["P7.4"]
    assert "final Mongo/Atlas snapshot" in db_action.prerequisites
    assert "30-day recovery window elapsed after P7.1 freeze" in db_action.prerequisites


def test_decommission_markdown_makes_safety_gate_unambiguous() -> None:
    markdown = render_markdown(build_decommission_audit())

    assert "# Legacy Decommission Audit — DRY RUN" in markdown
    assert "This report does not archive repositories" in markdown
    assert "P7.1" in markdown
    assert "P7.6" in markdown
    assert "manual_approval_required" in markdown
    assert "legacy databases must not be dropped" in markdown


def test_decommission_cli_outputs_machine_readable_dry_run_json() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "infra.decommission.audit", "--format", "json"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )

    payload = json.loads(result.stdout)

    assert payload["mode"] == "dry-run"
    assert payload["safe_to_execute"] is False
    assert payload["actions"][0]["task_id"] == "P7.1"


def test_decommission_runbook_and_postmortem_are_planning_artifacts_only() -> None:
    runbook = (ROOT / "docs" / "legacy-decommission-runbook.md").read_text(encoding="utf-8")
    postmortem = (ROOT / "docs" / "migration-postmortem.md").read_text(encoding="utf-8")

    assert "Non-destructive planning artifact" in runbook
    assert "Do not archive GitHub repositories from automation" in runbook
    assert "Do not stop/delete Cloud Run services or VMs from automation" in runbook
    assert "Do not drop Mongo databases from automation" in runbook
    assert "DRAFT — not a completion record" in postmortem
    assert "P7.4 remains unchecked until the 30-day recovery window has elapsed" in postmortem
