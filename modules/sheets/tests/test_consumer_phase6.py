from __future__ import annotations

import inspect
from datetime import UTC, datetime
from typing import Any

import pytest

from zeler_sheets.consumer import SheetsEvent, SheetsEventHandler


class FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs

    def sort(self, sort_spec: list[tuple[str, int]]) -> FakeCursor:
        docs = list(self._docs)
        for key, direction in reversed(sort_spec):
            docs.sort(key=lambda doc: str(_nested_value(doc, key) or ""), reverse=direction < 0)
        return FakeCursor(docs)

    async def to_list(self, *, length: int | None = None) -> list[dict[str, Any]]:
        return self._docs[:length]


class FakeWriteResult:
    def __init__(
        self, *, matched_count: int = 1, modified_count: int = 1, upserted_id: str | None = None
    ) -> None:
        self.matched_count = matched_count
        self.modified_count = modified_count
        self.upserted_id = upserted_id


class FakeCollection:
    def __init__(self, docs: list[dict[str, Any]] | None = None) -> None:
        self.docs = docs or []
        self.replace_calls: list[tuple[dict[str, Any], dict[str, Any], bool]] = []

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        for doc in self.docs:
            if _matches_filter(doc, query):
                return doc
        return None

    def find(self, query: dict[str, Any]) -> FakeCursor:
        return FakeCursor([doc for doc in self.docs if _matches_filter(doc, query)])

    async def replace_one(
        self, filter_spec: dict[str, Any], replacement: dict[str, Any], *, upsert: bool = False
    ) -> FakeWriteResult:
        self.replace_calls.append((dict(filter_spec), dict(replacement), upsert))
        for index, doc in enumerate(self.docs):
            if _matches_filter(doc, filter_spec):
                self.docs[index] = dict(replacement)
                return FakeWriteResult()
        if upsert:
            self.docs.append(dict(replacement))
            return FakeWriteResult(
                matched_count=0, modified_count=0, upserted_id=str(replacement["_id"])
            )
        return FakeWriteResult(matched_count=0, modified_count=0)

    async def update_one(
        self,
        filter_spec: dict[str, Any],
        update: dict[str, Any],
        *,
        upsert: bool = False,
        bypass_document_validation: bool = False,
    ) -> FakeWriteResult:
        _ = bypass_document_validation
        for doc in self.docs:
            if _matches_filter(doc, filter_spec):
                for path, value in update.get("$set", {}).items():
                    _set_path(doc, path, value)
                for path in update.get("$unset", {}):
                    _unset_path(doc, path)
                return FakeWriteResult()
        if upsert and "$setOnInsert" in update:
            document = dict(update["$setOnInsert"])
            self.docs.append(document)
            return FakeWriteResult(
                matched_count=0, modified_count=0, upserted_id=str(document["_id"])
            )
        return FakeWriteResult(matched_count=0, modified_count=0)


def _matches_filter(document: dict[str, Any], filter_spec: dict[str, Any]) -> bool:
    for key, expected in filter_spec.items():
        if key == "$or":
            if not any(_matches_filter(document, option) for option in expected):
                return False
            continue
        actual = _nested_value(document, key)
        if isinstance(expected, dict) and "$in" in expected:
            if actual not in expected["$in"]:
                return False
            continue
        if isinstance(expected, dict) and "$exists" in expected:
            if (actual is not None) != expected["$exists"]:
                return False
            continue
        if isinstance(expected, dict) and "$lte" in expected:
            if actual is None or actual > expected["$lte"]:
                return False
            continue
        if actual != expected:
            return False
    return True


def _nested_value(document: dict[str, Any], dotted_path: str) -> Any:
    value: Any = document
    for part in dotted_path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _set_path(document: dict[str, Any], dotted_path: str, value: Any) -> None:
    target: Any = document
    parts = dotted_path.split(".")
    for part in parts[:-1]:
        if not isinstance(target.get(part), dict):
            target[part] = {}
        target = target[part]
    target[parts[-1]] = value


def _unset_path(document: dict[str, Any], dotted_path: str) -> None:
    target: Any = document
    parts = dotted_path.split(".")
    for part in parts[:-1]:
        if not isinstance(target, dict) or not isinstance(target.get(part), dict):
            return
        target = target[part]
    if isinstance(target, dict):
        target.pop(parts[-1], None)


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
        self.calls: list[tuple[Any, str]] = []

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


