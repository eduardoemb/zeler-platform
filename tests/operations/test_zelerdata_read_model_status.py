"""Tests for the sanitized read-only ZelerData read-model status report.

Covers Phase 2 S4a-S5 tasks from
``openspec/changes/zelerdata-read-model-freshness-guards/tasks.md``: 17-row
synthesis with exact contracted keys for full and empty collections (2.1),
sanitized output that excludes identifiers and degrades malformed or
unknown-source evidence to ``null`` (2.2), ``in_productive_window`` gated on
productive evidence (2.3), the deterministic action map ``none`` /
``await_lease`` / ``re_run_reconcile`` (2.4), the CLI wiring that consumes
the core inventory object and validates argv before any DB access (3.1,
2.6d), and the S5 readiness contract (2.5): ``ready``/``degraded`` with a
``blocking`` list, the completed ``main()`` contract that reads once per run
and never writes, nonzero exit when readiness is degraded or the run is
anomalous, and sanitized errors.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any, cast

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
# Derived per-row fields exposed on top of the contracted projection.
ROW_KEYS = CONTRACTED_ROW_KEYS | {"in_productive_window", "action_recommended"}


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
    return status_module.build_read_model_status_report(db=collection, seller_id=SELLER_ID, now=NOW)


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
    assert all(set(row) == ROW_KEYS for row in report["read_models"])
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
    assert set(row) == ROW_KEYS
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


# 2.3 — in_productive_window only on productive evidence --------------------


def test_reconciled_marker_with_covering_window_is_productive() -> None:
    row = _row_of(_marker(state="reconciled", fresh_until=NOW + HOUR))
    assert row["in_productive_window"] is True


def test_fresh_marker_with_covering_window_is_productive() -> None:
    row = _row_of(_marker(state="fresh", fresh_until=NOW + HOUR))
    assert row["in_productive_window"] is True


@pytest.mark.parametrize("state", ["stale", "failed", "missing", "mystery"])
def test_non_productive_states_are_outside_window(state: str) -> None:
    row = _row_of(_marker(state=state, fresh_until=NOW + HOUR))
    assert row["in_productive_window"] is False


def test_expired_fresh_until_is_outside_window() -> None:
    row = _row_of(_marker(state="reconciled", fresh_until=NOW - HOUR))
    assert row["in_productive_window"] is False


def test_absent_fresh_until_is_outside_window() -> None:
    row = _row_of(_marker(state="reconciled", fresh_until=None))
    assert row["in_productive_window"] is False


def test_unknown_source_is_outside_window() -> None:
    row = _row_of(_marker(source="mystery_writer", state="reconciled", fresh_until=NOW + HOUR))
    assert row["source"] is None
    assert row["in_productive_window"] is False


def test_missing_questions_and_orders_are_outside_window() -> None:
    report = _report(_StatusCollection())
    assert _row(report, "questions")["in_productive_window"] is False
    assert _row(report, "orders")["in_productive_window"] is False


@pytest.mark.parametrize(
    "read_model,basis",
    [
        ("stock_time_metrics", None),
        ("catalog_time_metrics", "garbage"),
        ("full_withdrawals", None),
    ],
)
def test_source_gated_models_require_valid_legacy_basis(read_model: str, basis: str | None) -> None:
    row = _row_of(
        _marker(
            read_model=read_model,
            state="reconciled",
            fresh_until=NOW + HOUR,
            coverage_basis=basis,
        ),
        read_model=read_model,
    )
    assert row["coverage_basis"] is None
    assert row["in_productive_window"] is False


@pytest.mark.parametrize(
    "basis",
    ["legacy_imported", "observed_only"],
)
def test_source_gated_models_with_valid_basis_are_productive(basis: str) -> None:
    row = _row_of(
        _marker(
            read_model="stock_time_metrics",
            state="reconciled",
            fresh_until=NOW + HOUR,
            coverage_basis=basis,
        ),
        read_model="stock_time_metrics",
    )
    assert row["coverage_basis"] == basis
    assert row["in_productive_window"] is True


def test_devoluciones_requires_unexpired_valid_until() -> None:
    row = _row_of(
        _marker(
            read_model="devoluciones",
            state="reconciled",
            fresh_until=NOW + HOUR,
            valid_until=NOW - HOUR,
        ),
        read_model="devoluciones",
    )
    assert row["valid_until"] is not None
    assert row["in_productive_window"] is False


def test_devoluciones_with_live_valid_until_is_productive() -> None:
    row = _row_of(
        _marker(
            read_model="devoluciones",
            state="reconciled",
            fresh_until=NOW + HOUR,
            valid_until=NOW + HOUR,
        ),
        read_model="devoluciones",
    )
    assert row["in_productive_window"] is True


# 2.4 — deterministic action map -------------------------------------------


def test_productive_row_recommends_none() -> None:
    row = _row_of(_marker(state="reconciled", fresh_until=NOW + HOUR))
    assert row["action_recommended"] == "none"


def test_missing_questions_recommends_await_lease() -> None:
    report = _report(_StatusCollection())
    assert _row(report, "questions")["action_recommended"] == "await_lease"


def test_missing_other_models_recommend_re_run_reconcile() -> None:
    report = _report(_StatusCollection())
    assert _row(report, "orders")["action_recommended"] == "re_run_reconcile"


@pytest.mark.parametrize("state", ["stale", "failed"])
def test_stale_and_failed_recommend_re_run_reconcile(state: str) -> None:
    row = _row_of(_marker(state=state, fresh_until=NOW + HOUR))
    assert row["action_recommended"] == "re_run_reconcile"


def test_expired_and_malformed_recommend_re_run_reconcile() -> None:
    expired = _row_of(_marker(state="reconciled", fresh_until=NOW - HOUR))
    malformed = _row_of(_marker(state="mystery", fresh_until=NOW + HOUR))
    assert expired["action_recommended"] == "re_run_reconcile"
    assert malformed["action_recommended"] == "re_run_reconcile"


def test_stale_questions_recommend_re_run_reconcile_not_await_lease() -> None:
    row = _row_of(
        _marker(read_model="questions", state="stale", fresh_until=NOW + HOUR),
        read_model="questions",
    )
    assert row["action_recommended"] == "re_run_reconcile"


# 3.1 — CLI wired to core inventory (no duplicated list) ----------------------
#
# The status CLI must consume the core 17-name inventory object directly.
# Task 1.1's parity test locks core-vs-reconciliation; these tests lock the
# CLI to the same core object (identity, never a duplicated list).


def test_status_cli_uses_core_inventory_object_identity() -> None:
    assert status_module.ALL_READ_MODELS is ALL_READ_MODELS
    assert len(status_module.ALL_READ_MODELS) == 17


def test_status_main_json_rows_follow_core_inventory_order() -> None:
    payload = json.loads(
        status_module.main(
            ["--seller-id", SELLER_ID, "--confirm-approved-runtime"],
            db=_StatusCollection(),
        )
    )
    assert [row["read_model"] for row in payload["read_models"]] == list(ALL_READ_MODELS)


# 2.6d — argv validation precedes DB; parser; main(argv, db) JSON -------------


class _SpyStatusDb:
    """Records collection access to prove validation precedes any DB use."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getitem__(self, name: str) -> Any:
        self.calls.append(name)
        return object()


