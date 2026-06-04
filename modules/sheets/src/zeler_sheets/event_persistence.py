from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import suppress
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

from bson.decimal128 import Decimal128
from pydantic import ValidationError

from zeler_platform_core.models import Item, Order, Shipment
from zeler_platform_core.models.base import current_schema_version
from zeler_sheets.sheetseller_backfill import (
    build_formula_row_doc,
    build_order_line_formula_row_docs,
    build_order_line_sku_index_docs,
    build_sku_index_docs,
    build_variation_formula_row_docs,
    extract_safe_order_item_identity,
)


class SheetsEventPersistence:
    def __init__(self, *, db: Any, clock: Callable[[], datetime] | None = None) -> None:
        self._db = db
        self._clock = clock or (lambda: datetime.now(UTC))

    async def persist(
        self, *, event_type: str, seller_id: int | str, resource: dict[str, Any]
    ) -> None:
        if event_type.startswith("items."):
            await self._persist_item(seller_id=str(seller_id), resource=resource)
            return
        if event_type.startswith("orders."):
            await self._persist_order(seller_id=str(seller_id), resource=resource)
            return
        if event_type.startswith("shipments."):
            await self._persist_shipment(seller_id=str(seller_id), resource=resource)

    async def _persist_item(self, *, seller_id: str, resource: dict[str, Any]) -> None:
        document = _canonical_item_document(resource, seller_id=seller_id, synced_at=self._clock())
        await self._db["items"].replace_one(
            {"_id": document["_id"], "seller_id": seller_id}, document, upsert=True
        )
        await self._refresh_item_read_models(document, seller_id=seller_id)

    async def _refresh_item_read_models(self, item: dict[str, Any], *, seller_id: str) -> None:
        sku_index_docs = build_sku_index_docs(item, seller_id=seller_id)
        for sku_index_doc in sku_index_docs:
            await self._db["sheets_item_sku_index"].replace_one(
                {"_id": sku_index_doc["_id"]}, sku_index_doc, upsert=True
            )

        formula_row_docs: list[dict[str, Any]] = []
        with suppress(ValueError):
            formula_row_docs.append(build_formula_row_doc(item, seller_id=seller_id))

        variation_formula_rows, _, _ = build_variation_formula_row_docs(
            item, sku_index_docs, seller_id=seller_id
        )
        formula_row_docs.extend(variation_formula_rows)
        order_line_identities = await self._load_order_line_sku_identities(
            item_id=str(item["_id"]), seller_id=seller_id
        )
        order_line_identities = _missing_order_line_identities(
            order_line_identities, sku_index_docs
        )
        formula_row_docs.extend(
            build_order_line_formula_row_docs(
                item,
                order_line_identities=order_line_identities,
                seller_id=seller_id,
            )
        )

        for formula_row_doc in formula_row_docs:
            await self._db["sheets_item_formula_rows"].replace_one(
                {"_id": formula_row_doc["_id"]}, formula_row_doc, upsert=True
            )

    async def _load_order_line_sku_identities(
        self, *, item_id: str, seller_id: str
    ) -> list[dict[str, Any]]:
        collection = self._db["sheets_item_sku_index"]
        cursor = collection.find(
            {
                "seller_id": seller_id,
                "item_id": item_id,
                "source": "order_line",
            }
        )
        return cast("list[dict[str, Any]]", await cursor.to_list(length=None))

    async def _persist_order(self, *, seller_id: str, resource: dict[str, Any]) -> None:
        document = _canonical_order_document(resource, seller_id=seller_id)
        await self._db["orders"].replace_one(
            {"_id": document["_id"], "seller_id": seller_id}, document, upsert=True
        )
        await self._refresh_order_line_sku_index(document, seller_id=seller_id)

    async def _refresh_order_line_sku_index(self, order: dict[str, Any], *, seller_id: str) -> None:
        collection = self._db["sheets_item_sku_index"]
        for sku_index_doc in build_order_line_sku_index_docs(order, seller_id=seller_id):
            if await self._has_conflicting_order_line_identity(sku_index_doc):
                continue
            await collection.replace_one({"_id": sku_index_doc["_id"]}, sku_index_doc, upsert=True)

    async def _has_conflicting_order_line_identity(self, sku_index_doc: dict[str, Any]) -> bool:
        collection = self._db["sheets_item_sku_index"]
        cursor = collection.find(
            {
                "seller_id": sku_index_doc["seller_id"],
                "item_id": sku_index_doc["item_id"],
                "variation_id": sku_index_doc.get("variation_id"),
                "source": "order_line",
            }
        )
        existing_docs = await cursor.to_list(length=None)
        normalized_sku = sku_index_doc.get("normalized_sku")
        return any(existing.get("normalized_sku") != normalized_sku for existing in existing_docs)

    async def _persist_shipment(self, *, seller_id: str, resource: dict[str, Any]) -> None:
        document = _canonical_shipment_document(resource, seller_id=seller_id)
        await self._db["shipments"].replace_one(
            {"_id": document["_id"], "seller_id": seller_id}, document, upsert=True
        )


