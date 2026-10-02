from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from bson import Int64, ObjectId
from infra.mongo.apply_validators import apply_validators
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient
from pymongo.errors import PyMongoError

import zeler_gateway.tokens.refresh_worker as refresh_worker_module
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


class RecordingLifecyclePublisher:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def publish(self, *, exchange: str, routing_key: str, payload: dict[str, Any]) -> None:
        self.events.append({"exchange": exchange, "routing_key": routing_key, "payload": payload})


class FakeAccountCursor:
    def __init__(self, candidates: list[dict[str, Any]]) -> None:
        self._candidates = candidates

    def __aiter__(self) -> FakeAccountCursor:
        return self

    async def __anext__(self) -> dict[str, Any]:
        if not self._candidates:
            raise StopAsyncIteration
        return self._candidates.pop(0)


class FakeMeliAccounts:
    def __init__(self, account: dict[str, Any]) -> None:
        self.account = account
        self.find_queries: list[dict[str, Any]] = []
        self.updates: list[dict[str, Any]] = []

    def find(self, query: dict[str, Any], projection: dict[str, Any]) -> FakeAccountCursor:
        self.find_queries.append(query)
        candidates = [{"_id": self.account["_id"]}] if self._matches(query) else []
        return FakeAccountCursor(candidates)

    def _matches(self, query: dict[str, Any]) -> bool:
        for field, condition in query.items():
            if field == "$and":
                if not all(self._matches(branch) for branch in condition):
                    return False
            elif field == "$or":
                if not any(self._matches(branch) for branch in condition):
                    return False
            elif isinstance(condition, dict):
                value = self.account.get(field)
                if "$in" in condition and value not in condition["$in"]:
                    return False
                if "$lt" in condition and (value is None or value >= condition["$lt"]):
                    return False
            elif self.account.get(field) != condition:
                return False
        return True

    async def find_one_and_update(
        self, query: dict[str, Any], update: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any] | None:
        if not self._matches(query):
            return None
        self.account.update(update["$set"])
        return self.account

    async def update_one(self, query: dict[str, Any], update: dict[str, Any]) -> None:
        self.updates.append({"query": query, "update": update})
        self.account.update(update["$set"])


class FakeRefreshDb:
    def __init__(self, account: dict[str, Any]) -> None:
        self.meli_accounts = FakeMeliAccounts(account)


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
def meli_accounts_db(default_mongo_uri: str) -> Any:
    mongo_uri = default_mongo_uri
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
        "schema_version": 1,
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
    publisher = RecordingLifecyclePublisher()

    async def spy_emit_accounts_revoked(
        *,
        seller_id: int,
        platform_user_id: str,
        amqp_publisher: Any,
        clock: Any,
    ) -> None:
        emitted.append(
            {
                "seller_id": seller_id,
                "platform_user_id": platform_user_id,
                "amqp_publisher": amqp_publisher,
                "occurred_at": clock(),
            }
        )

    monkeypatch.setattr(
        "zeler_gateway.tokens.refresh_worker.emit_accounts_revoked", spy_emit_accounts_revoked
    )

    with respx.mock(assert_all_called=True) as respx_mock:
        token_route = respx_mock.post("https://api.mercadolibre.com/oauth/token").mock(
            return_value=httpx.Response(400, json={"error": "invalid_grant"})
        )

        stats = await refresh_once(
            async_db,
            now_fn=lambda: fixed_now,
            lifecycle_publisher=publisher,
        )

    stored = database.meli_accounts.find_one({"_id": original["_id"]})
    assert stored is not None
    assert token_route.call_count == 1
    assert stats.attempted == 1
    assert stats.revoked == 1
    assert stored["status"] == "revoked"
    assert stored["lock_held_until"] is None
    assert emitted == [
        {
            "seller_id": 123456789,
            "platform_user_id": "platform-user-123",
            "amqp_publisher": publisher,
            "occurred_at": fixed_now,
        }
    ]


@pytest.mark.asyncio
async def test_invalid_grant_publishes_one_revocation_with_worker_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed_now = datetime(2026, 8, 10, 18, 30, tzinfo=UTC)
    account = {
        "_id": ObjectId(),
        "seller_id": Int64(123456789),
        "platform_user_id": "platform-user-456",
        "refresh_token_ciphertext": b"ciphertext",
        "refresh_token_dek_wrapped": b"wrapped",
        "refresh_token_nonce": b"nonce",
        "kms_key_version": "key-version-1",
        "status": "active",
        "expires_at": fixed_now + timedelta(minutes=5),
    }
    db = FakeRefreshDb(account)
    publisher = RecordingLifecyclePublisher()

    async def fail_with_invalid_grant(**kwargs: Any) -> dict[str, Any]:
        raise refresh_worker_module.InvalidGrantError

    monkeypatch.setattr(refresh_worker_module, "_call_meli_refresh", fail_with_invalid_grant)

    stats = await refresh_once(
        db,
        now_fn=lambda: fixed_now,
        lifecycle_publisher=publisher,
    )

    assert stats.attempted == 1
    assert stats.revoked == 1
    assert account["status"] == "revoked"
    assert publisher.events == [
        {
            "exchange": "meli.events",
            "routing_key": "accounts.revoked",
            "payload": {
                "seller_id": "123456789",
                "platform_user_id": "platform-user-456",
                "occurred_at": "2026-08-10T18:30:00+00:00",
                "idempotency_key": (
                    "accounts-revoked-123456789-platform-user-456-2026-08-10T18:30:00+00:00"
                ),
            },
        }
    ]


