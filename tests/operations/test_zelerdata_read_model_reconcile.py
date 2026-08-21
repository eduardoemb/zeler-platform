from __future__ import annotations

import asyncio
import json
import os
import re
import stat
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from infra.mongo.validator_contract import validate_document_against_schema
from infra.operations import zelerdata_read_model_reconcile as reconcile_operation_module
from infra.operations.zelerdata_read_model_reconcile import (
    DEFAULT_PHASE2_DRY_RUN_SCOPES,
    DEFAULT_PHASE2_PREFLIGHT_TARGETS,
    READ_MODELS,
    ExpectedReadModelCounts,
    FocusedRuntimeEvidence,
    PrivateExportRecord,
    ReadModelAggregate,
    ReadModelIssue,
    ReconciliationSummary,
    ScheduledRunSample,
    ScheduledTransportEnvelope,
    build_arg_parser,
    build_phase2_runtime_contract,
    build_reconciliation_request,
    collect_expected_read_model_counts,
    collect_reconciliation_counts,
    evaluate_timing_campaign,
    execute_observed_pause_basis_repair,
    scheduled_sample_from_summary,
    validate_reconciliation_safety,
)
from infra.operations.zelerdata_read_model_reconcile import (
    execute_reconciliation_write as _execute_reconciliation_write,
)
from infra.operations.zelerdata_read_model_reconcile import (
    write_complete_read_model_freshness_markers as _write_complete_read_model_freshness_markers,
)
from infra.operations.zelerdata_scheduled_evidence import build_scheduled_evidence

from zeler_platform_core.devoluciones_readiness import DevolucionesOperationContext
from zeler_sheets import devoluciones_reconciliation as devoluciones_module
from zeler_sheets.claim_projection import ClaimProjectionError, ClaimProjectionReason
from zeler_sheets.devoluciones_reconciliation import ClaimInventoryError
from zeler_sheets.formulas.read_models import read_model_reconciliation_marker_covers

SHEETS_RUNTIME_DOCKERFILES = (
    Path("modules/sheets/Dockerfile.api"),
    Path("modules/sheets/Dockerfile.worker"),
)
ZELERDATA_RECONCILE_HELPER = Path("infra/operations/zelerdata_read_model_reconcile.py")
OPERATIONS_COPY_STANZA = "COPY infra/operations ./infra/operations"
COLLECTOR_ATTR = "collect_reconciliation_counts"
ROOT = Path(__file__).resolve().parents[2]


def _operation() -> DevolucionesOperationContext:
    return DevolucionesOperationContext(
        seller_id="82453304",
        scope="devoluciones",
        operation_id="operations-unit-test",
        attempt_token=uuid4().hex,
        fence=1,
        owns_lease=True,
    )


async def execute_reconciliation_write(**kwargs: Any) -> dict[str, int]:
    kwargs.setdefault("operation", _operation())
    return await _execute_reconciliation_write(**kwargs)


async def write_complete_read_model_freshness_markers(**kwargs: Any) -> dict[str, int]:
    kwargs.setdefault("operation", _operation())
    return await _write_complete_read_model_freshness_markers(**kwargs)


@pytest.fixture(autouse=True)
def _reconciliation_root_fencing_test_harness(monkeypatch: pytest.MonkeyPatch) -> None:
    async def acquire(**kwargs: Any) -> DevolucionesOperationContext:
        return DevolucionesOperationContext(
            seller_id=str(kwargs["seller_id"]),
            scope="devoluciones",
            operation_id=str(kwargs["operation_id"]),
            attempt_token=uuid4().hex,
            fence=1,
            owns_lease=True,
        )

    async def finish(**kwargs: Any) -> None:
        del kwargs

    async def guarded_write(**kwargs: Any) -> None:
        await kwargs["writer"](None)

    @asynccontextmanager
    async def heartbeat(**kwargs: Any) -> Any:
        del kwargs
        yield

    monkeypatch.setattr(reconcile_operation_module, "acquire_devoluciones_operation", acquire)
    monkeypatch.setattr(reconcile_operation_module, "finish_devoluciones_operation", finish)
    monkeypatch.setattr(reconcile_operation_module, "guarded_devoluciones_write", guarded_write)
    monkeypatch.setattr(reconcile_operation_module, "maintain_devoluciones_heartbeat", heartbeat)


class FakeAsyncCollection:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.documents = documents
        self.count_filters: list[dict[str, Any]] = []
        self.updates: list[tuple[dict[str, Any], dict[str, Any], bool]] = []

    async def count_documents(self, filter_spec: dict[str, Any]) -> int:
        self.count_filters.append(filter_spec)
        return sum(1 for document in self.documents if _matches_filter(document, filter_spec))

    async def find_one(self, filter_spec: dict[str, Any]) -> dict[str, Any] | None:
        for document in self.documents:
            if _matches_filter(document, filter_spec):
                return dict(document)
        return None

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

    def find(self, filter_spec: dict[str, Any], projection: dict[str, int] | None = None) -> Any:
        del projection

        async def cursor() -> Any:
            for document in self.documents:
                if _matches_filter(document, filter_spec):
                    yield dict(document)

        return cursor()

    async def distinct(self, field_name: str, filter_spec: dict[str, Any]) -> list[Any]:
        values: dict[Any, None] = {}
        for document in self.documents:
            if not _matches_filter(document, filter_spec):
                continue
            value = _lookup(document, field_name)
            if value is not None and str(value).strip():
                values.setdefault(value, None)
        return list(values)

    async def update_one(
        self,
        filter_spec: dict[str, Any],
        update_spec: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> Any:
        self.updates.append((filter_spec, update_spec, upsert))
        for document in self.documents:
            if not _matches_filter(document, filter_spec):
                continue
            if "$set" in update_spec:
                document.update(dict(update_spec["$set"]))
            return type(
                "UpdateResult",
                (),
                {"modified_count": 1, "upserted_id": None},
            )()
        if upsert:
            replacement = dict(update_spec.get("$set", {}))
            replacement.setdefault("_id", filter_spec.get("_id"))
            self.documents.append(replacement)
        return type(
            "UpdateResult",
            (),
            {"modified_count": 1, "upserted_id": filter_spec.get("_id")},
        )()


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
    questions_found: int | None = None
    question_ids: list[str] | None = None
    question_detail_missing: int = 0
    claims_found: int | None = None
    claim_ids: list[str] | None = None
    planned_orders: int = 0
    planned_items: int = 0
    planned_shipments: int = 0
    planned_claims: int = 0
    written_orders: int = 0
    written_items: int = 0
    written_shipments: int = 0
    written_claims: int = 0
    item_detail_missing: int = 0
    redacted_errors: int = 0
    claim_source_fingerprint: str | None = None
    claim_read_model_fingerprint: str | None = None


@dataclass(frozen=True)
class FakeWriteSummary:
    items_updated: int = 0
    items_planned: int = 0
    batches_fetched: int = 0
    diagnostic_reason_counts: dict[str, int] | None = None
    formula_row_upserts: int = 0
    sku_index_upserts: int = 0


def test_historical_expected_counts_preserve_source_and_local_proof_fingerprints() -> None:
    expected = reconcile_operation_module._historical_meli_expected_counts(
        FakeHistoricalMeliSummary(
            orders_found=1,
            order_ids=["order-1"],
            shipment_ids=[],
            item_ids=["MLA1"],
            claims_found=1,
            claim_ids=["claim-1"],
            claim_source_fingerprint="hydrated-source-proof",
            claim_read_model_fingerprint="local-comparable-proof",
        )
    )

    assert expected.source_fingerprint == "hydrated-source-proof"
    assert expected.read_model_fingerprint == "local-comparable-proof"
    assert expected.refs["claims"] == frozenset({"claim-1"})


@dataclass(frozen=True)
class FakeObservedSeedSummary:
    price_snapshots_planned: int = 0
    price_snapshots_updated: int = 0
    stockout_snapshots_planned: int = 0
    stockout_snapshots_updated: int = 0


@dataclass(frozen=True)
class FakeSourceGatedSummary:
    stock_time_metrics_planned: int = 1
    stock_time_metrics_updated: int = 1
    catalog_time_metrics_planned: int = 1
    catalog_time_metrics_updated: int = 1
    full_withdrawals_planned: int = 1
    full_withdrawals_updated: int = 1
    stock_time_item_ids: list[str] | None = None
    catalog_time_item_ids: list[str] | None = None
    full_withdrawal_ids: list[str] | None = None
    coverage_basis: dict[str, str] | None = None
    coverage_complete: dict[str, bool] | None = None
    source_inventory_counts: dict[str, int] | None = None


def _matches_filter(document: dict[str, Any], filter_spec: dict[str, Any]) -> bool:
    for key, expected in filter_spec.items():
        if key == "$or":
            if not any(_matches_filter(document, branch) for branch in expected):
                return False
            continue
        actual = _lookup(document, key)
        if isinstance(expected, dict):
            for operator, operand in expected.items():
                if operator == "$gte" and not (actual is not None and actual >= operand):
                    return False
                if operator == "$lt" and not (actual is not None and actual < operand):
                    return False
                if operator == "$in" and actual not in operand:
                    return False
                if operator == "$nin" and actual in operand:
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


def _complete_price_stockout_summary(request: Any) -> ReconciliationSummary:
    return ReconciliationSummary(
        seller_id=request.seller_id,
        date_from=request.date_range.date_from,
        date_to=request.date_range.date_to,
        dry_run=False,
        approved_runtime=True,
        write_enabled=True,
        aggregates=(
            ReadModelAggregate(
                read_model="price_history_snapshots",
                expected_count=1,
                persisted_count=1,
                missing_count=0,
                complete_count=1,
            ),
            ReadModelAggregate(
                read_model="stockout_snapshots",
                expected_count=1,
                persisted_count=1,
                missing_count=0,
                complete_count=1,
            ),
        ),
    )


@pytest.mark.asyncio
async def test_expected_counts_passes_catalog_gateway_to_historical_backfill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from infra.operations import zelerdata_read_model_reconcile

    from zeler_sheets import historical_meli_backfill

    primary_gateway = object()
    order_detail_gateway = object()
    catalog_gateway = object()
    captured_catalog_gateway: dict[str, Any] = {}

    async def fake_historical_backfill(**kwargs: Any) -> FakeHistoricalMeliSummary:
        captured_catalog_gateway["value"] = kwargs["catalog_gateway"]
        assert kwargs["gateway"] is primary_gateway
        assert kwargs["order_detail_gateway"] is order_detail_gateway
        return FakeHistoricalMeliSummary(orders_found=0, order_ids=[], shipment_ids=[], item_ids=[])

    monkeypatch.setattr(
        zelerdata_read_model_reconcile,
        "create_runtime_historical_meli_gateways",
        lambda: type(
            "Gateways",
            (),
            {
                "gateway": primary_gateway,
                "order_detail_gateway": order_detail_gateway,
                "catalog_gateway": catalog_gateway,
            },
        )(),
    )
    monkeypatch.setattr(
        historical_meli_backfill, "run_historical_meli_backfill", fake_historical_backfill
    )

    await zelerdata_read_model_reconcile._collect_historical_meli_expected_counts(
        db=FakeAsyncDb({}), request=_request()
    )

    assert captured_catalog_gateway["value"] is catalog_gateway


@pytest.mark.asyncio
async def test_reconciliation_write_passes_catalog_gateway_to_historical_backfill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from infra.operations import zelerdata_read_model_reconcile

    from zeler_sheets import historical_meli_backfill, sheetseller_backfill

    primary_gateway = object()
    order_detail_gateway = object()
    catalog_gateway = object()
    captured_catalog_gateway: dict[str, Any] = {}

    async def fake_historical_backfill(**kwargs: Any) -> FakeHistoricalMeliSummary:
        captured_catalog_gateway["value"] = kwargs["catalog_gateway"]
        assert kwargs["gateway"] is primary_gateway
        assert kwargs["order_detail_gateway"] is order_detail_gateway
        return FakeHistoricalMeliSummary(orders_found=0, order_ids=[], shipment_ids=[], item_ids=[])

    async def fake_item_enrichment(**_: Any) -> FakeWriteSummary:
        return FakeWriteSummary()

    async def fake_formula_rebuild(**_: Any) -> FakeWriteSummary:
        return FakeWriteSummary()

    monkeypatch.setattr(
        zelerdata_read_model_reconcile,
        "create_runtime_historical_meli_gateways",
        lambda: type(
            "Gateways",
            (),
            {
                "gateway": primary_gateway,
                "order_detail_gateway": order_detail_gateway,
                "catalog_gateway": catalog_gateway,
            },
        )(),
    )
    monkeypatch.setattr(
        historical_meli_backfill, "run_historical_meli_backfill", fake_historical_backfill
    )
    monkeypatch.setattr(sheetseller_backfill, "run_item_detail_enrichment", fake_item_enrichment)
    monkeypatch.setattr(sheetseller_backfill, "run_sheetseller_backfill", fake_formula_rebuild)

    await execute_reconciliation_write(db=FakeAsyncDb({}), request=_write_request())

    assert captured_catalog_gateway["value"] is catalog_gateway


@pytest.mark.asyncio
async def test_reconciliation_write_passes_max_items_to_observed_seed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from infra.operations import zelerdata_read_model_reconcile

    from zeler_sheets import (
        historical_meli_backfill,
        remaining_read_model_writers,
        sheetseller_backfill,
    )

    captured_observed_seed_kwargs: dict[str, Any] = {}

    async def fake_historical_backfill(**_: Any) -> FakeHistoricalMeliSummary:
        return FakeHistoricalMeliSummary(orders_found=0, order_ids=[], shipment_ids=[], item_ids=[])

    async def fake_item_enrichment(**_: Any) -> FakeWriteSummary:
        return FakeWriteSummary()

    async def fake_formula_rebuild(**_: Any) -> FakeWriteSummary:
        return FakeWriteSummary()

    async def fake_observed_seed(
        *, db: Any, seller_id: str, dry_run: bool, max_items: int | None
    ) -> FakeObservedSeedSummary:
        captured_observed_seed_kwargs.update(
            {"db": db, "seller_id": seller_id, "dry_run": dry_run, "max_items": max_items}
        )
        return FakeObservedSeedSummary()

    monkeypatch.setattr(
        zelerdata_read_model_reconcile,
        "create_runtime_historical_meli_gateways",
        lambda: type(
            "Gateways",
            (),
            {"gateway": object(), "order_detail_gateway": object(), "catalog_gateway": object()},
        )(),
    )
    monkeypatch.setattr(
        historical_meli_backfill, "run_historical_meli_backfill", fake_historical_backfill
    )
    monkeypatch.setattr(sheetseller_backfill, "run_item_detail_enrichment", fake_item_enrichment)
    monkeypatch.setattr(sheetseller_backfill, "run_sheetseller_backfill", fake_formula_rebuild)
    monkeypatch.setattr(
        remaining_read_model_writers,
        "run_remaining_observed_read_model_seed",
        fake_observed_seed,
    )

    db = FakeAsyncDb({})
    await execute_reconciliation_write(
        db=db, request=_write_request(extra_args=["--max-items", "2"])
    )

    assert captured_observed_seed_kwargs == {
        "db": db,
        "seller_id": "82453304",
        "dry_run": False,
        "max_items": 2,
    }


@pytest.mark.parametrize(
    "extra_args",
    [
        ["--max-orders", "1"],
        ["--max-shipments", "1"],
        ["--resume-after-order-id", "ORDER-PII-RESUME"],
    ],
    ids=("max-orders", "max-shipments", "resume-after-order-id"),
)
@pytest.mark.asyncio
async def test_non_item_bounded_write_controls_skip_observed_seed(
    monkeypatch: pytest.MonkeyPatch, extra_args: list[str]
) -> None:
    from infra.operations import zelerdata_read_model_reconcile

    from zeler_sheets import (
        historical_meli_backfill,
        remaining_read_model_writers,
        sheetseller_backfill,
    )

    async def fake_historical_backfill(**_: Any) -> FakeHistoricalMeliSummary:
        return FakeHistoricalMeliSummary(orders_found=0, order_ids=[], shipment_ids=[], item_ids=[])

    async def fake_item_enrichment(**_: Any) -> FakeWriteSummary:
        return FakeWriteSummary()

    async def fake_formula_rebuild(**_: Any) -> FakeWriteSummary:
        return FakeWriteSummary()

    async def forbidden_observed_seed(**kwargs: Any) -> FakeObservedSeedSummary:
        raise AssertionError(
            f"observed seed should be skipped for unsafe bounded controls: {kwargs!r}"
        )

    monkeypatch.setattr(
        zelerdata_read_model_reconcile,
        "create_runtime_historical_meli_gateways",
        lambda: type(
            "Gateways",
            (),
            {"gateway": object(), "order_detail_gateway": object(), "catalog_gateway": object()},
        )(),
    )
    monkeypatch.setattr(
        historical_meli_backfill, "run_historical_meli_backfill", fake_historical_backfill
    )
    monkeypatch.setattr(sheetseller_backfill, "run_item_detail_enrichment", fake_item_enrichment)
    monkeypatch.setattr(sheetseller_backfill, "run_sheetseller_backfill", fake_formula_rebuild)
    monkeypatch.setattr(
        remaining_read_model_writers,
        "run_remaining_observed_read_model_seed",
        forbidden_observed_seed,
    )

    counts = await execute_reconciliation_write(
        db=FakeAsyncDb({}), request=_write_request(extra_args=extra_args)
    )

    assert "price_history_snapshots_updated" not in counts
    assert "stockout_snapshots_updated" not in counts


@pytest.mark.parametrize(
    "extra_args",
    [
        ["--max-orders", "1"],
        ["--max-shipments", "1"],
        ["--resume-after-order-id", "ORDER-PII-RESUME"],
    ],
    ids=("max-orders", "max-shipments", "resume-after-order-id"),
)
@pytest.mark.asyncio
async def test_non_item_bounded_write_controls_skip_source_gated_import(
    monkeypatch: pytest.MonkeyPatch, extra_args: list[str]
) -> None:
    from infra.operations import zelerdata_read_model_reconcile

    from zeler_sheets import (
        historical_meli_backfill,
        sheetseller_backfill,
        source_gated_read_model_writers,
    )

    async def fake_historical_backfill(**_: Any) -> FakeHistoricalMeliSummary:
        return FakeHistoricalMeliSummary(orders_found=0, order_ids=[], shipment_ids=[], item_ids=[])

    async def fake_item_enrichment(**_: Any) -> FakeWriteSummary:
        return FakeWriteSummary()

    async def fake_formula_rebuild(**_: Any) -> FakeWriteSummary:
        return FakeWriteSummary()

    async def forbidden_source_gated_import(**kwargs: Any) -> FakeSourceGatedSummary:
        raise AssertionError(
            f"source-gated import should be skipped for non-item bounded write controls: {kwargs!r}"
        )

    monkeypatch.setattr(
        zelerdata_read_model_reconcile,
        "create_runtime_historical_meli_gateways",
        lambda: type(
            "Gateways",
            (),
            {"gateway": object(), "order_detail_gateway": object(), "catalog_gateway": object()},
        )(),
    )
    monkeypatch.setattr(
        historical_meli_backfill, "run_historical_meli_backfill", fake_historical_backfill
    )
    monkeypatch.setattr(sheetseller_backfill, "run_item_detail_enrichment", fake_item_enrichment)
    monkeypatch.setattr(sheetseller_backfill, "run_sheetseller_backfill", fake_formula_rebuild)
    monkeypatch.setattr(
        source_gated_read_model_writers,
        "run_source_gated_read_model_import",
        forbidden_source_gated_import,
    )

    counts = await execute_reconciliation_write(
        db=FakeAsyncDb({}), request=_write_request(extra_args=extra_args)
    )

    assert counts["source_gated_import_skipped_bounded_controls"] == 1
    assert "stock_time_metrics_updated" not in counts
    assert "catalog_time_metrics_updated" not in counts
    assert "full_withdrawals_updated" not in counts


@pytest.mark.parametrize(
    "extra_args",
    [
        ["--max-orders", "1"],
        ["--max-shipments", "1"],
        ["--resume-after-order-id", "ORDER-PII-RESUME"],
    ],
    ids=("max-orders", "max-shipments", "resume-after-order-id"),
)
@pytest.mark.asyncio
async def test_non_item_bounded_source_gated_expected_counts_and_markers_are_skipped(
    monkeypatch: pytest.MonkeyPatch, extra_args: list[str]
) -> None:
    from infra.operations import zelerdata_read_model_reconcile

    from zeler_sheets import source_gated_read_model_writers

    source_gated_import_calls: list[dict[str, Any]] = []

    async def fake_source_gated_import(**kwargs: Any) -> FakeSourceGatedSummary:
        source_gated_import_calls.append(kwargs)
        return FakeSourceGatedSummary(
            stock_time_item_ids=["MLA1"],
            catalog_time_item_ids=["MLA1"],
            full_withdrawal_ids=["82453304:RET-1:PKG-1:INV-1"],
            coverage_basis={
                "stock_time_metrics": "legacy_imported",
                "catalog_time_metrics": "legacy_imported",
                "full_withdrawals": "legacy_imported",
            },
            coverage_complete={
                "stock_time_metrics": True,
                "catalog_time_metrics": True,
                "full_withdrawals": True,
            },
            source_inventory_counts={
                "stock_time_metrics": 1,
                "catalog_time_metrics": 1,
                "full_withdrawals": 1,
            },
        )

    monkeypatch.setattr(
        source_gated_read_model_writers,
        "run_source_gated_read_model_import",
        fake_source_gated_import,
    )

    db = FakeAsyncDb({})
    request = _write_request(extra_args=extra_args)
    expected = await zelerdata_read_model_reconcile._collect_source_gated_expected_counts(
        db=db, request=request
    )
    summary = ReconciliationSummary(
        seller_id=request.seller_id,
        date_from=request.date_range.date_from,
        date_to=request.date_range.date_to,
        dry_run=False,
        approved_runtime=True,
        write_enabled=True,
        aggregates=(
            ReadModelAggregate(
                read_model="stock_time_metrics",
                expected_count=1,
                persisted_count=1,
                missing_count=0,
                complete_count=1,
                truth_mode="legacy_imported",
            ),
            ReadModelAggregate(
                read_model="catalog_time_metrics",
                expected_count=1,
                persisted_count=1,
                missing_count=0,
                complete_count=1,
                truth_mode="legacy_imported",
            ),
            ReadModelAggregate(
                read_model="full_withdrawals",
                expected_count=1,
                persisted_count=1,
                missing_count=0,
                complete_count=1,
                truth_mode="legacy_imported",
            ),
        ),
    )
    marker_counts = await write_complete_read_model_freshness_markers(
        db=db, request=request, summary=summary
    )

    assert source_gated_import_calls == []
    assert expected.counts == {
        "stock_time_metrics": None,
        "catalog_time_metrics": None,
        "full_withdrawals": None,
    }
    assert expected.truth_mode == {
        "stock_time_metrics": "source_deferred",
        "catalog_time_metrics": "source_deferred",
        "full_withdrawals": "source_deferred",
    }
    assert {issue.code for issue in expected.issues} == {
        "source_gated_import_skipped_bounded_controls"
    }
    assert marker_counts == {}
    assert db["sheets_read_model_freshness"].documents == []
    assert db["sheets_read_model_freshness"].updates == []


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


def test_observed_pause_basis_repair_write_requires_explicit_max_items() -> None:
    parser = build_arg_parser()
    unbounded_repair = parser.parse_args(
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
            "--repair-observed-pause-basis",
        ]
    )

    with pytest.raises(
        SystemExit,
        match="--max-items is required with --repair-observed-pause-basis --write",
    ):
        validate_reconciliation_safety(unbounded_repair)

    bounded_repair = parser.parse_args(
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
            "--repair-observed-pause-basis",
            "--max-items",
            "25",
        ]
    )

    validate_reconciliation_safety(bounded_repair)


