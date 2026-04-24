from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx

from zeler_gateway.app import app
from zeler_gateway.tokens.encryption import reset_dek_cache, set_kms_client


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


class FakeUpdateResult:
    def __init__(self, upserted_id: str | None = "account-1") -> None:
        self.upserted_id = upserted_id
        self.modified_count = 0


class FakeAsyncCollection:
    def __init__(self) -> None:
        self.documents: dict[tuple[int, str], dict[str, Any]] = {}

    async def update_one(
        self, filter_spec: dict[str, Any], update_spec: dict[str, Any], *, upsert: bool
    ) -> FakeUpdateResult:
        assert upsert is True
        key = (filter_spec["seller_id"], filter_spec["app_id"])
        existing = self.documents.get(key, {})
        insert_defaults = update_spec.get("$setOnInsert", {})
        updated = update_spec.get("$set", {})
        self.documents[key] = {**insert_defaults, **existing, **updated}
        return FakeUpdateResult()

    async def find_one(self, filter_spec: dict[str, Any]) -> dict[str, Any] | None:
        return self.documents.get((filter_spec["seller_id"], filter_spec["app_id"]))


class FakeAsyncDatabase:
    def __init__(self) -> None:
        self.meli_accounts = FakeAsyncCollection()

    def __getitem__(self, collection_name: str) -> FakeAsyncCollection:
        assert collection_name == "meli_accounts"
        return self.meli_accounts


@pytest.fixture
def fake_mongo_db(monkeypatch: pytest.MonkeyPatch) -> FakeAsyncDatabase:
    database = FakeAsyncDatabase()
    app.state.mongo_db = database
    reset_dek_cache()
    set_kms_client(FakeKmsClient())
    monkeypatch.setenv("MELI_CLIENT_ID", "meli-client-id-test")
    monkeypatch.setenv("MELI_CLIENT_SECRET", "meli-client-secret-test")
    monkeypatch.setenv("MELI_REDIRECT_URI", "https://gateway.test/oauth/callback")
    return database


@pytest.mark.asyncio
async def test_oauth_authorize_redirects_to_meli(fake_mongo_db: FakeAsyncDatabase) -> None:
    del fake_mongo_db
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://gateway.test") as client:
        response = await client.get(
            "/oauth/authorize", params={"platform_user_id": "platform-user-123"}
        )

    assert response.status_code == 302
    redirect = urlparse(response.headers["location"])
    params = parse_qs(redirect.query)
    assert (
        f"{redirect.scheme}://{redirect.netloc}{redirect.path}"
        == "https://auth.mercadolibre.com/authorization"
    )
    assert params["client_id"] == ["meli-client-id-test"]
    assert params["redirect_uri"] == ["https://gateway.test/oauth/callback"]
    assert params["response_type"] == ["code"]
    assert params["state"][0]


@pytest.mark.asyncio
async def test_oauth_callback_upserts_meli_account(fake_mongo_db: FakeAsyncDatabase) -> None:
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://gateway.test") as client:
        authorize_response = await client.get(
            "/oauth/authorize", params={"platform_user_id": "platform-user-123"}
        )
        state = parse_qs(urlparse(authorize_response.headers["location"]).query)["state"][0]

        with respx.mock(assert_all_called=True) as respx_mock:
            token_route = respx_mock.post("https://api.mercadolibre.com/oauth/token").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "access_token": "access-token-plain",
                        "refresh_token": "refresh-token-plain",
                        "user_id": 123456789,
                        "expires_in": 21600,
                        "scope": "read write",
                    },
                )
            )

            response = await client.get(
                "/oauth/callback", params={"code": "valid-code", "state": state}
            )

    assert response.status_code == 302
    assert token_route.called

    stored = await fake_mongo_db["meli_accounts"].find_one(
        {"seller_id": 123456789, "app_id": "zeler-platform"}
    )
    assert stored is not None
    assert stored["platform_user_id"] == "platform-user-123"
    assert stored["seller_id"] == 123456789
    assert stored["app_id"] == "zeler-platform"
    assert stored["status"] == "active"
    assert stored["scopes"] == ["read", "write"]
    assert stored["access_token_ciphertext"] != "access-token-plain"  # noqa: S105
    assert stored["refresh_token_ciphertext"] != "refresh-token-plain"  # noqa: S105
    assert stored["access_token_dek_wrapped"]
    assert stored["refresh_token_dek_wrapped"]
    assert isinstance(stored["expires_at"], datetime)
    assert stored["expires_at"].tzinfo == UTC


@pytest.mark.asyncio
async def test_oauth_callback_invalid_grant_returns_400(fake_mongo_db: FakeAsyncDatabase) -> None:
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://gateway.test") as client:
        authorize_response = await client.get(
            "/oauth/authorize", params={"platform_user_id": "platform-user-123"}
        )
        state = parse_qs(urlparse(authorize_response.headers["location"]).query)["state"][0]

        with respx.mock(assert_all_called=True):
            respx.post("https://api.mercadolibre.com/oauth/token").mock(
                return_value=httpx.Response(400, json={"error": "invalid_grant"})
            )

            response = await client.get(
                "/oauth/callback", params={"code": "expired-code", "state": state}
            )

    assert response.status_code == 400
    assert fake_mongo_db["meli_accounts"].documents == {}
