from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from .source_gated_read_model_writers import (
    _canonical_bson_bytes,
    _canonical_bson_document,
    _deep_freeze,
    _plan_stock_time_actions,
    _StockTimeAction,
    _StockTimeActionPlan,
    _StockTimeActionPlanError,
)

_READ_MODEL = "stock_time_metrics"
_METRIC_COLLECTION = "sheets_stock_time_metrics"
_MARKER_COLLECTION = "sheets_read_model_freshness"
_RECONCILE_SOURCE = "zelerdata_read_model_reconcile"
_SHA = re.compile(r"^[0-9a-f]{64}$")
_ERROR_CODES = frozenset(
    {
        "INVALID_SELLER",
        "INVALID_UTC_INTERVAL",
        "INVALID_SHA256",
        "INVALID_BSON_INPUT",
        "ACTION_SCOPE_MISMATCH",
        "INVALID_ACTION",
    }
)


class _ForwardEngineError(RuntimeError):
    def __init__(self, code: str) -> None:
        if code not in _ERROR_CODES:
            raise ValueError("unknown forward-engine error code")
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class _ForwardBinding:
    _seller_id: str = field(repr=False)
    date_from: datetime
    date_to: datetime
    source_fingerprint: str
    plan_fingerprint: str


@dataclass(frozen=True)
class _ForwardMutation:
    sequence: int
    target_collection: str
    _target_id: str = field(repr=False)
    action: str
    _document: Mapping[str, Any] | None = field(repr=False)
    _preimage: Mapping[str, Any] | None = field(repr=False)
    preimage_kind: str
    preimage_fingerprint: str
    expected_forward_revision: str


@dataclass(frozen=True)
class _ForwardLedgerCounts:
    planned_insert_count: int
    planned_update_count: int
    planned_delete_count: int
    planned_preimage_count: int


@dataclass(frozen=True)
class _SealedForwardPlan:
    binding: _ForwardBinding
    _action_plan: _StockTimeActionPlan = field(repr=False)
    operation_id: str
    _marker_action: str = field(repr=False)
    _marker_preimage: Mapping[str, Any] | None = field(repr=False)
    _mutations: tuple[_ForwardMutation, ...] = field(repr=False)
    _expected_metric_documents: tuple[Mapping[str, Any], ...] = field(repr=False)
    _desired_marker: Mapping[str, Any] = field(repr=False)
    expected_metric_fingerprint: str
    ledger_counts: _ForwardLedgerCounts


def _digest(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_bson_bytes(document)).hexdigest()


def _operation_revision(
    operation_id: str, target_collection: str, target_id: str, action: str
) -> str:
    return _digest(
        {
            "domain": "zeler.stock-time-forward-revision",
            "version": 1,
            "operation_id": operation_id,
            "target_collection": target_collection,
            "target_id": target_id,
            "action": action,
        }
    )


def _preimage_fingerprint(preimage: Mapping[str, Any] | None) -> str:
    return _digest(
        {
            "domain": "zeler.stock-time-forward-preimage",
            "version": 1,
            "preimage_kind": "absent" if preimage is None else "exact_document",
            "preimage": preimage,
        }
    )


def _metric_proof_fingerprint(documents: Sequence[Mapping[str, Any]]) -> str:
    exact = sorted(documents, key=lambda document: str(document.get("_id")))
    return _digest(
        {
            "domain": "zeler.stock-time-forward-metric-proof",
            "version": 1,
            "exact_final_metrics": exact,
        }
    )


def _mutation(
    *,
    operation_id: str,
    sequence: int,
    target_collection: str,
    target_id: str,
    action: str,
    document: Mapping[str, Any] | None,
    preimage: Mapping[str, Any] | None,
) -> _ForwardMutation:
    return _ForwardMutation(
        sequence=sequence,
        target_collection=target_collection,
        _target_id=target_id,
        action=action,
        _document=_deep_freeze(document),
        _preimage=_deep_freeze(preimage),
        preimage_kind="absent" if preimage is None else "exact_document",
        preimage_fingerprint=_preimage_fingerprint(preimage),
        expected_forward_revision=_operation_revision(
            operation_id, target_collection, target_id, action
        ),
    )


