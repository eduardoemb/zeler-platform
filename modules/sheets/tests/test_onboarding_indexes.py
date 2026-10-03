from __future__ import annotations

import json
from pathlib import Path

from infra.mongo.readiness import _validate_index_files

ROOT = Path(__file__).resolve().parents[3]


def test_onboarding_indexes_bind_query_scope_without_expiring_history() -> None:
    definitions = {
        name: json.loads((ROOT / "infra/mongo/indexes" / f"{name}.json").read_text())
        for name in (
            "sheets_full_operations",
            "sheets_history_pending_records",
            "sheets_history_backfill_plans",
            "sheets_history_receipts",
        )
    }
    assert all(
        "expireAfterSeconds" not in index.get("options", {})
        for indexes in definitions.values()
        for index in indexes
    )
    assert any(
        index["keys"] == {"seller_id": 1, "operation_id": 1}
        and index["options"].get("unique") is True
        for index in definitions["sheets_full_operations"]
    )
    assert any(
        list(index["keys"])[-2:] == ["state", "resource_id"]
        for index in definitions["sheets_history_pending_records"]
    )
    assert any(
        index["options"]["name"] == "onboarding_due"
        and index["keys"] == {"policy_version": 1, "next_cycle_at": 1}
        for index in definitions["sheets_history_backfill_plans"]
    )
    assert any(
        index["keys"]
        == {
            "acquisition_id": 1,
            "seller_id": 1,
            "read_model": 1,
            "generation": 1,
            "pass_number": 1,
            "kind": 1,
            "resource_id": 1,
        }
        for index in definitions["sheets_history_receipts"]
    )
    summary, findings = _validate_index_files(ROOT / "infra/mongo/indexes")
    assert not findings
    assert summary["index_file_errors"] == 0
