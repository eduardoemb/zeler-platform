from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

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