@pytest.mark.asyncio
async def test_already_revoked_account_does_not_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed_now = datetime(2026, 8, 10, 19, 0, tzinfo=UTC)
    account = {
        "_id": ObjectId(),
        "seller_id": Int64(987654321),
        "platform_user_id": "platform-user-revoked",
        "status": "revoked",
        "expires_at": fixed_now - timedelta(minutes=5),
    }
    db = FakeRefreshDb(account)
    publisher = RecordingLifecyclePublisher()

    async def unexpected_refresh(**kwargs: Any) -> dict[str, Any]:
        pytest.fail("already-revoked account must not be refreshed")

    monkeypatch.setattr(refresh_worker_module, "_call_meli_refresh", unexpected_refresh)

    stats = await refresh_once(
        db,
        now_fn=lambda: fixed_now,
        lifecycle_publisher=publisher,
    )

    assert stats.attempted == 0
    assert stats.revoked == 0
    assert len(db.meli_accounts.find_queries) == 1
    assert db.meli_accounts.find_queries[0]["expires_at"] == {
        "$lt": fixed_now + timedelta(minutes=15)
    }
    assert publisher.events == []


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


def _unit_refresh_account(now: datetime) -> dict[str, Any]:
    reset_dek_cache()
    set_kms_client(FakeKmsClient())
    access = encrypt_token("old-access", account_id="123456789")
    refresh = encrypt_token("old-refresh", account_id="123456789")
    return {
        "_id": ObjectId(),
        "seller_id": Int64(123456789),
        "platform_user_id": "platform-user-test",
        "status": "active",
        "expires_at": now - timedelta(minutes=5),
        "lock_held_until": None,
        "access_token_ciphertext": access.ciphertext,
        "access_token_dek_wrapped": access.dek_wrapped,
        "token_nonce": access.nonce,
        "refresh_token_ciphertext": refresh.ciphertext,
        "refresh_token_dek_wrapped": refresh.dek_wrapped,
        "refresh_token_nonce": refresh.nonce,
        "kms_key_version": access.kms_key_version,
    }


_REFRESH_SUCCESS = {
    "access_token": "new-access",
    "refresh_token": "new-refresh",
    "expires_in": 21600,
}


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [429, 500, 503, 599, "connect", "timeout"])
async def test_transient_refresh_remains_eligible_for_next_pass(failure: int | str) -> None:
    now = datetime(2026, 10, 2, 5, 0, tzinfo=UTC)
    account = _unit_refresh_account(now)
    original = dict(account)
    db = FakeRefreshDb(account)
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post("https://api.mercadolibre.com/oauth/token")
        if isinstance(failure, int):
            route.mock(return_value=httpx.Response(failure, json={}))
        else:
            error = httpx.ConnectError if failure == "connect" else httpx.ReadTimeout
            route.mock(side_effect=error("synthetic transient failure"))
        first = await refresh_once(db, now_fn=lambda: now)
        assert first.failed == 1
        assert account["status"] == "refresh_pending"
        assert account["lock_held_until"] is None
        assert account["expires_at"] == original["expires_at"]
        for field in original:
            if "token" in field or field == "kms_key_version":
                assert account[field] == original[field]
        route.mock(return_value=httpx.Response(200, json=_REFRESH_SUCCESS))
        second = await refresh_once(db, now_fn=lambda: now + timedelta(minutes=5))
    assert route.call_count == 2
    assert second.succeeded == 1
    assert account["status"] == "active"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "last_error", "eligible"),
    [
        ("error", "Meli refresh failed with status 429", True),
        ("error", "Meli refresh failed with status 500", True),
        ("error", "Meli refresh failed with status 599", True),
        ("error", "Meli refresh failed with status 401", False),
        ("error", "Meli refresh failed with status 600", False),
        ("error", "Meli refresh failed with status 429 trailing", False),
        ("error", "Meli refresh failed with status 429\n", False),
        ("error", "unrecognized transport failure", False),
        ("revoked", "Meli refresh failed with status 429", False),
        ("paused", "Meli refresh failed with status 500", False),
    ],
)
async def test_legacy_refresh_errors_retry_only_exact_transient_evidence(
    status: str, last_error: str, eligible: bool
) -> None:
    now = datetime(2026, 10, 2, 5, 0, tzinfo=UTC)
    account = _unit_refresh_account(now)
    account.update(status=status, last_error=last_error)
    db = FakeRefreshDb(account)
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://api.mercadolibre.com/oauth/token").mock(
            return_value=httpx.Response(200, json=_REFRESH_SUCCESS)
        )
        stats = await refresh_once(db, now_fn=lambda: now)
    assert route.call_count == int(eligible)
    assert stats.succeeded == int(eligible)
    assert account["status"] == ("active" if eligible else status)


