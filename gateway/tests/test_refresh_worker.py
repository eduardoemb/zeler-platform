from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from bson import Int64, ObjectId
from dotenv import load_dotenv
from infra.mongo.apply_validators import DEFAULT_MONGO_URI, apply_validators
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from zeler_gateway.tokens.encryption import (
    EncryptedToken,
    decrypt_token,
    encrypt_token,
    reset_dek_cache,
    set_kms_client,
)
from zeler_gateway.tokens.refresh_worker import refresh_once

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS_DIR = ROOT / "infra" / "mongo" / "schemas"
load_dotenv(ROOT / ".env")


class FakeKmsResponse:
    def __init__(
        self,
        ciphertext: bytes | None = None,
        plaintext: bytes | None = None,
        name: str = "key-version-1",
    ) -> None:
        self.ciphertext = ciphertext
        self.plaintext = plaintext
        self.name = name


class FakeKmsClient:
    def __init__(self) -> None:
        self.wrapped_to_plaintext: dict[bytes, bytes] = {}

    def encrypt(self, request: dict[str, bytes | str]) -> FakeKmsResponse:
        plaintext = request["plaintext"]
        assert isinstance(plaintext, bytes)
        wrapped = b"wrapped:" + plaintext
        self.wrapped_to_plaintext[wrapped] = plaintext
        return FakeKmsResponse(ciphertext=wrapped, name="projects/test/cryptoKeyVersions/1")

    def decrypt(self, request: dict[str, bytes | str]) -> FakeKmsResponse:
        ciphertext = request["ciphertext"]
        assert isinstance(ciphertext, bytes)
        return FakeKmsResponse(plaintext=self.wrapped_to_plaintext[ciphertext])


@pytest.fixture
def meli_accounts_db() -> Any:
    mongo_uri = os.environ.get("MONGO_URI", DEFAULT_MONGO_URI)
    client: MongoClient[dict[str, Any]] = MongoClient(
        mongo_uri, serverSelectionTimeoutMS=1000, tz_aware=True
    )
    try:
        client.admin.command("ping")
    except PyMongoError as exc:  # pragma: no cover - only for machines without local Docker Mongo
        pytest.skip(f"local Mongo is not available: {exc}")

    database = client.get_default_database()
    database.drop_collection("meli_accounts")
    apply_validators(mongo_uri, SCHEMAS_DIR)
    async_client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        mongo_uri, serverSelectionTimeoutMS=1000, tz_aware=True
    )
    async_db = async_client.get_default_database()
    reset_dek_cache()
    set_kms_client(FakeKmsClient())
    yield async_db, database
    database.drop_collection("meli_accounts")
    async_client.close()
    client.close()


def _seed_refreshable_account(
    database: Any,
    *,
    fixed_now: datetime,
    lock_held_until: datetime | None = None,
) -> dict[str, Any]:
    access_enc = encrypt_token("old-access", account_id="123456789")
    refresh_enc = encrypt_token("old-refresh", account_id="123456789")
    doc = {
        "_id": ObjectId(),
        "seller_id": Int64(123456789),
        "nickname": "TEST_SELLER",
        "app_id": "zeler-platform",
        "platform_user_id": "platform-user-123",
        "access_token_ciphertext": access_enc.ciphertext,
        "access_token_dek_wrapped": access_enc.dek_wrapped,
        "refresh_token_ciphertext": refresh_enc.ciphertext,
        "refresh_token_dek_wrapped": refresh_enc.dek_wrapped,
        "token_nonce": access_enc.nonce,
        "refresh_token_nonce": refresh_enc.nonce,
        "scopes": ["read", "write"],
        "status": "active",
        "expires_at": fixed_now + timedelta(minutes=5),
        "lock_held_until": lock_held_until,
        "created_at": fixed_now - timedelta(days=1),
        "updated_at": fixed_now - timedelta(days=1),
        "kms_key_version": access_enc.kms_key_version,
    }
    database.meli_accounts.insert_one(doc)
    return doc


def _token_from_doc(doc: dict[str, Any], *, prefix: str) -> EncryptedToken:
    return EncryptedToken(
        ciphertext=doc[f"{prefix}_token_ciphertext"],
        dek_wrapped=doc[f"{prefix}_token_dek_wrapped"],
        nonce=doc["token_nonce" if prefix == "access" else "refresh_token_nonce"],
        kms_key_version=doc["kms_key_version"],
    )


