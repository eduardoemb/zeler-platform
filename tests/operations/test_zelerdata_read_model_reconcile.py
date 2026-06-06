from __future__ import annotations

import json
from pathlib import Path

import pytest
from infra.operations.zelerdata_read_model_reconcile import (
    DEFAULT_PHASE2_DRY_RUN_SCOPES,
    DEFAULT_PHASE2_PREFLIGHT_TARGETS,
    PrivateExportRecord,
    ReadModelAggregate,
    ReconciliationSummary,
    build_arg_parser,
    build_phase2_runtime_contract,
    build_reconciliation_request,
    validate_reconciliation_safety,
)


def test_reconciliation_request_parses_june_1_to_4_range_and_defaults_to_dry_run() -> None:
    args = build_arg_parser().parse_args(
        [
            "--seller-id",
            "82453304",
            "--date-from",
            "2026-06-01",
            "--date-to",
            "2026-06-04",
            "--confirm-approved-runtime",
        ]
    )

    request = build_reconciliation_request(args)

    assert request.date_range.date_from == "2026-06-01"
    assert request.date_range.date_to == "2026-06-04"
    assert request.date_range.date_to_exclusive == "2026-06-05T00:00:00Z"
    assert request.dry_run is True
    assert request.approved_runtime is True
    assert request.write_enabled is False
    assert request.max_orders is None


def test_reconciliation_request_rejects_local_runtime_even_for_dry_run() -> None:
    args = build_arg_parser().parse_args(
        [
            "--seller-id",
            "82453304",
            "--date-from",
            "2026-06-01",
            "--date-to",
            "2026-06-04",
        ]
    )

    with pytest.raises(SystemExit, match="--confirm-approved-runtime is required"):
        validate_reconciliation_safety(args)


def test_reconciliation_write_requires_separate_production_write_confirmation() -> None:
    parser = build_arg_parser()
    missing_write_approval = parser.parse_args(
        [
            "--seller-id",
            "82453304",
            "--date-from",
            "2026-06-01",
            "--date-to",
            "2026-06-04",
            "--confirm-approved-runtime",
            "--write",
        ]
    )

    with pytest.raises(SystemExit, match="--confirm-production-write is required with --write"):
        validate_reconciliation_safety(missing_write_approval)

    approved = parser.parse_args(
        [
            "--seller-id",
            "82453304",
            "--date-from",
            "2026-06-01",
            "--date-to",
            "2026-06-04",
            "--confirm-approved-runtime",
            "--write",
            "--confirm-production-write",
        ]
    )

    validate_reconciliation_safety(approved)
    assert build_reconciliation_request(approved).write_enabled is True


def test_reconciliation_summary_is_aggregate_only_and_has_stop_criteria() -> None:
    summary = ReconciliationSummary(
        seller_id="82453304",
        date_from="2026-06-01",
        date_to="2026-06-04",
        dry_run=True,
        approved_runtime=True,
        write_enabled=False,
        aggregates=(
            ReadModelAggregate(
                read_model="orders",
                expected_count=10,
                persisted_count=7,
                missing_count=3,
                complete_count=6,
                na_count=1,
                zero_count=2,
                positive_count=4,
                unauthorized_count=0,
                error_count=0,
            ),
        ),
        stop_criteria=("unsanitized_output", "unexpected_count_delta"),
        private_export_refs=("export:orders:count-10",),
        raw_context={
            "order_ids": ["2001"],
            "shipment_id": "3001",
            "item_id": "MLA1",
            "buyer": {"name": "SENTINEL BUYER NAME"},
            "receiver_address": {"street_name": "SENTINEL STREET"},
            "raw_payload": {"id": "2001"},
            "env": {"MONGO_URI": "SENTINEL_DB_URI_VALUE"},
            "access_token": "SENTINEL_ACCESS_TOKEN_VALUE",
            "client_secret": "SENTINEL_CLIENT_SECRET_VALUE",
        },
    )

    sanitized = summary.to_sanitized_dict()
    sanitized_json = json.dumps(sanitized, sort_keys=True)

    assert sanitized["seller_scope"] == "provided"
    assert sanitized["date_range"] == {"from": "2026-06-01", "to": "2026-06-04"}
    assert sanitized["mode"] == "dry_run"
    assert sanitized["aggregates"] == [
        {
            "read_model": "orders",
            "expected_count": 10,
            "persisted_count": 7,
            "missing_count": 3,
            "complete_count": 6,
            "na_count": 1,
            "zero_count": 2,
            "positive_count": 4,
            "unauthorized_count": 0,
            "error_count": 0,
        }
    ]
    assert sanitized["stop_criteria"] == ["unsanitized_output", "unexpected_count_delta"]
    assert sanitized["private_export_refs"] == ["export:orders:count-10"]
    for forbidden in (
        "seller_id",
        "raw_context",
        "82453304",
        "2001",
        "3001",
        "MLA1",
        "SENTINEL BUYER NAME",
        "SENTINEL STREET",
        "raw_payload",
        "MONGO_URI",
        "SENTINEL_DB_URI_VALUE",
        "SENTINEL_ACCESS_TOKEN_VALUE",
        "SENTINEL_CLIENT_SECRET_VALUE",
    ):
        assert forbidden not in sanitized_json