def test_reconciliation_request_parses_observed_pause_basis_repair_dry_run_flag() -> None:
    args = build_arg_parser().parse_args(
        [
            "--seller-id",
            "82453304",
            "--date-from",
            "2026-06-01",
            "--date-to",
            "2026-06-04",
            "--confirm-approved-runtime",
            "--repair-observed-pause-basis",
        ]
    )

    request = build_reconciliation_request(args)

    assert request.dry_run is True
    assert request.write_enabled is False
    assert request.repair_observed_pause_basis is True


@pytest.mark.asyncio
async def test_observed_pause_basis_repair_reports_sanitized_dry_run_counts() -> None:
    @dataclass(frozen=True)
    class FakeRepairSummary:
        dry_run: bool = True
        candidate_states: int = 2
        states_planned: int = 2
        states_updated: int = 0
        candidate_formula_rows: int = 3
        formula_rows_planned: int = 3
        formula_rows_updated: int = 0
        basis_from_existing_status_timestamp: int = 1
        basis_from_repair_time: int = 1

        def as_dict(self) -> dict[str, int | bool | str]:
            return {
                "seller_id": "82453304",
                "dry_run": self.dry_run,
                "candidate_states": self.candidate_states,
                "states_planned": self.states_planned,
                "states_updated": self.states_updated,
                "candidate_formula_rows": self.candidate_formula_rows,
                "formula_rows_planned": self.formula_rows_planned,
                "formula_rows_updated": self.formula_rows_updated,
                "basis_from_existing_status_timestamp": self.basis_from_existing_status_timestamp,
                "basis_from_repair_time": self.basis_from_repair_time,
            }

    async def fake_repair_runner(**kwargs: Any) -> FakeRepairSummary:
        assert kwargs["seller_id"] == "82453304"
        assert kwargs["dry_run"] is True
        assert kwargs["limit"] is None
        return FakeRepairSummary()

    counts = await execute_observed_pause_basis_repair(
        db=FakeAsyncDb({}), request=_request(), repair_runner=fake_repair_runner
    )

    assert counts == {
        "observed_pause_basis_candidate_states": 2,
        "observed_pause_basis_states_planned": 2,
        "observed_pause_basis_states_updated": 0,
        "observed_pause_basis_candidate_formula_rows": 3,
        "observed_pause_basis_formula_rows_planned": 3,
        "observed_pause_basis_formula_rows_updated": 0,
        "observed_pause_basis_from_existing_status_timestamp": 1,
        "observed_pause_basis_from_repair_time": 1,
    }
    assert "82453304" not in json.dumps(counts, sort_keys=True)


@pytest.mark.asyncio
async def test_observed_pause_basis_repair_write_uses_approved_bounded_request() -> None:
    async def fake_repair_runner(**kwargs: Any) -> Any:
        assert kwargs["seller_id"] == "82453304"
        assert kwargs["dry_run"] is False
        assert kwargs["limit"] == 10

        class Summary:
            def as_dict(self) -> dict[str, int | bool | str]:
                return {
                    "seller_id": "82453304",
                    "dry_run": False,
                    "candidate_states": 1,
                    "states_planned": 1,
                    "states_updated": 1,
                    "candidate_formula_rows": 1,
                    "formula_rows_planned": 1,
                    "formula_rows_updated": 1,
                    "basis_from_existing_status_timestamp": 0,
                    "basis_from_repair_time": 1,
                }

        return Summary()

    counts = await execute_observed_pause_basis_repair(
        db=FakeAsyncDb({}),
        request=_write_request(extra_args=["--repair-observed-pause-basis", "--max-items", "10"]),
        repair_runner=fake_repair_runner,
    )

    assert counts["observed_pause_basis_states_updated"] == 1
    assert counts["observed_pause_basis_formula_rows_updated"] == 1


@pytest.mark.asyncio
async def test_observed_pause_basis_repair_write_rejects_unbounded_request_before_runner() -> None:
    base = _write_request(extra_args=["--repair-observed-pause-basis", "--max-items", "1"])
    unsafe_request = base.__class__(
        seller_id=base.seller_id,
        date_range=base.date_range,
        dry_run=False,
        approved_runtime=True,
        write_enabled=True,
        include_buyer_address_pii=False,
        controls=base.controls.__class__(),
        repair_observed_pause_basis=True,
    )

    async def fake_repair_runner(**kwargs: Any) -> Any:
        raise AssertionError(f"repair runner should not be called: {kwargs!r}")

    with pytest.raises(
        ValueError,
        match="--max-items is required with --repair-observed-pause-basis --write",
    ):
        await execute_observed_pause_basis_repair(
            db=FakeAsyncDb({}), request=unsafe_request, repair_runner=fake_repair_runner
        )


def test_reconciliation_write_blocks_unapproved_request_before_marker_write() -> None:
    request = _write_request()
    unsafe_request = request.__class__(
        seller_id=request.seller_id,
        date_range=request.date_range,
        dry_run=False,
        approved_runtime=False,
        write_enabled=True,
        include_buyer_address_pii=False,
        controls=request.controls,
    )
    summary = ReconciliationSummary(
        seller_id=request.seller_id,
        date_from=request.date_range.date_from,
        date_to=request.date_range.date_to,
        dry_run=False,
        approved_runtime=False,
        write_enabled=True,
        aggregates=(
            ReadModelAggregate(
                read_model="questions",
                expected_count=1,
                persisted_count=1,
                missing_count=0,
                complete_count=1,
            ),
        ),
    )

    with pytest.raises(ValueError, match="approved_runtime"):
        asyncio.run(
            write_complete_read_model_freshness_markers(
                db=FakeAsyncDb({}), request=unsafe_request, summary=summary
            )
        )


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
            "questions": [
                _seller_doc(
                    _id="QUESTION-PII-1",
                    date_created=_dt(2),
                    status="ANSWERED",
                    item_id="ITEM-PII-1",
                    text="Still available?",
                    from_user_id="BUYER-PII-1",
                    answer={"text": "Yes", "date_created": _dt(3)},
                ),
            ],
            "claims": [
                _seller_doc(
                    _id="CLAIM-PII-1",
                    date_created=_dt(2),
                    order_id="ORDER-PII-1",
                    item_id="MLA1",
                    status="closed",
                    productive=True,
                    returned_quantity=1,
                    return_quantity_basis="v2_return_order",
                ),
            ],
            "sheets_catalog_product_snapshots": [
                _seller_doc(_id="PRODUCT-PII-1", catalog_product_id="CATALOG-PII-1"),
            ],
            "sheets_catalog_buybox_snapshots": [
                _seller_doc(
                    _id="BUYBOX-PII-1",
                    item_id="ITEM-PII-1",
                    catalog_product_id="CATALOG-PII-1",
                ),
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
                "questions": 1,
                "claims": 1,
                "catalog_product_snapshots": 1,
                "catalog_buybox_snapshots": 1,
                "sheets_item_formula_rows": 2,
                "sheets_item_sku_index": 2,
                "item_status_states": None,
                "item_status_transitions": None,
                "price_history_snapshots": 0,
                "stockout_snapshots": 0,
                "stock_time_metrics": None,
                "catalog_time_metrics": None,
                "full_withdrawals": None,
            },
            refs={
                "shipments": frozenset({"SHIP-PII-1"}),
                "items": frozenset({"ITEM-PII-1"}),
                "catalog_product_snapshots": frozenset({"CATALOG-PII-1"}),
                "catalog_buybox_snapshots": frozenset({"ITEM-PII-1"}),
            },
            truth_mode={
                "items": "unavailable",
                "item_status_states": "observed_only",
                "item_status_transitions": "observed_only",
                "price_history_snapshots": "observed_current",
                "stockout_snapshots": "observed_current",
                "stock_time_metrics": "source_deferred",
                "catalog_time_metrics": "source_deferred",
                "full_withdrawals": "source_deferred",
            },
            issues=(
                ReadModelIssue(
                    read_model="items",
                    code="expected_unavailable",
                    message="expected source unavailable",
                ),
                ReadModelIssue(
                    read_model="stock_time_metrics",
                    code="source_deferred",
                    message="stock time source deferred",
                ),
                ReadModelIssue(
                    read_model="catalog_time_metrics",
                    code="source_deferred",
                    message="catalog time source deferred",
                ),
                ReadModelIssue(
                    read_model="full_withdrawals",
                    code="source_deferred",
                    message="withdrawals source deferred",
                ),
            ),
        ),
    )

    output = summary.to_sanitized_dict()
    by_model = {aggregate["read_model"]: aggregate for aggregate in output["aggregates"]}

    assert set(by_model) == set(READ_MODELS)
    intentionally_empty = {
        "price_history_snapshots",
        "stockout_snapshots",
        "stock_time_metrics",
        "catalog_time_metrics",
        "full_withdrawals",
    }
    assert all(
        aggregate["persisted_count"] > 0
        for read_model, aggregate in by_model.items()
        if read_model not in intentionally_empty
    )
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
    assert by_model["questions"]["persisted_count"] == 1
    assert by_model["questions"]["complete_count"] == 1
    assert by_model["claims"]["persisted_count"] == 1
    assert by_model["claims"]["complete_count"] == 1
    assert by_model["catalog_product_snapshots"]["persisted_count"] == 1
    assert by_model["catalog_buybox_snapshots"]["persisted_count"] == 1
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
        "QUESTION-PII",
        "CLAIM-PII",
        "CATALOG-PII",
        "FORMULA-PII",
        "SKU-PII",
        "STATE-PII",
        "TRANSITION-PII",
        "SENTINEL STREET",
    ):
        assert forbidden not in sanitized_json


@pytest.mark.asyncio
async def test_dry_run_or_incomplete_coverage_does_not_write_reconciliation_markers() -> None:
    db = FakeAsyncDb({})
    request = _request()
    partial_summary = ReconciliationSummary(
        seller_id=request.seller_id,
        date_from=request.date_range.date_from,
        date_to=request.date_range.date_to,
        dry_run=True,
        approved_runtime=True,
        write_enabled=False,
        aggregates=(
            ReadModelAggregate(
                read_model="questions",
                expected_count=2,
                persisted_count=1,
                missing_count=1,
                complete_count=1,
            ),
        ),
    )

    counts = await write_complete_read_model_freshness_markers(
        db=db, request=request, summary=partial_summary
    )

    assert counts == {}
    assert db["sheets_read_model_freshness"].updates == []


@pytest.mark.asyncio
async def test_complete_write_records_shared_reconciliation_marker_after_coverage() -> None:
    db = FakeAsyncDb({})
    request = _write_request()
    summary = ReconciliationSummary(
        seller_id=request.seller_id,
        date_from=request.date_range.date_from,
        date_to=request.date_range.date_to,
        dry_run=False,
        approved_runtime=True,
        write_enabled=True,
        aggregates=(
            ReadModelAggregate(
                read_model="questions",
                expected_count=2,
                persisted_count=2,
                missing_count=0,
                complete_count=2,
            ),
            ReadModelAggregate(
                read_model="catalog_buybox_snapshots",
                expected_count=None,
                persisted_count=1,
                missing_count=None,
                complete_count=1,
                truth_mode="source_deferred",
            ),
        ),
    )

    counts = await write_complete_read_model_freshness_markers(
        db=db, request=request, summary=summary
    )

    assert counts == {"freshness_markers_written": 1}
    markers = db["sheets_read_model_freshness"].documents
    assert {marker["read_model"] for marker in markers} == {"questions"}
    assert all(marker["state"] == "reconciled" for marker in markers)
    validator = json.loads(
        (ROOT / "infra/mongo/schemas/sheets_read_model_freshness.json").read_text()
    )
    schema = validator["$jsonSchema"]
    allowed_fields = set(schema["properties"])
    required_fields = set(schema["required"])
    forbidden_fields = {
        "coverage",
        "expected_count",
        "persisted_count",
        "complete_count",
        "reconciled_at",
    }
    for marker in markers:
        validation = validate_document_against_schema(marker, validator)
        assert validation.valid is True
        assert required_fields <= set(marker)
        assert set(marker) <= allowed_fields
        assert forbidden_fields.isdisjoint(marker)
        assert marker["fresh_until"] == request.date_range.end_exclusive
        assert marker["updated_at"].tzinfo == UTC
        assert marker["last_event_synced_at"] == request.date_range.start
    assert all(marker["reconciled_until"] == request.date_range.end_exclusive for marker in markers)
    assert "catalog_buybox_snapshots" not in {marker["read_model"] for marker in markers}


@pytest.mark.asyncio
async def test_questions_reconciliation_marker_records_requested_range_through_final_day() -> None:
    db = FakeAsyncDb({})
    request = _write_request(extra_args=["--date-to", "2026-06-17"])
    summary = ReconciliationSummary(
        seller_id=request.seller_id,
        date_from=request.date_range.date_from,
        date_to=request.date_range.date_to,
        dry_run=False,
        approved_runtime=True,
        write_enabled=True,
        aggregates=(
            ReadModelAggregate(
                read_model="questions",
                expected_count=1,
                persisted_count=1,
                missing_count=0,
                complete_count=1,
            ),
        ),
    )

    counts = await write_complete_read_model_freshness_markers(
        db=db, request=request, summary=summary
    )

    marker = db["sheets_read_model_freshness"].documents[0]
    assert counts == {"freshness_markers_written": 1}
    assert marker["date_from"] == datetime(2026, 6, 1, tzinfo=UTC)
    assert marker["fresh_until"] == datetime(2026, 6, 18, tzinfo=UTC)
    assert marker["reconciled_until"] == datetime(2026, 6, 18, tzinfo=UTC)
    assert read_model_reconciliation_marker_covers(
        marker,
        date_from=datetime(2026, 6, 1, tzinfo=UTC),
        date_to=datetime(2026, 6, 17, 23, 59, 59, tzinfo=UTC),
    )
    assert (
        validate_document_against_schema(
            marker,
            json.loads((ROOT / "infra/mongo/schemas/sheets_read_model_freshness.json").read_text()),
        ).valid
        is True
    )


@pytest.mark.asyncio
async def test_narrower_marker_write_preserves_wider_existing_reconciled_coverage() -> None:
    existing_date_from = datetime(2026, 5, 1, tzinfo=UTC)
    existing_fresh_until = datetime(2026, 6, 30, tzinfo=UTC)
    existing_collection = FakeAsyncCollection(
        [
            _seller_doc(
                _id="82453304:questions",
                read_model="questions",
                state="reconciled",
                date_from=existing_date_from,
                fresh_until=existing_fresh_until,
                reconciled_until=existing_fresh_until,
                last_event_synced_at=existing_date_from,
                updated_at=_dt(1),
                source="zelerdata_read_model_reconcile",
                schema_version=1,
            )
        ]
    )
    db = FakeAsyncDb({"sheets_read_model_freshness": existing_collection})
    request = _write_request()
    summary = ReconciliationSummary(
        seller_id=request.seller_id,
        date_from=request.date_range.date_from,
        date_to=request.date_range.date_to,
        dry_run=False,
        approved_runtime=True,
        write_enabled=True,
        aggregates=(
            ReadModelAggregate(
                read_model="questions",
                expected_count=1,
                persisted_count=1,
                missing_count=0,
                complete_count=1,
            ),
        ),
    )

    counts = await write_complete_read_model_freshness_markers(
        db=db, request=request, summary=summary
    )

    assert counts == {"freshness_markers_written": 1}
    _, update_spec, _ = existing_collection.updates[-1]
    assert update_spec["$set"]["date_from"] == existing_date_from
    assert update_spec["$set"]["fresh_until"] == existing_fresh_until
    assert update_spec["$set"]["reconciled_until"] == existing_fresh_until


