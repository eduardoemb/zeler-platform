from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = ROOT / "infra" / "mongo" / "schemas"
EXPECTED_FILES = {
    # Source-of-truth canon (gateway-owned, from spec section 4)
    "users.json",
    "meli_accounts.json",
    "items.json",
    "orders.json",
    "questions.json",
    "messages.json",
    "shipments.json",
    "claims.json",
    "events.json",
    # Webhook ingestion + audit
    "webhook_events.json",
    "processed_events.json",
    "audit_log.json",
    "rate_limit_counters.json",
    # Bootstrap + module runtime
    "bootstrap_jobs.json",
    "bootstrap_dispatcher_locks.json",
    "module_registry.json",
    # Repricer module-owned
    "repricer_rules.json",
    "repricer_history.json",
    # Sheets module-owned
    "sheets_exports.json",
    "sheets_sync_jobs.json",
    "google_oauth_tokens.json",
    "google_oauth_state.json",
    "meli_oauth_state.json",
    # Publicador module-owned
    "publicador_drafts.json",
    "publicador_history.json",
    # Autoreply module-owned
    "autoreply_templates.json",
    "autoreply_history.json",
    # FullDock module-owned
    "fulldock_inventory_rules.json",
    "fulldock_history.json",
    # FullDock module-owned (from topic stock-locations)
    "stock_locations.json",
    # Catalog competition tracking (SheetSeller + FullDock + Repricer)
    # from topic catalog_item_competition_status
    "competition_snapshots.json",
}
ACTIVE_NON_PLACEHOLDER_SCHEMAS = {
    "audit_log.json",
    "bootstrap_jobs.json",
    "bootstrap_dispatcher_locks.json",
    "claims.json",
    "events.json",
    "items.json",
    "meli_accounts.json",
    "messages.json",
    "module_registry.json",
    "orders.json",
    "rate_limit_counters.json",
    "questions.json",
    "repricer_history.json",
    "repricer_rules.json",
    "sheets_exports.json",
    "sheets_sync_jobs.json",
    "google_oauth_tokens.json",
    "google_oauth_state.json",
    "meli_oauth_state.json",
    "shipments.json",
    "users.json",
    "webhook_events.json",
    "processed_events.json",
    "publicador_drafts.json",
    "publicador_history.json",
    "autoreply_templates.json",
    "autoreply_history.json",
    "fulldock_inventory_rules.json",
    "fulldock_history.json",
}


def test_placeholder_schema_files_exist_and_reference_phase_three() -> None:
    assert SCHEMAS_DIR.exists()

    actual_files = {path.name for path in SCHEMAS_DIR.glob("*.json")}
    assert actual_files == EXPECTED_FILES

    for file_name in sorted(EXPECTED_FILES - ACTIVE_NON_PLACEHOLDER_SCHEMAS):
        payload = json.loads((SCHEMAS_DIR / file_name).read_text(encoding="utf-8"))
        assert isinstance(payload, dict)
        assert "P3" in payload.get("$comment", "")
