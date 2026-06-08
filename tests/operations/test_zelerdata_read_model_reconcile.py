from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from infra.operations.zelerdata_read_model_reconcile import (
    DEFAULT_PHASE2_DRY_RUN_SCOPES,
    DEFAULT_PHASE2_PREFLIGHT_TARGETS,
    READ_MODELS,
    ExpectedReadModelCounts,
    PrivateExportRecord,
    ReadModelAggregate,
    ReadModelIssue,
    ReconciliationSummary,
    build_arg_parser,
    build_phase2_runtime_contract,
    build_reconciliation_request,
    collect_expected_read_model_counts,
    collect_reconciliation_counts,
    execute_reconciliation_write,
    validate_reconciliation_safety,
)

SHEETS_RUNTIME_DOCKERFILES = (
    Path("modules/sheets/Dockerfile.api"),
    Path("modules/sheets/Dockerfile.worker"),
)
ZELERDATA_RECONCILE_HELPER = Path("infra/operations/zelerdata_read_model_reconcile.py")
OPERATIONS_COPY_STANZA = "COPY infra/operations ./infra/operations"
COLLECTOR_ATTR = "collect_reconciliation_counts"


class FakeAsyncCollection:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.documents = documents
        self.count_filters: list[dict[str, Any]] = []

    async def count_documents(self, filter_spec: dict[str, Any]) -> int:
        self.count_filters.append(filter_spec)
        return sum(1 for document in self.documents if _matches_filter(document, filter_spec))

    def aggregate(self, pipeline: list[dict[str, Any]]) -> Any:
        rows = self.documents
        if pipeline and "$match" in pipeline[0]:
            rows = [row for row in rows if _matches_filter(row, pipeline[0]["$match"])]
        group_field = pipeline[1]["$group"]["_id"].removeprefix("$")
        grouped: dict[str, int] = {}
        for row in rows:
            value = _lookup(row, group_field)
            key = "missing" if value is None else str(value)
            grouped[key] = grouped.get(key, 0) + 1

        async def cursor() -> Any:
            for key, count in grouped.items():
                yield {"_id": key, "count": count}

        return cursor()


class FakeAsyncDb:
    def __init__(self, collections: dict[str, Any]) -> None:
        self.collections = {
            name: documents
            if isinstance(documents, FakeAsyncCollection)
            else FakeAsyncCollection(documents)
            for name, documents in collections.items()
        }

    def __getitem__(self, name: str) -> FakeAsyncCollection:
        return self.collections.setdefault(name, FakeAsyncCollection([]))


class FailingCountCollection(FakeAsyncCollection):
    def __init__(self, error: Exception) -> None:
        super().__init__([])
        self.error = error

    async def count_documents(self, filter_spec: dict[str, Any]) -> int:
        self.count_filters.append(filter_spec)
        raise self.error


class FakeRateLimitError(Exception):
    retry_after_seconds = 7


class FakeValidatorError(Exception):
    pass


@dataclass(frozen=True)
class FakeHistoricalMeliSummary:
    orders_found: int
    order_ids: list[str]
    shipment_ids: list[str]
    item_ids: list[str]
    planned_orders: int = 0
    planned_items: int = 0
    planned_shipments: int = 0
    written_orders: int = 0
    written_items: int = 0
    written_shipments: int = 0
    item_detail_missing: int = 0
    redacted_errors: int = 0


@dataclass(frozen=True)
class FakeWriteSummary:
    items_updated: int = 0
    items_planned: int = 0
    batches_fetched: int = 0
    diagnostic_reason_counts: dict[str, int] | None = None
    formula_row_upserts: int = 0
    sku_index_upserts: int = 0


def _matches_filter(document: dict[str, Any], filter_spec: dict[str, Any]) -> bool:
    for key, expected in filter_spec.items():
        actual = _lookup(document, key)
        if isinstance(expected, dict):
            for operator, operand in expected.items():
                if operator == "$gte" and not (actual is not None and actual >= operand):
                    return False
                if operator == "$lt" and not (actual is not None and actual < operand):
                    return False
                if operator == "$in" and actual not in operand:
                    return False
                exists = _lookup(document, key, missing=...) is not ...
                if operator == "$exists" and exists != operand:
                    return False
                if operator == "$ne" and actual == operand:
                    return False
        elif actual != expected:
            return False
    return True


def _lookup(document: dict[str, Any], dotted: str, *, missing: Any = None) -> Any:
    current: Any = document
    for part in dotted.split("."):
        if isinstance(current, list) and part.isdigit():
            index = int(part)
            if index >= len(current):
                return missing
            current = current[index]
            continue
        if not isinstance(current, dict) or part not in current:
            return missing
        current = current[part]
    return current


