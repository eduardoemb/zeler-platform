from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

READ_MODELS: tuple[str, ...] = (
    "orders",
    "shipments",
    "items",
    "sheets_item_formula_rows",
    "sheets_item_sku_index",
    "status_history",
)
DEFAULT_STOP_CRITERIA: tuple[str, ...] = (
    "unsanitized_output",
    "unauthorized_pii",
    "unexpected_count_delta",
    "validator_error",
    "auth_error",
    "formula_regression",
)


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
    max_orders: int | None


@dataclass(frozen=True)
class ReadModelAggregate:
    read_model: str
    expected_count: int
    persisted_count: int
    missing_count: int
    complete_count: int = 0
    na_count: int = 0
    zero_count: int = 0
    positive_count: int = 0
    unauthorized_count: int = 0
    error_count: int = 0

    def to_sanitized_dict(self) -> dict[str, int | str]:
        return {
            "read_model": self.read_model,
            "expected_count": self.expected_count,
            "persisted_count": self.persisted_count,
            "missing_count": self.missing_count,
            "complete_count": self.complete_count,
            "na_count": self.na_count,
            "zero_count": self.zero_count,
            "positive_count": self.positive_count,
            "unauthorized_count": self.unauthorized_count,
            "error_count": self.error_count,
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
    raw_context: dict[str, Any] = field(default_factory=dict, repr=False)

    def to_sanitized_dict(self) -> dict[str, Any]:
        return {
            "seller_scope": "provided",
            "date_range": {"from": self.date_from, "to": self.date_to},
            "mode": "dry_run" if self.dry_run else "write",
            "approved_runtime": self.approved_runtime,
            "write_enabled": self.write_enabled,
            "aggregates": [aggregate.to_sanitized_dict() for aggregate in self.aggregates],
            "stop_criteria": list(self.stop_criteria),
            "private_export_refs": list(self.private_export_refs),
        }


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
    if not bool(args.confirm_approved_runtime):
        raise SystemExit("--confirm-approved-runtime is required")
    if not bool(args.dry_run) and not bool(args.confirm_production_write):
        raise SystemExit("--confirm-production-write is required with --write")
    if bool(args.include_buyer_address_pii) and args.max_orders is None:
        raise SystemExit("--max-orders is required with --include-buyer-address-pii")


def build_reconciliation_request(args: argparse.Namespace) -> ReconciliationRequest:
    validate_reconciliation_safety(args)
    date_range = parse_reconciliation_date_range(str(args.date_from), str(args.date_to))
    dry_run = bool(args.dry_run)
    return ReconciliationRequest(
        seller_id=str(args.seller_id),
        date_range=date_range,
        dry_run=dry_run,
        approved_runtime=bool(args.confirm_approved_runtime),
        write_enabled=not dry_run,
        include_buyer_address_pii=bool(args.include_buyer_address_pii),
        max_orders=args.max_orders,
    )


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


def build_empty_summary(request: ReconciliationRequest) -> ReconciliationSummary:
    return ReconciliationSummary(
        seller_id=request.seller_id,
        date_from=request.date_range.date_from,
        date_to=request.date_range.date_to,
        dry_run=request.dry_run,
        approved_runtime=request.approved_runtime,
        write_enabled=request.write_enabled,
        aggregates=tuple(
            ReadModelAggregate(
                read_model=read_model,
                expected_count=0,
                persisted_count=0,
                missing_count=0,
            )
            for read_model in READ_MODELS
        ),
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        request = build_reconciliation_request(args)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(build_empty_summary(request).to_sanitized_dict(), sort_keys=True))
    return 0


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


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
