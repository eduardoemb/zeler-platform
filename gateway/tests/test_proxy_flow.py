from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
import respx
from bson import Int64, ObjectId
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from dotenv import load_dotenv
from infra.mongo.apply_validators import DEFAULT_MONGO_URI, apply_validators
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from zeler_gateway.app import app
from zeler_gateway.proxy.router import router as proxy_router
from zeler_gateway.tokens.encryption import encrypt_token, reset_dek_cache, set_kms_client
from zeler_platform_core.auth.jwt import mint_module_jwt
from zeler_platform_core.auth.jwt import set_kms_client as set_jwt_kms_client

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS_DIR = ROOT / "infra" / "mongo" / "schemas"
load_dotenv(ROOT / ".env")


class FakeEnvelopeKmsResponse:
    def __init__(
        self,
        ciphertext: bytes | None = None,
        plaintext: bytes | None = None,
        name: str = "key-version-1",
    ) -> None:
        self.ciphertext = ciphertext
        self.plaintext = plaintext
        self.name = name


class FakeEnvelopeKmsClient:
    def __init__(self) -> None:
        self.wrapped_to_plaintext: dict[bytes, bytes] = {}

    def encrypt(self, request: dict[str, bytes | str]) -> FakeEnvelopeKmsResponse:
        plaintext = request["plaintext"]
        assert isinstance(plaintext, bytes)
        wrapped = b"wrapped:" + plaintext
        self.wrapped_to_plaintext[wrapped] = plaintext
        return FakeEnvelopeKmsResponse(ciphertext=wrapped, name="projects/test/cryptoKeyVersions/1")

    def decrypt(self, request: dict[str, bytes | str]) -> FakeEnvelopeKmsResponse:
        ciphertext = request["ciphertext"]
        assert isinstance(ciphertext, bytes)
        return FakeEnvelopeKmsResponse(plaintext=self.wrapped_to_plaintext[ciphertext])


class FakeJwtKmsSignResponse:
    def __init__(self, signature: bytes) -> None:
        self.signature = signature


class FakeJwtKmsPublicKeyResponse:
    def __init__(self, pem: str) -> None:
        self.pem = pem


class FakeJwtKmsClient:
    def __init__(self) -> None:
        self.private_key = ec.generate_private_key(ec.SECP256R1())

    def asymmetric_sign(self, request: dict[str, Any]) -> FakeJwtKmsSignResponse:
        digest = request["digest"]
        sha256_digest = digest["sha256"]
        signature = self.private_key.sign(
            sha256_digest,
            ec.ECDSA(utils.Prehashed(hashes.SHA256())),
        )
        return FakeJwtKmsSignResponse(signature)

    def get_public_key(self, request: dict[str, str]) -> FakeJwtKmsPublicKeyResponse:
        pem = self.private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return FakeJwtKmsPublicKeyResponse(pem.decode("ascii"))


@pytest.fixture
def proxy_db() -> Iterator[Any]:
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
    database.drop_collection("module_registry")
    database.drop_collection("audit_log")
    database.drop_collection("rate_limit_counters")
    apply_validators(mongo_uri, SCHEMAS_DIR)
    database.module_registry.insert_one(
        {
            "_id": "repricer",
            "version": "0.1.0",
            "allowed_meli_scopes": ["GET /items/*"],
            "status": "enabled",
        }
    )
    async_client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        mongo_uri, serverSelectionTimeoutMS=1000, tz_aware=True
    )
    reset_dek_cache()
    set_kms_client(FakeEnvelopeKmsClient())
    set_jwt_kms_client(FakeJwtKmsClient())
    yield async_client.get_default_database(), database
    database.drop_collection("meli_accounts")
    database.drop_collection("module_registry")
    database.drop_collection("audit_log")
    database.drop_collection("rate_limit_counters")
    async_client.close()
    client.close()
    set_jwt_kms_client(None)