def _request() -> Any:
    return build_reconciliation_request(
        build_arg_parser().parse_args(
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
    )


def _write_request(*, extra_args: list[str] | None = None) -> Any:
    args = [
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
    if extra_args:
        args.extend(extra_args)
    return build_reconciliation_request(build_arg_parser().parse_args(args))


def _dt(day: int) -> datetime:
    return datetime(2026, 6, day, tzinfo=UTC)


def _seller_doc(**values: Any) -> dict[str, Any]:
    return {"seller_id": "82453304", **values}


def _expected_order_refs() -> frozenset[str]:
    return frozenset(
        {
            "ORDER-PII-ABSENT",
            "ORDER-PII-IN-RANGE",
            "ORDER-PII-OUT-OF-RANGE",
        }
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


def test_reconciliation_request_records_throttle_resume_and_bounds_without_leaking_cursor() -> None:
    args = build_arg_parser().parse_args(
        [
            "--seller-id",
            "82453304",
            "--date-from",
            "2026-06-01",
            "--date-to",
            "2026-06-04",
            "--confirm-approved-runtime",
            "--max-orders",
            "25",
            "--max-items",
            "10",
            "--max-shipments",
            "5",
            "--concurrency",
            "2",
            "--sleep-ms",
            "250",
            "--error-threshold",
            "3",
            "--stop-on-rate-limit",
            "--resume-after-order-id",
            "ORDER-PII-RESUME",
        ]
    )

    request = build_reconciliation_request(args)
    summary = ReconciliationSummary(
        seller_id=request.seller_id,
        date_from=request.date_range.date_from,
        date_to=request.date_range.date_to,
        dry_run=request.dry_run,
        approved_runtime=request.approved_runtime,
        write_enabled=request.write_enabled,
        controls=request.controls,
    )
    output = summary.to_sanitized_dict()
    output_json = json.dumps(output, sort_keys=True)

    assert request.controls.max_orders == 25
    assert request.controls.max_items == 10
    assert request.controls.max_shipments == 5
    assert request.controls.concurrency == 2
    assert request.controls.sleep_ms == 250
    assert request.controls.error_threshold == 3
    assert request.controls.stop_on_rate_limit is True
    assert request.controls.resume_after_order_id == "ORDER-PII-RESUME"
    assert output["controls"] == {
        "max_orders": 25,
        "max_items": 10,
        "max_shipments": 5,
        "concurrency": 2,
        "sleep_ms": 250,
        "error_threshold": 3,
        "stop_on_rate_limit": True,
        "resume_cursor": "provided",
    }
    assert "ORDER-PII-RESUME" not in output_json
    assert "82453304" not in output_json


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

    args.seller_id = " "
    args.confirm_approved_runtime = True
    with pytest.raises(SystemExit, match="seller-id is required"):
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


@pytest.mark.asyncio
async def test_reconciliation_write_runs_item_enrichment_and_formula_rebuild(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from infra.operations import zelerdata_read_model_reconcile

    from zeler_sheets import historical_meli_backfill, sheetseller_backfill

    calls: list[tuple[Any, ...]] = []

    async def fake_historical_backfill(**kwargs: Any) -> FakeHistoricalMeliSummary:
        calls.append(("historical", kwargs["dry_run"]))
        return FakeHistoricalMeliSummary(
            orders_found=1,
            order_ids=["ORDER-PII-1"],
            shipment_ids=["SHIP-PII-1"],
            item_ids=["ITEM-PII-1", "ITEM-PII-2"],
            planned_orders=1,
            planned_items=2,
            planned_shipments=1,
            written_orders=1,
            written_items=2,
            written_shipments=1,
        )

    async def fake_item_enrichment(**kwargs: Any) -> FakeWriteSummary:
        calls.append(
            (
                "item_enrichment",
                tuple(kwargs["item_ids"]),
                kwargs["dry_run"],
                kwargs["sale_price_enabled"],
                kwargs["listing_fixed_fee_enabled"],
            )
        )
        return FakeWriteSummary(items_updated=len(kwargs["item_ids"]), items_planned=1)

    async def fake_formula_rebuild(**kwargs: Any) -> FakeWriteSummary:
        calls.append(("formula_rebuild", kwargs["dry_run"]))
        return FakeWriteSummary(formula_row_upserts=2, sku_index_upserts=2)

    monkeypatch.setattr(
        zelerdata_read_model_reconcile,
        "create_runtime_historical_meli_gateways",
        lambda: type("Gateways", (), {"gateway": object(), "order_detail_gateway": object()})(),
    )
    monkeypatch.setattr(
        historical_meli_backfill,
        "run_historical_meli_backfill",
        fake_historical_backfill,
    )
    monkeypatch.setattr(sheetseller_backfill, "run_item_detail_enrichment", fake_item_enrichment)
    monkeypatch.setattr(sheetseller_backfill, "run_sheetseller_backfill", fake_formula_rebuild)

    counts = await execute_reconciliation_write(db=FakeAsyncDb({}), request=_write_request())

    item_calls = [call for call in calls if call[0] == "item_enrichment"]
    enriched_item_ids = [item_id for call in item_calls for item_id in call[1]]
    assert calls[0] == ("historical", False)
    assert calls[-1] == ("formula_rebuild", False)
    assert enriched_item_ids == ["ITEM-PII-1", "ITEM-PII-2"]
    assert all(call[2] is False and call[3] is True and call[4] is True for call in item_calls)
    assert counts | {"formula_row_upserts": counts["formula_row_upserts"]} == {
        "planned_orders": 1,
        "planned_items": 2,
        "planned_shipments": 1,
        "written_orders": 1,
        "written_items": 2,
        "written_shipments": 1,
        "item_detail_missing": 0,
        "redacted_errors": 0,
        "item_detail_items_planned": 2,
        "item_detail_items_updated": 2,
        "formula_row_upserts": 2,
        "sku_index_upserts": 2,
    }
    assert "ORDER-PII-1" not in json.dumps(counts, sort_keys=True)
    assert "ITEM-PII" not in json.dumps(counts, sort_keys=True)


@pytest.mark.asyncio
async def test_reconciliation_write_enforces_concurrency_for_item_enrichment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from infra.operations import zelerdata_read_model_reconcile

    from zeler_sheets import historical_meli_backfill, sheetseller_backfill

    active = 0
    max_active = 0
    item_calls: list[tuple[str, ...]] = []

    async def fake_historical_backfill(**_: Any) -> FakeHistoricalMeliSummary:
        return FakeHistoricalMeliSummary(
            orders_found=1,
            order_ids=["ORDER-PII-1"],
            shipment_ids=[],
            item_ids=["ITEM-PII-1", "ITEM-PII-2", "ITEM-PII-3"],
        )

    async def fake_item_enrichment(**kwargs: Any) -> FakeWriteSummary:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        item_calls.append(tuple(kwargs["item_ids"]))
        await asyncio.sleep(0.01)
        active -= 1
        return FakeWriteSummary(items_updated=len(kwargs["item_ids"]), items_planned=1)

    async def fake_formula_rebuild(**_: Any) -> FakeWriteSummary:
        return FakeWriteSummary(formula_row_upserts=3, sku_index_upserts=3)

    monkeypatch.setattr(
        zelerdata_read_model_reconcile,
        "create_runtime_historical_meli_gateways",
        lambda: type("Gateways", (), {"gateway": object(), "order_detail_gateway": object()})(),
    )
    monkeypatch.setattr(
        historical_meli_backfill,
        "run_historical_meli_backfill",
        fake_historical_backfill,
    )
    monkeypatch.setattr(sheetseller_backfill, "run_item_detail_enrichment", fake_item_enrichment)
    monkeypatch.setattr(sheetseller_backfill, "run_sheetseller_backfill", fake_formula_rebuild)

    await execute_reconciliation_write(
        db=FakeAsyncDb({}),
        request=_write_request(extra_args=["--concurrency", "2"]),
    )

    assert sorted(item_calls) == [("ITEM-PII-1",), ("ITEM-PII-2",), ("ITEM-PII-3",)]
    assert max_active == 2


@pytest.mark.asyncio
async def test_reconciliation_write_stops_on_write_phase_redacted_errors_before_item_enrichment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from infra.operations import zelerdata_read_model_reconcile

    from zeler_sheets import historical_meli_backfill, sheetseller_backfill

    calls: list[str] = []

    async def fake_historical_backfill(**_: Any) -> FakeHistoricalMeliSummary:
        calls.append("historical")
        return FakeHistoricalMeliSummary(
            orders_found=1,
            order_ids=["ORDER-PII-1"],
            shipment_ids=[],
            item_ids=["ITEM-PII-1"],
            redacted_errors=2,
        )

    async def fake_item_enrichment(**_: Any) -> FakeWriteSummary:
        calls.append("item_enrichment")
        return FakeWriteSummary(items_updated=1, items_planned=1)

    async def fake_formula_rebuild(**_: Any) -> FakeWriteSummary:
        calls.append("formula_rebuild")
        return FakeWriteSummary(formula_row_upserts=1, sku_index_upserts=1)

    monkeypatch.setattr(
        zelerdata_read_model_reconcile,
        "create_runtime_historical_meli_gateways",
        lambda: type("Gateways", (), {"gateway": object(), "order_detail_gateway": object()})(),
    )
    monkeypatch.setattr(
        historical_meli_backfill,
        "run_historical_meli_backfill",
        fake_historical_backfill,
    )
    monkeypatch.setattr(sheetseller_backfill, "run_item_detail_enrichment", fake_item_enrichment)
    monkeypatch.setattr(sheetseller_backfill, "run_sheetseller_backfill", fake_formula_rebuild)

    with pytest.raises(ValueError, match="error_threshold"):
        await execute_reconciliation_write(
            db=FakeAsyncDb({}),
            request=_write_request(extra_args=["--error-threshold", "2"]),
        )

    assert calls == ["historical"]


@pytest.mark.asyncio
async def test_reconciliation_write_stops_on_item_enrichment_rate_limit_before_formula_rebuild(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from infra.operations import zelerdata_read_model_reconcile

    from zeler_sheets import historical_meli_backfill, sheetseller_backfill

    calls: list[str] = []

    async def fake_historical_backfill(**_: Any) -> FakeHistoricalMeliSummary:
        calls.append("historical")
        return FakeHistoricalMeliSummary(
            orders_found=1,
            order_ids=["ORDER-PII-1"],
            shipment_ids=[],
            item_ids=["ITEM-PII-1"],
        )

    async def fake_item_enrichment(**_: Any) -> FakeWriteSummary:
        calls.append("item_enrichment")
        return FakeWriteSummary(
            items_updated=0,
            items_planned=1,
            diagnostic_reason_counts={"seller_shipping_cost:transient:rate_limited": 1},
        )

    async def fake_formula_rebuild(**_: Any) -> FakeWriteSummary:
        calls.append("formula_rebuild")
        return FakeWriteSummary(formula_row_upserts=1, sku_index_upserts=1)

    monkeypatch.setattr(
        zelerdata_read_model_reconcile,
        "create_runtime_historical_meli_gateways",
        lambda: type("Gateways", (), {"gateway": object(), "order_detail_gateway": object()})(),
    )
    monkeypatch.setattr(
        historical_meli_backfill,
        "run_historical_meli_backfill",
        fake_historical_backfill,
    )
    monkeypatch.setattr(sheetseller_backfill, "run_item_detail_enrichment", fake_item_enrichment)
    monkeypatch.setattr(sheetseller_backfill, "run_sheetseller_backfill", fake_formula_rebuild)

    with pytest.raises(ValueError, match="rate_limit"):
        await execute_reconciliation_write(
            db=FakeAsyncDb({}),
            request=_write_request(extra_args=["--stop-on-rate-limit"]),
        )

    assert calls == ["historical", "item_enrichment"]


@pytest.mark.asyncio
async def test_reconciliation_write_surfaces_item_enrichment_diagnostic_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from infra.operations import zelerdata_read_model_reconcile

    from zeler_sheets import historical_meli_backfill, sheetseller_backfill

    async def fake_historical_backfill(**_: Any) -> FakeHistoricalMeliSummary:
        return FakeHistoricalMeliSummary(
            orders_found=1,
            order_ids=["ORDER-PII-1"],
            shipment_ids=[],
            item_ids=["ITEM-PII-1"],
        )

    async def fake_item_enrichment(**_: Any) -> FakeWriteSummary:
        return FakeWriteSummary(
            items_updated=0,
            items_planned=1,
            diagnostic_reason_counts={
                "seller_shipping_cost:transient:rate_limited": 1,
                "listing_fee_projection:malformed:source_error": 2,
            },
        )

    async def fake_formula_rebuild(**_: Any) -> FakeWriteSummary:
        return FakeWriteSummary(formula_row_upserts=1, sku_index_upserts=1)

    monkeypatch.setattr(
        zelerdata_read_model_reconcile,
        "create_runtime_historical_meli_gateways",
        lambda: type("Gateways", (), {"gateway": object(), "order_detail_gateway": object()})(),
    )
    monkeypatch.setattr(
        historical_meli_backfill,
        "run_historical_meli_backfill",
        fake_historical_backfill,
    )
    monkeypatch.setattr(sheetseller_backfill, "run_item_detail_enrichment", fake_item_enrichment)
    monkeypatch.setattr(sheetseller_backfill, "run_sheetseller_backfill", fake_formula_rebuild)

    counts = await execute_reconciliation_write(db=FakeAsyncDb({}), request=_write_request())

    assert counts["item_detail_diagnostics"] == 3
    assert counts["item_detail_rate_limit"] == 1


def test_reconciliation_write_stops_on_rate_limit_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from infra.operations import zelerdata_read_model_reconcile

    calls: dict[str, bool] = {}

    async def fake_expected(**_: Any) -> ExpectedReadModelCounts:
        return ExpectedReadModelCounts(counts={"items": None})

    async def fake_collect(**_: Any) -> ReconciliationSummary:
        return ReconciliationSummary(
            seller_id="82453304",
            date_from="2026-06-01",
            date_to="2026-06-04",
            dry_run=False,
            approved_runtime=True,
            write_enabled=True,
            aggregates=(
                ReadModelAggregate(
                    read_model="items",
                    expected_count=None,
                    persisted_count=None,
                    missing_count=None,
                    complete_count=None,
                    truth_mode="unavailable",
                    issues=(
                        ReadModelIssue(
                            read_model="items",
                            code="rate_limit",
                            message="SENTINEL raw rate limit details",
                        ),
                    ),
                ),
            ),
        )

    async def fake_execute(**_: Any) -> dict[str, int]:
        calls["execute"] = True
        return {}

    monkeypatch.setattr(
        zelerdata_read_model_reconcile, "create_runtime_db", lambda: FakeAsyncDb({})
    )
    monkeypatch.setattr(
        zelerdata_read_model_reconcile,
        "collect_expected_read_model_counts",
        fake_expected,
    )
    monkeypatch.setattr(zelerdata_read_model_reconcile, COLLECTOR_ATTR, fake_collect)
    monkeypatch.setattr(
        zelerdata_read_model_reconcile, "execute_reconciliation_write", fake_execute
    )

    with pytest.raises(SystemExit, match="rate_limit"):
        zelerdata_read_model_reconcile.main(
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
                "--stop-on-rate-limit",
            ]
        )

    assert calls == {}


def test_reconciliation_write_stops_when_error_threshold_is_reached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from infra.operations import zelerdata_read_model_reconcile

    calls: dict[str, bool] = {}

    async def fake_expected(**_: Any) -> ExpectedReadModelCounts:
        return ExpectedReadModelCounts(counts={"orders": 1})

    async def fake_collect(**_: Any) -> ReconciliationSummary:
        return ReconciliationSummary(
            seller_id="82453304",
            date_from="2026-06-01",
            date_to="2026-06-04",
            dry_run=False,
            approved_runtime=True,
            write_enabled=True,
            aggregates=(
                ReadModelAggregate(
                    read_model="orders",
                    expected_count=1,
                    persisted_count=0,
                    missing_count=1,
                    complete_count=0,
                    error_count=1,
                ),
            ),
        )

    async def fake_execute(**_: Any) -> dict[str, int]:
        calls["execute"] = True
        return {}

    monkeypatch.setattr(
        zelerdata_read_model_reconcile, "create_runtime_db", lambda: FakeAsyncDb({})
    )
    monkeypatch.setattr(
        zelerdata_read_model_reconcile,
        "collect_expected_read_model_counts",
        fake_expected,
    )
    monkeypatch.setattr(zelerdata_read_model_reconcile, COLLECTOR_ATTR, fake_collect)
    monkeypatch.setattr(
        zelerdata_read_model_reconcile, "execute_reconciliation_write", fake_execute
    )

    with pytest.raises(SystemExit, match="error_threshold"):
        zelerdata_read_model_reconcile.main(
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
                "--error-threshold",
                "1",
            ]
        )

    assert calls == {}


@pytest.mark.asyncio
async def test_collect_reconciliation_counts_reports_real_sanitized_aggregates() -> None:
    db = FakeAsyncDb(
        {
            "orders": [
                _seller_doc(
                    _id="ORDER-PII-1",
                    date_created=_dt(1),
                    items=[{}],
                    status="paid",
                    shipment_id="SHIP-PII-1",
                    meli_pack_id="PACK-PII-1",
                    buyer_id="BUYER-PII-1",
                ),
                _seller_doc(_id="ORDER-PII-2", date_created=_dt(3), items=[], status="cancelled"),
                {"_id": "OTHER", "seller_id": "other", "date_created": _dt(2), "status": "paid"},
            ],
            "shipments": [
                _seller_doc(
                    _id="SHIP-PII-1",
                    order_id="ORDER-PII-1",
                    status="delivered",
                    receiver_address={"street_name": "SENTINEL STREET"},
                    real_shipping_cost={"seller_cost": 12.5},
                ),
                _seller_doc(_id="SHIP-PII-2", status="ready_to_ship"),
            ],
            "items": [
                _seller_doc(
                    _id="ITEM-PII-1",
                    status="active",
                    seller_shipping_cost=10,
                    listing_fee_projection={"source": "/sites/{site}/listing_prices"},
                    listing_price_fixed_fee={"fixed_fee": 5},
                    current_promotion={"source": "/items/{id}/sale_price"},
                ),
                _seller_doc(_id="ITEM-PII-2", status="paused"),
            ],
            "sheets_item_formula_rows": [
                _seller_doc(
                    _id="FORMULA-PII-1",
                    current={
                        "status": "active",
                        "price": 100,
                        "listing_type_id": "gold_special",
                        "seller_shipping_cost": 8,
                        "listing_fee_projection": {"source": "/sites/{site}/listing_prices"},
                        "listing_price_fixed_fee": {"fixed_fee": 5},
                    },
                ),
                _seller_doc(_id="FORMULA-PII-2", current={"status": "paused"}),
            ],
            "sheets_item_sku_index": [
                _seller_doc(
                    _id="SKU-PII-1",
                    source="item_attribute",
                    normalized_sku="SKU-1",
                    item_id="ITEM-PII-1",
                ),
                _seller_doc(
                    _id="SKU-PII-2",
                    source="order_line",
                    normalized_sku="SKU-2",
                    item_id="ITEM-PII-2",
                ),
            ],
            "item_status_states": [
                _seller_doc(_id="STATE-PII-1", current_status="active", last_observed_at=_dt(4)),
                _seller_doc(_id="STATE-PII-2", current_status="paused"),
            ],
            "item_status_transitions": [
                _seller_doc(
                    _id="TRANSITION-PII-1",
                    from_status="active",
                    to_status="paused",
                    observed_at=_dt(2),
                ),
                _seller_doc(
                    _id="TRANSITION-PII-2",
                    from_status="paused",
                    to_status="active",
                    observed_at=_dt(4),
                ),
            ],
        }
    )

    summary = await collect_reconciliation_counts(
        db=db,
        request=_request(),
        expected=ExpectedReadModelCounts(
            counts={
                "orders": 3,
                "shipments": 1,
                "items": None,
                "sheets_item_formula_rows": 2,
                "sheets_item_sku_index": 2,
                "item_status_states": None,
                "item_status_transitions": None,
            },
            refs={
                "shipments": frozenset({"SHIP-PII-1"}),
                "items": frozenset({"ITEM-PII-1"}),
            },
            truth_mode={
                "items": "unavailable",
                "item_status_states": "observed_only",
                "item_status_transitions": "observed_only",
            },
            issues=(
                ReadModelIssue(
                    read_model="items",
                    code="expected_unavailable",
                    message="expected source unavailable",
                ),
            ),
        ),
    )

    output = summary.to_sanitized_dict()
    by_model = {aggregate["read_model"]: aggregate for aggregate in output["aggregates"]}

    assert set(by_model) == set(READ_MODELS)
    assert all(aggregate["persisted_count"] > 0 for aggregate in by_model.values())
    assert by_model["orders"] | {"field_counts": by_model["orders"]["field_counts"]} == {
        "read_model": "orders",
        "expected_count": 3,
        "persisted_count": 2,
        "missing_count": 1,
        "complete_count": 1,
        "truth_mode": "expected",
        "field_counts": {
            "buyer_id": {"missing": 1, "present": 1},
            "meli_pack_id": {"missing": 1, "present": 1},
            "shipment_id": {"missing": 1, "present": 1},
            "status": {"cancelled": 1, "paid": 1},
        },
    }
    assert by_model["shipments"]["field_counts"]["receiver_address"] == {
        "missing": 0,
        "present": 1,
    }
    assert by_model["items"]["expected_count"] is None
    assert by_model["items"]["missing_count"] is None
    assert by_model["items"]["issues"] == [{"code": "expected_unavailable"}]
    assert by_model["sheets_item_formula_rows"]["complete_count"] == 1
    assert by_model["sheets_item_sku_index"]["field_counts"]["source"] == {
        "item_attribute": 1,
        "order_line": 1,
    }
    assert by_model["item_status_states"]["truth_mode"] == "observed_only"
    assert by_model["item_status_states"]["missing_count"] is None
    assert by_model["item_status_transitions"]["expected_count"] is None
    assert by_model["item_status_transitions"]["field_counts"]["to_status"] == {
        "active": 1,
        "paused": 1,
    }
    assert db["orders"].count_filters[0] == {
        "seller_id": "82453304",
        "date_created": {"$gte": _dt(1), "$lt": _dt(5)},
    }
    assert db["item_status_transitions"].count_filters[0] == {
        "seller_id": "82453304",
        "observed_at": {"$gte": _dt(1), "$lt": _dt(5)},
    }
    assert db["shipments"].count_filters[0] == {
        "seller_id": "82453304",
        "_id": {"$in": ["SHIP-PII-1"]},
    }
    assert db["items"].count_filters[0] == {
        "seller_id": "82453304",
        "_id": {"$in": ["ITEM-PII-1"]},
    }
    sanitized_json = json.dumps(output, sort_keys=True)
    for forbidden in (
        "82453304",
        "ORDER-PII",
        "SHIP-PII",
        "ITEM-PII",
        "FORMULA-PII",
        "SKU-PII",
        "STATE-PII",
        "TRANSITION-PII",
        "SENTINEL STREET",
    ):
        assert forbidden not in sanitized_json


@pytest.mark.asyncio
async def test_expected_counts_use_historical_meli_source_and_bound_refs() -> None:
    db = FakeAsyncDb(
        {
            "shipments": [
                _seller_doc(_id="SHIP-PII-1", order_id="ORDER-PII-1", status="delivered"),
                _seller_doc(_id="SHIP-PII-2", order_id="ORDER-PII-2", status="shipped"),
            ],
            "items": [
                _seller_doc(_id="ITEM-PII-1", status="active", last_meli_sync_at=_dt(2)),
                _seller_doc(_id="ITEM-PII-2", status="paused", last_meli_sync_at=_dt(3)),
                _seller_doc(_id="ITEM-PII-3", status="closed", last_meli_sync_at=_dt(4)),
            ],
        }
    )
    request = _request()
    calls: dict[str, Any] = {}

    async def fake_historical_source(*, db: Any, request: Any) -> FakeHistoricalMeliSummary:
        calls["request"] = (request.seller_id, request.date_range.date_to_exclusive)
        return FakeHistoricalMeliSummary(
            orders_found=2,
            order_ids=["ORDER-PII-1", "ORDER-PII-2"],
            shipment_ids=["SHIP-PII-1"],
            item_ids=["ITEM-PII-1", "ITEM-PII-2"],
        )

    expected = await collect_expected_read_model_counts(
        db=db,
        request=request,
        historical_meli_source=fake_historical_source,
    )
    summary = await collect_reconciliation_counts(
        db=db,
        request=request,
        expected=expected,
        read_models=("shipments", "items"),
    )

    output = summary.to_sanitized_dict()
    by_model = {aggregate["read_model"]: aggregate for aggregate in output["aggregates"]}

    assert calls["request"] == ("82453304", "2026-06-05T00:00:00Z")
    assert expected.counts["orders"] == 2
    assert expected.refs["orders"] == frozenset({"ORDER-PII-1", "ORDER-PII-2"})
    assert expected.counts["shipments"] == 1
    assert expected.counts["items"] == 2
    assert expected.refs["shipments"] == frozenset({"SHIP-PII-1"})
    assert expected.refs["items"] == frozenset({"ITEM-PII-1", "ITEM-PII-2"})
    assert by_model["shipments"] | {"field_counts": by_model["shipments"]["field_counts"]} == {
        "read_model": "shipments",
        "expected_count": 1,
        "persisted_count": 1,
        "missing_count": 0,
        "complete_count": 1,
        "truth_mode": "expected",
        "field_counts": {
            "real_shipping_cost.seller_cost": {"missing": 1, "present": 0},
            "receiver_address": {"missing": 1, "present": 0},
            "status": {"delivered": 1},
        },
    }
    assert by_model["items"]["expected_count"] == 2
    assert by_model["items"]["persisted_count"] == 2
    assert by_model["items"]["missing_count"] == 0
    assert db["shipments"].count_filters[0] == {
        "seller_id": "82453304",
        "_id": {"$in": ["SHIP-PII-1"]},
    }
    assert db["items"].count_filters[0] == {
        "seller_id": "82453304",
        "_id": {"$in": ["ITEM-PII-1", "ITEM-PII-2"]},
    }
    sanitized_json = json.dumps(output, sort_keys=True)
    for forbidden in ("ORDER-PII", "SHIP-PII", "ITEM-PII", "82453304"):
        assert forbidden not in sanitized_json


@pytest.mark.asyncio
async def test_shipments_and_items_without_expected_refs_do_not_broaden_reads() -> None:
    db = FakeAsyncDb(
        {
            "shipments": [_seller_doc(_id="SHIP-PII-SELLER-WIDE", status="delivered")],
            "items": [_seller_doc(_id="ITEM-PII-SELLER-WIDE", status="active")],
        }
    )

    summary = await collect_reconciliation_counts(
        db=db,
        request=_request(),
        expected=ExpectedReadModelCounts(
            counts={"shipments": None, "items": None},
            truth_mode={"shipments": "unavailable", "items": "unavailable"},
            issues=(
                ReadModelIssue(
                    read_model="shipments",
                    code="expected_unavailable",
                    message="SENTINEL raw shipment source failure",
                ),
                ReadModelIssue(
                    read_model="items",
                    code="expected_unavailable",
                    message="SENTINEL raw item source failure",
                ),
            ),
        ),
        read_models=("shipments", "items"),
    )

    output = summary.to_sanitized_dict()
    by_model = {aggregate["read_model"]: aggregate for aggregate in output["aggregates"]}

    assert by_model["shipments"]["persisted_count"] is None
    assert by_model["shipments"]["complete_count"] is None
    assert by_model["shipments"]["missing_count"] is None
    assert {issue["code"] for issue in by_model["shipments"]["issues"]} == {
        "expected_refs_unavailable",
        "expected_unavailable",
    }
    assert by_model["items"]["persisted_count"] is None
    assert by_model["items"]["complete_count"] is None
    assert by_model["items"]["missing_count"] is None
    assert {issue["code"] for issue in by_model["items"]["issues"]} == {
        "expected_refs_unavailable",
        "expected_unavailable",
    }
    assert db["shipments"].count_filters == []
    assert db["items"].count_filters == []
    sanitized_json = json.dumps(output, sort_keys=True)
    for forbidden in ("SHIP-PII-SELLER-WIDE", "ITEM-PII-SELLER-WIDE", "SENTINEL"):
        assert forbidden not in sanitized_json


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_code"),
    (
        (PermissionError("SENTINEL_TOKEN unauthorized"), "auth_error"),
        (FakeRateLimitError("SENTINEL rate limited"), "rate_limit"),
    ),
)
async def test_expected_source_auth_and_rate_limit_are_sanitized_unavailable(
    error: Exception,
    expected_code: str,
) -> None:
    async def failing_historical_source(*, db: Any, request: Any) -> FakeHistoricalMeliSummary:
        raise error

    expected = await collect_expected_read_model_counts(
        db=FakeAsyncDb({}),
        request=_request(),
        historical_meli_source=failing_historical_source,
    )
    issue_output = [issue.to_sanitized_dict() for issue in expected.issues]

    for read_model in ("orders", "shipments", "items"):
        assert expected.counts[read_model] is None
        assert expected.truth_mode[read_model] == "unavailable"
        assert any(
            issue.read_model == read_model and issue.code == expected_code
            for issue in expected.issues
        )
    assert "SENTINEL" not in json.dumps(issue_output, sort_keys=True)


@pytest.mark.asyncio
async def test_query_and_validator_anomalies_emit_target_scoped_sanitized_issues() -> None:
    db = FakeAsyncDb(
        {
            "orders": FailingCountCollection(RuntimeError("SENTINEL raw order query")),
            "sheets_item_formula_rows": FailingCountCollection(
                FakeValidatorError("SENTINEL validator detail")
            ),
        }
    )

    summary = await collect_reconciliation_counts(
        db=db,
        request=_request(),
        expected=ExpectedReadModelCounts(
            counts={"orders": 2, "sheets_item_formula_rows": 2},
        ),
        read_models=("orders", "sheets_item_formula_rows"),
    )

    output = summary.to_sanitized_dict()
    by_model = {aggregate["read_model"]: aggregate for aggregate in output["aggregates"]}

    assert by_model["orders"]["persisted_count"] is None
    assert by_model["orders"]["complete_count"] is None
    assert by_model["orders"]["issues"] == [{"code": "query_anomaly"}]
    assert by_model["sheets_item_formula_rows"]["persisted_count"] is None
    assert by_model["sheets_item_formula_rows"]["complete_count"] is None
    assert by_model["sheets_item_formula_rows"]["issues"] == [
        {"code": "validator_or_index_anomaly"}
    ]
    sanitized_json = json.dumps(output, sort_keys=True)
    for forbidden in ("SENTINEL", "raw order query", "validator detail", "82453304"):
        assert forbidden not in sanitized_json


def test_reconciliation_cli_uses_runtime_collector_and_keeps_output_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from infra.operations import zelerdata_read_model_reconcile

    db = FakeAsyncDb({})
    calls: dict[str, Any] = {}

    async def fake_expected(*, db: Any, request: Any) -> ExpectedReadModelCounts:
        calls["expected"] = request.date_range.date_to_exclusive
        return ExpectedReadModelCounts(counts={"orders": None})

    async def fake_collect(
        *, db: Any, request: Any, expected: ExpectedReadModelCounts
    ) -> ReconciliationSummary:
        calls["collect"] = (db, request.seller_id, expected.counts["orders"])
        return ReconciliationSummary(
            seller_id=request.seller_id,
            date_from=request.date_range.date_from,
            date_to=request.date_range.date_to,
            dry_run=True,
            approved_runtime=True,
            write_enabled=False,
            aggregates=(
                ReadModelAggregate(
                    read_model="orders",
                    expected_count=None,
                    persisted_count=4,
                    missing_count=None,
                    complete_count=3,
                    truth_mode="unavailable",
                    field_counts={"buyer_id": {"present": 4}},
                ),
            ),
            raw_context={"seller_id": "82453304", "access_token": "SENTINEL_TOKEN"},
        )

    monkeypatch.setattr(zelerdata_read_model_reconcile, "create_runtime_db", lambda: db)
    monkeypatch.setattr(
        zelerdata_read_model_reconcile,
        "collect_expected_read_model_counts",
        fake_expected,
    )
    monkeypatch.setattr(zelerdata_read_model_reconcile, COLLECTOR_ATTR, fake_collect)

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
        ]
    )

    output = json.loads(capsys.readouterr().out)
    output_json = json.dumps(output, sort_keys=True)

    assert result == 0
    assert output["aggregates"] == [
        {
            "read_model": "orders",
            "expected_count": None,
            "persisted_count": 4,
            "missing_count": None,
            "complete_count": 3,
            "truth_mode": "unavailable",
            "field_counts": {"buyer_id": {"present": 4}},
        }
    ]
    assert calls["expected"] == "2026-06-05T00:00:00Z"
    assert calls["collect"] == (db, "82453304", None)
    assert "82453304" not in output_json
    assert "SENTINEL_TOKEN" not in output_json


