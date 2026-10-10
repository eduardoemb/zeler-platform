from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from infra.operations.sheets_dlq_archive import (
    ARCHIVE_COLLECTION,
    ARCHIVE_RECORD_ALLOWLIST,
    MODEL_FOR_EVENT_PREFIX,
    REASON_AGE_EXCEEDED,
    REASON_RESOURCE_REREAD,
    REASON_RETAINED,
    REASON_WINDOW_RECONCILED,
    REREAD_MARGIN,
    build_archive_record,
    build_archive_report,
    decide_archive,
    main,
    reread_at_from_document,
    reread_target,
)

NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)


def _message(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "event_id": "evt-0001",
        "event_type": "items.updated",
        "resource": "/items/MLM761153981",
        "seller_id": 82453304,
        "occurred_at": "2026-06-01T00:00:00Z",
        "idempotency_key": "SECRET-KEY-DO-NOT-EMIT",
        "payload": {"title": "SECRET BODY"},
    }
    base.update(overrides)
    return base


def _reconciled_until(
    seller_id: str, models: dict[str, datetime]
) -> dict[str, dict[str, datetime]]:
    return {seller_id: models}


def test_a_message_inside_a_reconciled_window_is_archived_with_that_reason() -> None:
    decision = decide_archive(
        _message(event_type="questions.new", resource="/questions/123"),
        reconciled_models_until=_reconciled_until(
            "82453304", {"questions": datetime(2026, 9, 1, tzinfo=UTC)}
        ),
        now=NOW,
    )

    assert decision.archive is True
    assert decision.reason_code == REASON_WINDOW_RECONCILED


def test_a_message_older_than_retention_is_archived_even_without_marker_evidence() -> None:
    decision = decide_archive(_message(), reconciled_models_until={}, now=NOW)

    assert decision.archive is True
    assert decision.reason_code == REASON_AGE_EXCEEDED


def test_a_recent_message_without_reconciled_evidence_is_retained() -> None:
    recent = _message(occurred_at=(NOW - timedelta(days=2)).isoformat())

    decision = decide_archive(recent, reconciled_models_until={}, now=NOW)

    assert decision.archive is False
    assert decision.reason_code == REASON_RETAINED


def test_a_recent_message_inside_a_reconciled_window_is_archived() -> None:
    recent = _message(
        event_type="questions.new",
        resource="/questions/123",
        occurred_at=(NOW - timedelta(hours=1)).isoformat(),
    )

    decision = decide_archive(
        recent,
        reconciled_models_until=_reconciled_until("82453304", {"questions": NOW}),
        now=NOW,
    )

    assert decision.archive is True
    assert decision.reason_code == REASON_WINDOW_RECONCILED


def test_a_message_for_a_different_seller_is_retained() -> None:
    """Absence of evidence for this seller is not evidence for another one."""
    other = _message(
        event_type="questions.new",
        resource="/questions/123",
        seller_id=99999999,
        occurred_at=(NOW - timedelta(days=1)).isoformat(),
    )

    decision = decide_archive(
        other,
        reconciled_models_until=_reconciled_until("82453304", {"questions": NOW}),
        now=NOW,
    )

    assert decision.archive is False
    assert decision.reason_code == REASON_RETAINED


@pytest.mark.parametrize(
    ("event_type", "resource", "marker_model"),
    [
        # No current writer publishes a reconciled item_formula_rows marker: the
        # inventory sweep finishes without one, and the marker production still
        # holds is a legacy reconciliation claim the loop never renews.
        ("items.updated", "/items/MLM1", "item_formula_rows"),
        ("items.updated", "/items/MLM1", "items"),
        # Shipments only ever get an observed-only heartbeat.
        ("shipments.updated", "/shipments/44", "shipments"),
        # A legacy date-range claim over stored snapshots, not a re-read.
        (
            "catalog_item_competition_status.updated",
            "/items/MLM1/price_to_win?version=v2",
            "catalog_buybox_snapshots",
        ),
        # The orders marker covers orders *created* in its latest window (one
        # hour for the fast sweep), and that window may end after the read.
        ("orders.updated", "/orders/55", "orders"),
    ],
)
def test_a_marker_that_does_not_prove_a_re_read_never_archives_a_message(
    event_type: str, resource: str, marker_model: str
) -> None:
    recent = _message(
        event_type=event_type,
        resource=resource,
        occurred_at=(NOW - timedelta(days=1)).isoformat(),
    )

    decision = decide_archive(
        recent,
        reconciled_models_until=_reconciled_until("82453304", {marker_model: NOW}),
        now=NOW,
    )

    assert decision == decide_archive(recent, reconciled_models_until={}, now=NOW)
    assert decision.reason_code == REASON_RETAINED


def test_only_the_questions_marker_still_authorizes_a_window_archive() -> None:
    assert dict(MODEL_FOR_EVENT_PREFIX) == {"questions": "questions"}


