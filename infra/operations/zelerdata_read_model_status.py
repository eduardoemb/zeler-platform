"""Sanitized read-only status report for ZelerData read-model freshness markers.

S4a emits exactly one row per read model (core 17-name inventory) from a
single projected query of ``sheets_read_model_freshness``, plus a summary
with exactly ``fresh``, ``reconciled``, ``stale``, ``failed``, and
``missing`` counters. Output is sanitized: rows are rebuilt from contracted
fields only, and malformed or unknown evidence degrades to ``null``.
Productive-window gates (S4b), argv/CLI wiring (S4c), and readiness (S5)
arrive in later slices.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from zeler_platform_core.devoluciones_readiness import READ_MODEL_FRESHNESS_COLLECTION
from zeler_platform_core.read_model_freshness import ALL_READ_MODELS

# Contracted per-row fields; the report rebuilds rows from exactly these.
CONTRACTED_FIELDS: tuple[str, ...] = (
    "read_model",
    "state",
    "fresh_until",
    "valid_until",
    "coverage_basis",
    "source",
    "updated_at",
)
# Sources a marker may legitimately carry; any other source becomes null.
STATUS_SOURCE_ALLOWLIST: frozenset[str] = frozenset(
    {
        "questions_event_persistence",
        "zelerdata_read_model_reconcile",
        "zelerdata_devoluciones_joint_reconcile",
        "devoluciones_operation_acquire",
        "devoluciones_operation_invalidate",
        "devoluciones_event_relevance_unknown",
        "devoluciones_relevant_order_event",
        "devoluciones_topology_rollback",
    }
)
VALID_COVERAGE_BASES: frozenset[str] = frozenset({"legacy_imported", "observed_only"})
KNOWN_STATES: frozenset[str] = frozenset({"fresh", "reconciled", "stale", "failed"})


def build_read_model_status_report(*, db: Any, seller_id: str) -> dict[str, Any]:
    """Emit the sanitized per-seller report: one query, 17 rows, summary."""
    projection: dict[str, int] = {field: 1 for field in CONTRACTED_FIELDS} | {"_id": 0}
    cursor = db[READ_MODEL_FRESHNESS_COLLECTION].find(
        {"seller_id": seller_id, "read_model": {"$in": list(ALL_READ_MODELS)}},
        projection,
    )
    by_model: dict[str, Mapping[str, Any]] = {}
    for document in list(cursor):
        if not isinstance(document, Mapping) or document.get("read_model") not in ALL_READ_MODELS:
            continue
        by_model[document["read_model"]] = {
            field: document.get(field) for field in CONTRACTED_FIELDS
        }
    rows = [_synthesize_row(model, by_model.get(model)) for model in ALL_READ_MODELS]
    return {"summary": _summarize(rows), "read_models": rows}


def _synthesize_row(
    read_model: str,
    projected: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """One sanitized row; ``missing`` rows are synthesized on demand."""
    if projected is None:
        return {
            "read_model": read_model,
            "state": "missing",
            "fresh_until": None,
            "valid_until": None,
            "coverage_basis": None,
            "source": None,
            "updated_at": None,
        }
    return {
        "read_model": read_model,
        "state": _normalized_state(projected.get("state")),
        "fresh_until": _sanitized_datetime(projected.get("fresh_until")),
        "valid_until": _sanitized_datetime(projected.get("valid_until")),
        "coverage_basis": _sanitized_allowlisted(
            projected.get("coverage_basis"), VALID_COVERAGE_BASES
        ),
        "source": _sanitized_allowlisted(projected.get("source"), STATUS_SOURCE_ALLOWLIST),
        "updated_at": _sanitized_datetime(projected.get("updated_at")),
    }


def _summarize(rows: list[dict[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = {"fresh": 0, "reconciled": 0, "stale": 0, "failed": 0, "missing": 0}
    for row in rows:
        summary[row["state"]] += 1
    return summary


def _normalized_state(raw: Any) -> str:
    if isinstance(raw, str) and raw in KNOWN_STATES:
        return raw
    return "stale"  # fail-closed bucket; schema validation makes this unreachable


def _sanitized_allowlisted(raw: Any, allowlist: frozenset[str]) -> str | None:
    return raw if isinstance(raw, str) and raw in allowlist else None


def _sanitized_datetime(raw: Any) -> str | None:
    return raw.isoformat() if isinstance(raw, datetime) else None
