from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Literal, Protocol
from uuid import uuid4

from zeler_publicador.schemas import SCHEMA_VERSION

ImageFlow = Literal["individual", "batch", "suggestion"]
OwnerType = Literal["draft", "batch_item", "suggestion"]

ALLOWED_IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
MIN_IMAGE_DIMENSION = 500
MIN_IMAGES_BY_FLOW: dict[ImageFlow, int] = {"individual": 3, "batch": 3, "suggestion": 3}
MAX_IMAGES_BY_FLOW: dict[ImageFlow, int] = {"individual": 10, "batch": 10, "suggestion": 10}


@dataclass(frozen=True)
class ImageUpload:
    filename: str
    content_type: str
    width: int
    height: int
    data: bytes


@dataclass(frozen=True)
class ImageValidationResult:
    valid: bool
    errors: list[str]


class AssetStore(Protocol):
    async def store(
        self, *, seller_id: str, account_id: str, owner_id: str, image: ImageUpload
    ) -> str: ...


class MeliPictureGateway(Protocol):
    async def upload_picture(self, storage_uri: str) -> str: ...


class DeterministicAssetStore:
    async def store(
        self, *, seller_id: str, account_id: str, owner_id: str, image: ImageUpload
    ) -> str:
        return f"publicador://assets/{seller_id}/{account_id}/{owner_id}/{image.filename}"


class MissingPictureGateway:
    async def upload_picture(self, _storage_uri: str) -> str:
        raise RuntimeError("meli_picture_gateway_not_configured")


def validate_image_batch(images: list[ImageUpload], *, flow: ImageFlow) -> ImageValidationResult:
    errors: list[str] = []
    if len(images) < MIN_IMAGES_BY_FLOW[flow]:
        errors.append(f"{flow} requires at least {MIN_IMAGES_BY_FLOW[flow]} images")
    if len(images) > MAX_IMAGES_BY_FLOW[flow]:
        errors.append(f"{flow} accepts at most {MAX_IMAGES_BY_FLOW[flow]} images")

    allowed_types = sorted(ALLOWED_IMAGE_CONTENT_TYPES)
    allowed = f"{', '.join(allowed_types[:-1])}, or {allowed_types[-1]}"
    for image in images:
        if image.content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
            errors.append(f"{image.filename} content_type must be {allowed}")
        if image.width < MIN_IMAGE_DIMENSION or image.height < MIN_IMAGE_DIMENSION:
            errors.append(f"{image.filename} resolution must be at least 500x500")

    return ImageValidationResult(valid=not errors, errors=errors)


