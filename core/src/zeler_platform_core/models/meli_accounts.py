from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import field_validator

from zeler_platform_core.models.base import TimestampedDocument, UtcDatetimeMixin, _coerce_str

MeliAccountStatus = Literal[
    "active", "pending", "refresh_pending", "revoked", "invalid_grant", "error", "invalid"
]


class MeliAccount(UtcDatetimeMixin, TimestampedDocument):
    seller_id: str
    nickname: str
    app_id: str = "zeler-platform"
    platform_user_id: str
    access_token_ciphertext: str
    access_token_dek_wrapped: str
    refresh_token_ciphertext: str
    refresh_token_dek_wrapped: str
    token_nonce: str
    refresh_token_nonce: str
    scopes: list[str]
    status: MeliAccountStatus
    expires_at: datetime
    kms_key_version: str
    refresh_token_expires_at: datetime | None = None
    lock_held_until: datetime | None = None
    last_refresh_at: datetime | None = None
    connected_at: datetime | None = None
    last_error: str | None = None
    sync_status: dict[str, object] | None = None

    @field_validator("seller_id", mode="before")
    @classmethod
    def _coerce_seller_id(cls, value: object) -> str:
        return _coerce_str(value)
