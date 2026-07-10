from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from zeler_platform_core.devoluciones_readiness import (
    DevolucionesOperationContext,
    acquire_devoluciones_operation,
    finish_devoluciones_operation,
    guarded_devoluciones_write,
    maintain_devoluciones_heartbeat,
    new_devoluciones_attempt_token,
    stable_devoluciones_operation_id,
)

READ_MODELS: tuple[str, ...] = (
    "orders",
    "shipments",
    "items",
    "questions",
    "claims",
    "catalog_product_snapshots",
    "catalog_buybox_snapshots",
    "sheets_item_formula_rows",
    "sheets_item_sku_index",
    "item_status_states",
    "item_status_transitions",
    "price_history_snapshots",
    "stockout_snapshots",
    "stock_time_metrics",
    "catalog_time_metrics",
    "full_withdrawals",
)
DEFAULT_PHASE2_PREFLIGHT_TARGETS: tuple[str, ...] = READ_MODELS
DEFAULT_PHASE2_DRY_RUN_SCOPES: tuple[str, ...] = (
    "orders",
    "shipments",
    "pack_or_cart_id",
    "buyer_address_presence_only",
    "realized_shipping",
    "realized_fees_where_implemented",
)
PHASE2_REQUIRED_COUNTERS: tuple[str, ...] = (
    "expected_count",
    "persisted_count",
    "missing_count",
    "complete_count",
    "na_count",
    "zero_count",
    "positive_count",
)
PHASE2_FORMULA_DISTRIBUTION_FIELDS: tuple[str, ...] = (
    "listing_type",
    "current_status",
    "sale_price",
    "listing_fixed_fee",
    "unit_cost",
    "realized_shipping_cost",
    "realized_fee",
    "pack_or_cart_id",
    "buyer_address_presence",
)
PHASE2_STOP_CONDITIONS: tuple[str, ...] = (
    "unsanitized_output",
    "unauthorized_pii",
    "validator_or_index_anomaly",
    "auth_error",
    "unexpected_delta",
)
DEFAULT_STOP_CRITERIA: tuple[str, ...] = (
    "unsanitized_output",
    "unauthorized_pii",
    "unexpected_count_delta",
    "validator_error",
    "auth_error",
    "formula_regression",
)
_OBSERVED_ONLY_MODELS = {
    "item_status_states",
    "item_status_transitions",
    "price_history_snapshots",
    "stockout_snapshots",
}
_OBSERVED_SNAPSHOT_SOURCES = frozenset(
    {
        "sheets_event_persistence",
        "sheets_backfill",
        "historical_meli_backfill",
        "manual_reconciliation",
    }
)
_OBSERVATION_BASES = frozenset({"current_observed", "event_observed", "zeler_first_observed"})
_STOCK_STATES = frozenset({"in_stock", "out_of_stock"})
_SOURCE_DEFERRED_MODELS = {"stock_time_metrics", "catalog_time_metrics", "full_withdrawals"}
_SOURCE_GATED_MODELS = frozenset(_SOURCE_DEFERRED_MODELS)
_SOURCE_GATED_INTERVAL_AGGREGATE_MODELS = frozenset({"stock_time_metrics", "catalog_time_metrics"})
_SOURCE_GATED_LEGACY_MODE = "legacy_imported"
_SOURCE_GATED_OBSERVED_MODE = "observed_only"
DEVOLUCIONES_MARKER_VALIDITY = timedelta(minutes=30)
_SOURCE_GATED_SOURCES = frozenset(
    {
        "legacy_history_import",
        "sheets_backfill",
        "historical_meli_backfill",
        "manual_reconciliation",
    }
)
_HISTORICAL_MELI_MODELS = ("orders", "shipments", "items", "questions", "claims")
_BOUNDED_REF_MODELS = {
    "shipments",
    "items",
    "catalog_product_snapshots",
    "catalog_buybox_snapshots",
    "price_history_snapshots",
    "stockout_snapshots",
}
_READ_MODEL_COLLECTIONS: Mapping[str, str] = {
    "catalog_product_snapshots": "sheets_catalog_product_snapshots",
    "catalog_buybox_snapshots": "sheets_catalog_buybox_snapshots",
    "price_history_snapshots": "sheets_price_history_snapshots",
    "stockout_snapshots": "sheets_stockout_snapshots",
    "stock_time_metrics": "sheets_stock_time_metrics",
    "catalog_time_metrics": "sheets_catalog_time_metrics",
    "full_withdrawals": "sheets_full_withdrawals",
}
_RECONCILED_MARKER_MODELS = {
    "questions",
    "claims",
    "catalog_product_snapshots",
    "catalog_buybox_snapshots",
    "price_history_snapshots",
    "stockout_snapshots",
    "stock_time_metrics",
    "catalog_time_metrics",
    "full_withdrawals",
}
_COMPLETE_FIELDS: Mapping[str, tuple[str, ...]] = {
    "orders": ("items.0",),
    "shipments": ("order_id", "status"),
    "items": ("status", "last_meli_sync_at"),
    "questions": ("date_created", "status", "item_id", "text", "from_user_id"),
    "claims": ("date_created", "order_id", "item_id", "status", "returned_quantity"),
    "catalog_product_snapshots": (
        "catalog_product_id",
        "snapshot_at",
        "source",
    ),
    "catalog_buybox_snapshots": (
        "item_id",
        "catalog_product_id",
        "buybox_status",
        "snapshot_at",
        "source",
    ),
    "sheets_item_formula_rows": ("current.status", "current.price", "current.listing_type_id"),
    "sheets_item_sku_index": ("normalized_sku", "item_id", "source"),
    "item_status_states": ("current_status", "last_observed_at"),
    "item_status_transitions": ("from_status", "to_status", "observed_at"),
    "price_history_snapshots": (
        "prices.0.price",
        "prices.0.status",
        "prices.0.observed_at",
        "prices.0.observation_basis",
        "snapshot_at",
        "source",
        "observation_basis",
    ),
    "stockout_snapshots": (
        "observed_at",
        "source",
        "observation_basis",
        "stock_state",
        "current_stock",
    ),
    "stock_time_metrics": (
        "date_from",
        "date_to",
        "total_hours",
        "source",
        "history_basis",
        "coverage_basis",
    ),
    "catalog_time_metrics": (
        "date_from",
        "date_to",
        "available_hours",
        "source",
        "history_basis",
        "coverage_basis",
    ),
    "full_withdrawals": (
        "withdrawal_id",
        "created_at",
        "source",
        "history_basis",
        "coverage_basis",
    ),
}
HistoricalMeliExpectedSource = Callable[..., Awaitable[Any]]
_DISTRIBUTION_FIELDS: Mapping[str, Mapping[str, str]] = {
    "orders": {"status": "status"},
    "shipments": {"status": "status"},
    "items": {"status": "status"},
    "sheets_item_formula_rows": {
        "current_status": "current.status",
        "listing_type": "current.listing_type_id",
    },
    "sheets_item_sku_index": {"source": "source", "identity_level": "identity_level"},
    "item_status_states": {"current_status": "current_status"},
    "item_status_transitions": {"from_status": "from_status", "to_status": "to_status"},
    "price_history_snapshots": {
        "source": "source",
        "observation_basis": "observation_basis",
    },
    "stockout_snapshots": {
        "stock_state": "stock_state",
        "source": "source",
        "observation_basis": "observation_basis",
    },
    "stock_time_metrics": {"source": "source", "coverage_basis": "coverage_basis"},
    "catalog_time_metrics": {"source": "source", "coverage_basis": "coverage_basis"},
    "full_withdrawals": {"source": "source", "coverage_basis": "coverage_basis"},
}
_PRESENCE_FIELDS: Mapping[str, Mapping[str, str]] = {
    "orders": {
        "buyer_id": "buyer_id",
        "meli_pack_id": "meli_pack_id",
        "shipment_id": "shipment_id",
    },
    "shipments": {
        "receiver_address": "receiver_address",
        "real_shipping_cost.seller_cost": "real_shipping_cost.seller_cost",
    },
    "items": {
        "seller_shipping_cost": "seller_shipping_cost",
        "listing_fee_projection": "listing_fee_projection",
        "listing_price_fixed_fee": "listing_price_fixed_fee",
        "current_promotion": "current_promotion",
    },
    "sheets_item_formula_rows": {
        "sale_price": "current.price",
        "listing_fixed_fee": "current.listing_price_fixed_fee.fixed_fee",
        "unit_cost": "current.unit_cost",
        "realized_shipping_cost": "current.seller_shipping_cost",
        "realized_fee": "current.listing_fee_projection.sale_fee_amount",
        "pack_or_cart_id": "current.pack_or_cart_id",
        "buyer_address_presence": "current.buyer_address_presence",
    },
}


@dataclass(frozen=True)
class ReconciliationDateRange:
    date_from: str
    date_to: str
    start: datetime
    end_exclusive: datetime

    @property
    def date_to_exclusive(self) -> str:
        return _format_utc(self.end_exclusive)


@dataclass(frozen=True)
class ReconciliationRequest:
    seller_id: str
    date_range: ReconciliationDateRange
    dry_run: bool
    approved_runtime: bool
    write_enabled: bool
    include_buyer_address_pii: bool
    controls: ReconciliationControls
    repair_observed_pause_basis: bool = False

    @property
    def max_orders(self) -> int | None:
        return self.controls.max_orders


@dataclass(frozen=True)
class ReconciliationControls:
    max_orders: int | None = None
    max_items: int | None = None
    max_shipments: int | None = None
    concurrency: int = 1
    sleep_ms: int = 0
    error_threshold: int | None = None
    stop_on_rate_limit: bool = False
    resume_after_order_id: str | None = field(default=None, repr=False)

    def to_sanitized_dict(self) -> dict[str, Any]:
        sanitized: dict[str, Any] = {}
        for field_name in (
            "max_orders",
            "max_items",
            "max_shipments",
            "concurrency",
            "sleep_ms",
            "error_threshold",
            "stop_on_rate_limit",
        ):
            value = getattr(self, field_name)
            if value not in (None, False) and not (field_name in {"concurrency"} and value == 1):
                sanitized[field_name] = value
        if self.resume_after_order_id:
            sanitized["resume_cursor"] = "provided"
        return sanitized


@dataclass(frozen=True)
class ReadModelIssue:
    read_model: str
    code: str
    message: str
    count: int | None = None

    def to_sanitized_dict(self) -> dict[str, int | str]:
        sanitized: dict[str, int | str] = {"code": self.code}
        if self.count is not None:
            sanitized["count"] = self.count
        return sanitized


@dataclass(frozen=True)
class ExpectedReadModelCounts:
    counts: Mapping[str, int | None]
    refs: Mapping[str, frozenset[str]] = field(default_factory=dict, repr=False)
    truth_mode: Mapping[str, str] = field(default_factory=dict)
    issues: tuple[ReadModelIssue, ...] = ()
    source_fingerprint: str | None = None
    read_model_fingerprint: str | None = None


