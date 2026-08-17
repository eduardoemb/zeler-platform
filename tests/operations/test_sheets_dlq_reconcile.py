from __future__ import annotations

import json
from typing import Any

import pytest
from infra.operations.sheets_dlq_reconcile import (
    ACTION_CAP,
    DLQ_CLASSES,
    MONGO_BATCH_CAP,
    MONGO_BATCH_INTERVAL_SECONDS,
    REPLAY_CONCURRENCY,
    SNAPSHOT_CAP,
    build_dry_run_report,
    classify_message,
    hash_evidence_pointer,
    message_fingerprint,
    seller_ref,
    validate_action_count,
    validate_body_size,
    validate_mongo_batch,
    validate_replay_concurrency,
    validate_replay_rate,
    validate_snapshot_size,
)


def _evidence(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "processed_events_active": False,
        "upstream_404_identity_matched": False,
        "webhook_reports_append_success": False,
        "operations_succeeded": False,
        "append_started": False,
        "evidence_missing": False,
        "evidence_malformed": False,
        "evidence_timeout": False,
        "evidence_stale": False,
        "webhook_events_valid": False,
        "export_enabled": False,
        "stable_key": False,
        "no_append_proof": False,
    }
    base.update(overrides)
    return base


def _message(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "message_id": "msg-0001",
        "idempotency_key": "evt-secret-key-0001",
        "scope_id": "sheets.events",
        "seller_id": 123456789,
        "event_type": "orders.updated",
        "payload": {"orders": "SECRET-BODY"},
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 2.1 Four-class classifier
# ---------------------------------------------------------------------------


def test_classifier_taxonomy_matches_design_contract() -> None:
    assert DLQ_CLASSES == (
        "already_applied",
        "terminal_upstream_404",
        "unknown_append_outcome",
        "replay_candidate",
    )


def test_classify_already_applied_when_scoped_key_active() -> None:
    result = classify_message(
        _message(),
        _evidence(processed_events_active=True),
    )
    assert result.classification == "already_applied"
    assert result.reason_code == "already_applied"
    assert result.evidence_source == "processed_events"


def test_classify_terminal_404_when_identity_matched() -> None:
    result = classify_message(
        _message(),
        _evidence(upstream_404_identity_matched=True),
    )
    assert result.classification == "terminal_upstream_404"
    assert result.reason_code == "terminal_upstream_404"


def test_classify_unknown_when_no_conclusive_evidence() -> None:
    result = classify_message(_message(), _evidence())
    assert result.classification == "unknown_append_outcome"
    assert result.reason_code == "replay_prerequisites_missing"


def test_classify_replay_candidate_when_all_prerequisites_met() -> None:
    result = classify_message(
        _message(),
        _evidence(
            webhook_events_valid=True,
            export_enabled=True,
            stable_key=True,
            no_append_proof=True,
        ),
    )
    assert result.classification == "replay_candidate"
    assert result.reason_code == "replay_candidate"


# ---------------------------------------------------------------------------
# 2.2 Evidence hierarchy and confirmations
# ---------------------------------------------------------------------------


def test_already_applied_beats_terminal_404_when_both_present() -> None:
    result = classify_message(
        _message(),
        _evidence(processed_events_active=True, upstream_404_identity_matched=True),
    )
    assert result.classification == "already_applied"


def test_operations_success_is_corroboration_only_not_already_applied() -> None:
    result = classify_message(
        _message(),
        _evidence(operations_succeeded=True),
    )
    assert result.classification == "unknown_append_outcome"
    assert result.reason_code == "conflicting_success_evidence"
    assert result.evidence_source == "sheets_devoluciones_operations"


def test_webhook_success_without_active_key_is_conflict_unknown() -> None:
    result = classify_message(
        _message(),
        _evidence(webhook_reports_append_success=True),
    )
    assert result.classification == "unknown_append_outcome"
    assert result.reason_code == "conflicting_success_evidence"
    assert result.evidence_source == "webhook_events"


def test_append_started_leads_to_unknown_append_outcome() -> None:
    result = classify_message(
        _message(),
        _evidence(append_started=True, no_append_proof=True),
    )
    assert result.classification == "unknown_append_outcome"
    assert result.reason_code == "inconclusive_append_evidence"


def test_missing_evidence_leads_to_unknown() -> None:
    result = classify_message(_message(), _evidence(evidence_missing=True))
    assert result.classification == "unknown_append_outcome"
    assert result.reason_code == "inconclusive_append_evidence"


def test_replay_candidate_requires_negative_append_proof() -> None:
    result = classify_message(
        _message(),
        _evidence(webhook_events_valid=True, export_enabled=True, stable_key=True),
    )
    assert result.classification == "unknown_append_outcome"
    assert result.reason_code == "replay_prerequisites_missing"


# ---------------------------------------------------------------------------
# 2.3 Sanitized dry-run output
# ---------------------------------------------------------------------------


def test_seller_ref_hashes_and_prefixes() -> None:
    expected = "sha256:" + __import__("hashlib").sha256(b"123456789").hexdigest()
    assert seller_ref(123456789) == expected
    assert seller_ref("123456789") == expected


def test_message_fingerprint_is_stable_and_salted() -> None:
    first = message_fingerprint(_message())
    second = message_fingerprint(_message())
    assert first == second
    assert first.startswith("sha256:")
    different = message_fingerprint(_message(idempotency_key="other-key"))
    assert different != first


def test_hash_evidence_pointer_is_deterministic() -> None:
    a = hash_evidence_pointer("processed_events", "doc-id-secret")
    b = hash_evidence_pointer("processed_events", "doc-id-secret")
    assert a == b
    assert a.startswith("sha256:")
    assert "doc-id-secret" not in a


def test_dry_run_report_emits_only_sanitized_fields() -> None:
    messages = [_message(message_id="msg-0001", seller_id=123456789)]

    report = build_dry_run_report(messages)

    assert report["summary"]["total"] == 1
    assert report["summary"]["by_class"] == {"unknown_append_outcome": 1}
    item = report["items"][0]
    assert item["fingerprint"].startswith("sha256:")
    assert item["seller_ref"].startswith("sha256:")
    assert item["classification"] == "unknown_append_outcome"
    assert item["reason_code"] == "replay_prerequisites_missing"

    serialized = json.dumps(report)
    assert "123456789" not in serialized
    assert "evt-secret-key-0001" not in serialized
    assert "SECRET-BODY" not in serialized
    assert "msg-0001" not in serialized
    assert "doc-id-secret" not in serialized


def test_dry_run_report_counts_by_class_across_messages() -> None:
    messages = [
        _message(message_id="m1", processed=1),
        _message(message_id="m2", processed=2),
    ]
    report = build_dry_run_report(
        messages,
        evidence_by_id={
            "m1": _evidence(processed_events_active=True),
            "m2": _evidence(
                webhook_events_valid=True,
                export_enabled=True,
                stable_key=True,
                no_append_proof=True,
            ),
        },
    )
    assert report["summary"]["by_class"] == {
        "already_applied": 1,
        "replay_candidate": 1,
    }


def test_dry_run_report_is_deterministic() -> None:
    messages = [_message(message_id="m1"), _message(message_id="m2")]
    assert json.dumps(build_dry_run_report(messages), sort_keys=True) == json.dumps(
        build_dry_run_report(messages), sort_keys=True
    )


# ---------------------------------------------------------------------------
# 2.4 Caps
# ---------------------------------------------------------------------------


def test_snapshot_cap_constant() -> None:
    assert SNAPSHOT_CAP == 10_000
    validate_snapshot_size(list(range(10_000)))
    with pytest.raises(ValueError):
        validate_snapshot_size(list(range(10_001)))


def test_action_cap_constant() -> None:
    assert ACTION_CAP == 100
    validate_action_count(100)
    with pytest.raises(ValueError):
        validate_action_count(101)


def test_mongo_batch_caps() -> None:
    assert MONGO_BATCH_CAP == 100
    assert MONGO_BATCH_INTERVAL_SECONDS == 1.0
    validate_mongo_batch(100)
    with pytest.raises(ValueError):
        validate_mongo_batch(101)


def test_replay_rate_and_concurrency_caps() -> None:
    assert REPLAY_CONCURRENCY == 1
    validate_replay_concurrency(1)
    with pytest.raises(ValueError):
        validate_replay_concurrency(2)
    validate_replay_rate(0.5)
    with pytest.raises(ValueError):
        validate_replay_rate(2.0)


def test_validate_body_size_rejects_oversize() -> None:
    validate_body_size(100, limit=200)
    with pytest.raises(ValueError):
        validate_body_size(300, limit=200)


def test_validate_body_size_defaults_to_broker_limit() -> None:
    with pytest.raises(ValueError):
        validate_body_size(10**7 + 1)
