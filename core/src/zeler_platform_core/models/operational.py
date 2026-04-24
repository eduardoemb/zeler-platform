from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, field_validator

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


class AuditLog(UtcDatetimeMixin, SellerScopedDocument):
    at: datetime
    module_id: str
    method: str
    path: str
    status: int
    duration_ms: int
    trace_id: str