@pytest.mark.asyncio
async def test_legacy_marker_without_date_from_preserves_last_event_synced_coverage() -> None:
    existing_coverage_start = datetime(2026, 5, 1, tzinfo=UTC)
    existing_fresh_until = datetime(2026, 6, 30, tzinfo=UTC)
    existing_collection = FakeAsyncCollection(
        [
            _seller_doc(
                _id="82453304:questions",
                read_model="questions",
                state="reconciled",
                fresh_until=existing_fresh_until,
                reconciled_until=existing_fresh_until,
                last_event_synced_at=existing_coverage_start,
                updated_at=_dt(1),
                source="zelerdata_read_model_reconcile",
                schema_version=1,
            )
        ]
    )
    db = FakeAsyncDb({"sheets_read_model_freshness": existing_collection})
    request = _write_request()
    summary = ReconciliationSummary(
        seller_id=request.seller_id,
        date_from=request.date_range.date_from,
        date_to=request.date_range.date_to,
        dry_run=False,
        approved_runtime=True,
        write_enabled=True,
        aggregates=(
            ReadModelAggregate(
                read_model="questions",
                expected_count=1,
                persisted_count=1,
                missing_count=0,
                complete_count=1,
            ),
        ),
    )

    counts = await write_complete_read_model_freshness_markers(
        db=db, request=request, summary=summary
    )

    marker = existing_collection.documents[0]
    assert counts == {"freshness_markers_written": 1}
    assert marker["date_from"] == existing_coverage_start
    assert marker["last_event_synced_at"] == existing_coverage_start
    assert marker["fresh_until"] == existing_fresh_until
    assert marker["reconciled_until"] == existing_fresh_until


@pytest.mark.asyncio
async def test_disjoint_earlier_marker_write_does_not_claim_gap_before_later_marker() -> None:
    existing_date_from = datetime(2026, 6, 10, tzinfo=UTC)
    existing_fresh_until = datetime(2026, 6, 20, tzinfo=UTC)
    existing_collection = FakeAsyncCollection(
        [
            _seller_doc(
                _id="82453304:questions",
                read_model="questions",
                state="reconciled",
                date_from=existing_date_from,
                fresh_until=existing_fresh_until,
                reconciled_until=existing_fresh_until,
                last_event_synced_at=existing_date_from,
                updated_at=_dt(10),
                source="zelerdata_read_model_reconcile",
                schema_version=1,
            )
        ]
    )
    db = FakeAsyncDb({"sheets_read_model_freshness": existing_collection})
    request = _write_request()
    summary = ReconciliationSummary(
        seller_id=request.seller_id,
        date_from=request.date_range.date_from,
        date_to=request.date_range.date_to,
        dry_run=False,
        approved_runtime=True,
        write_enabled=True,
        aggregates=(
            ReadModelAggregate(
                read_model="questions",
                expected_count=1,
                persisted_count=1,
                missing_count=0,
                complete_count=1,
            ),
        ),
    )

    counts = await write_complete_read_model_freshness_markers(
        db=db, request=request, summary=summary
    )

    marker = existing_collection.documents[0]
    assert counts == {}
    assert existing_collection.updates == []
    assert marker["date_from"] == existing_date_from
    assert marker["fresh_until"] == existing_fresh_until
    assert marker["reconciled_until"] == existing_fresh_until
    assert not read_model_reconciliation_marker_covers(
        marker,
        date_from=request.date_range.start,
        date_to=request.date_range.end_exclusive,
    )


@pytest.mark.asyncio
async def test_inconsistent_legacy_marker_boundaries_do_not_overclaim_coverage() -> None:
    existing_collection = FakeAsyncCollection(
        [
            _seller_doc(
                _id="82453304:questions",
                read_model="questions",
                state="reconciled",
                date_from=datetime(2026, 6, 10, tzinfo=UTC),
                fresh_until=datetime(2026, 6, 20, tzinfo=UTC),
                reconciled_until=datetime(2026, 6, 5, tzinfo=UTC),
                last_event_synced_at=datetime(2026, 6, 1, tzinfo=UTC),
                updated_at=_dt(10),
                source="zelerdata_read_model_reconcile",
                schema_version=1,
            )
        ]
    )
    db = FakeAsyncDb({"sheets_read_model_freshness": existing_collection})
    request = _write_request()
    summary = ReconciliationSummary(
        seller_id=request.seller_id,
        date_from=request.date_range.date_from,
        date_to=request.date_range.date_to,
        dry_run=False,
        approved_runtime=True,
        write_enabled=True,
        aggregates=(
            ReadModelAggregate(
                read_model="questions",
                expected_count=1,
                persisted_count=1,
                missing_count=0,
                complete_count=1,
            ),
        ),
    )

    counts = await write_complete_read_model_freshness_markers(
        db=db, request=request, summary=summary
    )

    marker = existing_collection.documents[0]
    assert counts == {}
    assert existing_collection.updates == []
    assert marker["date_from"] == datetime(2026, 6, 10, tzinfo=UTC)
    assert marker["fresh_until"] == datetime(2026, 6, 20, tzinfo=UTC)
    assert marker["reconciled_until"] == datetime(2026, 6, 5, tzinfo=UTC)


@pytest.mark.parametrize(
    ("existing_date_from", "case_name"),
    [
        (datetime(2026, 6, 3, tzinfo=UTC), "overlapping"),
        (datetime(2026, 6, 5, tzinfo=UTC), "contiguous"),
    ],
    ids=lambda value: value if isinstance(value, str) else value.isoformat(),
)
@pytest.mark.asyncio
async def test_overlapping_or_contiguous_marker_write_merges_without_gaps(
    existing_date_from: datetime, case_name: str
) -> None:
    del case_name
    existing_fresh_until = datetime(2026, 6, 20, tzinfo=UTC)
    existing_collection = FakeAsyncCollection(
        [
            _seller_doc(
                _id="82453304:questions",
                read_model="questions",
                state="reconciled",
                date_from=existing_date_from,
                fresh_until=existing_fresh_until,
                reconciled_until=existing_fresh_until,
                last_event_synced_at=existing_date_from,
                updated_at=_dt(10),
                source="zelerdata_read_model_reconcile",
                schema_version=1,
            )
        ]
    )
    db = FakeAsyncDb({"sheets_read_model_freshness": existing_collection})
    request = _write_request()
    summary = ReconciliationSummary(
        seller_id=request.seller_id,
        date_from=request.date_range.date_from,
        date_to=request.date_range.date_to,
        dry_run=False,
        approved_runtime=True,
        write_enabled=True,
        aggregates=(
            ReadModelAggregate(
                read_model="questions",
                expected_count=1,
                persisted_count=1,
                missing_count=0,
                complete_count=1,
            ),
        ),
    )

    counts = await write_complete_read_model_freshness_markers(
        db=db, request=request, summary=summary
    )

    assert counts == {"freshness_markers_written": 1}
    _, update_spec, _ = existing_collection.updates[-1]
    assert update_spec["$set"]["date_from"] == request.date_range.start
    assert update_spec["$set"]["fresh_until"] == existing_fresh_until
    assert update_spec["$set"]["reconciled_until"] == existing_fresh_until


@pytest.mark.asyncio
async def test_source_gated_interval_marker_write_does_not_merge_broader_existing_range() -> None:
    existing_fresh_until = datetime(2026, 7, 1, tzinfo=UTC)
    existing_collection = FakeAsyncCollection(
        [
            _seller_doc(
                _id="82453304:stock_time_metrics",
                read_model="stock_time_metrics",
                state="reconciled",
                date_from=datetime(2026, 6, 1, tzinfo=UTC),
                fresh_until=existing_fresh_until,
                reconciled_until=existing_fresh_until,
                last_event_synced_at=datetime(2026, 6, 1, tzinfo=UTC),
                coverage_basis="legacy_imported",
                updated_at=_dt(1),
                source="zelerdata_read_model_reconcile",
                schema_version=1,
            )
        ]
    )
    db = FakeAsyncDb({"sheets_read_model_freshness": existing_collection})
    request = _write_request()
    summary = ReconciliationSummary(
        seller_id=request.seller_id,
        date_from=request.date_range.date_from,
        date_to=request.date_range.date_to,
        dry_run=False,
        approved_runtime=True,
        write_enabled=True,
        aggregates=(
            ReadModelAggregate(
                read_model="stock_time_metrics",
                expected_count=1,
                persisted_count=1,
                missing_count=0,
                complete_count=1,
                truth_mode="legacy_imported",
            ),
        ),
    )

    counts = await write_complete_read_model_freshness_markers(
        db=db, request=request, summary=summary
    )

    assert counts == {"freshness_markers_written": 1}
    _, update_spec, _ = existing_collection.updates[-1]
    assert update_spec["$set"]["date_from"] == request.date_range.start
    assert update_spec["$set"]["fresh_until"] == request.date_range.end_exclusive
    assert update_spec["$set"]["reconciled_until"] == request.date_range.end_exclusive


@pytest.mark.asyncio
async def test_price_stockout_markers_do_not_write_for_wrong_item_refs() -> None:
    from infra.operations import zelerdata_read_model_reconcile

    db = FakeAsyncDb(
        {
            "sheets_item_formula_rows": [
                _seller_doc(
                    _id="82453304:SKU-EXPECTED:MLA-EXPECTED",
                    item_id="MLA-EXPECTED",
                    sku="sku-expected",
                    normalized_sku="SKU-EXPECTED",
                    current={
                        "title": "Expected item",
                        "status": "active",
                        "price": 149.99,
                        "available_quantity": 0,
                    },
                    updated_at=_dt(4),
                    schema_version=2,
                )
            ],
            "sheets_price_history_snapshots": [
                _seller_doc(
                    _id="82453304:MLA-WRONG",
                    item_id="MLA-WRONG",
                    prices=[
                        {
                            "price": 149.99,
                            "status": "active",
                            "observed_at": _dt(4),
                            "observation_basis": "current_observed",
                        }
                    ],
                    snapshot_at=_dt(4),
                    source="sheets_backfill",
                    observation_basis="current_observed",
                    schema_version=1,
                )
            ],
            "sheets_stockout_snapshots": [
                _seller_doc(
                    _id="82453304:MLA-WRONG",
                    item_id="MLA-WRONG",
                    observed_at=_dt(4),
                    source="sheets_backfill",
                    observation_basis="zeler_first_observed",
                    stock_state="out_of_stock",
                    current_stock=0,
                    out_of_stock_since=_dt(4),
                    schema_version=1,
                )
            ],
        }
    )
    request = _write_request()
    expected = await zelerdata_read_model_reconcile._collect_remaining_observed_expected_counts(
        db=db,
        seller_id=request.seller_id,
    )

    summary = await collect_reconciliation_counts(
        db=db,
        request=request,
        expected=expected,
        read_models=("price_history_snapshots", "stockout_snapshots"),
    )
    counts = await write_complete_read_model_freshness_markers(
        db=db, request=request, summary=summary
    )

    by_model = {aggregate.read_model: aggregate for aggregate in summary.aggregates}
    assert expected.refs == {
        "price_history_snapshots": frozenset({"MLA-EXPECTED"}),
        "stockout_snapshots": frozenset({"MLA-EXPECTED"}),
    }
    assert by_model["price_history_snapshots"].persisted_count == 0
    assert by_model["stockout_snapshots"].persisted_count == 0
    assert counts == {}
    assert db["sheets_read_model_freshness"].documents == []


@pytest.mark.asyncio
async def test_collect_expected_counts_merges_observed_refs_and_keeps_marker_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from zeler_sheets import sheetseller_backfill

    async def fake_historical_source(*, db: Any, request: Any) -> FakeHistoricalMeliSummary:
        return FakeHistoricalMeliSummary(orders_found=0, order_ids=[], shipment_ids=[], item_ids=[])

    async def fake_formula_rebuild(**_: Any) -> FakeWriteSummary:
        return FakeWriteSummary(formula_row_upserts=1)

    async def fake_order_line_backfill(**_: Any) -> FakeWriteSummary:
        return FakeWriteSummary()

    monkeypatch.setattr(sheetseller_backfill, "run_sheetseller_backfill", fake_formula_rebuild)
    monkeypatch.setattr(
        sheetseller_backfill, "run_order_line_identity_backfill", fake_order_line_backfill
    )
    db = FakeAsyncDb(
        {
            "sheets_item_formula_rows": [
                _seller_doc(
                    _id="82453304:SKU-EXPECTED:MLA-EXPECTED",
                    item_id="MLA-EXPECTED",
                    sku="sku-expected",
                    normalized_sku="SKU-EXPECTED",
                    current={
                        "title": "Expected item",
                        "status": "active",
                        "price": 149.99,
                        "available_quantity": 0,
                    },
                    updated_at=_dt(4),
                    schema_version=2,
                )
            ],
            "sheets_price_history_snapshots": [
                _seller_doc(
                    _id="82453304:MLA-WRONG",
                    item_id="MLA-WRONG",
                    prices=[
                        {
                            "price": 149.99,
                            "status": "active",
                            "observed_at": _dt(4),
                            "observation_basis": "current_observed",
                        }
                    ],
                    snapshot_at=_dt(4),
                    source="sheets_backfill",
                    observation_basis="current_observed",
                    schema_version=1,
                )
            ],
            "sheets_stockout_snapshots": [
                _seller_doc(
                    _id="82453304:MLA-WRONG",
                    item_id="MLA-WRONG",
                    observed_at=_dt(4),
                    source="sheets_backfill",
                    observation_basis="zeler_first_observed",
                    stock_state="out_of_stock",
                    current_stock=0,
                    out_of_stock_since=_dt(4),
                    schema_version=1,
                )
            ],
        }
    )
    request = _write_request()

    expected = await collect_expected_read_model_counts(
        db=db,
        request=request,
        historical_meli_source=fake_historical_source,
    )
    summary = await collect_reconciliation_counts(
        db=db,
        request=request,
        expected=expected,
        read_models=("price_history_snapshots", "stockout_snapshots"),
    )
    counts = await write_complete_read_model_freshness_markers(
        db=db, request=request, summary=summary
    )

    by_model = {aggregate.read_model: aggregate for aggregate in summary.aggregates}
    assert expected.refs["price_history_snapshots"] == frozenset({"MLA-EXPECTED"})
    assert expected.refs["stockout_snapshots"] == frozenset({"MLA-EXPECTED"})
    assert db["sheets_price_history_snapshots"].count_filters[0] == {
        "seller_id": "82453304",
        "item_id": {"$in": ["MLA-EXPECTED"]},
    }
    assert db["sheets_stockout_snapshots"].count_filters[0] == {
        "seller_id": "82453304",
        "item_id": {"$in": ["MLA-EXPECTED"]},
    }
    assert by_model["price_history_snapshots"].persisted_count == 0
    assert by_model["stockout_snapshots"].persisted_count == 0
    assert counts == {}
    assert db["sheets_read_model_freshness"].documents == []


@pytest.mark.asyncio
async def test_observed_price_stockout_ready_and_deferred_models_blocked() -> None:
    db = FakeAsyncDb(
        {
            "sheets_price_history_snapshots": [
                _seller_doc(
                    _id="82453304:MLA1",
                    item_id="MLA1",
                    prices=[
                        {
                            "price": 149.99,
                            "status": "active",
                            "observed_at": _dt(4),
                            "observation_basis": "current_observed",
                        }
                    ],
                    snapshot_at=_dt(4),
                    source="sheets_backfill",
                    observation_basis="current_observed",
                    schema_version=1,
                )
            ],
            "sheets_stockout_snapshots": [
                _seller_doc(
                    _id="82453304:MLA1",
                    item_id="MLA1",
                    observed_at=_dt(4),
                    source="sheets_backfill",
                    observation_basis="zeler_first_observed",
                    stock_state="out_of_stock",
                    current_stock=0,
                    out_of_stock_since=_dt(4),
                    schema_version=1,
                )
            ],
        }
    )
    request = _write_request()
    expected = ExpectedReadModelCounts(
        counts={
            "price_history_snapshots": 1,
            "stockout_snapshots": 1,
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
            "price_history_snapshots": frozenset({"MLA1"}),
            "stockout_snapshots": frozenset({"MLA1"}),
        },
        issues=(
            ReadModelIssue(
                read_model="stock_time_metrics",
                code="source_deferred",
                message="stock time requires accepted semantics",
            ),
            ReadModelIssue(
                read_model="catalog_time_metrics",
                code="source_deferred",
                message="catalog time requires approved interval source",
            ),
            ReadModelIssue(
                read_model="full_withdrawals",
                code="source_deferred",
                message="full withdrawals require approved source/import",
            ),
        ),
    )

    summary = await collect_reconciliation_counts(
        db=db,
        request=request,
        expected=expected,
        read_models=(
            "price_history_snapshots",
            "stockout_snapshots",
            "stock_time_metrics",
            "catalog_time_metrics",
            "full_withdrawals",
        ),
    )
    counts = await write_complete_read_model_freshness_markers(
        db=db, request=request, summary=summary
    )

    output = summary.to_sanitized_dict()
    by_model = {aggregate["read_model"]: aggregate for aggregate in output["aggregates"]}
    assert counts == {"freshness_markers_written": 2}
    assert {marker["read_model"] for marker in db["sheets_read_model_freshness"].documents} == {
        "price_history_snapshots",
        "stockout_snapshots",
    }
    assert by_model["price_history_snapshots"]["complete_count"] == 1
    assert by_model["stockout_snapshots"]["complete_count"] == 1
    assert by_model["stock_time_metrics"]["truth_mode"] == "source_deferred"
    assert by_model["stock_time_metrics"]["issues"] == [{"code": "source_deferred"}]
    assert by_model["catalog_time_metrics"]["truth_mode"] == "source_deferred"
    assert by_model["full_withdrawals"]["truth_mode"] == "source_deferred"