def test_a_resource_re_read_after_the_event_archives_a_recent_message() -> None:
    occurred = NOW - timedelta(days=2)
    recent = _message(occurred_at=occurred.isoformat())

    decision = decide_archive(
        recent,
        reconciled_models_until={},
        now=NOW,
        reread_at=occurred + REREAD_MARGIN,
    )

    assert decision.archive is True
    assert decision.reason_code == REASON_RESOURCE_REREAD


def test_a_re_read_inside_the_margin_is_not_evidence() -> None:
    """The persist clock trails the read and Mercado Libre may lag the webhook."""
    occurred = NOW - timedelta(days=2)
    recent = _message(occurred_at=occurred.isoformat())

    decision = decide_archive(
        recent,
        reconciled_models_until={},
        now=NOW,
        reread_at=occurred + REREAD_MARGIN - timedelta(seconds=1),
    )

    assert decision.archive is False
    assert decision.reason_code == REASON_RETAINED


def test_a_read_before_the_event_is_not_evidence() -> None:
    occurred = NOW - timedelta(days=2)

    decision = decide_archive(
        _message(occurred_at=occurred.isoformat()),
        reconciled_models_until={},
        now=NOW,
        reread_at=occurred - timedelta(days=1),
    )

    assert decision.reason_code == REASON_RETAINED


def test_a_read_timestamp_from_the_future_is_not_evidence() -> None:
    occurred = NOW - timedelta(days=2)

    decision = decide_archive(
        _message(occurred_at=occurred.isoformat()),
        reconciled_models_until={},
        now=NOW,
        reread_at=NOW + timedelta(minutes=1),
    )

    assert decision.reason_code == REASON_RETAINED


def test_a_re_read_without_a_parseable_event_time_is_not_evidence() -> None:
    decision = decide_archive(
        _message(occurred_at="not-a-timestamp"),
        reconciled_models_until={},
        now=NOW,
        reread_at=NOW - timedelta(hours=1),
    )

    assert decision.reason_code == REASON_RETAINED


def test_a_re_read_is_recorded_even_when_the_message_is_also_past_retention() -> None:
    """The stronger evidence wins: nothing was lost, not merely too old."""
    old = _message(occurred_at="2026-06-01T00:00:00Z")

    decision = decide_archive(
        old,
        reconciled_models_until={},
        now=NOW,
        reread_at=datetime(2026, 9, 1, tzinfo=UTC),
    )

    assert decision.reason_code == REASON_RESOURCE_REREAD


@pytest.mark.parametrize(
    ("event_type", "resource", "collection", "query", "field"),
    [
        (
            "items.updated",
            "/items/MLM761153981",
            "items",
            {"_id": "MLM761153981", "seller_id": "82453304"},
            "last_meli_sync_at",
        ),
        (
            # The worker re-reads the whole publication for a price event.
            "items.price_updated",
            "/items/MLM761153981/prices",
            "items",
            {"_id": "MLM761153981", "seller_id": "82453304"},
            "last_meli_sync_at",
        ),
        (
            "shipments.updated",
            "/shipments/44123",
            "shipments",
            {"_id": "44123", "seller_id": "82453304"},
            "formula_observed_at",
        ),
        (
            "orders.updated",
            "/orders/2000012345",
            "orders",
            {"_id": "2000012345", "seller_id": "82453304"},
            "items.sale_fee_synced_at",
        ),
        (
            "catalog_item_competition_status.updated",
            "/items/MLM761153981/price_to_win?version=v2",
            "sheets_catalog_competition_observations",
            {"seller_id": "82453304", "item_id": "MLM761153981"},
            "observed_at",
        ),
    ],
)
def test_each_re_readable_event_points_at_its_platform_read_timestamp(
    event_type: str,
    resource: str,
    collection: str,
    query: dict[str, str],
    field: str,
) -> None:
    target = reread_target(_message(event_type=event_type, resource=resource))

    assert target is not None
    assert target.collection == collection
    assert dict(target.filter) == query
    assert target.field == field
    # One bounded read: the identity filter plus a minimal projection.
    assert set(target.projection) == {field.split(".")[0]}


def test_the_latest_competition_observation_is_read_through_its_index_order() -> None:
    target = reread_target(
        _message(
            event_type="catalog_item_competition_status.updated",
            resource="/items/MLM1/price_to_win?version=v2",
        )
    )

    assert target is not None
    assert target.sort == (("observed_at", -1),)


@pytest.mark.parametrize(
    ("event_type", "resource", "seller_id"),
    [
        ("questions.new", "/questions/123", 82453304),
        ("items.updated", "/items/not-an-item", 82453304),
        ("items.updated", "/users/82453304/items/MLM1", 82453304),
        ("shipments.updated", "/shipments/abc", 82453304),
        ("orders.updated", "/orders/55/feedback", 82453304),
        ("catalog_item_competition_status.updated", "/items/MLM1", 82453304),
        ("items.updated", "/items/MLM1", None),
        ("items.updated", "/items/MLM1", "seller-x"),
        ("items.updated", None, 82453304),
    ],
)
def test_an_unrecognized_resource_or_seller_has_no_re_read_target(
    event_type: str, resource: str | None, seller_id: Any
) -> None:
    assert (
        reread_target(_message(event_type=event_type, resource=resource, seller_id=seller_id))
        is None
    )


