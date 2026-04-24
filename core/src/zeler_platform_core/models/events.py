from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, field_validator

from zeler_platform_core.models.base import UtcDatetimeMixin, ZelerModel, _coerce_str

EventType = Literal[
    "ItemUpdated",
    "ItemPriceChanged",
    "OrderCreated",
    "QuestionReceived",
    "MessageReceived",
    "MeliAccountRevoked",
    "MeliAccountReconnected",
    "BootstrapCompleted",
]


class DomainEvent(UtcDatetimeMixin, ZelerModel):
    event_id: UUID
    event_type: EventType
    account_id: str
    occurred_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("account_id", mode="before")
    @classmethod
    def _coerce_account_id(cls, value: object) -> str:
        return _coerce_str(value)


class BootstrapCompleted(DomainEvent):
    event_type: Literal["BootstrapCompleted"] = "BootstrapCompleted"


class ItemUpdated(DomainEvent):
    event_type: Literal["ItemUpdated"] = "ItemUpdated"


class ItemPriceChanged(DomainEvent):
    event_type: Literal["ItemPriceChanged"] = "ItemPriceChanged"


class OrderCreated(DomainEvent):
    event_type: Literal["OrderCreated"] = "OrderCreated"


class QuestionReceived(DomainEvent):
    event_type: Literal["QuestionReceived"] = "QuestionReceived"


class MessageReceived(DomainEvent):
    event_type: Literal["MessageReceived"] = "MessageReceived"


class MeliAccountRevoked(DomainEvent):
    event_type: Literal["MeliAccountRevoked"] = "MeliAccountRevoked"


class MeliAccountReconnected(DomainEvent):
    event_type: Literal["MeliAccountReconnected"] = "MeliAccountReconnected"
