from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol


class PublishValidationError(ValueError):
    """Raised when Meli validation rejects a draft before publication."""


class DraftNotFoundError(ValueError):
    """Raised when a requested Publicador draft does not exist."""


class GatewayClient(Protocol):
    async def request(
        self, method: str, path: str, *, seller_id: str, json: dict[str, Any]
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class PublishResult:
    item_id: str | None
    outcome: str
    payload: dict[str, Any]


class PublicadorPublisher:
    def __init__(
        self,
        *,
        mongo_db: Any,
        gateway_client: GatewayClient,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._mongo_db = mongo_db
        self._gateway_client = gateway_client
        self._clock = clock or (lambda: datetime.now(UTC))

    async def publish(self, draft_id: str) -> PublishResult:
        draft = await self._mongo_db["publicador_drafts"].find_one({"_id": draft_id})
        if draft is None:
            raise DraftNotFoundError(draft_id)

        seller_id = str(draft["seller_id"])
        payload = _build_meli_payload(draft)
        validation_response = await self._gateway_client.request(
            "POST", "/items/validate", seller_id=seller_id, json=payload
        )
        if validation_response.get("status") != "valid":
            await self._record_outcome(
                draft=draft,
                outcome="validation_failed",
                gateway_response=validation_response,
                item_id=None,
                error=", ".join(str(error) for error in validation_response.get("errors", []))
                or "validation failed",
            )
            raise PublishValidationError(
                ", ".join(str(error) for error in validation_response.get("errors", []))
                or "validation failed"
            )

        publish_response = await self._gateway_client.request(
            "POST", "/items", seller_id=seller_id, json=payload
        )
        item_id = (
            str(publish_response.get("id")) if publish_response.get("id") is not None else None
        )
        await self._record_outcome(
            draft=draft,
            outcome="published",
            gateway_response=publish_response,
            item_id=item_id,
            error=None,
        )
        return PublishResult(item_id=item_id, outcome="published", payload=payload)

    async def _record_outcome(
        self,
        *,
        draft: dict[str, Any],
        outcome: str,
        gateway_response: dict[str, Any],
        item_id: str | None,
        error: str | None,
    ) -> None:
        created_at = self._clock()
        updated_draft = {**draft, "status": outcome, "updated_at": created_at}
        await self._mongo_db["publicador_drafts"].replace_one(
            {"_id": draft["_id"]}, updated_draft, upsert=True
        )
        await self._mongo_db["publicador_history"].insert_one(
            {
                "_id": f"publicador-history-{draft['_id']}-{int(created_at.timestamp())}",
                "seller_id": str(draft["seller_id"]),
                "draft_id": str(draft["_id"]),
                "action": "publish",
                "outcome": outcome,
                "meli_item_id": item_id,
                "gateway_response": gateway_response,
                "error": error,
                "created_at": created_at,
                "schema_version": 1,
            }
        )


def _build_meli_payload(draft: dict[str, Any]) -> dict[str, Any]:
    listing = draft["generated_listing"]
    source = draft["source_product"]
    return {
        "title": listing["title"],
        "description": listing["description"],
        "attributes": listing.get("attributes", {}),
        "price": source.get("price"),
        "category_id": source.get("category_id"),
        "seller_custom_field": source.get("sku"),
    }
