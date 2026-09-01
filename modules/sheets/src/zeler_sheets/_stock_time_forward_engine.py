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
class _SealedForwardPlan:
    binding: _ForwardBinding
    _action_plan: _StockTimeActionPlan = field(repr=False)
    operation_id: str
    _marker_action: str = field(repr=False)
    _marker_document: Mapping[str, Any] = field(repr=False)
    _marker_preimage: Mapping[str, Any] | None = field(repr=False)


def _digest(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_bson_bytes(document)).hexdigest()


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
    marker_document: Mapping[str, Any],
    marker_preimage: Mapping[str, Any] | None,
) -> _SealedForwardPlan:
    seller = seller_id.strip() if isinstance(seller_id, str) else ""
    if not seller:
        raise _ForwardEngineError("INVALID_SELLER")
    bounds = (date_from, date_to)
    if (
        any(value.tzinfo is None or value.utcoffset() != timedelta(0) for value in bounds)
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
        desired = _canonical_bson_document(marker_document)
        prior = _canonical_bson_document(marker_preimage) if marker_preimage is not None else None
    except _StockTimeActionPlanError as exc:
        raise _ForwardEngineError("INVALID_BSON_INPUT") from exc
    marker_id = f"{seller}:{_READ_MODEL}"
    for marker in (desired, prior):
        if marker is not None and (
            marker.get("_id") != marker_id
            or str(marker.get("seller_id")) != seller
            or marker.get("read_model") != _READ_MODEL
        ):
            raise _ForwardEngineError("ACTION_SCOPE_MISMATCH")
    if desired.get("date_from") != start or desired.get("reconciled_until") != end:
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
        "marker_document": desired,
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
    return _SealedForwardPlan(
        binding,
        validated,
        operation_id,
        "replace" if prior is not None else "insert",
        _deep_freeze(desired),
        _deep_freeze(prior),
    )
