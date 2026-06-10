from __future__ import annotations

from datetime import UTC, datetime
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