@dataclass(frozen=True)
class HistoricalMeliExpectedCounts:
    counts: Mapping[str, int | None]
    refs: Mapping[str, frozenset[str]] = field(default_factory=dict, repr=False)
    truth_mode: Mapping[str, str] = field(default_factory=dict)
    issues: tuple[ReadModelIssue, ...] = ()
    source_fingerprint: str | None = None
    read_model_fingerprint: str | None = None


@dataclass(frozen=True)
class ReadModelAggregate:
    read_model: str
    expected_count: int | None
    persisted_count: int | None
    missing_count: int | None
    complete_count: int | None = 0
    na_count: int = 0
    zero_count: int = 0
    positive_count: int = 0
    unauthorized_count: int = 0
    error_count: int = 0
    truth_mode: str = "expected"
    field_counts: Mapping[str, Mapping[str, int]] = field(default_factory=dict)
    issues: tuple[ReadModelIssue, ...] = ()
    out_of_range_by_date_created: int = 0

    def to_sanitized_dict(self) -> dict[str, Any]:
        sanitized: dict[str, Any] = {
            "read_model": self.read_model,
            "expected_count": self.expected_count,
            "persisted_count": self.persisted_count,
            "missing_count": self.missing_count,
            "complete_count": self.complete_count,
        }
        if (
            self.truth_mode != "expected"
            or self.expected_count is None
            or self.missing_count is None
            or self.field_counts
            or self.issues
        ):
            sanitized["truth_mode"] = self.truth_mode
        legacy_counters = {
            "na_count": self.na_count,
            "zero_count": self.zero_count,
            "positive_count": self.positive_count,
            "unauthorized_count": self.unauthorized_count,
            "error_count": self.error_count,
        }
        if any(legacy_counters.values()):
            sanitized.update(legacy_counters)
        if self.out_of_range_by_date_created:
            sanitized["out_of_range_by_date_created"] = self.out_of_range_by_date_created
        if self.field_counts:
            sanitized["field_counts"] = _sorted_field_counts(self.field_counts)
        if self.issues:
            sanitized["issues"] = [issue.to_sanitized_dict() for issue in self.issues]
        return sanitized


@dataclass(frozen=True)
class Phase2PreflightTarget:
    read_model: str
    required_counters: tuple[str, ...] = PHASE2_REQUIRED_COUNTERS
    distribution_fields: tuple[str, ...] = ()
    truth_boundary: str | None = None

    def to_sanitized_dict(self) -> dict[str, Any]:
        sanitized: dict[str, Any] = {
            "read_model": self.read_model,
            "required_counters": list(self.required_counters),
            "distribution_fields": list(self.distribution_fields),
        }
        if self.truth_boundary is not None:
            sanitized["truth_boundary"] = self.truth_boundary
        return sanitized


@dataclass(frozen=True)
class PrivateExportRecord:
    read_model: str
    export_ref: str
    document_count: int

    def to_sanitized_dict(self) -> dict[str, int | str]:
        return {
            "read_model": self.read_model,
            "export_ref": self.export_ref,
            "document_count": self.document_count,
        }


@dataclass(frozen=True)
class Phase2RuntimeContract:
    date_from: str
    date_to: str
    preflight_targets: tuple[Phase2PreflightTarget, ...]
    dry_run_scopes: tuple[str, ...] = DEFAULT_PHASE2_DRY_RUN_SCOPES
    private_exports: tuple[PrivateExportRecord, ...] = ()
    stop_conditions: tuple[str, ...] = PHASE2_STOP_CONDITIONS
    raw_context: dict[str, Any] = field(default_factory=dict, repr=False)

    def to_sanitized_dict(self) -> dict[str, Any]:
        return {
            "phase": "phase2_read_only_runtime_preflight_dry_run",
            "approved_runtime_only": True,
            "production_writes_enabled": False,
            "date_range": {"from": self.date_from, "to": self.date_to},
            "preflight_targets": [target.to_sanitized_dict() for target in self.preflight_targets],
            "dry_run_scopes": list(self.dry_run_scopes),
            "buyer_address_policy": "presence_counts_only",
            "realized_fees_policy": "only_where_read_model_support_exists_else_NA",
            "private_exports": [export.to_sanitized_dict() for export in self.private_exports],
            "stop_conditions": list(self.stop_conditions),
        }


@dataclass(frozen=True)
class ReconciliationSummary:
    seller_id: str
    date_from: str
    date_to: str
    dry_run: bool
    approved_runtime: bool
    write_enabled: bool
    aggregates: tuple[ReadModelAggregate, ...] = ()
    stop_criteria: tuple[str, ...] = DEFAULT_STOP_CRITERIA
    private_export_refs: tuple[str, ...] = ()
    phase2_contract: Phase2RuntimeContract | None = None
    controls: ReconciliationControls | None = None
    write_counts: Mapping[str, int] = field(default_factory=dict)
    repair_counts: Mapping[str, int] = field(default_factory=dict)
    raw_context: dict[str, Any] = field(default_factory=dict, repr=False)

    def to_sanitized_dict(self) -> dict[str, Any]:
        sanitized: dict[str, Any] = {
            "seller_scope": "provided",
            "date_range": {"from": self.date_from, "to": self.date_to},
            "mode": "dry_run" if self.dry_run else "write",
            "approved_runtime": self.approved_runtime,
            "write_enabled": self.write_enabled,
            "aggregates": [aggregate.to_sanitized_dict() for aggregate in self.aggregates],
            "stop_criteria": list(self.stop_criteria),
            "private_export_refs": list(self.private_export_refs),
        }
        if self.phase2_contract is not None:
            sanitized["phase2_contract"] = self.phase2_contract.to_sanitized_dict()
        if self.controls is not None:
            controls = self.controls.to_sanitized_dict()
            if controls:
                sanitized["controls"] = controls
        if self.write_counts:
            sanitized["write_counts"] = dict(sorted(self.write_counts.items()))
        if self.repair_counts:
            sanitized["repair_counts"] = dict(sorted(self.repair_counts.items()))
        return sanitized


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Plan a sanitized ZelerData read-model reconciliation from approved runtime only."
        )
    )
    parser.add_argument("--seller-id", required=True, help="Seller id to reconcile.")
    parser.add_argument("--date-from", required=True, help="Inclusive start date (YYYY-MM-DD).")
    parser.add_argument("--date-to", required=True, help="Inclusive end date (YYYY-MM-DD).")
    parser.add_argument(
        "--max-orders",
        "--limit",
        dest="max_orders",
        type=_positive_int,
        help="Optional maximum order count for bounded trial runs.",
    )
    parser.add_argument(
        "--max-items",
        type=_positive_int,
        help="Optional maximum item count for bounded write/reconciliation trials.",
    )
    parser.add_argument(
        "--max-shipments",
        type=_positive_int,
        help="Optional maximum shipment count for bounded write/reconciliation trials.",
    )
    parser.add_argument(
        "--concurrency",
        type=_positive_int,
        default=1,
        help="Maximum concurrent runtime fetch/write units. Defaults to 1.",
    )
    parser.add_argument(
        "--sleep-ms",
        type=_non_negative_int,
        default=0,
        help="Milliseconds to sleep between bounded write phases for rate-limit protection.",
    )
    parser.add_argument(
        "--error-threshold",
        type=_positive_int,
        help="Stop write planning when sanitized error counts reach this threshold.",
    )
    parser.add_argument(
        "--stop-on-rate-limit",
        action="store_true",
        help="Stop instead of continuing when the expected source reports rate limiting.",
    )
    parser.add_argument(
        "--resume-after-order-id",
        help="Private resume cursor. Output reports only whether a cursor was provided.",
    )
    parser.add_argument(
        "--confirm-approved-runtime",
        action="store_true",
        help="Required for every run; confirms approved VM/VPC/runtime execution.",
    )
    parser.add_argument(
        "--confirm-production-write",
        action="store_true",
        help="Required with --write; confirms separate production-write authorization.",
    )
    parser.add_argument(
        "--include-buyer-address-pii",
        action="store_true",
        help="Allow bounded PII processing in approved runtime; output remains aggregate-only.",
    )
    parser.add_argument(
        "--emit-phase2-contract",
        action="store_true",
        help="Include Phase 2 read-only preflight/dry-run contract in sanitized output.",
    )
    parser.add_argument(
        "--repair-observed-pause-basis",
        action="store_true",
        help=(
            "Plan or run bounded observed pause-basis repair for current paused rows missing "
            "paused_since. Dry-run reports sanitized counters only."
        ),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        default=True,
        help="Plan/summarize only; do not write (default).",
    )
    mode.add_argument(
        "--write",
        action="store_false",
        dest="dry_run",
        help="Enable a write phase after separate production-write authorization.",
    )
    return parser


def validate_reconciliation_safety(args: argparse.Namespace) -> None:
    if not str(args.seller_id).strip():
        raise SystemExit("seller-id is required")
    if not bool(args.confirm_approved_runtime):
        raise SystemExit("--confirm-approved-runtime is required")
    if not bool(args.dry_run) and not bool(args.confirm_production_write):
        raise SystemExit("--confirm-production-write is required with --write")
    if not bool(args.dry_run) and bool(args.repair_observed_pause_basis) and args.max_items is None:
        raise SystemExit("--max-items is required with --repair-observed-pause-basis --write")
    if bool(args.include_buyer_address_pii) and args.max_orders is None:
        raise SystemExit("--max-orders is required with --include-buyer-address-pii")


def build_reconciliation_request(args: argparse.Namespace) -> ReconciliationRequest:
    validate_reconciliation_safety(args)
    date_range = parse_reconciliation_date_range(str(args.date_from), str(args.date_to))
    dry_run = bool(args.dry_run)
    return ReconciliationRequest(
        seller_id=str(args.seller_id).strip(),
        date_range=date_range,
        dry_run=dry_run,
        approved_runtime=bool(args.confirm_approved_runtime),
        write_enabled=not dry_run,
        include_buyer_address_pii=bool(args.include_buyer_address_pii),
        controls=ReconciliationControls(
            max_orders=args.max_orders,
            max_items=args.max_items,
            max_shipments=args.max_shipments,
            concurrency=args.concurrency,
            sleep_ms=args.sleep_ms,
            error_threshold=args.error_threshold,
            stop_on_rate_limit=bool(args.stop_on_rate_limit),
            resume_after_order_id=(
                str(args.resume_after_order_id).strip()
                if args.resume_after_order_id is not None
                else None
            ),
        ),
        repair_observed_pause_basis=bool(args.repair_observed_pause_basis),
    )


@dataclass(frozen=True)
class RuntimeDatabase:
    db: Any
    client: Any = field(repr=False)

    def close(self) -> None:
        self.client.close()


@dataclass(frozen=True)
class RuntimeHistoricalMeliGateways:
    gateway: Any = field(repr=False)
    order_detail_gateway: Any = field(repr=False)
    catalog_gateway: Any = field(repr=False)


