from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from zeler_platform_core.repos import ItemRepo, MeliAccountRepo

NOW = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)


class FakeCursor:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.documents = documents
        self.sort_spec: list[tuple[str, int]] | None = None
        self.skip_count = 0
        self.limit_count = 0

    def sort(self, sort_spec: list[tuple[str, int]]) -> FakeCursor:
        self.sort_spec = sort_spec
        return self

    def skip(self, count: int) -> FakeCursor:
        self.skip_count = count
        return self

    def limit(self, count: int) -> FakeCursor:
        self.limit_count = count
        return self

    async def to_list(self, length: int) -> list[dict[str, Any]]:
        end = self.skip_count + min(length, self.limit_count or length)
        return self.documents[self.skip_count : end]


class FakeCollection:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.documents = documents
        self.filters: list[dict[str, Any]] = []
        self.cursor = FakeCursor(documents)

    async def find_one(self, filter_spec: dict[str, Any]) -> dict[str, Any] | None:
        self.filters.append(filter_spec)
        return next(
            (doc for doc in self.documents if all(doc.get(k) == v for k, v in filter_spec.items())),
            None,
        )

    def find(self, filter_spec: dict[str, Any]) -> FakeCursor:
        self.filters.append(filter_spec)
        filtered = [
            doc for doc in self.documents if all(doc.get(k) == v for k, v in filter_spec.items())
        ]
        self.cursor = FakeCursor(filtered)
        return self.cursor


class FakeDatabase(dict[str, FakeCollection]):
    def __getitem__(self, collection_name: str) -> FakeCollection:
        return super().__getitem__(collection_name)


class FakeClient:
    def __init__(self, database: FakeDatabase) -> None:
        self.database = database

    def get_default_database(self) -> FakeDatabase:
        return self.database


def _account_doc() -> dict[str, Any]:
    return {
        "_id": "507f1f77bcf86cd799439011",
        "seller_id": "123",
        "nickname": "TEST_SELLER",
        "app_id": "zeler-platform",
        "platform_user_id": "platform-user-1",
        "access_token_ciphertext": "access-ciphertext",
        "access_token_dek_wrapped": "access-dek",
        "refresh_token_ciphertext": "refresh-ciphertext",
        "refresh_token_dek_wrapped": "refresh-dek",
        "token_nonce": "nonce",
        "refresh_token_nonce": "refresh-nonce",
        "scopes": ["read"],
        "status": "active",
        "expires_at": NOW,
        "created_at": NOW,
        "updated_at": NOW,
        "kms_key_version": "kms-v1",
        "schema_version": 1,
    }


def _item_doc(item_id: str, seller_id: str = "123") -> dict[str, Any]:
    return {
        "_id": item_id,
        "seller_id": seller_id,
        "title": f"Item {item_id}",
        "price": Decimal("10.00"),
        "base_price": Decimal("12.00"),
        "available_quantity": 3,
        "status": "active",
        "category_id": "MLM-CAT",
        "last_meli_sync_at": NOW,
        "date_created": NOW,
        "last_updated": NOW,
        "schema_version": 1,
    }


@pytest.mark.asyncio
async def test_meli_account_repo_get_by_user_id_is_read_only_and_filters_platform_user() -> None:
    database = FakeDatabase({"meli_accounts": FakeCollection([_account_doc()])})
    repo = MeliAccountRepo(FakeClient(database))

    account = await repo.get_by_user_id("platform-user-1")

    assert account is not None
    assert account.platform_user_id == "platform-user-1"
    assert database["meli_accounts"].filters == [{"platform_user_id": "platform-user-1"}]
    assert not hasattr(repo, "insert")
    assert repo.save(_account_doc()) is NotImplemented


@pytest.mark.asyncio
async def test_item_repo_list_by_seller_applies_seller_filter_and_pagination() -> None:
    database = FakeDatabase(
        {
            "items": FakeCollection(
                [_item_doc("MLM1"), _item_doc("MLM2"), _item_doc("MLM3"), _item_doc("MLM9", "999")]
            )
        }
    )
    repo = ItemRepo(FakeClient(database))

    items = await repo.list_by_seller("123", status="active", limit=2, offset=1)

    assert [item.id for item in items] == ["MLM2", "MLM3"]
    assert database["items"].filters == [{"seller_id": "123", "status": "active"}]
    assert database["items"].cursor.sort_spec == [("last_updated", -1)]
    assert database["items"].cursor.skip_count == 1
    assert database["items"].cursor.limit_count == 2
