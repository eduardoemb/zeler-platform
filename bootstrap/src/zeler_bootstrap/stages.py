from __future__ import annotations

import os
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlsplit

import httpx

from zeler_bootstrap.state_machine import BootstrapStateMachine
from zeler_platform_core.meli_timezones import resolve_meli_timezone
from zeler_platform_core.models import (
    Claim,
    Item,
    Message,
    Order,
    Question,
    Shipment,
    ShipmentRealShippingCostProjection,
)
from zeler_platform_core.models.base import current_schema_version
from zeler_sheets.sheetseller_backfill import run_item_detail_enrichment, run_sheetseller_backfill

MELI_ITEMS_BATCH_SIZE = 20
SELLER_SKU_ATTRIBUTE_ID = "SELLER_SKU"


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


class _BootstrapMeliItemGatewayAdapter:
    def __init__(self, gateway: BootstrapGatewayClient) -> None:
        self._gateway = gateway

    async def fetch_resource(self, *, seller_id: str, path: str) -> Any:
        _ = seller_id
        parsed = urlsplit(path)
        params = dict(parse_qsl(parsed.query)) or None
        return await self._gateway.get(parsed.path, params)


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


def _normalize_order_items(
    raw_items: list[dict[str, Any]], *, sale_fee_synced_at: Any | None = None
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for raw_item in raw_items:
        if "item_id" in raw_item and "qty" in raw_item:
            order_item = dict(raw_item)
            _copy_sale_fee_metadata(order_item, raw_item, sale_fee_synced_at=sale_fee_synced_at)
            normalized.append(order_item)
            continue
        item = raw_item.get("item") or {}
        order_item = {
            "item_id": item.get("id") or raw_item.get("item_id"),
            "qty": raw_item.get("quantity") or raw_item.get("qty"),
            "unit_price": raw_item.get("unit_price"),
        }
        _copy_optional_identity(order_item, "variation_id", raw_item, item)
        _copy_optional_identity(order_item, "sku", raw_item, item)
        _copy_optional_identity(order_item, "seller_sku", raw_item, item)
        _copy_optional_identity(order_item, "seller_custom_field", raw_item, item)
        _copy_sale_fee_metadata(order_item, raw_item, sale_fee_synced_at=sale_fee_synced_at)
        normalized.append(order_item)
    return normalized


def _copy_sale_fee_metadata(
    target: dict[str, Any], raw_item: dict[str, Any], *, sale_fee_synced_at: Any | None
) -> None:
    sale_fee = raw_item.get("sale_fee")
    if sale_fee is None or sale_fee_synced_at is None:
        return
    target["sale_fee"] = sale_fee
    target["sale_fee_source"] = "/orders/{id}"
    target["sale_fee_synced_at"] = sale_fee_synced_at


def _copy_optional_identity(
    target: dict[str, Any], field: str, raw_item: dict[str, Any], item: dict[str, Any]
) -> None:
    value = raw_item.get(field) or item.get(field)
    if value is None and field == "seller_sku":
        value = _seller_sku_from_order_attributes(raw_item, item)
    if value is not None and str(value).strip():
        target[field] = value


def _seller_sku_from_order_attributes(raw_item: dict[str, Any], item: dict[str, Any]) -> Any:
    for attributes in (
        raw_item.get("variation_attributes"),
        item.get("variation_attributes"),
        raw_item.get("attributes"),
        item.get("attributes"),
    ):
        value = _seller_sku_from_attributes(attributes)
        if value is not None:
            return value
    return None


def _seller_sku_from_attributes(attributes: Any) -> Any:
    if not isinstance(attributes, Iterable) or isinstance(attributes, (str, bytes)):
        return None
    for attribute in attributes:
        if not isinstance(attribute, dict):
            continue
        attribute_id = str(attribute.get("id") or "").strip().upper()
        if attribute_id != SELLER_SKU_ATTRIBUTE_ID:
            continue
        for key in ("value_name", "value", "name"):
            value = attribute.get(key)
            if value is not None and str(value).strip():
                return value
    return None


def _without_none_values(document: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in document.items() if value is not None}


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


def _meli_pack_id(raw: dict[str, Any]) -> str | None:
    value = raw.get("pack_id")
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


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
        update = _account_metadata_update(seller_id=seller_id, metadata=metadata)
        await self.database["meli_accounts"].update_one(
            {"seller_id": seller_id},
            update,
            upsert=True,
        )
        await state_machine.update_cursor(self.name, {"seller_id": seller_id})


def _account_metadata_update(*, seller_id: str, metadata: dict[str, Any]) -> dict[str, Any]:
    site_id = _metadata_site_id(metadata)
    timezone_resolution = resolve_meli_timezone(site_id)
    set_fields = _without_none_values(
        {
            "seller_id": seller_id,
            "nickname": metadata.get("nickname"),
            "schema_version": 1,
            "site_id": timezone_resolution.site_id,
        }
    )
    update: dict[str, Any] = {"$set": set_fields}
    if timezone_resolution.site_id is None:
        update["$setOnInsert"] = {"timezone": timezone_resolution.timezone}
    else:
        set_fields["timezone"] = timezone_resolution.timezone
    return update


def _metadata_site_id(metadata: dict[str, Any]) -> str | None:
    value = metadata.get("site_id")
    if value is None:
        return None
    return str(value)


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
                            "schema_version": current_schema_version("items"),
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
        await _populate_zelerdata_item_read_models(
            gateway=self.gateway,
            database=self.database,
            seller_id=seller_id,
        )


async def _populate_zelerdata_item_read_models(
    *, gateway: BootstrapGatewayClient, database: BootstrapDatabase, seller_id: str
) -> None:
    if _env_flag_enabled("ZELERDATA_ENRICHMENT_ENABLED"):
        await run_item_detail_enrichment(
            db=database,
            gateway=_BootstrapMeliItemGatewayAdapter(gateway),
            seller_id=seller_id,
            dry_run=False,
            sale_price_enabled=_env_flag_enabled("ZELERDATA_SALE_PRICE_ENABLED"),
            listing_fixed_fee_enabled=_env_flag_enabled("ZELERDATA_LISTING_FIXED_FEE_ENABLED"),
        )
    await run_sheetseller_backfill(db=database, seller_id=seller_id, dry_run=False)


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
                    "items": _normalize_order_items(
                        raw.get("items") or raw.get("order_items", []),
                        sale_fee_synced_at=(
                            raw.get("last_updated")
                            or raw.get("date_closed")
                            or raw.get("date_created")
                            or _now()
                        ),
                    ),
                    "shipment_id": shipment_id,
                    "meli_pack_id": _meli_pack_id(raw),
                    "schema_version": 1,
                }
            )
            document = order.model_dump(by_alias=True, mode="json")
            document["items"] = [_without_none_values(item) for item in document.get("items", [])]
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
        seller_id = str(job["seller_id"])
        shipment_ids = job.get("checkpoints", {}).get("orders", {}).get("shipment_ids", [])
        written: list[str] = []
        for shipment_id in shipment_ids:
            raw = await self.gateway.get(f"/shipments/{shipment_id}")
            shipment_cost = await _shipment_real_shipping_cost_snapshot(
                gateway=self.gateway,
                seller_id=seller_id,
                shipment_id=str(raw.get("id") or shipment_id),
                synced_at=_now(),
            )
            payload = {
                **raw,
                "_id": raw["id"],
                "seller_id": seller_id,
                "receiver_address": _receiver_address_snapshot(raw),
                "schema_version": 1,
            }
            if shipment_cost is not None:
                payload["real_shipping_cost"] = shipment_cost
            document = Shipment.model_validate(
                payload,
            ).model_dump(by_alias=True, mode="json", exclude_none=True)
            await _upsert(self.database["shipments"], document)
            written.append(str(document["_id"]))
        await state_machine.update_cursor(self.name, {"shipment_ids": written})


