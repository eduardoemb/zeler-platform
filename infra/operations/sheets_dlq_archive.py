"""Archive Sheets DLQ messages with a recorded reason (Q4-b, Q11-c).

The agreed disposition for the stuck Sheets DLQ is *archive with the reason
recorded*, not replay. This module decides that disposition from evidence
instead of from a queue name:

* a message whose seller and read model are already covered by a reconciled
  freshness marker is archived as ``window_reconciled``, because the durable
  read model already contains newer data than the message could append; and
* a message older than the retention bound is archived as ``age_exceeded``,
  because the queue is not a data store and the platform's read models do not
  depend on it.

Anything else is retained. Absence of evidence never authorizes a disposition,
and no raw payload, idempotency key, seller id or resource id leaves the
process: the record keeps hashed references plus bounded metadata only.

The CLI is dry-run first and only writes through an explicitly approved
runtime, mirroring the reconciliation surfaces.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ARCHIVE_COLLECTION = "sheets_dlq_archives"
REASON_WINDOW_RECONCILED = "window_reconciled"
REASON_AGE_EXCEEDED = "age_exceeded"
REASON_RETAINED = "retained"
RETENTION = timedelta(days=30)

# The archive record is a closed, sanitized shape. Raw payloads, idempotency
# keys, resource ids and seller ids are never members of it.
ARCHIVE_RECORD_ALLOWLIST = frozenset(
    {
        "event_type",
        "seller_ref",
        "resource_ref",
        "message_fingerprint",
        "occurred_at",
        "reason_code",
        "archived_at",
        "schema_version",
    }
)

# Read model -> the freshness marker that proves its window is reconciled.
MODEL_FOR_EVENT_PREFIX: Mapping[str, str] = {
    "orders": "orders",
    "shipments": "shipments",
    "items": "items",
    "questions": "questions",
}


@dataclass(frozen=True)
class ArchiveDecision:
    """One message's disposition plus the bounded reason that justifies it."""

    archive: bool
    reason_code: str


def decide_archive(
    message: Mapping[str, Any],
    *,
    reconciled_models_until: Mapping[str, Mapping[str, datetime]],
    now: datetime,
    retention: timedelta = RETENTION,
) -> ArchiveDecision:
    """Decide one message's disposition from reconciled coverage or its age."""
    occurred_at = _parse_timestamp(message.get("occurred_at"))
    seller = str(message.get("seller_id") or "").strip()
    event_type = str(message.get("event_type") or message.get("event") or "").strip()
    model = MODEL_FOR_EVENT_PREFIX.get(event_type.split(".")[0])
    per_seller = reconciled_models_until.get(seller) or {}
    covered_until = per_seller.get(model) if model else None
    if occurred_at is not None and covered_until is not None and _utc(covered_until) >= occurred_at:
        return ArchiveDecision(True, REASON_WINDOW_RECONCILED)
    if occurred_at is not None and now - occurred_at > retention:
        return ArchiveDecision(True, REASON_AGE_EXCEEDED)
    return ArchiveDecision(False, REASON_RETAINED)


def build_archive_record(
    message: Mapping[str, Any],
    decision: ArchiveDecision,
    *,
    now: datetime,
) -> dict[str, Any]:
    """Build the sanitized, allowlisted archive record for one message."""
    record: dict[str, Any] = {
        "schema_version": 1,
        "event_type": str(message.get("event_type") or message.get("event") or ""),
        "seller_ref": _hash_ref("seller", message.get("seller_id")),
        "resource_ref": _hash_ref("resource", message.get("resource")),
        "message_fingerprint": _hash_ref(
            "message",
            message.get("idempotency_key") or message.get("event_id") or message.get("resource"),
        ),
        "occurred_at": _iso(message.get("occurred_at")),
        "reason_code": decision.reason_code,
        "archived_at": _utc(now).isoformat(),
    }
    return {key: record[key] for key in sorted(ARCHIVE_RECORD_ALLOWLIST)}


def build_archive_report(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Emit counts by reason. Records are already sanitized."""
    by_reason = Counter(str(record.get("reason_code")) for record in records)
    return {
        "schema_version": 1,
        "dry_run": False,
        "summary": {
            "total": len(records),
            "by_reason": dict(sorted(by_reason.items())),
        },
        "items": [dict(record) for record in records],
    }


def build_archive_plan(
    messages: Sequence[Mapping[str, Any]],
    *,
    reconciled_models_until: Mapping[str, Mapping[str, datetime]],
    now: datetime,
    retention: timedelta = RETENTION,
) -> dict[str, Any]:
    """Dry-run plan: which messages would be archived and with which reason."""
    records: list[dict[str, Any]] = []
    for message in messages:
        decision = decide_archive(
            message,
            reconciled_models_until=reconciled_models_until,
            now=now,
            retention=retention,
        )
        records.append(build_archive_record(message, decision, now=now))
    report = build_archive_report(records)
    report["dry_run"] = True
    return report


def main(
    argv: Sequence[str] | None = None,
    *,
    reconciled_models_until: Mapping[str, Mapping[str, datetime]] | None = None,
    now: Callable[[], datetime] | None = None,
) -> int:
    """Dry-run by default; a write needs both runtime and archive confirmations."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.write and not (args.confirm_approved_runtime and args.confirm_archive):
        raise SystemExit(
            "explicit --confirm-approved-runtime and --confirm-archive confirmations "
            "are required for an archive write"
        )
    messages = _load_messages(args.snapshot)
    plan = build_archive_plan(
        messages,
        reconciled_models_until=reconciled_models_until or {},
        now=(now or (lambda: datetime.now(UTC)))(),
        retention=timedelta(days=args.retention_days),
    )
    plan["dry_run"] = not args.write
    print(json.dumps(plan, sort_keys=True, separators=(",", ":"), default=str))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Archive Sheets DLQ messages with a recorded reason. Dry-run by "
            "default; the CLI never contacts the broker."
        )
    )
    parser.add_argument("--snapshot", type=Path, required=True, help="DLQ snapshot JSON")
    parser.add_argument("--write", action="store_true", help="Emit the approved archive plan")
    parser.add_argument("--confirm-approved-runtime", action="store_true")
    parser.add_argument("--confirm-archive", action="store_true")
    parser.add_argument("--retention-days", type=int, default=RETENTION.days)
    return parser


def _load_messages(path: Path) -> Sequence[Mapping[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, Mapping) and isinstance(raw.get("messages"), list):
        return [message for message in raw["messages"] if isinstance(message, Mapping)]
    if isinstance(raw, list):
        return [message for message in raw if isinstance(message, Mapping)]
    return []


def _hash_ref(kind: str, value: Any) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()
    return f"sha256:{kind}:{digest}"


def _iso(value: Any) -> str | None:
    parsed = _parse_timestamp(value)
    return parsed.isoformat() if parsed is not None else None


def _parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _utc(value)
    if isinstance(value, str):
        try:
            return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


if __name__ == "__main__":
    sys.exit(main())
