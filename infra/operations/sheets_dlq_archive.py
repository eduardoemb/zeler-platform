"""Archive Sheets DLQ messages with a recorded reason (Q4-b, Q11-c).

The agreed disposition for the stuck Sheets DLQ is *archive with the reason
recorded*, not replay. This module decides that disposition from evidence
instead of from a queue name:

* a message whose Mercado Libre resource the platform read again after the
  event is archived as ``resource_reread``. The event envelope carries no data:
  the worker always re-reads the resource, so a later read already holds
  everything a replay could have fetched;
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
import re
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ARCHIVE_COLLECTION = "sheets_dlq_archives"
REASON_RESOURCE_REREAD = "resource_reread"
REASON_WINDOW_RECONCILED = "window_reconciled"
REASON_AGE_EXCEEDED = "age_exceeded"
REASON_RETAINED = "retained"
RETENTION = timedelta(days=30)
# A read only proves the event's change once it is clearly after the event.
# ``occurred_at`` is when the gateway received the webhook; Mercado Libre may
# serve the change a little later, and the event path stamps the read when it
# persists, a moment after the fetch. The margin absorbs both.
REREAD_MARGIN = timedelta(minutes=15)

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

# Event prefix -> the read model whose reconciled marker proves the window.
# Only questions qualify: each question acquisition re-scans the whole marked
# window (a formula-triggered window can still end after its read; no question
# event has reached this DLQ). The others do not prove that a given resource
# was read after its event, so they are deliberately absent and rely on
# ``resource_reread``:
#
# * items: no current writer publishes a reconciled ``item_formula_rows``
#   marker. The inventory sweep finishes without one, and the marker some
#   sellers still hold is a legacy reconciliation claim the loop never renews.
# * shipments: only an ``observed_only`` heartbeat exists.
# * catalog competition: ``catalog_buybox_snapshots`` holds a legacy date-range
#   claim over stored snapshots, not a re-read of each publication.
# * orders: the marker covers orders *created* inside its latest window (one
#   hour for the fast sweep), and a formula-triggered window ends at the next
#   UTC midnight, after the read. It would archive an update to any older order.
MODEL_FOR_EVENT_PREFIX: Mapping[str, str] = {
    "questions": "questions",
}


@dataclass(frozen=True)
class RereadTarget:
    """Where the platform stamps its last read of one Mercado Libre resource.

    One bounded read answers it: ``filter`` addresses the document by identity
    (or the existing observation index), ``projection`` keeps only ``field``.
    """

    collection: str
    filter: Mapping[str, str]
    projection: Mapping[str, int]
    field: str
    sort: tuple[tuple[str, int], ...] | None = None


_ITEM_ID = r"(ML[A-Z][0-9]+)"
# Event prefix -> (resource shape, collection, platform read timestamp). Each
# timestamp is written only from a fresh Mercado Libre read, never from
# Mercado Libre's own ``last_updated``:
# * ``items.last_meli_sync_at``: the event path and every detail acquisition.
#   ``items.price_updated`` re-reads the whole publication, so it shares it.
# * ``shipments.formula_observed_at``: shipment recovery, right after the
#   detail read. Event writes keep the previous value, which only understates.
# * ``orders.items[].sale_fee_synced_at``: stamped on every order line from
#   ``/orders/{id}`` in the same replace as the order. The bootstrap stores the
#   order's own last change there, which is never later than its read.
# * ``sheets_catalog_competition_observations.observed_at``: taken before the
#   ``price_to_win`` read by both the event path and buybox recovery.
_REREAD_SOURCES: Mapping[str, tuple[re.Pattern[str], str, str]] = {
    "items": (re.compile(rf"/items/{_ITEM_ID}(?:/prices)?"), "items", "last_meli_sync_at"),
    "shipments": (re.compile(r"/shipments/([0-9]+)"), "shipments", "formula_observed_at"),
    "orders": (re.compile(r"/orders/([0-9]+)"), "orders", "items.sale_fee_synced_at"),
    "catalog_item_competition_status": (
        re.compile(rf"/items/{_ITEM_ID}/price_to_win(?:\?version=v2)?"),
        "sheets_catalog_competition_observations",
        "observed_at",
    ),
}


@dataclass(frozen=True)
class ArchiveDecision:
    """One message's disposition plus the bounded reason that justifies it."""

    archive: bool
    reason_code: str


def reread_target(message: Mapping[str, Any]) -> RereadTarget | None:
    """Locate the platform's read stamp for the message's resource, if any."""
    seller = str(message.get("seller_id") or "").strip()
    resource = message.get("resource")
    source = _REREAD_SOURCES.get(_event_type(message).split(".")[0])
    if source is None or not seller.isascii() or not seller.isdecimal():
        return None
    pattern, collection, field = source
    match = pattern.fullmatch(resource) if isinstance(resource, str) else None
    if match is None:
        return None
    identity = match.group(1)
    projection = {field.split(".")[0]: 1}
    if collection == "sheets_catalog_competition_observations":
        return RereadTarget(
            collection,
            {"seller_id": seller, "item_id": identity},
            projection,
            field,
            sort=((field, -1),),
        )
    return RereadTarget(collection, {"_id": identity, "seller_id": seller}, projection, field)


def reread_at_from_document(
    target: RereadTarget, document: Mapping[str, Any] | None
) -> datetime | None:
    """Return the latest read stamp at ``target.field``; anything else is no evidence."""
    if document is None:
        return None
    head, _, rest = target.field.partition(".")
    values = document.get(head)
    if rest:
        lines = values if isinstance(values, list) else []
        values = [line.get(rest) for line in lines if isinstance(line, Mapping)]
    else:
        values = [values]
    stamps = [_utc(value) for value in values if isinstance(value, datetime)]
    return max(stamps, default=None)


def decide_archive(
    message: Mapping[str, Any],
    *,
    reconciled_models_until: Mapping[str, Mapping[str, datetime]],
    now: datetime,
    retention: timedelta = RETENTION,
    reread_at: datetime | None = None,
) -> ArchiveDecision:
    """Decide one message's disposition from a re-read, reconciled coverage or age."""
    occurred_at = _parse_timestamp(message.get("occurred_at"))
    if (
        occurred_at is not None
        and reread_at is not None
        and occurred_at + REREAD_MARGIN <= _utc(reread_at) <= _utc(now)
    ):
        return ArchiveDecision(True, REASON_RESOURCE_REREAD)
    seller = str(message.get("seller_id") or "").strip()
    model = MODEL_FOR_EVENT_PREFIX.get(_event_type(message).split(".")[0])
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


def _event_type(message: Mapping[str, Any]) -> str:
    return str(message.get("event_type") or message.get("event") or "").strip()


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