def parse_reconciliation_date_range(date_from: str, date_to: str) -> ReconciliationDateRange:
    start_date = _parse_date(date_from, field_name="date-from")
    end_date = _parse_date(date_to, field_name="date-to")
    if end_date < start_date:
        raise ValueError("date-to must be on or after date-from")
    start = datetime.combine(start_date, datetime.min.time(), tzinfo=UTC)
    end_exclusive = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    return ReconciliationDateRange(
        date_from=start_date.isoformat(),
        date_to=end_date.isoformat(),
        start=start,
        end_exclusive=end_exclusive,
    )


async def collect_expected_read_model_counts(
    *,
    db: Any,
    request: ReconciliationRequest,
    historical_meli_source: HistoricalMeliExpectedSource | None = None,
) -> ExpectedReadModelCounts:
    counts: dict[str, int | None] = {
        read_model: None
        for read_model in (
            *_HISTORICAL_MELI_MODELS,
            "item_status_states",
            "item_status_transitions",
            "price_history_snapshots",
            "stockout_snapshots",
            "stock_time_metrics",
            "catalog_time_metrics",
            "full_withdrawals",
        )
    }
    refs: dict[str, frozenset[str]] = {}
    truth_mode = {read_model: "unavailable" for read_model in _HISTORICAL_MELI_MODELS}
    truth_mode.update(
        {"item_status_states": "observed_only", "item_status_transitions": "observed_only"}
    )
    truth_mode.update(
        {
            "price_history_snapshots": "observed_current",
            "stockout_snapshots": "observed_current",
            "stock_time_metrics": "source_deferred",
            "catalog_time_metrics": "source_deferred",
            "full_withdrawals": "source_deferred",
        }
    )
    issues: list[ReadModelIssue] = []
    source_fingerprint: str | None = None
    read_model_fingerprint: str | None = None

    source = historical_meli_source or _collect_historical_meli_expected_counts
    try:
        historical_summary = await source(db=db, request=request)
    except Exception as exc:  # noqa: BLE001 - expected source anomalies are sanitized.
        issue_code = _classify_expected_source_issue(exc)
        issues.extend(
            _issue(read_model, issue_code, "historical expected source unavailable")
            for read_model in _HISTORICAL_MELI_MODELS
        )
    else:
        historical = _historical_meli_expected_counts(historical_summary)
        counts.update(historical.counts)
        refs.update(historical.refs)
        truth_mode.update(historical.truth_mode)
        issues.extend(historical.issues)
        source_fingerprint = historical.source_fingerprint
        read_model_fingerprint = historical.read_model_fingerprint

    try:
        from zeler_sheets.sheetseller_backfill import (
            run_order_line_identity_backfill,
            run_sheetseller_backfill,
        )

        sheets_summary = await run_sheetseller_backfill(
            db=db,
            seller_id=request.seller_id,
            dry_run=True,
        )
        order_line_summary = await run_order_line_identity_backfill(
            db=db,
            seller_id=request.seller_id,
            dry_run=True,
            date_from=request.date_range.date_from,
            date_to=request.date_range.date_to,
        )
    except (AttributeError, ImportError, RuntimeError, TypeError, ValueError):
        for read_model in ("sheets_item_formula_rows", "sheets_item_sku_index"):
            counts[read_model] = None
            truth_mode[read_model] = "unavailable"
            issues.append(_issue(read_model, "expected_unavailable", "dry-run source unavailable"))
    else:
        counts["sheets_item_formula_rows"] = sheets_summary.formula_row_upserts
        counts["sheets_item_sku_index"] = (
            sheets_summary.sku_index_upserts + order_line_summary.sku_index_upserts
        )
        truth_mode["sheets_item_formula_rows"] = "expected"
        truth_mode["sheets_item_sku_index"] = "expected"

    catalog_expected = await _collect_catalog_expected_counts(db=db, seller_id=request.seller_id)
    counts.update(catalog_expected.counts)
    refs.update(catalog_expected.refs)
    truth_mode.update(catalog_expected.truth_mode)
    issues.extend(catalog_expected.issues)

    observed_expected = await _collect_remaining_observed_expected_counts(
        db=db, seller_id=request.seller_id, max_items=request.controls.max_items
    )
    counts.update(observed_expected.counts)
    refs.update(observed_expected.refs)
    truth_mode.update(observed_expected.truth_mode)
    issues.extend(observed_expected.issues)

    source_gated_expected = await _collect_source_gated_expected_counts(db=db, request=request)
    counts.update(source_gated_expected.counts)
    refs.update(source_gated_expected.refs)
    truth_mode.update(source_gated_expected.truth_mode)
    issues = [issue for issue in issues if issue.read_model not in _SOURCE_GATED_MODELS]
    issues.extend(source_gated_expected.issues)

    return ExpectedReadModelCounts(
        counts=counts,
        refs=refs,
        truth_mode=truth_mode,
        issues=tuple(issues),
        source_fingerprint=source_fingerprint,
        read_model_fingerprint=read_model_fingerprint,
    )


async def collect_reconciliation_counts(
    *,
    db: Any,
    request: ReconciliationRequest,
    expected: ExpectedReadModelCounts,
    read_models: Sequence[str] = READ_MODELS,
) -> ReconciliationSummary:
    if not request.seller_id:
        raise ValueError("seller-id is required")

    aggregates = tuple(
        [
            await _collect_read_model_aggregate(
                db=db, request=request, expected=expected, read_model=read_model
            )
            for read_model in read_models
        ]
    )
    return ReconciliationSummary(
        seller_id=request.seller_id,
        date_from=request.date_range.date_from,
        date_to=request.date_range.date_to,
        dry_run=request.dry_run,
        approved_runtime=request.approved_runtime,
        write_enabled=request.write_enabled,
        aggregates=aggregates,
        controls=request.controls,
    )


def create_runtime_db() -> RuntimeDatabase:
    mongo_uri = os.environ.get("MONGO_URI")
    mongo_db_name = os.environ.get("MONGO_DB")
    if not mongo_uri or not mongo_db_name:
        raise SystemExit("runtime Mongo configuration is required")

    from motor.motor_asyncio import AsyncIOMotorClient

    client: AsyncIOMotorClient[Any] = AsyncIOMotorClient(mongo_uri)
    return RuntimeDatabase(db=client[mongo_db_name], client=client)


def create_runtime_historical_meli_gateways() -> RuntimeHistoricalMeliGateways:
    from google.cloud import kms_v1

    from zeler_platform_core.auth.meli_gateway_auth import MeliGatewayAuth
    from zeler_platform_core.clients.meli_gateway_client import MeliGatewayClient
    from zeler_sheets.historical_meli_backfill import (
        DEFAULT_CATALOG_GATEWAY_MODULE_ID,
        DEFAULT_GATEWAY_BASE_URL,
        DEFAULT_GATEWAY_MODULE_ID,
        DEFAULT_ORDER_DETAIL_GATEWAY_MODULE_ID,
    )

    gateway_base_url = os.environ.get("GATEWAY_BASE_URL", DEFAULT_GATEWAY_BASE_URL)
    kms_client = kms_v1.KeyManagementServiceClient()
    gateway = MeliGatewayClient(
        gateway_base_url,
        MeliGatewayAuth(DEFAULT_GATEWAY_MODULE_ID, kms_client),
    )
    order_detail_gateway = gateway
    if DEFAULT_ORDER_DETAIL_GATEWAY_MODULE_ID != DEFAULT_GATEWAY_MODULE_ID:
        order_detail_gateway = MeliGatewayClient(
            gateway_base_url,
            MeliGatewayAuth(DEFAULT_ORDER_DETAIL_GATEWAY_MODULE_ID, kms_client),
        )
    if DEFAULT_CATALOG_GATEWAY_MODULE_ID == DEFAULT_GATEWAY_MODULE_ID:
        catalog_gateway = gateway
    elif DEFAULT_CATALOG_GATEWAY_MODULE_ID == DEFAULT_ORDER_DETAIL_GATEWAY_MODULE_ID:
        catalog_gateway = order_detail_gateway
    else:
        catalog_gateway = MeliGatewayClient(
            gateway_base_url,
            MeliGatewayAuth(DEFAULT_CATALOG_GATEWAY_MODULE_ID, kms_client),
        )
    return RuntimeHistoricalMeliGateways(
        gateway=gateway,
        order_detail_gateway=order_detail_gateway,
        catalog_gateway=catalog_gateway,
    )


def _runtime_catalog_gateway(gateways: RuntimeHistoricalMeliGateways) -> Any:
    return getattr(gateways, "catalog_gateway", gateways.order_detail_gateway)


async def _collect_historical_meli_expected_counts(
    *, db: Any, request: ReconciliationRequest
) -> Any:
    from zeler_sheets.historical_meli_backfill import run_historical_meli_backfill

    gateways = create_runtime_historical_meli_gateways()
    return await run_historical_meli_backfill(
        db=db,
        gateway=gateways.gateway,
        order_detail_gateway=gateways.order_detail_gateway,
        catalog_gateway=_runtime_catalog_gateway(gateways),
        seller_id=request.seller_id,
        date_from=request.date_range.date_from,
        date_to=request.date_range.date_to,
        dry_run=True,
        approved_runtime=request.approved_runtime,
        include_buyer_address_pii=request.include_buyer_address_pii,
        max_orders=request.max_orders,
        max_items=request.controls.max_items,
        max_shipments=request.controls.max_shipments,
        resume_after_order_id=request.controls.resume_after_order_id,
        include_questions=True,
        include_claims=True,
        include_catalog_snapshots=True,
    )