@pytest.mark.parametrize(
    "argv",
    [
        [],  # no arguments at all
        ["--confirm-approved-runtime"],  # still missing --seller-id
        ["--seller-id", "   ", "--confirm-approved-runtime"],  # blank seller id
        ["--seller-id", SELLER_ID],  # missing --confirm-approved-runtime
        ["--seller-id", SELLER_ID, "--confirm-approved-runtime", "--unknown"],  # unknown flag
    ],
    ids=["no-argv", "missing-seller-id", "blank-seller-id", "missing-confirm", "unknown-flag"],
)
def test_status_argv_validation_fails_before_any_db_access(argv: list[str]) -> None:
    db = _SpyStatusDb()
    with pytest.raises(SystemExit):
        status_module.main(argv, db=db)
    assert db.calls == []


def test_status_main_emits_json_report_for_valid_argv() -> None:
    collection = _StatusCollection([_marker(state="reconciled", fresh_until=NOW + HOUR)])
    payload = json.loads(
        status_module.main(
            ["--seller-id", SELLER_ID, "--confirm-approved-runtime"],
            db=collection,
        )
    )
    assert set(payload) == {"summary", "read_models"}
    assert len(payload["read_models"]) == 17
    assert payload["summary"] == {
        "fresh": 0,
        "reconciled": 1,
        "stale": 0,
        "failed": 0,
        "missing": 16,
    }
    row = next(row for row in payload["read_models"] if row["read_model"] == "orders")
    assert row["read_model"] == "orders"
    assert row["state"] == "reconciled"


