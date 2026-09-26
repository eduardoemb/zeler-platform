"""A source-specific retry window for quality that Mercado Libre has not generated."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from zeler_sheets.status_history import bson_ms_utc_datetime

QUALITY_NOT_GENERATED_RETRY = timedelta(hours=1)


def quality_probe_due(probe: Any, item_updated_at: Any, *, now: datetime) -> bool:
    """A changed publication bypasses the cooldown; an unchanged one waits."""
    if not isinstance(probe, dict) or probe.get("status") != "not_generated":
        return True
    observed_version = bson_ms_utc_datetime(probe.get("item_updated_at"))
    current_version = bson_ms_utc_datetime(item_updated_at)
    next_probe = bson_ms_utc_datetime(probe.get("next_probe_at"))
    if observed_version is None or current_version is None or next_probe is None:
        return True
    return observed_version != current_version or now.astimezone(UTC) >= next_probe


def quality_probe_record(
    *, status: str, checked_at: datetime, item_updated_at: datetime
) -> dict[str, Any]:
    return {
        "status": status,
        "checked_at": checked_at,
        "next_probe_at": checked_at
        + (QUALITY_NOT_GENERATED_RETRY if status == "not_generated" else timedelta(0)),
        "item_updated_at": item_updated_at,
    }
