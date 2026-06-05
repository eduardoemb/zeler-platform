from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from google_test_fakes import FakeKmsClient, fake_kms_client
from pydantic import SecretStr

from zeler_sheets.consumer import SheetsEvent, SheetsEventHandler
from zeler_sheets.google_sheets_client import make_sheets_client
from zeler_sheets.google_token_encryption import encrypt_token
from zeler_sheets.sheets_config import SheetsSettings

__all__ = ["fake_kms_client"]


class FakeCollection:
    def __init__(self, documents: dict[str, dict[str, Any]] | None = None) -> None:
        self.documents = documents or {}

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        for doc in self.documents.values():
            if all(doc.get(key) == value for key, value in query.items()):
                return dict(doc)
        return None

    async def update_one(
        self, filter_spec: dict[str, Any], update_spec: dict[str, Any], *, upsert: bool = False
    ) -> FakeWriteResult:
        doc_id = str(filter_spec["_id"])
        existing = dict(self.documents.get(doc_id, {}))
        if existing or upsert:
            self.documents[doc_id] = {
                **update_spec.get("$setOnInsert", {}),
                **existing,
                **update_spec.get("$set", {}),
                "_id": doc_id,
            }
            return FakeWriteResult(
                upserted_id=doc_id if upsert and not existing else None,
                matched_count=1 if existing else 0,
                modified_count=1 if existing else 0,
            )
        return FakeWriteResult(matched_count=0, modified_count=0)

    async def replace_one(
        self, filter_spec: dict[str, Any], replacement: dict[str, Any], *, upsert: bool = False
    ) -> FakeWriteResult:
        doc_id = str(filter_spec["_id"])
        existing = doc_id in self.documents
        if existing or upsert:
            self.documents[doc_id] = dict(replacement)
            return FakeWriteResult(
                upserted_id=doc_id if upsert and not existing else None,
                matched_count=1 if existing else 0,
                modified_count=1 if existing else 0,
            )
        return FakeWriteResult(matched_count=0, modified_count=0)

    def find(self, query: dict[str, Any]) -> FakeCursor:
        return FakeCursor(
            [
                dict(doc)
                for doc in self.documents.values()
                if all(doc.get(key) == value for key, value in query.items())
            ]
        )


class FakeCursor:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self._documents = documents

    async def to_list(self, length: int | None = None) -> list[dict[str, Any]]:
        if length is None:
            return list(self._documents)
        return list(self._documents[:length])


class FakeWriteResult:
    def __init__(
        self, *, matched_count: int = 1, modified_count: int = 1, upserted_id: str | None = None
    ) -> None:
        self.matched_count = matched_count
        self.modified_count = modified_count
        self.upserted_id = upserted_id


class FakeDb:
    def __init__(self, token_doc: dict[str, Any]) -> None:
        self.collections = {
            "sheets_exports": FakeCollection(
                {
                    "export-123456789": {
                        "_id": "export-123456789",
                        "seller_id": "123456789",
                        "spreadsheet_id": "spreadsheet-1",
                        "worksheet_name": "Items",
                        "enabled": True,
                    }
                }
            ),
            "google_oauth_tokens": FakeCollection({token_doc["_id"]: token_doc}),
            "items": FakeCollection(),
            "sheets_item_sku_index": FakeCollection(),
            "sheets_item_formula_rows": FakeCollection(),
        }

    def __getitem__(self, name: str) -> FakeCollection:
        return self.collections.setdefault(name, FakeCollection())


class FakeGatewayClient:
    async def fetch_resource(self, *, seller_id: int, path: str) -> dict[str, Any]:
        assert seller_id == 123456789
        assert path == "/items/MLA123"
        return {
            "id": "MLA123",
            "title": "Premium widget",
            "status": "active",
            "price": 149.99,
            "available_quantity": 7,
        }


class FakeIdempotency:
    def __init__(self) -> None:
        self.marked: list[str] = []

    async def is_duplicate(self, key: str) -> bool:
        return False

    async def mark_processed(self, key: str) -> None:
        self.marked.append(key)


def _settings() -> SheetsSettings:
    return SheetsSettings(
        google_oauth_client_id="google-client-id",
        google_oauth_client_secret=SecretStr("google-client-secret"),
        google_oauth_redirect_uri="https://sheets.test/oauth/google/callback",
        kms_project_id="zeler-dev",
    )


def _token_doc(fake_kms_client: FakeKmsClient) -> dict[str, Any]:
    del fake_kms_client
    now = datetime(2026, 4, 26, 12, 0, tzinfo=UTC)
    access = encrypt_token("fresh-access-token", account_id="123456789")
    refresh = encrypt_token("refresh-token", account_id="123456789")
    return {
        "_id": "google-token-123456789",
        "seller_id": "123456789",
        "access_token_ciphertext": access.ciphertext,
        "access_token_dek_wrapped": access.dek_wrapped,
        "token_nonce": access.nonce,
        "refresh_token_ciphertext": refresh.ciphertext,
        "refresh_token_dek_wrapped": refresh.dek_wrapped,
        "refresh_token_nonce": refresh.nonce,
        "kms_key_version": access.kms_key_version,
        "scopes": ["https://www.googleapis.com/auth/spreadsheets"],
        "expires_at": now + timedelta(days=365),
        "status": "active",
        "last_error": None,
        "connected_at": now,
        "created_at": now,
        "updated_at": now,
        "schema_version": 1,
    }


@pytest.mark.asyncio
async def test_consumer_event_appends_row_through_real_google_sheets_client(
    fake_kms_client: FakeKmsClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    append_calls: list[dict[str, Any]] = []

    class FakeRequest:
        def execute(self) -> dict[str, Any]:
            return {"updatedRows": 1}

    class FakeValues:
        def append(self, **kwargs: Any) -> FakeRequest:
            append_calls.append(kwargs)
            return FakeRequest()

    class FakeSpreadsheets:
        def values(self) -> FakeValues:
            return FakeValues()

    class FakeService:
        def spreadsheets(self) -> FakeSpreadsheets:
            return FakeSpreadsheets()

    def fake_build(*args: Any, **kwargs: Any) -> FakeService:
        assert args[:2] == ("sheets", "v4")
        return FakeService()

    monkeypatch.setattr("zeler_sheets.google_sheets_client.build", fake_build)
    db = FakeDb(_token_doc(fake_kms_client))
    idempotency = FakeIdempotency()
    handler = SheetsEventHandler(
        db=db,
        gateway_client=FakeGatewayClient(),
        sheets_client=make_sheets_client(db, fake_kms_client, _settings()),
        idempotency_store=idempotency,
    )

    result = await handler.handle(
        SheetsEvent(
            event_id="event-1",
            event_type="items.price_updated",
            seller_id=123456789,
            resource="/items/MLA123",
            idempotency_key="items:/items/MLA123:event-1",
        )
    )

    assert result == "appended"
    assert append_calls == [
        {
            "spreadsheetId": "spreadsheet-1",
            "range": "Items!A1",
            "valueInputOption": "USER_ENTERED",
            "body": {
                "values": [
                    ["items.price_updated", "MLA123", "Premium widget", "active", "149.99", "7"]
                ]
            },
        }
    ]
    assert idempotency.marked == ["items:/items/MLA123:event-1"]
