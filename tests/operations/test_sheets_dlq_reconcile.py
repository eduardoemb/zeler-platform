from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from infra.operations.sheets_dlq_reconcile import (
    ACTION_ALLOWLIST,
    ACTION_CAP,
    ALL_ACTIONS,
    CLASS_REPLAY_CANDIDATE,
    DLQ_CLASSES,
    MONGO_BATCH_CAP,
    MONGO_BATCH_INTERVAL_SECONDS,
    REPLAY_CONCURRENCY,
    SANITIZED_OUTPUT_ALLOWLIST,
    SNAPSHOT_CAP,
    AppendOnlyLedger,
    ApprovalError,
    DuplicateReplayError,
    LedgerAppendError,
    PublishNotConfirmedError,
    QuarantineUnavailableError,
    _build_parser,
    build_append_event,
    build_approval,
    build_dry_run_report,
    check_replay_gate,
    classify_and_sanitize_one,
    classify_message,
    hash_evidence_pointer,
    main,
    message_fingerprint,
    pre_publish_duplicate_reject,
    record_publish_success,
    reserve_publish_attempt,
    rollback_run,
    seller_ref,
    validate_action_count,
    validate_allowed_action,
    validate_approval,
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


# ---------------------------------------------------------------------------
# 3.1 Closed ACTION_ALLOWLIST per class
# ---------------------------------------------------------------------------


def test_action_allowlist_is_closed_and_matches_design() -> None:
    assert {
        "already_applied": frozenset({"terminal_close_archive"}),
        "terminal_upstream_404": frozenset({"quarantine", "terminal_close_archive"}),
        "unknown_append_outcome": frozenset({"quarantine_manual_review"}),
        "replay_candidate": frozenset({"approved_dry_run", "replay"}),
    } == ACTION_ALLOWLIST
    assert (
        frozenset(
            {
                "terminal_close_archive",
                "quarantine",
                "quarantine_manual_review",
                "approved_dry_run",
                "replay",
            }
        )
        == ALL_ACTIONS
    )


def test_validate_allowed_action_accepts_permitted_transitions() -> None:
    validate_allowed_action("already_applied", "terminal_close_archive")
    validate_allowed_action("terminal_upstream_404", "quarantine")
    validate_allowed_action("terminal_upstream_404", "terminal_close_archive")
    validate_allowed_action("unknown_append_outcome", "quarantine_manual_review")
    validate_allowed_action("replay_candidate", "approved_dry_run")
    validate_allowed_action("replay_candidate", "replay")


def test_validate_allowed_action_rejects_forbidden_transition_for_class() -> None:
    for action in ("replay", "quarantine", "quarantine_manual_review", "approved_dry_run"):
        with pytest.raises(ValueError):
            validate_allowed_action("already_applied", action)
    for action in ("replay", "terminal_close_archive", "quarantine", "approved_dry_run"):
        with pytest.raises(ValueError):
            validate_allowed_action("unknown_append_outcome", action)
    with pytest.raises(ValueError):
        validate_allowed_action("replay_candidate", "quarantine")


def test_validate_allowed_action_rejects_unknown_action_and_class() -> None:
    with pytest.raises(ValueError):
        validate_allowed_action("replay_candidate", "purge")
    with pytest.raises(ValueError):
        validate_allowed_action("replay_candidate", "delete")
    with pytest.raises(ValueError):
        validate_allowed_action("replay_candidate", "not_an_action")
    with pytest.raises(ValueError):
        validate_allowed_action("not_a_class", "replay")


# ---------------------------------------------------------------------------
# 3.2 Digest-bound approval records
# ---------------------------------------------------------------------------


def test_build_approval_contains_digest_bound_fields() -> None:
    approval = build_approval(
        classification=CLASS_REPLAY_CANDIDATE,
        action="replay",
        fingerprint="sha256:f",
        plan_digest="sha256:plan",
        actor="ops-user",
        expiry=datetime(2030, 1, 1, tzinfo=UTC),
    )
    assert approval["classification"] == "replay_candidate"
    assert approval["action"] == "replay"
    assert approval["fingerprint"] == "sha256:f"
    assert approval["plan_digest"] == "sha256:plan"
    assert approval["actor"] == "ops-user"
    assert approval["schema_version"] == 1


def test_validate_approval_accepts_valid_digest_bound_approval() -> None:
    approval = build_approval(
        classification=CLASS_REPLAY_CANDIDATE,
        action="replay",
        fingerprint="sha256:f",
        plan_digest="sha256:plan",
        actor="ops",
        expiry=datetime(2030, 1, 1, tzinfo=UTC),
    )
    validate_approval(
        approval,
        current_plan_digest="sha256:plan",
        current_classification=CLASS_REPLAY_CANDIDATE,
        current_fingerprint="sha256:f",
        now=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_validate_approval_rejects_plan_digest_mismatch() -> None:
    approval = build_approval(
        classification=CLASS_REPLAY_CANDIDATE,
        action="replay",
        fingerprint="sha256:f",
        plan_digest="sha256:plan",
        actor="ops",
        expiry=datetime(2030, 1, 1, tzinfo=UTC),
    )
    with pytest.raises(ApprovalError):
        validate_approval(
            approval,
            current_plan_digest="sha256:OTHER",
            current_classification=CLASS_REPLAY_CANDIDATE,
            current_fingerprint="sha256:f",
            now=datetime(2026, 1, 1, tzinfo=UTC),
        )


def test_validate_approval_rejects_expired_approval() -> None:
    approval = build_approval(
        classification=CLASS_REPLAY_CANDIDATE,
        action="replay",
        fingerprint="sha256:f",
        plan_digest="sha256:plan",
        actor="ops",
        expiry=datetime(2020, 1, 1, tzinfo=UTC),
    )
    with pytest.raises(ApprovalError):
        validate_approval(
            approval,
            current_plan_digest="sha256:plan",
            current_classification=CLASS_REPLAY_CANDIDATE,
            current_fingerprint="sha256:f",
            now=datetime(2026, 1, 1, tzinfo=UTC),
        )


def test_validate_approval_rejects_changed_classification() -> None:
    approval = build_approval(
        classification=CLASS_REPLAY_CANDIDATE,
        action="replay",
        fingerprint="sha256:f",
        plan_digest="sha256:plan",
        actor="ops",
        expiry=datetime(2030, 1, 1, tzinfo=UTC),
    )
    with pytest.raises(ApprovalError):
        validate_approval(
            approval,
            current_plan_digest="sha256:plan",
            current_classification="unknown_append_outcome",
            current_fingerprint="sha256:f",
            now=datetime(2026, 1, 1, tzinfo=UTC),
        )


def test_validate_approval_rejects_fingerprint_mismatch() -> None:
    approval = build_approval(
        classification=CLASS_REPLAY_CANDIDATE,
        action="replay",
        fingerprint="sha256:f",
        plan_digest="sha256:plan",
        actor="ops",
        expiry=datetime(2030, 1, 1, tzinfo=UTC),
    )
    with pytest.raises(ApprovalError):
        validate_approval(
            approval,
            current_plan_digest="sha256:plan",
            current_classification=CLASS_REPLAY_CANDIDATE,
            current_fingerprint="sha256:DIFFERENT",
            now=datetime(2026, 1, 1, tzinfo=UTC),
        )


def test_validate_approval_rejects_action_not_allowed_for_class() -> None:
    approval = build_approval(
        classification="unknown_append_outcome",
        action="replay",
        fingerprint="sha256:f",
        plan_digest="sha256:plan",
        actor="ops",
        expiry=datetime(2030, 1, 1, tzinfo=UTC),
    )
    with pytest.raises(ApprovalError):
        validate_approval(
            approval,
            current_plan_digest="sha256:plan",
            current_classification="unknown_append_outcome",
            current_fingerprint="sha256:f",
            now=datetime(2026, 1, 1, tzinfo=UTC),
        )


# ---------------------------------------------------------------------------
# 3.3 Pre-publish duplicate prevention
# ---------------------------------------------------------------------------


def test_pre_publish_duplicate_reject_allows_clean_replay() -> None:
    check_replay_gate(
        message_class=CLASS_REPLAY_CANDIDATE,
        scoped_key_present=False,
        prior_replay_success_present=False,
    )


def test_pre_publish_duplicate_reject_blocks_only_replay_candidate_publish() -> None:
    with pytest.raises(DuplicateReplayError):
        check_replay_gate(
            message_class="already_applied",
            scoped_key_present=False,
            prior_replay_success_present=False,
        )


def test_pre_publish_duplicate_reject_blocks_active_scoped_key() -> None:
    with pytest.raises(DuplicateReplayError):
        pre_publish_duplicate_reject(scoped_key_present=True, prior_replay_success_present=False)


def test_pre_publish_duplicate_reject_blocks_prior_replay_success() -> None:
    with pytest.raises(DuplicateReplayError):
        pre_publish_duplicate_reject(scoped_key_present=False, prior_replay_success_present=True)


def test_pre_publish_duplicate_reject_blocks_when_both_conditions_hold() -> None:
    with pytest.raises(DuplicateReplayError):
        check_replay_gate(
            message_class=CLASS_REPLAY_CANDIDATE,
            scoped_key_present=True,
            prior_replay_success_present=True,
        )


# ---------------------------------------------------------------------------
# 3.4 Publisher confirm + append-only ledger
# ---------------------------------------------------------------------------


def test_build_append_event_has_chain_link_fields() -> None:
    event = build_append_event(
        run_id="run-1",
        sequence=1,
        event_type="classification",
        actor="ops",
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        fingerprint="sha256:f",
        classification="replay_candidate",
        predecessor_hash="",
    )
    assert event["_id"] == "run-1:1"
    assert event["run_id"] == "run-1"
    assert event["sequence"] == 1
    assert event["event_type"] == "classification"
    assert event["predecessor_hash"] == ""
    assert event["event_hash"].startswith("sha256:")


def test_append_only_ledger_enforces_monotonic_sequence_and_hash_chain() -> None:
    ledger = AppendOnlyLedger()
    e1 = build_append_event(
        run_id="run-1",
        sequence=1,
        event_type="classification",
        actor="ops",
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        fingerprint="sha256:f",
        classification="replay_candidate",
        predecessor_hash="",
    )
    ledger.append(e1)
    e2 = build_append_event(
        run_id="run-1",
        sequence=2,
        event_type="classification",
        actor="ops",
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        fingerprint="sha256:f",
        classification="replay_candidate",
        predecessor_hash=e1["event_hash"],
    )
    ledger.append(e2)
    last = ledger.last()
    assert last is not None
    assert last["sequence"] == 2
    assert last["predecessor_hash"] == e1["event_hash"]

    # Sequence overwrite is rejected (append-only).
    with pytest.raises(LedgerAppendError):
        ledger.append(e1)


def test_append_only_ledger_rejects_broken_hash_chain() -> None:
    ledger = AppendOnlyLedger()
    e1 = build_append_event(
        run_id="run-1",
        sequence=1,
        event_type="classification",
        actor="ops",
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        fingerprint="sha256:f",
        classification="replay_candidate",
        predecessor_hash="",
    )
    ledger.append(e1)
    broken = build_append_event(
        run_id="run-1",
        sequence=2,
        event_type="classification",
        actor="ops",
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        fingerprint="sha256:f",
        classification="replay_candidate",
        predecessor_hash="tampered",
    )
    with pytest.raises(LedgerAppendError):
        ledger.append(broken)


def test_append_only_ledger_exposes_no_update_or_delete_path() -> None:
    ledger = AppendOnlyLedger()
    assert not hasattr(ledger, "update")
    assert not hasattr(ledger, "delete")
    assert {"append", "events", "last"} <= set(dir(ledger))


def test_publish_success_requires_confirm_before_ledger_append() -> None:
    ledger = AppendOnlyLedger()
    with pytest.raises(PublishNotConfirmedError):
        record_publish_success(
            confirmed=False,
            ledger=ledger,
            run_id="run-1",
            sequence=1,
            actor="ops",
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            fingerprint="sha256:f",
        )
    assert ledger.events() == []

    event = record_publish_success(
        confirmed=True,
        ledger=ledger,
        run_id="run-1",
        sequence=1,
        actor="ops",
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        fingerprint="sha256:f",
    )
    last = ledger.last()
    assert last is not None
    assert last["reason_code"] == "replay_succeeded"
    assert event["event_type"] == "action"


def test_publish_success_fails_closed_when_persistence_fails() -> None:
    class PersistFailedError(RuntimeError):
        pass

    persisted: list[Mapping[str, Any]] = []

    def failing_persist(event: Mapping[str, Any]) -> None:
        persisted.append(event)
        raise PersistFailedError("durable persistence failed")

    ledger = AppendOnlyLedger(persist=failing_persist)
    with pytest.raises(PersistFailedError):
        record_publish_success(
            confirmed=True,
            ledger=ledger,
            run_id="run-1",
            sequence=1,
            actor="ops",
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            fingerprint="sha256:f",
        )
    assert ledger.events() == []
    assert len(persisted) == 1
    assert persisted[0]["reason_code"] == "replay_succeeded"


def test_durable_reservation_blocks_retry_after_confirmed_publish_final_write_failure() -> None:
    class PersistFailedError(RuntimeError):
        pass

    durable_events: list[Mapping[str, Any]] = []

    def persist(event: Mapping[str, Any]) -> None:
        if event["reason_code"] == "replay_succeeded":
            raise PersistFailedError("durable success write failed")
        durable_events.append(dict(event))

    first_process = AppendOnlyLedger(persist=persist)
    reservation = reserve_publish_attempt(
        ledger=first_process,
        run_id="run-1",
        sequence=1,
        actor="ops",
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        fingerprint="sha256:f",
    )

    with pytest.raises(PersistFailedError):
        record_publish_success(
            confirmed=True,
            ledger=first_process,
            run_id="run-1",
            sequence=2,
            actor="ops",
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            fingerprint="sha256:f",
            predecessor_hash=reservation["event_hash"],
        )

    assert [event["reason_code"] for event in durable_events] == ["replay_publish_reserved"]
    second_process = AppendOnlyLedger(load=lambda: durable_events)
    assert second_process.events() == durable_events

    with pytest.raises(DuplicateReplayError):
        check_replay_gate(
            message_class=CLASS_REPLAY_CANDIDATE,
            scoped_key_present=False,
            prior_replay_success_present=False,
            ledger_events=second_process.events(),
            fingerprint="sha256:f",
        )


# ---------------------------------------------------------------------------
# 3.5 Fail-closed rollback / quarantine adapter
# ---------------------------------------------------------------------------


class _RecordingQuarantiner:
    def __init__(self) -> None:
        self.planned: list[str] = []
        self.available = True

    def quarantine(self, message: Mapping[str, Any]) -> str:
        if not self.available:
            raise QuarantineUnavailableError("quarantine adapter unavailable")
        self.planned.append(str(message.get("message_id")))
        return "quarantined"


def test_rollback_stops_quarantines_remainder_and_appends_event() -> None:
    ledger = AppendOnlyLedger()
    adapter = _RecordingQuarantiner()
    result = rollback_run(
        ledger=ledger,
        remaining_approved=[
            {"message_id": "m1", "classification": "terminal_upstream_404"},
            {"message_id": "m2", "classification": "terminal_upstream_404"},
        ],
        quarantiner=adapter,
        run_id="run-1",
        actor="ops",
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        sequence_base=1,
    )
    assert result["stopped_publishing"] is True
    assert result["quarantined_count"] == 2
    assert adapter.planned == ["m1", "m2"]
    last = ledger.last()
    assert last is not None
    assert last["event_type"] == "rollback"


def test_rollback_fails_closed_without_quarantine_adapter() -> None:
    ledger = AppendOnlyLedger()
    with pytest.raises(QuarantineUnavailableError):
        rollback_run(
            ledger=ledger,
            remaining_approved=[{"message_id": "m1", "classification": "terminal_upstream_404"}],
            quarantiner=None,
            run_id="run-1",
            actor="ops",
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            sequence_base=1,
        )
    assert ledger.events() == []


def test_rollback_fails_closed_when_adapter_is_unavailable() -> None:
    ledger = AppendOnlyLedger()
    adapter = _RecordingQuarantiner()
    adapter.available = False
    with pytest.raises(QuarantineUnavailableError):
        rollback_run(
            ledger=ledger,
            remaining_approved=[{"message_id": "m1", "classification": "terminal_upstream_404"}],
            quarantiner=adapter,
            run_id="run-1",
            actor="ops",
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            sequence_base=1,
        )
    assert ledger.events() == []
    assert adapter.planned == []


def test_rollback_skips_quarantine_for_class_without_disposition() -> None:
    ledger = AppendOnlyLedger()
    adapter = _RecordingQuarantiner()
    result = rollback_run(
        ledger=ledger,
        remaining_approved=[
            {"message_id": "r1", "classification": "replay_candidate"},
            {"message_id": "q1", "classification": "unknown_append_outcome"},
        ],
        quarantiner=adapter,
        run_id="run-1",
        actor="ops",
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        sequence_base=1,
    )
    assert adapter.planned == ["q1"]
    assert result["quarantined_count"] == 1
    assert result["retained_count"] == 1
    last = ledger.last()
    assert last is not None
    assert last["event_type"] == "rollback"


# ---------------------------------------------------------------------------
# 3.6 Static CLI + argparse
# ---------------------------------------------------------------------------


def test_cli_parser_declares_snapshot_and_evidence_args(tmp_path: Path) -> None:
    parser = _build_parser()
    args = parser.parse_args(["--snapshot", str(tmp_path / "s.json")])
    assert args.snapshot == tmp_path / "s.json"
    assert args.dry_run is True


def test_cli_dry_run_prints_sanitized_report(tmp_path: Path, capsys: Any) -> None:
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"messages": [_message(message_id="m1")]}), encoding="utf-8")

    rc = main(["--snapshot", str(snapshot)])

    assert rc == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["dry_run"] is True
    assert "SECRET-BODY" not in out
    assert "123456789" not in out