# 2.5 — readiness ready/degraded + blocking; main() contract -----------------
#
# The design contract: ``ready`` is reported only when every row's
# ``action_recommended`` is ``none``; every non-``none`` action blocks
# readiness. ``main(argv, db)`` is repeatable and read-only (one read per
# run, zero writes), and the completed CLI entry returns nonzero when
# readiness is degraded or the run is anomalous, with sanitized errors.


def _productive_marker(read_model: str, **overrides: Any) -> dict[str, Any]:
    """A marker that is productive for its read model (state, window, source).

    ``main``/``run`` anchor the window with real ``datetime.now(UTC)``, so
    productive markers must be fresh relative to real now.
    """
    real_now = datetime.now(UTC)
    marker = _marker(
        read_model=read_model,
        _id=f"{SELLER_ID}:{read_model}",
        state="reconciled",
        fresh_until=real_now + HOUR,
        updated_at=real_now,
        **overrides,
    )
    if read_model in {"stock_time_metrics", "catalog_time_metrics", "full_withdrawals"}:
        marker["coverage_basis"] = "legacy_imported"
    if read_model == "devoluciones":
        marker["valid_until"] = real_now + HOUR
    return marker


def _all_productive_markers() -> list[dict[str, Any]]:
    return [_productive_marker(model) for model in ALL_READ_MODELS]


def _readiness(argv: list[str], collection: _StatusCollection) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(status_module.main(argv, db=collection)))


@pytest.mark.parametrize("readiness_flag", [["--readiness"]], ids=["with-readiness"])
def test_readiness_ready_when_all_models_productive(readiness_flag: list[str]) -> None:
    argv = ["--seller-id", SELLER_ID, "--confirm-approved-runtime", *readiness_flag]
    payload = _readiness(argv, _StatusCollection(_all_productive_markers()))
    assert payload["status"] == "ready"
    assert payload["blocking"] == []


def test_readiness_degraded_and_blocking_lists_stale_model() -> None:
    markers = _all_productive_markers()
    stale = next(marker for marker in markers if marker["read_model"] == "orders")
    stale["state"] = "stale"
    payload = _readiness(
        ["--seller-id", SELLER_ID, "--confirm-approved-runtime", "--readiness"],
        _StatusCollection(markers),
    )
    assert payload["status"] == "degraded"
    assert payload["blocking"] == ["orders"]


def test_readiness_blocking_lists_every_non_none_action_in_row_order() -> None:
    # Empty collection: every row is missing, so every non-questions action
    # is re_run_reconcile and questions is await_lease; all 17 block.
    payload = _readiness(
        ["--seller-id", SELLER_ID, "--confirm-approved-runtime", "--readiness"],
        _StatusCollection(),
    )
    assert payload["status"] == "degraded"
    assert payload["blocking"] == list(ALL_READ_MODELS)


def test_readiness_degraded_when_questions_await_lease_blocks() -> None:
    # Triangulation: await_lease blocks readiness too, not just stale/failed.
    markers = [
        marker for marker in _all_productive_markers() if marker["read_model"] != "questions"
    ]
    payload = _readiness(
        ["--seller-id", SELLER_ID, "--confirm-approved-runtime", "--readiness"],
        _StatusCollection(markers),
    )
    assert payload["status"] == "degraded"
    assert payload["blocking"] == ["questions"]


