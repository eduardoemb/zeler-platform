from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

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
_OBSERVED_ONLY_MODELS = {"item_status_states", "item_status_transitions"}
_HISTORICAL_MELI_MODELS = ("orders", "shipments", "items", "questions", "claims")
_BOUNDED_REF_MODELS = {
    "shipments",
    "items",
    "catalog_product_snapshots",
    "catalog_buybox_snapshots",
}
_READ_MODEL_COLLECTIONS: Mapping[str, str] = {
    "catalog_product_snapshots": "sheets_catalog_product_snapshots",
    "catalog_buybox_snapshots": "sheets_catalog_buybox_snapshots",
}
_RECONCILED_MARKER_MODELS = {
    "questions",
    "claims",
    "catalog_product_snapshots",
    "catalog_buybox_snapshots",
}
_COMPLETE_FIELDS: Mapping[str, tuple[str, ...]] = {
    "orders": ("items.0",),
    "shipments": ("order_id", "status"),
    "items": ("status", "last_meli_sync_at"),
    "questions": ("date_created", "status", "item_id", "text", "from_user_id"),
    "claims": ("date_created", "order_id", "status", "returned_quantity"),
    "catalog_product_snapshots": (
        "catalog_product_id",
        "title",
        "description",
        "image_url",
        "attributes",
        "snapshot_at",
        "source",
    ),
    "catalog_buybox_snapshots": (
        "item_id",
        "catalog_product_id",
        "title",
        "available_quantity",
        "buybox_status",
        "price",
        "winning_price",
        "competitor_count",
        "only_competitor",
        "snapshot_at",
        "source",
    ),
    "sheets_item_formula_rows": ("current.status", "current.price", "current.listing_type_id"),
    "sheets_item_sku_index": ("normalized_sku", "item_id", "source"),
    "item_status_states": ("current_status", "last_observed_at"),
    "item_status_transitions": ("from_status", "to_status", "observed_at"),
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


@dataclass(frozen=True)
class HistoricalMeliExpectedCounts:
    counts: Mapping[str, int | None]
    refs: Mapping[str, frozenset[str]] = field(default_factory=dict, repr=False)
    truth_mode: Mapping[str, str] = field(default_factory=dict)
    issues: tuple[ReadModelIssue, ...] = ()


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
        )
    }
    refs: dict[str, frozenset[str]] = {}
    truth_mode = {read_model: "unavailable" for read_model in _HISTORICAL_MELI_MODELS}
    truth_mode.update(
        {"item_status_states": "observed_only", "item_status_transitions": "observed_only"}
    )
    issues: list[ReadModelIssue] = []

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

    return ExpectedReadModelCounts(
        counts=counts,
        refs=refs,
        truth_mode=truth_mode,
        issues=tuple(issues),
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
    return RuntimeHistoricalMeliGateways(
        gateway=gateway,
        order_detail_gateway=order_detail_gateway,
    )


async def _collect_historical_meli_expected_counts(
    *, db: Any, request: ReconciliationRequest
) -> Any:
    from zeler_sheets.historical_meli_backfill import run_historical_meli_backfill

    gateways = create_runtime_historical_meli_gateways()
    return await run_historical_meli_backfill(
        db=db,
        gateway=gateways.gateway,
        order_detail_gateway=gateways.order_detail_gateway,
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
    *, db: Any, request: ReconciliationRequest
) -> dict[str, int]:
    if request.dry_run or not request.write_enabled:
        return {}
    if not request.approved_runtime:
        raise ValueError("approved_runtime is required for write reconciliation")
    if request.controls.sleep_ms > 0:
        await asyncio.sleep(request.controls.sleep_ms / 1000)

    from zeler_sheets.historical_meli_backfill import run_historical_meli_backfill
    from zeler_sheets.sheetseller_backfill import (
        run_item_detail_enrichment,
        run_sheetseller_backfill,
    )

    gateways = create_runtime_historical_meli_gateways()
    summary = await run_historical_meli_backfill(
        db=db,
        gateway=gateways.gateway,
        order_detail_gateway=gateways.order_detail_gateway,
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
        ),
        controls=request.controls,
    )
    formula_summary = await run_sheetseller_backfill(
        db=db,
        seller_id=request.seller_id,
        dry_run=False,
    )
    counts = _combined_write_counts(
        historical_summary=summary,
        item_summaries=item_summaries,
        formula_summary=formula_summary,
    )
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
            if expected_count is not None and truth_mode == "expected"
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
    *, db: Any, request: ReconciliationRequest, summary: ReconciliationSummary
) -> dict[str, int]:
    if request.dry_run or not request.write_enabled:
        return {}
    if not request.approved_runtime:
        raise ValueError("approved_runtime is required for marker write")

    written = 0
    collection = db["sheets_read_model_freshness"]
    for aggregate in summary.aggregates:
        if aggregate.read_model not in _RECONCILED_MARKER_MODELS:
            continue
        if not _aggregate_has_complete_scoped_coverage(aggregate):
            continue
        marker_id = f"{request.seller_id}:{aggregate.read_model}"
        updated_at = datetime.now(UTC)
        await collection.update_one(
            {"_id": marker_id, "seller_id": request.seller_id, "read_model": aggregate.read_model},
            {
                "$set": {
                    "_id": marker_id,
                    "seller_id": request.seller_id,
                    "read_model": aggregate.read_model,
                    "state": "reconciled",
                    "fresh_until": request.date_range.end_exclusive,
                    "reconciled_until": request.date_range.end_exclusive,
                    "last_event_synced_at": request.date_range.start,
                    "updated_at": updated_at,
                    "source": "zelerdata_read_model_reconcile",
                    "schema_version": 1,
                }
            },
            upsert=True,
        )
        written += 1
    return {"freshness_markers_written": written} if written else {}