async def execute_reconciliation_write(
    *,
    db: Any,
    request: ReconciliationRequest,
    operation: DevolucionesOperationContext,
) -> dict[str, int]:
    if request.dry_run or not request.write_enabled:
        return {}
    if not request.approved_runtime:
        raise ValueError("approved_runtime is required for write reconciliation")
    if request.controls.sleep_ms > 0:
        await asyncio.sleep(request.controls.sleep_ms / 1000)

    from zeler_sheets.historical_meli_backfill import run_historical_meli_backfill
    from zeler_sheets.remaining_read_model_writers import run_remaining_observed_read_model_seed
    from zeler_sheets.sheetseller_backfill import (
        run_item_detail_enrichment,
        run_sheetseller_backfill,
    )
    from zeler_sheets.source_gated_read_model_writers import run_source_gated_read_model_import

    gateways = create_runtime_historical_meli_gateways()
    summary = await run_historical_meli_backfill(
        db=db,
        gateway=gateways.gateway,
        order_detail_gateway=gateways.order_detail_gateway,
        catalog_gateway=_runtime_catalog_gateway(gateways),
        seller_id=request.seller_id,
        date_from=request.date_range.date_from,
        date_to=request.date_range.date_to,
        dry_run=False,
        approved_runtime=request.approved_runtime,
        include_buyer_address_pii=request.include_buyer_address_pii,
        max_orders=request.controls.max_orders,
        max_items=request.controls.max_items,
        max_shipments=request.controls.max_shipments,
        resume_after_order_id=request.controls.resume_after_order_id,
        include_questions=True,
        include_claims=True,
        include_catalog_snapshots=True,
        operation=operation,
    )
    _enforce_write_count_safety_controls(
        _write_counts_from_summary(summary), controls=request.controls
    )
    item_summaries = await _run_bounded_item_detail_enrichment(
        db=db,
        gateway=gateways.gateway,
        request=request,
        item_ids=_summary_ref_list(summary, "item_ids"),
        enrichment_runner=run_item_detail_enrichment,
    )
    _enforce_write_count_safety_controls(
        _combined_write_counts(
            historical_summary=summary,
            item_summaries=item_summaries,
            formula_summary=None,
            observed_summary=None,
            source_gated_summary=None,
        ),
        controls=request.controls,
    )
    formula_summary = await run_sheetseller_backfill(
        db=db,
        seller_id=request.seller_id,
        dry_run=False,
    )
    observed_summary = None
    if _observed_seed_write_is_safely_scoped(request.controls):
        observed_summary = await run_remaining_observed_read_model_seed(
            db=db,
            seller_id=request.seller_id,
            dry_run=False,
            max_items=request.controls.max_items,
        )
    source_gated_summary = None
    source_gated_import_skipped = False
    if _source_gated_import_is_safely_scoped(request.controls):
        source_gated_summary = await run_source_gated_read_model_import(
            db=db,
            seller_id=request.seller_id,
            date_from=request.date_range.start,
            date_to=request.date_range.end_exclusive,
            dry_run=False,
            max_items=request.controls.max_items,
        )
    else:
        source_gated_import_skipped = True
    counts = _combined_write_counts(
        historical_summary=summary,
        item_summaries=item_summaries,
        formula_summary=formula_summary,
        observed_summary=observed_summary,
        source_gated_summary=source_gated_summary,
    )
    if source_gated_import_skipped:
        counts["source_gated_import_skipped_bounded_controls"] = 1
    _enforce_write_count_safety_controls(counts, controls=request.controls)
    return counts


async def execute_observed_pause_basis_repair(
    *,
    db: Any,
    request: ReconciliationRequest,
    repair_runner: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, int]:
    if request.write_enabled and not request.approved_runtime:
        raise ValueError("approved_runtime is required for observed pause-basis repair")
    if request.write_enabled and request.controls.max_items is None:
        raise ValueError("--max-items is required with --repair-observed-pause-basis --write")
    if repair_runner is None:
        from zeler_sheets.sheetseller_backfill import run_observed_pause_basis_repair

        repair_runner = run_observed_pause_basis_repair
    summary = await repair_runner(
        db=db,
        seller_id=request.seller_id,
        dry_run=request.dry_run or not request.write_enabled,
        limit=request.controls.max_items,
    )
    return _observed_pause_basis_repair_counts(summary)


async def _run_bounded_item_detail_enrichment(
    *,
    db: Any,
    gateway: Any,
    request: ReconciliationRequest,
    item_ids: Sequence[str],
    enrichment_runner: Callable[..., Awaitable[Any]],
) -> tuple[Any, ...]:
    if not item_ids:
        return ()
    semaphore = asyncio.Semaphore(request.controls.concurrency)

    async def run_one(item_id: str) -> Any:
        async with semaphore:
            return await enrichment_runner(
                db=db,
                gateway=gateway,
                seller_id=request.seller_id,
                dry_run=False,
                sale_price_enabled=True,
                listing_fixed_fee_enabled=True,
                item_ids=(item_id,),
            )

    return tuple(await asyncio.gather(*(run_one(item_id) for item_id in item_ids)))


def build_phase2_runtime_contract(
    *,
    date_from: str,
    date_to: str,
    private_exports: Sequence[PrivateExportRecord] = (),
    raw_context: dict[str, Any] | None = None,
) -> Phase2RuntimeContract:
    date_range = parse_reconciliation_date_range(date_from, date_to)
    return Phase2RuntimeContract(
        date_from=date_range.date_from,
        date_to=date_range.date_to,
        preflight_targets=tuple(
            _phase2_preflight_target(read_model) for read_model in DEFAULT_PHASE2_PREFLIGHT_TARGETS
        ),
        private_exports=tuple(private_exports),
        raw_context=raw_context or {},
    )


async def _collect_read_model_aggregate(
    *,
    db: Any,
    request: ReconciliationRequest,
    expected: ExpectedReadModelCounts,
    read_model: str,
) -> ReadModelAggregate:
    expected_count = expected.counts.get(read_model)
    truth_mode = expected.truth_mode.get(
        read_model,
        "observed_only" if read_model in _OBSERVED_ONLY_MODELS else "expected",
    )
    if expected_count is None and truth_mode == "expected":
        truth_mode = "unavailable"
    expected_issues = tuple(issue for issue in expected.issues if issue.read_model == read_model)
    refs = expected.refs.get(read_model)
    if read_model in _BOUNDED_REF_MODELS and refs is None:
        issues = (
            *expected_issues,
            ReadModelIssue(
                read_model=read_model,
                code="expected_refs_unavailable",
                message="bounded expected refs unavailable",
            ),
        )
        if not expected_issues and expected_count is None:
            issues = (
                ReadModelIssue(
                    read_model=read_model,
                    code="expected_unavailable",
                    message="expected source unavailable",
                ),
                *issues,
            )
        return ReadModelAggregate(
            read_model=read_model,
            expected_count=expected_count,
            persisted_count=None,
            missing_count=None,
            complete_count=None,
            truth_mode=truth_mode,
            issues=issues,
        )

    collection = db[_read_model_collection_name(read_model)]
    filter_refs = None if read_model == "orders" else refs
    filter_spec = _read_model_filter(read_model, request, filter_refs)
    try:
        persisted_count = await collection.count_documents(filter_spec)
        complete_count = await _complete_count(collection, read_model, filter_spec)
        field_counts = await _read_model_field_counts(
            collection=collection,
            read_model=read_model,
            filter_spec=filter_spec,
            persisted_count=persisted_count,
        )
    except Exception as exc:  # noqa: BLE001 - query details must not leak to output.
        return ReadModelAggregate(
            read_model=read_model,
            expected_count=expected_count,
            persisted_count=None,
            missing_count=None,
            complete_count=None,
            truth_mode=truth_mode,
            issues=(
                *expected_issues,
                ReadModelIssue(
                    read_model=read_model,
                    code=_classify_query_issue(exc),
                    message="read query unavailable",
                ),
            ),
        )
    missing_count: int | None
    out_of_range_by_date_created = 0
    if read_model == "orders" and refs is not None and truth_mode == "expected":
        missing_count, out_of_range_by_date_created = await _order_date_delta_counts(
            collection, request, refs
        )
    else:
        missing_count = (
            max(expected_count - persisted_count, 0)
            if expected_count is not None
            and truth_mode in {"expected", "observed_current", _SOURCE_GATED_LEGACY_MODE}
            else None
        )
    issues = expected_issues
    if expected_count is None and truth_mode == "unavailable" and not issues:
        issues = (
            ReadModelIssue(
                read_model=read_model,
                code="expected_unavailable",
                message="expected source unavailable",
            ),
        )
    return ReadModelAggregate(
        read_model=read_model,
        expected_count=expected_count,
        persisted_count=persisted_count,
        missing_count=missing_count,
        out_of_range_by_date_created=out_of_range_by_date_created,
        complete_count=complete_count,
        truth_mode=truth_mode,
        field_counts=field_counts,
        issues=issues,
    )


async def write_complete_read_model_freshness_markers(
    *,
    db: Any,
    request: ReconciliationRequest,
    summary: ReconciliationSummary,
    expected: ExpectedReadModelCounts | None = None,
    operation: DevolucionesOperationContext,
) -> dict[str, int]:
    if request.dry_run or not request.write_enabled:
        return {}
    if _has_bounded_reconciliation_controls(request.controls):
        return {}
    if not request.approved_runtime:
        raise ValueError("approved_runtime is required for marker write")
    current_utc_day = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    if request.date_range.end_exclusive > current_utc_day:
        raise ValueError("DEVOLUCIONES readiness requires a closed UTC range")

    written = 0
    devoluciones_written = 0

    async def write(session: Any) -> None:
        nonlocal devoluciones_written, written
        collection = db["sheets_read_model_freshness"]
        session_kwargs = {"session": session} if session is not None else {}
        for aggregate in summary.aggregates:
            if aggregate.read_model not in _RECONCILED_MARKER_MODELS:
                continue
            if aggregate.read_model == "claims":
                continue
            if not _aggregate_has_complete_scoped_coverage(aggregate):
                continue
            if aggregate.read_model in {"price_history_snapshots", "stockout_snapshots"} and (
                aggregate.expected_count is None or aggregate.expected_count <= 0
            ):
                continue
            marker_id = f"{request.seller_id}:{aggregate.read_model}"
            updated_at = datetime.now(UTC)
            filter_spec = {
                "_id": marker_id,
                "seller_id": request.seller_id,
                "read_model": aggregate.read_model,
            }
            if aggregate.read_model in _SOURCE_GATED_INTERVAL_AGGREGATE_MODELS:
                date_from = request.date_range.start
                reconciled_until = request.date_range.end_exclusive
            else:
                existing_marker = await collection.find_one(filter_spec, **session_kwargs)
                if not _marker_range_can_merge(
                    existing_marker,
                    requested_start=request.date_range.start,
                    requested_end=request.date_range.end_exclusive,
                ):
                    continue
                date_from, reconciled_until = _merged_marker_authoritative_range(
                    existing_marker,
                    requested_start=request.date_range.start,
                    requested_end=request.date_range.end_exclusive,
                )
            marker_fields: dict[str, Any] = {
                "_id": marker_id,
                "seller_id": request.seller_id,
                "read_model": aggregate.read_model,
                "state": "reconciled",
                "date_from": date_from,
                "fresh_until": reconciled_until,
                "reconciled_until": reconciled_until,
                "last_event_synced_at": date_from,
                "updated_at": updated_at,
                "source": "zelerdata_read_model_reconcile",
                "schema_version": 1,
            }
            if aggregate.read_model in _SOURCE_GATED_MODELS:
                marker_fields["coverage_basis"] = _SOURCE_GATED_LEGACY_MODE
            await collection.update_one(
                filter_spec,
                {"$set": marker_fields},
                upsert=True,
                **session_kwargs,
            )
            written += 1

        claims_aggregate = next(
            (aggregate for aggregate in summary.aggregates if aggregate.read_model == "claims"),
            None,
        )
        if claims_aggregate is None:
            return
        if not _request_encloses_required_devoluciones_coverage(
            request=request,
            operation=operation,
        ):
            return
        expected_claim_ids, expected_read_model_fingerprint = _validated_devoluciones_marker_inputs(
            expected=expected,
            aggregate=claims_aggregate,
            operation=operation,
        )
        from zeler_sheets.devoluciones_reconciliation import verify_devoluciones_read_model

        await verify_devoluciones_read_model(
            db=db,
            seller_id=request.seller_id,
            date_from=request.date_range.start,
            date_to=request.date_range.end_exclusive,
            expected_claim_ids=expected_claim_ids,
            expected_read_model_fingerprint=expected_read_model_fingerprint,
            session=session,
        )
        marker_id = f"{request.seller_id}:devoluciones"
        await collection.update_one(
            {
                "_id": marker_id,
                "seller_id": request.seller_id,
                "read_model": "devoluciones",
            },
            [
                {
                    "$set": {
                        "_id": marker_id,
                        "seller_id": request.seller_id,
                        "read_model": "devoluciones",
                        "state": "reconciled",
                        "date_from": request.date_range.start,
                        "fresh_until": request.date_range.end_exclusive,
                        "reconciled_until": request.date_range.end_exclusive,
                        "last_event_synced_at": request.date_range.start,
                        "valid_until": {
                            "$dateAdd": {
                                "startDate": "$$NOW",
                                "unit": "second",
                                "amount": int(DEVOLUCIONES_MARKER_VALIDITY.total_seconds()),
                            }
                        },
                        "updated_at": "$$NOW",
                        "source": "zelerdata_devoluciones_joint_reconcile",
                        "revision": operation.attempt_token,
                        "proof_fingerprint": expected_read_model_fingerprint,
                        "schema_version": 1,
                    }
                }
            ],
            upsert=True,
            **session_kwargs,
        )
        devoluciones_written = 1

    await guarded_devoluciones_write(
        db=db,
        operation=operation,
        seller_id=request.seller_id,
        checkpoint={
            "phase": "marker_publication",
            "date_from": request.date_range.date_from,
            "date_to": request.date_range.date_to,
        },
        writer=write,
    )
    counts: dict[str, int] = {}
    if written:
        counts["freshness_markers_written"] = written
    if devoluciones_written:
        counts["devoluciones_markers_written"] = devoluciones_written
    return counts