def test_cli_launches_no_shell_or_subprocess() -> None:
    source_path = Path(__file__).resolve().parents[2] / "infra/operations/sheets_dlq_reconcile.py"
    source = source_path.read_text(encoding="utf-8")
    assert "import subprocess" not in source
    assert "from subprocess" not in source
    assert "os.system" not in source
    assert "shell=True" not in source
    assert "Popen" not in source


# ---------------------------------------------------------------------------
# 4.1 Canonical sanitized wrapper (PR 1)
# ---------------------------------------------------------------------------


def test_classify_and_sanitize_one_matches_canonical_taxonomy_on_all_four_classes() -> None:
    cases = (
        (
            _evidence(processed_events_active=True),
            "already_applied",
            "already_applied",
            "processed_events",
        ),
        (
            _evidence(upstream_404_identity_matched=True),
            "terminal_upstream_404",
            "terminal_upstream_404",
            "broker",
        ),
        (
            _evidence(webhook_reports_append_success=True),
            "unknown_append_outcome",
            "conflicting_success_evidence",
            "webhook_events",
        ),
        (
            _evidence(
                webhook_events_valid=True,
                export_enabled=True,
                stable_key=True,
                no_append_proof=True,
            ),
            "replay_candidate",
            "replay_candidate",
            "webhook_events",
        ),
    )
    for evidence, expected_class, expected_reason, expected_source in cases:
        message = _message()
        result = classify_and_sanitize_one(message, evidence)
        verdict = classify_message(message, evidence)
        assert result == {
            "classification": verdict.classification,
            "reason_code": verdict.reason_code,
            "evidence_source": verdict.evidence_source,
        }
        assert result == {
            "classification": expected_class,
            "reason_code": expected_reason,
            "evidence_source": expected_source,
        }