def _canonical_item_document(
    resource: dict[str, Any], *, seller_id: str, synced_at: datetime
) -> dict[str, Any]:
    item_id = _string_id(resource.get("_id") or resource.get("id"))
    price = resource.get("price", 0)
    model = Item.model_validate(
        {
            **resource,
            "_id": item_id,
            "seller_id": seller_id,
            "price": price,
            "base_price": resource.get("base_price", price),
            "category_id": str(resource.get("category_id") or ""),
            "date_created": resource.get("date_created") or synced_at,
            "last_updated": resource.get("last_updated") or resource.get("updated_at") or synced_at,
            "last_meli_sync_at": synced_at,
            "schema_version": current_schema_version("items"),
        }
    )
    return cast(
        "dict[str, Any]",
        _bson_safe(model.model_dump(by_alias=True, mode="python", exclude_none=True)),
    )


def _canonical_order_document(resource: dict[str, Any], *, seller_id: str) -> dict[str, Any]:
    order_id = _string_id(resource.get("_id") or resource.get("id"))
    model = Order.model_validate(
        {
            **resource,
            "_id": order_id,
            "seller_id": seller_id,
            "buyer_id": _buyer_id(resource),
            "shipment_id": _shipment_id(resource),
            "items": _order_items(resource),
            "schema_version": current_schema_version("orders"),
        }
    )
    return cast(
        "dict[str, Any]",
        _bson_safe(model.model_dump(by_alias=True, mode="python", exclude_none=True)),
    )


def _canonical_shipment_document(resource: dict[str, Any], *, seller_id: str) -> dict[str, Any]:
    shipment_id = _string_id(resource.get("_id") or resource.get("id"))
    try:
        model = Shipment.model_validate(
            {
                **resource,
                "_id": shipment_id,
                "seller_id": seller_id,
                "order_id": _shipment_order_id(resource),
                "receiver_address": _receiver_address_snapshot(resource),
                "schema_version": current_schema_version("shipments"),
            }
        )
    except ValidationError:
        msg = "shipment resource failed validation"
        raise ValueError(msg) from None
    return cast(
        "dict[str, Any]",
        _bson_safe(model.model_dump(by_alias=True, mode="python", exclude_none=True)),
    )


def _missing_order_line_identities(
    order_line_identities: Sequence[dict[str, Any]], sku_index_docs: Sequence[dict[str, Any]]
) -> list[dict[str, Any]]:
    direct_identity_keys = {
        (str(doc.get("item_id") or ""), _optional_string(doc.get("variation_id")))
        for doc in sku_index_docs
    }
    return [
        identity
        for identity in order_line_identities
        if (
            str(identity.get("item_id") or ""),
            _optional_string(identity.get("variation_id")),
        )
        not in direct_identity_keys
    ]


def _bson_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return Decimal128(value)
    if isinstance(value, dict):
        return {key: _bson_safe(nested) for key, nested in value.items()}
    if isinstance(value, list):
        return [_bson_safe(nested) for nested in value]
    return value


def _order_items(resource: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items = resource.get("items") or resource.get("order_items") or []
    if not isinstance(raw_items, Sequence) or isinstance(raw_items, (str, bytes)):
        return []

    items: list[dict[str, Any]] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        identity = extract_safe_order_item_identity(raw_item)
        if "item_id" not in identity:
            continue
        normalized: dict[str, Any] = {
            "item_id": identity["item_id"],
            "qty": raw_item.get("qty", raw_item.get("quantity", 1)),
            "unit_price": raw_item.get("unit_price", 0),
        }
        for field in ("variation_id", "sku", "seller_sku", "seller_custom_field"):
            value = identity.get(field)
            if value is not None:
                normalized[field] = str(value).strip()
        items.append(normalized)
    return items


def _buyer_id(resource: dict[str, Any]) -> str:
    buyer = resource.get("buyer")
    if isinstance(buyer, dict):
        return _string_id(buyer.get("id") or buyer.get("buyer_id"))
    return _string_id(resource.get("buyer_id"))


def _shipment_id(resource: dict[str, Any]) -> str | None:
    shipping = resource.get("shipping")
    if isinstance(shipping, dict):
        value = shipping.get("id") or shipping.get("shipment_id")
    else:
        value = resource.get("shipment_id")
    return None if value is None else str(value)


def _shipment_order_id(resource: dict[str, Any]) -> str:
    order = resource.get("order")
    if isinstance(order, dict):
        return _string_id(order.get("id") or order.get("order_id"))
    return _string_id(resource.get("order_id"))


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
    if value is None:
        return None
    if isinstance(value, (dict, list, tuple, set, bytes, bytearray)):
        return None
    normalized = str(value).strip()
    return normalized or None


def _first_receiver_address_string(*values: Any) -> str | None:
    for value in values:
        normalized = _receiver_address_string(value)
        if normalized is not None:
            return normalized
    return None


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _string_id(value: Any) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        msg = "resource is missing required id"
        raise ValueError(msg)
    return normalized