def _request_encloses_required_devoluciones_coverage(
    *,
    request: ReconciliationRequest,
    operation: DevolucionesOperationContext,
) -> bool:
    required_start = operation.required_coverage_start
    required_end = operation.required_coverage_end
    if required_start is None and required_end is None:
        return True
    if required_start is None or required_end is None or required_start >= required_end:
        return False
    return (
        request.date_range.start <= required_start
        and request.date_range.end_exclusive >= required_end
    )


def _validated_devoluciones_marker_inputs(
    *,
    expected: ExpectedReadModelCounts | None,
    aggregate: ReadModelAggregate,
    operation: DevolucionesOperationContext,
) -> tuple[frozenset[str], str]:
    if expected is None:
        raise RuntimeError("authoritative DEVOLUCIONES expected inventory is required")
    expected_count = expected.counts.get("claims")
    expected_ids = expected.refs.get("claims")
    if (
        isinstance(expected_count, bool)
        or not isinstance(expected_count, int)
        or expected_count < 0
        or expected_ids is None
        or len(expected_ids) != expected_count
        or expected.truth_mode.get("claims") != "expected"
        or not expected.source_fingerprint
        or not expected.read_model_fingerprint
        or expected.source_fingerprint != operation.source_fingerprint
        or any(issue.read_model == "claims" for issue in expected.issues)
    ):
        raise RuntimeError("authoritative DEVOLUCIONES source proof is incomplete")
    if (
        aggregate.expected_count != expected_count
        or aggregate.persisted_count != expected_count
        or aggregate.missing_count != 0
        or aggregate.issues
        or aggregate.error_count != 0
    ):
        raise RuntimeError("DEVOLUCIONES claims reconciliation is incomplete")
    return expected_ids, expected.read_model_fingerprint


def _aggregate_has_complete_scoped_coverage(aggregate: ReadModelAggregate) -> bool:
    if (
        aggregate.read_model in _SOURCE_GATED_MODELS
        and aggregate.truth_mode != _SOURCE_GATED_LEGACY_MODE
    ):
        return False
    return (
        aggregate.expected_count is not None
        and aggregate.persisted_count == aggregate.expected_count
        and aggregate.complete_count is not None
        and aggregate.complete_count >= aggregate.expected_count
        and aggregate.missing_count == 0
        and not aggregate.issues
        and aggregate.error_count == 0
    )


def _has_bounded_reconciliation_controls(controls: ReconciliationControls) -> bool:
    for field_name, value in vars(controls).items():
        if not (field_name.startswith(("max_", "limit_")) or field_name.startswith("resume_")):
            continue
        if value is not None and value is not False:
            return True
    return False


def _observed_seed_write_is_safely_scoped(controls: ReconciliationControls) -> bool:
    return not _has_non_item_bounded_reconciliation_controls(controls)


def _source_gated_import_is_safely_scoped(controls: ReconciliationControls) -> bool:
    return not _has_non_item_bounded_reconciliation_controls(controls)


def _has_non_item_bounded_reconciliation_controls(controls: ReconciliationControls) -> bool:
    return any(
        value is not None and value is not False
        for value in (
            controls.max_orders,
            controls.max_shipments,
            controls.resume_after_order_id,
        )
    )


def _merged_marker_authoritative_range(
    existing_marker: Any,
    *,
    requested_start: datetime,
    requested_end: datetime,
) -> tuple[datetime, datetime]:
    existing_range = _marker_coverage_range(existing_marker)
    if existing_range is None:
        return requested_start, requested_end
    existing_start, existing_end = existing_range
    return min(existing_start, requested_start), max(existing_end, requested_end)


def _marker_range_can_merge(
    existing_marker: Any, *, requested_start: datetime, requested_end: datetime
) -> bool:
    existing_range = _marker_coverage_range(existing_marker)
    if existing_range is None:
        return True
    existing_start, existing_end = existing_range
    if existing_end < existing_start:
        return False
    return requested_start <= existing_end and existing_start <= requested_end


def _marker_coverage_range(existing_marker: Any) -> tuple[datetime, datetime] | None:
    if not (isinstance(existing_marker, Mapping) and existing_marker.get("state") == "reconciled"):
        return None
    date_from = existing_marker.get("date_from")
    start = _coerce_utc_datetime(date_from)
    if date_from is None:
        start = _coerce_utc_datetime(existing_marker.get("last_event_synced_at"))
    end = _coerce_utc_datetime(existing_marker.get("reconciled_until"))
    if end is None:
        end = _coerce_utc_datetime(existing_marker.get("fresh_until"))
    if start is None or end is None:
        return None
    return (start, end)


async def _complete_count(collection: Any, read_model: str, filter_spec: dict[str, Any]) -> int:
    if read_model == "questions":
        return await _complete_questions_count(collection, filter_spec)
    if read_model == "claims":
        return int(await collection.count_documents(_complete_claims_filter(filter_spec)))
    if read_model == "price_history_snapshots":
        return await _complete_price_history_count(collection, filter_spec)
    if read_model == "stockout_snapshots":
        return await _complete_stockout_count(collection, filter_spec)
    if read_model in _SOURCE_GATED_MODELS:
        return await _complete_source_gated_count(collection, read_model, filter_spec)
    required_fields = _COMPLETE_FIELDS.get(read_model, ())
    if not required_fields:
        return int(await collection.count_documents(filter_spec))
    return int(await collection.count_documents(_with_present_fields(filter_spec, required_fields)))


async def _complete_price_history_count(collection: Any, filter_spec: dict[str, Any]) -> int:
    complete = 0
    async for document in _matching_documents(collection, filter_spec):
        complete += int(_price_history_snapshot_is_complete(document))
    return complete


async def _complete_stockout_count(collection: Any, filter_spec: dict[str, Any]) -> int:
    complete = 0
    async for document in _matching_documents(collection, filter_spec):
        complete += int(_stockout_snapshot_is_complete(document))
    return complete


async def _complete_source_gated_count(
    collection: Any, read_model: str, filter_spec: dict[str, Any]
) -> int:
    complete = 0
    async for document in _matching_documents(collection, filter_spec):
        complete += int(_source_gated_document_is_complete(document, read_model=read_model))
    return complete


async def _matching_documents(collection: Any, filter_spec: dict[str, Any]) -> AsyncIterator[Any]:
    cursor = collection.find(filter_spec)
    if callable(to_list := getattr(cursor, "to_list", None)):
        for document in await to_list(length=None):
            yield document
        return
    async for document in cursor:
        yield document


def _price_history_snapshot_is_complete(document: Any) -> bool:
    if not isinstance(document, Mapping):
        return False
    if not _is_datetime_like(document.get("snapshot_at")):
        return False
    if not _allowed_observed_source(document.get("source")):
        return False
    if not _allowed_observation_basis(document.get("observation_basis")):
        return False
    prices = document.get("prices")
    if not isinstance(prices, Sequence) or isinstance(prices, (str, bytes, bytearray)):
        return False
    if not prices:
        return False
    return all(_price_entry_is_complete(entry) for entry in prices)


def _price_entry_is_complete(entry: Any) -> bool:
    if not isinstance(entry, Mapping):
        return False
    return (
        _numeric_observed_price(entry.get("price"))
        and _is_present(entry.get("status"))
        and _is_datetime_like(entry.get("observed_at"))
        and _allowed_observation_basis(entry.get("observation_basis"))
    )


def _stockout_snapshot_is_complete(document: Any) -> bool:
    if not isinstance(document, Mapping):
        return False
    if not _is_datetime_like(document.get("observed_at")):
        return False
    out_since = document.get("out_of_stock_since")
    if out_since is not None and not _is_datetime_like(out_since):
        return False
    if not _allowed_observed_source(document.get("source")):
        return False
    if not _allowed_observation_basis(document.get("observation_basis")):
        return False
    stock_state = str(document.get("stock_state") or "").strip()
    if stock_state not in _STOCK_STATES:
        return False
    current_stock = document.get("current_stock")
    if not isinstance(current_stock, int) or isinstance(current_stock, bool) or current_stock < 0:
        return False
    if stock_state == "out_of_stock" and current_stock != 0:
        return False
    if stock_state == "in_stock" and current_stock == 0:
        return False
    status = document.get("status")
    return status is None or _is_present(status)


