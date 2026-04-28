from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime
from typing import Any, Literal, overload
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


class FakeOAuthStateCollection:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}

    async def insert_one(self, document: dict[str, Any]) -> None:
        self.documents[str(document["_id"])] = dict(document)

    async def find_one_and_delete(self, filter_spec: dict[str, Any]) -> dict[str, Any] | None:
        doc = self.documents.pop(str(filter_spec["_id"]), None)
        if doc is None:
            return None
        return dict(doc)


class FakeAsyncDatabase:
    def __init__(self) -> None:
        self.meli_accounts = FakeAsyncCollection()
        self.meli_oauth_state = FakeOAuthStateCollection()

    @overload
    def __getitem__(self, collection_name: Literal["meli_accounts"]) -> FakeAsyncCollection: ...

    @overload
    def __getitem__(
        self, collection_name: Literal["meli_oauth_state"]
    ) -> FakeOAuthStateCollection: ...

    @overload
    def __getitem__(
        self, collection_name: str
    ) -> FakeAsyncCollection | FakeOAuthStateCollection: ...

    def __getitem__(self, collection_name: str) -> FakeAsyncCollection | FakeOAuthStateCollection:
        if collection_name == "meli_accounts":
            return self.meli_accounts
        if collection_name == "meli_oauth_state":
            return self.meli_oauth_state
        raise AssertionError(collection_name)


def _pkce_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _seed_oauth_state(
    database: FakeAsyncDatabase,
    *,
    state: str = "state-1",
    platform_user_id: str = "platform-user-123",
    code_verifier: str = "verifier-abcdefghijklmnopqrstuvwxyz-1234567890",
) -> str:
    database.meli_oauth_state.documents[state] = {
        "_id": state,
        "platform_user_id": platform_user_id,
        "code_verifier": code_verifier,
        "created_at": datetime.now(UTC),
    }
    return state


@pytest.fixture
def fake_mongo_db(monkeypatch: pytest.MonkeyPatch) -> Any:
    database = FakeAsyncDatabase()
    app.state.mongo_db = database
    reset_dek_cache()
    set_kms_client(FakeKmsClient())
    monkeypatch.setenv("MELI_CLIENT_ID", "meli-client-id-test")
    monkeypatch.setenv("MELI_CLIENT_SECRET", "meli-client-secret-test")
    monkeypatch.setenv("MELI_REDIRECT_URI", "https://gateway.test/oauth/callback")
    yield database


@pytest.mark.asyncio
async def test_authorize_redirects_with_pkce_and_persists_state(
    fake_mongo_db: FakeAsyncDatabase,
) -> None:
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
    assert params["code_challenge_method"] == ["S256"]
    state = params["state"][0]
    assert state
    assert params["code_challenge"][0]

    state_doc = fake_mongo_db.meli_oauth_state.documents[state]
    assert state_doc["_id"] == state
    assert state_doc["platform_user_id"] == "platform-user-123"
    assert len(state_doc["code_verifier"]) >= 32
    assert params["code_challenge"] == [_pkce_challenge(str(state_doc["code_verifier"]))]
    assert isinstance(state_doc["created_at"], datetime)
    assert state_doc["created_at"].tzinfo == UTC


@pytest.mark.asyncio
async def test_authorize_rejects_empty_platform_user_id(
    fake_mongo_db: FakeAsyncDatabase,
) -> None:
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://gateway.test") as client:
        response = await client.get("/oauth/authorize", params={"platform_user_id": "   "})

    assert response.status_code == 400
    assert fake_mongo_db.meli_oauth_state.documents == {}