@pytest_asyncio.fixture
async def proxy_client(proxy_db: Any) -> AsyncIterator[httpx.AsyncClient]:
    async_db, _ = proxy_db
    app.state.mongo_db = async_db
    app.include_router(proxy_router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


def _seed_account(
    database: Any,
    *,
    seller_id: int = 123456789,
    status: str = "active",
    lock_held_until: datetime | None = None,
) -> None:
    access_enc = encrypt_token("meli-access-token", account_id=str(seller_id))
    refresh_enc = encrypt_token("meli-refresh-token", account_id=str(seller_id))
    now = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)
    database.meli_accounts.insert_one(
        {
            "_id": ObjectId(),
            "seller_id": Int64(seller_id),
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
            "status": status,
            "expires_at": now + timedelta(hours=1),
            "lock_held_until": lock_held_until,
            "created_at": now - timedelta(days=1),
            "updated_at": now - timedelta(days=1),
            "kms_key_version": access_enc.kms_key_version,
        }
    )


def _auth_header(module_id: str = "repricer", seller_id: int = 123456789) -> dict[str, str]:
    return {"Authorization": f"Bearer {mint_module_jwt(module_id, seller_id=seller_id)}"}


@pytest.mark.asyncio
async def test_proxy_call_injects_token_and_forwards(
    proxy_client: httpx.AsyncClient, proxy_db: Any
) -> None:
    _, database = proxy_db
    _seed_account(database)

    with respx.mock(assert_all_called=True) as respx_mock:
        upstream = respx_mock.get("https://api.mercadolibre.com/items/MLA123").mock(
            return_value=httpx.Response(200, json={"id": "MLA123"})
        )

        response = await proxy_client.get("/proxy/meli/items/MLA123", headers=_auth_header())

    assert response.status_code == 200
    assert response.json() == {"id": "MLA123"}
    assert upstream.calls.last.request.headers["Authorization"] == "Bearer meli-access-token"
    audit_doc = database.audit_log.find_one(
        {
            "module_id": "repricer",
            "seller_id": 123456789,
            "method": "GET",
            "path": "/items/MLA123",
        }
    )
    assert audit_doc is not None
    assert audit_doc["upstream_status"] == 200
    assert isinstance(audit_doc["duration_ms"], int)


@pytest.mark.asyncio
async def test_proxy_retries_transient_upstream_502(
    proxy_client: httpx.AsyncClient, proxy_db: Any
) -> None:
    _, database = proxy_db
    _seed_account(database)

    async def fast_sleep(_delay_s: float) -> None:
        return None

    app.state.proxy_retry_sleep = fast_sleep

    with respx.mock(assert_all_called=True) as respx_mock:
        upstream = respx_mock.get("https://api.mercadolibre.com/items/MLA123").mock(
            side_effect=[
                httpx.Response(502),
                httpx.Response(200, json={"id": "MLA123"}),
            ]
        )

        response = await proxy_client.get("/proxy/meli/items/MLA123", headers=_auth_header())

    assert response.status_code == 200
    assert response.json() == {"id": "MLA123"}
    assert upstream.call_count == 2
    del app.state.proxy_retry_sleep


@pytest.mark.asyncio
async def test_proxy_call_during_refresh_returns_503_after_timeout(
    proxy_client: httpx.AsyncClient, proxy_db: Any
) -> None:
    _, database = proxy_db
    fake_now = datetime.now(UTC)

    def now_fn() -> datetime:
        return fake_now

    async def sleep_fn(delay_s: float) -> None:
        nonlocal fake_now
        fake_now += timedelta(seconds=delay_s)

    app.state.proxy_wait_now = now_fn
    app.state.proxy_wait_sleep = sleep_fn
    _seed_account(
        database,
        status="refresh_pending",
        lock_held_until=fake_now + timedelta(seconds=120),
    )

    with respx.mock(assert_all_called=False) as respx_mock:
        upstream = respx_mock.get("https://api.mercadolibre.com/items/MLA123")
        response = await proxy_client.get("/proxy/meli/items/MLA123", headers=_auth_header())

    assert response.status_code == 503
    assert response.json() == {"error": "token_refresh_timeout"}
    assert response.headers["Retry-After"] == "5"
    assert upstream.call_count == 0
    del app.state.proxy_wait_now
    del app.state.proxy_wait_sleep


