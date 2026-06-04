from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import field_validator, model_validator

from zeler_platform_core.models.base import SellerScopedDocument, UtcDatetimeMixin, _coerce_str


class SellerUnitCost(UtcDatetimeMixin, SellerScopedDocument):
    normalized_sku: str | None = None
    item_id: str | None = None
    variation_id: str | None = None
    unit_cost: Decimal
    currency: str
    source: Literal["manual", "import"]
    status: Literal["active", "inactive"] = "active"
    effective_from: datetime
    effective_to: datetime | None = None
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    updated_by: str | None = None

    @field_validator("normalized_sku", mode="before")
    @classmethod
    def _normalize_sku(cls, value: object) -> str | None:
        if value is None:
            return None
        normalized = _coerce_str(value).strip().upper()
        return normalized or None

    @field_validator("item_id", "variation_id", "created_by", "updated_by", mode="before")
    @classmethod
    def _normalize_optional_string(cls, value: object) -> str | None:
        if value is None:
            return None
        normalized = _coerce_str(value).strip()
        return normalized or None

    @field_validator("currency", mode="before")
    @classmethod
    def _normalize_currency(cls, value: object) -> str:
        normalized = _coerce_str(value).strip().upper()
        if not normalized:
            msg = "currency must be non-empty"
            raise ValueError(msg)
        return normalized

    @field_validator("unit_cost", mode="before")
    @classmethod
    def _coerce_unit_cost(cls, value: object) -> Decimal:
        if isinstance(value, (bool, dict, list)):
            msg = "unit_cost must be a finite non-negative number"
            raise ValueError(msg)
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
        if not parsed.is_finite() or parsed < 0:
            msg = "unit_cost must be a finite non-negative number"
            raise ValueError(msg)
        return parsed

    @field_validator("effective_from", "effective_to", mode="before")
    @classmethod
    def _effective_datetime_must_be_aware(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                msg = "effective datetimes must be timezone-aware"
                raise ValueError(msg)
            return value.astimezone(UTC)
        return value

    @model_validator(mode="after")
    def _validate_identity_and_dates(self) -> SellerUnitCost:
        if not any((self.normalized_sku, self.item_id)):
            msg = "unit cost requires normalized_sku or item_id"
            raise ValueError(msg)
        if self.variation_id and not self.item_id:
            msg = "variation_id requires item_id"
            raise ValueError(msg)
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            msg = "effective_to must be after effective_from"
            raise ValueError(msg)
        return self
