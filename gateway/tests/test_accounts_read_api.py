from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI


class FakeCursor:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.documents = documents

    def sort(self, *_args: Any) -> FakeCursor:
        return self

    async def to_list(self, length: int | None = None) -> list[dict[str, Any]]:
        if length is None:
            return self.documents
        return self.documents[:length]


class FakeAccountsCollection:
    def __init__(self) -> None:
        self.documents = [
            {
                "seller_id": 123456789,
                "nickname": "Zeler Shop",
                "platform_user_id": "platform-user-123",
                "status": "active",
                "connected_at": datetime(2026, 4, 24, 12, 0, tzinfo=UTC),
                "last_refreshed_at": datetime(2026, 4, 24, 12, 30, tzinfo=UTC),
                "access_token_ciphertext": b"secret",
                "refresh_token_ciphertext": b"secret",
            },
            {
                "seller_id": 987654321,
                "nickname": "Other Shop",
                "platform_user_id": "other-user",
                "status": "revoked",
            },
        ]

    def find(self, filter_doc: dict[str, Any], projection: dict[str, int]) -> FakeCursor:
        assert projection["access_token_ciphertext"] == 0
        assert projection["refresh_token_ciphertext"] == 0
        return FakeCursor(
            [
                document
                for document in self.documents
                if document.get("platform_user_id") == filter_doc["platform_user_id"]
            ]
        )


class FakeDb:
    def __init__(self) -> None:
        self.meli_accounts = FakeAccountsCollection()

    def __getitem__(self, name: str) -> FakeAccountsCollection:
        assert name == "meli_accounts"
        return self.meli_accounts


@pytest.mark.asyncio
async def test_list_accounts_returns_user_accounts_without_tokens() -> None:
    from zeler_gateway.accounts.router import router

    app = FastAPI()
    app.state.mongo_db = FakeDb()
    app.include_router(router)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://gateway.test"
    ) as client:
        response = await client.get("/api/accounts", params={"user_id": "platform-user-123"})

    assert response.status_code == 200
    assert response.json() == {
        "accounts": [
            {
                "seller_id": 123456789,
                "nickname": "Zeler Shop",
                "status": "active",
                "connected_at": "2026-04-24T12:00:00Z",
                "last_refreshed_at": "2026-04-24T12:30:00Z",
            }
        ]
    }
    assert "access_token_ciphertext" not in response.text
    assert "refresh_token_ciphertext" not in response.text