@pytest.mark.asyncio
async def test_source_gated_interval_aggregates_require_exact_reconcile_interval_rows() -> None:
    db = FakeAsyncDb(
        {
            "sheets_stock_time_metrics": [
                _seller_doc(
                    _id="82453304:MLA1:SKU1:2026-06-01:2026-07-01",
                    item_id="MLA1",
                    sku="SKU1",
                    normalized_sku="SKU1",
                    date_from=datetime(2026, 6, 1, tzinfo=UTC),
                    date_to=datetime(2026, 7, 1, tzinfo=UTC),
                    total_hours=720,
                    active_stock_hours=720,
                    source="legacy_history_import",
                    history_basis="legacy_imported",
                    coverage_basis="legacy_imported",
                )
            ],
            "sheets_catalog_time_metrics": [
                _seller_doc(
                    _id="82453304:MLA1:2026-06-01:2026-07-01",
                    item_id="MLA1",
                    date_from=datetime(2026, 6, 1, tzinfo=UTC),
                    date_to=datetime(2026, 7, 1, tzinfo=UTC),
                    available_hours=720,
                    winning_hours=720,
                    source="legacy_history_import",
                    history_basis="legacy_imported",
                    coverage_basis="legacy_imported",
                )
            ],
        }
    )
    request = _write_request()

    summary = await collect_reconciliation_counts(
        db=db,
        request=request,
        expected=ExpectedReadModelCounts(
            counts={"stock_time_metrics": 1, "catalog_time_metrics": 1},
            truth_mode={
                "stock_time_metrics": "legacy_imported",
                "catalog_time_metrics": "legacy_imported",
            },
            refs={
                "stock_time_metrics": frozenset({"MLA1"}),
                "catalog_time_metrics": frozenset({"MLA1"}),
            },
        ),
        read_models=("stock_time_metrics", "catalog_time_metrics"),
    )
    counts = await write_complete_read_model_freshness_markers(
        db=db, request=request, summary=summary
    )

    by_model = {aggregate.read_model: aggregate for aggregate in summary.aggregates}
    assert by_model["stock_time_metrics"].persisted_count == 0
    assert by_model["stock_time_metrics"].complete_count == 0
    assert by_model["catalog_time_metrics"].persisted_count == 0
    assert by_model["catalog_time_metrics"].complete_count == 0
    assert counts == {}
    assert db["sheets_read_model_freshness"].documents == []


@pytest.mark.parametrize(
    "extra_args",
    [
        ["--max-items", "1"],
        ["--max-orders", "1"],
        ["--max-shipments", "1"],
    ],
    ids=("max-items", "max-orders", "max-shipments"),
)
@pytest.mark.asyncio
async def test_bounded_write_controls_skip_global_price_stockout_freshness_markers(
    extra_args: list[str],
) -> None:
    db = FakeAsyncDb({})
    request = _write_request(extra_args=extra_args)
    summary = _complete_price_stockout_summary(request)

    counts = await write_complete_read_model_freshness_markers(
        db=db, request=request, summary=summary
    )

    assert counts == {}
    assert db["sheets_read_model_freshness"].documents == []
    assert db["sheets_read_model_freshness"].updates == []


@pytest.mark.asyncio
async def test_unbounded_complete_price_stockout_coverage_writes_global_freshness_markers() -> None:
    db = FakeAsyncDb({})
    request = _write_request()
    summary = _complete_price_stockout_summary(request)

    counts = await write_complete_read_model_freshness_markers(
        db=db, request=request, summary=summary
    )

    markers = db["sheets_read_model_freshness"].documents
    assert counts == {"freshness_markers_written": 2}
    assert {marker["_id"] for marker in markers} == {
        "82453304:price_history_snapshots",
        "82453304:stockout_snapshots",
    }
    assert {marker["read_model"] for marker in markers} == {
        "price_history_snapshots",
        "stockout_snapshots",
    }
    assert all(marker["date_from"] == request.date_range.start for marker in markers)
    assert all(marker["fresh_until"] == request.date_range.end_exclusive for marker in markers)


@pytest.mark.asyncio
async def test_bounded_write_does_not_mutate_existing_wider_price_stockout_markers() -> None:
    existing_date_from = datetime(2026, 5, 1, tzinfo=UTC)
    existing_fresh_until = datetime(2026, 6, 30, tzinfo=UTC)
    existing_collection = FakeAsyncCollection(
        [
            _seller_doc(
                _id="82453304:price_history_snapshots",
                read_model="price_history_snapshots",
                state="reconciled",
                date_from=existing_date_from,
                fresh_until=existing_fresh_until,
                reconciled_until=existing_fresh_until,
                last_event_synced_at=existing_date_from,
                updated_at=_dt(1),
                source="zelerdata_read_model_reconcile",
                schema_version=1,
            ),
            _seller_doc(
                _id="82453304:stockout_snapshots",
                read_model="stockout_snapshots",
                state="reconciled",
                date_from=existing_date_from,
                fresh_until=existing_fresh_until,
                reconciled_until=existing_fresh_until,
                last_event_synced_at=existing_date_from,
                updated_at=_dt(1),
                source="zelerdata_read_model_reconcile",
                schema_version=1,
            ),
        ]
    )
    db = FakeAsyncDb({"sheets_read_model_freshness": existing_collection})
    request = _write_request(extra_args=["--max-items", "1"])
    summary = _complete_price_stockout_summary(request)

    counts = await write_complete_read_model_freshness_markers(
        db=db, request=request, summary=summary
    )

    assert counts == {}
    assert existing_collection.updates == []
    for marker in existing_collection.documents:
        assert marker["date_from"] == existing_date_from
        assert marker["fresh_until"] == existing_fresh_until
        assert marker["reconciled_until"] == existing_fresh_until


@pytest.mark.asyncio
async def test_multi_entry_price_doc_missing_any_basis_is_incomplete() -> None:
    db = FakeAsyncDb(
        {
            "sheets_price_history_snapshots": [
                _seller_doc(
                    _id="82453304:MLA1",
                    item_id="MLA1",
                    prices=[
                        {
                            "price": 149.99,
                            "status": "active",
                            "observed_at": _dt(4),
                            "observation_basis": "current_observed",
                        },
                        {
                            "price": 129.99,
                            "status": "paused",
                            "observed_at": _dt(3),
                        },
                    ],
                    snapshot_at=_dt(4),
                    source="sheets_backfill",
                    observation_basis="current_observed",
                    schema_version=1,
                )
            ],
        }
    )
    request = _write_request()
    summary = await collect_reconciliation_counts(
        db=db,
        request=request,
        expected=ExpectedReadModelCounts(
            counts={"price_history_snapshots": 1},
            truth_mode={"price_history_snapshots": "observed_current"},
            refs={"price_history_snapshots": frozenset({"MLA1"})},
        ),
        read_models=("price_history_snapshots",),
    )
    counts = await write_complete_read_model_freshness_markers(
        db=db, request=request, summary=summary
    )

    aggregate = summary.aggregates[0]
    assert aggregate.persisted_count == 1
    assert aggregate.complete_count == 0
    assert counts == {}
    assert db["sheets_read_model_freshness"].documents == []


@pytest.mark.asyncio
async def test_legacy_invalid_price_doc_is_incomplete_and_cannot_write_marker() -> None:
    db = FakeAsyncDb(
        {
            "sheets_price_history_snapshots": [
                _seller_doc(
                    _id="82453304:MLA1",
                    item_id="MLA1",
                    prices=[
                        {
                            "price": "149.99",
                            "status": "active",
                            "observed_at": "2026-06-04T00:00:00Z",
                            "observation_basis": "legacy_scrape",
                        }
                    ],
                    snapshot_at="2026-06-04T00:00:00Z",
                    source="legacy_sheetseller",
                    observation_basis="legacy_scrape",
                    schema_version=1,
                )
            ],
        }
    )
    request = _write_request()

    summary = await collect_reconciliation_counts(
        db=db,
        request=request,
        expected=ExpectedReadModelCounts(
            counts={"price_history_snapshots": 1},
            truth_mode={"price_history_snapshots": "observed_current"},
            refs={"price_history_snapshots": frozenset({"MLA1"})},
        ),
        read_models=("price_history_snapshots",),
    )
    counts = await write_complete_read_model_freshness_markers(
        db=db, request=request, summary=summary
    )

    aggregate = summary.aggregates[0]
    assert aggregate.persisted_count == 1
    assert aggregate.complete_count == 0
    assert counts == {}
    assert db["sheets_read_model_freshness"].documents == []


@pytest.mark.asyncio
async def test_legacy_invalid_stockout_doc_is_incomplete_and_cannot_write_marker() -> None:
    db = FakeAsyncDb(
        {
            "sheets_stockout_snapshots": [
                _seller_doc(
                    _id="82453304:MLA1",
                    item_id="MLA1",
                    observed_at="2026-06-04T00:00:00Z",
                    source="legacy_sheetseller",
                    observation_basis="legacy_scrape",
                    status="active",
                    stock_state="out_of_stock",
                    current_stock=0,
                    out_of_stock_since="2026-06-04T00:00:00Z",
                    schema_version=1,
                )
            ],
        }
    )
    request = _write_request()

    summary = await collect_reconciliation_counts(
        db=db,
        request=request,
        expected=ExpectedReadModelCounts(
            counts={"stockout_snapshots": 1},
            truth_mode={"stockout_snapshots": "observed_current"},
            refs={"stockout_snapshots": frozenset({"MLA1"})},
        ),
        read_models=("stockout_snapshots",),
    )
    counts = await write_complete_read_model_freshness_markers(
        db=db, request=request, summary=summary
    )

    aggregate = summary.aggregates[0]
    assert aggregate.persisted_count == 1
    assert aggregate.complete_count == 0
    assert counts == {}
    assert db["sheets_read_model_freshness"].documents == []


@pytest.mark.asyncio
async def test_inconsistent_stockout_rows_are_incomplete_and_cannot_write_marker() -> None:
    db = FakeAsyncDb(
        {
            "sheets_stockout_snapshots": [
                _seller_doc(
                    _id="82453304:MLA1",
                    item_id="MLA1",
                    observed_at=_dt(4),
                    source="sheets_backfill",
                    observation_basis="current_observed",
                    status="active",
                    stock_state="out_of_stock",
                    current_stock=3,
                    out_of_stock_since=_dt(4),
                    schema_version=1,
                ),
                _seller_doc(
                    _id="82453304:MLA2",
                    item_id="MLA2",
                    observed_at=_dt(4),
                    source="sheets_backfill",
                    observation_basis="current_observed",
                    status="active",
                    stock_state="in_stock",
                    current_stock=0,
                    out_of_stock_since=None,
                    schema_version=1,
                ),
            ],
        }
    )
    request = _write_request()

    summary = await collect_reconciliation_counts(
        db=db,
        request=request,
        expected=ExpectedReadModelCounts(
            counts={"stockout_snapshots": 2},
            truth_mode={"stockout_snapshots": "observed_current"},
            refs={"stockout_snapshots": frozenset({"MLA1", "MLA2"})},
        ),
        read_models=("stockout_snapshots",),
    )
    counts = await write_complete_read_model_freshness_markers(
        db=db, request=request, summary=summary
    )

    aggregate = summary.aggregates[0]
    assert aggregate.persisted_count == 2
    assert aggregate.complete_count == 0
    assert counts == {}
    assert db["sheets_read_model_freshness"].documents == []


@pytest.mark.asyncio
async def test_valid_stockout_rows_count_complete_and_can_write_marker() -> None:
    db = FakeAsyncDb(
        {
            "sheets_stockout_snapshots": [
                _seller_doc(
                    _id="82453304:MLA1",
                    item_id="MLA1",
                    observed_at=_dt(4),
                    source="sheets_backfill",
                    observation_basis="current_observed",
                    status="active",
                    stock_state="out_of_stock",
                    current_stock=0,
                    out_of_stock_since=_dt(4),
                    schema_version=1,
                ),
                _seller_doc(
                    _id="82453304:MLA2",
                    item_id="MLA2",
                    observed_at=_dt(4),
                    source="sheets_backfill",
                    observation_basis="current_observed",
                    status="active",
                    stock_state="in_stock",
                    current_stock=5,
                    out_of_stock_since=None,
                    schema_version=1,
                ),
            ],
        }
    )
    request = _write_request()

    summary = await collect_reconciliation_counts(
        db=db,
        request=request,
        expected=ExpectedReadModelCounts(
            counts={"stockout_snapshots": 2},
            truth_mode={"stockout_snapshots": "observed_current"},
            refs={"stockout_snapshots": frozenset({"MLA1", "MLA2"})},
        ),
        read_models=("stockout_snapshots",),
    )
    counts = await write_complete_read_model_freshness_markers(
        db=db, request=request, summary=summary
    )

    aggregate = summary.aggregates[0]
    marker = db["sheets_read_model_freshness"].documents[0]
    assert aggregate.persisted_count == 2
    assert aggregate.complete_count == 2
    assert counts == {"freshness_markers_written": 1}
    assert marker["read_model"] == "stockout_snapshots"


@pytest.mark.asyncio
async def test_questions_answer_detail_gaps_keep_coverage_partial_and_marker_unwritten() -> None:
    db = FakeAsyncDb(
        {
            "questions": [
                _seller_doc(
                    _id="QUESTION-PII-ANSWERED-COMPLETE",
                    date_created=_dt(2),
                    status="ANSWERED",
                    item_id="ITEM-PII-1",
                    text="Still available?",
                    from_user_id="BUYER-PII-1",
                    answer={"text": "Yes", "date_created": _dt(2)},
                ),
                _seller_doc(
                    _id="QUESTION-PII-ANSWERED-INCOMPLETE",
                    date_created=_dt(3),
                    status="ANSWERED",
                    item_id="ITEM-PII-2",
                    text="Ships today?",
                    from_user_id="BUYER-PII-2",
                    answer={"date_created": _dt(3)},
                ),
            ]
        }
    )
    request = _write_request()

    summary = await collect_reconciliation_counts(
        db=db,
        request=request,
        expected=ExpectedReadModelCounts(counts={"questions": 2}),
        read_models=("questions",),
    )
    counts = await write_complete_read_model_freshness_markers(
        db=db, request=request, summary=summary
    )

    aggregate = summary.to_sanitized_dict()["aggregates"][0]
    assert aggregate["persisted_count"] == 2
    assert aggregate["complete_count"] == 1
    assert aggregate["missing_count"] == 0
    assert counts == {}
    assert db["sheets_read_model_freshness"].documents == []


@pytest.mark.asyncio
async def test_devoluciones_nine_claim_regression_proves_9_9_9_0_coverage() -> None:
    db = FakeAsyncDb(
        {
            "claims": [
                _seller_doc(
                    _id=f"CLAIM-{index}",
                    date_created=_dt(index),
                    order_id=f"ORDER-{index}",
                    item_id=f"MLA{index}",
                    status="closed",
                    type="returns",
                    productive=True,
                    returned_quantity=1,
                    return_quantity_basis="v2_return_order",
                )
                for index in range(1, 10)
            ]
        }
    )
    request = _write_request(extra_args=["--date-to", "2026-06-10"])

    summary = await collect_reconciliation_counts(
        db=db,
        request=request,
        expected=ExpectedReadModelCounts(
            counts={"claims": 9},
            refs={"claims": frozenset(f"CLAIM-{index}" for index in range(1, 10))},
        ),
        read_models=("claims",),
    )
    aggregate = summary.aggregates[0]
    assert (
        aggregate.expected_count,
        aggregate.persisted_count,
        aggregate.complete_count,
        aggregate.missing_count,
    ) == (9, 9, 9, 0)


@pytest.mark.asyncio
async def test_devoluciones_claim_aggregate_excludes_unrelated_claim_types() -> None:
    db = FakeAsyncDb(
        {
            "claims": [
                _seller_doc(
                    _id="RETURN-1",
                    date_created=_dt(2),
                    order_id="ORDER-1",
                    item_id="MLA1",
                    status="closed",
                    type="returns",
                    productive=True,
                    returned_quantity=1,
                    return_quantity_basis="v2_return_order",
                ),
                _seller_doc(
                    _id="CANCEL-1",
                    date_created=_dt(2),
                    order_id="ORDER-2",
                    item_id="MLA2",
                    status="closed",
                    type="cancel_purchase",
                    productive=False,
                ),
            ]
        }
    )
    request = _write_request()

    summary = await collect_reconciliation_counts(
        db=db,
        request=request,
        expected=ExpectedReadModelCounts(
            counts={"claims": 1}, refs={"claims": frozenset({"RETURN-1"})}
        ),
        read_models=("claims",),
    )

    aggregate = summary.aggregates[0]
    assert aggregate.persisted_count == 1
    assert aggregate.complete_count == 1
    assert aggregate.missing_count == 0


@pytest.mark.asyncio
async def test_questions_expected_counts_come_from_historical_question_coverage() -> None:
    async def fake_historical_source(*, db: Any, request: Any) -> FakeHistoricalMeliSummary:
        return FakeHistoricalMeliSummary(
            orders_found=0,
            order_ids=[],
            shipment_ids=[],
            item_ids=[],
            questions_found=2,
            question_ids=["QUESTION-PII-1", "QUESTION-PII-2"],
        )

    expected = await collect_expected_read_model_counts(
        db=FakeAsyncDb({}),
        request=_request(),
        historical_meli_source=fake_historical_source,
    )

    assert expected.counts["questions"] == 2
    assert expected.refs["questions"] == frozenset({"QUESTION-PII-1", "QUESTION-PII-2"})
    assert expected.truth_mode["questions"] == "expected"


@pytest.mark.asyncio
async def test_missing_question_detail_blocks_reconciled_marker_with_sanitized_issue() -> None:
    class QuestionGapGateway:
        async def fetch_resource(self, *, seller_id: str, path: str) -> Any:
            if path.startswith("/orders/search?"):
                return {"results": [], "paging": {"total": 0, "limit": 50, "offset": 0}}
            if path.startswith("/questions/search?"):
                return {
                    "questions": [
                        {"id": "Q1", "date_created": "2026-06-02T10:00:00Z"},
                        {"id": "Q2", "date_created": "2026-06-02T10:01:00Z"},
                    ],
                    "paging": {"total": 2, "limit": 50, "offset": 0},
                }
            if path == "/questions/Q1":
                return {
                    "id": "Q1",
                    "date_created": "2026-06-02T10:00:00Z",
                    "status": "ANSWERED",
                    "item_id": "ITEM-PII-1",
                    "text": "RAW QUESTION BODY MUST NOT LEAK",
                    "from": {"id": "BUYER-PII-1"},
                    "answer": {"text": "RAW ANSWER MUST NOT LEAK"},
                }
            if path == "/questions/Q2":
                return {"message": "detail missing without question id"}
            raise AssertionError(f"Unexpected gateway path: {path}")

    async def historical_source(*, db: Any, request: Any) -> Any:
        from zeler_sheets.historical_meli_backfill import run_historical_meli_backfill

        gateway = QuestionGapGateway()
        return await run_historical_meli_backfill(
            db=db,
            gateway=gateway,
            order_detail_gateway=gateway,
            seller_id=request.seller_id,
            date_from=request.date_range.date_from,
            date_to=request.date_range.date_to,
            dry_run=True,
            approved_runtime=request.approved_runtime,
            include_questions=True,
        )

    db = FakeAsyncDb(
        {
            "questions": [
                _seller_doc(
                    _id="Q1",
                    date_created=_dt(2),
                    status="ANSWERED",
                    item_id="ITEM-PII-1",
                    text="Persisted body must not leak",
                    from_user_id="BUYER-PII-1",
                )
            ]
        }
    )
    request = _write_request()

    expected = await collect_expected_read_model_counts(
        db=db,
        request=request,
        historical_meli_source=historical_source,
    )
    summary = await collect_reconciliation_counts(
        db=db,
        request=request,
        expected=expected,
        read_models=("questions",),
    )
    marker_counts = await write_complete_read_model_freshness_markers(
        db=db, request=request, summary=summary
    )

    output = summary.to_sanitized_dict()
    aggregate = output["aggregates"][0]
    serialized = json.dumps(output, sort_keys=True)

    assert expected.counts["questions"] == 2
    assert expected.refs["questions"] == frozenset({"Q1", "Q2"})
    assert aggregate["expected_count"] == 2
    assert aggregate["persisted_count"] == 1
    assert aggregate["missing_count"] == 1
    assert aggregate["issues"] == [{"code": "question_detail_missing", "count": 1}]
    assert marker_counts == {}
    assert db["sheets_read_model_freshness"].documents == []
    assert "RAW QUESTION BODY" not in serialized
    assert "RAW ANSWER" not in serialized
    assert "BUYER-PII" not in serialized


