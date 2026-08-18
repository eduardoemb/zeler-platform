from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

# Exact fail-closed classification taxonomy from the reconcile-sheets-dlq
# design. Every DLQ message resolves to exactly one of these classes.
DLQ_CLASSES = (
    "already_applied",
    "terminal_upstream_404",
    "unknown_append_outcome",
    "replay_candidate",
)

CLASS_ALREADY_APPLIED = "already_applied"
CLASS_TERMINAL_UPSTREAM_404 = "terminal_upstream_404"
CLASS_UNKNOWN_APPEND_OUTCOME = "unknown_append_outcome"
CLASS_REPLAY_CANDIDATE = "replay_candidate"

# Descending evidence authority per proposal and design.
EVIDENCE_ORDER = (
    "processed_events",
    "sheets_devoluciones_operations",
    "webhook_events",
    "logs",
    "broker",
    "external",
)

# Caps from proposal and spec.
SNAPSHOT_CAP = 10_000
ACTION_CAP = 100
MONGO_BATCH_CAP = 100
MONGO_BATCH_INTERVAL_SECONDS = 1.0
REPLAY_CONCURRENCY = 1
# Conservative oversize body limit in bytes; the broker's real limit is lower.
DEFAULT_BODY_SIZE_LIMIT = 10**6

UNKNOWN_REASON_NO_EVIDENCE = "replay_prerequisites_missing"


class Classification:
    """One DLQ message's fail-closed verdict."""

    __slots__ = ("classification", "reason_code", "evidence_source")

    def __init__(
        self,
        classification: str,
        reason_code: str,
        evidence_source: str | None,
    ) -> None:
        self.classification = classification
        self.reason_code = reason_code
        self.evidence_source = evidence_source


