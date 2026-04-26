# ruff: noqa: S105,S106

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from google_test_fakes import FakeKmsClient, fake_kms_client
from pydantic import SecretStr

from zeler_sheets.google_errors import SellerNotConnectedError, SellerTokenRevokedError
from zeler_sheets.google_token_encryption import EncryptedToken, decrypt_token, encrypt_token
from zeler_sheets.google_token_store import GoogleTokenStore
from zeler_sheets.sheets_config import SheetsSettings

__all__ = ["fake_kms_client"]


class FakeUpdateResult:
    modified_count = 1
    upserted_id = None


class FakeCollection:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}

    async def find_one(self, filter_spec: dict[str, Any]) -> dict[str, Any] | None:
        for doc in self.documents.values():
            if all(doc.get(key) == value for key, value in filter_spec.items()):
                return dict(doc)
        return None

    async def update_one(
        self, filter_spec: dict[str, Any], update_spec: dict[str, Any], *, upsert: bool = False
    ) -> FakeUpdateResult:
        doc_id = str(filter_spec["_id"])
        existing = dict(self.documents.get(doc_id, {}))
        if not existing and not upsert:
            return FakeUpdateResult()
        self.documents[doc_id] = {
            **update_spec.get("$setOnInsert", {}),
            **existing,
            **update_spec.get("$set", {}),
            "_id": doc_id,
        }
        return FakeUpdateResult()


class FakeDb:
    def __init__(self) -> None:
        self.google_oauth_tokens = FakeCollection()

    def __getitem__(self, name: str) -> FakeCollection:
        assert name == "google_oauth_tokens"
        return self.google_oauth_tokens


def _settings() -> SheetsSettings:
    return SheetsSettings(
        google_oauth_client_id="google-client-id",
        google_oauth_client_secret=SecretStr("google-client-secret"),
        google_oauth_redirect_uri="https://sheets.test/oauth/google/callback",
        kms_project_id="zeler-dev",
    )


def _store(
    db: FakeDb,
    fake_kms_client: FakeKmsClient,
    *,
    now: datetime,
    http_client_factory: Any | None = None,
) -> GoogleTokenStore:
    return GoogleTokenStore(
        db=db,
        kms_client=fake_kms_client,
        http_client_factory=http_client_factory or (lambda: httpx.AsyncClient()),
        settings=_settings(),
        now_fn=lambda: now,
    )


def _token_doc(
    *, seller_id: str, access_token: str, refresh_token: str, expires_at: datetime
) -> dict[str, Any]:
    access = encrypt_token(access_token, account_id=seller_id)
    refresh = encrypt_token(refresh_token, account_id=seller_id)
    now = datetime(2026, 4, 26, 12, 0, tzinfo=UTC)
    return {
        "_id": f"google-token-{seller_id}",
        "seller_id": seller_id,
        "access_token_ciphertext": access.ciphertext,
        "access_token_dek_wrapped": access.dek_wrapped,
        "token_nonce": access.nonce,
        "refresh_token_ciphertext": refresh.ciphertext,
        "refresh_token_dek_wrapped": refresh.dek_wrapped,
        "refresh_token_nonce": refresh.nonce,
        "kms_key_version": access.kms_key_version,
        "scopes": ["https://www.googleapis.com/auth/spreadsheets"],
        "expires_at": expires_at,
        "status": "active",
        "last_error": None,
        "connected_at": now,
        "created_at": now,
        "updated_at": now,
        "schema_version": 1,
    }


@pytest.mark.asyncio
async def test_get_access_token_no_doc_raises_seller_not_connected(
    fake_kms_client: FakeKmsClient,
) -> None:
    store = _store(FakeDb(), fake_kms_client, now=datetime(2026, 4, 26, 12, 0, tzinfo=UTC))

    with pytest.raises(SellerNotConnectedError, match="seller seller-1 is not connected"):
        await store.get_access_token("seller-1")


@pytest.mark.asyncio
async def test_get_access_token_returns_decrypted_when_fresh(
    fake_kms_client: FakeKmsClient,
) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=UTC)
    db = FakeDb()
    db.google_oauth_tokens.documents["google-token-seller-1"] = _token_doc(
        seller_id="seller-1",
        access_token="fresh-access-token",
        refresh_token="refresh-token",
        expires_at=now + timedelta(hours=1),
    )

    token = await _store(db, fake_kms_client, now=now).get_access_token("seller-1")

    assert token == "fresh-access-token"


