from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, cast
from uuid import uuid4

from zeler_publicador.batch_parser import (
    LegacyBatchContractError,
    ParsedBatchRow,
    parse_legacy_batch_zip,
)
from zeler_publicador.meli import MeliGateway, MeliPublicationService
from zeler_publicador.schemas import SCHEMA_VERSION


class PublicadorBatchError(ValueError):
    """Raised when a batch lifecycle operation cannot be completed."""


class PublicadorBatchService:
    def __init__(
        self,
        mongo_db: Any,
        *,
        meli_gateway: MeliGateway | None = None,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[str], str] | None = None,
    ) -> None:
        self._mongo_db = mongo_db
        self._meli_gateway = meli_gateway
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_factory = id_factory or (lambda prefix: f"{prefix}-{uuid4().hex}")

    async def create_from_zip(
        self,
        *,
        seller_id: str,
        account_id: str,
        source_filename: str,
        content: bytes,
        actor_id: str,
    ) -> dict[str, Any]:
        parsed = parse_legacy_batch_zip(content)
        if parsed.account_id != account_id:
            raise PublicadorBatchError("publicador_batch_account_not_linked")
        idempotency_key = sha256(content).hexdigest()
        existing = await self._mongo_db["publicador_batches"].find_one(
            {"seller_id": seller_id, "account_id": account_id, "idempotency_key": idempotency_key}
        )
        if existing is not None:
            return cast(dict[str, Any], existing)

        now = self._clock()
        batch: dict[str, Any] = {
            "_id": self._id_factory("batch"),
            "seller_id": seller_id,
            "account_id": account_id,
            "source_filename": source_filename,
            "idempotency_key": idempotency_key,
            "status": "preview_ready",
            "process_status": "not_started",
            "publish_status": "not_started",
            "counts": _empty_counts(),
            "errors": [],
            "warnings": parsed.global_warnings,
            "created_at": now,
            "updated_at": now,
            "created_by": actor_id,
            "updated_by": actor_id,
            "schema_version": SCHEMA_VERSION,
        }
        await self._mongo_db["publicador_batches"].insert_one(batch)
        items = [
            self._item_from_row(batch=batch, row=row, actor_id=actor_id) for row in parsed.rows
        ]
        for item in items:
            await self._mongo_db["publicador_batch_items"].insert_one(item)
        await self._refresh_counts(
            batch_id=batch["_id"], seller_id=seller_id, account_id=account_id
        )
        created = await self._load_batch(
            seller_id=seller_id, account_id=account_id, batch_id=batch["_id"]
        )
        await self._append_event(
            seller_id=seller_id,
            account_id=account_id,
            aggregate_type="batch",
            aggregate_id=batch["_id"],
            operation="batch.uploaded",
            status="preview_ready",
            actor_id=actor_id,
        )
        return created

    async def list_batches(self, *, seller_id: str, account_id: str) -> list[dict[str, Any]]:
        return cast(
            list[dict[str, Any]],
            await self._mongo_db["publicador_batches"]
            .find({"seller_id": seller_id, "account_id": account_id})
            .to_list(length=100),
        )

    async def batch_detail(
        self, *, seller_id: str, account_id: str, batch_id: str
    ) -> dict[str, Any] | None:
        batch = await self._mongo_db["publicador_batches"].find_one(
            {"_id": batch_id, "seller_id": seller_id, "account_id": account_id}
        )
        if batch is None:
            return None
        items = await self._items_for_batch(
            seller_id=seller_id, account_id=account_id, batch_id=batch_id
        )
        return {**batch, "items": items}

    async def process_batch(
        self, *, seller_id: str, account_id: str, batch_id: str, actor_id: str
    ) -> dict[str, Any]:
        batch = await self._load_batch(
            seller_id=seller_id, account_id=account_id, batch_id=batch_id
        )
        queued = [
            item
            for item in await self._items_for_batch(
                seller_id=seller_id, account_id=account_id, batch_id=batch_id
            )
            if item["status"] in {"queued", "retryable"}
        ]
        for item in queued:
            draft = await self._create_draft_from_item(item=item, actor_id=actor_id)
            await self._replace_item(
                {
                    **item,
                    "status": "processed",
                    "process_status": "processed",
                    "draft_id": draft["_id"],
                    "updated_at": self._clock(),
                    "updated_by": actor_id,
                }
            )
        await self._replace_batch(
            {
                **batch,
                "status": "processed",
                "process_status": "processed",
                "updated_at": self._clock(),
            }
        )
        await self._refresh_counts(batch_id=batch_id, seller_id=seller_id, account_id=account_id)
        await self._append_event(
            seller_id=seller_id,
            account_id=account_id,
            aggregate_type="batch",
            aggregate_id=batch_id,
            operation="batch.processed",
            status="processed",
            actor_id=actor_id,
        )
        return await self._load_batch(seller_id=seller_id, account_id=account_id, batch_id=batch_id)

    async def publish_batch(
        self, *, seller_id: str, account_id: str, batch_id: str, actor_id: str
    ) -> dict[str, Any]:
        batch = await self._load_batch(
            seller_id=seller_id, account_id=account_id, batch_id=batch_id
        )
        items = [
            item
            for item in await self._items_for_batch(
                seller_id=seller_id, account_id=account_id, batch_id=batch_id
            )
            if item["status"] in {"processed", "publish_failed"} and item.get("draft_id")
        ]
        publication_service = MeliPublicationService(
            self._mongo_db, gateway=self._meli_gateway, clock=self._clock
        )
        for item in items:
            try:
                result = await publication_service.validate_and_publish_draft(
                    seller_id=seller_id,
                    account_id=account_id,
                    draft_id=str(item["draft_id"]),
                    actor_id=actor_id,
                )
            except (RuntimeError, ValueError, LegacyBatchContractError) as exc:
                await self._replace_item(self._failed_item(item, actor_id=actor_id, error=str(exc)))
                continue
            if result["status"] == "published":
                await self._replace_item(
                    {
                        **item,
                        "status": "published",
                        "publish_status": "published",
                        "meli_item_id": result.get("meli_item_id"),
                        "permalink": result.get("permalink"),
                        "updated_at": self._clock(),
                        "updated_by": actor_id,
                    }
                )
            else:
                await self._replace_item(
                    self._failed_item(item, actor_id=actor_id, error="batch_item_publish_blocked")
                )
        status = "published"
        await self._replace_batch(
            {**batch, "status": status, "publish_status": status, "updated_at": self._clock()}
        )
        await self._refresh_counts(batch_id=batch_id, seller_id=seller_id, account_id=account_id)
        await self._append_event(
            seller_id=seller_id,
            account_id=account_id,
            aggregate_type="batch",
            aggregate_id=batch_id,
            operation="batch.published",
            status=status,
            actor_id=actor_id,
        )
        return await self._load_batch(seller_id=seller_id, account_id=account_id, batch_id=batch_id)

    def _item_from_row(
        self, *, batch: dict[str, Any], row: ParsedBatchRow, actor_id: str
    ) -> dict[str, Any]:
        now = self._clock()
        status = "blocked" if row.errors else "queued"
        return {
            "_id": self._id_factory("batch_item"),
            "batch_id": batch["_id"],
            "seller_id": batch["seller_id"],
            "account_id": batch["account_id"],
            "row_number": row.row_number,
            "sku": row.sku,
            "gtin": row.codigo_barras,
            "price": row.price,
            "logistics_type": row.logistics_type,
            "listing_type": row.listing_type,
            "free_shipping": row.free_shipping,
            "publicar": row.publicar,
            "raw": row.raw,
            "images": [
                {
                    "filename": image.filename,
                    "content_type": image.content_type,
                    "width": image.width,
                    "height": image.height,
                    "hash": image.hash,
                }
                for image in row.images
            ],
            "draft_id": None,
            "status": status,
            "process_status": status,
            "publish_status": "blocked" if row.errors else "not_started",
            "retry_count": 0,
            "errors": row.errors,
            "created_at": now,
            "updated_at": now,
            "created_by": actor_id,
            "updated_by": actor_id,
            "schema_version": SCHEMA_VERSION,
        }

    async def _create_draft_from_item(
        self, *, item: dict[str, Any], actor_id: str
    ) -> dict[str, Any]:
        existing_draft_id = item.get("draft_id")
        if existing_draft_id:
            existing = await self._mongo_db["publicador_drafts"].find_one(
                {
                    "_id": existing_draft_id,
                    "seller_id": item["seller_id"],
                    "account_id": item["account_id"],
                }
            )
            if existing is not None:
                return cast(dict[str, Any], existing)
        now = self._clock()
        draft: dict[str, Any] = {
            "_id": self._id_factory("draft"),
            "seller_id": item["seller_id"],
            "account_id": item["account_id"],
            "sku": item["sku"],
            "gtin": item["gtin"],
            "title": item["sku"],
            "family_name": None,
            "description": None,
            "category_id": "MLM-BATCH",
            "domain_id": None,
            "attributes": {},
            "price": item["price"],
            "logistics_type": item["logistics_type"],
            "listing_type": item["listing_type"],
            "free_shipping": item["free_shipping"],
            "official_store_id": None,
            "brand": None,
            "catalog_product_id": None,
            "is_catalog": False,
            "warranty": None,
            "asset_ids": [],
            "source_product": {
                "name": item["sku"],
                "sku": item["sku"],
                "gtin": item["gtin"],
                "price": item["price"],
                "logistics_type": item["logistics_type"],
                "listing_type": item["listing_type"],
                "free_shipping": item["free_shipping"],
                "batch_id": item["batch_id"],
            },
            "generated_listing": {},
            "status": "generated",
            "enrichment_status": "generated",
            "approval_status": "approved",
            "process_status": "not_started",
            "meli_item_id": None,
            "permalink": None,
            "errors": [],
            "created_at": now,
            "updated_at": now,
            "created_by": actor_id,
            "updated_by": actor_id,
            "schema_version": SCHEMA_VERSION,
        }
        await self._mongo_db["publicador_drafts"].insert_one(draft)
        await self._create_assets_for_item(item=item, draft=draft, actor_id=actor_id)
        await self._append_event(
            seller_id=item["seller_id"],
            account_id=item["account_id"],
            aggregate_type="batch_item",
            aggregate_id=item["_id"],
            operation="batch_item.processed",
            status="processed",
            actor_id=actor_id,
        )
        return draft

    async def _create_assets_for_item(
        self, *, item: dict[str, Any], draft: dict[str, Any], actor_id: str
    ) -> None:
        asset_ids: list[str] = []
        for image in item.get("images", []):
            asset = {
                "_id": self._id_factory("asset"),
                "seller_id": item["seller_id"],
                "account_id": item["account_id"],
                "owner_type": "draft",
                "owner_id": draft["_id"],
                "sku": item["sku"],
                "storage_uri": (
                    f"publicador://batches/{item['batch_id']}/{item['sku']}/{image['filename']}"
                ),
                "content_type": image["content_type"],
                "width": image["width"],
                "height": image["height"],
                "hash": image["hash"],
                "status": "registered",
                "meli_picture_id": None,
                "errors": [],
                "created_at": self._clock(),
                "updated_at": self._clock(),
                "created_by": actor_id,
                "schema_version": SCHEMA_VERSION,
            }
            await self._mongo_db["publicador_assets"].insert_one(asset)
            asset_ids.append(asset["_id"])
        draft["asset_ids"] = asset_ids
        await self._mongo_db["publicador_drafts"].replace_one(
            {
                "_id": draft["_id"],
                "seller_id": draft["seller_id"],
                "account_id": draft["account_id"],
            },
            draft,
            upsert=False,
        )

    async def _load_batch(
        self, *, seller_id: str, account_id: str, batch_id: str
    ) -> dict[str, Any]:
        batch = await self._mongo_db["publicador_batches"].find_one(
            {"_id": batch_id, "seller_id": seller_id, "account_id": account_id}
        )
        if batch is None:
            raise PublicadorBatchError("publicador_batch_not_found")
        return cast(dict[str, Any], batch)

    async def _items_for_batch(
        self, *, seller_id: str, account_id: str, batch_id: str
    ) -> list[dict[str, Any]]:
        return cast(
            list[dict[str, Any]],
            await self._mongo_db["publicador_batch_items"]
            .find({"batch_id": batch_id, "seller_id": seller_id, "account_id": account_id})
            .to_list(length=1000),
        )

    async def _refresh_counts(self, *, batch_id: str, seller_id: str, account_id: str) -> None:
        batch = await self._load_batch(
            seller_id=seller_id, account_id=account_id, batch_id=batch_id
        )
        items = await self._items_for_batch(
            seller_id=seller_id, account_id=account_id, batch_id=batch_id
        )
        counts = _empty_counts()
        counts["total"] = len(items)
        for item in items:
            status = str(item["status"])
            if status in counts:
                counts[status] += 1
            elif status in {"publish_failed", "retryable"}:
                counts["failed"] += 1
        await self._replace_batch({**batch, "counts": counts, "updated_at": self._clock()})

    async def _replace_batch(self, batch: dict[str, Any]) -> None:
        await self._mongo_db["publicador_batches"].replace_one(
            {
                "_id": batch["_id"],
                "seller_id": batch["seller_id"],
                "account_id": batch["account_id"],
            },
            batch,
            upsert=False,
        )

    async def _replace_item(self, item: dict[str, Any]) -> None:
        await self._mongo_db["publicador_batch_items"].replace_one(
            {"_id": item["_id"], "seller_id": item["seller_id"], "account_id": item["account_id"]},
            item,
            upsert=False,
        )

    def _failed_item(self, item: dict[str, Any], *, actor_id: str, error: str) -> dict[str, Any]:
        return {
            **item,
            "status": "publish_failed",
            "publish_status": "failed",
            "retry_count": int(item.get("retry_count", 0)) + 1,
            "errors": [*item.get("errors", []), error],
            "updated_at": self._clock(),
            "updated_by": actor_id,
        }

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
                "created_at": self._clock(),
                "schema_version": SCHEMA_VERSION,
            }
        )


def _empty_counts() -> dict[str, int]:
    return {"total": 0, "queued": 0, "blocked": 0, "processed": 0, "published": 0, "failed": 0}
