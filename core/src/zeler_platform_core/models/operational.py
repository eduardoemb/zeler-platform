from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import AliasChoices, Field, field_validator

from zeler_platform_core.models.base import (
    MongoDocument,
    PriceMixin,
    SellerScopedDocument,
    UtcDatetimeMixin,
    _coerce_str,
)
from zeler_platform_core.models.events import BootstrapCompleted


class WebhookEvent(UtcDatetimeMixin, MongoDocument):
    topic: str
    user_id: str
    resource: str
    received_at: datetime
    published_at: datetime | None = None
    classification: str | None = None
    raw_body: dict[str, Any]
    source_ip: str

    @field_validator("user_id", mode="before")
    @classmethod
    def _coerce_user_id(cls, value: object) -> str:
        return _coerce_str(value)


class BootstrapJob(UtcDatetimeMixin, SellerScopedDocument):
    state: Literal["pending", "running", "paused", "succeeded", "failed", "cancelled"]
    dag: dict[str, str] = Field(default_factory=dict)
    checkpoints: dict[str, dict[str, Any]] = Field(default_factory=dict)
    current_stage: str | None = None
    stage_progress: dict[str, dict[str, int]] = Field(default_factory=dict)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    errors: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    def to_event(self, event_id: UUID, occurred_at: datetime) -> BootstrapCompleted:
        return BootstrapCompleted(
            event_id=event_id,
            account_id=self.seller_id,
            occurred_at=occurred_at,
            payload={"job_id": self.id, "seller_id": self.seller_id},
        )


class ModuleRegistry(UtcDatetimeMixin, MongoDocument):
    version: str
    allowed_meli_scopes: list[str] = Field(default_factory=list)
    routing_keys: list[str] = Field(default_factory=list)
    status: Literal["enabled", "disabled", "degraded"]
    last_heartbeat_at: datetime | None = None
    health: dict[str, Any] | None = None


class RepricerRule(UtcDatetimeMixin, PriceMixin, SellerScopedDocument):
    item_id: str
    strategy: Literal["min_price", "competitive", "maximize"]
    min_price: Decimal
    max_price: Decimal
    active: bool
    updated_at: datetime

    @field_validator("item_id", mode="before")
    @classmethod
    def _coerce_item_id(cls, value: object) -> str:
        return _coerce_str(value)


class RepricerHistory(UtcDatetimeMixin, PriceMixin, SellerScopedDocument):
    item_id: str
    old_price: Decimal
    new_price: Decimal
    reason: str
    applied_at: datetime

    @field_validator("item_id", mode="before")
    @classmethod
    def _coerce_item_id(cls, value: object) -> str:
        return _coerce_str(value)


class RepricerAllyAccount(UtcDatetimeMixin):
    account_id: str = Field(validation_alias=AliasChoices("account_id", "seller_id"))
    nickname: str | None = None
    item_id: str | None = None

    @field_validator("account_id", "item_id", mode="before")
    @classmethod
    def _coerce_account_fields(cls, value: object) -> object:
        if value is None:
            return None
        return _coerce_str(value)


class RepricerRuleExecutionState(UtcDatetimeMixin, PriceMixin):
    last_outcome: Literal["applied", "guard_blocked", "paused", "no_action", "error"] | None = None
    last_event_at: datetime | None = None
    last_applied_price: Decimal | None = None
    last_competitor: RepricerAllyAccount | None = None
    predominant_variant_id: str | None = None

    @field_validator("predominant_variant_id", mode="before")
    @classmethod
    def _coerce_variant_id(cls, value: object) -> object:
        if value is None:
            return None
        return _coerce_str(value)


class RepricerCatalogRule(UtcDatetimeMixin, PriceMixin, SellerScopedDocument):
    account_id: str
    item_id: str
    title: str | None = None
    sku: str | None = None
    strategy: Literal["min_price", "competitive", "maximize"]
    min_price: Decimal
    max_price: Decimal
    active: bool
    execution_state: RepricerRuleExecutionState
    created_at: datetime
    updated_at: datetime
    created_by: str
    updated_by: str

    @field_validator("account_id", "item_id", "created_by", "updated_by", mode="before")
    @classmethod
    def _coerce_catalog_fields(cls, value: object) -> str:
        return _coerce_str(value)


class RepricerLimits(UtcDatetimeMixin, PriceMixin, SellerScopedDocument):
    account_id: str
    enabled: bool
    min_price_limit: Decimal
    max_price_limit: Decimal
    undercut_delta: Decimal
    pause_competition: bool
    escalate_to_manual_review: bool
    created_at: datetime
    updated_at: datetime

    @field_validator("account_id", mode="before")
    @classmethod
    def _coerce_account_id(cls, value: object) -> str:
        return _coerce_str(value)


class RepricerAllies(UtcDatetimeMixin, SellerScopedDocument):
    allies: list[RepricerAllyAccount] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class RepricerBulkJob(UtcDatetimeMixin, SellerScopedDocument):
    account_id: str
    status: Literal[
        "draft",
        "validated",
        "processing",
        "completed",
        "completed_with_errors",
        "failed",
    ]
    source_filename: str
    total_rows: int
    processed_rows: int
    success_rows: int
    failed_rows: int
    created_at: datetime
    updated_at: datetime
    created_by: str

    @field_validator("account_id", "source_filename", "created_by", mode="before")
    @classmethod
    def _coerce_bulk_job_fields(cls, value: object) -> str:
        return _coerce_str(value)


class RepricerBulkRow(UtcDatetimeMixin, SellerScopedDocument):
    account_id: str
    job_id: str
    row_number: int
    status: Literal["validated", "queued", "processed", "failed", "skipped"]
    item_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime

    @field_validator("account_id", "job_id", "item_id", "error_code", "error_message", mode="before")
    @classmethod
    def _coerce_bulk_row_fields(cls, value: object) -> object:
        if value is None:
            return None
        return _coerce_str(value)


class RepricerReport(UtcDatetimeMixin, SellerScopedDocument):
    account_id: str
    report_type: Literal["rules_export", "history_export", "bulk_errors"]
    format: Literal["csv", "xlsx"]
    status: Literal["pending", "ready", "failed"]
    storage_path: str
    row_count: int
    created_at: datetime
    updated_at: datetime
    requested_by: str

    @field_validator("account_id", "storage_path", "requested_by", mode="before")
    @classmethod
    def _coerce_report_fields(cls, value: object) -> str:
        return _coerce_str(value)


class RepricerMonitoringSnapshot(UtcDatetimeMixin, SellerScopedDocument):
    account_id: str
    generated_at: datetime
    worker_heartbeat_at: datetime | None = None
    queue_backlog: dict[str, int] = Field(default_factory=dict)
    error_buckets: dict[str, int] = Field(default_factory=dict)
    active_bulk_job_ids: list[str] = Field(default_factory=list)

    @field_validator("account_id", mode="before")
    @classmethod
    def _coerce_monitoring_account_id(cls, value: object) -> str:
        return _coerce_str(value)

    @field_validator("active_bulk_job_ids", mode="before")
    @classmethod
    def _coerce_bulk_job_ids(cls, value: object) -> list[str]:
        if value is None:
            return []
        return [_coerce_str(item) for item in value]


class AuditLog(UtcDatetimeMixin, SellerScopedDocument):
    at: datetime
    module_id: str
    method: str
    path: str
    status: int
    duration_ms: int
    trace_id: str