@pytest.mark.asyncio
@pytest.mark.parametrize("new_status", ["paused", "revoked", "error"])
async def test_refresh_lock_rechecks_account_eligibility(
    new_status: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 10, 2, 5, 0, tzinfo=UTC)
    account = _unit_refresh_account(now)
    db = FakeRefreshDb(account)
    original_find = db.meli_accounts.find

    def race(query: dict[str, Any], projection: dict[str, Any]) -> FakeAccountCursor:
        cursor = original_find(query, projection)
        account.update(status=new_status, last_error="non-transient failure")
        return cursor

    monkeypatch.setattr(db.meli_accounts, "find", race)
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://api.mercadolibre.com/oauth/token").mock(
            return_value=httpx.Response(200, json=_REFRESH_SUCCESS)
        )
        stats = await refresh_once(db, now_fn=lambda: now)
    assert route.call_count == 0
    assert stats.skipped == 1
    assert account["status"] == new_status


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 404])
async def test_nontransient_refresh_remains_terminal(status: int) -> None:
    now = datetime(2026, 10, 2, 5, 0, tzinfo=UTC)
    account = _unit_refresh_account(now)
    db = FakeRefreshDb(account)
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post("https://api.mercadolibre.com/oauth/token").mock(
            return_value=httpx.Response(status, json={})
        )
        first = await refresh_once(db, now_fn=lambda: now)
        second = await refresh_once(db, now_fn=lambda: now + timedelta(minutes=5))
    assert first.failed == 1
    assert second.attempted == 0
    assert route.call_count == 1
    assert account["status"] == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 503])
async def test_transient_refresh_retry_with_mongo_validator(
    meli_accounts_db: Any, status: int
) -> None:
    async_db, database = meli_accounts_db
    now = datetime(2026, 10, 2, 5, 0, tzinfo=UTC)
    original = _seed_refreshable_account(database, fixed_now=now)
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post("https://api.mercadolibre.com/oauth/token").mock(
            return_value=httpx.Response(status, json={})
        )
        first = await refresh_once(async_db, now_fn=lambda: now)
        stored = database.meli_accounts.find_one({"_id": original["_id"]})
        assert first.failed == 1
        assert stored["status"] == "refresh_pending"
        assert stored["lock_held_until"] is None
        assert stored["refresh_token_ciphertext"] == original["refresh_token_ciphertext"]
        route.mock(return_value=httpx.Response(200, json=_REFRESH_SUCCESS))
        second = await refresh_once(async_db, now_fn=lambda: now + timedelta(minutes=5))
    assert route.call_count == 2
    assert second.succeeded == 1
    assert database.meli_accounts.find_one({"_id": original["_id"]})["status"] == "active"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "last_error", "expected"),
    [
        ("error", "Meli refresh failed with status 429", 1),
        ("error", "Meli refresh failed with status 503", 1),
        ("error", "Meli refresh failed with status 401", 0),
        ("error", "Meli refresh failed with status 429\n", 0),
        ("revoked", "Meli refresh failed with status 429", 0),
        ("paused", "Meli refresh failed with status 429", 0),
    ],
)
async def test_legacy_retry_selection_with_mongo_validator(
    meli_accounts_db: Any, status: str, last_error: str, expected: int
) -> None:
    async_db, database = meli_accounts_db
    now = datetime(2026, 10, 2, 5, 0, tzinfo=UTC)
    original = _seed_refreshable_account(database, fixed_now=now)
    database.meli_accounts.update_one(
        {"_id": original["_id"]}, {"$set": {"status": status, "last_error": last_error}}
    )
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://api.mercadolibre.com/oauth/token").mock(
            return_value=httpx.Response(200, json=_REFRESH_SUCCESS)
        )
        stats = await refresh_once(async_db, now_fn=lambda: now)
    assert route.call_count == expected
    assert stats.succeeded == expected
    assert database.meli_accounts.find_one({"_id": original["_id"]})["status"] == (
        "active" if expected else status
    )
