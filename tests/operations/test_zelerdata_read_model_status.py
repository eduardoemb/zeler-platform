"""Tests for the sanitized read-only ZelerData read-model status report.

Covers Phase 2 S4a tasks from
``openspec/changes/zelerdata-read-model-freshness-guards/tasks.md``: 17-row
synthesis with exact contracted keys for full and empty collections (2.1),
and sanitized output that excludes identifiers and degrades malformed or
unknown-source evidence to ``null`` (2.2). Productive-window gates (S4b),
argv/CLI wiring (S4c), and readiness (S5) arrive in later slices.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from infra.operations import zelerdata_read_model_status as status_module

from zeler_platform_core.read_model_freshness import ALL_READ_MODELS

SELLER_ID = "82453304"
NOW = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)
HOUR = timedelta(hours=1)
CONTRACTED_ROW_KEYS = {
    "read_model",
    "state",
    "fresh_until",
    "valid_until",
    "coverage_basis",
    "source",
    "updated_at",
}


class _StatusCollection:
    """In-memory freshness collection; find returns matching documents."""

    def __init__(self, documents: list[dict[str, Any]] | None = None) -> None:
        self.documents = [deepcopy(document) for document in documents or []]

    def find(
        self,
        filter_spec: dict[str, Any],
        projection: dict[str, int] | None = None,
    ) -> list[dict[str, Any]]:
        return [
            deepcopy(document) for document in self.documents if _matches(document, filter_spec)
        ]

    def __getitem__(self, name: str) -> _StatusCollection:
        return self


def _matches(document: dict[str, Any], filter_spec: dict[str, Any]) -> bool:
    return all(
        document.get(field) in expected["$in"]
        if isinstance(expected, dict) and "$in" in expected
        else document.get(field) == expected
        for field, expected in filter_spec.items()
    )


def _marker(**overrides: Any) -> dict[str, Any]:
    marker = {
        "_id": f"{SELLER_ID}:orders",
        "seller_id": SELLER_ID,
        "read_model": "orders",
        "state": "reconciled",
        "fresh_until": NOW + HOUR,
        "updated_at": NOW,
        "source": "zelerdata_read_model_reconcile",
    }
    marker.update(overrides)
    return marker


def _report(collection: _StatusCollection) -> dict[str, Any]:
    return status_module.build_read_model_status_report(db=collection, seller_id=SELLER_ID)


def _row(report: dict[str, Any], read_model: str) -> dict[str, Any]:
    return next(row for row in report["read_models"] if row["read_model"] == read_model)


def _row_of(marker: dict[str, Any], read_model: str = "orders") -> dict[str, Any]:
    return _row(_report(_StatusCollection([marker])), read_model)


# 2.1 — full/empty -> 17 rows, exact keys, missing --------------------------


def test_empty_collection_reports_seventeen_missing_rows() -> None:
    report = _report(_StatusCollection())
    assert [row["read_model"] for row in report["read_models"]] == list(ALL_READ_MODELS)
    assert all(row["state"] == "missing" for row in report["read_models"])
    assert report["summary"] == {
        "fresh": 0,
        "reconciled": 0,
        "stale": 0,
        "failed": 0,
        "missing": 17,
    }


def test_full_marker_set_reports_exact_keys_states_and_summary() -> None:
    markers = [
        _marker(
            read_model=model,
            _id=f"{SELLER_ID}:{model}",
            state="reconciled" if index % 2 == 0 else "stale",
        )
        for index, model in enumerate(ALL_READ_MODELS)
    ]
    report = _report(_StatusCollection(markers))
    assert len(report["read_models"]) == 17
    assert all(set(row) == CONTRACTED_ROW_KEYS for row in report["read_models"])
    assert report["summary"] == {"fresh": 0, "reconciled": 9, "stale": 8, "failed": 0, "missing": 0}


# 2.2 — sanitized output, identifier exclusion, degradation -----------------


def test_projection_and_output_exclude_identifiers_and_unknown_fields() -> None:
    assert set(status_module.CONTRACTED_FIELDS) == CONTRACTED_ROW_KEYS
    assert "seller_id" not in status_module.CONTRACTED_FIELDS
    assert "_id" not in status_module.CONTRACTED_FIELDS
    row = _row_of(
        _marker(
            access_token="SECRET",  # noqa: S106 — fixture proves token fields never leak
            cookie="SECRET",  # noqa: S106
            connection_string="mongodb://SECRET",  # noqa: S106
        )
    )
    assert set(row) == CONTRACTED_ROW_KEYS
    assert "seller_id" not in row and "_id" not in row


@pytest.mark.parametrize(
    "overrides,degraded_field",
    [
        ({"source": "mystery_writer"}, "source"),
        ({"coverage_basis": "garbage"}, "coverage_basis"),
    ],
)
def test_unknown_or_malformed_evidence_degrades(
    overrides: dict[str, Any],
    degraded_field: str,
) -> None:
    row = _row_of(_marker(**overrides))
    assert row[degraded_field] is None


def test_malformed_state_buckets_fail_closed_and_summary_stays_exact() -> None:
    report = _report(_StatusCollection([_marker(state="mystery")]))
    assert _row(report, "orders")["state"] == "stale"
    assert set(report["summary"]) == {"fresh", "reconciled", "stale", "failed", "missing"}


def test_duplicate_marker_documents_collapse_to_one_row() -> None:
    report = _report(_StatusCollection([_marker(), _marker(source="mystery_writer")]))
    rows = [row for row in report["read_models"] if row["read_model"] == "orders"]
    assert len(rows) == 1
    assert rows[0]["source"] is None  # last document wins deterministically
