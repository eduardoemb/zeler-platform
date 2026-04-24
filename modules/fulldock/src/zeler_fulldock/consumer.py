from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class FulldockEvent:
    event_id: str
    event_type: str
    seller_id: int
    resource: str
    idempotency_key: str


class GatewayClient(Protocol):
    async def request(
        self, method: str, path: str, *, seller_id: str, json: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...


class IdempotencyStore(Protocol):
    async def is_duplicate(self, key: str) -> bool: ...

    async def mark_processed(self, key: str) -> None: ...


class FulldockEventHandler:
    def __init__(
        self,
        *,
        db: Any,
        gateway_client: GatewayClient,
        idempotency_store: IdempotencyStore,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db
        self._gateway_client = gateway_client
        self._idempotency_store = idempotency_store
        self._clock = clock or (lambda: datetime.now(UTC))

    async def handle(self, event: FulldockEvent) -> str:
        if await self._idempotency_store.is_duplicate(event.idempotency_key):
            return "duplicate"

        seller_id = str(event.seller_id)
        resource = await self._gateway_client.request(
            "GET", event.resource, seller_id=seller_id, json=None
        )
        item_ids = item_ids_from_event_resource(event.event_type, event.resource, resource)
        rules = await self._rules_for_items(seller_id=seller_id, item_ids=item_ids)

        if not rules:
            await self._record_history(
                event=event,
                item_id=item_ids[0] if item_ids else "unknown",
                outcome="no_rule",
                rule_id=None,
                stock_locations=[],
            )
            await self._idempotency_store.mark_processed(event.idempotency_key)
            return "no_rule"

        for rule in rules:
            item_id = str(rule["item_id"])
            stock_locations = normalize_stock_locations(rule.get("stock_locations", []))
            await self._gateway_client.request(
                "PUT",
                f"/items/{item_id}/stock_locations",
                seller_id=seller_id,
                json={"locations": stock_locations},
            )
            await self._record_history(
                event=event,
                item_id=item_id,
                outcome="updated",
                rule_id=str(rule["_id"]),
                stock_locations=stock_locations,
            )

        await self._idempotency_store.mark_processed(event.idempotency_key)
        return "updated"

    async def _rules_for_items(
        self, *, seller_id: str, item_ids: list[str]
    ) -> list[dict[str, Any]]:
        rules: list[dict[str, Any]] = []
        for item_id in item_ids:
            found = (
                await self._db["fulldock_inventory_rules"]
                .find({"seller_id": seller_id, "item_id": item_id, "enabled": True})
                .to_list(length=100)
            )
            rules.extend(found)
        return rules

    async def _record_history(
        self,
        *,
        event: FulldockEvent,
        item_id: str,
        outcome: str,
        rule_id: str | None,
        stock_locations: list[dict[str, Any]],
    ) -> None:
        created_at = self._clock()
        await self._db["fulldock_history"].insert_one(
            {
                "_id": f"fulldock-history-{event.idempotency_key}-{item_id}",
                "seller_id": str(event.seller_id),
                "event_id": event.event_id,
                "idempotency_key": event.idempotency_key,
                "event_type": event.event_type,
                "item_id": item_id,
                "outcome": outcome,
                "rule_id": rule_id,
                "stock_locations": stock_locations,
                "created_at": created_at,
                "schema_version": 1,
            }
        )


def item_ids_from_event_resource(
    event_type: str, resource_path: str, resource: dict[str, Any]
) -> list[str]:
    if event_type.startswith("shipments."):
        raw_items = resource.get("items", resource.get("order_items", []))
        if isinstance(raw_items, list):
            return [item_id for item in raw_items if (item_id := item_id_from_payload(item))]
        return []
    item_id = item_id_from_payload(resource) or resource_path.rstrip("/").split("/")[-1]
    return [item_id]


def item_id_from_payload(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("item_id", "id"):
        value = payload.get(key)
        if value is not None:
            return str(value)
    nested_item = payload.get("item")
    if isinstance(nested_item, dict):
        value = nested_item.get("id") or nested_item.get("item_id")
        if value is not None:
            return str(value)
    return None


def normalize_stock_locations(raw_locations: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_locations, list):
        return []
    locations: list[dict[str, Any]] = []
    for location in raw_locations:
        if isinstance(location, dict):
            locations.append(
                {
                    "location_id": str(location["location_id"]),
                    "quantity": int(location["quantity"]),
                }
            )
    return locations