def seller_ref(seller_id: int | str) -> str:
    """Hash a seller reference so raw seller IDs never leave a report."""
    digest = hashlib.sha256(str(seller_id).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def message_fingerprint(message: Mapping[str, Any]) -> str:
    """Deterministic sanitized fingerprint of a DLQ message."""
    id_key = message.get("idempotency_key")
    digest = hashlib.sha256(str(id_key).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def hash_evidence_pointer(source: str, document_ref: Any) -> str:
    """Hash a raw evidence document reference into a pointer for reports."""
    digest = hashlib.sha256(str(document_ref).encode("utf-8")).hexdigest()
    return f"sha256:{source}:{digest}"


def classify_message(message: Mapping[str, Any], evidence: Mapping[str, Any]) -> Classification:
    """Resolve one message to its fail-closed class using the evidence hierarchy.

    Precedence follows the design: an active exact scoped ``processed_events``
    key beats everything (``already_applied``); then an identity-matched
    sanitized upstream 404 (``terminal_upstream_404``); then missing, stale,
    malformed, conflicting, timeout, or possible append-started evidence
    (``unknown_append_outcome``); and only then a ``replay_candidate`` when
    every prerequisite holds with affirmative proof no append succeeded.
    """
    if evidence.get("processed_events_active"):
        return Classification(
            CLASS_ALREADY_APPLIED,
            CLASS_ALREADY_APPLIED,
            "processed_events",
        )

    if evidence.get("upstream_404_identity_matched"):
        return Classification(
            CLASS_TERMINAL_UPSTREAM_404,
            CLASS_TERMINAL_UPSTREAM_404,
            "broker",
        )

    # Lower-authority success evidence without an active idempotency key is a
    # conflict: operations success is corroboration only because the handler
    # finishes the operation before the Sheets append.
    if evidence.get("webhook_reports_append_success"):
        return Classification(
            CLASS_UNKNOWN_APPEND_OUTCOME,
            "conflicting_success_evidence",
            "webhook_events",
        )
    if evidence.get("operations_succeeded"):
        return Classification(
            CLASS_UNKNOWN_APPEND_OUTCOME,
            "conflicting_success_evidence",
            "sheets_devoluciones_operations",
        )

    if _append_outcome_inconclusive(evidence):
        return Classification(
            CLASS_UNKNOWN_APPEND_OUTCOME,
            "inconclusive_append_evidence",
            _inconclusive_source(evidence),
        )

    if _is_replay_candidate(evidence):
        return Classification(
            CLASS_REPLAY_CANDIDATE,
            CLASS_REPLAY_CANDIDATE,
            "webhook_events",
        )

    return Classification(
        CLASS_UNKNOWN_APPEND_OUTCOME,
        UNKNOWN_REASON_NO_EVIDENCE,
        None,
    )


# Closed set of verdict fields the canonical wrapper may emit. Everything
# beyond these three values must be derived (for example, hashed) separately;
# raw payloads, ids, credentials, and URIs never cross this boundary.
SANITIZED_OUTPUT_ALLOWLIST = frozenset({"classification", "reason_code", "evidence_source"})


def classify_and_sanitize_one(
    message: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, str | None]:
    """Classify one raw message through the canonical taxonomy and sanitize it.

    Rejects non-mappings so raw structures never reach the verdict path.
    Always delegates to :func:`classify_message` so the four-class taxonomy
    cannot drift. Returns only allowlisted verdict fields; with no in-process
    evidence, passing an empty mapping preserves the fail-closed unknown
    classification.
    """
    if not isinstance(message, Mapping):
        raise TypeError(f"message must be a mapping, got {type(message).__name__}")
    if not isinstance(evidence, Mapping):
        raise TypeError(f"evidence must be a mapping, got {type(evidence).__name__}")
    verdict = classify_message(message, evidence)
    return {
        "classification": verdict.classification,
        "reason_code": verdict.reason_code,
        "evidence_source": verdict.evidence_source,
    }


def _append_outcome_inconclusive(evidence: Mapping[str, Any]) -> bool:
    return any(
        evidence.get(flag)
        for flag in (
            "append_started",
            "evidence_missing",
            "evidence_malformed",
            "evidence_timeout",
            "evidence_stale",
        )
    )


def _inconclusive_source(evidence: Mapping[str, Any]) -> str:
    for flag, source in (
        ("append_started", "webhook_events"),
        ("evidence_stale", "logs"),
        ("evidence_malformed", "logs"),
        ("evidence_timeout", "broker"),
        ("evidence_missing", None),
    ):
        if evidence.get(flag):
            return source if source is not None else "processed_events"
    return "processed_events"


def _is_replay_candidate(evidence: Mapping[str, Any]) -> bool:
    return bool(
        evidence.get("webhook_events_valid")
        and evidence.get("export_enabled")
        and evidence.get("stable_key")
        and evidence.get("no_append_proof")
    )


def build_dry_run_report(
    messages: Sequence[Mapping[str, Any]],
    *,
    evidence_by_id: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Emit a sanitized dry-run plan: counts plus hashed/fingerprinted fields.

    Output contains only counts, hashed seller references, message
    fingerprints, class, reason codes, and hashed evidence pointers. Raw
    payloads, seller IDs, document references, idempotency keys, and message
    ids never leave this function.
    """
    evidence_by_id = evidence_by_id or {}
    items: list[dict[str, Any]] = []
    by_class: dict[str, int] = {}

    for message in messages:
        message_id = message.get("message_id")
        key = message_id if message_id is not None else message_fingerprint(message)
        evidence = evidence_by_id.get(key, {})
        verdict = classify_message(message, evidence)
        by_class[verdict.classification] = by_class.get(verdict.classification, 0) + 1
        items.append(_sanitized_item(message, verdict, evidence))

    return {
        "schema_version": 1,
        "dry_run": True,
        "summary": {
            "total": len(messages),
            "by_class": dict(sorted(by_class.items())),
        },
        "items": items,
    }


def _sanitized_item(
    message: Mapping[str, Any],
    verdict: Classification,
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "fingerprint": message_fingerprint(message),
        "seller_ref": seller_ref(message["seller_id"]),
        "classification": verdict.classification,
        "reason_code": verdict.reason_code,
    }
    evidence_pointers = _evidence_pointers(evidence)
    if evidence_pointers:
        item["evidence_pointers"] = list(sorted(evidence_pointers))
    return item


def _evidence_pointers(evidence: Mapping[str, Any]) -> list[str]:
    pointers: list[str] = []
    document_ref = evidence.get("evidence_document_ref")
    if document_ref is not None:
        pointers.append(hash_evidence_pointer("evidence", document_ref))
    return pointers


# ---------------------------------------------------------------------------
# Caps
# ---------------------------------------------------------------------------


def validate_snapshot_size(messages: Sequence[Any]) -> None:
    if len(messages) > SNAPSHOT_CAP:
        raise ValueError(f"snapshot exceeds cap: {len(messages)} > {SNAPSHOT_CAP} messages")


def validate_action_count(count: int) -> None:
    if count > ACTION_CAP:
        raise ValueError(f"action count exceeds cap: {count} > {ACTION_CAP}")


def validate_mongo_batch(write_count: int) -> None:
    if write_count > MONGO_BATCH_CAP:
        raise ValueError(f"mongo batch exceeds cap: {write_count} > {MONGO_BATCH_CAP} writes")


def validate_replay_concurrency(concurrency: int) -> None:
    if concurrency > REPLAY_CONCURRENCY:
        raise ValueError(f"replay concurrency exceeds cap: {concurrency} > {REPLAY_CONCURRENCY}")


def validate_replay_rate(messages_per_second: float) -> None:
    if messages_per_second >= 1.0:
        raise ValueError(f"replay rate must be <1 msg/s, got {messages_per_second}")


def validate_body_size(body_size: int, *, limit: int | None = None) -> None:
    effective_limit = limit if limit is not None else DEFAULT_BODY_SIZE_LIMIT
    if body_size > effective_limit:
        raise ValueError(f"body exceeds size limit: {body_size} > {effective_limit} bytes")


# ---------------------------------------------------------------------------
# 3.1 Closed ACTION_ALLOWLIST per class
# ---------------------------------------------------------------------------

# Closed action taxonomy from the design's Interfaces / Contracts table. The
# mapping is immutable by construction (frozenset values) so no forged action
# can ever be admitted outside the explicit transitions below.
ALL_ACTIONS = frozenset(
    {
        "terminal_close_archive",
        "quarantine",
        "quarantine_manual_review",
        "approved_dry_run",
        "replay",
    }
)

ACTION_ALLOWLIST: Mapping[str, frozenset[str]] = {
    CLASS_ALREADY_APPLIED: frozenset({"terminal_close_archive"}),
    CLASS_TERMINAL_UPSTREAM_404: frozenset({"quarantine", "terminal_close_archive"}),
    CLASS_UNKNOWN_APPEND_OUTCOME: frozenset({"quarantine_manual_review"}),
    CLASS_REPLAY_CANDIDATE: frozenset({"approved_dry_run", "replay"}),
}


def validate_allowed_action(classification: str, action: str) -> None:
    """Fail closed unless ``action`` is an explicitly allowed transition.

    Unknown actions, unknown classifications, and skipped/forbidden
    transitions all raise ``ValueError``. No default or best-effort path.
    """
    if action not in ALL_ACTIONS:
        raise ValueError(f"unknown action: {action}")
    allowed = ACTION_ALLOWLIST.get(classification)
    if allowed is None:
        raise ValueError(f"unknown classification: {classification}")
    if action not in allowed:
        raise ValueError(f"forbidden transition: {classification} -> {action}")


# ---------------------------------------------------------------------------
# 3.2 Digest-bound approval records
# ---------------------------------------------------------------------------


class ApprovalError(ValueError):
    """An approval is missing, stale, mismatched, or not authorized."""


def build_approval(
    *,
    classification: str,
    action: str,
    fingerprint: str,
    plan_digest: str,
    actor: str,
    expiry: datetime,
    predecessor_hash: str = "",
) -> dict[str, Any]:
    """Build a digest-bound approval record.

    The approval binds the exact plan digest, message fingerprint,
    classification, and action, and carries an expiry and actor. It is the
    only artifact that may later authorize a mutation, and only when every
    bound field still matches at execution time.
    """
    return {
        "classification": classification,
        "action": action,
        "fingerprint": fingerprint,
        "plan_digest": plan_digest,
        "actor": actor,
        "expiry": expiry,
        "predecessor_hash": predecessor_hash,
        "schema_version": 1,
    }


def validate_approval(
    approval: Mapping[str, Any],
    *,
    current_plan_digest: str,
    current_classification: str,
    current_fingerprint: str,
    now: datetime,
) -> None:
    """Fail closed unless the approval is unexpired and fully bound.

    Digest mismatch, expired approval, changed classification, changed
    message fingerprint, an unknown action, or an action not allowed for the
    current classification all raise :class:`ApprovalError`.
    """
    if approval.get("plan_digest") != current_plan_digest:
        raise ApprovalError("approval plan digest mismatch")
    if approval.get("classification") != current_classification:
        raise ApprovalError("approval classification changed")
    if approval.get("fingerprint") != current_fingerprint:
        raise ApprovalError("approval message fingerprint mismatch")
    action = approval.get("action")
    if action not in ALL_ACTIONS:
        raise ApprovalError("approval carries unknown action")
    allowed = ACTION_ALLOWLIST.get(current_classification, frozenset())
    if action not in allowed:
        raise ApprovalError("approval action not allowed for current classification")
    expiry = approval.get("expiry")
    if expiry is None or expiry <= now:
        raise ApprovalError("approval expired")


# ---------------------------------------------------------------------------
# 3.3 Pre-publish duplicate prevention
# ---------------------------------------------------------------------------


class DuplicateReplayError(RuntimeError):
    """A replay must not publish: the message was already applied/replayed."""


def pre_publish_duplicate_reject(
    *,
    scoped_key_present: bool,
    prior_replay_success_present: bool,
    prior_replay_attempt_present: bool = False,
) -> None:
    """Fail closed if the exact scoped key or a prior replay state exists."""
    if scoped_key_present or prior_replay_success_present or prior_replay_attempt_present:
        raise DuplicateReplayError(
            "replay blocked: active scoped idempotency key, prior replay-success, "
            "or unreconciled replay reservation present"
        )


def check_replay_gate(
    message_class: str,
    *,
    scoped_key_present: bool,
    prior_replay_success_present: bool,
    ledger_events: Sequence[Mapping[str, Any]] = (),
    fingerprint: str | None = None,
) -> None:
    """Authorize replay only for ``replay_candidate`` with no duplicate proof.

    The durable ledger is checked for prior successes and pending publish
    reservations. A reservation remains blocking if the publisher confirms but
    the subsequent success event cannot be durably recorded.
    """
    if message_class != CLASS_REPLAY_CANDIDATE:
        raise DuplicateReplayError(f"only replay_candidate may publish replay, got {message_class}")
    pre_publish_duplicate_reject(
        scoped_key_present=scoped_key_present,
        prior_replay_success_present=prior_replay_success_present,
        prior_replay_attempt_present=has_blocking_replay_ledger_event(
            ledger_events,
            fingerprint=fingerprint,
        ),
    )


# ---------------------------------------------------------------------------
# 3.4 Publisher confirm + append-only ledger
# ---------------------------------------------------------------------------

LEDGER_EVENT_TYPES = ("classification", "approval", "action", "rollback")
LEDGER_SCHEMA_VERSION = 1
REPLAY_RESERVATION_REASON = "replay_publish_reserved"
REPLAY_SUCCESS_REASON = "replay_succeeded"
REPLAY_RECONCILIATION_REASON = "replay_reconciled_no_publish"


class LedgerAppendError(RuntimeError):
    """The append-only ledger rejected an out-of-order or tampered append."""


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=_json_default).encode(
        "utf-8"
    )


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def ledger_event_hash(payload: Mapping[str, Any]) -> str:
    """Deterministic sha256-based hash over canonical event content."""
    digest = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    return f"sha256:{digest}"


def build_append_event(
    *,
    run_id: str,
    sequence: int,
    event_type: str,
    actor: str,
    occurred_at: datetime,
    fingerprint: str,
    message_id: str | None = None,
    seller_ref_hash: str | None = None,
    classification: str | None = None,
    reason_code: str | None = None,
    evidence: Sequence[str] = (),
    predecessor_hash: str = "",
    schema_version: int = LEDGER_SCHEMA_VERSION,
) -> dict[str, Any]:
    """Build one immutable ledger event.

    ``event_hash`` is computed over the deterministic serialized content but
    excludes the mutable timestamp and the ``_id``; ``predecessor_hash`` links
    each event into an unforgeable hash chain.
    """
    event: dict[str, Any] = {
        "_id": f"{run_id}:{sequence}",
        "run_id": run_id,
        "sequence": sequence,
        "event_type": event_type,
        "actor": actor,
        "occurred_at": occurred_at,
        "fingerprint": fingerprint,
        "message_id": message_id,
        "seller_ref": seller_ref_hash,
        "classification": classification,
        "reason_code": reason_code,
        "evidence": list(evidence),
        "predecessor_hash": predecessor_hash,
        "schema_version": schema_version,
    }
    hashed_content = {
        key: value for key, value in event.items() if key not in ("_id", "occurred_at")
    }
    event["event_hash"] = ledger_event_hash(hashed_content)
    return event


class AppendOnlyLedger:
    """In-memory immutable ledger with a strict append-only write path.

    Supports only ``append`` (writes) plus read helpers (``events``,
    ``last``). There is intentionally no update or delete method.
    """

    def __init__(
        self,
        persist: Callable[[Mapping[str, Any]], None] | None = None,
        load: Callable[[], Sequence[Mapping[str, Any]]] | None = None,
    ) -> None:
        self._store = [dict(event) for event in load()] if load is not None else []
        self._persist = persist

    def append(self, event: Mapping[str, Any]) -> None:
        if self._store:
            previous = self._store[-1]
            if event["sequence"] <= previous["sequence"]:
                raise LedgerAppendError("append-only ledger: sequence must strictly increase")
            if event["predecessor_hash"] != previous["event_hash"]:
                raise LedgerAppendError("append-only ledger: broken hash chain")
        elif event["predecessor_hash"] != "":
            raise LedgerAppendError("append-only ledger: first event must have empty predecessor")
        stored = dict(event)
        if self._persist is not None:
            self._persist(stored)
        self._store.append(stored)

    def events(self) -> list[dict[str, Any]]:
        return list(self._store)

    def last(self) -> dict[str, Any] | None:
        return self._store[-1] if self._store else None


class PublishNotConfirmedError(RuntimeError):
    """Publish was not confirmed, so no ack or success-ledger append may run."""


def has_blocking_replay_ledger_event(
    events: Sequence[Mapping[str, Any]],
    *,
    fingerprint: str | None,
) -> bool:
    """Return whether durable replay history blocks a new publish.

    A reservation is a durable record that publishing might occur. It remains
    blocking after a process restart unless an explicit reconciliation event
    proves no publish occurred. A success event is always blocking.
    """
    blocked = False
    for event in events:
        if fingerprint is not None and event.get("fingerprint") != fingerprint:
            continue
        reason_code = event.get("reason_code")
        if reason_code in (REPLAY_RESERVATION_REASON, REPLAY_SUCCESS_REASON):
            blocked = True
        elif reason_code == REPLAY_RECONCILIATION_REASON:
            blocked = False
    return blocked


def reserve_publish_attempt(
    *,
    ledger: AppendOnlyLedger,
    run_id: str,
    sequence: int,
    actor: str,
    occurred_at: datetime,
    fingerprint: str,
    classification: str = CLASS_REPLAY_CANDIDATE,
    predecessor_hash: str = "",
) -> dict[str, Any]:
    """Durably reserve a replay attempt before invoking the publisher.

    ``ledger.append`` persists before returning. Callers must not publish if it
    raises. If publisher confirmation succeeds but final success persistence
    fails, this immutable reservation remains a fail-closed replay blocker.
    """
    event = build_append_event(
        run_id=run_id,
        sequence=sequence,
        event_type="action",
        actor=actor,
        occurred_at=occurred_at,
        fingerprint=fingerprint,
        classification=classification,
        reason_code=REPLAY_RESERVATION_REASON,
        predecessor_hash=predecessor_hash,
    )
    ledger.append(event)
    return event


def record_publish_success(
    *,
    confirmed: bool,
    ledger: AppendOnlyLedger,
    run_id: str,
    sequence: int,
    actor: str,
    occurred_at: datetime,
    fingerprint: str,
    classification: str = CLASS_REPLAY_CANDIDATE,
    predecessor_hash: str = "",
) -> dict[str, Any]:
    """Append a replay-success ledger event only after publisher confirm.

    Without ``confirmed`` the call fails closed and appends nothing, so an
    unconfirmed publish is never acknowledged nor recorded as successful. The
    caller must reserve the attempt durably before publishing; a failed final
    append then leaves that reservation as the cross-process replay blocker.
    """
    if not confirmed:
        raise PublishNotConfirmedError(
            "publisher confirm required before ack or success-ledger append"
        )
    event = build_append_event(
        run_id=run_id,
        sequence=sequence,
        event_type="action",
        actor=actor,
        occurred_at=occurred_at,
        fingerprint=fingerprint,
        classification=classification,
        reason_code=REPLAY_SUCCESS_REASON,
        predecessor_hash=predecessor_hash,
    )
    ledger.append(event)
    return event


# ---------------------------------------------------------------------------
# 3.5 Fail-closed rollback / quarantine adapter
# ---------------------------------------------------------------------------


class QuarantineUnavailableError(RuntimeError):
    """The approved quarantine disposition adapters is not usable."""


class QuarantineDispositionAdapter(Protocol):
    def quarantine(self, message: Mapping[str, Any]) -> str: ...


_QUARANTINE_ACTIONS = frozenset({"quarantine", "quarantine_manual_review"})


def _quarantine_action_for(classification: str) -> str | None:
    for allowed in ACTION_ALLOWLIST.get(classification, frozenset()):
        if allowed in _QUARANTINE_ACTIONS:
            return allowed
    return None


def rollback_run(
    *,
    ledger: AppendOnlyLedger,
    remaining_approved: Sequence[Mapping[str, Any]],
    quarantiner: QuarantineDispositionAdapter | None,
    run_id: str,
    actor: str,
    occurred_at: datetime,
    sequence_base: int,
) -> dict[str, Any]:
    """Stop publishing, quarantine the remaining items, and append rollback.

    Fail-closed: without a usable quarantine adapter the rollback raises
    :class:`QuarantineUnavailableError` and appends nothing, leaving source
    messages untouched. Only classes that hold an approved quarantine action
    are passed to the adapter; others are recorded as retained.
    """
    if quarantiner is None:
        raise QuarantineUnavailableError(
            "rollback fail-closed: no quarantine disposition adapter bound"
        )

    sequence = sequence_base
    quarantined = 0
    retained = 0
    for item in remaining_approved:
        classification = item.get("classification", CLASS_REPLAY_CANDIDATE)
        action = _quarantine_action_for(classification)
        if action is None:
            retained += 1
            continue
        try:
            quarantiner.quarantine(item)
        except Exception as exc:
            raise QuarantineUnavailableError(f"quarantine adapter unavailable: {exc}") from exc
        quarantined += 1
        sequence += 1
        previous = ledger.last()
        predecessor = previous["event_hash"] if previous is not None else ""
        ledger.append(
            build_append_event(
                run_id=run_id,
                sequence=sequence,
                event_type="action",
                actor=actor,
                occurred_at=occurred_at,
                fingerprint="",
                classification=classification,
                reason_code="quarantined_on_rollback",
                predecessor_hash=predecessor,
            )
        )

    sequence += 1
    previous = ledger.last()
    predecessor = previous["event_hash"] if previous is not None else ""
    rollback_event = build_append_event(
        run_id=run_id,
        sequence=sequence,
        event_type="rollback",
        actor=actor,
        occurred_at=occurred_at,
        fingerprint="",
        reason_code="rollback_requested",
        predecessor_hash=predecessor,
    )
    ledger.append(rollback_event)
    return {
        "stopped_publishing": True,
        "quarantined_count": quarantined,
        "retained_count": retained,
        "rollback_event": rollback_event,
    }


# ---------------------------------------------------------------------------
# 3.6 Static dry-run CLI (snapshot/dry-run only, no shell/subprocess)
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only, dry-run-first Sheets DLQ reconciliation. Loads a capped "
            "snapshot plus optional evidence and emits a sanitized plan. "
            "Launches no shell or subprocess and performs no publish."
        )
    )
    parser.add_argument("--snapshot", type=Path, required=True, help="DLQ snapshot JSON")
    parser.add_argument(
        "--evidence",
        type=Path,
        help="Optional evidence JSON keyed by message id",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Emit a sanctioned dry-run plan only (the only supported mode)",
    )
    return parser


def _load_messages(path: Path) -> Sequence[Mapping[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, Mapping) and isinstance(raw.get("messages"), list):
        return [message for message in raw["messages"] if isinstance(message, Mapping)]
    if isinstance(raw, list):
        return [message for message in raw if isinstance(message, Mapping)]
    return []


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    messages = _load_messages(args.snapshot)
    validate_snapshot_size(messages)
    evidence_by_id: dict[str, Mapping[str, Any]] = {}
    if args.evidence is not None:
        evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
        if isinstance(evidence, Mapping):
            evidence_by_id = {
                str(key): value for key, value in evidence.items() if isinstance(value, Mapping)
            }
    report = build_dry_run_report(messages, evidence_by_id=evidence_by_id)
    print(json.dumps(report, sort_keys=True, separators=(",", ":"), default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
