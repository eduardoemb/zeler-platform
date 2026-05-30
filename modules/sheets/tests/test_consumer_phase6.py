from __future__ import annotations

import inspect
from datetime import UTC, datetime
from typing import Any

import pytest

from zeler_sheets.consumer import SheetsEvent, SheetsEventHandler


class FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs

    async def to_list(self, *, length: int | None = None) -> list[dict[str, Any]]:
        return self._docs[:length]


class FakeCollection:
    def __init__(self, docs: list[dict[str, Any]] | None = None) -> None:
        self.docs = docs or []
        self.replace_calls: list[tuple[dict[str, Any], dict[str, Any], bool]] = []

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                return doc
        return None

    def find(self, query: dict[str, Any]) -> FakeCursor:
        return FakeCursor(
            [doc for doc in self.docs if all(doc.get(key) == value for key, value in query.items())]
        )

    async def replace_one(
        self, filter_spec: dict[str, Any], replacement: dict[str, Any], *, upsert: bool = False
    ) -> None:
        self.replace_calls.append((dict(filter_spec), dict(replacement), upsert))
        for index, doc in enumerate(self.docs):
            if doc.get("_id") == replacement.get("_id"):
                self.docs[index] = dict(replacement)
                return
        self.docs.append(dict(replacement))


class FakeDb:
    def __init__(self, export: dict[str, Any] | None | bool = True) -> None:
        export_docs = []
        if export is True:
            export_docs = [
                {
                    "_id": "export-1",
                    "seller_id": "123456789",
                    "spreadsheet_id": "sheet-123",
                    "worksheet_name": "Items",
                    "enabled": True,
                    "created_at": datetime(2026, 4, 24, 12, 0, tzinfo=UTC),
                    "updated_at": datetime(2026, 4, 24, 12, 0, tzinfo=UTC),
                    "schema_version": 1,
                }
            ]
        elif isinstance(export, dict):
            export_docs = [export]
        self.collections = {
            "sheets_exports": FakeCollection(export_docs),
        }

    def __getitem__(self, name: str) -> FakeCollection:
        return self.collections.setdefault(name, FakeCollection())


class FakeGatewayClient:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str]] = []

    async def fetch_resource(self, *, seller_id: int, path: str) -> dict[str, Any]:
        self.calls.append((seller_id, path))
        return {
            "id": "MLA123",
            "title": "Premium widget",
            "status": "active",
            "price": 149.99,
            "base_price": 149.99,
            "available_quantity": 7,
            "category_id": "MLA123",
            "attributes": [{"id": "SELLER_SKU", "value_name": "sku-123"}],
            "date_created": "2026-04-20T12:30:00Z",
            "last_updated": "2026-04-24T12:30:00Z",
        }


class FakeSheetsClient:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, list[str], str]] = []

    async def append_row(
        self,
        *,
        seller_id: str,
        spreadsheet_id: str,
        worksheet_name: str,
        row: list[str],
        idempotency_key: str,
    ) -> None:
        self.rows.append((seller_id, spreadsheet_id, worksheet_name, row, idempotency_key))


class FakeIdempotency:
    def __init__(self, duplicate: bool = False) -> None:
        self.duplicate = duplicate
        self.marked: list[str] = []

    async def is_duplicate(self, key: str) -> bool:
        return self.duplicate

    async def mark_processed(self, key: str) -> None:
        self.marked.append(key)


@pytest.mark.asyncio
async def test_google_sheets_client_protocol_requires_seller_id_kwarg() -> None:
    from zeler_sheets.consumer import GoogleSheetsClient

    signature = inspect.signature(GoogleSheetsClient.append_row)

    assert "seller_id" in signature.parameters
    assert signature.parameters["seller_id"].kind is inspect.Parameter.KEYWORD_ONLY
    assert signature.parameters["seller_id"].annotation == "str"