class AssetService:
    def __init__(
        self,
        mongo_db: Any,
        *,
        storage: AssetStore | None = None,
        picture_gateway: MeliPictureGateway | None = None,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[str], str] | None = None,
    ) -> None:
        self._mongo_db = mongo_db
        self._storage = storage or DeterministicAssetStore()
        self._picture_gateway = picture_gateway or MissingPictureGateway()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_factory = id_factory or (lambda prefix: f"{prefix}-{uuid4().hex}")

    async def register_assets(
        self,
        *,
        seller_id: str,
        account_id: str,
        owner_type: OwnerType,
        owner_id: str,
        sku: str,
        images: list[ImageUpload],
        actor_id: str,
        flow: ImageFlow = "individual",
    ) -> list[dict[str, Any]]:
        validation = validate_image_batch(images, flow=flow)
        if not validation.valid:
            raise ValueError("; ".join(validation.errors))

        assets: list[dict[str, Any]] = []
        for image in images:
            image_hash = sha256(image.data).hexdigest()
            existing = await self._mongo_db["publicador_assets"].find_one(
                {"seller_id": seller_id, "hash": image_hash}
            )
            if existing is not None:
                assets.append(existing)
                continue

            now = self._clock()
            storage_uri = await self._storage.store(
                seller_id=seller_id, account_id=account_id, owner_id=owner_id, image=image
            )
            document = {
                "_id": self._id_factory("asset"),
                "seller_id": seller_id,
                "account_id": account_id,
                "owner_type": owner_type,
                "owner_id": owner_id,
                "sku": sku,
                "storage_uri": storage_uri,
                "content_type": image.content_type,
                "width": image.width,
                "height": image.height,
                "hash": image_hash,
                "status": "registered",
                "meli_picture_id": None,
                "errors": [],
                "created_at": now,
                "updated_at": now,
                "created_by": actor_id,
                "schema_version": SCHEMA_VERSION,
            }
            await self._mongo_db["publicador_assets"].insert_one(document)
            assets.append(document)

        await self._link_assets_to_owner(
            seller_id=seller_id,
            account_id=account_id,
            owner_type=owner_type,
            owner_id=owner_id,
            asset_ids=[asset["_id"] for asset in assets],
        )
        await self._append_event(
            seller_id=seller_id,
            account_id=account_id,
            aggregate_type=owner_type,
            aggregate_id=owner_id,
            operation="asset.registered",
            status="registered",
            actor_id=actor_id,
            details={"asset_ids": [asset["_id"] for asset in assets]},
        )
        return assets

    async def upload_to_meli(
        self, *, asset_id: str, seller_id: str, account_id: str, actor_id: str
    ) -> dict[str, Any]:
        asset = await self._mongo_db["publicador_assets"].find_one(
            {"_id": asset_id, "seller_id": seller_id, "account_id": account_id}
        )
        if asset is None:
            raise ValueError("publicador_asset_not_found")
        if asset.get("meli_picture_id"):
            await self._append_asset_event(
                asset,
                operation="asset.meli_upload_skipped",
                status="uploaded",
                actor_id=actor_id,
            )
            return asset

        try:
            picture_id = await self._picture_gateway.upload_picture(str(asset["storage_uri"]))
        except RuntimeError:
            updated = {
                **asset,
                "status": "upload_failed",
                "errors": ["meli_picture_upload_failed"],
                "updated_at": self._clock(),
            }
            await self._replace_asset(updated)
            await self._append_asset_event(
                updated,
                operation="asset.meli_upload_failed",
                status="failed",
                actor_id=actor_id,
            )
            return updated

        updated = {
            **asset,
            "status": "uploaded",
            "meli_picture_id": picture_id,
            "errors": [],
            "updated_at": self._clock(),
        }
        await self._replace_asset(updated)
        await self._append_asset_event(
            updated,
            operation="asset.meli_uploaded",
            status="uploaded",
            actor_id=actor_id,
        )
        return updated

    async def _link_assets_to_owner(
        self,
        *,
        seller_id: str,
        account_id: str,
        owner_type: OwnerType,
        owner_id: str,
        asset_ids: list[str],
    ) -> None:
        if owner_type != "draft":
            return
        draft = await self._mongo_db["publicador_drafts"].find_one(
            {"_id": owner_id, "seller_id": seller_id, "account_id": account_id}
        )
        if draft is None:
            return
        merged_ids = list(dict.fromkeys([*draft.get("asset_ids", []), *asset_ids]))
        updated = {**draft, "asset_ids": merged_ids, "updated_at": self._clock()}
        await self._mongo_db["publicador_drafts"].replace_one(
            {"_id": owner_id, "seller_id": seller_id, "account_id": account_id},
            updated,
            upsert=False,
        )

    async def _replace_asset(self, asset: dict[str, Any]) -> None:
        await self._mongo_db["publicador_assets"].replace_one(
            {
                "_id": asset["_id"],
                "seller_id": asset["seller_id"],
                "account_id": asset["account_id"],
            },
            asset,
            upsert=False,
        )

    async def _append_asset_event(
        self, asset: dict[str, Any], *, operation: str, status: str, actor_id: str
    ) -> None:
        await self._append_event(
            seller_id=asset["seller_id"],
            account_id=asset["account_id"],
            aggregate_type="asset",
            aggregate_id=asset["_id"],
            operation=operation,
            status=status,
            actor_id=actor_id,
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
