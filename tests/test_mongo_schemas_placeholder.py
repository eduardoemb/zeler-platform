from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = ROOT / "infra" / "mongo" / "schemas"
EXPECTED_FILES = {
    "users.json",
    "meli_accounts.json",
    "items.json",
    "orders.json",
    "questions.json",
    "messages.json",
    "shipments.json",
    "claims.json",
    "webhook_events.json",
    "bootstrap_jobs.json",
    "module_registry.json",
    "repricer_rules.json",
    "repricer_history.json",
    "audit_log.json",
}


def test_placeholder_schema_files_exist_and_reference_phase_three() -> None:
    assert SCHEMAS_DIR.exists()

    actual_files = {path.name for path in SCHEMAS_DIR.glob("*.json")}
    assert actual_files == EXPECTED_FILES

    for file_name in sorted(EXPECTED_FILES):
        payload = json.loads((SCHEMAS_DIR / file_name).read_text(encoding="utf-8"))
        assert isinstance(payload, dict)
        assert "P3" in payload.get("$comment", "")
