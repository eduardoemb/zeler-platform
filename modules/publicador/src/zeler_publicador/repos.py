from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from zeler_publicador.schemas import SCHEMA_VERSION, DraftCreate, DraftRead, DraftUpdate

DraftTransition = str


class PublicadorRepository:
    def __init__(
        self,
        mongo_db: Any,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[str], str] | None = None,
    ) -> None:
        self._mongo_db = mongo_db
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_factory = id_factory or (lambda prefix: f"{prefix}-{uuid4().hex}")

    async def create_draft(self, draft: DraftCreate) -> DraftRead:
        now = self._clock()
        draft_id = self._id_factory("draft")
        document: dict[str, Any] = {
            "_id": draft_id,
            "seller_id": draft.seller_id,
            "account_id": draft.account_id,
            "sku": draft.sku,
            "gtin": draft.gtin,
            "title": draft.title,
            "family_name": draft.family_name,
            "description": draft.description,
            "category_id": draft.category_id,
            "domain_id": draft.domain_id,
            "attributes": draft.attributes,
            "price": draft.price,
            "logistics_type": draft.logistics_type,
            "listing_type": draft.listing_type,
            "free_shipping": draft.free_shipping,
            "official_store_id": draft.official_store_id,
            "brand": draft.brand,
            "catalog_product_id": draft.catalog_product_id,
            "is_catalog": draft.catalog_product_id is not None,
            "warranty": draft.warranty,
            "asset_ids": [],
            "source_product": {
                "name": draft.title,
                "sku": draft.sku,
                "gtin": draft.gtin,
                "category_id": draft.category_id,
                "price": draft.price,
                "logistics_type": draft.logistics_type,
                "listing_type": draft.listing_type,
                "free_shipping": draft.free_shipping,
            },
            "generated_listing": {},
            "status": "draft",
            "enrichment_status": "pending",
            "approval_status": "draft",
            "process_status": "not_started",
            "meli_item_id": None,
            "permalink": None,
            "errors": [],
            "created_at": now,
            "updated_at": now,
            "created_by": draft.created_by,
            "updated_by": draft.created_by,
            "schema_version": SCHEMA_VERSION,
        }
        await self._mongo_db["publicador_drafts"].insert_one(document)
        await self._append_event(
            document,
            operation="draft.created",
            status="created",
            actor_id=draft.created_by,
        )
        return DraftRead.model_validate(document)

    async def list_drafts(
        self, *, seller_id: str, account_id: str | None = None
    ) -> list[dict[str, Any]]:
        query: dict[str, Any] = {"seller_id": seller_id}
        if account_id is not None:
            query["account_id"] = account_id
        return cast(
            list[dict[str, Any]],
            await self._mongo_db["publicador_drafts"].find(query).to_list(length=100),
        )

    async def get_draft(
        self, *, draft_id: str, seller_id: str, account_id: str | None = None
    ) -> dict[str, Any] | None:
        query: dict[str, Any] = {"_id": draft_id, "seller_id": seller_id}
        if account_id is not None:
            query["account_id"] = account_id
        return cast(
            dict[str, Any] | None, await self._mongo_db["publicador_drafts"].find_one(query)
        )

    async def update_draft(
        self,
        *,
        draft_id: str,
        seller_id: str,
        account_id: str,
        update: DraftUpdate,
        actor_id: str,
    ) -> dict[str, Any] | None:
        draft = await self.get_draft(draft_id=draft_id, seller_id=seller_id, account_id=account_id)
        if draft is None:
            return None

        changes = update.model_dump(exclude_none=True, exclude={"updated_by"})
        if not changes:
            return draft

        updated = {**draft, **changes, "updated_at": self._clock(), "updated_by": actor_id}
        updated["is_catalog"] = bool(updated.get("catalog_product_id"))
        updated["source_product"] = self._source_product_from_draft(updated)
        await self._mongo_db["publicador_drafts"].replace_one(
            {"_id": draft_id, "seller_id": seller_id, "account_id": account_id},
            updated,
            upsert=False,
        )
        await self._append_event(
            updated,
            operation="draft.updated",
            status="updated",
            actor_id=actor_id,
        )
        return updated

    async def transition_draft(
        self,
        *,
        draft_id: str,
        seller_id: str,
        account_id: str,
        action: DraftTransition,
        actor_id: str,
        reason: str | None = None,
    ) -> dict[str, Any] | None:
        draft = await self.get_draft(draft_id=draft_id, seller_id=seller_id, account_id=account_id)
        if draft is None:
            return None

        now = self._clock()
        updated = {**draft, "updated_at": now, "updated_by": actor_id}
        operation: str
        event_status: str
        if action == "reject":
            updated["approval_status"] = "rejected"
            updated["rejection_reason"] = reason or "Rejected without reason"
            operation = "draft.rejected"
            event_status = "rejected"
        elif action == "approve":
            updated["approval_status"] = "approved"
            updated.pop("rejection_reason", None)
            operation = "draft.approved"
            event_status = "approved"
        elif action == "process":
            updated["process_status"] = "processing"
            operation = "draft.process_requested"
            event_status = "processing"
        else:
            raise ValueError(f"Unsupported publicador draft action: {action}")

        await self._mongo_db["publicador_drafts"].replace_one(
            {"_id": draft_id, "seller_id": seller_id, "account_id": account_id},
            updated,
            upsert=False,
        )
        await self._append_event(
            updated,
            operation=operation,
            status=event_status,
            actor_id=actor_id,
            reason=reason,
        )
        return updated

    async def history_for_draft(
        self, *, draft_id: str, seller_id: str, account_id: str
    ) -> list[dict[str, Any]]:
        return cast(
            list[dict[str, Any]],
            await self._mongo_db["publicador_events"]
            .find(
                {
                    "seller_id": seller_id,
                    "account_id": account_id,
                    "aggregate_type": "draft",
                    "aggregate_id": draft_id,
                }
            )
            .to_list(length=100),
        )

    async def _append_event(
        self,
        draft: dict[str, Any],
        *,
        operation: str,
        status: str,
        actor_id: str,
        reason: str | None = None,
    ) -> None:
        now = self._clock()
        event = {
            "_id": self._id_factory("event"),
            "seller_id": draft["seller_id"],
            "account_id": draft["account_id"],
            "aggregate_type": "draft",
            "aggregate_id": draft["_id"],
            "draft_id": draft["_id"],
            "operation": operation,
            "status": status,
            "actor_id": actor_id,
            "reason": reason,
            "created_at": now,
            "schema_version": SCHEMA_VERSION,
        }
        await self._mongo_db["publicador_events"].insert_one(event)

    @staticmethod
    def _source_product_from_draft(draft: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": draft.get("title"),
            "sku": draft.get("sku"),
            "gtin": draft.get("gtin"),
            "category_id": draft.get("category_id"),
            "price": draft.get("price"),
            "logistics_type": draft.get("logistics_type"),
            "listing_type": draft.get("listing_type"),
            "free_shipping": draft.get("free_shipping", False),
        }