@pytest.mark.asyncio
async def test_refresh_acquires_lock_and_updates_tokens(meli_accounts_db: Any) -> None:
    async_db, database = meli_accounts_db
    fixed_now = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)
    original = _seed_refreshable_account(database, fixed_now=fixed_now, lock_held_until=None)

    with respx.mock(assert_all_called=True) as respx_mock:
        token_route = respx_mock.post("https://api.mercadolibre.com/oauth/token").mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "new-access",
                    "refresh_token": "new-refresh",
                    "expires_in": 21600,
                    "scope": "read write",
                    "user_id": 123456789,
                },
            )
        )

        stats = await refresh_once(async_db, now_fn=lambda: fixed_now)

    stored = database.meli_accounts.find_one({"_id": original["_id"]})
    assert stored is not None
    assert token_route.call_count == 1
    assert stats.attempted == 1
    assert stats.succeeded == 1
    assert stored["access_token_ciphertext"] != original["access_token_ciphertext"]
    assert stored["refresh_token_ciphertext"] != original["refresh_token_ciphertext"]
    assert stored["status"] == "active"
    assert stored["lock_held_until"] is None
    assert stored["expires_at"] == fixed_now + timedelta(seconds=21600)
    assert stored["last_refresh_at"] == fixed_now
    assert stored["last_refreshed_at"] == fixed_now
    assert (
        await decrypt_token(_token_from_doc(stored, prefix="access"), account_id="123456789")
        == "new-access"
    )
    assert (
        await decrypt_token(_token_from_doc(stored, prefix="refresh"), account_id="123456789")
        == "new-refresh"
    )


@pytest.mark.asyncio
async def test_concurrent_refresh_second_worker_skips(meli_accounts_db: Any) -> None:
    async_db, database = meli_accounts_db
    fixed_now = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)
    original = _seed_refreshable_account(
        database,
        fixed_now=fixed_now,
        lock_held_until=fixed_now + timedelta(seconds=60),
    )

    with respx.mock(assert_all_called=False):
        stats = await refresh_once(async_db, now_fn=lambda: fixed_now)

    stored = database.meli_accounts.find_one({"_id": original["_id"]})
    assert stored is not None
    assert stats.attempted == 0
    assert stats.skipped == 1
    assert stored["access_token_ciphertext"] == original["access_token_ciphertext"]
    assert stored["refresh_token_ciphertext"] == original["refresh_token_ciphertext"]
    assert stored["lock_held_until"] == fixed_now + timedelta(seconds=60)
    assert stored["status"] == "active"


@pytest.mark.asyncio
async def test_invalid_grant_sets_status_revoked(
    meli_accounts_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    async_db, database = meli_accounts_db
    fixed_now = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)
    original = _seed_refreshable_account(database, fixed_now=fixed_now, lock_held_until=None)
    emitted: list[dict[str, Any]] = []

    async def spy_emit_accounts_revoked(*, seller_id: int, platform_user_id: str) -> None:
        emitted.append({"seller_id": seller_id, "platform_user_id": platform_user_id})

    monkeypatch.setattr(
        "zeler_gateway.tokens.refresh_worker.emit_accounts_revoked", spy_emit_accounts_revoked
    )

    with respx.mock(assert_all_called=True) as respx_mock:
        token_route = respx_mock.post("https://api.mercadolibre.com/oauth/token").mock(
            return_value=httpx.Response(400, json={"error": "invalid_grant"})
        )

        stats = await refresh_once(async_db, now_fn=lambda: fixed_now)

    stored = database.meli_accounts.find_one({"_id": original["_id"]})
    assert stored is not None
    assert token_route.call_count == 1
    assert stats.attempted == 1
    assert stats.revoked == 1
    assert stored["status"] == "revoked"
    assert stored["lock_held_until"] is None
    assert emitted == [{"seller_id": 123456789, "platform_user_id": "platform-user-123"}]


@pytest.mark.asyncio
async def test_stale_lock_is_reacquired(meli_accounts_db: Any) -> None:
    async_db, database = meli_accounts_db
    fixed_now = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)
    original = _seed_refreshable_account(
        database,
        fixed_now=fixed_now,
        lock_held_until=fixed_now - timedelta(minutes=1),
    )

    with respx.mock(assert_all_called=True) as respx_mock:
        token_route = respx_mock.post("https://api.mercadolibre.com/oauth/token").mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "new-access-after-stale-lock",
                    "refresh_token": "new-refresh-after-stale-lock",
                    "expires_in": 21600,
                    "scope": "read write",
                    "user_id": 123456789,
                },
            )
        )

        stats = await refresh_once(async_db, now_fn=lambda: fixed_now)

    stored = database.meli_accounts.find_one({"_id": original["_id"]})
    assert stored is not None
    assert token_route.call_count == 1
    assert stats.succeeded == 1
    assert stored["status"] == "active"
    assert stored["lock_held_until"] is None
    assert (
        await decrypt_token(_token_from_doc(stored, prefix="access"), account_id="123456789")
        == "new-access-after-stale-lock"
    )