@pytest.mark.asyncio
async def test_claims_expected_counts_are_bounded_by_historical_order_scope() -> None:
    async def fake_historical_source(*, db: Any, request: Any) -> FakeHistoricalMeliSummary:
        return FakeHistoricalMeliSummary(
            orders_found=2,
            order_ids=["ORDER-PII-1", "ORDER-PII-2"],
            shipment_ids=[],
            item_ids=[],
            claims_found=2,
            claim_ids=["CLAIM-PII-1", "CLAIM-PII-2"],
        )

    expected = await collect_expected_read_model_counts(
        db=FakeAsyncDb({}),
        request=_request(),
        historical_meli_source=fake_historical_source,
    )

    assert expected.counts["claims"] == 2
    assert expected.refs["claims"] == frozenset({"CLAIM-PII-1", "CLAIM-PII-2"})
    assert expected.truth_mode["claims"] == "expected"


@pytest.mark.asyncio
async def test_catalog_expected_counts_come_from_scoped_items_with_catalog_product_id() -> None:
    async def fake_historical_source(*, db: Any, request: Any) -> FakeHistoricalMeliSummary:
        return FakeHistoricalMeliSummary(orders_found=0, order_ids=[], shipment_ids=[], item_ids=[])

    db = FakeAsyncDb(
        {
            "items": [
                _seller_doc(_id="ITEM-PII-1", catalog_product_id="CATALOG-PII-1"),
                _seller_doc(_id="ITEM-PII-2", catalog_product_id="CATALOG-PII-1"),
                _seller_doc(_id="ITEM-PII-3", catalog_product_id="CATALOG-PII-2"),
                _seller_doc(_id="ITEM-PII-NO-CATALOG", catalog_product_id=""),
                {"_id": "ITEM-OTHER", "seller_id": "other", "catalog_product_id": "CAT-OTHER"},
            ],
        }
    )

    expected = await collect_expected_read_model_counts(
        db=db, request=_request(), historical_meli_source=fake_historical_source
    )

    assert expected.counts["catalog_product_snapshots"] == 2
    assert expected.refs["catalog_product_snapshots"] == frozenset(
        {"CATALOG-PII-1", "CATALOG-PII-2"}
    )
    assert expected.counts["catalog_buybox_snapshots"] == 3
    assert expected.refs["catalog_buybox_snapshots"] == frozenset(
        {"ITEM-PII-1", "ITEM-PII-2", "ITEM-PII-3"}
    )
    assert expected.truth_mode["catalog_product_snapshots"] == "expected"
    assert expected.truth_mode["catalog_buybox_snapshots"] == "expected"


@pytest.mark.asyncio
async def test_catalog_product_optional_display_fields_do_not_block_marker_readiness() -> None:
    db = FakeAsyncDb(
        {
            "sheets_catalog_product_snapshots": [
                _seller_doc(
                    _id="PRODUCT-PII-1",
                    catalog_product_id="CATALOG-PII-1",
                    title="Catalog title",
                    attributes={"BRAND": "Acme"},
                    snapshot_at=_dt(2),
                    source="historical_meli_backfill",
                ),
                _seller_doc(
                    _id="PRODUCT-PII-2",
                    catalog_product_id="CATALOG-PII-2",
                    title="Catalog title two",
                    description=None,
                    image_url=None,
                    attributes={},
                    snapshot_at=_dt(2),
                    source="historical_meli_backfill",
                ),
            ],
        }
    )
    request = _write_request()

    summary = await collect_reconciliation_counts(
        db=db,
        request=request,
        expected=ExpectedReadModelCounts(
            counts={"catalog_product_snapshots": 2},
            refs={"catalog_product_snapshots": frozenset({"CATALOG-PII-1", "CATALOG-PII-2"})},
        ),
        read_models=("catalog_product_snapshots",),
    )
    counts = await write_complete_read_model_freshness_markers(
        db=db, request=request, summary=summary
    )

    aggregate = summary.to_sanitized_dict()["aggregates"][0]
    assert aggregate["persisted_count"] == 2
    assert aggregate["complete_count"] == 2
    assert aggregate["missing_count"] == 0
    assert counts == {"freshness_markers_written": 1}
    assert db["sheets_read_model_freshness"].documents[0]["read_model"] == (
        "catalog_product_snapshots"
    )


@pytest.mark.asyncio
async def test_catalog_buybox_optional_numeric_and_display_fields_do_not_block_readiness() -> None:
    db = FakeAsyncDb(
        {
            "sheets_catalog_buybox_snapshots": [
                _seller_doc(
                    _id="BUYBOX-PII-2",
                    item_id="ITEM-PII-2",
                    catalog_product_id="CATALOG-PII-2",
                    buybox_status="competing",
                    snapshot_at=_dt(2),
                    source="historical_meli_backfill",
                ),
                _seller_doc(
                    _id="BUYBOX-PII-3",
                    item_id="ITEM-PII-3",
                    catalog_product_id="CATALOG-PII-3",
                    title=None,
                    available_quantity=None,
                    buybox_status="not_winning",
                    price=None,
                    winning_price=None,
                    competitor_count=None,
                    only_competitor=None,
                    snapshot_at=_dt(3),
                    source="historical_meli_backfill",
                ),
            ],
        }
    )
    request = _write_request()

    summary = await collect_reconciliation_counts(
        db=db,
        request=request,
        expected=ExpectedReadModelCounts(
            counts={"catalog_buybox_snapshots": 2},
            refs={
                "catalog_buybox_snapshots": frozenset({"ITEM-PII-2", "ITEM-PII-3"}),
            },
        ),
        read_models=("catalog_buybox_snapshots",),
    )
    counts = await write_complete_read_model_freshness_markers(
        db=db, request=request, summary=summary
    )

    aggregate = summary.to_sanitized_dict()["aggregates"][0]
    assert aggregate["persisted_count"] == 2
    assert aggregate["complete_count"] == 2
    assert aggregate["missing_count"] == 0
    assert counts == {"freshness_markers_written": 1}
    assert db["sheets_read_model_freshness"].documents[0]["read_model"] == (
        "catalog_buybox_snapshots"
    )


@pytest.mark.asyncio
async def test_missing_catalog_required_snapshot_fields_keep_markers_unwritten() -> None:
    db = FakeAsyncDb(
        {
            "sheets_catalog_product_snapshots": [
                _seller_doc(
                    _id="PRODUCT-PII-1",
                    catalog_product_id="CATALOG-PII-1",
                    snapshot_at=_dt(2),
                    source="historical_meli_backfill",
                ),
                _seller_doc(
                    _id="PRODUCT-PII-2",
                    catalog_product_id="CATALOG-PII-2",
                    source="historical_meli_backfill",
                ),
            ],
            "sheets_catalog_buybox_snapshots": [
                _seller_doc(
                    _id="BUYBOX-PII-1",
                    item_id="ITEM-PII-1",
                    catalog_product_id="CATALOG-PII-1",
                    buybox_status="winning",
                    snapshot_at=_dt(2),
                    source="historical_meli_backfill",
                ),
                _seller_doc(
                    _id="BUYBOX-PII-2",
                    item_id="ITEM-PII-2",
                    catalog_product_id="CATALOG-PII-2",
                    snapshot_at=_dt(2),
                ),
            ],
        }
    )
    request = _write_request()

    summary = await collect_reconciliation_counts(
        db=db,
        request=request,
        expected=ExpectedReadModelCounts(
            counts={"catalog_product_snapshots": 2, "catalog_buybox_snapshots": 2},
            refs={
                "catalog_product_snapshots": frozenset({"CATALOG-PII-1", "CATALOG-PII-2"}),
                "catalog_buybox_snapshots": frozenset({"ITEM-PII-1", "ITEM-PII-2"}),
            },
        ),
        read_models=("catalog_product_snapshots", "catalog_buybox_snapshots"),
    )
    counts = await write_complete_read_model_freshness_markers(
        db=db, request=request, summary=summary
    )

    by_model = {
        aggregate["read_model"]: aggregate
        for aggregate in summary.to_sanitized_dict()["aggregates"]
    }
    assert by_model["catalog_product_snapshots"]["complete_count"] == 1
    assert by_model["catalog_buybox_snapshots"]["complete_count"] == 1
    assert by_model["catalog_product_snapshots"]["missing_count"] == 0
    assert by_model["catalog_buybox_snapshots"]["missing_count"] == 0
    assert counts == {}
    assert db["sheets_read_model_freshness"].documents == []


@pytest.mark.asyncio
async def test_complete_catalog_snapshot_coverage_writes_readiness_markers() -> None:
    db = FakeAsyncDb({})
    request = _write_request()
    summary = ReconciliationSummary(
        seller_id=request.seller_id,
        date_from=request.date_range.date_from,
        date_to=request.date_range.date_to,
        dry_run=False,
        approved_runtime=True,
        write_enabled=True,
        aggregates=(
            ReadModelAggregate(
                read_model="catalog_product_snapshots",
                expected_count=2,
                persisted_count=2,
                missing_count=0,
                complete_count=2,
            ),
            ReadModelAggregate(
                read_model="catalog_buybox_snapshots",
                expected_count=3,
                persisted_count=3,
                missing_count=0,
                complete_count=3,
            ),
        ),
    )

    counts = await write_complete_read_model_freshness_markers(
        db=db, request=request, summary=summary
    )

    assert counts == {"freshness_markers_written": 2}
    assert {marker["read_model"] for marker in db["sheets_read_model_freshness"].documents} == {
        "catalog_product_snapshots",
        "catalog_buybox_snapshots",
    }


@pytest.mark.asyncio
async def test_unknown_returned_quantity_is_incomplete_in_claim_aggregate() -> None:
    db = FakeAsyncDb(
        {
            "claims": [
                _seller_doc(
                    _id="CLAIM-PII-1",
                    date_created=_dt(2),
                    order_id="ORDER-PII-1",
                    item_id="MLA1",
                    status="closed",
                    productive=True,
                    returned_quantity=1,
                    return_quantity_basis="v2_return_order",
                ),
                _seller_doc(
                    _id="CLAIM-PII-2",
                    date_created=_dt(3),
                    order_id="ORDER-PII-2",
                    status="closed",
                ),
            ]
        }
    )
    request = _write_request()

    summary = await collect_reconciliation_counts(
        db=db,
        request=request,
        expected=ExpectedReadModelCounts(counts={"claims": 2}),
        read_models=("claims",),
    )
    aggregate = summary.to_sanitized_dict()["aggregates"][0]
    assert aggregate["persisted_count"] == 2
    assert aggregate["complete_count"] == 1
    assert aggregate["missing_count"] == 0


@pytest.mark.asyncio
async def test_missing_claim_item_id_prevents_complete_count() -> None:
    db = FakeAsyncDb(
        {
            "claims": [
                _seller_doc(
                    _id="CLAIM-PII-1",
                    date_created=_dt(2),
                    order_id="ORDER-PII-1",
                    item_id="MLA1",
                    status="closed",
                    productive=True,
                    returned_quantity=1,
                    return_quantity_basis="v2_return_order",
                ),
                _seller_doc(
                    _id="CLAIM-PII-2",
                    date_created=_dt(3),
                    order_id="ORDER-PII-2",
                    status="closed",
                    productive=True,
                    returned_quantity=1,
                    return_quantity_basis="v2_return_order",
                ),
            ]
        }
    )
    request = _write_request()

    summary = await collect_reconciliation_counts(
        db=db,
        request=request,
        expected=ExpectedReadModelCounts(counts={"claims": 2}),
        read_models=("claims",),
    )
    aggregate = summary.to_sanitized_dict()["aggregates"][0]
    assert aggregate["persisted_count"] == 2
    assert aggregate["complete_count"] == 1
    assert aggregate["missing_count"] == 0


@pytest.mark.asyncio
async def test_empty_claim_scope_fields_and_zero_quantity_are_incomplete() -> None:
    db = FakeAsyncDb(
        {
            "claims": [
                _seller_doc(
                    _id="CLAIM-COMPLETE",
                    date_created=_dt(2),
                    order_id="ORDER-PII-1",
                    item_id="MLA1",
                    status="closed",
                    productive=True,
                    returned_quantity=1,
                    return_quantity_basis="v2_return_order",
                ),
                _seller_doc(
                    _id="CLAIM-EMPTY-ITEM",
                    date_created=_dt(2),
                    order_id="ORDER-PII-2",
                    item_id="",
                    status="closed",
                    productive=True,
                    returned_quantity=1,
                    return_quantity_basis="v2_return_order",
                ),
                _seller_doc(
                    _id="CLAIM-EMPTY-ORDER-STATUS",
                    date_created=_dt(3),
                    order_id="",
                    item_id="MLA2",
                    status="",
                    productive=True,
                    returned_quantity=1,
                    return_quantity_basis="v2_return_order",
                ),
                _seller_doc(
                    _id="CLAIM-ZERO-QUANTITY",
                    date_created=_dt(4),
                    order_id="ORDER-PII-3",
                    item_id="MLA3",
                    status="closed",
                    productive=True,
                    returned_quantity=0,
                    return_quantity_basis="v2_return_order",
                ),
            ]
        }
    )
    request = _write_request()

    summary = await collect_reconciliation_counts(
        db=db,
        request=request,
        expected=ExpectedReadModelCounts(counts={"claims": 4}),
        read_models=("claims",),
    )
    aggregate = summary.to_sanitized_dict()["aggregates"][0]
    assert aggregate["persisted_count"] == 4
    assert aggregate["complete_count"] == 1
    assert aggregate["missing_count"] == 0


def test_reconciled_marker_requires_reconciled_state_and_enclosing_range() -> None:
    stale_reconciled = {
        "state": "reconciled",
        "last_event_synced_at": datetime(2026, 6, 1, tzinfo=UTC),
        "reconciled_until": datetime(2026, 6, 3, 23, 59, 59, tzinfo=UTC),
    }
    event_fresh_only = {
        "state": "fresh",
        "last_event_synced_at": datetime(2026, 6, 1, tzinfo=UTC),
        "fresh_until": datetime(2026, 6, 5, tzinfo=UTC),
    }
    late_start_reconciled = {
        "state": "reconciled",
        "last_event_synced_at": datetime(2026, 6, 3, tzinfo=UTC),
        "fresh_until": datetime(2026, 6, 5, tzinfo=UTC),
        "reconciled_until": datetime(2026, 6, 5, tzinfo=UTC),
    }
    complete_reconciled = {
        "state": "reconciled",
        "last_event_synced_at": datetime(2026, 6, 1, tzinfo=UTC),
        "fresh_until": datetime(2026, 6, 5, tzinfo=UTC),
        "reconciled_until": datetime(2026, 6, 5, tzinfo=UTC),
    }

    assert (
        read_model_reconciliation_marker_covers(
            stale_reconciled,
            date_from=datetime(2026, 6, 1, tzinfo=UTC),
            date_to=datetime(2026, 6, 4, 23, 59, 59, tzinfo=UTC),
        )
        is False
    )
    assert (
        read_model_reconciliation_marker_covers(
            event_fresh_only,
            date_from=datetime(2026, 6, 1, tzinfo=UTC),
            date_to=datetime(2026, 6, 4, 23, 59, 59, tzinfo=UTC),
        )
        is False
    )
    assert (
        read_model_reconciliation_marker_covers(
            late_start_reconciled,
            date_from=datetime(2026, 6, 1, tzinfo=UTC),
            date_to=datetime(2026, 6, 4, 23, 59, 59, tzinfo=UTC),
        )
        is False
    )
    assert (
        read_model_reconciliation_marker_covers(
            late_start_reconciled,
            date_from=datetime(2026, 6, 3, tzinfo=UTC),
            date_to=datetime(2026, 6, 4, 23, 59, 59, tzinfo=UTC),
        )
        is True
    )
    assert (
        read_model_reconciliation_marker_covers(
            complete_reconciled,
            date_from=datetime(2026, 6, 1, tzinfo=UTC),
            date_to=datetime(2026, 6, 4, 23, 59, 59, tzinfo=UTC),
        )
        is True
    )


def test_reconciled_marker_requires_coherent_authoritative_interval() -> None:
    inconsistent_reconciled = {
        "state": "reconciled",
        "date_from": datetime(2026, 6, 10, tzinfo=UTC),
        "reconciled_until": datetime(2026, 6, 5, tzinfo=UTC),
        "fresh_until": datetime(2026, 6, 20, tzinfo=UTC),
    }
    missing_reconciled_until = {
        "state": "reconciled",
        "date_from": datetime(2026, 6, 10, tzinfo=UTC),
        "fresh_until": datetime(2026, 6, 20, tzinfo=UTC),
    }
    complete_reconciled = {
        "state": "reconciled",
        "date_from": datetime(2026, 6, 10, tzinfo=UTC),
        "reconciled_until": datetime(2026, 6, 20, tzinfo=UTC),
        "fresh_until": datetime(2026, 6, 20, tzinfo=UTC),
    }

    assert (
        read_model_reconciliation_marker_covers(
            inconsistent_reconciled,
            date_from=datetime(2026, 6, 10, tzinfo=UTC),
            date_to=datetime(2026, 6, 15, tzinfo=UTC),
        )
        is False
    )
    assert (
        read_model_reconciliation_marker_covers(
            missing_reconciled_until,
            date_from=datetime(2026, 6, 10, tzinfo=UTC),
            date_to=datetime(2026, 6, 15, tzinfo=UTC),
        )
        is False
    )
    assert (
        read_model_reconciliation_marker_covers(
            complete_reconciled,
            date_from=datetime(2026, 6, 10, tzinfo=UTC),
            date_to=datetime(2026, 6, 15, tzinfo=UTC),
        )
        is True
    )


def test_reconciled_marker_exact_interval_rejects_enclosing_subranges() -> None:
    broad_reconciled = {
        "state": "reconciled",
        "date_from": datetime(2026, 6, 1, tzinfo=UTC),
        "fresh_until": datetime(2026, 7, 1, tzinfo=UTC),
        "reconciled_until": datetime(2026, 7, 1, tzinfo=UTC),
        "coverage_basis": "legacy_imported",
    }

    assert read_model_reconciliation_marker_covers(
        broad_reconciled,
        date_from=datetime(2026, 6, 1, tzinfo=UTC),
        date_to=datetime(2026, 7, 1, tzinfo=UTC),
        coverage_basis="legacy_imported",
        exact_interval=True,
    )
    assert not read_model_reconciliation_marker_covers(
        broad_reconciled,
        date_from=datetime(2026, 6, 1, tzinfo=UTC),
        date_to=datetime(2026, 6, 5, tzinfo=UTC),
        coverage_basis="legacy_imported",
        exact_interval=True,
    )
    assert read_model_reconciliation_marker_covers(
        broad_reconciled,
        date_from=datetime(2026, 6, 1, tzinfo=UTC),
        date_to=datetime(2026, 6, 5, tzinfo=UTC),
        coverage_basis="legacy_imported",
    )


def test_partial_marker_keeps_formula_read_model_data_unavailable() -> None:
    partial_marker = {
        "state": "partial",
        "reconciled_until": datetime(2026, 6, 5, tzinfo=UTC),
    }

    assert (
        read_model_reconciliation_marker_covers(
            partial_marker,
            date_from=datetime(2026, 6, 1, tzinfo=UTC),
            date_to=datetime(2026, 6, 4, tzinfo=UTC),
        )
        is False
    )


