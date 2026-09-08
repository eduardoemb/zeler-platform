"""Source-bound evidence for a complete publication projection."""

from __future__ import annotations

import hashlib
from typing import Any

from bson import BSON

from zeler_sheets.status_history import bson_ms_utc_datetime


def _ordered(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _ordered(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_ordered(entry) for entry in value]
    return value


def item_source_fingerprint(item: dict[str, Any]) -> str:
    return hashlib.sha256(BSON.encode(_ordered(item))).hexdigest()


def stamp_item_projection(rows: list[dict[str, Any]], item: dict[str, Any]) -> None:
    observed = bson_ms_utc_datetime(item.get("last_meli_sync_at"))
    if observed is None or not rows:
        return
    evidence = {
        "observed_at": observed,
        "fingerprint": item_source_fingerprint(item),
        "rows_count": len(rows),
    }
    for row in rows:
        row["source_snapshot"] = dict(evidence)
