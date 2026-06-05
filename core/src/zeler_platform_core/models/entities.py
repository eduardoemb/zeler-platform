from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from zeler_platform_core.models.base import (
    PriceMixin,
    SellerScopedDocument,
    UtcDatetimeMixin,
    _coerce_str,
)

ItemStatus = Literal["active", "paused", "closed", "under_review", "inactive"]
OrderStatus = Literal[
    "paid",
    "confirmed",
    "payment_required",
    "payment_in_process",
    "cancelled",
    "partially_refunded",
]
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


class PromoPriceProjection(UtcDatetimeMixin):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    source: Literal["/items/{id}/sale_price"]
    sale_amount: Decimal
    regular_amount: Decimal
    discount_percent: Decimal | None = None
    currency_id: str
    promotion_id: str | None = None
    promotion_type: str | None = None
    reference_at: datetime
    synced_at: datetime

    @field_validator("sale_amount", "regular_amount", "discount_percent", mode="before")
    @classmethod
    def _coerce_finite_non_negative_decimal(cls, value: object) -> Decimal | None:
        if value is None:
            return None
        if isinstance(value, (bool, dict, list)):
            msg = "promo numeric fields must be finite non-negative numbers"
            raise ValueError(msg)
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
        if not parsed.is_finite() or parsed < 0:
            msg = "promo numeric fields must be finite non-negative numbers"
            raise ValueError(msg)
        return parsed

    @field_validator("currency_id", mode="before")
    @classmethod
    def _coerce_currency_id(cls, value: object) -> str:
        normalized = _coerce_str(value).strip().upper()
        if not normalized:
            msg = "currency_id must be non-blank"
            raise ValueError(msg)
        return normalized

    @field_validator("promotion_id", "promotion_type", mode="before")
    @classmethod
    def _coerce_optional_promo_string(cls, value: object) -> object:
        if value is None:
            return None
        normalized = _coerce_str(value).strip()
        return normalized or None

    @field_validator("reference_at", "synced_at", mode="before")
    @classmethod
    def _promotion_datetimes_must_be_aware(cls, value: object) -> object:
        return UtcDatetimeMixin._datetime_must_be_aware(value)

    @model_validator(mode="after")
    def _must_be_discount(self) -> PromoPriceProjection:
        if self.sale_amount >= self.regular_amount:
            msg = "sale_amount must be less than regular_amount"
            raise ValueError(msg)
        return self