@pytest.mark.asyncio
async def test_proxy_call_waits_for_refresh_then_forwards(
    proxy_client: httpx.AsyncClient, proxy_db: Any
) -> None:
    _, database = proxy_db
    fake_now = datetime.now(UTC)
    refresh_completed = False

    def now_fn() -> datetime:
        return fake_now

    async def sleep_fn(delay_s: float) -> None:
        nonlocal fake_now, refresh_completed
        fake_now += timedelta(seconds=delay_s)
        if refresh_completed:
            return
        refresh_completed = True
        access_enc = encrypt_token("fresh-meli-access-token", account_id="123456789")
        refresh_enc = encrypt_token("fresh-meli-refresh-token", account_id="123456789")
        database.meli_accounts.update_one(
            {"seller_id": 123456789},
            {
                "$set": {
                    "status": "active",
                    "access_token_ciphertext": access_enc.ciphertext,
                    "access_token_dek_wrapped": access_enc.dek_wrapped,
                    "refresh_token_ciphertext": refresh_enc.ciphertext,
                    "refresh_token_dek_wrapped": refresh_enc.dek_wrapped,
                    "token_nonce": access_enc.nonce,
                    "refresh_token_nonce": refresh_enc.nonce,
                    "lock_held_until": None,
                    "updated_at": fake_now,
                }
            },
        )

    app.state.proxy_wait_now = now_fn
    app.state.proxy_wait_sleep = sleep_fn
    _seed_account(
        database,
        status="refresh_pending",
        lock_held_until=fake_now + timedelta(seconds=120),
    )

    with respx.mock(assert_all_called=True) as respx_mock:
        upstream = respx_mock.get("https://api.mercadolibre.com/items/MLA123").mock(
            return_value=httpx.Response(200, json={"id": "MLA123"})
        )
        response = await proxy_client.get("/proxy/meli/items/MLA123", headers=_auth_header())

    assert response.status_code == 200
    assert response.json() == {"id": "MLA123"}
    assert upstream.calls.last.request.headers["Authorization"] == "Bearer fresh-meli-access-token"
    del app.state.proxy_wait_now
    del app.state.proxy_wait_sleep


@pytest.mark.asyncio
async def test_proxy_unknown_module_returns_401(
    proxy_client: httpx.AsyncClient, proxy_db: Any
) -> None:
    _, database = proxy_db
    _seed_account(database)

    with respx.mock(assert_all_called=False) as respx_mock:
        upstream = respx_mock.get("https://api.mercadolibre.com/items/MLA123")
        response = await proxy_client.get(
            "/proxy/meli/items/MLA123", headers=_auth_header(module_id="unknown")
        )

    assert response.status_code == 401
    assert upstream.call_count == 0


@pytest.mark.asyncio
async def test_proxy_out_of_scope_path_returns_403(
    proxy_client: httpx.AsyncClient, proxy_db: Any
) -> None:
    _, database = proxy_db
    _seed_account(database)

    with respx.mock(assert_all_called=False) as respx_mock:
        upstream = respx_mock.post("https://api.mercadolibre.com/items/MLA123")
        response = await proxy_client.post(
            "/proxy/meli/items/MLA123", headers=_auth_header(), json={"price": 100}
        )

    assert response.status_code == 403
    assert upstream.call_count == 0


@pytest.mark.asyncio
async def test_rate_limit_exceeded_returns_429(
    proxy_client: httpx.AsyncClient, proxy_db: Any
) -> None:
    _, database = proxy_db
    _seed_account(database)
    now = datetime.now(UTC)
    window_start = datetime.fromtimestamp(
        int(now.timestamp()) - (int(now.timestamp()) % 60), tz=UTC
    )
    database.rate_limit_counters.insert_one(
        {
            "_id": "repricer:123456789",
            "module_id": "repricer",
            "seller_id": Int64(123456789),
            "window_start": window_start,
            "count": 60,
            "updated_at": now,
        }
    )

    with respx.mock(assert_all_called=False) as respx_mock:
        upstream = respx_mock.get("https://api.mercadolibre.com/items/MLA123")
        response = await proxy_client.get("/proxy/meli/items/MLA123", headers=_auth_header())

    assert response.status_code == 429
    assert "Retry-After" in response.headers
    assert upstream.call_count == 0