@pytest.mark.asyncio
async def test_get_access_token_lazy_refresh_within_5min(fake_kms_client: FakeKmsClient) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=UTC)
    db = FakeDb()
    db.google_oauth_tokens.documents["google-token-seller-1"] = _token_doc(
        seller_id="seller-1",
        access_token="stale-access-token",
        refresh_token="refresh-token",
        expires_at=now + timedelta(minutes=4),
    )
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"access_token": "new-access-token", "expires_in": 3600})

    store = _store(
        db,
        fake_kms_client,
        now=now,
        http_client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    token = await store.get_access_token("seller-1")

    assert token == "new-access-token"
    assert len(requests) == 1
    updated = db.google_oauth_tokens.documents["google-token-seller-1"]
    assert updated["expires_at"] == now + timedelta(seconds=3600)
    assert updated["status"] == "active"


@pytest.mark.asyncio
async def test_get_access_token_refresh_invalid_grant_marks_revoked_raises(
    fake_kms_client: FakeKmsClient,
) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=UTC)
    db = FakeDb()
    db.google_oauth_tokens.documents["google-token-seller-1"] = _token_doc(
        seller_id="seller-1",
        access_token="stale-access-token",
        refresh_token="refresh-token",
        expires_at=now + timedelta(minutes=1),
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    store = _store(
        db,
        fake_kms_client,
        now=now,
        http_client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(SellerTokenRevokedError, match="seller seller-1 token revoked"):
        await store.get_access_token("seller-1")

    assert db.google_oauth_tokens.documents["google-token-seller-1"]["status"] == "revoked"


@pytest.mark.asyncio
async def test_store_initial_upserts_with_encrypted_tokens(fake_kms_client: FakeKmsClient) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=UTC)
    db = FakeDb()
    expires_at = now + timedelta(hours=1)

    await _store(db, fake_kms_client, now=now).store_initial(
        "seller-1",
        access_token="initial-access",
        refresh_token="initial-refresh",
        expires_at=expires_at,
        scopes=["scope-a"],
    )

    doc = db.google_oauth_tokens.documents["google-token-seller-1"]
    assert doc["seller_id"] == "seller-1"
    assert doc["status"] == "active"
    assert doc["scopes"] == ["scope-a"]
    assert doc["expires_at"] == expires_at
    access = await decrypt_token(
        EncryptedToken(
            ciphertext=doc["access_token_ciphertext"],
            dek_wrapped=doc["access_token_dek_wrapped"],
            nonce=doc["token_nonce"],
            kms_key_version=doc["kms_key_version"],
        ),
        account_id="seller-1",
    )
    assert access == "initial-access"


@pytest.mark.asyncio
async def test_store_initial_preserves_refresh_token_when_absent_in_response(
    fake_kms_client: FakeKmsClient,
) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=UTC)
    db = FakeDb()
    db.google_oauth_tokens.documents["google-token-seller-1"] = _token_doc(
        seller_id="seller-1",
        access_token="old-access",
        refresh_token="existing-refresh",
        expires_at=now + timedelta(hours=1),
    )

    await _store(db, fake_kms_client, now=now).store_initial(
        "seller-1",
        access_token="new-access",
        refresh_token=None,
        expires_at=now + timedelta(hours=2),
        scopes=["scope-a"],
    )

    doc = db.google_oauth_tokens.documents["google-token-seller-1"]
    refresh = await decrypt_token(
        EncryptedToken(
            ciphertext=doc["refresh_token_ciphertext"],
            dek_wrapped=doc["refresh_token_dek_wrapped"],
            nonce=doc["refresh_token_nonce"],
            kms_key_version=doc["kms_key_version"],
        ),
        account_id="seller-1",
    )
    assert refresh == "existing-refresh"


@pytest.mark.asyncio
async def test_revoke_marks_status_and_persists_reason(fake_kms_client: FakeKmsClient) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=UTC)
    db = FakeDb()
    db.google_oauth_tokens.documents["google-token-seller-1"] = _token_doc(
        seller_id="seller-1",
        access_token="access",
        refresh_token="refresh",
        expires_at=now + timedelta(hours=1),
    )

    await _store(db, fake_kms_client, now=now).revoke("seller-1", reason="manual revoke")

    doc = db.google_oauth_tokens.documents["google-token-seller-1"]
    assert doc["status"] == "revoked"
    assert doc["last_error"] == "manual revoke"