def _source_gated_document_is_complete(document: Any, *, read_model: str) -> bool:
    if not isinstance(document, Mapping):
        return False
    if str(document.get("source") or "").strip() not in _SOURCE_GATED_SOURCES:
        return False
    if str(document.get("history_basis") or "").strip() not in {
        _SOURCE_GATED_LEGACY_MODE,
        _SOURCE_GATED_OBSERVED_MODE,
    }:
        return False
    if str(document.get("coverage_basis") or "").strip() not in {
        _SOURCE_GATED_LEGACY_MODE,
        _SOURCE_GATED_OBSERVED_MODE,
    }:
        return False
    if read_model in {"stock_time_metrics", "catalog_time_metrics"}:
        if not _is_datetime_like(document.get("date_from")) or not _is_datetime_like(
            document.get("date_to")
        ):
            return False
        if read_model == "stock_time_metrics":
            return _numeric_observed_price(document.get("total_hours"))
        return _numeric_observed_price(document.get("available_hours"))
    if read_model == "full_withdrawals":
        return _is_present(document.get("withdrawal_id")) and _is_datetime_like(
            document.get("created_at")
        )
    return False


def _allowed_observed_source(value: Any) -> bool:
    return str(value or "").strip() in _OBSERVED_SNAPSHOT_SOURCES


def _allowed_observation_basis(value: Any) -> bool:
    return str(value or "").strip() in _OBSERVATION_BASES


def _is_datetime_like(value: Any) -> bool:
    return isinstance(value, datetime)


def _numeric_observed_price(value: Any) -> bool:
    if value is None or isinstance(value, (bool, str, bytes, bytearray, Mapping)):
        return False
    if value.__class__.__name__ == "Decimal128":
        return True
    return isinstance(value, (int, float, Decimal))


def _is_present(value: Any) -> bool:
    return value is not None and not (isinstance(value, str) and not value.strip())


async def _complete_questions_count(collection: Any, filter_spec: dict[str, Any]) -> int:
    complete_filter = _with_present_fields(
        filter_spec,
        _COMPLETE_FIELDS["questions"],
    )
    complete_filter["$or"] = [
        {"status": {"$ne": "ANSWERED"}},
        _with_present_fields({}, ("answer.text", "answer.date_created")),
    ]
    return int(await collection.count_documents(complete_filter))


def _complete_claims_filter(filter_spec: dict[str, Any]) -> dict[str, Any]:
    complete_filter = _with_present_fields(filter_spec, ("date_created",))
    for field_path in ("order_id", "item_id", "status"):
        complete_filter[field_path] = {"$exists": True, "$nin": [None, ""]}
    complete_filter["returned_quantity"] = {"$gte": 1}
    return complete_filter


async def _order_date_delta_counts(
    collection: Any,
    request: ReconciliationRequest,
    refs: frozenset[str],
) -> tuple[int, int]:
    if not refs:
        return (0, 0)
    id_filter = {"seller_id": request.seller_id, "_id": {"$in": sorted(refs)}}
    date_filter = {
        **id_filter,
        "date_created": {
            "$gte": request.date_range.start,
            "$lt": request.date_range.end_exclusive,
        },
    }
    present_by_id = int(await collection.count_documents(id_filter))
    present_in_range = int(await collection.count_documents(date_filter))
    return (max(len(refs) - present_by_id, 0), max(present_by_id - present_in_range, 0))


async def _read_model_field_counts(
    *,
    collection: Any,
    read_model: str,
    filter_spec: dict[str, Any],
    persisted_count: int,
) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for output_key, field_path in _DISTRIBUTION_FIELDS.get(read_model, {}).items():
        counts[output_key] = await _distribution_counts(collection, filter_spec, field_path)
    for output_key, field_path in _PRESENCE_FIELDS.get(read_model, {}).items():
        counts[output_key] = await _presence_counts(
            collection,
            filter_spec,
            field_path=field_path,
            persisted_count=persisted_count,
        )
    return counts


async def _distribution_counts(
    collection: Any, filter_spec: dict[str, Any], field_path: str
) -> dict[str, int]:
    cursor = collection.aggregate(
        [
            {"$match": filter_spec},
            {"$group": {"_id": f"${field_path}", "count": {"$sum": 1}}},
            {"$sort": {"_id": 1}},
        ]
    )
    counts: dict[str, int] = {}
    async for row in cursor:
        key = "missing" if row.get("_id") is None else str(row["_id"])
        counts[key] = int(row.get("count", 0))
    return dict(sorted(counts.items()))


async def _presence_counts(
    collection: Any,
    filter_spec: dict[str, Any],
    *,
    field_path: str,
    persisted_count: int,
) -> dict[str, int]:
    present = await collection.count_documents(_with_present_fields(filter_spec, (field_path,)))
    return {"missing": max(persisted_count - present, 0), "present": present}


def _read_model_filter(
    read_model: str,
    request: ReconciliationRequest,
    refs: frozenset[str] | None,
) -> dict[str, Any]:
    filter_spec: dict[str, Any] = {"seller_id": request.seller_id}
    if read_model in {"orders", "questions", "claims"}:
        filter_spec["date_created"] = {
            "$gte": request.date_range.start,
            "$lt": request.date_range.end_exclusive,
        }
    elif read_model == "item_status_transitions":
        filter_spec["observed_at"] = {
            "$gte": request.date_range.start,
            "$lt": request.date_range.end_exclusive,
        }
    elif read_model in _SOURCE_GATED_INTERVAL_AGGREGATE_MODELS:
        filter_spec["date_from"] = request.date_range.start
        filter_spec["date_to"] = request.date_range.end_exclusive
    elif read_model == "full_withdrawals":
        filter_spec["created_at"] = {
            "$gte": request.date_range.start,
            "$lt": request.date_range.end_exclusive,
        }
    if refs is not None:
        if read_model == "catalog_product_snapshots":
            filter_spec["catalog_product_id"] = {"$in": sorted(refs)}
        elif read_model in {
            "catalog_buybox_snapshots",
            "price_history_snapshots",
            "stockout_snapshots",
            "stock_time_metrics",
            "catalog_time_metrics",
        }:
            filter_spec["item_id"] = {"$in": sorted(refs)}
        else:
            filter_spec["_id"] = {"$in": sorted(refs)}
    return filter_spec


def _read_model_collection_name(read_model: str) -> str:
    return _READ_MODEL_COLLECTIONS.get(read_model, read_model)


def _with_present_fields(filter_spec: dict[str, Any], fields: Sequence[str]) -> dict[str, Any]:
    scoped = dict(filter_spec)
    for field_path in fields:
        scoped[field_path] = {"$exists": True, "$ne": None}
    return scoped


async def _run_cli(args: argparse.Namespace) -> ReconciliationSummary:
    request = build_reconciliation_request(args)
    handle = create_runtime_db()
    try:
        db = handle.db if isinstance(handle, RuntimeDatabase) else handle
        expected = await collect_expected_read_model_counts(db=db, request=request)
        summary = await collect_reconciliation_counts(db=db, request=request, expected=expected)
        repair_counts: dict[str, int] = {}
        if request.repair_observed_pause_basis and not request.write_enabled:
            repair_counts = await execute_observed_pause_basis_repair(db=db, request=request)
            summary = replace(summary, repair_counts=repair_counts)
        if request.write_enabled:
            _enforce_write_safety_controls(summary=summary, controls=request.controls)
            operation_id = stable_devoluciones_operation_id(
                "reconciliation",
                (
                    f"{request.seller_id}:{request.date_range.date_from}:"
                    f"{request.date_range.date_to}:write"
                ),
            )
            operation = await acquire_devoluciones_operation(
                db=db,
                seller_id=request.seller_id,
                scope="devoluciones",
                operation_id=operation_id,
                attempt_token=new_devoluciones_attempt_token(),
                source_fingerprint=expected.source_fingerprint,
            )
            async with maintain_devoluciones_heartbeat(db=db, operation=operation):
                try:
                    write_counts = await execute_reconciliation_write(
                        db=db, request=request, operation=operation
                    )
                    _enforce_write_count_safety_controls(write_counts, controls=request.controls)
                    if request.repair_observed_pause_basis:
                        repair_counts = await execute_observed_pause_basis_repair(
                            db=db, request=request
                        )
                        _enforce_write_count_safety_controls(
                            repair_counts, controls=request.controls
                        )
                    expected = await collect_expected_read_model_counts(db=db, request=request)
                    if expected.source_fingerprint != operation.source_fingerprint:
                        raise RuntimeError(
                            "claim source fingerprint changed before marker publication"
                        )
                    refreshed_summary = await collect_reconciliation_counts(
                        db=db, request=request, expected=expected
                    )
                    marker_counts = await write_complete_read_model_freshness_markers(
                        db=db,
                        request=request,
                        summary=refreshed_summary,
                        expected=expected,
                        operation=operation,
                    )
                    summary = replace(
                        refreshed_summary,
                        write_counts={**write_counts, **marker_counts},
                        repair_counts=repair_counts,
                    )
                except Exception:
                    await finish_devoluciones_operation(
                        db=db,
                        operation=operation,
                        succeeded=False,
                        error_code="reconciliation_failed",
                    )
                    raise
                await finish_devoluciones_operation(
                    db=db,
                    operation=operation,
                    succeeded=True,
                )
        if bool(args.emit_phase2_contract):
            summary = replace(
                summary,
                phase2_contract=build_phase2_runtime_contract(
                    date_from=request.date_range.date_from,
                    date_to=request.date_range.date_to,
                ),
            )
        return summary
    finally:
        if callable(close := getattr(handle, "close", None)):
            close()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        summary = asyncio.run(_run_cli(args))
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    except (AttributeError, RuntimeError, TypeError) as exc:
        raise SystemExit("query_anomaly") from exc
    print(json.dumps(summary.to_sanitized_dict(), sort_keys=True))
    return 0


def _phase2_preflight_target(read_model: str) -> Phase2PreflightTarget:
    distribution_fields = (
        PHASE2_FORMULA_DISTRIBUTION_FIELDS if read_model == "sheets_item_formula_rows" else ()
    )
    truth_boundary = None
    if read_model in {"item_status_states", "item_status_transitions"}:
        truth_boundary = "observed transitions only; do not synthesize paused/status history"
    elif read_model in {"price_history_snapshots", "stockout_snapshots"}:
        truth_boundary = "current/go-forward observed only; do not synthesize history"
    elif read_model in _SOURCE_DEFERRED_MODELS:
        truth_boundary = "source-deferred; do not publish readiness without approved source"
    return Phase2PreflightTarget(
        read_model=read_model,
        distribution_fields=distribution_fields,
        truth_boundary=truth_boundary,
    )


def _parse_date(value: str, *, field_name: str) -> date:
    normalized = value.strip()
    if len(normalized) != 10:
        raise ValueError(f"{field_name} must use YYYY-MM-DD")
    try:
        return date.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{field_name} must use YYYY-MM-DD") from exc


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _coerce_utc_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    return None


def _sorted_field_counts(
    field_counts: Mapping[str, Mapping[str, int]],
) -> dict[str, dict[str, int]]:
    return {field: dict(sorted(counts.items())) for field, counts in sorted(field_counts.items())}


