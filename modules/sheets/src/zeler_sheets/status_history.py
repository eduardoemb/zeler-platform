from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any

STATUS_HISTORY_DATETIME_FIELDS = (
    "status_observed_at",
    "first_observed_at",
    "last_observed_at",
    "status_started_at",
    "paused_since",
    "last_status_change_at",
)


def bson_ms_utc_datetime(value: Any) -> datetime | None:
    aware = mongo_loaded_utc_datetime(value)
    if aware is None:
        return None
    return aware.replace(microsecond=(aware.microsecond // 1000) * 1000)


def mongo_loaded_utc_datetime(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def normalize_mongo_loaded_datetimes(value: Any) -> Any:
    normalized = mongo_loaded_utc_datetime(value)
    if normalized is not None:
        return normalized
    if isinstance(value, dict):
        return {key: normalize_mongo_loaded_datetimes(nested) for key, nested in value.items()}
    if isinstance(value, list):
        return [normalize_mongo_loaded_datetimes(nested) for nested in value]
    return value


def require_bson_ms_utc_datetime(value: datetime) -> datetime:
    normalized = bson_ms_utc_datetime(value)
    if normalized is None:
        msg = "status-history timestamp must be a datetime"
        raise TypeError(msg)
    return normalized


def normalize_status_history_datetimes(document: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(document)
    for field in STATUS_HISTORY_DATETIME_FIELDS:
        value = bson_ms_utc_datetime(normalized.get(field))
        if value is not None:
            normalized[field] = value
    current = normalized.get("current")
    if isinstance(current, dict):
        normalized["current"] = normalize_status_history_datetimes(current)
    return normalized


def effective_pause_start(current_or_state: Mapping[str, Any] | None) -> datetime | None:
    if current_or_state is None:
        return None
    record = _status_history_record(current_or_state)
    if _status_value(record) != "paused":
        return None
    return bson_ms_utc_datetime(record.get("paused_since"))


def effective_paused_days(current_or_state: Mapping[str, Any] | None, *, today: date) -> int | None:
    pause_start = effective_pause_start(current_or_state)
    if pause_start is None:
        return None
    return max((today - pause_start.date()).days, 0)


def _status_history_record(current_or_state: Mapping[str, Any]) -> Mapping[str, Any]:
    current = current_or_state.get("current")
    return current if isinstance(current, Mapping) else current_or_state


def _status_value(record: Mapping[str, Any]) -> str:
    return str(record.get("current_status") or record.get("status") or "").strip().casefold()