@pytest.mark.asyncio
async def test_authorize_generates_unique_state_and_verifier(
    fake_mongo_db: FakeAsyncDatabase,
) -> None:
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://gateway.test") as client:
        first = await client.get(
            "/oauth/authorize", params={"platform_user_id": "platform-user-123"}
        )
        second = await client.get(
            "/oauth/authorize", params={"platform_user_id": "platform-user-123"}
        )

    first_state = parse_qs(urlparse(first.headers["location"]).query)["state"][0]
    second_state = parse_qs(urlparse(second.headers["location"]).query)["state"][0]
    assert first_state != second_state
    assert len(fake_mongo_db.meli_oauth_state.documents) == 2
    assert (
        fake_mongo_db.meli_oauth_state.documents[first_state]["code_verifier"]
        != fake_mongo_db.meli_oauth_state.documents[second_state]["code_verifier"]
    )


@pytest.mark.asyncio
async def test_callback_consumes_state_and_sends_code_verifier(
    fake_mongo_db: FakeAsyncDatabase,
) -> None:
    state = _seed_oauth_state(fake_mongo_db)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://gateway.test") as client:
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
    assert "state-1" not in fake_mongo_db.meli_oauth_state.documents
    token_request = token_route.calls.last.request
    token_form = parse_qs(token_request.content.decode())
    assert token_form["grant_type"] == ["authorization_code"]
    assert token_form["code"] == ["valid-code"]
    assert token_form["redirect_uri"] == ["https://gateway.test/oauth/callback"]
    assert token_form["client_id"] == ["meli-client-id-test"]
    assert token_form["client_secret"] == ["meli-client-secret-test"]
    assert token_form["code_verifier"] == ["verifier-abcdefghijklmnopqrstuvwxyz-1234567890"]

    stored = await fake_mongo_db["meli_accounts"].find_one(
        {"seller_id": 123456789, "app_id": "zeler-platform"}
    )
    assert stored is not None
    assert stored["platform_user_id"] == "platform-user-123"
    assert stored["seller_id"] == 123456789
    assert stored["app_id"] == "zeler-platform"
    assert stored["status"] == "active"
    assert stored["scopes"] == ["read", "write"]
    assert stored["schema_version"] == 1
    assert isinstance(stored["created_at"], datetime)
    assert isinstance(stored["updated_at"], datetime)
    assert isinstance(stored["connected_at"], datetime)
    assert isinstance(stored["last_refreshed_at"], datetime)
    assert stored["access_token_ciphertext"] != "access-token-plain"  # noqa: S105
    assert stored["refresh_token_ciphertext"] != "refresh-token-plain"  # noqa: S105
    assert stored["access_token_dek_wrapped"]
    assert stored["refresh_token_dek_wrapped"]
    assert isinstance(stored["expires_at"], datetime)
    assert stored["expires_at"].tzinfo == UTC


@pytest.mark.asyncio
async def test_callback_invalid_state_returns_400(fake_mongo_db: FakeAsyncDatabase) -> None:
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://gateway.test") as client:
        with respx.mock(assert_all_called=False) as respx_mock:
            token_route = respx_mock.post("https://api.mercadolibre.com/oauth/token").mock(
                return_value=httpx.Response(200, json={"access_token": "unused"})
            )
            response = await client.get(
                "/oauth/callback", params={"code": "valid-code", "state": "missing-state"}
            )

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_state"}
    assert not token_route.called
    assert fake_mongo_db["meli_accounts"].documents == {}


@pytest.mark.asyncio
async def test_callback_state_consumed_only_once(fake_mongo_db: FakeAsyncDatabase) -> None:
    state = _seed_oauth_state(fake_mongo_db)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://gateway.test") as client:
        with respx.mock(assert_all_called=False) as respx_mock:
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
            first = await client.get(
                "/oauth/callback", params={"code": "valid-code", "state": state}
            )
            second = await client.get(
                "/oauth/callback", params={"code": "valid-code", "state": state}
            )

    assert first.status_code == 302
    assert second.status_code == 400
    assert second.json() == {"error": "invalid_state"}
    assert len(token_route.calls) == 1