class ListingPriceFixedFeeParams(PriceMixin):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    site_id: str
    category_id: str
    price: Decimal
    currency_id: str
    listing_type_id: str
    shipping_mode: str | None = None
    logistic_type: str | None = None
    billable_weight: Decimal | None = None
    tags: list[str] = Field(default_factory=list)

    @field_validator("site_id", "category_id", "currency_id", "listing_type_id", mode="before")
    @classmethod
    def _coerce_required_string(cls, value: object) -> str:
        normalized = _coerce_str(value).strip()
        if not normalized:
            msg = "listing price params must include non-blank required strings"
            raise ValueError(msg)
        return normalized.upper() if normalized.casefold() in {"mla", "ars"} else normalized

    @field_validator("shipping_mode", "logistic_type", mode="before")
    @classmethod
    def _coerce_optional_string(cls, value: object) -> str | None:
        if value is None:
            return None
        normalized = _coerce_str(value).strip()
        return normalized or None

    @field_validator("price", "billable_weight", mode="before")
    @classmethod
    def _coerce_finite_non_negative_decimal(cls, value: object) -> Decimal | None:
        msg = "listing price numeric params must be finite non-negative numbers"
        if value is None:
            return None
        if isinstance(value, (bool, dict, list)):
            raise ValueError(msg)
        try:
            parsed = value if isinstance(value, Decimal) else Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(msg) from exc
        if not parsed.is_finite() or parsed < 0:
            raise ValueError(msg)
        return parsed

    @field_validator("tags", mode="before")
    @classmethod
    def _coerce_tags(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            msg = "tags must be a list of strings"
            raise ValueError(msg)
        return [tag for raw in value if (tag := _coerce_str(raw).strip())]


class ListingPriceFixedFeeProjection(UtcDatetimeMixin):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    source: Literal["/sites/{site}/listing_prices"]
    fixed_fee: Decimal
    currency_id: str
    synced_at: datetime
    params: ListingPriceFixedFeeParams

    @field_validator("fixed_fee", mode="before")
    @classmethod
    def _coerce_fixed_fee(cls, value: object) -> Decimal:
        msg = "fixed_fee must be a finite non-negative number"
        if value is None or isinstance(value, (bool, dict, list)):
            raise ValueError(msg)
        try:
            parsed = value if isinstance(value, Decimal) else Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(msg) from exc
        if not parsed.is_finite() or parsed < 0:
            raise ValueError(msg)
        return parsed

    @field_validator("currency_id", mode="before")
    @classmethod
    def _coerce_currency_id(cls, value: object) -> str:
        normalized = _coerce_str(value).strip().upper()
        if not normalized:
            msg = "currency_id must be non-blank"
            raise ValueError(msg)
        return normalized

    @field_validator("synced_at", mode="before")
    @classmethod
    def _synced_at_must_be_aware(cls, value: object) -> object:
        return UtcDatetimeMixin._datetime_must_be_aware(value)

    @model_validator(mode="after")
    def _currency_must_match_params(self) -> ListingPriceFixedFeeProjection:
        if self.currency_id != self.params.currency_id.upper():
            msg = "fixed_fee currency_id must match params currency_id"
            raise ValueError(msg)
        return self


class Item(UtcDatetimeMixin, PriceMixin, SellerScopedDocument):
    title: str
    price: Decimal
    base_price: Decimal
    available_quantity: int
    status: ItemStatus
    category_id: str
    currency_id: str | None = None
    site_id: str | None = None
    permalink: str | None = None
    thumbnail: str | None = None
    catalog_product_id: str | None = None
    inventory_id: str | None = None
    listing_type_id: str | None = None
    seller_shipping_cost: Decimal | None = None
    billable_weight: Decimal | None = None
    tags: list[str] = Field(default_factory=list)
    variations: list[dict[str, Any]] = Field(default_factory=list)
    attributes: list[dict[str, Any]] = Field(default_factory=list)
    shipping: dict[str, Any] | None = None
    health: float | None = None
    current_promotion: PromoPriceProjection | None = None
    listing_price_fixed_fee: ListingPriceFixedFeeProjection | None = None
    last_meli_sync_at: datetime
    date_created: datetime
    last_updated: datetime

    @field_validator(
        "permalink",
        "thumbnail",
        "catalog_product_id",
        "inventory_id",
        "listing_type_id",
        "currency_id",
        "site_id",
        mode="before",
    )
    @classmethod
    def _coerce_optional_formula_field(cls, value: object) -> object:
        if value is None:
            return None
        normalized = _coerce_str(value).strip()
        return normalized or None

    @field_validator("currency_id")
    @classmethod
    def _uppercase_currency_id(cls, value: str | None) -> str | None:
        return value.upper() if value is not None else None

    @field_validator("site_id")
    @classmethod
    def _uppercase_site_id(cls, value: str | None) -> str | None:
        return value.upper() if value is not None else None

    @field_validator("seller_shipping_cost", "billable_weight", mode="before")
    @classmethod
    def _coerce_seller_shipping_cost(cls, value: object) -> Decimal | None:
        if value is None:
            return None
        if isinstance(value, (bool, dict, list)):
            msg = "seller_shipping_cost must be a finite non-negative number"
            raise ValueError(msg)
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
        if not parsed.is_finite() or parsed < 0:
            msg = "seller_shipping_cost must be a finite non-negative number"
            raise ValueError(msg)
        return parsed

    @field_validator("tags", mode="before")
    @classmethod
    def _coerce_tags(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            msg = "tags must be a list of strings"
            raise ValueError(msg)
        return [tag for raw in value if (tag := _coerce_str(raw).strip())]


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


class ReceiverAddressSnapshot(UtcDatetimeMixin):
    name: str | None = Field(default=None, max_length=120)
    street_name: str | None = Field(default=None, max_length=120)
    street_number: str | None = Field(default=None, max_length=120)
    neighborhood: str | None = Field(default=None, max_length=120)
    zip_code: str | None = Field(default=None, max_length=120)
    city: str | None = Field(default=None, max_length=120)
    state: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, max_length=120)

    @field_validator(
        "name",
        "street_name",
        "street_number",
        "neighborhood",
        "zip_code",
        "city",
        "state",
        "country",
        mode="before",
    )
    @classmethod
    def _coerce_optional_receiver_address_field(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, (dict, list, tuple, set, bytes, bytearray)):
            return None
        normalized = _coerce_str(value).strip()
        return normalized or None


class Shipment(UtcDatetimeMixin, SellerScopedDocument):
    order_id: str
    status: ShipmentStatus
    substatus: str | None = None
    tracking_number: str | None = None
    logistic_type: ShipmentLogisticType
    receiver_address: ReceiverAddressSnapshot | None = None
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