def _materialize_forward_plan(
    *,
    binding: _ForwardBinding,
    action_plan: _StockTimeActionPlan,
    operation_id: str,
    marker_action: str,
    marker_preimage: Mapping[str, Any] | None,
) -> _SealedForwardPlan:
    mutations: list[_ForwardMutation] = []
    final_metrics: list[Mapping[str, Any]] = []
    for action in action_plan.actions:
        if action.action == "no-op":
            if action._preimage is None:
                raise _ForwardEngineError("INVALID_ACTION")
            final_metrics.append(action._preimage)
            continue
        revision = _operation_revision(
            operation_id, _METRIC_COLLECTION, action._target_id, action.action
        )
        document = None
        if action.action != "delete":
            if action._document is None:
                raise _ForwardEngineError("INVALID_ACTION")
            document = _canonical_bson_document({**action._document, "revision": revision})
            final_metrics.append(document)
        mutations.append(
            _mutation(
                operation_id=operation_id,
                sequence=len(mutations) + 1,
                target_collection=_METRIC_COLLECTION,
                target_id=action._target_id,
                action=action.action,
                document=document,
                preimage=action._preimage,
            )
        )

    expected_metrics = tuple(_deep_freeze(document) for document in final_metrics)
    proof = _metric_proof_fingerprint(expected_metrics)
    marker_id = f"{binding._seller_id}:{_READ_MODEL}"
    marker_revision = _operation_revision(
        operation_id, _MARKER_COLLECTION, marker_id, marker_action
    )
    marker = _canonical_bson_document(
        {
            "_id": marker_id,
            "seller_id": binding._seller_id,
            "read_model": _READ_MODEL,
            "state": "reconciled",
            "date_from": binding.date_from,
            "fresh_until": binding.date_to,
            "reconciled_until": binding.date_to,
            "last_event_synced_at": binding.date_from,
            "updated_at": binding.date_to,
            "source": _RECONCILE_SOURCE,
            "coverage_basis": "legacy_imported",
            "revision": marker_revision,
            "proof_fingerprint": proof,
            "schema_version": 1,
        }
    )
    mutations.append(
        _mutation(
            operation_id=operation_id,
            sequence=len(mutations) + 1,
            target_collection=_MARKER_COLLECTION,
            target_id=marker_id,
            action=marker_action,
            document=marker,
            preimage=marker_preimage,
        )
    )
    frozen_mutations = tuple(mutations)
    counts = _ForwardLedgerCounts(
        planned_insert_count=sum(item.action == "insert" for item in frozen_mutations),
        planned_update_count=sum(item.action == "replace" for item in frozen_mutations),
        planned_delete_count=sum(item.action == "delete" for item in frozen_mutations),
        planned_preimage_count=len(frozen_mutations),
    )
    return _SealedForwardPlan(
        binding,
        action_plan,
        operation_id,
        marker_action,
        _deep_freeze(marker_preimage),
        frozen_mutations,
        expected_metrics,
        _deep_freeze(marker),
        proof,
        counts,
    )


def _validated_action_plan(
    source_inventory: Sequence[Mapping[str, Any]], supplied: _StockTimeActionPlan
) -> _StockTimeActionPlan:
    try:
        for row in source_inventory:
            _canonical_bson_bytes(row)
        if not all(isinstance(action, _StockTimeAction) for action in supplied.actions):
            raise _ForwardEngineError("INVALID_ACTION")
        planned = [action._document for action in supplied.actions if action._document is not None]
        existing = [action._preimage for action in supplied.actions if action._preimage is not None]
        validated = _plan_stock_time_actions(
            source_inventory=source_inventory,
            planned_documents=planned,
            existing_target_rows=existing,
        )
    except _StockTimeActionPlanError as exc:
        raise _ForwardEngineError("INVALID_ACTION") from exc
    if supplied != validated:
        raise _ForwardEngineError("INVALID_ACTION")
    return validated


