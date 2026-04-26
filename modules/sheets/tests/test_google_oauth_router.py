from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from google_test_fakes import FakeKmsClient, fake_kms_client
from pydantic import SecretStr

from zeler_sheets.google_token_encryption import EncryptedToken, decrypt_token, encrypt_token
from zeler_sheets.sheets_config import SheetsSettings

__all__ = ["fake_kms_client"]


class FakeUpdateResult:
    modified_count = 1
    upserted_id = None


class FakeDeleteResult:
    deleted_count = 1


class FakeCollection:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}

    async def insert_one(self, document: dict[str, Any]) -> None:
        self.documents[str(document["_id"])] = dict(document)

    async def find_one(self, filter_spec: dict[str, Any]) -> dict[str, Any] | None:
        for doc in self.documents.values():
            if all(doc.get(key) == value for key, value in filter_spec.items()):
                return dict(doc)
        return None

    async def find_one_and_delete(self, filter_spec: dict[str, Any]) -> dict[str, Any] | None:
        found = await self.find_one(filter_spec)
        if found is not None:
            self.documents.pop(str(found["_id"]), None)
        return found

    async def delete_one(self, filter_spec: dict[str, Any]) -> FakeDeleteResult:
        found = await self.find_one(filter_spec)
        if found is not None:
            self.documents.pop(str(found["_id"]), None)
        return FakeDeleteResult()

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
        self.google_oauth_state = FakeCollection()
        self.google_oauth_tokens = FakeCollection()

    def __getitem__(self, name: str) -> FakeCollection:
        return cast(FakeCollection, getattr(self, name))


def _settings() -> SheetsSettings:
    return SheetsSettings(
        google_oauth_client_id="google-client-id",
        google_oauth_client_secret=SecretStr("google-client-secret"),
        google_oauth_redirect_uri="https://sheets.test/oauth/google/callback",
        kms_project_id="zeler-dev",
    )


def _app(
    db: FakeDb,
    fake_kms_client: FakeKmsClient,
    *,
    token_response: httpx.Response | None = None,
    now: datetime | None = None,
) -> FastAPI:
    from zeler_sheets.google_oauth_router import build_router

    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return token_response or httpx.Response(
            200,
            json={"access_token": "access-1", "refresh_token": "refresh-1", "expires_in": 3600},
        )

    app = FastAPI()
    app.state.mongo_db = db
    app.state.kms_client = fake_kms_client
    app.state.settings = _settings()
    app.state.now_fn = lambda: now or datetime(2026, 4, 26, 12, 0, tzinfo=UTC)
    app.state.http_client_factory = lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    )
    app.state.token_requests = requests
    app.include_router(build_router())
    return app


def test_authorize_redirects_with_pkce_and_state(fake_kms_client: FakeKmsClient) -> None:
    db = FakeDb()

    response = TestClient(_app(db, fake_kms_client)).get(
        "/oauth/google/authorize?seller_id=foo", follow_redirects=False
    )

    assert response.status_code == 302
    location = response.headers["location"]
    parsed = urlparse(location)
    params = parse_qs(parsed.query)
    assert parsed.scheme == "https"
    assert parsed.netloc == "accounts.google.com"
    assert params["client_id"] == ["google-client-id"]
    assert params["redirect_uri"] == ["https://sheets.test/oauth/google/callback"]
    assert params["scope"] == ["https://www.googleapis.com/auth/spreadsheets"]
    assert params["code_challenge_method"] == ["S256"]
    assert params["access_type"] == ["offline"]
    assert params["prompt"] == ["consent"]
    assert params["response_type"] == ["code"]
    assert params["state"][0]
    assert params["code_challenge"][0]