def _historical_meli_expected_counts(summary: Any) -> HistoricalMeliExpectedCounts:
    counts: dict[str, int | None] = {}
    refs: dict[str, frozenset[str]] = {}
    truth_mode: dict[str, str] = {}
    issues: list[ReadModelIssue] = []

    order_refs = _summary_ref_set(summary, "order_ids")
    shipment_refs = _summary_ref_set(summary, "shipment_ids")
    item_refs = _summary_ref_set(summary, "item_ids")
    order_count = _summary_optional_int(summary, "orders_found")
    if order_count is None and order_refs is not None:
        order_count = len(order_refs)

    if order_count is None:
        counts["orders"] = None
        truth_mode["orders"] = "unavailable"
        issues.append(_issue("orders", "expected_unavailable", "historical orders unavailable"))
    else:
        counts["orders"] = order_count
        if order_refs is not None:
            refs["orders"] = order_refs
        truth_mode["orders"] = "expected"

    for read_model, model_refs in (("shipments", shipment_refs), ("items", item_refs)):
        if model_refs is None:
            counts[read_model] = None
            truth_mode[read_model] = "unavailable"
            issues.append(_issue(read_model, "expected_unavailable", "historical refs unavailable"))
            continue
        counts[read_model] = len(model_refs)
        refs[read_model] = model_refs
        truth_mode[read_model] = "expected"

    question_refs = _summary_ref_set(summary, "question_ids")
    question_count = _summary_optional_int(summary, "questions_found")
    question_detail_missing = _summary_optional_int(summary, "question_detail_missing") or 0
    if question_count is None and question_refs is not None:
        question_count = len(question_refs)
    if question_count is None:
        counts["questions"] = None
        truth_mode["questions"] = "unavailable"
        issues.append(
            _issue("questions", "expected_unavailable", "historical questions unavailable")
        )
    else:
        counts["questions"] = question_count
        if question_refs is not None:
            refs["questions"] = question_refs
        truth_mode["questions"] = "expected"
    if question_detail_missing > 0:
        issues.append(
            _issue(
                "questions",
                "question_detail_missing",
                "historical question detail coverage incomplete",
                count=question_detail_missing,
            )
        )

    claim_refs = _summary_ref_set(summary, "claim_ids")
    claim_count = _summary_optional_int(summary, "claims_found")
    if claim_count is None and claim_refs is not None:
        claim_count = len(claim_refs)
    if claim_count is None:
        counts["claims"] = None
        truth_mode["claims"] = "unavailable"
        issues.append(_issue("claims", "expected_unavailable", "historical claims unavailable"))
    else:
        counts["claims"] = claim_count
        if claim_refs is not None:
            refs["claims"] = claim_refs
        truth_mode["claims"] = "expected"

    return HistoricalMeliExpectedCounts(
        counts=counts,
        refs=refs,
        truth_mode=truth_mode,
        issues=tuple(issues),
        source_fingerprint=(
            str(value).strip()
            if (value := _summary_value(summary, "claim_source_fingerprint")) is not None
            and str(value).strip()
            else None
        ),
        read_model_fingerprint=(
            str(value).strip()
            if (value := _summary_value(summary, "claim_read_model_fingerprint")) is not None
            and str(value).strip()
            else None
        ),
    )


async def _collect_catalog_expected_counts(*, db: Any, seller_id: str) -> ExpectedReadModelCounts:
    catalog_product_ids: dict[str, None] = {}
    catalog_item_ids: dict[str, None] = {}
    try:
        cursor = db["items"].find(
            {
                "seller_id": seller_id,
                "catalog_product_id": {"$exists": True, "$ne": None},
            },
            {"_id": 1, "catalog_product_id": 1},
        )
        async for item in cursor:
            item_id = str(item.get("_id") or item.get("id") or "").strip()
            catalog_product_id = str(item.get("catalog_product_id") or "").strip()
            if not item_id or not catalog_product_id:
                continue
            catalog_item_ids.setdefault(item_id, None)
            catalog_product_ids.setdefault(catalog_product_id, None)
    except Exception:  # noqa: BLE001 - expected source anomalies are sanitized.
        return ExpectedReadModelCounts(
            counts={
                "catalog_product_snapshots": None,
                "catalog_buybox_snapshots": None,
            },
            truth_mode={
                "catalog_product_snapshots": "unavailable",
                "catalog_buybox_snapshots": "unavailable",
            },
            issues=(
                _issue(
                    "catalog_product_snapshots",
                    "expected_unavailable",
                    "catalog source unavailable",
                ),
                _issue(
                    "catalog_buybox_snapshots", "expected_unavailable", "catalog source unavailable"
                ),
            ),
        )
    return ExpectedReadModelCounts(
        counts={
            "catalog_product_snapshots": len(catalog_product_ids),
            "catalog_buybox_snapshots": len(catalog_item_ids),
        },
        refs={
            "catalog_product_snapshots": frozenset(catalog_product_ids),
            "catalog_buybox_snapshots": frozenset(catalog_item_ids),
        },
        truth_mode={
            "catalog_product_snapshots": "expected",
            "catalog_buybox_snapshots": "expected",
        },
    )


async def _collect_remaining_observed_expected_counts(
    *, db: Any, seller_id: str, max_items: int | None = None
) -> ExpectedReadModelCounts:
    try:
        from zeler_sheets.remaining_read_model_writers import (
            run_remaining_observed_read_model_seed,
        )

        summary = await run_remaining_observed_read_model_seed(
            db=db,
            seller_id=seller_id,
            dry_run=True,
            max_items=max_items,
        )
    except Exception:  # noqa: BLE001 - expected source anomalies are sanitized.
        return ExpectedReadModelCounts(
            counts={
                "price_history_snapshots": None,
                "stockout_snapshots": None,
                "stock_time_metrics": None,
                "catalog_time_metrics": None,
                "full_withdrawals": None,
            },
            truth_mode={
                "price_history_snapshots": "unavailable",
                "stockout_snapshots": "unavailable",
                "stock_time_metrics": "source_deferred",
                "catalog_time_metrics": "source_deferred",
                "full_withdrawals": "source_deferred",
            },
            issues=(
                _issue(
                    "price_history_snapshots",
                    "expected_unavailable",
                    "current observed price source unavailable",
                ),
                _issue(
                    "stockout_snapshots",
                    "expected_unavailable",
                    "current observed stockout source unavailable",
                ),
                *_deferred_source_issues(),
            ),
        )
    return ExpectedReadModelCounts(
        counts={
            "price_history_snapshots": summary.price_snapshots_planned,
            "stockout_snapshots": summary.stockout_snapshots_planned,
            "stock_time_metrics": None,
            "catalog_time_metrics": None,
            "full_withdrawals": None,
        },
        truth_mode={
            "price_history_snapshots": "observed_current",
            "stockout_snapshots": "observed_current",
            "stock_time_metrics": "source_deferred",
            "catalog_time_metrics": "source_deferred",
            "full_withdrawals": "source_deferred",
        },
        refs={
            "price_history_snapshots": frozenset(summary.price_item_ids),
            "stockout_snapshots": frozenset(summary.stockout_item_ids),
        },
        issues=_deferred_source_issues(),
    )


async def _collect_source_gated_expected_counts(
    *, db: Any, request: ReconciliationRequest
) -> ExpectedReadModelCounts:
    if not _source_gated_import_is_safely_scoped(request.controls):
        return _source_gated_import_skipped_expected_counts()
    try:
        from zeler_sheets.source_gated_read_model_writers import (
            run_source_gated_read_model_import,
        )

        summary = await run_source_gated_read_model_import(
            db=db,
            seller_id=request.seller_id,
            date_from=request.date_range.start,
            date_to=request.date_range.end_exclusive,
            dry_run=True,
            max_items=request.controls.max_items,
        )
    except Exception:  # noqa: BLE001 - source inventory failures must stay sanitized.
        return ExpectedReadModelCounts(
            counts={read_model: None for read_model in _SOURCE_GATED_MODELS},
            truth_mode={read_model: "source_deferred" for read_model in _SOURCE_GATED_MODELS},
            issues=_deferred_source_issues(),
        )

    planned_by_model = {
        "stock_time_metrics": _summary_optional_int(summary, "stock_time_metrics_planned") or 0,
        "catalog_time_metrics": _summary_optional_int(summary, "catalog_time_metrics_planned") or 0,
        "full_withdrawals": _summary_optional_int(summary, "full_withdrawals_planned") or 0,
    }
    basis_by_model = _summary_coverage_basis(summary)
    source_inventory_counts = _summary_source_inventory_counts(summary)
    coverage_complete = _summary_coverage_complete(summary)
    counts: dict[str, int | None] = {}
    refs: dict[str, frozenset[str]] = {}
    truth_mode: dict[str, str] = {}
    issues: list[ReadModelIssue] = []
    for read_model in _SOURCE_GATED_MODELS:
        basis = basis_by_model.get(read_model, _SOURCE_GATED_OBSERVED_MODE)
        planned = planned_by_model[read_model]
        inventory_count = source_inventory_counts.get(read_model, planned)
        complete = coverage_complete.get(read_model, basis == _SOURCE_GATED_LEGACY_MODE)
        is_complete_legacy = basis == _SOURCE_GATED_LEGACY_MODE and complete and planned > 0
        truth_mode[read_model] = basis if is_complete_legacy else _SOURCE_GATED_OBSERVED_MODE
        counts[read_model] = planned if is_complete_legacy else None
        if is_complete_legacy:
            continue
        if inventory_count > 0:
            issues.append(
                _issue(
                    read_model,
                    "source_history_incomplete",
                    "legacy imported history does not cover requested interval",
                )
            )
        else:
            issues.append(
                _issue(
                    read_model,
                    "source_history_absent",
                    "legacy imported history unavailable for requested interval",
                )
            )

    refs.update(_source_gated_refs(summary))
    return ExpectedReadModelCounts(
        counts=counts,
        refs=refs,
        truth_mode=truth_mode,
        issues=tuple(issues),
    )


def _source_gated_import_skipped_expected_counts() -> ExpectedReadModelCounts:
    return ExpectedReadModelCounts(
        counts={read_model: None for read_model in _SOURCE_GATED_MODELS},
        truth_mode={read_model: "source_deferred" for read_model in _SOURCE_GATED_MODELS},
        issues=tuple(
            _issue(
                read_model,
                "source_gated_import_skipped_bounded_controls",
                "source-gated import skipped for non-item bounded reconciliation controls",
            )
            for read_model in _SOURCE_GATED_MODELS
        ),
    )


def _summary_coverage_basis(summary: Any) -> dict[str, str]:
    raw = _summary_value(summary, "coverage_basis")
    if not isinstance(raw, Mapping):
        return {}
    return {
        str(read_model): str(basis)
        for read_model, basis in raw.items()
        if str(read_model) in _SOURCE_GATED_MODELS and str(basis)
    }


