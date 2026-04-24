from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from zeler_platform_core.models.base import TimestampedDocument, UtcDatetimeMixin, _coerce_str


class User(UtcDatetimeMixin, TimestampedDocument):
    email: str
    name: str
    auth_provider: Literal["local", "google", "meli", "internal"]
    meli_account_ids: list[str] = Field(default_factory=list)
    module_permissions: dict[str, list[str]] = Field(default_factory=dict)
    roles: list[str] = Field(default_factory=lambda: ["user"])
    status: Literal["active", "suspended", "deleted"] = "active"

    @field_validator("meli_account_ids", mode="before")
    @classmethod
    def _coerce_meli_account_ids(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [_coerce_str(item) for item in value]
        return [_coerce_str(value)]