@pytest.mark.asyncio
async def test_callback_propagates_meli_error(fake_mongo_db: FakeAsyncDatabase) -> None:
    state = _seed_oauth_state(fake_mongo_db)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://gateway.test") as client:
        with respx.mock(assert_all_called=True) as respx_mock:
            respx_mock.post("https://api.mercadolibre.com/oauth/token").mock(
                return_value=httpx.Response(400, json={"error": "invalid_grant"})
            )
            response = await client.get(
                "/oauth/callback", params={"code": "expired-code", "state": state}
            )

    assert response.status_code == 400
    assert fake_mongo_db["meli_accounts"].documents == {}


async def _run_oauth_callback(
    fake_mongo_db: FakeAsyncDatabase,
    token_response: httpx.Response,
    *,
    code: str = "valid-code",
) -> httpx.Response:
    state = _seed_oauth_state(fake_mongo_db, state=f"state-{code}")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway.test") as client:
        with respx.mock(assert_all_called=True) as respx_mock:
            respx_mock.post("https://api.mercadolibre.com/oauth/token").mock(
                return_value=token_response
            )
            return await client.get("/oauth/callback", params={"code": code, "state": state})


@pytest.mark.asyncio
async def test_duplicate_connect_preserves_connected_at(
    fake_mongo_db: FakeAsyncDatabase,
) -> None:
    """Spec §1 R1.1: duplicate connect while active preserves connected_at."""
    token_response = httpx.Response(
        200,
        json={
            "access_token": "access-token-plain",
            "refresh_token": "refresh-token-plain",
            "user_id": 123456789,
            "expires_in": 21600,
            "scope": "read write",
        },
    )

    first = await _run_oauth_callback(fake_mongo_db, token_response)
    assert first.status_code == 302
    first_doc = await fake_mongo_db["meli_accounts"].find_one(
        {"seller_id": 123456789, "app_id": "zeler-platform"}
    )
    assert first_doc is not None
    first_connected_at = first_doc["connected_at"]

    # Second connect while status is still 'active' → connected_at must stick.
    second = await _run_oauth_callback(fake_mongo_db, token_response)
    assert second.status_code == 302
    second_doc = await fake_mongo_db["meli_accounts"].find_one(
        {"seller_id": 123456789, "app_id": "zeler-platform"}
    )
    assert second_doc is not None
    assert second_doc["connected_at"] == first_connected_at
    # But last_refreshed_at must be updated on each call.
    assert second_doc["last_refreshed_at"] >= first_doc["last_refreshed_at"]


@pytest.mark.asyncio
async def test_relink_after_revoked_updates_connected_at(
    fake_mongo_db: FakeAsyncDatabase,
) -> None:
    """Spec §1 R1.1 line 185: re-link from revoked bumps connected_at."""
    token_response = httpx.Response(
        200,
        json={
            "access_token": "access-token-plain",
            "refresh_token": "refresh-token-plain",
            "user_id": 123456789,
            "expires_in": 21600,
            "scope": "read write",
        },
    )

    first = await _run_oauth_callback(fake_mongo_db, token_response)
    assert first.status_code == 302
    first_doc = await fake_mongo_db["meli_accounts"].find_one(
        {"seller_id": 123456789, "app_id": "zeler-platform"}
    )
    assert first_doc is not None
    first_connected_at = first_doc["connected_at"]

    # Flip the stored doc to 'revoked' to simulate an invalid_grant path.
    fake_mongo_db["meli_accounts"].documents[(123456789, "zeler-platform")]["status"] = "revoked"

    # Re-link should mint a new connected_at, strictly greater.
    relink = await _run_oauth_callback(fake_mongo_db, token_response, code="new-code")
    assert relink.status_code == 302
    relinked_doc = await fake_mongo_db["meli_accounts"].find_one(
        {"seller_id": 123456789, "app_id": "zeler-platform"}
    )
    assert relinked_doc is not None
    assert relinked_doc["status"] == "active"
    assert relinked_doc["connected_at"] > first_connected_at
