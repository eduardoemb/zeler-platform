from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import quote_plus

from zeler_publicador.schemas import SCHEMA_VERSION


class MeliGateway(Protocol):
    async def request(
        self, method: str, path: str, json: dict[str, Any] | None = None
    ) -> Any: ...


class MissingMeliGateway:
    async def request(
        self, _method: str, _path: str, json: dict[str, Any] | None = None
    ) -> Any:
        raise RuntimeError("publicador_meli_gateway_not_configured")


class MeliPublicationService:
    def __init__(
        self,
        mongo_db: Any,
        *,
        gateway: MeliGateway | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._mongo_db = mongo_db
        self._gateway = gateway or MissingMeliGateway()
        self._clock = clock or (lambda: datetime.now(UTC))

    async def predict_categories(
        self, *, seller_id: str, account_id: str, query: str
    ) -> list[dict[str, Any]]:
        self._require_scope(seller_id=seller_id, account_id=account_id)
        response = await self._gateway.request(
            "GET", f"/sites/MLM/domain_discovery/search?limit=8&q={quote_plus(query)}"
        )
        return [
            {
                "category_id": str(item["category_id"]),
                "category_name": str(item.get("category_name") or item["category_id"]),
                "domain_id": str(item.get("domain_id") or ""),
            }
            for item in response
        ]

    async def required_attributes(
        self, *, seller_id: str, account_id: str, category_id: str
    ) -> list[dict[str, Any]]:
        self._require_scope(seller_id=seller_id, account_id=account_id)
        response = await self._gateway.request("GET", f"/categories/{category_id}/attributes")
        return [
            {
                "id": str(attribute["id"]),
                "name": str(attribute.get("name") or attribute["id"]),
                "required": bool(attribute.get("tags", {}).get("required")),
            }
            for attribute in response
        ]

    async def publication_preferences(self, *, seller_id: str, account_id: str) -> dict[str, Any]:
        self._require_scope(seller_id=seller_id, account_id=account_id)
        settings = await self._mongo_db["publicador_settings"].find_one(
            {"seller_id": seller_id, "account_id": account_id}
        )
        listing_types = await self._gateway.request("GET", "/sites/MLM/listing_types")
        shipping = await self._gateway.request("GET", f"/users/{seller_id}/shipping_preferences")
        brands = await self._gateway.request("GET", f"/users/{seller_id}/brands")
        stores = await self._gateway.request("GET", f"/users/{seller_id}/stores/search")
        return {
            "seller_id": seller_id,
            "account_id": account_id,
            "defaults": dict(settings.get("defaults", {})) if settings else {},
            "listing_types": list(listing_types),
            "shipping_modes": list(shipping.get("logistics", [])),
            "brands": list(brands),
            "official_stores": list(stores),
        }

    async def validate_draft(
        self, *, seller_id: str, account_id: str, draft_id: str, actor_id: str
    ) -> dict[str, Any]:
        draft = await self._load_draft(
            seller_id=seller_id, account_id=account_id, draft_id=draft_id
        )
        attributes = await self.required_attributes(
            seller_id=seller_id,
            account_id=account_id,
            category_id=str(draft.get("category_id") or ""),
        )
        preferences = await self.publication_preferences(seller_id=seller_id, account_id=account_id)
        field_errors = self._local_field_errors(
            draft=draft, required_attributes=attributes, preferences=preferences
        )
        payload = await self.build_publish_payload(draft)
        if field_errors:
            await self._block_draft(draft, field_errors=field_errors, actor_id=actor_id)
            return {"status": "blocked", "field_errors": field_errors, "payload": payload}

        gateway_validation = await self._gateway.request("POST", "/items/validate", json=payload)
        gateway_errors = self._gateway_field_errors(gateway_validation)
        if gateway_errors:
            await self._block_draft(draft, field_errors=gateway_errors, actor_id=actor_id)
            return {"status": "blocked", "field_errors": gateway_errors, "payload": payload}
        return {"status": "valid", "field_errors": [], "payload": payload}

    async def validate_and_publish_draft(
        self, *, seller_id: str, account_id: str, draft_id: str, actor_id: str
    ) -> dict[str, Any]:
        validation = await self.validate_draft(
            seller_id=seller_id, account_id=account_id, draft_id=draft_id, actor_id=actor_id
        )
        if validation["status"] != "valid":
            return validation

        draft = await self._load_draft(
            seller_id=seller_id, account_id=account_id, draft_id=draft_id
        )
        response = await self._gateway.request("POST", "/items", json=validation["payload"])
        now = self._clock()
        updated = {
            **draft,
            "status": "published",
            "process_status": "published",
            "meli_item_id": response.get("id"),
            "permalink": response.get("permalink"),
            "meli_response": response,
            "errors": [],
            "updated_at": now,
            "updated_by": actor_id,
        }
        await self._replace_draft(updated)
        await self._append_event(
            updated, operation="draft.published", status="published", actor_id=actor_id
        )
        return {"status": "published", **updated, "payload": validation["payload"]}

    async def build_publish_payload(self, draft: dict[str, Any]) -> dict[str, Any]:
        attributes = [
            {"id": key, "value_name": str(value)}
            for key, value in dict(draft.get("attributes", {})).items()
            if value not in (None, "")
        ]
        gtin = draft.get("gtin")
        if gtin:
            attributes.append({"id": "GTIN", "value_name": str(gtin)})
        pictures = [
            {"id": asset["meli_picture_id"]}
            for asset in await self._mongo_db["publicador_assets"].find(
                {
                    "seller_id": draft["seller_id"],
                    "account_id": draft["account_id"],
                    "owner_id": draft["_id"],
                }
            ).to_list(length=10)
            if asset.get("meli_picture_id")
        ]
        payload: dict[str, Any] = {
            "title": draft["title"],
            "category_id": draft["category_id"],
            "price": draft["price"],
            "currency_id": "MXN",
            "available_quantity": 0,
            "status": "paused",
            "buying_mode": "buy_it_now",
            "condition": "new",
            "listing_type_id": draft["listing_type"],
            "attributes": attributes,
            "pictures": pictures,
            "shipping": {
                "mode": draft["logistics_type"],
                "free_shipping": bool(draft.get("free_shipping", False)),
            },
        }
        if draft.get("official_store_id"):
            payload["official_store_id"] = draft["official_store_id"]
        if draft.get("description"):
            payload["description"] = {"plain_text": draft["description"]}
        if draft.get("warranty"):
            payload["sale_terms"] = [{"id": "WARRANTY_TYPE", "value_name": draft["warranty"]}]
        if draft.get("catalog_product_id"):
            payload["catalog_product_id"] = draft["catalog_product_id"]
        return payload

    async def _load_draft(
        self, *, seller_id: str, account_id: str, draft_id: str
    ) -> dict[str, Any]:
        draft = await self._mongo_db["publicador_drafts"].find_one(
            {"_id": draft_id, "seller_id": seller_id, "account_id": account_id}
        )
        if draft is None:
            raise ValueError("publicador_draft_not_found")
        return draft

    def _local_field_errors(
        self,
        *,
        draft: dict[str, Any],
        required_attributes: list[dict[str, Any]],
        preferences: dict[str, Any],
    ) -> list[dict[str, str]]:
        errors: list[dict[str, str]] = []
        gtin = str(draft.get("gtin") or "")
        if not gtin.isdigit() or not 8 <= len(gtin) <= 14:
            errors.append({"field": "gtin", "message": "GTIN is required and must be numeric"})
        draft_attributes = dict(draft.get("attributes", {}))
        for attribute in required_attributes:
            if attribute["required"] and not draft_attributes.get(attribute["id"]):
                errors.append(
                    {
                        "field": f"attributes.{attribute['id']}",
                        "message": (
                            f"{attribute['name']} is required by category "
                            f"{draft.get('category_id')}"
                        ),
                    }
                )
        listing_ids = {item["id"] for item in preferences.get("listing_types", [])}
        if draft.get("listing_type") not in listing_ids:
            errors.append(
                {
                    "field": "listing_type",
                    "message": f"{draft.get('listing_type')} is not enabled for this account",
                }
            )
        shipping_types = {item["type"] for item in preferences.get("shipping_modes", [])}
        if draft.get("logistics_type") not in shipping_types:
            errors.append(
                {
                    "field": "logistics_type",
                    "message": f"{draft.get('logistics_type')} is not enabled for this account",
                }
            )
        return errors

    async def _block_draft(
        self, draft: dict[str, Any], *, field_errors: list[dict[str, str]], actor_id: str
    ) -> None:
        updated = {
            **draft,
            "status": "validation_failed",
            "process_status": "failed",
            "errors": field_errors,
            "updated_at": self._clock(),
            "updated_by": actor_id,
        }
        await self._replace_draft(updated)
        await self._append_event(
            updated,
            operation="draft.validation_blocked",
            status="blocked",
            actor_id=actor_id,
            details={"field_errors": field_errors},
        )

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

    async def _append_event(
        self,
        draft: dict[str, Any],
        *,
        operation: str,
        status: str,
        actor_id: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        await self._mongo_db["publicador_events"].insert_one(
            {
                "_id": f"event-{operation}-{draft['_id']}",
                "seller_id": draft["seller_id"],
                "account_id": draft["account_id"],
                "aggregate_type": "draft",
                "aggregate_id": draft["_id"],
                "draft_id": draft["_id"],
                "operation": operation,
                "status": status,
                "actor_id": actor_id,
                "details": details or {},
                "created_at": self._clock(),
                "schema_version": SCHEMA_VERSION,
            }
        )

    @staticmethod
    def _gateway_field_errors(response: dict[str, Any]) -> list[dict[str, str]]:
        return [
            {"field": str(error["field"]), "message": str(error["message"])}
            for error in response.get("field_errors", [])
        ]

    @staticmethod
    def _require_scope(*, seller_id: str, account_id: str) -> None:
        if not seller_id or not account_id:
            raise ValueError("seller_id_and_account_id_required")