def _aggregate_has_complete_scoped_coverage(aggregate: ReadModelAggregate) -> bool:
    return (
        aggregate.expected_count is not None
        and aggregate.persisted_count == aggregate.expected_count
        and aggregate.complete_count is not None
        and aggregate.complete_count >= aggregate.expected_count
        and aggregate.missing_count == 0
        and not aggregate.issues
        and aggregate.error_count == 0
    )


async def _complete_count(collection: Any, read_model: str, filter_spec: dict[str, Any]) -> int:
    if read_model == "questions":
        return await _complete_questions_count(collection, filter_spec)
    required_fields = _COMPLETE_FIELDS.get(read_model, ())
    if not required_fields:
        return int(await collection.count_documents(filter_spec))
    return int(await collection.count_documents(_with_present_fields(filter_spec, required_fields)))


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
    if refs is not None:
        if read_model == "catalog_product_snapshots":
            filter_spec["catalog_product_id"] = {"$in": sorted(refs)}
        elif read_model == "catalog_buybox_snapshots":
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
            write_counts = await execute_reconciliation_write(db=db, request=request)
            _enforce_write_count_safety_controls(write_counts, controls=request.controls)
            if request.repair_observed_pause_basis:
                repair_counts = await execute_observed_pause_basis_repair(db=db, request=request)
                _enforce_write_count_safety_controls(repair_counts, controls=request.controls)
            expected = await collect_expected_read_model_counts(db=db, request=request)
            refreshed_summary = await collect_reconciliation_counts(
                db=db, request=request, expected=expected
            )
            marker_counts = await write_complete_read_model_freshness_markers(
                db=db, request=request, summary=refreshed_summary
            )
            summary = replace(
                refreshed_summary,
                write_counts={**write_counts, **marker_counts},
                repair_counts=repair_counts,
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
    truth_boundary = (
        "observed transitions only; do not synthesize paused/status history"
        if read_model in {"item_status_states", "item_status_transitions"}
        else None
    )
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
    *, historical_summary: Any, item_summaries: Sequence[Any], formula_summary: Any | None
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