def test_readiness_keys_absent_without_readiness_flag() -> None:
    # S4 behavior preserved: plain output carries no status/blocking keys.
    payload = _readiness(
        ["--seller-id", SELLER_ID, "--confirm-approved-runtime"],
        _StatusCollection([_marker(state="stale")]),
    )
    assert set(payload) == {"summary", "read_models"}
    assert "status" not in payload and "blocking" not in payload


class _ReadWriteSpyDb:
    """Counts read (find) calls and any write-method attempt."""

    def __init__(self, documents: list[dict[str, Any]] | None = None) -> None:
        self._inner = _StatusCollection(documents)
        self.reads = 0
        self.writes = 0

    def __getitem__(self, name: str) -> _ReadWriteSpyDb:
        return self

    def find(
        self,
        filter_spec: dict[str, Any],
        projection: dict[str, int] | None = None,
    ) -> list[dict[str, Any]]:
        self.reads += 1
        return self._inner.find(filter_spec, projection)

    def update_one(self, *args: Any, **kwargs: Any) -> object:
        self.writes += 1
        return object()

    def update_many(self, *args: Any, **kwargs: Any) -> object:
        self.writes += 1
        return object()

    def insert_one(self, *args: Any, **kwargs: Any) -> object:
        self.writes += 1
        return object()

    def insert_many(self, *args: Any, **kwargs: Any) -> object:
        self.writes += 1
        return object()

    def delete_one(self, *args: Any, **kwargs: Any) -> object:
        self.writes += 1
        return object()

    def delete_many(self, *args: Any, **kwargs: Any) -> object:
        self.writes += 1
        return object()


def test_main_called_twice_reads_once_per_run_and_never_writes() -> None:
    db = _ReadWriteSpyDb(_all_productive_markers())
    argv = ["--seller-id", SELLER_ID, "--confirm-approved-runtime", "--readiness"]
    first = status_module.main(argv, db=db)
    second = status_module.main(argv, db=db)
    assert json.loads(first) == json.loads(second)  # repeatable
    assert db.reads == 2  # exactly one read per run
    assert db.writes == 0  # zero writes across both runs


def test_run_exits_zero_when_readiness_ready() -> None:
    exit_code = status_module.run(
        ["--seller-id", SELLER_ID, "--confirm-approved-runtime", "--readiness"],
        db=_StatusCollection(_all_productive_markers()),
    )
    assert exit_code == 0


def test_run_exits_nonzero_when_readiness_degraded() -> None:
    markers = _all_productive_markers()
    next(marker for marker in markers if marker["read_model"] == "orders")["state"] = "stale"
    exit_code = status_module.run(
        ["--seller-id", SELLER_ID, "--confirm-approved-runtime", "--readiness"],
        db=_StatusCollection(markers),
    )
    assert exit_code != 0


def test_run_exits_zero_without_readiness_flag_even_when_degraded() -> None:
    # Nonzero exit is tied to the readiness emission, not to degraded rows alone.
    markers = _all_productive_markers()
    next(marker for marker in markers if marker["read_model"] == "orders")["state"] = "stale"
    exit_code = status_module.run(
        ["--seller-id", SELLER_ID, "--confirm-approved-runtime"],
        db=_StatusCollection(markers),
    )
    assert exit_code == 0


class _ExplodingStatusDb:
    """Raises an anomaly carrying a secret so leak behavior is provable."""

    def __getitem__(self, name: str) -> Any:
        raise RuntimeError("connection to mongodb://user:supersecret@host:27017 failed")  # noqa: S106


def test_run_raises_sanitized_system_exit_on_anomaly() -> None:
    with pytest.raises(SystemExit) as exc_info:
        status_module.run(
            ["--seller-id", SELLER_ID, "--confirm-approved-runtime", "--readiness"],
            db=_ExplodingStatusDb(),
        )
    message = str(exc_info.value)
    assert message == "query_anomaly"
    assert "mongodb://" not in message
    assert "supersecret" not in message


# Motor-cursor regression (final-verification defect) ------------------------
#
# The runtime DB is Motor (``AsyncIOMotorClient``), whose ``find()`` returns
# an ``AsyncIOMotorCursor``: an async iterable that is deliberately NOT
# sync-iterable. The pre-fix report called ``list(cursor)``, which raises
# ``TypeError: 'AsyncIOMotorCursor' object is not iterable`` at runtime. The
# report must drain Motor cursors through an event loop while keeping the
# sync fake path and the sync ``main``/``run`` contracts unchanged.