def _seal_forward_plan(
    *,
    seller_id: str,
    date_from: datetime,
    date_to: datetime,
    source_inventory: Sequence[Mapping[str, Any]],
    action_plan: _StockTimeActionPlan,
    marker_preimage: Mapping[str, Any] | None,
) -> _SealedForwardPlan:
    seller = seller_id.strip() if isinstance(seller_id, str) else ""
    if not seller:
        raise _ForwardEngineError("INVALID_SELLER")
    bounds = (date_from, date_to)
    if (
        not all(isinstance(value, datetime) for value in bounds)
        or any(value.tzinfo is None or value.utcoffset() != timedelta(0) for value in bounds)
        or date_to <= date_from
    ):
        raise _ForwardEngineError("INVALID_UTC_INTERVAL")
    start, end = date_from.astimezone(UTC), date_to.astimezone(UTC)
    if not isinstance(action_plan, _StockTimeActionPlan):
        raise _ForwardEngineError("INVALID_ACTION")
    fingerprints = (
        action_plan.source_fingerprint,
        action_plan.preimage_fingerprint,
        action_plan.plan_fingerprint,
    )
    if not all(isinstance(value, str) and _SHA.fullmatch(value) for value in fingerprints):
        raise _ForwardEngineError("INVALID_SHA256")
    try:
        prior = _canonical_bson_document(marker_preimage) if marker_preimage is not None else None
    except _StockTimeActionPlanError as exc:
        raise _ForwardEngineError("INVALID_BSON_INPUT") from exc
    marker_id = f"{seller}:{_READ_MODEL}"
    if prior is not None and (
        prior.get("_id") != marker_id
        or str(prior.get("seller_id")) != seller
        or prior.get("read_model") != _READ_MODEL
    ):
        raise _ForwardEngineError("ACTION_SCOPE_MISMATCH")
    presence = {
        "insert": (True, False),
        "replace": (True, True),
        "delete": (False, True),
        "no-op": (True, True),
    }
    for action in action_plan.actions:
        if not isinstance(action, _StockTimeAction) or action.action not in presence:
            raise _ForwardEngineError("INVALID_ACTION")
        if (action._document is not None, action._preimage is not None) != presence[action.action]:
            raise _ForwardEngineError("INVALID_ACTION")
        scoped = (
            document for document in (action._document, action._preimage) if document is not None
        )
        if any(
            document.get("_id") != action._target_id
            or str(document.get("seller_id")) != seller
            or document.get("date_from") != start
            or document.get("date_to") != end
            for document in scoped
        ):
            raise _ForwardEngineError("ACTION_SCOPE_MISMATCH")
    validated = _validated_action_plan(source_inventory, action_plan)
    seal_material = {
        "domain": "zeler.stock-time-forward-plan",
        "version": 1,
        "action_plan_fingerprint": validated.plan_fingerprint,
        "marker_preimage": prior,
    }
    sealed_fingerprint = _digest(seal_material)
    binding = _ForwardBinding(seller, start, end, validated.source_fingerprint, sealed_fingerprint)
    operation_id = _digest(
        {
            "domain": "zeler.stock-time-forward-operation",
            "version": 1,
            "seller_id": seller,
            "date_from": start,
            "date_to": end,
            "source_fingerprint": binding.source_fingerprint,
            "plan_fingerprint": binding.plan_fingerprint,
        }
    )
    return _materialize_forward_plan(
        binding=binding,
        action_plan=validated,
        operation_id=operation_id,
        marker_action="replace" if prior is not None else "insert",
        marker_preimage=prior,
    )
