"""Sanitized read-only status report for ZelerData read-model freshness markers.

S4a emits exactly one row per read model (core 17-name inventory) from a
single projected query of ``sheets_read_model_freshness``, plus a summary
with exactly ``fresh``, ``reconciled``, ``stale``, ``failed``, and
``missing`` counters. Output is sanitized: rows are rebuilt from contracted
fields only, and malformed or unknown evidence degrades to ``null``.
S4b adds the fail-closed productive-window gate (``in_productive_window``
is ``true`` only for ``fresh``/``reconciled`` markers whose coverage window
includes now, with an allowlisted source, the source-gated legacy basis,
and an unexpired ``valid_until`` for ``devoluciones``) and the
deterministic action map (``none`` / ``await_lease`` for missing
``questions`` / ``re_run_reconcile``). S4c wires the CLI: a parser and
``validate_status_argv`` that reject invalid argv before any DB access,
plus ``main(argv, db)`` emitting the report as JSON. Readiness (S5)
arrives in a later slice.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from zeler_platform_core.devoluciones_readiness import (
    DEVOLUCIONES_READ_MODEL,
    READ_MODEL_FRESHNESS_COLLECTION,
)
from zeler_platform_core.read_model_freshness import ALL_READ_MODELS

__all__ = [
    "ACTION_AWAIT_LEASE",
    "ACTION_NONE",
    "ACTION_RE_RUN_RECONCILE",
    "ALL_READ_MODELS",
    "CONTRACTED_FIELDS",
    "build_read_model_status_report",
    "build_status_arg_parser",
    "main",
    "validate_status_argv",
]

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
# Reconciliation-owned models whose markers carry a source-gated coverage
# basis (mirrors ``_SOURCE_DEFERRED_MODELS`` in
# ``infra.operations.zelerdata_read_model_reconcile``); a productive window
# for these requires a valid basis.
SOURCE_GATED_MODELS: frozenset[str] = frozenset(
    {"stock_time_metrics", "catalog_time_metrics", "full_withdrawals"}
)
# Deterministic per-row actions (design contract).
ACTION_NONE = "none"
ACTION_AWAIT_LEASE = "await_lease"
ACTION_RE_RUN_RECONCILE = "re_run_reconcile"


def build_status_arg_parser() -> argparse.ArgumentParser:
    """Build the status CLI argument parser.

    Validation of parsed argv happens in ``validate_status_argv`` before
    any database access; the parser itself only describes the flags.
    """
    parser = argparse.ArgumentParser(
        description="Emit a sanitized ZelerData read-model freshness status report."
    )
    parser.add_argument("--seller-id", required=True, help="Seller id to report.")
    parser.add_argument(
        "--confirm-approved-runtime",
        action="store_true",
        help="Required for every run; confirms approved VM/VPC/runtime execution.",
    )
    return parser


def validate_status_argv(argv: Sequence[str]) -> argparse.Namespace:
    """Parse and validate CLI argv before any DB access.

    Raises ``SystemExit`` for missing ``--seller-id``, a blank seller id,
    or a missing ``--confirm-approved-runtime`` confirmation.
    """
    args = build_status_arg_parser().parse_args(argv)
    if not str(args.seller_id).strip():
        raise SystemExit("seller-id is required")
    if not bool(args.confirm_approved_runtime):
        raise SystemExit("--confirm-approved-runtime is required")
    return args


def main(argv: Sequence[str], db: Any) -> str:
    """CLI entry: validate argv, build the report, return its JSON.

    ``argv`` is validated before any database access; the report is
    emitted as a JSON string with sorted keys.
    """
    args = validate_status_argv(argv)
    now = datetime.now(UTC)
    report = build_read_model_status_report(
        db=db,
        seller_id=str(args.seller_id).strip(),
        now=now,
    )
    return json.dumps(report, sort_keys=True)


def build_read_model_status_report(*, db: Any, seller_id: str, now: datetime) -> dict[str, Any]:
    """Emit the sanitized per-seller report: one query, 17 rows, summary.

    ``now`` anchors the productive-window evaluation: a row is productive
    only when the marker state is ``fresh`` or ``reconciled`` and the
    coverage window includes ``now``.
    """
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
    rows = [_synthesize_row(model, by_model.get(model), now=now) for model in ALL_READ_MODELS]
    return {"summary": _summarize(rows), "read_models": rows}


def _synthesize_row(
    read_model: str,
    projected: Mapping[str, Any] | None,
    *,
    now: datetime,
) -> dict[str, Any]:
    """One sanitized row; ``missing`` rows are synthesized on demand."""
    if projected is None:
        row: dict[str, Any] = {
            "read_model": read_model,
            "state": "missing",
            "fresh_until": None,
            "valid_until": None,
            "coverage_basis": None,
            "source": None,
            "updated_at": None,
        }
    else:
        row = {
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
    row["in_productive_window"] = _in_productive_window(
        read_model=read_model,
        state=row["state"],
        source=row["source"],
        coverage_basis=row["coverage_basis"],
        fresh_until=projected.get("fresh_until") if projected is not None else None,
        valid_until=projected.get("valid_until") if projected is not None else None,
        now=now,
    )
    row["action_recommended"] = _recommended_action(
        read_model=read_model, state=row["state"], in_window=row["in_productive_window"]
    )
    return row


def _summarize(rows: list[dict[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = {"fresh": 0, "reconciled": 0, "stale": 0, "failed": 0, "missing": 0}
    for row in rows:
        summary[row["state"]] += 1
    return summary


def _in_productive_window(
    *,
    read_model: str,
    state: str,
    source: str | None,
    coverage_basis: str | None,
    fresh_until: Any,
    valid_until: Any,
    now: datetime,
) -> bool:
    """Fail-closed productive-window gate (design contract).

    A row is productive only when the marker is ``fresh`` or ``reconciled``,
    its source is allowlisted, its ``fresh_until`` covers ``now``, the
    source-gated models carry a valid ``coverage_basis``, and
    ``devoluciones`` has an unexpired ``valid_until``.
    """
    if state not in ("fresh", "reconciled"):
        return False
    if source is None:
        return False
    if not _covers_now(fresh_until, now):
        return False
    if read_model in SOURCE_GATED_MODELS and coverage_basis is None:
        return False
    return read_model != DEVOLUCIONES_READ_MODEL or _covers_now(valid_until, now)


def _covers_now(value: Any, now: datetime) -> bool:
    return isinstance(value, datetime) and value > now


def _recommended_action(*, read_model: str, state: str, in_window: bool) -> str:
    """Deterministic state-to-action map (design contract)."""
    if in_window:
        return ACTION_NONE
    if read_model == "questions" and state == "missing":
        return ACTION_AWAIT_LEASE
    return ACTION_RE_RUN_RECONCILE


def _normalized_state(raw: Any) -> str:
    if isinstance(raw, str) and raw in KNOWN_STATES:
        return raw
    return "stale"  # fail-closed bucket; schema validation makes this unreachable


def _sanitized_allowlisted(raw: Any, allowlist: frozenset[str]) -> str | None:
    return raw if isinstance(raw, str) and raw in allowlist else None


def _sanitized_datetime(raw: Any) -> str | None:
    return raw.isoformat() if isinstance(raw, datetime) else None
