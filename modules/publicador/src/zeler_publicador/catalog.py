from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import quote_plus, urlencode
from uuid import uuid4

from zeler_publicador.meli import MeliGateway, MeliPublicationService, MissingMeliGateway
from zeler_publicador.schemas import SCHEMA_VERSION


class CatalogSuggestionService:
    def __init__(
        self,
        mongo_db: Any,
        *,
        gateway: MeliGateway | None = None,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[str], str] | None = None,
    ) -> None:
        self._mongo_db = mongo_db
        self._gateway = gateway or MissingMeliGateway()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_factory = id_factory or (lambda prefix: f"{prefix}-{uuid4().hex}")

    async def search_catalog(
        self,
        *,
        seller_id: str,
        account_id: str,
        query: str | None = None,
        gtin: str | None = None,
        permalink: str | None = None,
    ) -> list[dict[str, Any]]:
        self._require_scope(seller_id=seller_id, account_id=account_id)
        params = {"site_id": "MLM"}
        if query:
            params["q"] = query
        if gtin:
            params["product_identifier"] = gtin
        if permalink:
            params["permalink"] = permalink
        response = await self._gateway.request(
            "GET", f"/products/search?{urlencode(params, quote_via=quote_plus)}"
        )
        return [self._catalog_candidate(item) for item in response.get("results", [])]

    async def publish_catalog_link(
        self,
        *,
        seller_id: str,
        account_id: str,
        draft_id: str,
        catalog_product_id: str,
        actor_id: str,
    ) -> dict[str, Any]:
        draft = await self._load_draft(
            seller_id=seller_id, account_id=account_id, draft_id=draft_id
        )
        updated = {
            **draft,
            "catalog_product_id": catalog_product_id,
            "is_catalog": True,
            "updated_at": self._clock(),
            "updated_by": actor_id,
        }
        await self._replace_draft(updated)
        await self._append_event(
            seller_id=seller_id,
            account_id=account_id,
            aggregate_type="draft",
            aggregate_id=draft_id,
            operation="catalog.linked",
            status="linked",
            actor_id=actor_id,
            details={"catalog_product_id": catalog_product_id},
        )
        result = await MeliPublicationService(
            self._mongo_db, gateway=self._gateway, clock=self._clock
        ).validate_and_publish_draft(
            seller_id=seller_id, account_id=account_id, draft_id=draft_id, actor_id=actor_id
        )
        return {**result, "catalog_product_id": catalog_product_id}

    async def create_for_draft(
        self, *, seller_id: str, account_id: str, draft_id: str, actor_id: str
    ) -> dict[str, Any]:
        draft = await self._load_draft(
            seller_id=seller_id, account_id=account_id, draft_id=draft_id
        )
        now = self._clock()
        suggestion: dict[str, Any] = {
            "_id": self._id_factory("suggestion"),
            "seller_id": seller_id,
            "account_id": account_id,
            "draft_id": draft_id,
            "batch_item_id": None,
            "sku": draft.get("sku"),
            "gtin": draft.get("gtin"),
            "title": draft.get("title"),
            "catalog_product_id": None,
            "suggestion_id": None,
            "meli_picture_ids": [],
            "status": "draft",
            "validation_errors": [],
            "errors": [],
            "created_at": now,
            "updated_at": now,
            "created_by": actor_id,
            "updated_by": actor_id,
            "schema_version": SCHEMA_VERSION,
        }
        await self._mongo_db["publicador_catalog_suggestions"].insert_one(suggestion)
        await self._append_suggestion_event(
            suggestion,
            operation="catalog_suggestion.created",
            status="draft",
            actor_id=actor_id,
        )
        return suggestion

    async def list_suggestions(
        self,
        *,
        seller_id: str,
        account_id: str,
        status: str | None = None,
        draft_id: str | None = None,
    ) -> list[dict[str, Any]]:
        query: dict[str, Any] = {"seller_id": seller_id, "account_id": account_id}
        if status:
            query["status"] = status
        if draft_id:
            query["draft_id"] = draft_id
        return cast(
            list[dict[str, Any]],
            await self._mongo_db["publicador_catalog_suggestions"].find(query).to_list(length=100),
        )

    async def get_suggestion(
        self, *, seller_id: str, account_id: str, suggestion_id: str
    ) -> dict[str, Any] | None:
        suggestion = await self._mongo_db["publicador_catalog_suggestions"].find_one(
            {"_id": suggestion_id, "seller_id": seller_id, "account_id": account_id}
        )
        if suggestion is None:
            return None
        return {**suggestion, "history": await self._history_for_suggestion(suggestion)}

    async def validate_suggestion(
        self, *, seller_id: str, account_id: str, suggestion_id: str, actor_id: str
    ) -> dict[str, Any]:
        suggestion = await self._load_suggestion(
            seller_id=seller_id, account_id=account_id, suggestion_id=suggestion_id
        )
        picture_ids = await self._suggestion_picture_ids(suggestion)
        payload = self._suggestion_payload(suggestion, picture_ids=picture_ids)
        response = await self._gateway.request(
            "POST", "/catalog_suggestions/validate", json=payload
        )
        errors = list(response.get("errors", []))
        status = "validation_failed" if errors else "validated"
        return await self._update_suggestion(
            suggestion,
            updates={
                "status": status,
                "meli_picture_ids": picture_ids,
                "validation_errors": errors,
                "errors": errors,
            },
            operation="catalog_suggestion.validated",
            event_status=status,
            actor_id=actor_id,
            details={"validation_errors": errors},
        )

    async def send_suggestion(
        self, *, seller_id: str, account_id: str, suggestion_id: str, actor_id: str
    ) -> dict[str, Any]:
        suggestion = await self._load_suggestion(
            seller_id=seller_id, account_id=account_id, suggestion_id=suggestion_id
        )
        picture_ids = suggestion.get("meli_picture_ids") or await self._suggestion_picture_ids(
            suggestion
        )
        response = await self._gateway.request(
            "POST",
            "/catalog_suggestions",
            json=self._suggestion_payload(suggestion, picture_ids=picture_ids),
        )
        return await self._update_suggestion(
            suggestion,
            updates={
                "suggestion_id": response.get("id"),
                "status": response.get("status") or "sent",
                "meli_picture_ids": picture_ids,
                "errors": list(response.get("errors", [])),
            },
            operation="catalog_suggestion.sent",
            event_status="sent",
            actor_id=actor_id,
            details={"suggestion_id": response.get("id")},
        )

    async def refresh_status(
        self, *, seller_id: str, account_id: str, suggestion_id: str, actor_id: str
    ) -> dict[str, Any]:
        suggestion = await self._load_suggestion(
            seller_id=seller_id, account_id=account_id, suggestion_id=suggestion_id
        )
        meli_id = suggestion.get("suggestion_id")
        if not meli_id:
            raise ValueError("publicador_catalog_suggestion_not_sent")
        response = await self._gateway.request("GET", f"/catalog_suggestions/{meli_id}")
        return await self._update_suggestion(
            suggestion,
            updates={
                "status": response.get("status") or suggestion["status"],
                "catalog_product_id": response.get(
                    "catalog_product_id", suggestion.get("catalog_product_id")
                ),
                "errors": list(response.get("errors", [])),
            },
            operation="catalog_suggestion.status_refreshed",
            event_status=str(response.get("status") or suggestion["status"]),
            actor_id=actor_id,
            details={"gateway_status": response},
        )

    async def process_notification(
        self, *, seller_id: str, account_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        meli_id = str(payload.get("suggestion_id") or "")
        suggestion = await self._mongo_db["publicador_catalog_suggestions"].find_one(
            {"seller_id": seller_id, "account_id": account_id, "suggestion_id": meli_id}
        )
        if suggestion is None:
            raise ValueError("publicador_catalog_suggestion_not_found")
        return await self._update_suggestion(
            suggestion,
            updates={
                "status": payload.get("status") or suggestion["status"],
                "catalog_product_id": payload.get(
                    "catalog_product_id", suggestion.get("catalog_product_id")
                ),
                "notification": {key: value for key, value in payload.items() if key != "raw"},
            },
            operation="catalog_suggestion.notification_processed",
            event_status=str(payload.get("status") or suggestion["status"]),
            actor_id="meli-notification",
            details={
                "notification": {key: value for key, value in payload.items() if key != "raw"}
            },
        )

    async def _load_draft(
        self, *, seller_id: str, account_id: str, draft_id: str
    ) -> dict[str, Any]:
        draft = await self._mongo_db["publicador_drafts"].find_one(
            {"_id": draft_id, "seller_id": seller_id, "account_id": account_id}
        )
        if draft is None:
            raise ValueError("publicador_draft_not_found")
        return cast(dict[str, Any], draft)

    async def _load_suggestion(
        self, *, seller_id: str, account_id: str, suggestion_id: str
    ) -> dict[str, Any]:
        suggestion = await self._mongo_db["publicador_catalog_suggestions"].find_one(
            {"_id": suggestion_id, "seller_id": seller_id, "account_id": account_id}
        )
        if suggestion is None:
            raise ValueError("publicador_catalog_suggestion_not_found")
        return cast(dict[str, Any], suggestion)

    async def _replace_draft(self, draft: dict[str, Any]) -> None:
        await self._mongo_db["publicador_drafts"].replace_one(
            {
                "_id": draft["_id"],
                "seller_id": draft["seller_id"],
                "account_id": draft["account_id"],
            },
            draft,
            upsert=False,
        )

    async def _update_suggestion(
        self,
        suggestion: dict[str, Any],
        *,
        updates: dict[str, Any],
        operation: str,
        event_status: str,
        actor_id: str,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        updated = {**suggestion, **updates, "updated_at": self._clock(), "updated_by": actor_id}
        await self._mongo_db["publicador_catalog_suggestions"].replace_one(
            {
                "_id": updated["_id"],
                "seller_id": updated["seller_id"],
                "account_id": updated["account_id"],
            },
            updated,
            upsert=False,
        )
        await self._append_suggestion_event(
            updated,
            operation=operation,
            status=event_status,
            actor_id=actor_id,
            details=details,
        )
        return updated

    async def _suggestion_picture_ids(self, suggestion: dict[str, Any]) -> list[str]:
        assets = (
            await self._mongo_db["publicador_assets"]
            .find(
                {
                    "seller_id": suggestion["seller_id"],
                    "account_id": suggestion["account_id"],
                    "owner_type": "suggestion",
                    "owner_id": suggestion["_id"],
                }
            )
            .to_list(length=10)
        )
        return [str(asset["meli_picture_id"]) for asset in assets if asset.get("meli_picture_id")]

    async def _history_for_suggestion(self, suggestion: dict[str, Any]) -> list[dict[str, Any]]:
        return cast(
            list[dict[str, Any]],
            await self._mongo_db["publicador_events"]
            .find(
                {
                    "seller_id": suggestion["seller_id"],
                    "account_id": suggestion["account_id"],
                    "aggregate_type": "catalog_suggestion",
                    "aggregate_id": suggestion["_id"],
                }
            )
            .to_list(length=100),
        )

    async def _append_suggestion_event(
        self,
        suggestion: dict[str, Any],
        *,
        operation: str,
        status: str,
        actor_id: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        await self._append_event(
            seller_id=suggestion["seller_id"],
            account_id=suggestion["account_id"],
            aggregate_type="catalog_suggestion",
            aggregate_id=suggestion["_id"],
            operation=operation,
            status=status,
            actor_id=actor_id,
            details=details,
        )

    async def _append_event(
        self,
        *,
        seller_id: str,
        account_id: str,
        aggregate_type: str,
        aggregate_id: str,
        operation: str,
        status: str,
        actor_id: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        await self._mongo_db["publicador_events"].insert_one(
            {
                "_id": self._id_factory("event"),
                "seller_id": seller_id,
                "account_id": account_id,
                "aggregate_type": aggregate_type,
                "aggregate_id": aggregate_id,
                "operation": operation,
                "status": status,
                "actor_id": actor_id,
                "details": details or {},
                "created_at": self._clock(),
                "schema_version": SCHEMA_VERSION,
            }
        )

    @staticmethod
    def _catalog_candidate(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "catalog_product_id": str(item["id"]),
            "name": str(item.get("name") or item["id"]),
            "domain_id": str(item.get("domain_id") or ""),
            "permalink": item.get("permalink"),
        }

    @staticmethod
    def _suggestion_payload(
        suggestion: dict[str, Any], *, picture_ids: list[str]
    ) -> dict[str, Any]:
        return {
            "title": suggestion.get("title"),
            "gtin": suggestion.get("gtin"),
            "sku": suggestion.get("sku"),
            "pictures": [{"id": picture_id} for picture_id in picture_ids],
        }

    @staticmethod
    def _require_scope(*, seller_id: str, account_id: str) -> None:
        if not seller_id or not account_id:
            raise ValueError("seller_id_and_account_id_required")