def test_authorize_persists_state_doc_in_db(fake_kms_client: FakeKmsClient) -> None:
    db = FakeDb()

    response = TestClient(_app(db, fake_kms_client)).get(
        "/oauth/google/authorize?seller_id=foo", follow_redirects=False
    )

    state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
    doc = db.google_oauth_state.documents[state]
    assert doc["_id"] == state
    assert doc["seller_id"] == "foo"
    assert len(doc["code_verifier"]) >= 32
    assert doc["created_at"] == datetime(2026, 4, 26, 12, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_callback_exchanges_code_and_upserts_token(fake_kms_client: FakeKmsClient) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=UTC)
    db = FakeDb()
    db.google_oauth_state.documents["state-1"] = {
        "_id": "state-1",
        "seller_id": "foo",
        "code_verifier": "verifier-1",
        "created_at": now,
    }
    app = _app(db, fake_kms_client, now=now)

    response = TestClient(app).get("/oauth/google/callback?code=code-1&state=state-1")

    assert response.status_code == 200
    token_doc = db.google_oauth_tokens.documents["google-token-foo"]
    assert token_doc["seller_id"] == "foo"
    assert token_doc["status"] == "active"
    assert token_doc["expires_at"] == now + timedelta(seconds=3600)
    access = await decrypt_token(
        EncryptedToken(
            ciphertext=token_doc["access_token_ciphertext"],
            dek_wrapped=token_doc["access_token_dek_wrapped"],
            nonce=token_doc["token_nonce"],
            kms_key_version=token_doc["kms_key_version"],
        ),
        account_id="foo",
    )
    assert access == "access-1"
    assert "state-1" not in db.google_oauth_state.documents
    assert app.state.token_requests[0].url == httpx.URL("https://oauth2.googleapis.com/token")


def test_callback_invalid_state_returns_400(fake_kms_client: FakeKmsClient) -> None:
    response = TestClient(_app(FakeDb(), fake_kms_client)).get(
        "/oauth/google/callback?code=code-1&state=missing"
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_state"


@pytest.mark.asyncio
async def test_callback_preserves_existing_refresh_token_when_response_omits_it(
    fake_kms_client: FakeKmsClient,
) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=UTC)
    db = FakeDb()
    db.google_oauth_state.documents["state-1"] = {
        "_id": "state-1",
        "seller_id": "foo",
        "code_verifier": "verifier-1",
        "created_at": now,
    }
    refresh = encrypt_token("existing-refresh", account_id="foo")
    db.google_oauth_tokens.documents["google-token-foo"] = {
        "_id": "google-token-foo",
        "seller_id": "foo",
        "refresh_token_ciphertext": refresh.ciphertext,
        "refresh_token_dek_wrapped": refresh.dek_wrapped,
        "refresh_token_nonce": refresh.nonce,
        "kms_key_version": refresh.kms_key_version,
    }
    response = TestClient(
        _app(
            db,
            fake_kms_client,
            token_response=httpx.Response(
                200, json={"access_token": "access-2", "expires_in": 3600}
            ),
            now=now,
        )
    ).get("/oauth/google/callback?code=code-1&state=state-1")

    assert response.status_code == 200
    doc = db.google_oauth_tokens.documents["google-token-foo"]
    preserved = await decrypt_token(
        EncryptedToken(
            ciphertext=doc["refresh_token_ciphertext"],
            dek_wrapped=doc["refresh_token_dek_wrapped"],
            nonce=doc["refresh_token_nonce"],
            kms_key_version=doc["kms_key_version"],
        ),
        account_id="foo",
    )
    assert preserved == "existing-refresh"


def test_callback_returns_400_when_no_refresh_token_and_no_prior_doc(
    fake_kms_client: FakeKmsClient,
) -> None:
    db = FakeDb()
    db.google_oauth_state.documents["state-1"] = {
        "_id": "state-1",
        "seller_id": "foo",
        "code_verifier": "verifier-1",
        "created_at": datetime(2026, 4, 26, 12, 0, tzinfo=UTC),
    }

    response = TestClient(
        _app(
            db,
            fake_kms_client,
            token_response=httpx.Response(
                200, json={"access_token": "access-2", "expires_in": 3600}
            ),
        )
    ).get("/oauth/google/callback?code=code-1&state=state-1")

    assert response.status_code == 400
    assert response.json()["error"] == "consent_required"
    assert db.google_oauth_tokens.documents == {}


def test_callback_propagates_google_invalid_grant_400(fake_kms_client: FakeKmsClient) -> None:
    db = FakeDb()
    db.google_oauth_state.documents["state-1"] = {
        "_id": "state-1",
        "seller_id": "foo",
        "code_verifier": "verifier-1",
        "created_at": datetime(2026, 4, 26, 12, 0, tzinfo=UTC),
    }

    response = TestClient(
        _app(
            db, fake_kms_client, token_response=httpx.Response(400, json={"error": "invalid_grant"})
        )
    ).get("/oauth/google/callback?code=code-1&state=state-1")

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"
    assert db.google_oauth_tokens.documents == {}
