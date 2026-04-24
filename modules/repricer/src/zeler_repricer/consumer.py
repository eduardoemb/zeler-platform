from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol

from zeler_platform_core.models import Item, RepricerRule
from zeler_repricer.engine import SetPrice, evaluate_rule


@dataclass(frozen=True)
class RepricerEvent:
    event_id: str
    event_type: str
    seller_id: int
    resource: str
    idempotency_key: str
    buybox_price: Decimal | None = None


class GatewayPriceClient(Protocol):
    async def update_price(
        self, *, seller_id: int, item_id: str, new_price: Decimal, idempotency_key: str
    ) -> tuple[int, int]: ...


class IdempotencyStoreLike(Protocol):
    async def is_duplicate(self, key: str) -> bool: ...

    async def mark_processed(self, key: str) -> None: ...


class RepricerEventHandler:
    def __init__(
        self,
        *,
        db: Any,
        gateway_client: GatewayPriceClient,
        idempotency_store: IdempotencyStoreLike,
    ) -> None:
        self._db = db
        self._gateway = gateway_client
        self._idempotency = idempotency_store

    async def handle(self, event: RepricerEvent) -> str:
        if await self._idempotency.is_duplicate(event.idempotency_key):
            return "duplicate"

        item_id = _item_id_from_resource(event.resource)
        item_doc = await self._db["items"].find_one(
            {"_id": item_id, "seller_id": str(event.seller_id)}
        )
        if item_doc is None:
            return "item_missing"
        item = Item.model_validate(item_doc)
        rule_doc = await self._db["repricer_rules"].find_one(
            {"seller_id": str(event.seller_id), "item_id": item.id, "active": True}
        )
        if rule_doc is None:
            return "rule_missing"
        rule = RepricerRule.model_validate(rule_doc)
        decision = evaluate_rule(rule, current_price=item.price, buybox_price=event.buybox_price)

        if isinstance(decision, SetPrice):
            gateway_status, latency_ms = await self._gateway.update_price(
                seller_id=event.seller_id,
                item_id=item.id,
                new_price=decision.new_price,
                idempotency_key=event.idempotency_key,
            )
            if gateway_status == 429:
                raise RuntimeError("gateway_backpressure")
            await self._write_history(
                event=event,
                item=item,
                new_price=decision.new_price,
                reason=decision.reason,
                gateway_status=gateway_status,
                latency_ms=latency_ms,
            )
            await self._idempotency.mark_processed(event.idempotency_key)
            return "set_price"

        reason = decision.reason
        await self._write_history(
            event=event,
            item=item,
            new_price=item.price,
            reason=reason,
            gateway_status=None,
            latency_ms=None,
        )
        await self._idempotency.mark_processed(event.idempotency_key)
        return "no_action"

    async def _write_history(
        self,
        *,
        event: RepricerEvent,
        item: Item,
        new_price: Decimal,
        reason: str,
        gateway_status: int | None,
        latency_ms: int | None,
    ) -> None:
        await self._db["repricer_history"].insert_one(
            {
                "seller_id": str(event.seller_id),
                "item_id": item.id,
                "old_price": item.price,
                "new_price": new_price,
                "reason": reason,
                "applied_at": datetime.now(UTC),
                "gateway_status": gateway_status,
                "gateway_latency_ms": latency_ms,
                "event_id": event.event_id,
                "schema_version": 1,
            }
        )


def _item_id_from_resource(resource: str) -> str:
    parts = [part for part in resource.split("/") if part]
    if len(parts) < 2 or parts[0] != "items":
        msg = f"unsupported repricer resource: {resource}"
        raise ValueError(msg)
    return parts[1]