@pytest.mark.asyncio
async def test_orders_outside_date_range_are_aggregate_drift_not_missing() -> None:
    db = FakeAsyncDb(
        {
            "orders": [
                _seller_doc(
                    _id="ORDER-PII-IN-RANGE",
                    date_created=_dt(2),
                    items=[{}],
                    status="paid",
                ),
                _seller_doc(
                    _id="ORDER-PII-OUT-OF-RANGE",
                    date_created=_dt(6),
                    items=[{}],
                    status="paid",
                ),
            ],
        }
    )

    summary = await collect_reconciliation_counts(
        db=db,
        request=_request(),
        expected=ExpectedReadModelCounts(
            counts={"orders": 3},
            refs={"orders": _expected_order_refs()},
        ),
        read_models=("orders",),
    )

    output = summary.to_sanitized_dict()
    aggregate = output["aggregates"][0]
    sorted_refs = sorted(_expected_order_refs())
    bounded_id_lookup = {"seller_id": "82453304", "_id": {"$in": sorted_refs}}
    bounded_date_lookup = {
        **bounded_id_lookup,
        "date_created": {"$gte": _dt(1), "$lt": _dt(5)},
    }

    assert aggregate["persisted_count"] == 1
    assert aggregate["missing_count"] == 1
    assert aggregate["out_of_range_by_date_created"] == 1
    assert bounded_id_lookup in db["orders"].count_filters
    assert bounded_date_lookup in db["orders"].count_filters
    assert {"seller_id": "82453304"} not in db["orders"].count_filters

    sanitized_json = json.dumps(output, sort_keys=True)
    for forbidden in (*sorted_refs, "82453304"):
        assert forbidden not in sanitized_json