class EnrichmentGatewayClient(FakeGatewayClient):
    async def fetch_resource(self, *, seller_id: int, path: str) -> dict[str, Any]:
        self.calls.append((seller_id, path))
        item_resource = {
            "id": "MLA123",
            "seller_id": str(seller_id),
            "title": "Premium widget",
            "status": "active",
            "price": "149.99",
            "base_price": "149.99",
            "available_quantity": 7,
            "category_id": "MLA123",
            "site_id": "MLA",
            "currency_id": "ARS",
            "listing_type_id": "gold_special",
            "shipping": {"free_shipping": True, "mode": "me2"},
            "attributes": [{"id": "SELLER_SKU", "value_name": "sku-123"}],
            "date_created": "2026-04-20T12:30:00Z",
            "last_updated": "2026-04-24T12:30:00Z",
        }
        if path == "/items/MLA123":
            return item_resource
        if path == "/items?ids=MLA123":
            return {"results": [{"code": 200, "body": item_resource}]}
        if path == f"/users/{seller_id}/shipping_options/free?item_id=MLA123":
            return {"coverage": {"all_country": {"list_cost": "83.25"}}}
        raise AssertionError(path)


class PriceWebhookGatewayClient(FakeGatewayClient):
    async def fetch_resource(self, *, seller_id: int, path: str) -> dict[str, Any]:
        self.calls.append((seller_id, path))
        if path != "/items/MLA123":
            raise AssertionError(path)
        return {
            "id": "MLA123",
            "title": "Canonical price widget",
            "status": "active",
            "price": "199.99",
            "base_price": "249.99",
            "available_quantity": 3,
            "category_id": "MLA123",
            "attributes": [{"id": "SELLER_SKU", "value_name": "sku-123"}],
            "date_created": "2026-04-20T12:30:00Z",
            "last_updated": "2026-04-25T12:30:00Z",
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
async def test_item_event_enrichment_wiring_refreshes_formula_rows_when_enabled() -> None:
    gateway = EnrichmentGatewayClient()
    sheets = FakeSheetsClient()
    idempotency = FakeIdempotency()
    db = FakeDb(export=None)
    handler = SheetsEventHandler(
        db=db,
        gateway_client=gateway,
        sheets_client=sheets,
        idempotency_store=idempotency,
        zelerdata_enrichment_enabled=True,
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
    assert ("123456789", "/items?ids=MLA123") in gateway.calls
    assert (
        "123456789",
        "/users/123456789/shipping_options/free?item_id=MLA123",
    ) in gateway.calls
    item = db["items"].docs[0]
    assert item["seller_shipping_cost"].to_decimal().to_eng_string() == "83.25"
    formula_row = db["sheets_item_formula_rows"].docs[0]
    assert formula_row["current"]["seller_shipping_cost"].to_decimal().to_eng_string() == "83.25"
    assert idempotency.marked == ["items:/items/MLA123:event-1"]


@pytest.mark.asyncio
async def test_item_price_updated_fetches_canonical_item_and_preserves_idempotency_key() -> None:
    gateway = PriceWebhookGatewayClient()
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
            event_id="event-price-1",
            event_type="items.price_updated",
            seller_id=123456789,
            resource="/items/MLA123/prices",
            idempotency_key="items_prices:/items/MLA123/prices:event-price-1",
        )
    )

    assert result == "no_export"
    assert gateway.calls == [(123456789, "/items/MLA123")]
    assert db["items"].docs[0]["price"].to_decimal().to_eng_string() == "199.99"
    assert (
        db["sheets_item_formula_rows"].docs[0]["current"]["price"].to_decimal().to_eng_string()
        == "199.99"
    )
    assert idempotency.marked == ["items_prices:/items/MLA123/prices:event-price-1"]


@pytest.mark.asyncio
async def test_item_price_updated_rejects_malformed_price_resource_before_fetch() -> None:
    gateway = PriceWebhookGatewayClient()
    handler = SheetsEventHandler(
        db=FakeDb(export=None),
        gateway_client=gateway,
        sheets_client=FakeSheetsClient(),
        idempotency_store=FakeIdempotency(),
    )

    with pytest.raises(ValueError, match="items.price_updated resource must be /items/{id}/prices"):
        await handler.handle(
            SheetsEvent(
                event_id="event-price-1",
                event_type="items.price_updated",
                seller_id=123456789,
                resource="/items/MLA123/price_history",
                idempotency_key="items_prices:/items/MLA123/price_history:event-price-1",
            )
        )

    assert gateway.calls == []


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