@pytest.mark.asyncio
async def test_item_event_triggers_sheets_append() -> None:
    gateway = FakeGatewayClient()
    sheets = FakeSheetsClient()
    idempotency = FakeIdempotency()
    handler = SheetsEventHandler(
        db=FakeDb(),
        gateway_client=gateway,
        sheets_client=sheets,
        idempotency_store=idempotency,
    )

    result = await handler.handle(
        SheetsEvent(
            event_id="event-1",
            event_type="items.updated",
            seller_id=123456789,
            resource="/items/MLA123",
            idempotency_key="items:/items/MLA123:event-1",
        )
    )

    assert result == "appended"
    assert gateway.calls == [(123456789, "/items/MLA123")]
    assert sheets.rows == [
        (
            "123456789",
            "sheet-123",
            "Items",
            ["items.updated", "MLA123", "Premium widget", "active", "149.99", "7"],
            "items:/items/MLA123:event-1",
        )
    ]
    assert idempotency.marked == ["items:/items/MLA123:event-1"]
    assert handler._db["items"].docs[0]["_id"] == "MLA123"
    assert handler._db["sheets_item_sku_index"].docs[0]["normalized_sku"] == "SKU-123"
    assert handler._db["sheets_item_formula_rows"].docs[0]["item_id"] == "MLA123"


@pytest.mark.asyncio
async def test_supported_event_persists_even_without_export_config() -> None:
    gateway = FakeGatewayClient()
    sheets = FakeSheetsClient()
    idempotency = FakeIdempotency()
    db = FakeDb(export=None)
    handler = SheetsEventHandler(
        db=db,
        gateway_client=gateway,
        sheets_client=sheets,
        idempotency_store=idempotency,
    )

    result = await handler.handle(
        SheetsEvent(
            event_id="event-1",
            event_type="items.updated",
            seller_id=123456789,
            resource="/items/MLA123",
            idempotency_key="items:/items/MLA123:event-1",
        )
    )

    assert result == "no_export"
    assert gateway.calls == [(123456789, "/items/MLA123")]
    assert db["items"].docs[0]["_id"] == "MLA123"
    assert sheets.rows == []
    assert idempotency.marked == ["items:/items/MLA123:event-1"]


@pytest.mark.asyncio
async def test_persistence_failure_does_not_append_or_mark_processed() -> None:
    class FailingPersistence:
        async def persist(self, **_: Any) -> None:
            raise RuntimeError("mongo unavailable")

    gateway = FakeGatewayClient()
    sheets = FakeSheetsClient()
    idempotency = FakeIdempotency()
    handler = SheetsEventHandler(
        db=FakeDb(),
        gateway_client=gateway,
        sheets_client=sheets,
        idempotency_store=idempotency,
        event_persistence=FailingPersistence(),
    )

    with pytest.raises(RuntimeError, match="mongo unavailable"):
        await handler.handle(
            SheetsEvent(
                event_id="event-1",
                event_type="items.updated",
                seller_id=123456789,
                resource="/items/MLA123",
                idempotency_key="items:/items/MLA123:event-1",
            )
        )

    assert gateway.calls == [(123456789, "/items/MLA123")]
    assert sheets.rows == []
    assert idempotency.marked == []


@pytest.mark.asyncio
async def test_duplicate_event_skipped() -> None:
    gateway = FakeGatewayClient()
    sheets = FakeSheetsClient()
    handler = SheetsEventHandler(
        db=FakeDb(),
        gateway_client=gateway,
        sheets_client=sheets,
        idempotency_store=FakeIdempotency(duplicate=True),
    )

    result = await handler.handle(
        SheetsEvent(
            event_id="event-1",
            event_type="items.updated",
            seller_id=123456789,
            resource="/items/MLA123",
            idempotency_key="items:/items/MLA123:event-1",
        )
    )

    assert result == "duplicate"
    assert gateway.calls == []
    assert sheets.rows == []