def test_order_out_of_range_counter_is_sanitized_and_non_zero_only() -> None:
    without_drift = ReadModelAggregate(
        read_model="orders",
        expected_count=1,
        persisted_count=1,
        missing_count=0,
        complete_count=1,
        out_of_range_by_date_created=0,
    ).to_sanitized_dict()
    with_drift = ReadModelAggregate(
        read_model="orders",
        expected_count=3,
        persisted_count=1,
        missing_count=1,
        complete_count=1,
        out_of_range_by_date_created=1,
    ).to_sanitized_dict()

    assert "out_of_range_by_date_created" not in without_drift
    assert with_drift["out_of_range_by_date_created"] == 1


@pytest.mark.asyncio
async def test_order_date_classification_preserves_unavailable_and_non_order_semantics() -> None:
    db = FakeAsyncDb(
        {
            "orders": [_seller_doc(_id="ORDER-PII-SELLER-WIDE", date_created=_dt(2))],
            "shipments": [_seller_doc(_id="SHIP-PII-PRESENT", order_id="ORDER-PII-1")],
        }
    )

    summary = await collect_reconciliation_counts(
        db=db,
        request=_request(),
        expected=ExpectedReadModelCounts(
            counts={"orders": None, "shipments": 2},
            refs={"shipments": frozenset({"SHIP-PII-PRESENT"})},
            truth_mode={"orders": "unavailable", "shipments": "expected"},
            issues=(
                ReadModelIssue(
                    read_model="orders",
                    code="expected_unavailable",
                    message="SENTINEL raw order source failure",
                ),
            ),
        ),
        read_models=("orders", "shipments"),
    )

    output = summary.to_sanitized_dict()
    by_model = {aggregate["read_model"]: aggregate for aggregate in output["aggregates"]}

    assert by_model["orders"]["expected_count"] is None
    assert by_model["orders"]["missing_count"] is None
    assert by_model["orders"]["truth_mode"] == "unavailable"
    assert "out_of_range_by_date_created" not in by_model["orders"]
    assert by_model["shipments"]["persisted_count"] == 1
    assert by_model["shipments"]["missing_count"] == 1

    sanitized_json = json.dumps(output, sort_keys=True)
    for forbidden in ("ORDER-PII", "SHIP-PII", "82453304", "SENTINEL"):
        assert forbidden not in sanitized_json


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
        "--max-items",
        "--max-shipments",
        "--sleep-ms",
        "--resume-after-order-id",
        "ZELERDATA_ENRICHMENT_ENABLED",
        "rollback-to-NA",
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
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from infra.operations import zelerdata_read_model_reconcile

    db = FakeAsyncDb({})

    async def fake_expected(*, db: Any, request: Any) -> ExpectedReadModelCounts:
        return ExpectedReadModelCounts(counts={})

    async def fake_collect(
        *, db: Any, request: Any, expected: ExpectedReadModelCounts
    ) -> ReconciliationSummary:
        return ReconciliationSummary(
            seller_id=request.seller_id,
            date_from=request.date_range.date_from,
            date_to=request.date_range.date_to,
            dry_run=True,
            approved_runtime=True,
            write_enabled=False,
            aggregates=(),
        )

    monkeypatch.setattr(zelerdata_read_model_reconcile, "create_runtime_db", lambda: db)
    monkeypatch.setattr(
        zelerdata_read_model_reconcile,
        "collect_expected_read_model_counts",
        fake_expected,
    )
    monkeypatch.setattr(zelerdata_read_model_reconcile, COLLECTOR_ATTR, fake_collect)

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


