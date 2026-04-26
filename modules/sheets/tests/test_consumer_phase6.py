from __future__ import annotations

import inspect
from datetime import UTC, datetime
from typing import Any

import pytest

from zeler_sheets.consumer import SheetsEvent, SheetsEventHandler


class FakeCollection:
    def __init__(self, docs: list[dict[str, Any]] | None = None) -> None:
        self.docs = docs or []

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                return doc
        return None


class FakeDb:
    def __init__(self) -> None:
        self.collections = {
            "sheets_exports": FakeCollection(
                [
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
            )
        }

    def __getitem__(self, name: str) -> FakeCollection:
        return self.collections[name]


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
            "available_quantity": 7,
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