def test_the_read_timestamp_comes_from_the_stored_document() -> None:
    target = reread_target(_message())
    assert target is not None
    synced = datetime(2026, 9, 20, 10, 0)

    # Motor returns naive UTC datetimes unless the client is tz-aware.
    assert reread_at_from_document(target, {"last_meli_sync_at": synced}) == synced.replace(
        tzinfo=UTC
    )
    assert reread_at_from_document(target, None) is None
    assert reread_at_from_document(target, {}) is None
    assert reread_at_from_document(target, {"last_meli_sync_at": "garbage"}) is None


def test_an_order_read_timestamp_is_the_latest_synced_order_line() -> None:
    target = reread_target(_message(event_type="orders.updated", resource="/orders/55"))
    assert target is not None
    first = datetime(2026, 9, 20, 10, 0, tzinfo=UTC)
    second = datetime(2026, 9, 21, 10, 0, tzinfo=UTC)

    document = {
        "items": [
            {"sale_fee_synced_at": first},
            {"item_id": "MLM1"},
            {"sale_fee_synced_at": second},
        ]
    }

    assert reread_at_from_document(target, document) == second
    assert reread_at_from_document(target, {"items": [{"item_id": "MLM1"}]}) is None
    assert reread_at_from_document(target, {"items": "corrupt"}) is None


def test_a_retention_boundary_message_is_retained() -> None:
    """Exactly at the retention edge is not yet past it."""
    edge = _message(occurred_at=(NOW - timedelta(days=30)).isoformat())

    decision = decide_archive(edge, reconciled_models_until={}, now=NOW)

    assert decision.archive is False
    assert decision.reason_code == REASON_RETAINED


def test_an_unparseable_timestamp_is_retained_rather_than_guessed() -> None:
    decision = decide_archive(
        _message(occurred_at="not-a-timestamp"), reconciled_models_until={}, now=NOW
    )

    assert decision.archive is False
    assert decision.reason_code == REASON_RETAINED


def test_archive_record_is_sanitized_and_hash_only() -> None:
    message = _message()
    decision = decide_archive(message, reconciled_models_until={}, now=NOW)

    record = build_archive_record(message, decision, now=NOW)

    assert set(record) == ARCHIVE_RECORD_ALLOWLIST
    encoded = json.dumps(record, default=str)
    assert "SECRET BODY" not in encoded
    assert "SECRET-KEY-DO-NOT-EMIT" not in encoded
    assert "MLM761153981" not in encoded
    assert "82453304" not in encoded
    assert record["reason_code"] == REASON_AGE_EXCEEDED
    assert record["event_type"] == "items.updated"
    assert record["seller_ref"].startswith("sha256:")
    assert record["resource_ref"].startswith("sha256:")
    assert record["occurred_at"] == "2026-06-01T00:00:00+00:00"


def test_archive_report_counts_by_reason_and_retains_nothing_raw() -> None:
    decisions = [
        decide_archive(_message(), reconciled_models_until={}, now=NOW),
        decide_archive(
            _message(event_id="evt-2", occurred_at=(NOW - timedelta(days=1)).isoformat()),
            reconciled_models_until={},
            now=NOW,
        ),
    ]
    records = [
        build_archive_record(_message(), decisions[0], now=NOW),
        build_archive_record(
            _message(event_id="evt-2", occurred_at=(NOW - timedelta(days=1)).isoformat()),
            decisions[1],
            now=NOW,
        ),
    ]

    report = build_archive_report(records)

    assert report["schema_version"] == 1
    assert report["summary"]["total"] == 2
    assert report["summary"]["by_reason"] == {REASON_AGE_EXCEEDED: 1, REASON_RETAINED: 1}
    assert "SECRET" not in json.dumps(report)


def test_cli_is_dry_run_only_without_explicit_write_confirmations(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"messages": [_message()]}), encoding="utf-8")

    exit_code = main(["--snapshot", str(snapshot)])

    assert exit_code == 0


def test_cli_refuses_a_write_without_both_confirmations(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"messages": [_message()]}), encoding="utf-8")

    with pytest.raises(SystemExit, match="confirmations"):
        main(["--snapshot", str(snapshot), "--write"])


def test_cli_write_requires_the_approved_runtime_and_archive_confirmations(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"messages": [_message()]}), encoding="utf-8")

    exit_code = main(
        [
            "--snapshot",
            str(snapshot),
            "--write",
            "--confirm-approved-runtime",
            "--confirm-archive",
        ]
    )

    assert exit_code == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["summary"]["by_reason"] == {REASON_AGE_EXCEEDED: 1}
    assert ARCHIVE_COLLECTION == "sheets_dlq_archives"