def test_reconciliation_cli_write_executes_write_gate_and_outputs_sanitized_counts(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from infra.operations import zelerdata_read_model_reconcile

    db = FakeAsyncDb({})
    calls: dict[str, Any] = {}

    async def fake_expected(*, db: Any, request: Any) -> ExpectedReadModelCounts:
        return ExpectedReadModelCounts(counts={"orders": 1})

    async def fake_collect(
        *, db: Any, request: Any, expected: ExpectedReadModelCounts
    ) -> ReconciliationSummary:
        return ReconciliationSummary(
            seller_id=request.seller_id,
            date_from=request.date_range.date_from,
            date_to=request.date_range.date_to,
            dry_run=False,
            approved_runtime=True,
            write_enabled=True,
            aggregates=(),
            controls=request.controls,
        )

    async def fake_write(*, db: Any, request: Any) -> dict[str, int]:
        calls["write"] = (db, request.write_enabled, request.controls.sleep_ms)
        return {"planned_orders": 1, "written_orders": 1, "written_items": 1}

    monkeypatch.setattr(zelerdata_read_model_reconcile, "create_runtime_db", lambda: db)
    monkeypatch.setattr(
        zelerdata_read_model_reconcile,
        "collect_expected_read_model_counts",
        fake_expected,
    )
    monkeypatch.setattr(zelerdata_read_model_reconcile, COLLECTOR_ATTR, fake_collect)
    monkeypatch.setattr(zelerdata_read_model_reconcile, "execute_reconciliation_write", fake_write)

    result = zelerdata_read_model_reconcile.main(
        [
            "--seller-id",
            "82453304",
            "--date-from",
            "2026-06-01",
            "--date-to",
            "2026-06-04",
            "--write",
            "--confirm-approved-runtime",
            "--confirm-production-write",
            "--sleep-ms",
            "50",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    output_json = json.dumps(output, sort_keys=True)

    assert result == 0
    assert calls["write"] == (db, True, 50)
    assert output["write_counts"] == {
        "planned_orders": 1,
        "written_items": 1,
        "written_orders": 1,
    }
    assert "82453304" not in output_json


@pytest.mark.parametrize("dockerfile_path", SHEETS_RUNTIME_DOCKERFILES)
def test_sheets_runtime_images_copy_operations_helper_for_phase2_contract(
    dockerfile_path: Path,
) -> None:
    dockerfile = dockerfile_path.read_text(encoding="utf-8")

    assert ZELERDATA_RECONCILE_HELPER.is_file()
    assert OPERATIONS_COPY_STANZA in dockerfile
    assert "COPY infra ./infra" not in dockerfile
    assert dockerfile.index("COPY core ./core") < dockerfile.index(OPERATIONS_COPY_STANZA)
    assert dockerfile.index(OPERATIONS_COPY_STANZA) < dockerfile.index(
        "COPY modules/sheets ./modules/sheets"
    )
