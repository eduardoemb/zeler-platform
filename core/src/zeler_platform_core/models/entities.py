from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field, field_validator

from zeler_platform_core.models.base import (
    PriceMixin,
    SellerScopedDocument,
    UtcDatetimeMixin,
    _coerce_str,
)

ItemStatus = Literal["active", "paused", "closed", "under_review", "inactive"]
OrderStatus = Literal["paid", "confirmed", "payment_required", "payment_in_process", "cancelled"]
MessageStatus = Literal["available", "blocked", "moderated", "deleted"]
ShipmentStatus = Literal[
    "pending",
    "handling",
    "ready_to_ship",
    "shipped",
    "delivered",
    "not_delivered",
    "cancelled",
]
ShipmentLogisticType = Literal[
    "fulfillment", "cross_docking", "self_service", "drop_off", "xd_drop_off"
]
ClaimStatus = Literal["opened", "closed", "mediating", "resolved"]
ClaimStage = Literal["claim", "dispute", "recontact", "none"]
ClaimType = Literal["mediations", "returns", "fulfillment", "cancel_purchase"]


class Item(UtcDatetimeMixin, PriceMixin, SellerScopedDocument):
    title: str
    price: Decimal
    base_price: Decimal
    available_quantity: int
    status: ItemStatus
    category_id: str
    permalink: str | None = None
    thumbnail: str | None = None
    catalog_product_id: str | None = None
    inventory_id: str | None = None
    variations: list[dict[str, Any]] = Field(default_factory=list)
    attributes: list[dict[str, Any]] = Field(default_factory=list)
    shipping: dict[str, Any] | None = None
    health: float | None = None
    last_meli_sync_at: datetime
    date_created: datetime
    last_updated: datetime

    @field_validator("permalink", "thumbnail", "catalog_product_id", "inventory_id", mode="before")
    @classmethod
    def _coerce_optional_formula_field(cls, value: object) -> object:
        if value is None:
            return None
        normalized = _coerce_str(value).strip()
        return normalized or None


class OrderItem(PriceMixin):
    item_id: str
    variation_id: str | None = None
    sku: str | None = None
    seller_sku: str | None = None
    seller_custom_field: str | None = None
    qty: int
    unit_price: Decimal

    @field_validator("item_id", mode="before")
    @classmethod
    def _coerce_item_id(cls, value: object) -> str:
        return _coerce_str(value)

    @field_validator("variation_id", "sku", "seller_sku", "seller_custom_field", mode="before")
    @classmethod
    def _coerce_optional_identity(cls, value: object) -> object:
        if value is None:
            return None
        normalized = _coerce_str(value).strip()
        return normalized or None

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("exclude_none", True)
        return super().model_dump(*args, **kwargs)


class Order(UtcDatetimeMixin, PriceMixin, SellerScopedDocument):
    buyer_id: str
    status: OrderStatus
    date_created: datetime
    date_closed: datetime | None = None
    total_amount: Decimal
    items: list[OrderItem] = Field(default_factory=list)
    shipment_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    feedback: dict[str, Any] | None = None

    @field_validator("buyer_id", "shipment_id", mode="before")
    @classmethod
    def _coerce_optional_ids(cls, value: object) -> object:
        return None if value is None else _coerce_str(value)


class QuestionAnswer(UtcDatetimeMixin):
    text: str
    date_created: datetime
    status: str


class Question(UtcDatetimeMixin, SellerScopedDocument):
    item_id: str
    text: str
    status: Literal["UNANSWERED", "ANSWERED", "DELETED", "BANNED"]
    answer: QuestionAnswer | None = None
    from_user_id: str
    date_created: datetime

    @field_validator("item_id", "from_user_id", mode="before")
    @classmethod
    def _coerce_ids(cls, value: object) -> str:
        return _coerce_str(value)


class Message(UtcDatetimeMixin, SellerScopedDocument):
    pack_id: str
    order_id: str | None = None
    from_user_id: str
    to_user_id: str
    text: str
    status: MessageStatus
    date_created: datetime
    read_at: datetime | None = None

    @field_validator("pack_id", "order_id", "from_user_id", "to_user_id", mode="before")
    @classmethod
    def _coerce_ids(cls, value: object) -> object:
        return None if value is None else _coerce_str(value)


class Shipment(UtcDatetimeMixin, SellerScopedDocument):
    order_id: str
    status: ShipmentStatus
    substatus: str | None = None
    tracking_number: str | None = None
    logistic_type: ShipmentLogisticType
    date_created: datetime
    last_updated: datetime

    @field_validator("order_id", mode="before")
    @classmethod
    def _coerce_order_id(cls, value: object) -> str:
        return _coerce_str(value)


class Claim(UtcDatetimeMixin, SellerScopedDocument):
    buyer_id: str | None = None
    order_id: str
    status: ClaimStatus
    stage: ClaimStage
    type: ClaimType
    date_created: datetime
    resolution: dict[str, Any] | None = None

    @field_validator("buyer_id", "order_id", mode="before")
    @classmethod
    def _coerce_ids(cls, value: object) -> object:
        return None if value is None else _coerce_str(value)
