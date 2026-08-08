from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

DLQ_CLASSES = (
    "attribution_missing",
    "http_4xx",
    "http_5xx",
    "deserialization",
    "claims_unbound",
    "transient_timeout",
)
UNKNOWN_CLASS = "unknown"
REPORT_SCOPE = "sheets_claims_dlq"
DLQ_EVENT = "worker.message.dlq"
INVALID_EVIDENCE_EXIT = 65


def seller_ref(seller_id: int | str) -> str:
    """Hash a seller reference so raw seller IDs never leave the report."""
    digest = hashlib.sha256(str(seller_id).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def build_sheets_claims_dlq_report(ndjson: str) -> dict[str, Any]:
    """Aggregate DLQ structured-log lines into sanitized per-seller counts.

    Reads only ``worker.message.dlq`` events, keeps the bounded ``dlq_class``
    and a hashed seller reference, discards every payload field, and emits
    counts only. Malformed lines are counted, never printed.
    """
    sellers: dict[str, dict[str, Any]] = {}
    unattributable: dict[str, Any] = {"count": 0, "by_class": {}}
    lines_read = 0
    dlq_events = 0
    invalid_lines = 0
    skipped_lines = 0

    for line in ndjson.splitlines():
        if not line.strip():
            continue
        lines_read += 1
        try:
            record = json.loads(line)
        except (TypeError, ValueError):
            invalid_lines += 1
            continue
        if not isinstance(record, Mapping):
            invalid_lines += 1
            continue
        if record.get("event") != DLQ_EVENT:
            skipped_lines += 1
            continue
        dlq_events += 1
        dlq_class = record.get("dlq_class")
        if not isinstance(dlq_class, str) or dlq_class not in DLQ_CLASSES:
            dlq_class = UNKNOWN_CLASS
        raw_seller = record.get("seller_id")
        if isinstance(raw_seller, bool) or not isinstance(raw_seller, (int, str)):
            unattributable["count"] += 1
            _bump_class(unattributable["by_class"], dlq_class)
            continue
        bucket = sellers.setdefault(seller_ref(raw_seller), {"count": 0, "by_class": {}})
        bucket["count"] += 1
        _bump_class(bucket["by_class"], dlq_class)

    return {
        "schema_version": 1,
        "scope": REPORT_SCOPE,
        "read_only": True,
        "lines_read": lines_read,
        "dlq_events": dlq_events,
        "sellers": dict(sorted(sellers.items())),
        "unattributable": _sorted_buckets(unattributable),
        "invalid_lines": invalid_lines,
        "skipped_lines": skipped_lines,
    }


def _bump_class(by_class: dict[str, int], dlq_class: str) -> None:
    by_class[dlq_class] = by_class.get(dlq_class, 0) + 1


def _sorted_buckets(bucket: dict[str, Any]) -> dict[str, Any]:
    return {
        "count": bucket["count"],
        "by_class": dict(sorted(bucket["by_class"].items())),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only Sheets claims DLQ aggregate report (NDJSON in, counts out)."
    )
    parser.add_argument("--input", type=Path, required=True, help="Structured-log NDJSON file")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        text = args.input.read_text(encoding="utf-8", errors="replace")
        report = build_sheets_claims_dlq_report(text)
    except OSError:
        report = {
            "schema_version": 1,
            "scope": REPORT_SCOPE,
            "read_only": True,
            "status_class": "evidence_invalid",
        }
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
        return INVALID_EVIDENCE_EXIT
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
