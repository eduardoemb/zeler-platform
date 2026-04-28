# ruff: noqa: S105,S106

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from google_test_fakes import fake_kms_client
from test_google_token_store import FakeDb, _store, _token_doc

from zeler_sheets.google_token_encryption import decrypt_token

__all__ = ["fake_kms_client"]


@pytest.mark.asyncio
async def test_get_access_token_handles_naive_expires_at_from_mongo(fake_kms_client) -> None:
    now = datetime(2026, 4, 28, 15, 0, tzinfo=UTC)
    db = FakeDb()
    db.google_oauth_tokens.documents["google-token-seller-1"] = _token_doc(
        seller_id="seller-1",
        access_token="stale-access-token",
        refresh_token="refresh-token",
        expires_at=(now - timedelta(hours=1)).replace(tzinfo=None),
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        refresh_token = await decrypt_token(
            _store(db, fake_kms_client, now=now)._encrypted_refresh_token(
                db.google_oauth_tokens.documents["google-token-seller-1"]
            ),
            account_id="seller-1",
        )
        assert refresh_token == "refresh-token"
        return httpx.Response(200, json={"access_token": "new-access-token", "expires_in": 3600})

    token = await _store(
        db,
        fake_kms_client,
        now=now,
        http_client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    ).get_access_token("seller-1")

    assert token == "new-access-token"