def test_reconciliation_runbook_documents_flags_stop_criteria_and_runtime_boundary() -> None:
    doc_path = Path("docs/sheets/zelerdata-read-model-reconciliation.md")

    content = doc_path.read_text(encoding="utf-8")

    for required in (
        "--confirm-approved-runtime",
        "--confirm-production-write",
        "--dry-run",
        "--write",
        "--max-orders",
        "approved VM/VPC/runtime",
        "Do not query production Mongo locally",
        "unsanitized output",
        "unexpected count delta",
        "index anomaly",
        "no secrets, tokens, raw IDs, raw payloads, buyer/address PII, or raw env values",
    ):
        assert required in content


def test_reconciliation_runbook_documents_phase2_read_only_contract() -> None:
    doc_path = Path("docs/sheets/zelerdata-read-model-reconciliation.md")

    content = doc_path.read_text(encoding="utf-8")

    for required in (
        "Phase 2 read-only contract",
        "--emit-phase2-contract",
        "orders, shipments, items, sheets_item_formula_rows, "
        "sheets_item_sku_index, and status models",
        "expected, persisted, missing, complete, NA, 0, and >0 counts",
        "private export IDs/counts",
        "realized fees where implemented; otherwise keep NA",
        "Live runtime execution is pending until an approved VM/VPC/runtime command is available",
    ):
        assert required in content


def test_phase2_runtime_contract_lists_read_only_preflight_targets_and_counters() -> None:
    contract = build_phase2_runtime_contract(
        date_from="2026-06-01",
        date_to="2026-06-04",
        private_exports=(
            PrivateExportRecord(
                read_model="orders",
                export_ref="private-export/orders/june-1-4",
                document_count=17,
            ),
        ),
    )

    sanitized = contract.to_sanitized_dict()
    targets = {target["read_model"]: target for target in sanitized["preflight_targets"]}

    assert sanitized["phase"] == "phase2_read_only_runtime_preflight_dry_run"
    assert sanitized["approved_runtime_only"] is True
    assert sanitized["production_writes_enabled"] is False
    assert sanitized["date_range"] == {"from": "2026-06-01", "to": "2026-06-04"}
    assert set(targets) == set(DEFAULT_PHASE2_PREFLIGHT_TARGETS)
    assert targets["orders"]["required_counters"] == [
        "expected_count",
        "persisted_count",
        "missing_count",
        "complete_count",
        "na_count",
        "zero_count",
        "positive_count",
    ]
    assert targets["sheets_item_formula_rows"]["distribution_fields"] == [
        "listing_type",
        "current_status",
        "sale_price",
        "listing_fixed_fee",
        "unit_cost",
        "realized_shipping_cost",
        "realized_fee",
        "pack_or_cart_id",
        "buyer_address_presence",
    ]
    assert targets["item_status_transitions"]["truth_boundary"] == (
        "observed transitions only; do not synthesize paused/status history"
    )
    assert sanitized["private_exports"] == [
        {
            "read_model": "orders",
            "export_ref": "private-export/orders/june-1-4",
            "document_count": 17,
        }
    ]


def test_phase2_runtime_contract_lists_dry_run_scopes_and_stop_conditions_without_pii() -> None:
    contract = build_phase2_runtime_contract(
        date_from="2026-06-01",
        date_to="2026-06-04",
        raw_context={
            "seller_id": "82453304",
            "order_id": "2001",
            "shipment_id": "3001",
            "item_id": "MLA1",
            "buyer": {"name": "SENTINEL BUYER NAME"},
            "receiver_address": {"street_name": "SENTINEL STREET"},
            "raw_payload": {"id": "2001"},
            "MONGO_URI": "SENTINEL_DB_URI_VALUE",
            "access_token": "SENTINEL_ACCESS_TOKEN_VALUE",
        },
    )

    sanitized = contract.to_sanitized_dict()
    sanitized_json = json.dumps(sanitized, sort_keys=True)

    assert sanitized["dry_run_scopes"] == list(DEFAULT_PHASE2_DRY_RUN_SCOPES)
    assert sanitized["realized_fees_policy"] == "only_where_read_model_support_exists_else_NA"
    assert sanitized["buyer_address_policy"] == "presence_counts_only"
    assert sanitized["stop_conditions"] == [
        "unsanitized_output",
        "unauthorized_pii",
        "validator_or_index_anomaly",
        "auth_error",
        "unexpected_delta",
    ]
    for forbidden in (
        "82453304",
        "2001",
        "3001",
        "MLA1",
        "SENTINEL BUYER NAME",
        "SENTINEL STREET",
        "raw_payload",
        "MONGO_URI",
        "SENTINEL_DB_URI_VALUE",
        "SENTINEL_ACCESS_TOKEN_VALUE",
    ):
        assert forbidden not in sanitized_json


def test_reconciliation_cli_can_emit_phase2_contract_from_approved_runtime_only(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from infra.operations import zelerdata_read_model_reconcile

    result = zelerdata_read_model_reconcile.main(
        [
            "--seller-id",
            "82453304",
            "--date-from",
            "2026-06-01",
            "--date-to",
            "2026-06-04",
            "--dry-run",
            "--confirm-approved-runtime",
            "--emit-phase2-contract",
        ]
    )

    output = json.loads(capsys.readouterr().out)

    assert result == 0
    assert output["phase2_contract"]["approved_runtime_only"] is True
    assert output["phase2_contract"]["dry_run_scopes"] == list(DEFAULT_PHASE2_DRY_RUN_SCOPES)
    assert "82453304" not in json.dumps(output, sort_keys=True)
