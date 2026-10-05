from __future__ import annotations

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
from infra.mongo.apply_validators import apply_validators
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
def proxy_db(default_mongo_uri: str) -> Iterator[Any]:
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
    database.drop_collection("module_registry")
    database.drop_collection("audit_log")
    database.drop_collection("rate_limit_counters")
    apply_validators(mongo_uri, SCHEMAS_DIR)
    database.module_registry.insert_one(
        {
            "_id": "repricer",
            "version": "0.1.0",
            "allowed_meli_scopes": ["GET /items/*"],
            "routing_keys": ["items.*"],
            "status": "enabled",
            "schema_version": 1,
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
            "schema_version": 1,
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
async def test_focused_proxy_call_disables_hidden_upstream_retry(
    proxy_client: httpx.AsyncClient, proxy_db: Any
) -> None:
    _, database = proxy_db
    _seed_account(database)

    with respx.mock(assert_all_called=True) as respx_mock:
        upstream = respx_mock.get("https://api.mercadolibre.com/items/MLA123").mock(
            side_effect=[httpx.Response(502), httpx.Response(200, json={"id": "unexpected"})]
        )
        response = await proxy_client.get(
            "/proxy/meli/items/MLA123",
            headers={**_auth_header(), "X-Zeler-Proxy-Retry": "disabled"},
        )

    assert response.status_code == 502
    assert upstream.call_count == 1
    assert response.headers["X-Zeler-Upstream-Attempts"] == "1"


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
async def test_order_proxy_preserves_partial_content_metadata_and_view_headers(
    proxy_client: httpx.AsyncClient,
    proxy_db: Any,
) -> None:
    _, database = proxy_db
    _seed_account(database)
    database.module_registry.update_one(
        {"_id": "repricer"},
        {"$set": {"allowed_meli_scopes": ["GET /orders/*"]}},
    )
    with respx.mock as mock:
        upstream = mock.get("https://api.mercadolibre.com/orders/42").respond(
            206,
            json={"id": 42, "buyer": {}},
            headers={"X-Content-Missing": "buyer,shipping", "X-Private-Upstream": "not-forwarded"},
        )
        response = await proxy_client.get(
            "/proxy/meli/orders/42",
            headers={**_auth_header(), "X-Api-Version": "2", "X-New-Domain": "true"},
        )
    assert response.status_code == 206
    assert response.json() == {"id": 42, "buyer": {}}
    assert response.headers["X-Content-Missing"] == "buyer,shipping"
    assert "X-Private-Upstream" not in response.headers
    assert upstream.calls.last.request.headers["X-Api-Version"] == "2"
    assert upstream.calls.last.request.headers["X-New-Domain"] == "true"


@pytest.mark.asyncio
async def test_rate_limit_exceeded_returns_429(
    proxy_client: httpx.AsyncClient, proxy_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GATEWAY_PROXY_RATE_LIMIT", "60")
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


def _seed_history_credit(database: Any, execution_id: str) -> None:
    database.sheets_history_backfill_plans.delete_many({})
    database.sheets_history_backfill_plans.insert_one(
        {
            "_id": "123456789",
            "seller_id": "123456789",
            "state": "active",
            "eligible": True,
            "policy_version": "history-on-link-v1",
            "sources": ["orders"],
            "authority": {"kind": "account_link_policy"},
            "execution_id": execution_id,
            "execution_consumed": 1,
            "execution_attempt_limit": 1,
            "execution_charged": {execution_id: {"orders": {"initial": 1}}},
            "budget": {"orders": {"consumed": 1}},
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 401, 502])
async def test_history_authenticated_proxy_traces_exactly_one_physical_attempt(
    proxy_client: httpx.AsyncClient,
    proxy_db: Any,
    status: int,
) -> None:
    _, database = proxy_db
    _seed_account(database)
    database.module_registry.insert_one(
        {
            "_id": "sheets",
            "version": "0.1.0",
            "allowed_meli_scopes": ["GET /orders/*"],
            "routing_keys": [],
            "status": "enabled",
            "schema_version": 1,
        }
    )
    _seed_history_credit(database, "a" * 32)
    trace = "h1-" + "a" * 32 + ":orders:initial"
    with respx.mock(assert_all_called=True) as mock:
        upstream = mock.get("https://api.mercadolibre.com/orders/1").mock(
            return_value=httpx.Response(status, json={})
        )
        response = await proxy_client.get(
            "/proxy/meli/orders/1",
            headers={
                **_auth_header(module_id="sheets"),
                "X-Zeler-Proxy-Retry": "disabled",
                "X-Zeler-History-Trace": trace,
            },
        )
    assert response.status_code == status and upstream.call_count == 1
    audit = database.audit_log.find_one({"trace_id": trace})
    assert audit is not None and audit["upstream_status"] == status
    plan = database.sheets_history_backfill_plans.find_one({"_id": "123456789"})
    assert plan["execution_sent"] == 1
    assert plan["execution_sent_by_source"] == {"a" * 32: {"orders": {"initial": 1}}}
    with respx.mock(assert_all_called=False) as mock:
        replay_upstream = mock.get("https://api.mercadolibre.com/orders/1")
        replay = await proxy_client.get(
            "/proxy/meli/orders/1",
            headers={
                **_auth_header(module_id="sheets"),
                "X-Zeler-Proxy-Retry": "disabled",
                "X-Zeler-History-Trace": trace,
            },
        )
    assert replay.status_code == 412 and replay_upstream.call_count == 0
    assert (
        database.sheets_history_backfill_plans.find_one({"_id": "123456789"})["execution_sent"] == 1
    )


@pytest.mark.asyncio
async def test_history_transport_failure_records_attempt_but_permission_denial_has_no_send(
    proxy_client: httpx.AsyncClient,
    proxy_db: Any,
) -> None:
    _, database = proxy_db
    _seed_account(database)
    database.module_registry.insert_one(
        {
            "_id": "sheets",
            "version": "0.1.0",
            "allowed_meli_scopes": ["GET /orders/*"],
            "routing_keys": [],
            "status": "enabled",
            "schema_version": 1,
        }
    )
    _seed_history_credit(database, "b" * 32)
    trace = "h1-" + "b" * 32 + ":orders:initial"
    headers = {
        **_auth_header(module_id="sheets"),
        "X-Zeler-Proxy-Retry": "disabled",
        "X-Zeler-History-Trace": trace,
    }
    with respx.mock(assert_all_called=True) as mock:
        upstream = mock.get("https://api.mercadolibre.com/orders/1").mock(
            side_effect=httpx.ConnectError("synthetic transport failure")
        )
        with pytest.raises(httpx.ConnectError):
            await proxy_client.get("/proxy/meli/orders/1", headers=headers)
    assert upstream.call_count == 1
    audit = database.audit_log.find_one({"trace_id": trace})
    assert audit is not None and audit["upstream_status"] == 0
    database.audit_log.delete_many({})
    denied = await proxy_client.get(
        "/proxy/meli/messages/packs/1/sellers/123456789",
        headers={
            **headers,
            "X-Zeler-History-Trace": "h1-" + "c" * 32 + ":messages:maintenance",
        },
    )
    assert denied.status_code == 403
    assert database.audit_log.count_documents({}) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"state": "paused"},
        {"execution_until": datetime(2020, 1, 1, tzinfo=UTC)},
        {"execution_utc_day": "2020-01-01"},
        {"execution_consumed": 0},
        {"execution_charged": {"d" * 32: {"orders": {"maintenance": 1}}}},
        {"execution_charged": {"d" * 32: {"messages": {"initial": 1}}}},
        {"execution_attempt_limit": 0},
        {"execution_charged": {"e" * 32: {"orders": {"initial": 1}}}},
        {"execution_charged": {"orders": {"initial": 50}}},
    ],
)
async def test_history_late_policy_guard_denies_without_physical_send(
    proxy_client: httpx.AsyncClient,
    proxy_db: Any,
    changes: dict[str, Any],
) -> None:
    _, database = proxy_db
    _seed_account(database)
    database.module_registry.insert_one(
        {
            "_id": "sheets",
            "version": "0.1.0",
            "allowed_meli_scopes": ["GET /orders/*"],
            "routing_keys": [],
            "status": "enabled",
            "schema_version": 1,
        }
    )
    # This fixture shares its disposable default DB between parameterized tests.
    database.sheets_history_backfill_plans.delete_many({})
    _seed_history_credit(database, "d" * 32)
    database.sheets_history_backfill_plans.update_one({"_id": "123456789"}, {"$set": changes})
    trace = "h1-" + "d" * 32 + ":orders:initial"
    with respx.mock(assert_all_called=False) as mock:
        upstream = mock.get("https://api.mercadolibre.com/orders/1").mock(
            return_value=httpx.Response(200, json={})
        )
        response = await proxy_client.get(
            "/proxy/meli/orders/1",
            headers={
                **_auth_header(module_id="sheets"),
                "X-Zeler-Proxy-Retry": "disabled",
                "X-Zeler-History-Trace": trace,
            },
        )
    assert response.status_code == 412 and upstream.call_count == 0
    assert response.headers["X-Zeler-Upstream-Attempts"] == "0"
    assert response.headers["X-Zeler-History-Policy-Status"] == "wait"
    audit = database.audit_log.find_one({"trace_id": trace})
    assert audit is not None and audit["upstream_status"] == -1 and audit["status"] == 412
    assert (
        database.sheets_history_backfill_plans.find_one({"_id": "123456789"}).get(
            "execution_sent", 0
        )
        == 0
    )
