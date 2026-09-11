from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from infra.operations.sheets_dlq_archive import (
    ARCHIVE_COLLECTION,
    ARCHIVE_RECORD_ALLOWLIST,
    REASON_AGE_EXCEEDED,
    REASON_RETAINED,
    REASON_WINDOW_RECONCILED,
    build_archive_record,
    build_archive_report,
    decide_archive,
    main,
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
        _message(),
        reconciled_models_until=_reconciled_until(
            "82453304", {"items": datetime(2026, 9, 1, tzinfo=UTC)}
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
    recent = _message(occurred_at=(NOW - timedelta(hours=1)).isoformat())

    decision = decide_archive(
        recent,
        reconciled_models_until=_reconciled_until("82453304", {"items": NOW}),
        now=NOW,
    )

    assert decision.archive is True
    assert decision.reason_code == REASON_WINDOW_RECONCILED


def test_a_message_for_a_different_seller_is_retained() -> None:
    """Absence of evidence for this seller is not evidence for another one."""
    other = _message(seller_id=99999999, occurred_at=(NOW - timedelta(days=1)).isoformat())

    decision = decide_archive(
        other,
        reconciled_models_until=_reconciled_until("82453304", {"items": NOW}),
        now=NOW,
    )

    assert decision.archive is False
    assert decision.reason_code == REASON_RETAINED


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
