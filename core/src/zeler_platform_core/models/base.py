from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _coerce_str(value: object) -> str:
    return str(value)


class ZelerModel(BaseModel):
    """Base model for Mongo-backed canonical documents."""

    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

    schema_version: int = 1

    @field_validator("schema_version")
    @classmethod
    def _positive_schema_version(cls, value: int) -> int:
        if value < 1:
            msg = "schema_version must be positive"
            raise ValueError(msg)
        return value


class MongoDocument(ZelerModel):
    id: str = Field(alias="_id")

    @field_validator("id", mode="before")
    @classmethod
    def _coerce_id(cls, value: object) -> str:
        return _coerce_str(value)


class TimestampedDocument(MongoDocument):
    created_at: datetime
    updated_at: datetime


class SellerScopedDocument(MongoDocument):
    seller_id: str

    @field_validator("seller_id", mode="before")
    @classmethod
    def _coerce_seller_id(cls, value: object) -> str:
        return _coerce_str(value)


class PriceMixin(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    @field_validator(
        "price",
        "base_price",
        "total_amount",
        "unit_price",
        "min_price",
        "max_price",
        "min_price_limit",
        "max_price_limit",
        "undercut_delta",
        "old_price",
        "new_price",
        "last_applied_price",
        mode="before",
        check_fields=False,
    )
    @classmethod
    def _coerce_decimal(cls, value: object) -> Decimal:
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))


def assert_aware_utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        msg = "datetime must be timezone-aware"
        raise ValueError(msg)
    return value.astimezone(UTC)


class UtcDatetimeMixin(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    @field_validator(
        "created_at",
        "updated_at",
        "expires_at",
        "refresh_token_expires_at",
        "lock_held_until",
        "last_refresh_at",
        "connected_at",
        "last_meli_sync_at",
        "date_created",
        "date_closed",
        "date_updated",
        "last_updated",
        "read_at",
        "received_at",
        "published_at",
        "started_at",
        "finished_at",
        "last_heartbeat_at",
        "applied_at",
        "at",
        "occurred_at",
        "last_event_at",
        "generated_at",
        "worker_heartbeat_at",
        "observed_at",
        "first_observed_at",
        "last_observed_at",
        "status_observed_at",
        "status_started_at",
        "paused_since",
        "last_status_change_at",
        mode="before",
        check_fields=False,
    )
    @classmethod
    def _datetime_must_be_aware(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, datetime):
            return assert_aware_utc_datetime(value)
        return value


JsonDict = dict[str, Any]


CURRENT_SCHEMA_VERSIONS: dict[str, int] = {
    "audit_log": 1,
    "bootstrap_jobs": 1,
    "claims": 1,
    "events": 1,
    "items": 2,
    "item_status_states": 1,
    "item_status_transitions": 1,
    "meli_accounts": 1,
    "messages": 1,
    "module_registry": 1,
    "orders": 1,
    "questions": 1,
    "repricer_history": 1,
    "repricer_rules": 1,
    "repricer_catalog_rules": 1,
    "repricer_limits": 1,
    "repricer_allies": 1,
    "repricer_bulk_jobs": 1,
    "repricer_bulk_rows": 1,
    "repricer_reports": 1,
    "repricer_monitoring_snapshots": 1,
    "shipments": 1,
    "users": 1,
    "webhook_events": 1,
}


def current_schema_version(entity: str) -> int:
    """Return the current schema version for a canonical collection/entity."""

    normalized = entity.lower()
    try:
        return CURRENT_SCHEMA_VERSIONS[normalized]
    except KeyError as exc:
        msg = f"unknown canonical entity: {entity}"
        raise KeyError(msg) from exc
