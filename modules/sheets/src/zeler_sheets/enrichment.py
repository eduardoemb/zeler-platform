from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any, Literal

import httpx
from bson.decimal128 import Decimal128

from zeler_platform_core.clients.meli_gateway_client import GatewayRateLimitError

EnrichmentStatus = Literal[
    "trusted",
    "authoritative_absent",
    "unauthorized",
    "transient",
    "basis_mismatch",
    "malformed",
    "stale",
]


@dataclass(frozen=True)
class EnrichmentFailure:
    status: EnrichmentStatus
    reason: str
    preserve_existing: bool


def classify_fetch_exception(exc: Exception) -> EnrichmentFailure:
    if isinstance(exc, GatewayRateLimitError):
        return EnrichmentFailure(status="transient", reason="rate_limited", preserve_existing=True)
    if isinstance(exc, RuntimeError):
        return EnrichmentFailure(status="transient", reason="runtime_error", preserve_existing=True)
    if isinstance(exc, httpx.RequestError):
        return EnrichmentFailure(status="transient", reason="request_error", preserve_existing=True)
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        if status_code == 429 or status_code >= 500:
            return EnrichmentFailure(
                status="transient",
                reason=f"http_{status_code}",
                preserve_existing=True,
            )
        if status_code in {401, 403}:
            return EnrichmentFailure(
                status="unauthorized",
                reason=f"http_{status_code}",
                preserve_existing=False,
            )
        if status_code == 404:
            return EnrichmentFailure(
                status="authoritative_absent",
                reason="http_404",
                preserve_existing=False,
            )
        return EnrichmentFailure(
            status="malformed",
            reason=f"http_{status_code}",
            preserve_existing=False,
        )
    return EnrichmentFailure(status="malformed", reason="source_error", preserve_existing=False)


def trusted_state(
    *, source: str, synced_at: datetime, basis: dict[str, Any] | None = None
) -> dict[str, Any]:
    return enrichment_state(source=source, status="trusted", synced_at=synced_at, basis=basis)


def enrichment_state(
    *,
    source: str,
    status: EnrichmentStatus,
    synced_at: datetime,
    reason: str | None = None,
    basis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state: dict[str, Any] = {
        "source": source,
        "status": status,
        "reason": reason,
        "synced_at": synced_at,
        "basis_hash": basis_hash(basis) if basis else None,
    }
    if basis is not None:
        state["basis"] = bounded_basis(basis)
    return state


def increment_reason_count(
    counts: dict[str, int], *, field: str, status: EnrichmentStatus, reason: str
) -> None:
    key = f"{field}:{status}:{reason}"
    counts[key] = counts.get(key, 0) + 1


def bounded_basis(raw_basis: dict[str, Any]) -> dict[str, Any]:
    basis: dict[str, Any] = {}
    for key in ("site_id", "category_id", "currency_id", "listing_type_id"):
        string_value = _optional_string(raw_basis.get(key))
        if string_value is not None:
            basis[key] = string_value.upper() if key in {"site_id", "currency_id"} else string_value
    for key in ("shipping_mode", "logistic_type"):
        string_value = _optional_string(raw_basis.get(key))
        if string_value is not None:
            basis[key] = string_value
    for key in ("price", "billable_weight"):
        decimal_value = _decimal_or_none(raw_basis.get(key))
        if decimal_value is not None:
            basis[key] = decimal_value
    tags = raw_basis.get("tags")
    if isinstance(tags, list):
        clean_tags = [tag for raw in tags if (tag := _optional_string(raw)) is not None]
        if clean_tags:
            basis["tags"] = clean_tags
    return basis


def basis_hash(raw_basis: dict[str, Any] | None) -> str | None:
    basis = bounded_basis(raw_basis or {})
    if not basis:
        return None
    serialized = json.dumps(_json_basis(basis), sort_keys=True, separators=(",", ":"))
    return f"sha256:{sha256(serialized.encode('utf-8')).hexdigest()}"


def listing_fee_basis_matches(
    existing_projection: dict[str, Any] | None, context: dict[str, Any]
) -> bool:
    if not isinstance(existing_projection, dict):
        return False
    comparable = ("site_id", "currency_id", "listing_type_id", "category_id")
    for key in comparable:
        existing_value = _optional_string(existing_projection.get(key))
        context_value = _optional_string(context.get(key))
        if key in {"site_id", "currency_id"}:
            existing_value = existing_value.upper() if existing_value is not None else None
            context_value = context_value.upper() if context_value is not None else None
        if existing_value != context_value:
            return False
    return _decimal_or_none(existing_projection.get("price")) == _decimal_or_none(
        context.get("price")
    ) and _optional_basis_matches(existing_projection, context)


def _optional_basis_matches(existing_projection: dict[str, Any], context: dict[str, Any]) -> bool:
    for key in ("shipping_mode", "logistic_type"):
        existing_value = _optional_string(existing_projection.get(key))
        context_value = _optional_string(context.get(key))
        if existing_value is None and context_value is None:
            continue
        if existing_value != context_value:
            return False
    if not _optional_decimal_basis_matches(
        existing_projection.get("billable_weight"), context.get("billable_weight")
    ):
        return False
    return _string_list(existing_projection.get("tags")) == _string_list(context.get("tags"))


def _optional_decimal_basis_matches(existing_value: Any, context_value: Any) -> bool:
    existing_decimal = _decimal_or_none(existing_value)
    context_decimal = _decimal_or_none(context_value)
    if existing_decimal is None and context_decimal is None:
        return True
    return existing_decimal is not None and existing_decimal == context_decimal


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for raw in value if (item := _optional_string(raw)) is not None]


def schema_safe_enrichment_state(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    clean: dict[str, Any] = {}
    for field, raw_state in value.items():
        if raw_state is None or not isinstance(raw_state, dict):
            continue
        state = dict(raw_state)
        basis = state.get("basis")
        if isinstance(basis, dict):
            state["basis"] = _schema_safe_basis(basis)
        clean[str(field)] = state
    return clean or None


def _schema_safe_basis(value: dict[str, Any]) -> dict[str, Any]:
    basis = dict(value)
    for key in ("price", "billable_weight"):
        if key in basis:
            decimal_value = _decimal_or_none(basis[key])
            basis[key] = Decimal128(decimal_value) if decimal_value is not None else None
    return basis


def _json_basis(value: dict[str, Any]) -> dict[str, Any]:
    serialized: dict[str, Any] = {}
    for key, nested in value.items():
        if isinstance(nested, Decimal):
            serialized[key] = str(nested)
        else:
            serialized[key] = nested
    return serialized


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or isinstance(value, (bool, dict, list)):
        return None
    if isinstance(value, Decimal128):
        parsed = value.to_decimal()
    elif isinstance(value, Decimal):
        parsed = value
    else:
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
    if not parsed.is_finite() or parsed < 0:
        return None
    return parsed


def _optional_string(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list, tuple, set, bytes, bytearray)):
        return None
    normalized = str(value).strip()
    return normalized or None