def test_write_failure_after_partial_rows_does_not_publish_freshness_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from infra.operations import zelerdata_read_model_reconcile

    db = FakeAsyncDb({})
    partial_rows: list[str] = []

    async def fake_expected(*, db: Any, request: Any) -> ExpectedReadModelCounts:
        return ExpectedReadModelCounts(counts={"questions": 1})

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
            aggregates=(
                ReadModelAggregate(
                    read_model="questions",
                    expected_count=1,
                    persisted_count=1,
                    missing_count=0,
                    complete_count=1,
                ),
            ),
            controls=request.controls,
        )

    async def failing_write(*, db: Any, request: Any, operation: Any) -> dict[str, int]:
        del operation
        partial_rows.append("questions")
        raise ValueError("query_anomaly")

    monkeypatch.setattr(zelerdata_read_model_reconcile, "create_runtime_db", lambda: db)
    monkeypatch.setattr(
        zelerdata_read_model_reconcile,
        "collect_expected_read_model_counts",
        fake_expected,
    )
    monkeypatch.setattr(zelerdata_read_model_reconcile, COLLECTOR_ATTR, fake_collect)
    monkeypatch.setattr(
        zelerdata_read_model_reconcile, "execute_reconciliation_write", failing_write
    )

    with pytest.raises(SystemExit, match="query_anomaly"):
        zelerdata_read_model_reconcile.main(
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
            ]
        )

    assert partial_rows == ["questions"]
    assert db["sheets_read_model_freshness"].documents == []


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
@pytest.mark.parametrize(
    ("error", "expected_code"),
    (
        (ClaimProjectionError("SENTINEL raw projection"), "claim_projection_error"),
        (ClaimInventoryError("SENTINEL fingerprint drift"), "claim_inventory_unstable"),
    ),
)
async def test_expected_source_preserves_sanitized_claim_failure_category(
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

    assert any(
        issue.read_model == "claims" and issue.code == expected_code for issue in expected.issues
    )
    assert "SENTINEL" not in json.dumps(issue_output, sort_keys=True)


def _authoritative_claims_expected() -> ExpectedReadModelCounts:
    return ExpectedReadModelCounts(
        counts={"claims": 1},
        refs={"claims": frozenset({"claim-1"})},
        truth_mode={"claims": "expected"},
        source_fingerprint="source-proof",
        read_model_fingerprint="read-model-proof",
    )


@pytest.mark.parametrize(
    ("expected", "issue_code"),
    (
        (
            ExpectedReadModelCounts(
                counts={},
                refs={"claims": frozenset({"claim-1"})},
                truth_mode={"claims": "expected"},
                source_fingerprint="source-proof",
                read_model_fingerprint="read-model-proof",
            ),
            "expected_count_unavailable",
        ),
        (
            ExpectedReadModelCounts(
                counts={"claims": 1},
                truth_mode={"claims": "expected"},
                source_fingerprint="source-proof",
                read_model_fingerprint="read-model-proof",
            ),
            "expected_refs_unavailable",
        ),
        (
            ExpectedReadModelCounts(
                counts={"claims": 1},
                refs={"claims": frozenset({"claim-1"})},
                truth_mode={"claims": "expected"},
                read_model_fingerprint="read-model-proof",
            ),
            "source_fingerprint_unavailable",
        ),
        (
            ExpectedReadModelCounts(
                counts={"claims": 1},
                refs={"claims": frozenset({"claim-1"})},
                truth_mode={"claims": "expected"},
                source_fingerprint="source-proof",
            ),
            "read_model_fingerprint_unavailable",
        ),
        (
            ExpectedReadModelCounts(
                counts={"claims": 1},
                refs={"claims": frozenset({"claim-1"})},
                truth_mode={"claims": "expected"},
                source_fingerprint="source-proof",
                read_model_fingerprint="read-model-proof",
                issues=(
                    ReadModelIssue(
                        read_model="claims",
                        code="claim_projection_error",
                        message="SENTINEL raw projection failure",
                    ),
                ),
            ),
            "claim_projection_error",
        ),
        (
            ExpectedReadModelCounts(
                counts={"claims": 2},
                refs={"claims": frozenset({"claim-1"})},
                truth_mode={"claims": "expected"},
                source_fingerprint="source-proof",
                read_model_fingerprint="read-model-proof",
            ),
            "expected_refs_count_mismatch",
        ),
        (
            ExpectedReadModelCounts(
                counts={"claims": 1},
                refs={"claims": frozenset({"claim-1"})},
                truth_mode={"claims": "unavailable"},
                source_fingerprint="source-proof",
                read_model_fingerprint="read-model-proof",
                issues=(
                    ReadModelIssue(
                        read_model="claims",
                        code="claim_inventory_unstable",
                        message="SENTINEL raw inventory drift",
                    ),
                ),
            ),
            "claim_inventory_unstable",
        ),
    ),
)
def test_mandatory_claims_source_gate_rejects_every_incomplete_proof(
    expected: ExpectedReadModelCounts,
    issue_code: str,
) -> None:
    gate = reconcile_operation_module._claims_authoritative_source_gate(expected)

    assert gate.authoritative is False
    assert issue_code in gate.issue_codes
    assert "SENTINEL" not in json.dumps(gate.to_sanitized_dict(), sort_keys=True)


def test_mandatory_claims_source_gate_accepts_complete_authoritative_proof() -> None:
    gate = reconcile_operation_module._claims_authoritative_source_gate(
        _authoritative_claims_expected()
    )

    assert gate.to_sanitized_dict() == {
        "read_model": "claims",
        "authoritative": True,
        "issue_codes": [],
    }


def test_focused_devoluciones_request_is_explicit_and_caps_concurrency() -> None:
    args = build_arg_parser().parse_args(
        [
            "--seller-id",
            "82453304",
            "--date-from",
            "2026-06-01",
            "--date-to",
            "2026-07-09",
            "--read-model",
            "devoluciones",
            "--concurrency",
            "4",
            "--confirm-approved-runtime",
        ]
    )

    request = build_reconciliation_request(args)

    assert request.read_model == "devoluciones"
    assert request.controls.concurrency == 4

    args.concurrency = 5
    with pytest.raises(SystemExit, match="concurrency"):
        build_reconciliation_request(args)


def test_twenty_run_nearest_rank_p95_campaign_accepts_only_strict_budgets() -> None:
    samples = tuple(
        ScheduledRunSample(
            duration_seconds=float(duration),
            succeeded=True,
            source_fingerprint="source-a",
            read_model_fingerprint="read-a",
        )
        for duration in [100] * 18 + [149, 179]
    )

    result = evaluate_timing_campaign(samples)

    assert result.accepted is True
    assert result.consecutive_runs == 20
    assert result.p95_seconds == 149.0
    assert result.hard_limit_seconds == 180.0
    assert result.p95_limit_seconds == 150.0


def test_timing_campaign_uses_complete_range_hard_source_attempt_cap() -> None:
    at_cap = tuple(
        ScheduledRunSample(
            100.0,
            True,
            "source-a",
            "read-a",
            campaign_id="campaign-a",
            physical_attempts=208,
        )
        for _ in range(20)
    )
    over_cap = replace(at_cap[0], physical_attempts=209)

    accepted = evaluate_timing_campaign(at_cap)
    rejected = evaluate_timing_campaign((over_cap, *at_cap))

    assert accepted.accepted is True
    assert rejected.accepted is False
    assert rejected.reason == "source_budget_exceeded"


def test_scheduled_evidence_accepts_complete_range_attempts_but_rejects_hard_cap_plus_one() -> None:
    def raw_output(attempts: int) -> str:
        return json.dumps(
            {
                "stage": "acceptance",
                "status_class": "success",
                "counters": {
                    "expected": 9,
                    "persisted": 9,
                    "complete": 9,
                    "missing": 0,
                    "P": 2,
                    "R": attempts - 11,
                    "O": 9,
                    "T": attempts,
                },
            }
        )

    accepted, accepted_status = build_scheduled_evidence(
        raw_output=raw_output(79),
        campaign_id="campaign-a",
        process_status=0,
        wrapper_duration_seconds=100.0,
    )
    rejected, rejected_status = build_scheduled_evidence(
        raw_output=raw_output(209),
        campaign_id="campaign-a",
        process_status=0,
        wrapper_duration_seconds=100.0,
    )

    assert accepted_status == 0
    assert accepted == {
        "stage": "scheduled",
        "status_class": "success",
        "counters": {
            "expected": 9,
            "persisted": 9,
            "complete": 9,
            "missing": 0,
            "P": 2,
            "R": 68,
            "O": 9,
            "T": 79,
        },
    }
    assert rejected_status == 65
    assert rejected == {
        "stage": "scheduled",
        "status_class": "source_budget_exceeded",
        "counters": {},
    }


@pytest.mark.parametrize(
    ("run_total", "first_snapshot", "second_snapshot", "expected_exit"),
    [(158, 79, 79, 0), (208, 104, 104, 0), (209, 104, 104, 65)],
    ids=("measured-two-snapshot-run", "inclusive-run-cap", "run-cap-plus-one"),
)
def test_scheduled_evidence_enforces_independent_snapshot_and_inclusive_run_caps(
    run_total: int,
    first_snapshot: int,
    second_snapshot: int,
    expected_exit: int,
) -> None:
    raw_output = json.dumps(
        {
            "stage": "write_readback",
            "status_class": "success",
            "counters": {
                "expected": 9,
                "persisted": 9,
                "complete": 9,
                "missing": 0,
                "P": 4,
                "R": run_total - 22,
                "O": 18,
                "T": run_total,
                "snapshot_1_T": first_snapshot,
                "snapshot_2_T": second_snapshot,
            },
        }
    )

    evidence, exit_code = build_scheduled_evidence(
        raw_output=raw_output,
        campaign_id="campaign-a",
        process_status=0,
        wrapper_duration_seconds=100.0,
    )

    assert exit_code == expected_exit
    assert evidence["stage"] == "scheduled"
    assert evidence["status_class"] == (
        "success" if expected_exit == 0 else "source_budget_exceeded"
    )


def test_focused_shared_evidence_exposes_exact_r4_allowlist() -> None:
    summary = ReconciliationSummary(
        seller_id="82453304",
        date_from="2026-06-01",
        date_to="2026-07-09",
        dry_run=True,
        approved_runtime=True,
        write_enabled=False,
        aggregates=(ReadModelAggregate("claims", 9, 9, 0, 9),),
        runtime_evidence=FocusedRuntimeEvidence(
            duration_seconds=100.0,
            source_calls={"P": 2, "R": 68, "O": 9, "T": 79, "raw_identifier": 82453304},
            succeeded=True,
            source_fingerprint="raw-source-proof",
            read_model_fingerprint="raw-read-proof",
            campaign_id="campaign-a",
        ),
    )

    evidence = summary.to_focused_evidence(stage="dry_run")

    assert evidence == {
        "stage": "dry_run",
        "status_class": "success",
        "counters": {
            "expected": 9,
            "persisted": 9,
            "complete": 9,
            "missing": 0,
            "P": 2,
            "R": 68,
            "O": 9,
            "T": 79,
        },
    }
    serialized = json.dumps(evidence, sort_keys=True)
    for forbidden in ("duration", "fingerprint", "campaign", "hash", "82453304"):
        assert forbidden not in serialized


@pytest.mark.parametrize(
    ("raw_output", "process_status", "expected_status_class", "expected_exit"),
    [
        ("", 0, "evidence_invalid", 65),
        ("not-json", 0, "evidence_invalid", 65),
        (
            json.dumps(
                {
                    "stage": "write_readback",
                    "status_class": "success",
                    "counters": {
                        "expected": 9,
                        "persisted": 9,
                        "complete": 9,
                        "missing": 0,
                        "P": 2,
                        "R": 68,
                        "O": 9,
                        "T": 78,
                    },
                }
            ),
            0,
            "counter_mismatch",
            65,
        ),
        (
            json.dumps(
                {
                    "stage": "write_readback",
                    "status_class": "internal_drift",
                    "counters": {"P": 2, "R": 68, "O": 9, "T": 79},
                }
            ),
            0,
            "internal_drift",
            65,
        ),
        (
            json.dumps(
                {
                    "stage": "write_readback",
                    "status_class": "success",
                    "counters": {"P": 2, "R": 94, "O": 9, "T": 105},
                }
            ),
            0,
            "source_budget_exceeded",
            65,
        ),
        ("", 1, "process_failed", 0),
    ],
    ids=("missing", "malformed", "counter-mismatch", "internal-drift", "snapshot-105", "process"),
)
def test_scheduled_evidence_threats_disqualify_with_exact_allowlist(
    raw_output: str,
    process_status: int,
    expected_status_class: str,
    expected_exit: int,
) -> None:
    evidence, exit_code = build_scheduled_evidence(
        raw_output=raw_output,
        campaign_id="campaign-a",
        process_status=process_status,
        wrapper_duration_seconds=100.0,
    )

    assert exit_code == expected_exit
    assert set(evidence) == {"stage", "status_class", "counters"}
    assert evidence["stage"] == "scheduled"
    assert evidence["status_class"] == expected_status_class
    assert isinstance(evidence["counters"], dict)
    serialized = json.dumps(evidence, sort_keys=True)
    for forbidden in ("duration", "fingerprint", "campaign", "hash"):
        assert forbidden not in serialized


@pytest.mark.parametrize(
    ("durations", "reason"),
    [
        ([100] * 18 + [150, 179], "p95_budget_exceeded"),
        ([100] * 19 + [180], "hard_budget_exceeded"),
    ],
)
def test_timing_campaign_rejects_equal_limits(durations: list[int], reason: str) -> None:
    result = evaluate_timing_campaign(
        tuple(
            ScheduledRunSample(
                duration_seconds=float(duration),
                succeeded=True,
                source_fingerprint="source-a",
                read_model_fingerprint="read-a",
            )
            for duration in durations
        )
    )

    assert result.accepted is False
    assert result.reason == reason


def test_failure_or_fingerprint_drift_resets_timing_campaign() -> None:
    stable = [
        ScheduledRunSample(100.0, True, "source-a", "read-a", campaign_id="campaign-a")
        for _ in range(20)
    ]
    failed = ScheduledRunSample(10.0, False, "source-a", "read-a", campaign_id="campaign-a")
    drifted = ScheduledRunSample(10.0, True, "source-b", "read-a", campaign_id="campaign-a")
    restarted = [replace(sample, campaign_id="campaign-b") for sample in stable]

    after_failure = evaluate_timing_campaign(tuple([*stable, failed, *stable[:19]]))
    after_drift = evaluate_timing_campaign(tuple([*stable, drifted, *stable[:19]]))
    recovered = evaluate_timing_campaign(tuple([failed, *restarted]))

    assert after_failure.accepted is False
    assert after_failure.consecutive_runs == 0
    assert after_failure.reason == "campaign_disqualified"
    assert after_drift.accepted is False
    assert after_drift.consecutive_runs == 0
    assert after_drift.reason == "campaign_disqualified"
    assert recovered.accepted is True


def test_hard_limit_disqualifies_campaign_until_explicit_new_campaign() -> None:
    hard_limit = ScheduledRunSample(
        180.0,
        True,
        "source-a",
        "read-a",
        campaign_id="campaign-a",
    )
    same_campaign = [
        ScheduledRunSample(100.0, True, "source-a", "read-a", campaign_id="campaign-a")
        for _ in range(20)
    ]
    new_campaign = [
        ScheduledRunSample(100.0, True, "source-a", "read-a", campaign_id="campaign-b")
        for _ in range(20)
    ]

    disqualified = evaluate_timing_campaign((hard_limit, *same_campaign))
    recovered = evaluate_timing_campaign((hard_limit, *new_campaign))

    assert disqualified.accepted is False
    assert disqualified.reason == "hard_budget_exceeded"
    assert recovered.accepted is True
    assert recovered.consecutive_runs == 20


def test_campaign_sample_is_derived_from_scheduled_write_runtime_evidence() -> None:
    summary = ReconciliationSummary(
        seller_id="82453304",
        date_from="2026-06-01",
        date_to="2026-07-09",
        dry_run=False,
        approved_runtime=True,
        write_enabled=True,
        write_counts={"devoluciones_markers_written": 1},
        runtime_evidence=FocusedRuntimeEvidence(
            duration_seconds=100.0,
            source_calls={"P": 4, "R": 8, "O": 4, "T": 16},
            succeeded=True,
            source_fingerprint="source-a",
            read_model_fingerprint="read-a",
            campaign_id="campaign-a",
        ),
    )

    sample = scheduled_sample_from_summary(summary)

    assert sample == ScheduledRunSample(
        100.0,
        True,
        "source-a",
        "read-a",
        campaign_id="campaign-a",
        physical_attempts=16,
        source_calls={"P": 4, "R": 8, "O": 4, "T": 16},
    )
    assert summary.to_sanitized_dict() == {
        "stage": "write_readback",
        "status_class": "success",
        "counters": {"P": 4, "R": 8, "O": 4, "T": 16},
    }
    assert summary.to_focused_evidence(stage="acceptance") == {
        "stage": "acceptance",
        "status_class": "success",
        "counters": {"P": 4, "R": 8, "O": 4, "T": 16},
    }
    assert sample.to_sanitized_dict() == {
        "stage": "scheduled",
        "status_class": "success",
        "counters": {"P": 4, "R": 8, "O": 4, "T": 16},
    }

    transport = summary.to_scheduled_transport()
    assert isinstance(transport, ScheduledTransportEnvelope)
    assert transport.public == {
        "stage": "write_readback",
        "status_class": "success",
        "counters": {"P": 4, "R": 8, "O": 4, "T": 16},
    }
    assert transport.private_campaign.campaign_id == "campaign-a"
    assert transport.private_campaign.duration_seconds == 100.0
    assert transport.private_campaign.source_fingerprint_hash != "source-a"
    assert transport.private_campaign.read_model_fingerprint_hash != "read-a"
    serialized_private = json.dumps(transport.to_private_dict(), sort_keys=True)
    assert "source-a" not in serialized_private
    assert "read-a" not in serialized_private
    assert "campaign-a" in serialized_private
    serialized_public = json.dumps(transport.public, sort_keys=True)
    for forbidden in ("duration", "fingerprint", "campaign", "hash"):
        assert forbidden not in serialized_public


def test_claim_completeness_accepts_only_exact_positive_v2_fact() -> None:
    filter_spec = reconcile_operation_module._complete_claims_filter(
        {"seller_id": "82453304", "_id": {"$in": ["claim-1", "claim-2"]}}
    )

    assert filter_spec["$or"] == [
        {
            "productive": True,
            "returned_quantity": {"$gte": 1},
            "return_quantity_basis": "v2_return_order",
        },
    ]
    assert "returned_quantity" not in {
        key: value for key, value in filter_spec.items() if key != "$or"
    }


class _OneClaimFocusedSource:
    async def search_claims(self, *, seller_id: str, params: dict[str, Any]) -> dict[str, Any]:
        del seller_id
        return {
            "data": [
                {
                    "id": "1",
                    "last_updated": "2026-06-01T12:01:00Z",
                    "date_created": "2026-06-01T12:00:00Z",
                    "type": "returns",
                    "status": "closed",
                }
            ],
            "paging": {"offset": params["offset"], "limit": params["limit"], "total": 1},
        }

    async def get_claim(self, *, seller_id: str, claim_id: str) -> dict[str, Any]:
        return {
            "id": claim_id,
            "claim_version": 1,
            "last_updated": "2026-06-01T12:01:00Z",
            "date_created": "2026-06-01T12:00:00Z",
            "order_id": "2",
            "item_id": "MLA1",
            "status": "closed",
            "stage": "claim",
            "type": "returns",
            "players": [
                {"user_id": seller_id, "role": "respondent", "type": "seller"},
                {"user_id": "buyer", "role": "complainant", "type": "buyer"},
            ],
        }

    async def get_returns(self, *, seller_id: str, claim_id: str) -> dict[str, Any]:
        del seller_id
        return {
            "id": f"return-{claim_id}",
            "status": "closed",
            "subtype": "return_partial",
            "last_updated": "2026-06-01T12:02:00Z",
            "orders": [{"order_id": "2", "item_id": "MLA1", "return_quantity": 1}],
        }

    async def get_order(self, *, seller_id: str, order_id: str) -> dict[str, Any]:
        return {
            "id": order_id,
            "seller": {"id": seller_id},
            "buyer": {"id": "buyer"},
            "status": "paid",
            "date_created": "2026-06-01T11:00:00Z",
            "items": [{"item": {"id": "MLA1"}, "quantity": 1}],
        }


class _FakeMonotonicClock:
    def __init__(self) -> None:
        self.current = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.current

    async def sleep(self, delay: float) -> None:
        self.sleeps.append(delay)
        self.current += delay


class _TimedOneClaimFocusedSource(_OneClaimFocusedSource):
    def __init__(self, clock: _FakeMonotonicClock) -> None:
        self.clock = clock
        self.return_starts: list[float] = []

    async def get_returns(self, *, seller_id: str, claim_id: str) -> dict[str, Any]:
        self.return_starts.append(self.clock.monotonic())
        return await super().get_returns(seller_id=seller_id, claim_id=claim_id)


class _RawGatewayReturnsError(Exception):
    def __init__(self, status_code: int, *, upstream_attempts: str | None = None) -> None:
        headers = (
            {"X-Zeler-Upstream-Attempts": upstream_attempts}
            if upstream_attempts is not None
            else {}
        )
        self.response = type("Response", (), {"status_code": status_code, "headers": headers})()
        super().__init__(
            "HTTP "
            f"{status_code} GET https://runtime.internal/post-purchase/v2/claims/"
            "519988002/returns?access_token=RAW_TOKEN&seller_id=82453304 "
            'payload={"claim_id":"519988002","order_id":"1999"}'
        )


class _FocusedGatewayClient:
    def __init__(
        self,
        *,
        returns_failure: Exception | None = None,
        returns_payload: dict[str, Any] | None = None,
        mediation_item_id: str | None = "MLA2",
    ) -> None:
        self.returns_failure = returns_failure
        self.returns_payload = returns_payload or {
            "id": "return-519988002",
            "status": "closed",
            "subtype": "return_partial",
            "last_updated": "2026-06-01T12:02:00Z",
            "orders": [{"order_id": "1999", "item_id": "MLA2", "return_quantity": 1}],
        }
        self.mediation_item_id = mediation_item_id
        self.paths: list[str] = []

    async def fetch_resource_once(self, *, seller_id: str, path: str) -> dict[str, Any]:
        self.paths.append(path)
        if path.startswith("/post-purchase/v1/claims/search?"):
            return {
                "data": [
                    {
                        "id": "519988002",
                        "last_updated": "2026-06-01T12:01:00Z",
                        "date_created": "2026-06-01T12:00:00Z",
                        "type": "mediations",
                        "status": "closed",
                    }
                ],
                "paging": {"offset": 0, "limit": 100, "total": 1},
            }
        if path == "/post-purchase/v1/claims/519988002":
            return {
                "id": "519988002",
                "claim_version": 1,
                "last_updated": "2026-06-01T12:01:00Z",
                "date_created": "2026-06-01T12:00:00Z",
                "order_id": "1999",
                "item_id": self.mediation_item_id,
                "status": "closed",
                "stage": "claim",
                "type": "mediations",
                "players": [
                    {"user_id": seller_id, "role": "respondent", "type": "seller"},
                    {"user_id": "buyer", "role": "complainant", "type": "buyer"},
                ],
                "related_entities": [],
            }
        if path == "/post-purchase/v2/claims/519988002/returns":
            if self.returns_failure is not None:
                raise self.returns_failure
            return dict(self.returns_payload)
        if path == "/orders/1999":
            return {
                "id": "1999",
                "seller": {"id": seller_id},
                "buyer": {"id": "buyer"},
                "status": "paid",
                "date_created": "2026-06-01T11:00:00Z",
                "items": [{"item": {"id": "MLA2"}, "quantity": 1}],
            }
        raise AssertionError(f"unexpected path: {path}")


def _install_focused_gateway(
    monkeypatch: pytest.MonkeyPatch,
    *,
    client: _FocusedGatewayClient,
) -> None:
    monkeypatch.setattr(reconcile_operation_module, "create_runtime_db", lambda: FakeAsyncDb({}))
    monkeypatch.setattr(
        reconcile_operation_module,
        "create_runtime_historical_meli_gateways",
        lambda: type("RuntimeGateways", (), {"order_detail_gateway": client})(),
    )


@pytest.mark.parametrize(
    "returns_failure",
    [
        _RawGatewayReturnsError(401),
        _RawGatewayReturnsError(403),
        _RawGatewayReturnsError(404),
        _RawGatewayReturnsError(429),
        _RawGatewayReturnsError(500),
        ConnectionError(
            "network GET https://runtime.internal/post-purchase/v2/claims/"
            "519988002/returns?access_token=RAW_TOKEN payload order_id=1999"
        ),
    ],
    ids=("401", "403", "404", "429", "500", "network"),
)
def test_focused_devoluciones_dry_run_sanitizes_gateway_returns_source_failures(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    returns_failure: Exception,
) -> None:
    client = _FocusedGatewayClient(returns_failure=returns_failure)
    _install_focused_gateway(
        monkeypatch,
        client=client,
    )

    result = reconcile_operation_module.main(
        [
            "--seller-id",
            "82453304",
            "--date-from",
            "2026-06-01",
            "--date-to",
            "2026-07-09",
            "--read-model",
            "devoluciones",
            "--dry-run",
            "--confirm-approved-runtime",
        ]
    )

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    combined_output = json.dumps(output, sort_keys=True) + captured.err

    assert result == 1
    assert output == {
        "stage": "dry_run",
        "status_class": "source_issue",
        "counters": {"P": 2, "R": 2, "O": 0, "T": 4},
    }
    for forbidden in (
        "Traceback",
        "https://runtime.internal",
        "/post-purchase/v2/claims",
        "access_token",
        "RAW_TOKEN",
        "82453304",
        "519988002",
        "1999",
        "payload",
    ):
        assert forbidden not in combined_output
    if getattr(getattr(returns_failure, "response", None), "status_code", None) == 429:
        assert client.paths.count("/post-purchase/v2/claims/519988002/returns") == 1


def test_focused_devoluciones_dry_run_accepts_authoritative_absent_return_as_exclusion(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = _FocusedGatewayClient(
        returns_failure=_RawGatewayReturnsError(404, upstream_attempts="1"),
        mediation_item_id=None,
    )
    _install_focused_gateway(monkeypatch, client=client)

    result = reconcile_operation_module.main(
        [
            "--seller-id",
            "82453304",
            "--date-from",
            "2026-06-01",
            "--date-to",
            "2026-07-09",
            "--read-model",
            "devoluciones",
            "--dry-run",
            "--confirm-approved-runtime",
        ]
    )

    output = json.loads(capsys.readouterr().out)

    assert result == 0
    assert output == {
        "stage": "dry_run",
        "status_class": "success",
        "counters": {
            "expected": 0,
            "persisted": 0,
            "complete": 0,
            "missing": 0,
            "P": 2,
            "R": 2,
            "O": 0,
            "T": 4,
        },
    }
    assert "/orders/1999" not in client.paths


def test_focused_devoluciones_dry_run_rejects_upstream_404_when_item_identity_exists(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_focused_gateway(
        monkeypatch,
        client=_FocusedGatewayClient(
            returns_failure=_RawGatewayReturnsError(404, upstream_attempts="1"),
        ),
    )

    result = reconcile_operation_module.main(
        [
            "--seller-id",
            "82453304",
            "--date-from",
            "2026-06-01",
            "--date-to",
            "2026-07-09",
            "--read-model",
            "devoluciones",
            "--dry-run",
            "--confirm-approved-runtime",
        ]
    )

    output = json.loads(capsys.readouterr().out)

    assert result == 1
    assert output == {
        "stage": "dry_run",
        "status_class": "source_issue",
        "counters": {"P": 2, "R": 2, "O": 0, "T": 4},
    }


def test_focused_devoluciones_dry_run_sanitizes_projection_failures(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_focused_gateway(
        monkeypatch,
        client=_FocusedGatewayClient(
            returns_payload={
                "id": "return-519988002",
                "status": "closed",
                "subtype": "return_partial",
                "last_updated": "2026-06-01T12:02:00Z",
                "orders": [],
            }
        ),
    )

    result = reconcile_operation_module.main(
        [
            "--seller-id",
            "82453304",
            "--date-from",
            "2026-06-01",
            "--date-to",
            "2026-07-09",
            "--read-model",
            "devoluciones",
            "--dry-run",
            "--confirm-approved-runtime",
        ]
    )

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    combined_output = json.dumps(output, sort_keys=True) + captured.err

    assert result == 1
    assert output == {
        "stage": "dry_run",
        "status_class": "query_anomaly",
        "counters": {"P": 2, "R": 2, "O": 1, "T": 5},
    }
    for forbidden in (
        "Traceback",
        "/post-purchase/v2/claims",
        "82453304",
        "519988002",
        "1999",
        "unique order/item",
    ):
        assert forbidden not in combined_output


@pytest.mark.parametrize("private_failure", tuple(devoluciones_module._FocusedDevolucionesFailure))
@pytest.mark.asyncio
async def test_focused_devoluciones_failure_enum_is_retained_only_in_private_evidence(
    monkeypatch: pytest.MonkeyPatch,
    private_failure: devoluciones_module._FocusedDevolucionesFailure,
) -> None:
    async def fail_snapshot(**_: Any) -> Any:
        raise ClaimInventoryError(
            "sanitized source failure",
            private_failure=private_failure,
        )

    monkeypatch.setattr(devoluciones_module, "collect_devoluciones_snapshot", fail_snapshot)
    request = build_reconciliation_request(
        build_arg_parser().parse_args(
            [
                "--seller-id",
                "82453304",
                "--date-from",
                "2026-06-01",
                "--date-to",
                "2026-07-09",
                "--read-model",
                "devoluciones",
                "--dry-run",
                "--confirm-approved-runtime",
            ]
        )
    )

    summary = await reconcile_operation_module.run_focused_devoluciones_reconciliation(
        db=FakeAsyncDb({}),
        request=request,
        source=object(),
    )

    public = summary.to_focused_evidence(stage="dry_run")
    private = summary.to_private_diagnostic_evidence()
    assert public == {
        "stage": "dry_run",
        "status_class": "source_issue",
        "counters": {"P": 0, "R": 0, "O": 0, "T": 0},
    }
    assert private == {"failure_class": private_failure.value}
    assert set(public) == {"stage", "status_class", "counters"}
    assert "failure_class" not in json.dumps(public, sort_keys=True)
    private_json = json.dumps(private, sort_keys=True)
    for forbidden in (
        "https://runtime.internal",
        "/post-purchase/v2/claims",
        "access_token",
        "RAW_TOKEN",
        "82453304",
        "519988002",
        "1999",
        "payload",
    ):
        assert forbidden not in private_json


def test_focused_diagnostic_writes_enum_to_separate_root_private_fd(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    writes: list[tuple[int, dict[str, str]]] = []
    _install_focused_gateway(
        monkeypatch,
        client=_FocusedGatewayClient(returns_failure=_RawGatewayReturnsError(404)),
    )
    monkeypatch.setattr(
        reconcile_operation_module,
        "_write_root_private_diagnostic_evidence",
        lambda fd, evidence: writes.append((fd, evidence)),
    )

    result = reconcile_operation_module.main(
        [
            "--seller-id",
            "82453304",
            "--date-from",
            "2026-06-01",
            "--date-to",
            "2026-07-09",
            "--read-model",
            "devoluciones",
            "--dry-run",
            "--confirm-approved-runtime",
            "--private-diagnostic-fd",
            "9",
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert json.loads(captured.out) == {
        "stage": "dry_run",
        "status_class": "source_issue",
        "counters": {"P": 2, "R": 2, "O": 0, "T": 4},
    }
    assert captured.err == ""
    assert writes == [(9, {"failure_class": "unsafe_404_failure"})]


@pytest.mark.parametrize(
    "evidence",
    (
        {"failure_class": "parser_failure"},
        {
            "failure_class": "parser_failure",
            "projection_reason": "projection_return_quantity",
        },
        {
            "failure_class": "source_failure",
            "source_stage": "claim_search",
            "source_family": "rate_limit",
        },
    ),
    ids=("legacy-parser-envelope", "extended-parser-envelope", "source-envelope"),
)
def test_private_diagnostic_fd_accepts_exact_legacy_and_extended_parser_envelopes(
    monkeypatch: pytest.MonkeyPatch,
    evidence: dict[str, str],
) -> None:
    writes: list[tuple[int, bytes]] = []
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        os,
        "fstat",
        lambda fd: type(
            "PrivateStat",
            (),
            {"st_uid": 0, "st_mode": stat.S_IFREG | 0o600},
        )(),
    )

    def write(fd: int, payload: bytes) -> int:
        writes.append((fd, payload))
        return len(payload)

    monkeypatch.setattr(os, "write", write)

    reconcile_operation_module._write_root_private_diagnostic_evidence(
        9,
        evidence,
    )

    assert writes == [
        (
            9,
            (json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii"),
        )
    ]


@pytest.mark.parametrize(
    "evidence",
    (
        {},
        {"failure_class": "parser_failure", "unexpected": "value"},
        {"failure_class": "unknown_failure"},
        {"failure_class": "parser_failure", "projection_reason": "projection_not_real"},
        {"failure_class": "source_failure", "projection_reason": "projection_return_quantity"},
        {
            "failure_class": "source_failure",
            "source_stage": "unknown_stage",
            "source_family": "rate_limit",
        },
        {
            "failure_class": "source_failure",
            "source_stage": "claim_search",
            "source_family": "unknown_family",
        },
        {
            "failure_class": "source_failure",
            "source_stage": "claim_search",
            "source_family": "rate_limit",
            "unexpected": "value",
        },
        {
            "failure_class": "source_failure",
            "source_stage": "cláim_search",
            "source_family": "rate_limit",
        },
        {"fáilure_class": "parser_failure"},
        {"failure_class": "parser_failure", "projection_reason": "razón"},
    ),
    ids=(
        "missing-key",
        "extra-key",
        "unknown-failure-class",
        "arbitrary-projection-reason",
        "reason-with-non-parser-class",
        "unknown-source-stage",
        "unknown-source-family",
        "source-extra-key",
        "source-non-ascii-stage",
        "non-ascii-key",
        "non-ascii-value",
    ),
)
def test_private_diagnostic_fd_rejects_invalid_envelopes(
    monkeypatch: pytest.MonkeyPatch,
    evidence: dict[str, str],
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        os,
        "fstat",
        lambda fd: type(
            "PrivateStat",
            (),
            {"st_uid": 0, "st_mode": stat.S_IFREG | 0o600},
        )(),
    )

    with pytest.raises(ValueError, match="private diagnostic evidence is invalid"):
        reconcile_operation_module._write_root_private_diagnostic_evidence(9, evidence)


def test_private_diagnostic_reason_is_private_and_preserves_public_focused_evidence() -> None:
    summary = ReconciliationSummary(
        seller_id="82453304",
        date_from="2026-06-01",
        date_to="2026-06-04",
        dry_run=True,
        approved_runtime=True,
        write_enabled=False,
        aggregates=(ReadModelAggregate("claims", None, None, None, None),),
        runtime_evidence=FocusedRuntimeEvidence(
            duration_seconds=0.0,
            source_calls={"P": 2, "R": 2, "O": 1, "T": 5},
            status_class="query_anomaly",
            private_failure=devoluciones_module._FocusedDevolucionesFailure.PARSER,
            projection_reason="projection_return_quantity",
        ),
    )

    assert summary.to_focused_evidence(stage="dry_run") == {
        "stage": "dry_run",
        "status_class": "query_anomaly",
        "counters": {"O": 1, "P": 2, "R": 2, "T": 5},
    }
    assert summary.to_private_diagnostic_evidence() == {
        "failure_class": "parser_failure",
        "projection_reason": "projection_return_quantity",
    }


@pytest.mark.parametrize(
    "projection_reason",
    [
        "projection_returns_orders_shape_absent",
        "projection_returns_orders_shape_null",
        "projection_returns_orders_shape_object",
        "projection_returns_orders_shape_scalar",
        "projection_returns_orders_shape_other",
    ],
)
def test_private_diagnostic_fd_allows_only_enum_derived_shape_reasons(
    projection_reason: str,
) -> None:
    assert reconcile_operation_module._is_allowed_projection_reason(projection_reason)
    assert ClaimProjectionReason(projection_reason).value == projection_reason


def test_shape_reason_stays_out_of_public_focused_evidence() -> None:
    summary = ReconciliationSummary(
        seller_id="82453304",
        date_from="2026-06-01",
        date_to="2026-06-04",
        dry_run=True,
        approved_runtime=True,
        write_enabled=False,
        runtime_evidence=FocusedRuntimeEvidence(
            duration_seconds=0.0,
            source_calls={"P": 2, "R": 2, "O": 1, "T": 5},
            status_class="query_anomaly",
            private_failure=devoluciones_module._FocusedDevolucionesFailure.PARSER,
            projection_reason="projection_returns_orders_shape_null",
        ),
    )

    assert summary.to_focused_evidence(stage="dry_run") == {
        "stage": "dry_run",
        "status_class": "query_anomaly",
        "counters": {"O": 1, "P": 2, "R": 2, "T": 5},
    }
    assert summary.to_private_diagnostic_evidence() == {
        "failure_class": "parser_failure",
        "projection_reason": "projection_returns_orders_shape_null",
    }


def test_source_failure_emits_bounded_stage_and_family_in_private_evidence() -> None:
    summary = ReconciliationSummary(
        seller_id="82453304",
        date_from="2026-06-01",
        date_to="2026-06-04",
        dry_run=True,
        approved_runtime=True,
        write_enabled=False,
        aggregates=(ReadModelAggregate("claims", None, None, None, None),),
        runtime_evidence=FocusedRuntimeEvidence(
            duration_seconds=0.0,
            source_calls={"P": 2, "R": 2, "O": 1, "T": 5},
            status_class="source_issue",
            private_failure=devoluciones_module._FocusedDevolucionesFailure.SOURCE,
            source_stage=devoluciones_module._FocusedSourceStage.RETURN_DETAIL,
            source_family=devoluciones_module._FocusedSourceFamily.RATE_LIMIT,
        ),
    )

    assert summary.to_focused_evidence(stage="dry_run") == {
        "stage": "dry_run",
        "status_class": "source_issue",
        "counters": {"O": 1, "P": 2, "R": 2, "T": 5},
    }
    assert summary.to_private_diagnostic_evidence() == {
        "failure_class": "source_failure",
        "source_stage": "return_detail",
        "source_family": "rate_limit",
    }


def test_private_diagnostic_preserves_unknown_projection_reason_in_exact_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writes: list[tuple[int, bytes]] = []
    summary = ReconciliationSummary(
        seller_id="82453304",
        date_from="2026-06-01",
        date_to="2026-06-04",
        dry_run=True,
        approved_runtime=True,
        write_enabled=False,
        runtime_evidence=FocusedRuntimeEvidence(
            duration_seconds=0.0,
            source_calls={},
            status_class="query_anomaly",
            private_failure=devoluciones_module._FocusedDevolucionesFailure.PARSER,
            projection_reason="projection_unknown",
        ),
    )
    evidence = summary.to_private_diagnostic_evidence()
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        os,
        "fstat",
        lambda fd: type("PrivateStat", (), {"st_uid": 0, "st_mode": stat.S_IFREG | 0o600})(),
    )

    def write(fd: int, payload: bytes) -> int:
        writes.append((fd, payload))
        return len(payload)

    monkeypatch.setattr(os, "write", write)

    assert evidence == {
        "failure_class": "parser_failure",
        "projection_reason": "projection_unknown",
    }
    reconcile_operation_module._write_root_private_diagnostic_evidence(9, evidence)
    assert writes == [
        (9, b'{"failure_class":"parser_failure","projection_reason":"projection_unknown"}\n')
    ]


@pytest.mark.asyncio
async def test_focused_projection_failure_propagates_only_allowlisted_private_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_snapshot(**_: Any) -> Any:
        raise ClaimProjectionError(
            "sensitive parser detail",
            projection_reason=ClaimProjectionReason.RETURN_QUANTITY,
        )

    monkeypatch.setattr(devoluciones_module, "collect_devoluciones_snapshot", fail_snapshot)

    summary = await reconcile_operation_module.run_focused_devoluciones_reconciliation(
        db=FakeAsyncDb({}),
        request=_request(),
        source=object(),
    )

    assert summary.to_focused_evidence(stage="dry_run") == {
        "stage": "dry_run",
        "status_class": "query_anomaly",
        "counters": {"P": 0, "R": 0, "O": 0, "T": 0},
    }
    assert summary.to_private_diagnostic_evidence() == {
        "failure_class": "parser_failure",
        "projection_reason": "projection_return_quantity",
    }


@pytest.mark.parametrize(
    ("effective_uid", "owner_uid", "mode"),
    [
        (501, 501, stat.S_IFREG | 0o600),
        (0, 501, stat.S_IFREG | 0o600),
        (0, 0, stat.S_IFREG | 0o640),
        (0, 0, stat.S_IFIFO | 0o600),
    ],
    ids=("non-root-process", "non-root-owner", "shared-mode", "non-regular"),
)
def test_private_diagnostic_fd_rejects_non_root_or_shared_channels(
    monkeypatch: pytest.MonkeyPatch,
    effective_uid: int,
    owner_uid: int,
    mode: int,
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: effective_uid)
    monkeypatch.setattr(
        os,
        "fstat",
        lambda fd: type(
            "PrivateStat",
            (),
            {"st_uid": owner_uid, "st_mode": mode},
        )(),
    )

    with pytest.raises(ValueError, match="root|0600"):
        reconcile_operation_module._write_root_private_diagnostic_evidence(
            9,
            {"failure_class": "parser_failure"},
        )


@pytest.mark.asyncio
async def test_focused_write_composes_db_bound_revalidation_heartbeat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    heartbeat_calls: list[tuple[Any, DevolucionesOperationContext]] = []

    async def acquire(**kwargs: Any) -> DevolucionesOperationContext:
        return DevolucionesOperationContext(
            seller_id=kwargs["seller_id"],
            scope="devoluciones",
            operation_id=kwargs["operation_id"],
            attempt_token=kwargs["attempt_token"],
            fence=1,
            owns_lease=True,
            source_fingerprint=kwargs["source_fingerprint"],
        )

    async def collect_counts(**kwargs: Any) -> ReconciliationSummary:
        request = kwargs["request"]
        return ReconciliationSummary(
            seller_id=request.seller_id,
            date_from=request.date_range.date_from,
            date_to=request.date_range.date_to,
            dry_run=False,
            approved_runtime=True,
            write_enabled=True,
            aggregates=(ReadModelAggregate("claims", 1, 1, 0, 1),),
            controls=request.controls,
        )

    async def write_snapshot(**_: Any) -> dict[str, int]:
        return {"written_claims": 1, "written_orders": 1}

    async def write_marker(**_: Any) -> dict[str, int]:
        return {"devoluciones_markers_written": 1}

    async def heartbeat(*, db: Any, operation: DevolucionesOperationContext) -> None:
        heartbeat_calls.append((db, operation))

    db = FakeAsyncDb({})
    monkeypatch.setattr(reconcile_operation_module, "acquire_devoluciones_operation", acquire)
    monkeypatch.setattr(reconcile_operation_module, "collect_reconciliation_counts", collect_counts)
    monkeypatch.setattr(
        reconcile_operation_module,
        "write_complete_read_model_freshness_markers",
        write_marker,
    )
    monkeypatch.setattr(reconcile_operation_module, "heartbeat_devoluciones_operation", heartbeat)
    monkeypatch.setattr(devoluciones_module, "write_devoluciones_snapshot", write_snapshot)
    clock = _FakeMonotonicClock()
    source = _TimedOneClaimFocusedSource(clock)

    result = await reconcile_operation_module.run_focused_devoluciones_reconciliation(
        db=db,
        request=_write_request(extra_args=["--read-model", "devoluciones"]),
        source=source,
        campaign_id="campaign-a",
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert result.write_counts["devoluciones_markers_written"] == 1
    assert result.runtime_evidence is not None
    assert result.runtime_evidence.source_calls == {"P": 4, "R": 4, "O": 2, "T": 10}
    assert scheduled_sample_from_summary(result).physical_attempts == 10
    assert source.return_starts == [0.0, 1.75]
    assert clock.sleeps == [1.75]
    assert heartbeat_calls
    assert all(bound_db is db for bound_db, _ in heartbeat_calls)


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

    assert result == 1
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
    assert output["mandatory_source_gate"] == {
        "read_model": "claims",
        "authoritative": False,
        "issue_codes": [
            "expected_count_unavailable",
            "expected_refs_unavailable",
            "read_model_fingerprint_unavailable",
            "source_fingerprint_unavailable",
            "truth_mode_unavailable",
        ],
    }
    assert "82453304" not in output_json
    assert "SENTINEL_TOKEN" not in output_json


def test_reconciliation_cli_returns_zero_for_complete_authoritative_claims_proof(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from infra.operations import zelerdata_read_model_reconcile

    async def fake_expected(*, db: Any, request: Any) -> ExpectedReadModelCounts:
        return _authoritative_claims_expected()

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
            aggregates=(
                ReadModelAggregate(
                    read_model="claims",
                    expected_count=1,
                    persisted_count=1,
                    missing_count=0,
                    complete_count=1,
                ),
            ),
        )

    monkeypatch.setattr(
        zelerdata_read_model_reconcile, "create_runtime_db", lambda: FakeAsyncDb({})
    )
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

    assert result == 0
    assert output["mandatory_source_gate"] == {
        "read_model": "claims",
        "authoritative": True,
        "issue_codes": [],
    }


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

    assert result == 1
    assert output["phase2_contract"]["approved_runtime_only"] is True
    assert output["phase2_contract"]["dry_run_scopes"] == list(DEFAULT_PHASE2_DRY_RUN_SCOPES)
    assert output["mandatory_source_gate"]["authoritative"] is False
    assert "82453304" not in json.dumps(output, sort_keys=True)


def test_reconciliation_cli_write_executes_write_gate_and_outputs_sanitized_counts(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from infra.operations import zelerdata_read_model_reconcile

    db = FakeAsyncDb({})
    calls: dict[str, Any] = {}

    async def fake_expected(*, db: Any, request: Any) -> ExpectedReadModelCounts:
        expected_calls = calls.setdefault("expected", [])
        expected_calls.append("after_write" if "write" in calls else "before_write")
        return ExpectedReadModelCounts(
            counts={"orders": 1, "catalog_product_snapshots": 1 if "write" in calls else 0}
        )

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

    async def fake_write(*, db: Any, request: Any, operation: Any) -> dict[str, int]:
        del operation
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
    assert calls["expected"] == ["before_write", "after_write"]
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


@pytest.mark.asyncio
async def test_source_gated_complete_legacy_coverage_writes_interval_markers() -> None:
    db = FakeAsyncDb(
        {
            "sheets_stock_time_metrics": [
                _seller_doc(
                    _id="82453304:MLA1:SKU1:2026-06-01:2026-06-05",
                    item_id="MLA1",
                    sku="SKU1",
                    normalized_sku="SKU1",
                    date_from=_dt(1),
                    date_to=_dt(5),
                    active_stock_hours=48,
                    total_hours=96,
                    source="legacy_history_import",
                    history_basis="legacy_imported",
                    coverage_basis="legacy_imported",
                    schema_version=1,
                )
            ],
            "sheets_catalog_time_metrics": [
                _seller_doc(
                    _id="82453304:MLA1:2026-06-01:2026-06-05",
                    item_id="MLA1",
                    date_from=_dt(1),
                    date_to=_dt(5),
                    winning_hours=24,
                    available_hours=96,
                    source="legacy_history_import",
                    history_basis="legacy_imported",
                    coverage_basis="legacy_imported",
                    schema_version=1,
                )
            ],
            "sheets_full_withdrawals": [
                _seller_doc(
                    _id="82453304:RET-1:PKG-1:INV-1",
                    withdrawal_id="RET-1",
                    withdrawal_detail_id="PKG-1",
                    created_at=_dt(2),
                    source="legacy_history_import",
                    history_basis="legacy_imported",
                    coverage_basis="legacy_imported",
                    schema_version=1,
                )
            ],
        }
    )
    request = _write_request()
    expected = ExpectedReadModelCounts(
        counts={
            "stock_time_metrics": 1,
            "catalog_time_metrics": 1,
            "full_withdrawals": 1,
        },
        refs={
            "stock_time_metrics": frozenset({"MLA1"}),
            "catalog_time_metrics": frozenset({"MLA1"}),
            "full_withdrawals": frozenset({"82453304:RET-1:PKG-1:INV-1"}),
        },
        truth_mode={
            "stock_time_metrics": "legacy_imported",
            "catalog_time_metrics": "legacy_imported",
            "full_withdrawals": "legacy_imported",
        },
    )

    summary = await collect_reconciliation_counts(
        db=db,
        request=request,
        expected=expected,
        read_models=("stock_time_metrics", "catalog_time_metrics", "full_withdrawals"),
    )
    counts = await write_complete_read_model_freshness_markers(
        db=db, request=request, summary=summary
    )

    assert counts == {"freshness_markers_written": 3}
    assert {marker["read_model"] for marker in db["sheets_read_model_freshness"].documents} == {
        "stock_time_metrics",
        "catalog_time_metrics",
        "full_withdrawals",
    }
    assert all(
        marker["coverage_basis"] == "legacy_imported"
        for marker in db["sheets_read_model_freshness"].documents
    )


@pytest.mark.asyncio
async def test_source_gated_observed_only_coverage_does_not_write_interval_markers() -> None:
    db = FakeAsyncDb(
        {
            "sheets_stock_time_metrics": [
                _seller_doc(
                    _id="82453304:MLA1:SKU1:2026-06-03:2026-06-05",
                    item_id="MLA1",
                    sku="SKU1",
                    normalized_sku="SKU1",
                    date_from=_dt(3),
                    date_to=_dt(5),
                    active_stock_hours=48,
                    total_hours=48,
                    source="sheets_backfill",
                    history_basis="observed_only",
                    coverage_basis="observed_only",
                    schema_version=1,
                )
            ]
        }
    )
    request = _write_request()
    summary = ReconciliationSummary(
        seller_id=request.seller_id,
        date_from=request.date_range.date_from,
        date_to=request.date_range.date_to,
        dry_run=False,
        approved_runtime=True,
        write_enabled=True,
        aggregates=(
            ReadModelAggregate(
                read_model="stock_time_metrics",
                expected_count=1,
                persisted_count=1,
                missing_count=0,
                complete_count=1,
                truth_mode="observed_only",
            ),
        ),
    )

    counts = await write_complete_read_model_freshness_markers(
        db=db, request=request, summary=summary
    )

    assert counts == {}
    assert db["sheets_read_model_freshness"].documents == []


@pytest.mark.asyncio
async def test_partial_source_gated_stock_inventory_does_not_write_interval_marker() -> None:
    from infra.operations import zelerdata_read_model_reconcile

    db = FakeAsyncDb(
        {
            "item_history_projection": [
                {
                    "_id": "covered-stock-source",
                    "seller_id": "82453304",
                    "item_id": "MLA1",
                    "variations_history": {
                        "SKU1": [
                            {"status2": "active", "changed_at": _dt(1)},
                        ]
                    },
                },
                {
                    "_id": "uncovered-stock-source",
                    "seller_id": "82453304",
                    "item_id": "MLA2",
                    "variations_history": {
                        "SKU2": [
                            {"status2": "active", "changed_at": _dt(3)},
                        ]
                    },
                },
            ],
            "sheets_stock_time_metrics": [
                _seller_doc(
                    _id="82453304:MLA1:SKU1:2026-06-01:2026-06-05",
                    item_id="MLA1",
                    sku="SKU1",
                    normalized_sku="SKU1",
                    date_from=_dt(1),
                    date_to=_dt(5),
                    active_stock_hours=96,
                    total_hours=96,
                    source="legacy_history_import",
                    history_basis="legacy_imported",
                    coverage_basis="legacy_imported",
                    schema_version=1,
                )
            ],
        }
    )
    request = _write_request()

    expected = await zelerdata_read_model_reconcile._collect_source_gated_expected_counts(
        db=db, request=request
    )
    summary = await collect_reconciliation_counts(
        db=db,
        request=request,
        expected=expected,
        read_models=("stock_time_metrics",),
    )
    counts = await write_complete_read_model_freshness_markers(
        db=db, request=request, summary=summary
    )

    stock_aggregate = summary.aggregates[0]
    assert expected.counts["stock_time_metrics"] is None
    assert stock_aggregate.truth_mode != "legacy_imported"
    assert {issue.code for issue in stock_aggregate.issues} == {"source_history_incomplete"}
    assert counts == {}
    assert db["sheets_read_model_freshness"].documents == []


# PR 3: static packaging contract for the authorized DLQ snapshot runtime (R10/R11).
# RED first: these assertions reference content that does not exist yet (worker
# image import smoke, dependency manifest coverage, and runbook markers).

SNAPSHOT_RUNTIME_MODULE = "infra.operations.sheets_dlq_snapshot_runtime"
SNAPSHOT_RUNTIME_SOURCE = Path("infra/operations/sheets_dlq_snapshot_runtime.py")
SHEETS_WORKER_DOCKERFILE = Path("modules/sheets/Dockerfile.worker")
SHEETS_PACKAGE_MANIFEST = Path("modules/sheets/pyproject.toml")
SNAPSHOT_RUNTIME_RUNBOOK = Path("docs/ops/sheets-dlq-reconciliation.md")
SNAPSHOT_EXECUTE_MODULE = "infra.operations.sheets_dlq_snapshot_execute"
SNAPSHOT_EXECUTE_SOURCE = Path("infra/operations/sheets_dlq_snapshot_execute.py")
SHEETS_API_DOCKERFILE = Path("modules/sheets/Dockerfile.api")


def test_sheets_worker_image_import_smoke_covers_snapshot_runtime() -> None:
    dockerfile = SHEETS_WORKER_DOCKERFILE.read_text(encoding="utf-8")

    assert f"import {SNAPSHOT_RUNTIME_MODULE}" in dockerfile
    assert dockerfile.index(f"import {SNAPSHOT_RUNTIME_MODULE}") > dockerfile.index("uv sync")


def test_snapshot_runtime_dependencies_available_in_sheets_context() -> None:
    runtime_source = SNAPSHOT_RUNTIME_SOURCE.read_text(encoding="utf-8")
    sheets_manifest = SHEETS_PACKAGE_MANIFEST.read_text(encoding="utf-8")

    # The worker image runs `uv sync --frozen --package zeler-sheets --no-dev`,
    # so the runtime import resolves only when both dependencies are declared
    # for the zeler-sheets package (R10).
    assert "import aio_pika" in runtime_source
    assert "import httpx" in runtime_source
    assert "aio-pika" in sheets_manifest
    assert "httpx" in sheets_manifest


def test_snapshot_runtime_runbook_authorization_and_boundaries() -> None:
    runbook = SNAPSHOT_RUNTIME_RUNBOOK.read_text(encoding="utf-8")

    # Authorization marker (R11): explicit owner-only token + compare_digest.
    assert "--authorization-token-file" in runbook
    assert "SHEETS_DLQ_SNAPSHOT_AUTH_SHA256" in runbook
    assert "owner-only" in runbook
    assert "compare_digest" in runbook

    # Canonical queue allowlist and deterministic exits.
    assert "zeler.sheets.events.dlq" in runbook
    assert "Deterministic exits" in runbook
    assert "Blind-retry prohibition" in runbook

    # Wave 2 and production execution are explicitly out of scope.
    assert "Wave 2" in runbook
    assert "production" in runbook
    assert "no execution" in runbook.lower() or "no live execution" in runbook.lower()


def test_sheets_worker_packages_the_execute_entrypoint_without_api_or_dependency_drift() -> None:
    worker = SHEETS_WORKER_DOCKERFILE.read_text(encoding="utf-8")
    api = SHEETS_API_DOCKERFILE.read_text(encoding="utf-8")
    source = SNAPSHOT_EXECUTE_SOURCE.read_text(encoding="utf-8")

    assert f"import {SNAPSHOT_EXECUTE_MODULE}" in worker
    assert worker.index(f"import {SNAPSHOT_EXECUTE_MODULE}") > worker.index("uv sync")
    assert OPERATIONS_COPY_STANZA in worker
    assert 'if __name__ == "__main__":' in source
    assert "raise SystemExit(main())" in source
    assert SNAPSHOT_EXECUTE_MODULE not in api
    assert "pip install" not in worker.split("uv sync", 1)[1]


def test_execute_runbook_covers_r14_without_granting_execution_consent() -> None:
    runbook = SNAPSHOT_RUNTIME_RUNBOOK.read_text(encoding="utf-8")
    required_headings = (
        "Purpose|Required authorization|Approved runtime|Preflight|Canonical command|"
        "Safe placeholders|Token and digest|Canonical lock|RabbitMQ binding|Limit|"
        "Side effects|Exit codes|Sanitized report|Cleanup|Rollback|Stop conditions|"
        "Retry prohibition|Remaining prohibitions|POINT_1_PASS checklist"
    )
    required_heading_list: list[str] = re.split(r"\|", required_headings)

    assert all(f"## {heading}" in runbook for heading in required_heading_list)
    required_strings = (
        "/opt/zeler-platform/sheets-dlq-snapshot-execute.sh|platform-vm|sheets-worker|root|"
        "zeler.sheets.events.dlq|24|RABBITMQ_URL|nack-requeue|75|Authorization rejected|"
        "separate explicit consent|does not authorize"
    )
    required_string_list: list[str] = re.split(r"\|", required_strings)
    for required in required_string_list:
        assert required in runbook
    assert "| 5 |" in runbook
    forbidden_operations = "ack|publish|purge|delete|quarantine|direct Python invocation"
    for forbidden in re.split(r"\|", forbidden_operations):
        assert forbidden in runbook