def test_classify_and_sanitize_one_rejects_non_mapping_message() -> None:
    non_mappings: list[Any] = ["raw-body", ["message"], 42]
    for candidate in non_mappings:
        with pytest.raises(TypeError):
            classify_and_sanitize_one(candidate, _evidence())


def test_classify_and_sanitize_one_rejects_non_mapping_evidence() -> None:
    non_mappings: list[Any] = ["raw-evidence", ["evidence"], 42]
    for candidate in non_mappings:
        with pytest.raises(TypeError):
            classify_and_sanitize_one(_message(), candidate)


def test_classify_and_sanitize_one_empty_evidence_stays_fail_closed_unknown() -> None:
    result = classify_and_sanitize_one(_message(), {})
    assert result["classification"] == "unknown_append_outcome"
    assert result["reason_code"] == "replay_prerequisites_missing"
    assert result["evidence_source"] is None


def test_classify_and_sanitize_one_returns_only_allowlisted_fields() -> None:
    result = classify_and_sanitize_one(
        _message(),
        _evidence(
            webhook_events_valid=True,
            export_enabled=True,
            stable_key=True,
            no_append_proof=True,
        ),
    )
    assert set(result) == {"classification", "reason_code", "evidence_source"}
    assert frozenset({"classification", "reason_code", "evidence_source"}) == (
        SANITIZED_OUTPUT_ALLOWLIST
    )


