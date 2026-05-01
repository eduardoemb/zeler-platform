from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import httpx

from zeler_bootstrap.state_machine import BootstrapStateMachine
from zeler_platform_core.models import Claim, Item, Message, Order, Question, Shipment

MELI_ITEMS_BATCH_SIZE = 20


class BootstrapGatewayClient(Protocol):
    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any: ...


class BootstrapCollection(Protocol):
    async def update_one(
        self, filter_spec: dict[str, Any], update: dict[str, Any], *, upsert: bool
    ) -> None: ...


class BootstrapDatabase(Protocol):
    def __getitem__(self, collection_name: str) -> BootstrapCollection: ...


class BootstrapPublisher(Protocol):
    async def publish_bootstrap_completed(self, job: dict[str, Any]) -> None: ...


class InMemoryPublisher:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def publish_bootstrap_completed(self, job: dict[str, Any]) -> None:
        self.events.append(
            {
                "event_type": "BootstrapCompleted",
                "payload": {"job_id": str(job["_id"]), "seller_id": str(job["seller_id"])},
            }
        )


async def _upsert(collection: BootstrapCollection, document: dict[str, Any]) -> None:
    await collection.update_one({"_id": document["_id"]}, {"$set": document}, upsert=True)


def _chunks(items: list[str], size: int) -> Iterable[list[str]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


def _normalize_order_items(raw_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for raw_item in raw_items:
        if "item_id" in raw_item and "qty" in raw_item:
            normalized.append(raw_item)
            continue
        item = raw_item.get("item") or {}
        normalized.append(
            {
                "item_id": item.get("id") or raw_item.get("item_id"),
                "qty": raw_item.get("quantity") or raw_item.get("qty"),
                "unit_price": raw_item.get("unit_price"),
            }
        )
    return normalized


def _message_user_id(raw: dict[str, Any], field: str) -> Any:
    user = raw.get(field) or {}
    return raw.get(f"{field}_user_id") or user.get("user_id") or user.get("id")


def _message_text(raw: dict[str, Any]) -> str:
    text = raw.get("text")
    if isinstance(text, dict):
        return str(text.get("plain") or "")
    return str(text or "")


def _message_date_created(raw: dict[str, Any]) -> Any:
    message_date = raw.get("message_date") or {}
    return raw.get("date_created") or raw.get("date") or message_date.get("created")


def _now() -> datetime:
    return datetime.now(UTC)


class AccountsStage:
    name = "accounts"

    def __init__(self, gateway: BootstrapGatewayClient, database: BootstrapDatabase) -> None:
        self.gateway = gateway
        self.database = database

    async def run(self, job: dict[str, Any], state_machine: BootstrapStateMachine) -> None:
        seller_id = str(job["seller_id"])
        metadata = await self.gateway.get(f"/users/{seller_id}")
        await self.database["meli_accounts"].update_one(
            {"seller_id": seller_id},
            {
                "$set": {
                    "seller_id": seller_id,
                    "nickname": metadata.get("nickname"),
                    "schema_version": 1,
                }
            },
            upsert=True,
        )
        await state_machine.update_cursor(self.name, {"seller_id": seller_id})


class ItemsStage:
    name = "items"

    def __init__(self, gateway: BootstrapGatewayClient, database: BootstrapDatabase) -> None:
        self.gateway = gateway
        self.database = database

    async def run(self, job: dict[str, Any], state_machine: BootstrapStateMachine) -> None:
        seller_id = str(job["seller_id"])
        cursor = job.get("checkpoints", {}).get(self.name, {}).get("scroll_id")
        while True:
            page = await self.gateway.get(f"/users/{seller_id}/items/search", {"scroll_id": cursor})
            item_ids = [str(item_id) for item_id in page.get("results", [])]
            for item_batch in _chunks(item_ids, MELI_ITEMS_BATCH_SIZE):
                details = await self.gateway.get("/items", {"ids": ",".join(item_batch)})
                detail_results = (
                    details if isinstance(details, list) else details.get("results", [])
                )
                for raw in detail_results:
                    body = raw.get("body", raw)
                    document = Item.model_validate(
                        {
                            **body,
                            "seller_id": seller_id,
                            "last_meli_sync_at": _now(),
                            "schema_version": 1,
                        }
                    ).model_dump(by_alias=True, mode="json")
                    await _upsert(self.database["items"], document)
            cursor = page.get("scroll_id")
            await state_machine.update_cursor(
                self.name,
                {
                    "scroll_id": cursor,
                    "fetched": len(item_ids),
                    "total": page.get("paging", {}).get("total"),
                },
            )
            if cursor is None:
                break


class OrdersStage:
    name = "orders"

    def __init__(
        self, gateway: BootstrapGatewayClient, database: BootstrapDatabase, *, days: int = 90
    ) -> None:
        self.gateway = gateway
        self.database = database
        self.days = days

    async def run(self, job: dict[str, Any], state_machine: BootstrapStateMachine) -> None:
        seller_id = str(job["seller_id"])
        date_from = (_now() - timedelta(days=self.days)).isoformat()
        page = await self.gateway.get(
            "/orders/search", {"seller": seller_id, "date_from": date_from}
        )
        order_ids: list[str] = []
        shipment_ids: list[str] = []
        message_targets: list[dict[str, str]] = []
        for raw in page.get("results", []):
            shipment_id = raw.get("shipment_id") or raw.get("shipping", {}).get("id")
            order_id = str(raw["id"])
            pack_id = raw.get("pack_id") or order_id
            order = Order.model_validate(
                {
                    "_id": raw["id"],
                    "seller_id": seller_id,
                    "buyer_id": raw.get("buyer_id") or raw.get("buyer", {}).get("id"),
                    "status": raw["status"],
                    "date_created": raw["date_created"],
                    "date_closed": raw.get("date_closed"),
                    "total_amount": raw["total_amount"],
                    "items": _normalize_order_items(raw.get("items") or raw.get("order_items", [])),
                    "shipment_id": shipment_id,
                    "schema_version": 1,
                }
            )
            document = order.model_dump(by_alias=True, mode="json")
            await _upsert(self.database["orders"], document)
            order_ids.append(order.id)
            message_targets.append({"pack_id": str(pack_id), "order_id": order.id})
            if order.shipment_id is not None:
                shipment_ids.append(order.shipment_id)
        await state_machine.update_cursor(
            self.name,
            {
                "order_ids": order_ids,
                "shipment_ids": shipment_ids,
                "message_targets": message_targets,
            },
        )


class QuestionsStage:
    name = "questions"

    def __init__(self, gateway: BootstrapGatewayClient, database: BootstrapDatabase) -> None:
        self.gateway = gateway
        self.database = database

    async def run(self, job: dict[str, Any], state_machine: BootstrapStateMachine) -> None:
        seller_id = str(job["seller_id"])
        page = await self.gateway.get(
            "/questions/search", {"seller_id": seller_id, "api_version": "4"}
        )
        question_ids: list[str] = []
        for raw in page.get("questions", []):
            document = Question.model_validate(
                {
                    "_id": raw["id"],
                    "seller_id": seller_id,
                    "item_id": raw["item_id"],
                    "text": raw["text"],
                    "status": raw["status"],
                    "from_user_id": raw.get("from_user_id") or raw.get("from", {}).get("id"),
                    "date_created": raw["date_created"],
                    "schema_version": 1,
                }
            ).model_dump(by_alias=True, mode="json")
            await _upsert(self.database["questions"], document)
            question_ids.append(str(document["_id"]))
        await state_machine.update_cursor(self.name, {"question_ids": question_ids})


class MessagesStage:
    name = "messages"

    def __init__(self, gateway: BootstrapGatewayClient, database: BootstrapDatabase) -> None:
        self.gateway = gateway
        self.database = database

    async def run(self, job: dict[str, Any], state_machine: BootstrapStateMachine) -> None:
        seller_id = str(job["seller_id"])
        order_checkpoint = job.get("checkpoints", {}).get("orders", {})
        message_targets = order_checkpoint.get("message_targets") or [
            {"pack_id": str(order_id), "order_id": str(order_id)}
            for order_id in order_checkpoint.get("order_ids", [])
        ]
        message_ids: list[str] = []
        missing_packs: list[str] = []
        for target in message_targets:
            pack_id = str(target["pack_id"])
            order_id = str(target["order_id"])
            try:
                page = await self.gateway.get(
                    f"/messages/packs/{pack_id}/sellers/{seller_id}",
                    {"tag": "post_sale", "mark_as_read": "false"},
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in {400, 404}:
                    missing_packs.append(pack_id)
                    continue
                raise
            for raw in page.get("messages", []):
                message_date = raw.get("message_date") or {}
                document = Message.model_validate(
                    {
                        "_id": raw["id"],
                        "seller_id": seller_id,
                        "pack_id": raw.get("pack_id") or pack_id,
                        "order_id": raw.get("order_id") or order_id,
                        "from_user_id": _message_user_id(raw, "from"),
                        "to_user_id": _message_user_id(raw, "to"),
                        "text": _message_text(raw),
                        "status": raw["status"],
                        "date_created": _message_date_created(raw),
                        "read_at": raw.get("read_at") or message_date.get("read"),
                        "schema_version": 1,
                    }
                ).model_dump(by_alias=True, mode="json")
                await _upsert(self.database["messages"], document)
                message_ids.append(str(document["_id"]))
        await state_machine.update_cursor(
            self.name, {"message_ids": message_ids, "missing_packs": missing_packs}
        )


class ShipmentsStage:
    name = "shipments"

    def __init__(self, gateway: BootstrapGatewayClient, database: BootstrapDatabase) -> None:
        self.gateway = gateway
        self.database = database

    async def run(self, job: dict[str, Any], state_machine: BootstrapStateMachine) -> None:
        shipment_ids = job.get("checkpoints", {}).get("orders", {}).get("shipment_ids", [])
        written: list[str] = []
        for shipment_id in shipment_ids:
            raw = await self.gateway.get(f"/shipments/{shipment_id}")
            document = Shipment.model_validate(
                {**raw, "_id": raw["id"], "seller_id": job["seller_id"], "schema_version": 1}
            ).model_dump(by_alias=True, mode="json")
            await _upsert(self.database["shipments"], document)
            written.append(str(document["_id"]))
        await state_machine.update_cursor(self.name, {"shipment_ids": written})


class ClaimsStage:
    name = "claims"

    def __init__(self, gateway: BootstrapGatewayClient, database: BootstrapDatabase) -> None:
        self.gateway = gateway
        self.database = database

    async def run(self, job: dict[str, Any], state_machine: BootstrapStateMachine) -> None:
        order_ids: Iterable[str] = job.get("checkpoints", {}).get("orders", {}).get("order_ids", [])
        claim_ids: list[str] = []
        missing_claim_searches: list[str] = []
        for order_id in order_ids:
            try:
                page = await self.gateway.get(
                    "/post-purchase/v1/claims/search", {"order_id": str(order_id)}
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    missing_claim_searches.append(str(order_id))
                    continue
                raise
            for raw in page.get("data", []):
                document = Claim.model_validate(
                    {
                        **raw,
                        "_id": raw["id"],
                        "seller_id": job["seller_id"],
                        "order_id": raw.get("order_id") or raw.get("resource_id") or order_id,
                        "schema_version": 1,
                    }
                ).model_dump(by_alias=True, mode="python")
                await _upsert(self.database["claims"], document)
                claim_ids.append(str(document["_id"]))
        await state_machine.update_cursor(
            self.name,
            {"claim_ids": claim_ids, "missing_claim_searches": missing_claim_searches},
        )
