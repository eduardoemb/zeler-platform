from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class SheetsEvent:
    event_id: str
    event_type: str
    seller_id: int
    resource: str
    idempotency_key: str


class GatewayResourceClient(Protocol):
    async def fetch_resource(self, *, seller_id: int, path: str) -> dict[str, Any]: ...


class GoogleSheetsClient(Protocol):
    async def append_row(
        self,
        *,
        spreadsheet_id: str,
        worksheet_name: str,
        row: list[str],
        idempotency_key: str,
    ) -> None: ...


class IdempotencyStore(Protocol):
    async def is_duplicate(self, key: str) -> bool: ...

    async def mark_processed(self, key: str) -> None: ...


class SheetsEventHandler:
    def __init__(
        self,
        *,
        db: Any,
        gateway_client: GatewayResourceClient,
        sheets_client: GoogleSheetsClient,
        idempotency_store: IdempotencyStore,
    ) -> None:
        self._db = db
        self._gateway_client = gateway_client
        self._sheets_client = sheets_client
        self._idempotency_store = idempotency_store

    async def handle(self, event: SheetsEvent) -> str:
        if await self._idempotency_store.is_duplicate(event.idempotency_key):
            return "duplicate"

        export_config = await self._db["sheets_exports"].find_one(
            {"seller_id": str(event.seller_id), "enabled": True}
        )
        if export_config is None:
            await self._idempotency_store.mark_processed(event.idempotency_key)
            return "no_export"

        resource = await self._gateway_client.fetch_resource(
            seller_id=event.seller_id,
            path=event.resource,
        )
        row = format_resource_row(event.event_type, resource)
        await self._sheets_client.append_row(
            spreadsheet_id=str(export_config["spreadsheet_id"]),
            worksheet_name=str(export_config.get("worksheet_name", "Events")),
            row=row,
            idempotency_key=event.idempotency_key,
        )
        await self._idempotency_store.mark_processed(event.idempotency_key)
        return "appended"


def format_resource_row(event_type: str, resource: dict[str, Any]) -> list[str]:
    resource_id = _first_string(resource, "id", "_id", "order_id", "shipment_id")
    title = _first_string(resource, "title", "description", "status_detail")
    status = _first_string(resource, "status")
    price = _first_string(resource, "price", "total_amount")
    quantity = _first_string(resource, "available_quantity", "quantity")
    return [event_type, resource_id, title, status, price, quantity]


def _first_string(resource: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = resource.get(key)
        if value is not None:
            return str(value)
    return ""
