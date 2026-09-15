from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from zeler_platform_core.models.base import assert_aware_utc_datetime

NonEmptyText = Annotated[str, Field(min_length=1, pattern=r"\S")]
NonNegativeCount = Annotated[int, Field(ge=0)]
PositiveCount = Annotated[int, Field(ge=1)]


class SheetsHistoryAcquisition(BaseModel):
    """Metadata validation only; ownership and coverage require the fenced store."""

    model_config = ConfigDict(strict=True, extra="forbid", populate_by_name=True)

    id: NonEmptyText = Field(alias="_id")
    seller_id: Annotated[str, Field(pattern=r"^[0-9]+$")]
    plan_id: NonEmptyText
    scope_id: NonEmptyText
    job_id: NonEmptyText
    schema_version: int = Field(default=1, ge=1, le=1)
    read_model: Literal["orders", "questions"]
    date_from: datetime
    date_to: datetime
    generation: PositiveCount = 1
    pass_number: PositiveCount = 1
    checkpoint_revision: NonNegativeCount = 0
    page_sequence: NonNegativeCount = 0
    phase: Literal["discover", "hydrate", "verify", "publish", "completed"] = "discover"
    next_cursor: NonNegativeCount | NonEmptyText | None = None
    active_range_id: NonEmptyText | None = None
    source_total: NonNegativeCount | None = None
    discovered_count: NonNegativeCount = 0
    fetched_count: NonNegativeCount = 0
    published_count: NonNegativeCount = 0
    drift_restarts: int = Field(default=0, ge=0, le=3)
    publish_after: NonEmptyText | None = None
    observed_from: datetime | None = None
    observed_until: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @field_validator(
        "date_from", "date_to", "observed_from", "observed_until", "created_at", "updated_at"
    )
    @classmethod
    def _normalize_dates(cls, value: datetime | None) -> datetime | None:
        return None if value is None else assert_aware_utc_datetime(value)

    @model_validator(mode="after")
    def _validate_contract(self) -> Self:
        if self.date_from >= self.date_to:
            raise ValueError("history bounds must be positive")
        if self.read_model == "orders":
            if re.fullmatch(r"orders:[0-9]{8}:[0-9]{8}", self.scope_id) is None:
                raise ValueError("orders require a monthly chunk identity")
            if self.date_to - self.date_from > timedelta(days=90):
                raise ValueError("order intervals cannot exceed 90 days")
            if self.next_cursor is not None and not isinstance(self.next_cursor, int):
                raise ValueError("order cursor must be an offset")
        elif self.scope_id != "seller_scan" or (
            self.next_cursor is not None and not isinstance(self.next_cursor, str)
        ):
            raise ValueError("questions require seller_scan scope and a scan cursor")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        if (self.observed_from is None) != (self.observed_until is None):
            raise ValueError("observation bounds must be supplied together")
        if (
            self.observed_from is not None
            and self.observed_until is not None
            and self.observed_until < self.observed_from
        ):
            raise ValueError("observation bounds must be ordered")
        if not self.published_count <= self.fetched_count <= self.discovered_count:
            raise ValueError("publication and fetch counts cannot exceed their prerequisites")
        if (self.published_count == 0) != (self.publish_after is None):
            raise ValueError("publication checkpoint must correspond to publication progress")
        if self.phase == "completed" and (
            self.observed_from is None
            or self.source_total is None
            or self.next_cursor is not None
            or self.published_count != self.fetched_count
        ):
            raise ValueError("completed acquisition requires final local bookkeeping")
        return self


class SheetsHistoryOrderRange(BaseModel):
    """Range bookkeeping only; parent binding and atomic scheduling belong to the store."""

    model_config = ConfigDict(strict=True, extra="forbid", populate_by_name=True)

    id: NonEmptyText = Field(alias="_id")
    acquisition_id: NonEmptyText
    seller_id: Annotated[str, Field(pattern=r"^[0-9]+$")]
    schema_version: int = Field(default=1, ge=1, le=1)
    generation: PositiveCount
    pass_number: PositiveCount
    node_id: NonEmptyText
    root_id: NonEmptyText
    parent_id: NonEmptyText | None = None
    date_from: datetime
    date_to: datetime
    depth: int = Field(default=0, ge=0, le=12)
    state: Literal["pending", "split", "enumerated"] = "pending"
    source_total: NonNegativeCount | None = None
    next_offset: NonNegativeCount = 0

    @field_validator("date_from", "date_to")
    @classmethod
    def normalize_dates(cls, value: datetime) -> datetime:
        return assert_aware_utc_datetime(value)

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if not timedelta(0) < self.date_to - self.date_from <= timedelta(days=90):
            raise ValueError("range requires positive bounds of at most 90 days")
        if (self.depth == 0) != (self.parent_id is None):
            raise ValueError("depth and parent linkage disagree")
        if self.depth == 0 and self.node_id != self.root_id:
            raise ValueError("root identity must identify the root node")
        if self.parent_id == self.node_id:
            raise ValueError("range cannot parent itself")
        if self.source_total is None:
            if self.next_offset or self.state != "pending":
                raise ValueError("unobserved range must be pending with zero offset")
        elif self.next_offset > self.source_total:
            raise ValueError("offset exceeds observed total")
        if self.state == "split" and (self.next_offset or self.source_total == 0):
            raise ValueError("split requires positive source total and zero offset")
        if self.state == "enumerated" and self.next_offset != self.source_total:
            raise ValueError("enumerated range must reach its observed total")
        return self


class SheetsHistoryReceipt(BaseModel):
    """Evidence metadata; the store verifies provenance, replay and BSON byte limits."""

    model_config = ConfigDict(strict=True, extra="forbid", populate_by_name=True)

    id: NonEmptyText = Field(alias="_id")
    acquisition_id: NonEmptyText
    seller_id: Annotated[str, Field(pattern=r"^[0-9]+$")]
    read_model: Literal["orders", "questions"]
    generation: PositiveCount
    pass_number: PositiveCount
    page_sequence: NonNegativeCount
    schema_version: int = Field(default=1, ge=1, le=1)
    kind: Literal["membership", "detail", "exclusion"]
    resource_id: NonEmptyText
    observed_at: datetime
    source_version: NonEmptyText | None = None
    source_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] | None = None
    source_payload: dict[str, JsonValue] | None = None
    payload_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] | None = None
    payload: dict[str, JsonValue] | None = None
    unavailable_fields: list[NonEmptyText] = Field(default_factory=list)
    exclusion_reason: NonEmptyText | None = None

    @field_validator("observed_at")
    @classmethod
    def _normalize_observation(cls, value: datetime) -> datetime:
        return assert_aware_utc_datetime(value)

    @model_validator(mode="after")
    def _validate_receipt(self) -> Self:
        if self.source_payload is not None and (
            not self.source_payload or self.source_hash is None
        ):
            raise ValueError("source evidence requires a nonempty payload and source hash")
        if len(set(self.unavailable_fields)) != len(self.unavailable_fields):
            raise ValueError("unavailable fields must be unique")
        if self.kind == "detail":
            if not self.payload or self.payload_hash is None:
                raise ValueError("detail requires a nonempty payload and payload hash")
            if self.exclusion_reason is not None:
                raise ValueError("detail cannot also be an exclusion")
        else:
            if self.payload is not None or self.payload_hash is not None or self.unavailable_fields:
                raise ValueError("membership and exclusion cannot carry detail fields")
            if (self.kind == "exclusion") != (self.exclusion_reason is not None):
                raise ValueError("only exclusion requires an exclusion reason")
        return self