def _collect_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        strings: list[str] = []
        for key, child in value.items():
            strings.extend(_collect_strings(key))
            strings.extend(_collect_strings(child))
        return strings
    if isinstance(value, (list, tuple)):
        strings = []
        for child in value:
            strings.extend(_collect_strings(child))
        return strings
    return []


def test_classify_and_sanitize_one_leaks_no_raw_payload_id_credential_or_uri() -> None:
    message = _message(
        message_id="raw-msg-f3a1",
        seller_id=82453304,
        idempotency_key="idem-super-secret-7f2b",
        payload={
            "orders": "SECRET-BODY",
            "credential": "AKIA-CREDENTIAL-SECRET",
            "url": "https://internal.example.com/x",
        },
        uri="amqp://svc:secret@broker.internal/zeler.sheets.events.dlq",
        headers={"x-auth": "header-secret"},
        evidence_document_ref="doc-ref-super-secret",
    )
    result = classify_and_sanitize_one(message, _evidence(processed_events_active=True))

    raw_markers = (
        "raw-msg-f3a1",
        "82453304",
        "idem-super-secret-7f2b",
        "SECRET-BODY",
        "AKIA-CREDENTIAL-SECRET",
        "https://internal.example.com/x",
        "amqp://svc:secret@broker.internal",
        "header-secret",
        "doc-ref-super-secret",
    )
    collected = _collect_strings(result)
    assert len(collected) >= 3
    for marker in raw_markers:
        assert all(marker not in text for text in collected)


def test_classify_and_sanitize_one_emits_nothing_to_stdout_or_stderr(capsys: Any) -> None:
    classify_and_sanitize_one(
        _message(payload={"orders": "SECRET-BODY", "credential": "AKIA-CREDENTIAL-SECRET"}),
        _evidence(),
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