async def _shipment_real_shipping_cost_snapshot(
    *,
    gateway: BootstrapGatewayClient,
    seller_id: str,
    shipment_id: str,
    synced_at: datetime,
) -> dict[str, Any] | None:
    try:
        costs_payload = await gateway.get(f"/shipments/{shipment_id}/costs")
    except Exception:  # noqa: BLE001 - shipment cost enrichment fails closed without raw output.
        return None
    projection = ShipmentRealShippingCostProjection.from_meli_costs_payload(
        costs_payload,
        seller_id=seller_id,
        synced_at=synced_at,
    )
    if projection is None:
        return None
    return projection.model_dump(mode="json")


def _receiver_address_snapshot(resource: dict[str, Any]) -> dict[str, Any] | None:
    raw_address = resource.get("receiver_address")
    if not isinstance(raw_address, dict):
        return None
    snapshot = {
        "name": _first_receiver_address_string(
            raw_address.get("receiver_name"), raw_address.get("name")
        ),
        "street_name": _receiver_address_string(raw_address.get("street_name")),
        "street_number": _receiver_address_string(raw_address.get("street_number")),
        "neighborhood": _receiver_address_string(_named_value(raw_address.get("neighborhood"))),
        "zip_code": _receiver_address_string(raw_address.get("zip_code")),
        "city": _receiver_address_string(_named_value(raw_address.get("city"))),
        "state": _receiver_address_string(_named_value(raw_address.get("state"))),
        "country": _receiver_address_string(_named_value(raw_address.get("country"))),
    }
    sanitized = {key: value for key, value in snapshot.items() if value is not None}
    return sanitized or None


def _named_value(value: Any) -> Any:
    if isinstance(value, dict):
        return _receiver_address_string(value.get("name")) or _receiver_address_string(
            value.get("id")
        )
    return value


def _receiver_address_string(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list, tuple, set, bytes, bytearray)):
        return None
    normalized = str(value).strip()
    return normalized or None


def _first_receiver_address_string(*values: Any) -> str | None:
    for value in values:
        normalized = _receiver_address_string(value)
        if normalized is not None:
            return normalized
    return None


def _env_flag_enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


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
