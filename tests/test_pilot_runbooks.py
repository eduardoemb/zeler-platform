from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_HEADERS = (
    "## Pre-flight checks",
    "## Setup",
    "## Trigger",
    "## Evidence of success",
    "## Evidence of broken",
    "## Rollback",
)


def _assert_pilot_runbook(module: str, module_keyword: str) -> None:
    path = ROOT / "docs" / "operations" / "pilot-runbooks" / f"{module}.md"

    assert path.exists()
    content = path.read_text(encoding="utf-8")
    header_positions = [content.index(header) for header in CANONICAL_HEADERS]
    assert header_positions == sorted(header_positions)
    for keyword in (*CANONICAL_HEADERS, "82453304", module_keyword):
        assert keyword in content


def test_legacy_pilot_runbooks_still_exist_for_backward_compatibility() -> None:
    for module in ("repricer", "sheets", "publicador", "autoreply", "fulldock"):
        assert (ROOT / "docs" / "runbooks" / f"pilot-{module}.md").exists()


def test_pilot_runbook_exists_for_repricer() -> None:
    _assert_pilot_runbook("repricer", "repricer_rules")


def test_pilot_runbook_exists_for_sheets() -> None:
    _assert_pilot_runbook("sheets", "sheets_exports")


def test_pilot_runbook_exists_for_publicador() -> None:
    _assert_pilot_runbook("publicador", "publicador_drafts")


def test_pilot_runbook_exists_for_autoreply() -> None:
    _assert_pilot_runbook("autoreply", "autoreply_templates")


def test_pilot_runbook_exists_for_fulldock() -> None:
    _assert_pilot_runbook("fulldock", "fulldock_inventory_rules")