def _summary_source_inventory_counts(summary: Any) -> dict[str, int]:
    raw = _summary_value(summary, "source_inventory_counts")
    if not isinstance(raw, Mapping):
        return {}
    counts: dict[str, int] = {}
    for read_model, value in raw.items():
        model = str(read_model)
        if model not in _SOURCE_GATED_MODELS:
            continue
        try:
            count = int(value)
        except (TypeError, ValueError):
            continue
        counts[model] = max(count, 0)
    return counts


def _summary_coverage_complete(summary: Any) -> dict[str, bool]:
    raw = _summary_value(summary, "coverage_complete")
    if not isinstance(raw, Mapping):
        return {}
    return {
        str(read_model): bool(complete)
        for read_model, complete in raw.items()
        if str(read_model) in _SOURCE_GATED_MODELS
    }


def _source_gated_refs(summary: Any) -> dict[str, frozenset[str]]:
    refs: dict[str, frozenset[str]] = {}
    for read_model, field_name in {
        "stock_time_metrics": "stock_time_item_ids",
        "catalog_time_metrics": "catalog_time_item_ids",
        "full_withdrawals": "full_withdrawal_ids",
    }.items():
        if (model_refs := _summary_ref_set(summary, field_name)) is not None:
            refs[read_model] = model_refs
    return refs


def _deferred_source_issues() -> tuple[ReadModelIssue, ...]:
    return (
        _issue(
            "stock_time_metrics",
            "source_deferred",
            "stock time metrics require accepted source semantics",
        ),
        _issue(
            "catalog_time_metrics",
            "source_deferred",
            "catalog time metrics require approved interval source",
        ),
        _issue(
            "full_withdrawals",
            "source_deferred",
            "full withdrawals require approved source/import",
        ),
    )


def _summary_ref_set(summary: Any, name: str) -> frozenset[str] | None:
    raw = _summary_value(summary, name)
    if raw is None:
        return None
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        return None
    refs = {normalized for value in raw if (normalized := str(value).strip())}
    return frozenset(refs)


def _summary_ref_list(summary: Any, name: str) -> list[str]:
    raw = _summary_value(summary, name)
    if raw is None:
        return []
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        return []
    return list(dict.fromkeys(normalized for value in raw if (normalized := str(value).strip())))


def _summary_optional_int(summary: Any, name: str) -> int | None:
    raw = _summary_value(summary, name)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _summary_value(summary: Any, name: str) -> Any:
    if isinstance(summary, Mapping):
        return summary.get(name)
    return getattr(summary, name, None)


def _classify_expected_source_issue(exc: Exception) -> str:
    status_code = _exception_status_code(exc)
    normalized = f"{type(exc).__name__} {exc}".lower()
    if status_code in {401, 403} or isinstance(exc, PermissionError):
        return "auth_error"
    if any(marker in normalized for marker in ("unauthorized", "forbidden", "auth")):
        return "auth_error"
    if hasattr(exc, "retry_after_seconds") or any(
        marker in normalized for marker in ("rate_limit", "ratelimit", "rate limit", "429")
    ):
        return "rate_limit"
    if any(marker in normalized for marker in ("validator", "validation", "index")):
        return "validator_or_index_anomaly"
    return "expected_unavailable"


def _classify_query_issue(exc: Exception) -> str:
    normalized = f"{type(exc).__name__} {exc}".lower()
    if any(marker in normalized for marker in ("validator", "validation", "index")):
        return "validator_or_index_anomaly"
    return "query_anomaly"


def _exception_status_code(exc: Exception) -> int | None:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if isinstance(status_code, int):
        return status_code
    return None


def _issue(read_model: str, code: str, message: str, *, count: int | None = None) -> ReadModelIssue:
    return ReadModelIssue(read_model=read_model, code=code, message=message, count=count)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def _write_counts_from_summary(summary: Any) -> dict[str, int]:
    fields = (
        "planned_orders",
        "planned_items",
        "planned_shipments",
        "planned_questions",
        "planned_claims",
        "planned_catalog_product_snapshots",
        "planned_catalog_buybox_snapshots",
        "written_orders",
        "written_items",
        "written_shipments",
        "written_questions",
        "written_claims",
        "written_catalog_product_snapshots",
        "written_catalog_buybox_snapshots",
        "item_detail_missing",
        "question_detail_missing",
        "redacted_errors",
    )
    counts: dict[str, int] = {}
    for field_name in fields:
        value = getattr(summary, field_name, None)
        if (field_name == "question_detail_missing" and value == 0) or (
            field_name in {"planned_claims", "written_claims"} and value == 0
        ):
            continue
        if isinstance(value, int):
            counts[field_name] = value
    return counts


def _observed_pause_basis_repair_counts(summary: Any) -> dict[str, int]:
    raw = summary.as_dict() if callable(getattr(summary, "as_dict", None)) else {}
    field_map = {
        "candidate_states": "observed_pause_basis_candidate_states",
        "states_planned": "observed_pause_basis_states_planned",
        "states_updated": "observed_pause_basis_states_updated",
        "candidate_formula_rows": "observed_pause_basis_candidate_formula_rows",
        "formula_rows_planned": "observed_pause_basis_formula_rows_planned",
        "formula_rows_updated": "observed_pause_basis_formula_rows_updated",
        "basis_from_existing_status_timestamp": (
            "observed_pause_basis_from_existing_status_timestamp"
        ),
        "basis_from_repair_time": "observed_pause_basis_from_repair_time",
    }
    return {
        output_field: value
        for input_field, output_field in field_map.items()
        if isinstance(value := raw.get(input_field), int) and not isinstance(value, bool)
    }


def _combined_write_counts(
    *,
    historical_summary: Any,
    item_summaries: Sequence[Any],
    formula_summary: Any | None,
    observed_summary: Any | None,
    source_gated_summary: Any | None,
) -> dict[str, int]:
    counts = _write_counts_from_summary(historical_summary)
    counts["item_detail_items_planned"] = sum(
        _summary_int(summary, "items_planned") for summary in item_summaries
    )
    counts["item_detail_items_updated"] = sum(
        _summary_int(summary, "items_updated") for summary in item_summaries
    )
    diagnostics = _item_detail_diagnostic_counts(item_summaries)
    diagnostic_total = sum(diagnostics.values())
    if diagnostic_total:
        counts["item_detail_diagnostics"] = diagnostic_total
        rate_limit_total = sum(
            count
            for reason, count in diagnostics.items()
            if _diagnostic_reason_is_rate_limit(reason)
        )
        if rate_limit_total:
            counts["item_detail_rate_limit"] = rate_limit_total
        counts.update(_sanitized_item_detail_diagnostic_counts(diagnostics))
    if formula_summary is not None:
        counts["formula_row_upserts"] = _summary_int(formula_summary, "formula_row_upserts")
        counts["sku_index_upserts"] = _summary_int(formula_summary, "sku_index_upserts")
    if observed_summary is not None:
        for output_field, summary_field in {
            "price_history_snapshots_planned": "price_snapshots_planned",
            "price_history_snapshots_updated": "price_snapshots_updated",
            "stockout_snapshots_planned": "stockout_snapshots_planned",
            "stockout_snapshots_updated": "stockout_snapshots_updated",
        }.items():
            if value := _summary_int(observed_summary, summary_field):
                counts[output_field] = value
    if source_gated_summary is not None:
        for output_field, summary_field in {
            "stock_time_metrics_planned": "stock_time_metrics_planned",
            "stock_time_metrics_updated": "stock_time_metrics_updated",
            "catalog_time_metrics_planned": "catalog_time_metrics_planned",
            "catalog_time_metrics_updated": "catalog_time_metrics_updated",
            "full_withdrawals_planned": "full_withdrawals_planned",
            "full_withdrawals_updated": "full_withdrawals_updated",
        }.items():
            if value := _summary_int(source_gated_summary, summary_field):
                counts[output_field] = value
    return counts


def _item_detail_diagnostic_counts(item_summaries: Sequence[Any]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for summary in item_summaries:
        raw_counts = _summary_value(summary, "diagnostic_reason_counts")
        if not isinstance(raw_counts, Mapping):
            continue
        for raw_reason, raw_count in raw_counts.items():
            try:
                count = int(raw_count)
            except (TypeError, ValueError):
                continue
            if count <= 0:
                continue
            reason = _safe_diagnostic_reason_key(raw_reason)
            if reason is None:
                continue
            merged[reason] = merged.get(reason, 0) + count
    return dict(sorted(merged.items()))


def _sanitized_item_detail_diagnostic_counts(
    diagnostic_counts: Mapping[str, int],
) -> dict[str, int]:
    return {
        f"item_detail_diagnostic_{reason}": count for reason, count in diagnostic_counts.items()
    }


def _safe_diagnostic_reason_key(value: Any) -> str | None:
    normalized = str(value).strip().lower()
    if not normalized:
        return None
    safe = "".join(character if character.isalnum() else "_" for character in normalized)
    collapsed = "_".join(part for part in safe.split("_") if part)
    return collapsed[:96] or None


def _diagnostic_reason_is_rate_limit(reason: str) -> bool:
    return any(marker in reason for marker in ("rate_limit", "rate_limited", "http_429"))


def _summary_int(summary: Any, name: str) -> int:
    value = _summary_value(summary, name)
    return value if isinstance(value, int) else 0


def _enforce_write_safety_controls(
    *, summary: ReconciliationSummary, controls: ReconciliationControls
) -> None:
    if controls.stop_on_rate_limit and _summary_issue_count(summary, "rate_limit") > 0:
        raise ValueError("rate_limit")
    threshold = controls.error_threshold
    if threshold is not None and _summary_error_count(summary) >= threshold:
        raise ValueError("error_threshold")


def _enforce_write_count_safety_controls(
    counts: Mapping[str, int], *, controls: ReconciliationControls
) -> None:
    if controls.stop_on_rate_limit and _write_count_rate_limit_count(counts) > 0:
        raise ValueError("rate_limit")
    threshold = controls.error_threshold
    if threshold is not None and _write_count_error_count(counts) >= threshold:
        raise ValueError("error_threshold")


def _write_count_error_count(counts: Mapping[str, int]) -> int:
    return (
        int(counts.get("redacted_errors", 0))
        + int(counts.get("item_detail_diagnostics", 0))
        + int(counts.get("question_detail_missing", 0))
    )


def _write_count_rate_limit_count(counts: Mapping[str, int]) -> int:
    return int(counts.get("item_detail_rate_limit", 0))


def _summary_error_count(summary: ReconciliationSummary) -> int:
    total = 0
    for aggregate in summary.aggregates:
        total += aggregate.error_count
        total += sum(
            1
            for issue in aggregate.issues
            if issue.code
            in {
                "auth_error",
                "expected_unavailable",
                "question_detail_missing",
                "query_anomaly",
                "rate_limit",
                "validator_or_index_anomaly",
            }
        )
    return total


def _summary_issue_count(summary: ReconciliationSummary, code: str) -> int:
    return sum(
        1 for aggregate in summary.aggregates for issue in aggregate.issues if issue.code == code
    )


if __name__ == "__main__":
    raise SystemExit(main())