class _AsyncStatusCursor:
    """Motor-compatible cursor: awaitable ``to_list``, ``async for``, and
    deliberately no sync ``__iter__`` (mirrors ``AsyncIOMotorCursor``)."""

    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.documents = [deepcopy(document) for document in documents]
        self._index = 0

    async def to_list(self, length: int | None = None) -> list[dict[str, Any]]:
        return [deepcopy(document) for document in self.documents]

    def __aiter__(self) -> _AsyncStatusCursor:
        self._index = 0
        return self

    async def __anext__(self) -> dict[str, Any]:
        if self._index >= len(self.documents):
            raise StopAsyncIteration
        document = self.documents[self._index]
        self._index += 1
        return deepcopy(document)


class _AsyncStatusDb:
    """Async-collection-shaped db whose ``find`` returns a Motor-shaped
    cursor; counts reads to lock the one-read-per-run contract."""

    def __init__(self, documents: list[dict[str, Any]] | None = None) -> None:
        self.documents = [deepcopy(document) for document in documents or []]
        self.reads = 0

    def __getitem__(self, name: str) -> _AsyncStatusDb:
        return self

    def find(
        self,
        filter_spec: dict[str, Any],
        projection: dict[str, int] | None = None,
    ) -> _AsyncStatusCursor:
        self.reads += 1
        return _AsyncStatusCursor(
            [document for document in self.documents if _matches(document, filter_spec)]
        )


def test_report_drains_motor_async_cursor_without_type_error() -> None:
    db = _AsyncStatusDb([_marker(state="reconciled", fresh_until=NOW + HOUR)])
    report = status_module.build_read_model_status_report(db=db, seller_id=SELLER_ID, now=NOW)
    assert len(report["read_models"]) == 17
    assert report["summary"] == {
        "fresh": 0,
        "reconciled": 1,
        "stale": 0,
        "failed": 0,
        "missing": 16,
    }
    row = _row(report, "orders")
    assert row["state"] == "reconciled"
    assert row["in_productive_window"] is True
    assert row["action_recommended"] == "none"


def test_async_cursor_report_matches_sync_cursor_report() -> None:
    markers = [
        _marker(read_model="orders", state="reconciled", fresh_until=NOW + HOUR),
        _marker(
            read_model="devoluciones",
            state="reconciled",
            fresh_until=NOW + HOUR,
            valid_until=NOW - HOUR,
        ),
        _marker(read_model="questions", source="mystery_writer"),
    ]
    sync_report = _report(_StatusCollection(markers))
    async_report = status_module.build_read_model_status_report(
        db=_AsyncStatusDb(markers), seller_id=SELLER_ID, now=NOW
    )
    assert async_report == sync_report


def test_main_with_motor_async_db_emits_readiness_json_and_reads_once() -> None:
    db = _AsyncStatusDb(_all_productive_markers())
    payload = json.loads(
        status_module.main(
            ["--seller-id", SELLER_ID, "--confirm-approved-runtime", "--readiness"],
            db=db,
        )
    )
    assert payload["status"] == "ready"
    assert payload["blocking"] == []
    assert db.reads == 1  # one read per run on the Motor-shaped path too


def test_run_with_motor_async_db_exits_zero_when_ready() -> None:
    exit_code = status_module.run(
        ["--seller-id", SELLER_ID, "--confirm-approved-runtime", "--readiness"],
        db=_AsyncStatusDb(_all_productive_markers()),
    )
    assert exit_code == 0


def test_run_with_motor_async_db_exits_nonzero_when_degraded() -> None:
    markers = _all_productive_markers()
    next(marker for marker in markers if marker["read_model"] == "orders")["state"] = "stale"
    exit_code = status_module.run(
        ["--seller-id", SELLER_ID, "--confirm-approved-runtime", "--readiness"],
        db=_AsyncStatusDb(markers),
    )
    assert exit_code != 0
