from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import infra.operations.zelerdata_read_model_reconcile as reconcile_module
import pytest
from infra.mongo.validator_contract import validate_document_against_schema
from infra.operations.zelerdata_read_model_reconcile import (
    ExpectedReadModelCounts,
    ReadModelAggregate,
    ReconciliationSummary,
    build_arg_parser,
    build_reconciliation_request,
    collect_reconciliation_counts,
    write_complete_read_model_freshness_markers,
)

from zeler_platform_core.devoluciones_readiness import (
    DEVOLUCIONES_OPERATIONS_COLLECTION,
    DevolucionesLeaseLostError,
    DevolucionesOperationContext,
)
from zeler_sheets.claim_projection import persist_claim_projection
from zeler_sheets.devoluciones_reconciliation import (
    collect_devoluciones_snapshot,
    devoluciones_read_model_fingerprint,
)
from zeler_sheets.event_persistence import SheetsEventPersistence
from zeler_sheets.historical_meli_backfill import run_historical_meli_backfill

SELLER_ID = "82453304"
NOW = datetime(2026, 6, 10, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[1]


class _WriteResult:
    def __init__(self, *, matched_count: int = 0, upserted_id: Any = None) -> None:
        self.matched_count = matched_count
        self.modified_count = matched_count
        self.upserted_id = upserted_id


class _Cursor:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self._documents = [deepcopy(document) for document in documents]
        self._index = 0

    def sort(self, sort_spec: list[tuple[str, int]]) -> _Cursor:
        documents = list(self._documents)
        for field, direction in reversed(sort_spec):
            documents.sort(
                key=lambda document: str(_lookup(document, field) or ""),
                reverse=direction < 0,
            )
        return _Cursor(documents)

    async def to_list(self, length: int | None = None) -> list[dict[str, Any]]:
        documents = self._documents if length is None else self._documents[:length]
        return deepcopy(documents)

    def __aiter__(self) -> _Cursor:
        self._index = 0
        return self

    async def __anext__(self) -> dict[str, Any]:
        if self._index >= len(self._documents):
            raise StopAsyncIteration
        document = deepcopy(self._documents[self._index])
        self._index += 1
        return document


class _MemoryCollection:
    def __init__(self, documents: list[dict[str, Any]] | None = None) -> None:
        self.documents: dict[str, dict[str, Any]] = {
            str(document["_id"]): deepcopy(document) for document in documents or []
        }

    async def count_documents(self, filter_spec: dict[str, Any]) -> int:
        return sum(_matches(document, filter_spec) for document in self.documents.values())

    async def find_one(self, filter_spec: dict[str, Any], **_: Any) -> dict[str, Any] | None:
        for document in self.documents.values():
            if _matches(document, filter_spec):
                return deepcopy(document)
        return None

    def find(
        self,
        filter_spec: dict[str, Any],
        projection: dict[str, int] | None = None,
        **_: Any,
    ) -> _Cursor:
        del projection
        return _Cursor(
            [document for document in self.documents.values() if _matches(document, filter_spec)]
        )

    def aggregate(self, pipeline: list[dict[str, Any]]) -> _Cursor:
        documents = list(self.documents.values())
        if pipeline and "$match" in pipeline[0]:
            documents = [
                document for document in documents if _matches(document, pipeline[0]["$match"])
            ]
        group_field = str(pipeline[1]["$group"]["_id"]).removeprefix("$")
        grouped: dict[str, int] = {}
        for document in documents:
            value = _lookup(document, group_field)
            key = "missing" if value is None else str(value)
            grouped[key] = grouped.get(key, 0) + 1
        return _Cursor([{"_id": key, "count": count} for key, count in grouped.items()])

    async def distinct(self, field: str, filter_spec: dict[str, Any]) -> list[Any]:
        return list(
            {
                _lookup(document, field)
                for document in self.documents.values()
                if _matches(document, filter_spec) and _lookup(document, field) is not None
            }
        )

    async def update_one(
        self,
        filter_spec: dict[str, Any],
        update: dict[str, Any] | list[dict[str, Any]],
        *,
        upsert: bool = False,
        **_: Any,
    ) -> _WriteResult:
        for document_id, document in self.documents.items():
            if not _matches(document, filter_spec):
                continue
            _apply_update(document, update)
            self.documents[document_id] = document
            return _WriteResult(matched_count=1)
        if not upsert:
            return _WriteResult()
        document = {
            key: deepcopy(value)
            for key, value in filter_spec.items()
            if not key.startswith("$") and not isinstance(value, dict)
        }
        _apply_update(document, update)
        document_id = str(document.get("_id") or uuid4().hex)
        document["_id"] = document_id
        self.documents[document_id] = document
        return _WriteResult(upserted_id=document_id)

    async def replace_one(
        self,
        filter_spec: dict[str, Any],
        replacement: dict[str, Any],
        *,
        upsert: bool = False,
        **_: Any,
    ) -> _WriteResult:
        for document_id, document in self.documents.items():
            if _matches(document, filter_spec):
                self.documents[document_id] = deepcopy(replacement)
                return _WriteResult(matched_count=1)
        if not upsert:
            return _WriteResult()
        document_id = str(replacement["_id"])
        self.documents[document_id] = deepcopy(replacement)
        return _WriteResult(upserted_id=document_id)


class _Transaction:
    async def __aenter__(self) -> _Transaction:
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None


class _Session:
    def start_transaction(self) -> _Transaction:
        return _Transaction()

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None


class _Client:
    def start_session(self) -> _Session:
        return _Session()


class _MemoryDb:
    def __init__(self, collections: dict[str, list[dict[str, Any]]] | None = None) -> None:
        self.client = _Client()
        self.collections = {
            name: _MemoryCollection(documents) for name, documents in (collections or {}).items()
        }

    def __getitem__(self, name: str) -> _MemoryCollection:
        return self.collections.setdefault(name, _MemoryCollection())


def _lookup(document: dict[str, Any], path: str, *, missing: Any = None) -> Any:
    current: Any = document
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return missing
        current = current[part]
    return current


def _matches(document: dict[str, Any], filter_spec: dict[str, Any]) -> bool:
    for field, expected in filter_spec.items():
        if field == "$and":
            if not all(_matches(document, branch) for branch in expected):
                return False
            continue
        if field == "$or":
            if not any(_matches(document, branch) for branch in expected):
                return False
            continue
        if field == "$expr":
            if not _matches_expr(document, expected):
                return False
            continue
        actual = _lookup(document, field, missing=...)
        if isinstance(expected, dict):
            for operator, operand in expected.items():
                if operator == "$exists" and (actual is not ...) != operand:
                    return False
                if operator == "$ne" and actual == operand:
                    return False
                if operator == "$in" and actual not in operand:
                    return False
                if operator == "$nin" and actual in operand:
                    return False
                if operator == "$gte" and not (actual is not ... and actual >= operand):
                    return False
                if operator == "$gt" and not (actual is not ... and actual > operand):
                    return False
                if operator == "$lte" and not (actual is not ... and actual <= operand):
                    return False
                if operator == "$lt" and not (actual is not ... and actual < operand):
                    return False
            continue
        if actual is ... or actual != expected:
            return False
    return True


def _matches_expr(document: dict[str, Any], expression: dict[str, Any]) -> bool:
    if "$gt" in expression:
        left, right = expression["$gt"]
        left_value = _lookup(document, str(left).removeprefix("$"))
        right_value = NOW if right == "$$NOW" else right
        return left_value is not None and left_value > right_value
    raise AssertionError(f"unsupported expression: {expression}")


def _apply_update(document: dict[str, Any], update: dict[str, Any] | list[dict[str, Any]]) -> None:
    stages = update if isinstance(update, list) else [update]
    for stage in stages:
        for field, value in stage.get("$setOnInsert", {}).items():
            if _lookup(document, field, missing=...) is ...:
                _set_path(document, field, deepcopy(value))
        for field, value in stage.get("$set", {}).items():
            _set_path(document, field, _resolve_update_value(value))
        for field in stage.get("$unset", {}):
            _unset_path(document, field)
        for field in stage.get("$currentDate", {}):
            _set_path(document, field, NOW)


def _resolve_update_value(value: Any) -> Any:
    if value == "$$NOW":
        return NOW
    if isinstance(value, dict) and "$dateAdd" in value:
        expression = value["$dateAdd"]
        assert expression["startDate"] == "$$NOW"
        assert expression["unit"] == "second"
        return NOW + timedelta(seconds=int(expression["amount"]))
    return deepcopy(value)


def _set_path(document: dict[str, Any], path: str, value: Any) -> None:
    target = document
    parts = path.split(".")
    for part in parts[:-1]:
        nested = target.get(part)
        if not isinstance(nested, dict):
            nested = {}
            target[part] = nested
        target = nested
    target[parts[-1]] = value


def _unset_path(document: dict[str, Any], path: str) -> None:
    target: Any = document
    parts = path.split(".")
    for part in parts[:-1]:
        if not isinstance(target, dict) or not isinstance(target.get(part), dict):
            return
        target = target[part]
    if isinstance(target, dict):
        target.pop(parts[-1], None)


def _operation() -> DevolucionesOperationContext:
    return DevolucionesOperationContext(
        seller_id=SELLER_ID,
        scope="devoluciones",
        operation_id="guarded-regression",
        attempt_token=uuid4().hex,
        fence=1,
        owns_lease=True,
    )


def _operation_document(operation: DevolucionesOperationContext) -> dict[str, Any]:
    return {
        "_id": f"{SELLER_ID}:devoluciones",
        "seller_id": SELLER_ID,
        "scope": "devoluciones",
        "operation_id": operation.operation_id,
        "attempt_token": operation.attempt_token,
        "fence": operation.fence,
        "state": "running",
        "lease_until": NOW + timedelta(minutes=2),
        "checkpoint": deepcopy(operation.checkpoint),
    }


def _write_request() -> Any:
    return build_reconciliation_request(
        build_arg_parser().parse_args(
            [
                "--seller-id",
                SELLER_ID,
                "--date-from",
                "2026-06-01",
                "--date-to",
                "2026-06-09",
                "--confirm-approved-runtime",
                "--write",
                "--confirm-production-write",
            ]
        )
    )


def _complete_claim_summary() -> ReconciliationSummary:
    request = _write_request()
    return ReconciliationSummary(
        seller_id=SELLER_ID,
        date_from=request.date_range.date_from,
        date_to=request.date_range.date_to,
        dry_run=False,
        approved_runtime=True,
        write_enabled=True,
        aggregates=(
            ReadModelAggregate(
                read_model="claims",
                expected_count=9,
                persisted_count=9,
                missing_count=0,
                complete_count=9,
            ),
        ),
    )


@pytest.mark.parametrize("ownership_state", ["expired", "taken_over"])
@pytest.mark.asyncio
async def test_actual_guarded_marker_writer_rejects_stale_owner(
    ownership_state: str,
) -> None:
    operation = _operation()
    operation_document = _operation_document(operation)
    if ownership_state == "expired":
        operation_document["lease_until"] = NOW - timedelta(seconds=1)
    else:
        operation_document["attempt_token"] = uuid4().hex
        operation_document["fence"] = 2
    freshness = [
        {
            "_id": f"{SELLER_ID}:claims",
            "seller_id": SELLER_ID,
            "read_model": "claims",
            "state": "stale",
        },
        {
            "_id": f"{SELLER_ID}:devoluciones",
            "seller_id": SELLER_ID,
            "read_model": "devoluciones",
            "state": "stale",
        },
    ]
    db = _MemoryDb(
        {
            DEVOLUCIONES_OPERATIONS_COLLECTION: [operation_document],
            "sheets_read_model_freshness": freshness,
        }
    )

    with pytest.raises(DevolucionesLeaseLostError, match="lease guard failed"):
        await write_complete_read_model_freshness_markers(
            db=db,
            request=_write_request(),
            summary=_complete_claim_summary(),
            operation=operation,
        )

    assert db["sheets_read_model_freshness"].documents == {
        marker["_id"]: marker for marker in freshness
    }
    assert operation.lease_lost is True


@pytest.mark.asyncio
async def test_actual_guarded_marker_writer_allows_current_owner_only() -> None:
    operation = _operation()
    db = _MemoryDb(
        {
            DEVOLUCIONES_OPERATIONS_COLLECTION: [_operation_document(operation)],
            "sheets_read_model_freshness": [],
        }
    )

    counts = await write_complete_read_model_freshness_markers(
        db=db,
        request=_write_request(),
        summary=ReconciliationSummary(
            seller_id=SELLER_ID,
            date_from="2026-06-01",
            date_to="2026-06-09",
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
        ),
        operation=operation,
    )

    assert counts == {"freshness_markers_written": 1}
    assert db["sheets_read_model_freshness"].documents[f"{SELLER_ID}:questions"]["state"] == (
        "reconciled"
    )
    assert f"{SELLER_ID}:devoluciones" not in db["sheets_read_model_freshness"].documents


class _NineClaimSource:
    def __init__(self) -> None:
        self.claim_ids = [str(5100 + index) for index in range(1, 10)]

    async def search_claims(
        self, *, seller_id: str, params: dict[str, str | int]
    ) -> dict[str, Any]:
        assert seller_id == SELLER_ID
        offset = int(params["offset"])
        limit = int(params["limit"])
        rows = [
            {
                "id": claim_id,
                "last_updated": f"2026-06-{index:02d}T12:00:00Z",
                "date_created": f"2026-06-{index:02d}T10:00:00Z",
            }
            for index, claim_id in enumerate(self.claim_ids, start=1)
        ]
        return {
            "data": rows[offset : offset + limit],
            "paging": {"offset": offset, "limit": limit, "total": len(rows)},
        }

    async def get_claim(self, *, seller_id: str, claim_id: str) -> dict[str, Any]:
        index = self.claim_ids.index(claim_id) + 1
        return {
            "id": claim_id,
            "order_id": str(6100 + index),
            "item_id": f"MLM{index}",
            "type": "return",
            "status": "closed",
            "stage": "claim",
            "claim_version": 9,
            "last_updated": f"2026-06-{index:02d}T12:00:00Z",
            "date_created": f"2026-06-{index:02d}T10:00:00Z",
            "players": [
                {"user_id": SELLER_ID, "role": "respondent", "type": "seller"},
                {"user_id": "buyer", "role": "complainant", "type": "buyer"},
            ],
        }

    async def get_returns(self, *, seller_id: str, claim_id: str) -> dict[str, Any]:
        index = self.claim_ids.index(claim_id) + 1
        return {
            "id": str(7100 + index),
            "status": "closed",
            "subtype": "return_partial",
            "last_updated": f"2026-06-{index:02d}T13:00:00Z",
            "orders": [
                {
                    "order_id": str(6100 + index),
                    "item_id": f"MLM{index}",
                    "return_quantity": 1,
                }
            ],
        }

    async def get_order(self, *, seller_id: str, order_id: str) -> dict[str, Any]:
        index = int(order_id) - 6100
        return {
            "id": order_id,
            "seller": {"id": seller_id},
            "buyer": {"id": "buyer"},
            "status": "paid",
            "date_created": f"2026-06-{index:02d}T09:00:00Z",
            "last_updated": f"2026-06-{index:02d}T09:30:00Z",
            "total_amount": "10.00",
            "order_items": [{"item": {"id": f"MLM{index}"}, "quantity": 1, "unit_price": "10.00"}],
        }


class _EmptyHistoricalGateway:
    async def fetch_resource(self, *, seller_id: str, path: str) -> dict[str, Any]:
        assert seller_id == SELLER_ID
        if path.startswith("/orders/search?"):
            return {"results": [], "paging": {"total": 0, "offset": 0, "limit": 50}}
        raise AssertionError(path)


@pytest.mark.asyncio
async def test_local_reconciliation_expands_three_persisted_claims_to_nine() -> None:
    source = _NineClaimSource()
    snapshot = await collect_devoluciones_snapshot(
        source=source,
        seller_id=SELLER_ID,
        start=datetime(2026, 6, 1, tzinfo=UTC),
        end=NOW,
    )
    operation = _operation()
    operation.source_fingerprint = snapshot.source_fingerprint
    db = _MemoryDb({DEVOLUCIONES_OPERATIONS_COLLECTION: [_operation_document(operation)]})
    persistence = SheetsEventPersistence(db=db)
    for order in snapshot.order_documents()[:3]:
        await persistence.persist(
            event_type="orders.updated",
            seller_id=SELLER_ID,
            resource=order,
            operation=operation,
        )
    for claim in snapshot.claim_documents()[:3]:
        await persist_claim_projection(db=db, document=claim, operation=operation)
    operation.checkpoint = {"claim_id": source.claim_ids[2]}

    assert set(db["claims"].documents) == set(source.claim_ids[:3])
    assert len(db["orders"].documents) == 3

    summary = await run_historical_meli_backfill(
        db=db,
        gateway=_EmptyHistoricalGateway(),
        order_detail_gateway=_EmptyHistoricalGateway(),
        seller_id=SELLER_ID,
        date_from="2026-06-01",
        date_to="2026-06-09",
        dry_run=False,
        approved_runtime=True,
        include_claims=True,
        operation=operation,
        devoluciones_source=source,
    )

    assert summary.existing_claims == 3
    assert summary.missing_claims == 6
    assert summary.written_claims == 6
    assert set(db["claims"].documents) == set(source.claim_ids)
    assert len(db["orders"].documents) == 9

    request = _write_request()
    reconciled = await collect_reconciliation_counts(
        db=db,
        request=request,
        expected=ExpectedReadModelCounts(
            counts={"claims": 9},
            refs={"claims": frozenset(source.claim_ids)},
            truth_mode={"claims": "expected"},
            source_fingerprint=snapshot.source_fingerprint,
            read_model_fingerprint=snapshot.read_model_fingerprint,
        ),
    )
    claim_counts = next(
        aggregate.to_sanitized_dict()
        for aggregate in reconciled.aggregates
        if aggregate.read_model == "claims"
    )

    assert claim_counts == {
        "read_model": "claims",
        "expected_count": 9,
        "persisted_count": 9,
        "missing_count": 0,
        "complete_count": 9,
    }


def _joint_claim(claim_id: str, *, order_id: str, item_id: str, productive: bool) -> dict[str, Any]:
    document: dict[str, Any] = {
        "_id": claim_id,
        "seller_id": SELLER_ID,
        "order_id": order_id,
        "item_id": item_id,
        "status": "closed",
        "stage": "claim",
        "type": "returns",
        "date_created": datetime(2026, 6, 2, tzinfo=UTC),
        "productive": productive,
        "claim_version": 9,
        "last_updated": datetime(2026, 6, 2, 1, tzinfo=UTC),
        "return_id": f"return-{claim_id}",
        "return_last_updated": datetime(2026, 6, 2, 2, tzinfo=UTC),
        "return_status": "closed",
        "return_subtype": "return_partial",
        "schema_version": 1,
    }
    if productive:
        document.update({"returned_quantity": 1, "return_quantity_basis": "v2_return_order"})
    else:
        document.update(
            {
                "return_subtype": "low_cost",
                "return_quantity_basis": "verified_low_cost_no_row",
            }
        )
    return document


def _joint_order(order_id: str, *, item_id: str) -> dict[str, Any]:
    return {
        "_id": order_id,
        "seller_id": SELLER_ID,
        "date_created": datetime(2025, 1, 1, tzinfo=UTC),
        "items": [{"item_id": item_id, "qty": 1, "unit_price": "10.00"}],
        "schema_version": 1,
    }


@pytest.mark.asyncio
async def test_actual_guarded_writer_rejects_narrower_joint_marker_without_union() -> None:
    operation = _operation()
    operation.source_fingerprint = "stable-claims"
    operation.required_coverage_start = datetime(2026, 5, 1, tzinfo=UTC)
    operation.required_coverage_end = datetime(2026, 7, 1, tzinfo=UTC)
    claims = [
        _joint_claim("claim-1", order_id="order-1", item_id="MLA1", productive=True),
        _joint_claim("claim-2", order_id="order-2", item_id="MLA2", productive=False),
    ]
    existing_joint_marker = {
        "_id": f"{SELLER_ID}:devoluciones",
        "seller_id": SELLER_ID,
        "read_model": "devoluciones",
        "state": "reconciled",
        "date_from": datetime(2026, 5, 1, tzinfo=UTC),
        "fresh_until": datetime(2026, 7, 1, tzinfo=UTC),
        "reconciled_until": datetime(2026, 7, 1, tzinfo=UTC),
        "last_event_synced_at": datetime(2026, 5, 1, tzinfo=UTC),
        "valid_until": NOW + timedelta(minutes=5),
        "updated_at": NOW,
        "schema_version": 1,
    }
    db = _MemoryDb(
        {
            DEVOLUCIONES_OPERATIONS_COLLECTION: [_operation_document(operation)],
            "claims": claims,
            "orders": [
                _joint_order("order-1", item_id="MLA1"),
                _joint_order("order-2", item_id="MLA2"),
            ],
            "sheets_read_model_freshness": [existing_joint_marker],
        }
    )
    request = _write_request()
    summary = ReconciliationSummary(
        seller_id=SELLER_ID,
        date_from=request.date_range.date_from,
        date_to=request.date_range.date_to,
        dry_run=False,
        approved_runtime=True,
        write_enabled=True,
        aggregates=(
            ReadModelAggregate(
                read_model="claims",
                expected_count=2,
                persisted_count=2,
                missing_count=0,
                complete_count=1,
            ),
        ),
    )
    expected = ExpectedReadModelCounts(
        counts={"claims": 2},
        refs={"claims": frozenset({"claim-1", "claim-2"})},
        truth_mode={"claims": "expected"},
        source_fingerprint="stable-claims",
        read_model_fingerprint=devoluciones_read_model_fingerprint(
            seller_id=SELLER_ID,
            claims=claims,
            orders=[
                _joint_order("order-1", item_id="MLA1"),
                _joint_order("order-2", item_id="MLA2"),
            ],
        ),
    )

    counts = await write_complete_read_model_freshness_markers(
        db=db,
        request=request,
        summary=summary,
        expected=expected,
        operation=operation,
    )

    assert counts == {}
    assert set(db["sheets_read_model_freshness"].documents) == {f"{SELLER_ID}:devoluciones"}
    marker = db["sheets_read_model_freshness"].documents[f"{SELLER_ID}:devoluciones"]
    assert marker["date_from"] == datetime(2026, 5, 1, tzinfo=UTC)
    assert marker["reconciled_until"] == datetime(2026, 7, 1, tzinfo=UTC)
    assert marker["fresh_until"] == datetime(2026, 7, 1, tzinfo=UTC)
    assert marker["valid_until"] == NOW + timedelta(minutes=5)
    validator = json.loads(
        (ROOT / "infra/mongo/schemas/sheets_read_model_freshness.json").read_text()
    )
    assert validate_document_against_schema(marker, validator).valid is True


@pytest.mark.asyncio
async def test_actual_guarded_writer_replaces_contained_joint_marker_with_exact_request() -> None:
    operation = _operation()
    operation.source_fingerprint = "stable-claims"
    operation.required_coverage_start = datetime(2026, 6, 2, tzinfo=UTC)
    operation.required_coverage_end = datetime(2026, 6, 5, tzinfo=UTC)
    claims = [_joint_claim("claim-1", order_id="order-1", item_id="MLA1", productive=True)]
    orders = [_joint_order("order-1", item_id="MLA1")]
    db = _MemoryDb(
        {
            DEVOLUCIONES_OPERATIONS_COLLECTION: [_operation_document(operation)],
            "claims": claims,
            "orders": orders,
            "sheets_read_model_freshness": [
                {
                    "_id": f"{SELLER_ID}:devoluciones",
                    "seller_id": SELLER_ID,
                    "read_model": "devoluciones",
                    "state": "stale",
                    "date_from": operation.required_coverage_start,
                    "fresh_until": operation.required_coverage_end,
                    "reconciled_until": operation.required_coverage_end,
                    "last_event_synced_at": operation.required_coverage_start,
                    "valid_until": NOW,
                    "updated_at": NOW,
                    "schema_version": 1,
                }
            ],
        }
    )
    request = _write_request()
    summary = ReconciliationSummary(
        seller_id=SELLER_ID,
        date_from=request.date_range.date_from,
        date_to=request.date_range.date_to,
        dry_run=False,
        approved_runtime=True,
        write_enabled=True,
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
    expected = ExpectedReadModelCounts(
        counts={"claims": 1},
        refs={"claims": frozenset({"claim-1"})},
        truth_mode={"claims": "expected"},
        source_fingerprint="stable-claims",
        read_model_fingerprint=devoluciones_read_model_fingerprint(
            seller_id=SELLER_ID,
            claims=claims,
            orders=orders,
        ),
    )

    counts = await write_complete_read_model_freshness_markers(
        db=db,
        request=request,
        summary=summary,
        expected=expected,
        operation=operation,
    )

    marker = db["sheets_read_model_freshness"].documents[f"{SELLER_ID}:devoluciones"]
    assert counts == {"devoluciones_markers_written": 1}
    assert marker["date_from"] == request.date_range.start
    assert marker["reconciled_until"] == request.date_range.end_exclusive
    assert marker["revision"] == operation.attempt_token
    assert marker["proof_fingerprint"] == expected.read_model_fingerprint


@pytest.mark.asyncio
async def test_joint_marker_revokes_publication_when_deadline_expires_after_write() -> None:
    operation = _operation()
    operation.source_fingerprint = "stable-claims"
    claims = [_joint_claim("claim-1", order_id="order-1", item_id="MLA1", productive=True)]
    orders = [_joint_order("order-1", item_id="MLA1")]
    db = _MemoryDb(
        {
            DEVOLUCIONES_OPERATIONS_COLLECTION: [_operation_document(operation)],
            "claims": claims,
            "orders": orders,
        }
    )
    request = _write_request()
    summary = ReconciliationSummary(
        seller_id=SELLER_ID,
        date_from=request.date_range.date_from,
        date_to=request.date_range.date_to,
        dry_run=False,
        approved_runtime=True,
        write_enabled=True,
        aggregates=(ReadModelAggregate("claims", 1, 1, 0, 1),),
    )
    expected = ExpectedReadModelCounts(
        counts={"claims": 1},
        refs={"claims": frozenset({"claim-1"})},
        truth_mode={"claims": "expected"},
        source_fingerprint="stable-claims",
        read_model_fingerprint=devoluciones_read_model_fingerprint(
            seller_id=SELLER_ID,
            claims=claims,
            orders=orders,
        ),
    )
    guard_calls = 0

    def publication_guard() -> None:
        nonlocal guard_calls
        guard_calls += 1
        if guard_calls >= 4:
            raise RuntimeError("focused DEVOLUCIONES process deadline exceeded")

    with pytest.raises(RuntimeError, match="deadline"):
        await write_complete_read_model_freshness_markers(
            db=db,
            request=request,
            summary=summary,
            expected=expected,
            operation=operation,
            publication_guard=publication_guard,
        )

    marker = db["sheets_read_model_freshness"].documents[f"{SELLER_ID}:devoluciones"]
    assert marker["state"] == "stale"
    assert marker["revision"] == operation.attempt_token


@pytest.mark.asyncio
async def test_joint_marker_revokes_when_commit_latency_crosses_publication_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operation = _operation()
    operation.source_fingerprint = "stable-claims"
    claims = [_joint_claim("claim-1", order_id="order-1", item_id="MLA1", productive=True)]
    orders = [_joint_order("order-1", item_id="MLA1")]
    db = _MemoryDb(
        {
            DEVOLUCIONES_OPERATIONS_COLLECTION: [_operation_document(operation)],
            "claims": claims,
            "orders": orders,
        }
    )
    request = _write_request()
    summary = ReconciliationSummary(
        seller_id=SELLER_ID,
        date_from=request.date_range.date_from,
        date_to=request.date_range.date_to,
        dry_run=False,
        approved_runtime=True,
        write_enabled=True,
        aggregates=(ReadModelAggregate("claims", 1, 1, 0, 1),),
    )
    expected = ExpectedReadModelCounts(
        counts={"claims": 1},
        refs={"claims": frozenset({"claim-1"})},
        truth_mode={"claims": "expected"},
        source_fingerprint="stable-claims",
        read_model_fingerprint=devoluciones_read_model_fingerprint(
            seller_id=SELLER_ID,
            claims=claims,
            orders=orders,
        ),
    )
    commit_finished = False

    async def delayed_commit(**kwargs: Any) -> Any:
        nonlocal commit_finished
        result = await kwargs["writer"](None)
        commit_finished = True
        return result

    def publication_guard() -> None:
        if commit_finished:
            raise RuntimeError("focused DEVOLUCIONES process deadline exceeded after commit")

    monkeypatch.setattr(reconcile_module, "guarded_devoluciones_write", delayed_commit)

    with pytest.raises(RuntimeError, match="after commit"):
        await write_complete_read_model_freshness_markers(
            db=db,
            request=request,
            summary=summary,
            expected=expected,
            operation=operation,
            publication_guard=publication_guard,
        )

    marker = db["sheets_read_model_freshness"].documents[f"{SELLER_ID}:devoluciones"]
    assert marker["state"] == "stale"


@pytest.mark.asyncio
async def test_joint_marker_dry_run_writes_nothing() -> None:
    operation = _operation()
    db = _MemoryDb({DEVOLUCIONES_OPERATIONS_COLLECTION: [_operation_document(operation)]})
    request = build_reconciliation_request(
        build_arg_parser().parse_args(
            [
                "--seller-id",
                SELLER_ID,
                "--date-from",
                "2026-06-01",
                "--date-to",
                "2026-06-09",
                "--confirm-approved-runtime",
            ]
        )
    )

    counts = await write_complete_read_model_freshness_markers(
        db=db,
        request=request,
        summary=ReconciliationSummary(
            seller_id=SELLER_ID,
            date_from=request.date_range.date_from,
            date_to=request.date_range.date_to,
            dry_run=True,
            approved_runtime=True,
            write_enabled=False,
        ),
        expected=ExpectedReadModelCounts(counts={"claims": 0}),
        operation=operation,
    )

    assert counts == {}
    assert db["sheets_read_model_freshness"].documents == {}


@pytest.mark.asyncio
async def test_joint_marker_rejects_open_utc_range_before_fenced_write() -> None:
    operation = _operation()
    db = _MemoryDb({DEVOLUCIONES_OPERATIONS_COLLECTION: [_operation_document(operation)]})
    open_utc_date = datetime.now(UTC).date().isoformat()
    request = build_reconciliation_request(
        build_arg_parser().parse_args(
            [
                "--seller-id",
                SELLER_ID,
                "--date-from",
                open_utc_date,
                "--date-to",
                open_utc_date,
                "--confirm-approved-runtime",
                "--write",
                "--confirm-production-write",
            ]
        )
    )

    with pytest.raises(ValueError, match="closed UTC range"):
        await write_complete_read_model_freshness_markers(
            db=db,
            request=request,
            summary=ReconciliationSummary(
                seller_id=SELLER_ID,
                date_from=request.date_range.date_from,
                date_to=request.date_range.date_to,
                dry_run=False,
                approved_runtime=True,
                write_enabled=True,
            ),
            expected=ExpectedReadModelCounts(counts={"claims": 0}),
            operation=operation,
        )

    operation_document = db[DEVOLUCIONES_OPERATIONS_COLLECTION].documents[
        f"{SELLER_ID}:devoluciones"
    ]
    assert operation_document["checkpoint"] == {}
    assert db["sheets_read_model_freshness"].documents == {}
