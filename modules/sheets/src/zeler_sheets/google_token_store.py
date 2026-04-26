from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx

from zeler_sheets.google_errors import SellerNotConnectedError, SellerTokenRevokedError
from zeler_sheets.google_token_encryption import (
    EncryptedToken,
    KmsClient,
    decrypt_token,
    encrypt_token,
    set_kms_client,
)
from zeler_sheets.sheets_config import SheetsSettings


class GoogleTokenStore:
    REFRESH_WINDOW = timedelta(minutes=5)

    def __init__(
        self,
        *,
        db: Any,
        kms_client: KmsClient,
        http_client_factory: Callable[[], httpx.AsyncClient],
        settings: SheetsSettings,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db
        self._tokens = db["google_oauth_tokens"]
        self._http_client_factory = http_client_factory
        self._settings = settings
        self._now_fn = now_fn or (lambda: datetime.now(UTC))
        set_kms_client(kms_client)

    async def get_access_token(self, seller_id: str) -> str:
        seller_id = str(seller_id)
        doc = await self._tokens.find_one({"_id": self._token_id(seller_id)})
        if doc is None:
            raise SellerNotConnectedError(f"seller {seller_id} is not connected")

        expires_at = cast(datetime, doc["expires_at"])
        if expires_at < self._now() + self.REFRESH_WINDOW:
            return await self._refresh(seller_id, doc)

        return await decrypt_token(self._encrypted_access_token(doc), account_id=seller_id)

    async def store_initial(
        self,
        seller_id: str,
        *,
        access_token: str,
        refresh_token: str | None,
        expires_at: datetime,
        scopes: list[str],
    ) -> None:
        seller_id = str(seller_id)
        now = self._now()
        existing = await self._tokens.find_one({"_id": self._token_id(seller_id)})
        if refresh_token is None and existing is None:
            raise ValueError("Google consent required to issue refresh_token")

        access_enc = encrypt_token(access_token, account_id=seller_id)
        doc_set: dict[str, Any] = {
            "seller_id": seller_id,
            "access_token_ciphertext": access_enc.ciphertext,
            "access_token_dek_wrapped": access_enc.dek_wrapped,
            "token_nonce": access_enc.nonce,
            "kms_key_version": access_enc.kms_key_version,
            "scopes": scopes,
            "expires_at": expires_at,
            "status": "active",
            "last_error": None,
            "updated_at": now,
            "schema_version": 1,
        }
        if refresh_token is not None:
            refresh_enc = encrypt_token(refresh_token, account_id=seller_id)
            doc_set.update(
                {
                    "refresh_token_ciphertext": refresh_enc.ciphertext,
                    "refresh_token_dek_wrapped": refresh_enc.dek_wrapped,
                    "refresh_token_nonce": refresh_enc.nonce,
                }
            )

        await self._tokens.update_one(
            {"_id": self._token_id(seller_id)},
            {
                "$set": doc_set,
                "$setOnInsert": {
                    "_id": self._token_id(seller_id),
                    "connected_at": now,
                    "created_at": now,
                },
            },
            upsert=True,
        )

    async def revoke(self, seller_id: str, *, reason: str) -> None:
        seller_id = str(seller_id)
        await self._tokens.update_one(
            {"_id": self._token_id(seller_id)},
            {"$set": {"status": "revoked", "last_error": reason, "updated_at": self._now()}},
        )

    async def mark_error(self, seller_id: str, *, reason: str) -> None:
        seller_id = str(seller_id)
        await self._tokens.update_one(
            {"_id": self._token_id(seller_id)},
            {"$set": {"status": "error", "last_error": reason, "updated_at": self._now()}},
        )

    async def _refresh(self, seller_id: str, doc: dict[str, Any]) -> str:
        refresh_token = await decrypt_token(
            self._encrypted_refresh_token(doc), account_id=seller_id
        )
        async with self._http_client_factory() as client:
            response = await client.post(
                self._settings.google_oauth_token_url,
                data={
                    "grant_type": "refresh_token",
                    "client_id": self._settings.google_oauth_client_id,
                    "client_secret": self._settings.google_oauth_client_secret.get_secret_value(),
                    "refresh_token": refresh_token,
                },
            )

        if response.status_code >= 400:
            payload = _safe_json(response)
            if 400 <= response.status_code < 500 and payload.get("error") == "invalid_grant":
                await self.revoke(seller_id, reason="invalid_grant")
                raise SellerTokenRevokedError(f"seller {seller_id} token revoked")
            reason = f"Google token refresh failed with status {response.status_code}"
            await self.mark_error(seller_id, reason=reason)
            raise RuntimeError(reason)

        payload = cast(dict[str, Any], response.json())
        access_token = str(payload["access_token"])
        access_enc = encrypt_token(access_token, account_id=seller_id)
        now = self._now()
        await self._tokens.update_one(
            {"_id": self._token_id(seller_id)},
            {
                "$set": {
                    "access_token_ciphertext": access_enc.ciphertext,
                    "access_token_dek_wrapped": access_enc.dek_wrapped,
                    "token_nonce": access_enc.nonce,
                    "kms_key_version": access_enc.kms_key_version,
                    "expires_at": now + timedelta(seconds=int(payload["expires_in"])),
                    "status": "active",
                    "last_error": None,
                    "updated_at": now,
                }
            },
        )
        return access_token

    def _now(self) -> datetime:
        return self._now_fn()

    @staticmethod
    def _token_id(seller_id: str) -> str:
        return f"google-token-{seller_id}"

    @staticmethod
    def _encrypted_access_token(doc: dict[str, Any]) -> EncryptedToken:
        return EncryptedToken(
            ciphertext=cast(bytes, doc["access_token_ciphertext"]),
            dek_wrapped=cast(bytes, doc["access_token_dek_wrapped"]),
            nonce=cast(bytes, doc["token_nonce"]),
            kms_key_version=cast(str, doc["kms_key_version"]),
        )

    @staticmethod
    def _encrypted_refresh_token(doc: dict[str, Any]) -> EncryptedToken:
        return EncryptedToken(
            ciphertext=cast(bytes, doc["refresh_token_ciphertext"]),
            dek_wrapped=cast(bytes, doc["refresh_token_dek_wrapped"]),
            nonce=cast(bytes, doc["refresh_token_nonce"]),
            kms_key_version=cast(str, doc["kms_key_version"]),
        )


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {}
    if isinstance(payload, dict):
        return cast(dict[str, Any], payload)
    return {}
