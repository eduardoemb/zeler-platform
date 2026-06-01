from __future__ import annotations

from base64 import b64decode
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol, cast

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from zeler_platform_core.auth.jwt import verify_module_jwt
from zeler_platform_core.auth.module_admin import authorize_module_admin
from zeler_publicador.ai import AIGenerationService, ProviderConfig
from zeler_publicador.assets import AssetService, ImageUpload
from zeler_publicador.batches import PublicadorBatchError, PublicadorBatchService
from zeler_publicador.catalog import CatalogSuggestionService
from zeler_publicador.generator import ProductInfo
from zeler_publicador.meli import MeliPublicationService
from zeler_publicador.reporting import PublicadorReportingService
from zeler_publicador.repos import PublicadorRepository
from zeler_publicador.schemas import (
    AiGenerateRequest,
    AssetCreate,
    AssetRegisterRequest,
    BatchActionRequest,
    BatchCreate,
    BatchUploadRequest,
    CatalogLinkPublishRequest,
    CatalogSuggestionNotification,
    ContractAccepted,
    DraftCreate,
    DraftUpdate,
    PublicadorSettings,
    PublicationAction,
    SuggestionCreate,
)


class DraftPayload(BaseModel):
    seller_id: str | None = None
    account_id: str | None = None
    source_product: dict[str, Any] | None = None
    title: str | None = None
    category_id: str | None = None
    attributes: dict[str, Any] = {}

    def to_source_product(self) -> dict[str, Any]:
        if self.source_product is not None:
            return self.source_product
        return {
            "name": self.title or "Untitled listing",
            "category_id": self.category_id or "unknown",
            **self.attributes,
        }


class Generator(Protocol):
    async def generate(self, product: ProductInfo) -> Any: ...


class Publisher(Protocol):
    async def publish(self, draft_id: str) -> Any: ...


def build_router(
    *,
    generator: Generator,
    publisher: Publisher,
    clock: Callable[[], datetime] | None = None,
) -> APIRouter:
    now = clock or (lambda: datetime.now(UTC))
    router = APIRouter(prefix="/publicador", tags=["publicador"])

    @router.get("/drafts")
    async def list_drafts(
        request: Request, seller_id: str, account_id: str | None = None
    ) -> JSONResponse:
        auth = _authorize(request, seller_id=seller_id)
        if auth is not None:
            return auth
        drafts = await _repo(request).list_drafts(seller_id=seller_id, account_id=account_id)
        history = await _seller_history(request, seller_id=seller_id)
        return JSONResponse(jsonable_encoder([_with_history(draft, history) for draft in drafts]))

    @router.get("/dashboard", response_model=dict[str, Any])
    async def dashboard(
        request: Request, seller_id: str, account_id: str
    ) -> dict[str, Any] | JSONResponse:
        auth = _authorize(request, seller_id=seller_id)
        if auth is not None:
            return auth
        return await _reporting_service(request, clock=now).dashboard(
            seller_id=seller_id, account_id=account_id
        )

    @router.post("/drafts", status_code=201)
    async def create_draft(request: Request, payload: DraftCreate | DraftPayload) -> JSONResponse:
        auth = _authorize(request, seller_id=payload.seller_id)
        if auth is not None:
            return auth
        created_at = now()
        seller_id = payload.seller_id or str(_seller_id_from_request(request))
        if isinstance(payload, DraftCreate):
            created = await _repo(request).create_draft(payload)
            return JSONResponse(
                status_code=201,
                content=jsonable_encoder(
                    {**created.model_dump(by_alias=True), "draft_id": created.id}
                ),
            )
        draft = {
            "_id": f"publicador-draft-{seller_id}-{int(created_at.timestamp())}",
            "seller_id": seller_id,
            "account_id": payload.account_id or seller_id,
            "source_product": payload.to_source_product(),
            "generated_listing": {},
            "status": "draft",
            "enrichment_status": "pending",
            "approval_status": "draft",
            "process_status": "not_started",
            "created_at": created_at,
            "updated_at": created_at,
            "created_by": "module-admin",
            "updated_by": "module-admin",
            "schema_version": 1,
        }
        await request.app.state.mongo_db["publicador_drafts"].insert_one(draft)
        return JSONResponse(
            status_code=201, content=jsonable_encoder({**draft, "draft_id": draft["_id"]})
        )

    @router.post("/drafts/{draft_id}/generate")
    async def generate_draft(request: Request, draft_id: str) -> JSONResponse:
        auth = _authorize(request)
        if auth is not None:
            return auth
        draft = await request.app.state.mongo_db["publicador_drafts"].find_one({"_id": draft_id})
        if draft is None:
            return JSONResponse(status_code=404, content={"error": "publicador_draft_not_found"})

        source = draft["source_product"]
        listing = await generator.generate(
            ProductInfo(
                name=str(source["name"]),
                category_id=str(source["category_id"]),
                brand=source.get("brand"),
                features=list(source.get("features", [])),
            )
        )
        updated = {
            **draft,
            "generated_listing": listing.model_dump(),
            "status": "generated",
            "updated_at": now(),
        }
        await request.app.state.mongo_db["publicador_drafts"].replace_one(
            {"_id": draft_id}, updated, upsert=True
        )
        return JSONResponse(jsonable_encoder(updated))

    @router.post("/drafts/{draft_id}/publish")
    async def publish_draft(request: Request, draft_id: str) -> JSONResponse:
        auth = _authorize(request)
        if auth is not None:
            return auth
        result = await publisher.publish(draft_id)
        return JSONResponse(
            status_code=200,
            content=jsonable_encoder(
                {"item_id": result.item_id, "outcome": result.outcome, "payload": result.payload}
            ),
        )

    @router.get("/drafts/{draft_id}")
    async def draft_detail(
        request: Request, draft_id: str, seller_id: str, account_id: str
    ) -> JSONResponse:
        auth = _authorize(request, seller_id=seller_id)
        if auth is not None:
            return auth
        draft = await _repo(request).get_draft(
            draft_id=draft_id, seller_id=seller_id, account_id=account_id
        )
        if draft is None:
            return JSONResponse(status_code=404, content={"error": "publicador_draft_not_found"})
        return JSONResponse(jsonable_encoder(await _draft_with_events(request, draft)))

    @router.patch("/drafts/{draft_id}")
    async def patch_draft(
        request: Request,
        draft_id: str,
        seller_id: str,
        account_id: str,
        payload: DraftUpdate,
    ) -> JSONResponse:
        auth = _authorize(request, seller_id=seller_id)
        if auth is not None:
            return auth
        updated = await _repo(request).update_draft(
            draft_id=draft_id,
            seller_id=seller_id,
            account_id=account_id,
            update=payload,
            actor_id=payload.updated_by,
        )
        if updated is None:
            return JSONResponse(status_code=404, content={"error": "publicador_draft_not_found"})
        return JSONResponse(jsonable_encoder(await _draft_with_events(request, updated)))

    @router.get("/publications", response_model=list[dict[str, Any]])
    async def list_publications(
        request: Request, seller_id: str, account_id: str
    ) -> list[dict[str, Any]] | JSONResponse:
        auth = _authorize(request, seller_id=seller_id)
        if auth is not None:
            return auth
        drafts = await _repo(request).list_drafts(seller_id=seller_id, account_id=account_id)
        return [await _draft_with_events(request, draft) for draft in drafts]

    @router.get("/publications/{publication_id}", response_model=dict[str, Any])
    async def publication_detail(
        request: Request, publication_id: str, seller_id: str, account_id: str
    ) -> dict[str, Any] | JSONResponse:
        auth = _authorize(request, seller_id=seller_id)
        if auth is not None:
            return auth
        draft = await _repo(request).get_draft(
            draft_id=publication_id, seller_id=seller_id, account_id=account_id
        )
        if draft is None:
            return JSONResponse(
                status_code=404, content={"error": "publicador_publication_not_found"}
            )
        return await _draft_with_events(request, draft)

    @router.post("/publications/{publication_id}/approve", response_model=dict[str, Any])
    async def approve_publication(
        request: Request,
        publication_id: str,
        seller_id: str,
        account_id: str,
        payload: PublicationAction | None = None,
    ) -> dict[str, Any] | JSONResponse:
        return await _publication_transition(
            request,
            publication_id=publication_id,
            seller_id=seller_id,
            account_id=account_id,
            action="approve",
            payload=payload,
        )

    @router.post("/publications/{publication_id}/reject", response_model=dict[str, Any])
    async def reject_publication(
        request: Request,
        publication_id: str,
        seller_id: str,
        account_id: str,
        payload: PublicationAction | None = None,
    ) -> dict[str, Any] | JSONResponse:
        return await _publication_transition(
            request,
            publication_id=publication_id,
            seller_id=seller_id,
            account_id=account_id,
            action="reject",
            payload=payload,
        )

    @router.post("/publications/{publication_id}/process", response_model=dict[str, Any])
    async def process_publication(
        request: Request,
        publication_id: str,
        seller_id: str,
        account_id: str,
        payload: PublicationAction | None = None,
    ) -> dict[str, Any] | JSONResponse:
        return await _publication_transition(
            request,
            publication_id=publication_id,
            seller_id=seller_id,
            account_id=account_id,
            action="process",
            payload=payload,
        )

    @router.post("/publications/{publication_id}/validate", response_model=dict[str, Any])
    async def validate_publication(
        request: Request,
        publication_id: str,
        seller_id: str,
        account_id: str,
        payload: PublicationAction | None = None,
    ) -> dict[str, Any] | JSONResponse:
        auth = _authorize(request, seller_id=seller_id)
        if auth is not None:
            return auth
        actor_id = payload.actor_id if payload is not None else "module-admin"
        try:
            result = await _meli_service(request, clock=now).validate_draft(
                seller_id=seller_id,
                account_id=account_id,
                draft_id=publication_id,
                actor_id=actor_id,
            )
        except ValueError as exc:
            status_code = 404 if str(exc) == "publicador_draft_not_found" else 422
            return JSONResponse(status_code=status_code, content={"error": str(exc)})
        if result["status"] == "blocked":
            return JSONResponse(status_code=422, content=jsonable_encoder(result))
        return result

    @router.get("/taxonomy/categories/predict", response_model=list[dict[str, Any]])
    async def predict_categories(
        request: Request, seller_id: str, account_id: str, q: str
    ) -> list[dict[str, Any]] | JSONResponse:
        auth = _authorize(request, seller_id=seller_id)
        if auth is not None:
            return auth
        return await _meli_service(request, clock=now).predict_categories(
            seller_id=seller_id, account_id=account_id, query=q
        )

    @router.get(
        "/taxonomy/categories/{category_id}/attributes",
        response_model=list[dict[str, Any]],
    )
    async def category_attributes(
        request: Request, category_id: str, seller_id: str, account_id: str
    ) -> list[dict[str, Any]] | JSONResponse:
        auth = _authorize(request, seller_id=seller_id)
        if auth is not None:
            return auth
        return await _meli_service(request, clock=now).required_attributes(
            seller_id=seller_id, account_id=account_id, category_id=category_id
        )

    @router.get("/preferences", response_model=dict[str, Any])
    async def publication_preferences(
        request: Request, seller_id: str, account_id: str
    ) -> dict[str, Any] | JSONResponse:
        auth = _authorize(request, seller_id=seller_id)
        if auth is not None:
            return auth
        return await _meli_service(request, clock=now).publication_preferences(
            seller_id=seller_id, account_id=account_id
        )

    @router.get("/catalog/search", response_model=list[dict[str, Any]])
    async def search_catalog(
        request: Request,
        seller_id: str,
        account_id: str,
        q: str | None = None,
        gtin: str | None = None,
        permalink: str | None = None,
    ) -> list[dict[str, Any]] | JSONResponse:
        auth = _authorize(request, seller_id=seller_id)
        if auth is not None:
            return auth
        return await _catalog_service(request, clock=now).search_catalog(
            seller_id=seller_id,
            account_id=account_id,
            query=q,
            gtin=gtin,
            permalink=permalink,
        )

    @router.post("/publications/{publication_id}/catalog-link", response_model=dict[str, Any])
    async def catalog_link_publish(
        request: Request, publication_id: str, payload: CatalogLinkPublishRequest
    ) -> dict[str, Any] | JSONResponse:
        auth = _authorize(request, seller_id=payload.seller_id)
        if auth is not None:
            return auth
        try:
            return await _catalog_service(request, clock=now).publish_catalog_link(
                seller_id=payload.seller_id,
                account_id=payload.account_id,
                draft_id=publication_id,
                catalog_product_id=payload.catalog_product_id,
                actor_id=payload.actor_id,
            )
        except ValueError as exc:
            status_code = 404 if str(exc) == "publicador_draft_not_found" else 422
            return JSONResponse(status_code=status_code, content={"error": str(exc)})

    @router.post("/publications/{publication_id}/retry", response_model=ContractAccepted)
    async def retry_publication(
        request: Request, publication_id: str, seller_id: str, account_id: str
    ) -> ContractAccepted | JSONResponse:
        return _contract_stub(request, seller_id=seller_id, account_id=account_id)

    @router.post("/assets", status_code=201)
    async def create_asset(
        request: Request, payload: AssetRegisterRequest | AssetCreate
    ) -> JSONResponse:
        auth = _authorize(request, seller_id=payload.seller_id)
        if auth is not None:
            return auth
        if isinstance(payload, AssetCreate):
            return JSONResponse(
                status_code=202,
                content=jsonable_encoder(
                    ContractAccepted(seller_id=payload.seller_id, account_id=payload.account_id)
                ),
            )
        images = [
            ImageUpload(
                filename=image.filename,
                content_type=image.content_type,
                width=image.width,
                height=image.height,
                data=b64decode(image.data_base64),
            )
            for image in payload.images
        ]
        try:
            assets = await _asset_service(request, clock=now).register_assets(
                seller_id=payload.seller_id,
                account_id=payload.account_id,
                owner_type=payload.owner_type,
                owner_id=payload.owner_id,
                sku=payload.sku,
                images=images,
                actor_id=payload.created_by,
            )
        except ValueError as exc:
            return JSONResponse(status_code=422, content={"error": str(exc)})
        return JSONResponse(status_code=201, content=jsonable_encoder({"assets": assets}))

    @router.post("/ai/generate", status_code=202)
    async def generate_ai(request: Request, payload: AiGenerateRequest) -> JSONResponse:
        auth = _authorize(request, seller_id=payload.seller_id)
        if auth is not None:
            return auth
        try:
            generated = await _ai_service(request, clock=now).generate_for_draft(
                seller_id=payload.seller_id,
                account_id=payload.account_id,
                draft_id=payload.draft_id,
                operation=payload.operation,
                prompt_inputs=payload.prompt_inputs,
                actor_id=payload.actor_id,
            )
        except ValueError as exc:
            status_code = 404 if str(exc) == "publicador_draft_not_found" else 422
            return JSONResponse(status_code=status_code, content={"error": str(exc)})
        return JSONResponse(status_code=202, content=jsonable_encoder(generated))

    @router.get("/batches", response_model=list[dict[str, Any]])
    async def list_batches(
        request: Request, seller_id: str, account_id: str
    ) -> list[dict[str, Any]] | JSONResponse:
        auth = _authorize(request, seller_id=seller_id)
        if auth is not None:
            return auth
        return await _batch_service(request, clock=now).list_batches(
            seller_id=seller_id, account_id=account_id
        )

    @router.post("/batches", response_model=dict[str, Any], status_code=201)
    async def create_batch(
        request: Request, payload: BatchUploadRequest | BatchCreate
    ) -> dict[str, Any] | JSONResponse:
        auth = _authorize(request, seller_id=payload.seller_id)
        if auth is not None:
            return auth
        if isinstance(payload, BatchCreate):
            return JSONResponse(
                status_code=202,
                content=jsonable_encoder(
                    ContractAccepted(seller_id=payload.seller_id, account_id=payload.account_id)
                ),
            )
        try:
            return await _batch_service(request, clock=now).create_from_zip(
                seller_id=payload.seller_id,
                account_id=payload.account_id,
                source_filename=payload.source_filename,
                content=b64decode(payload.content_base64),
                actor_id=payload.created_by,
            )
        except (ValueError, PublicadorBatchError) as exc:
            return JSONResponse(status_code=422, content={"error": str(exc)})

    @router.get("/batches/{batch_id}", response_model=dict[str, Any])
    async def batch_detail(
        request: Request, batch_id: str, seller_id: str, account_id: str
    ) -> dict[str, Any] | JSONResponse:
        auth = _authorize(request, seller_id=seller_id)
        if auth is not None:
            return auth
        batch = await _batch_service(request, clock=now).batch_detail(
            seller_id=seller_id, account_id=account_id, batch_id=batch_id
        )
        if batch is None:
            return JSONResponse(status_code=404, content={"error": "publicador_batch_not_found"})
        return batch

    @router.post("/batches/{batch_id}/process", response_model=dict[str, Any])
    async def process_batch(
        request: Request,
        batch_id: str,
        seller_id: str,
        account_id: str,
        payload: BatchActionRequest | None = None,
    ) -> dict[str, Any] | JSONResponse:
        auth = _authorize(request, seller_id=seller_id)
        if auth is not None:
            return auth
        try:
            return await _batch_service(request, clock=now).process_batch(
                seller_id=seller_id,
                account_id=account_id,
                batch_id=batch_id,
                actor_id=payload.actor_id if payload is not None else "module-admin",
            )
        except PublicadorBatchError as exc:
            return JSONResponse(status_code=404, content={"error": str(exc)})

    @router.post("/batches/{batch_id}/publish", response_model=dict[str, Any])
    async def publish_batch(
        request: Request,
        batch_id: str,
        seller_id: str,
        account_id: str,
        payload: BatchActionRequest | None = None,
    ) -> dict[str, Any] | JSONResponse:
        auth = _authorize(request, seller_id=seller_id)
        if auth is not None:
            return auth
        try:
            return await _batch_service(request, clock=now).publish_batch(
                seller_id=seller_id,
                account_id=account_id,
                batch_id=batch_id,
                actor_id=payload.actor_id if payload is not None else "module-admin",
            )
        except PublicadorBatchError as exc:
            return JSONResponse(status_code=404, content={"error": str(exc)})

    @router.get("/suggestions", response_model=list[dict[str, Any]])
    async def list_suggestions(
        request: Request,
        seller_id: str,
        account_id: str,
        status: str | None = None,
        draft_id: str | None = None,
    ) -> list[dict[str, Any]] | JSONResponse:
        auth = _authorize(request, seller_id=seller_id)
        if auth is not None:
            return auth
        return await _catalog_service(request, clock=now).list_suggestions(
            seller_id=seller_id, account_id=account_id, status=status, draft_id=draft_id
        )

    @router.post("/suggestions", response_model=dict[str, Any], status_code=201)
    async def create_suggestion(
        request: Request, payload: SuggestionCreate
    ) -> dict[str, Any] | JSONResponse:
        auth = _authorize(request, seller_id=payload.seller_id)
        if auth is not None:
            return auth
        if not payload.draft_id:
            return JSONResponse(status_code=422, content={"error": "draft_id_required"})
        try:
            return await _catalog_service(request, clock=now).create_for_draft(
                seller_id=payload.seller_id,
                account_id=payload.account_id,
                draft_id=payload.draft_id,
                actor_id=payload.actor_id,
            )
        except ValueError as exc:
            status_code = 404 if str(exc) == "publicador_draft_not_found" else 422
            return JSONResponse(status_code=status_code, content={"error": str(exc)})

    @router.get("/suggestions/{suggestion_id}", response_model=dict[str, Any])
    async def suggestion_detail(
        request: Request, suggestion_id: str, seller_id: str, account_id: str
    ) -> dict[str, Any] | JSONResponse:
        auth = _authorize(request, seller_id=seller_id)
        if auth is not None:
            return auth
        suggestion = await _catalog_service(request, clock=now).get_suggestion(
            seller_id=seller_id, account_id=account_id, suggestion_id=suggestion_id
        )
        if suggestion is None:
            return JSONResponse(
                status_code=404, content={"error": "publicador_catalog_suggestion_not_found"}
            )
        return suggestion

    @router.post("/suggestions/{suggestion_id}/validate", response_model=dict[str, Any])
    async def validate_suggestion(
        request: Request,
        suggestion_id: str,
        seller_id: str,
        account_id: str,
        payload: PublicationAction | None = None,
    ) -> dict[str, Any] | JSONResponse:
        return await _suggestion_action(
            request,
            suggestion_id=suggestion_id,
            seller_id=seller_id,
            account_id=account_id,
            action="validate",
            payload=payload,
            clock=now,
        )

    @router.post("/suggestions/{suggestion_id}/send", response_model=dict[str, Any])
    async def send_suggestion(
        request: Request,
        suggestion_id: str,
        seller_id: str,
        account_id: str,
        payload: PublicationAction | None = None,
    ) -> dict[str, Any] | JSONResponse:
        return await _suggestion_action(
            request,
            suggestion_id=suggestion_id,
            seller_id=seller_id,
            account_id=account_id,
            action="send",
            payload=payload,
            clock=now,
        )

    @router.post("/suggestions/{suggestion_id}/refresh", response_model=dict[str, Any])
    async def refresh_suggestion(
        request: Request,
        suggestion_id: str,
        seller_id: str,
        account_id: str,
        payload: PublicationAction | None = None,
    ) -> dict[str, Any] | JSONResponse:
        return await _suggestion_action(
            request,
            suggestion_id=suggestion_id,
            seller_id=seller_id,
            account_id=account_id,
            action="refresh",
            payload=payload,
            clock=now,
        )

    @router.post("/suggestions/notifications", response_model=dict[str, Any])
    async def suggestion_notification(
        request: Request, payload: CatalogSuggestionNotification
    ) -> dict[str, Any] | JSONResponse:
        auth = _authorize(request, seller_id=payload.seller_id)
        if auth is not None:
            return auth
        try:
            return await _catalog_service(request, clock=now).process_notification(
                seller_id=payload.seller_id,
                account_id=payload.account_id,
                payload=payload.model_dump(),
            )
        except ValueError as exc:
            return JSONResponse(status_code=404, content={"error": str(exc)})

    @router.get("/logs", response_model=dict[str, Any])
    async def list_logs(
        request: Request,
        seller_id: str,
        account_id: str,
        status: str | None = None,
        sku: str | None = None,
        error: str | None = None,
        aggregate_type: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any] | JSONResponse:
        auth = _authorize(request, seller_id=seller_id)
        if auth is not None:
            return auth
        return await _reporting_service(request, clock=now).list_logs(
            seller_id=seller_id,
            account_id=account_id,
            status=status,
            sku=sku,
            error=error,
            aggregate_type=aggregate_type,
            date_from=_parse_date_filter(date_from, end_of_day=False),
            date_to=_parse_date_filter(date_to, end_of_day=True),
            page=page,
            page_size=page_size,
        )

    @router.get("/statistics", response_model=dict[str, Any])
    async def statistics(
        request: Request,
        seller_id: str,
        account_id: str,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any] | JSONResponse:
        auth = _authorize(request, seller_id=seller_id)
        if auth is not None:
            return auth
        return await _reporting_service(request, clock=now).statistics(
            seller_id=seller_id,
            account_id=account_id,
            date_from=_parse_date_filter(date_from, end_of_day=False),
            date_to=_parse_date_filter(date_to, end_of_day=True),
        )

    @router.get("/settings", response_model=PublicadorSettings)
    async def get_settings(
        request: Request, seller_id: str, account_id: str
    ) -> PublicadorSettings | JSONResponse:
        auth = _authorize(request, seller_id=seller_id)
        if auth is not None:
            return auth
        return PublicadorSettings.model_validate(
            await _reporting_service(request, clock=now).get_settings(
                seller_id=seller_id, account_id=account_id
            )
        )

    @router.put("/settings", response_model=PublicadorSettings)
    async def put_settings(
        request: Request, payload: PublicadorSettings
    ) -> PublicadorSettings | JSONResponse:
        auth = _authorize(request, seller_id=payload.seller_id)
        if auth is not None:
            return auth
        return PublicadorSettings.model_validate(
            await _reporting_service(request, clock=now).upsert_settings(payload)
        )

    return router


def _repo(request: Request) -> PublicadorRepository:
    return PublicadorRepository(request.app.state.mongo_db)


def _asset_service(request: Request, *, clock: Callable[[], datetime]) -> AssetService:
    storage = getattr(request.app.state, "publicador_asset_store", None)
    picture_gateway = getattr(request.app.state, "publicador_picture_gateway", None)
    return AssetService(
        request.app.state.mongo_db,
        storage=storage,
        picture_gateway=picture_gateway,
        clock=clock,
    )


def _ai_service(request: Request, *, clock: Callable[[], datetime]) -> AIGenerationService:
    providers = getattr(request.app.state, "publicador_ai_providers", {})
    default = getattr(
        request.app.state,
        "publicador_ai_default",
        ProviderConfig(provider="publicador-ai-provider-not-configured", model="disabled"),
    )
    return AIGenerationService(
        request.app.state.mongo_db,
        providers=providers,
        platform_default=default,
        clock=clock,
    )


def _meli_service(request: Request, *, clock: Callable[[], datetime]) -> MeliPublicationService:
    gateway = getattr(request.app.state, "publicador_meli_gateway", None)
    return MeliPublicationService(request.app.state.mongo_db, gateway=gateway, clock=clock)


def _catalog_service(
    request: Request, *, clock: Callable[[], datetime]
) -> CatalogSuggestionService:
    gateway = getattr(request.app.state, "publicador_meli_gateway", None)
    return CatalogSuggestionService(request.app.state.mongo_db, gateway=gateway, clock=clock)


def _batch_service(request: Request, *, clock: Callable[[], datetime]) -> PublicadorBatchService:
    gateway = getattr(request.app.state, "publicador_meli_gateway", None)
    return PublicadorBatchService(request.app.state.mongo_db, meli_gateway=gateway, clock=clock)


def _reporting_service(
    request: Request, *, clock: Callable[[], datetime]
) -> PublicadorReportingService:
    return PublicadorReportingService(request.app.state.mongo_db, clock=clock)


def _contract_stub(
    request: Request, *, seller_id: str, account_id: str
) -> ContractAccepted | JSONResponse:
    auth = _authorize(request, seller_id=seller_id)
    if auth is not None:
        return auth
    return ContractAccepted(seller_id=seller_id, account_id=account_id)


async def _publication_transition(
    request: Request,
    *,
    publication_id: str,
    seller_id: str,
    account_id: str,
    action: str,
    payload: PublicationAction | None,
) -> dict[str, Any] | JSONResponse:
    auth = _authorize(request, seller_id=seller_id)
    if auth is not None:
        return auth
    actor_id = payload.actor_id if payload is not None else "module-admin"
    reason = payload.reason if payload is not None else None
    if action == "process" and hasattr(request.app.state, "publicador_meli_gateway"):
        try:
            service = _meli_service(request, clock=lambda: datetime.now(UTC))
            result = await service.validate_and_publish_draft(
                seller_id=seller_id,
                account_id=account_id,
                draft_id=publication_id,
                actor_id=actor_id,
            )
        except ValueError as exc:
            status_code = 404 if str(exc) == "publicador_draft_not_found" else 422
            return JSONResponse(status_code=status_code, content={"error": str(exc)})
        if result["status"] == "blocked":
            return JSONResponse(status_code=422, content=jsonable_encoder(result))
        return result
    updated = await _repo(request).transition_draft(
        draft_id=publication_id,
        seller_id=seller_id,
        account_id=account_id,
        action=action,
        actor_id=actor_id,
        reason=reason,
    )
    if updated is None:
        return JSONResponse(status_code=404, content={"error": "publicador_publication_not_found"})
    return await _draft_with_events(request, updated)


async def _suggestion_action(
    request: Request,
    *,
    suggestion_id: str,
    seller_id: str,
    account_id: str,
    action: str,
    payload: PublicationAction | None,
    clock: Callable[[], datetime],
) -> dict[str, Any] | JSONResponse:
    auth = _authorize(request, seller_id=seller_id)
    if auth is not None:
        return auth
    actor_id = payload.actor_id if payload is not None else "module-admin"
    service = _catalog_service(request, clock=clock)
    try:
        if action == "validate":
            return await service.validate_suggestion(
                seller_id=seller_id,
                account_id=account_id,
                suggestion_id=suggestion_id,
                actor_id=actor_id,
            )
        if action == "send":
            return await service.send_suggestion(
                seller_id=seller_id,
                account_id=account_id,
                suggestion_id=suggestion_id,
                actor_id=actor_id,
            )
        if action == "refresh":
            return await service.refresh_status(
                seller_id=seller_id,
                account_id=account_id,
                suggestion_id=suggestion_id,
                actor_id=actor_id,
            )
        raise ValueError("publicador_catalog_suggestion_action_unsupported")
    except ValueError as exc:
        status_code = 404 if str(exc) == "publicador_catalog_suggestion_not_found" else 422
        return JSONResponse(status_code=status_code, content={"error": str(exc)})


async def _draft_with_events(request: Request, draft: dict[str, Any]) -> dict[str, Any]:
    history = await _history_for_draft(request, draft=draft)
    return {**draft, "history": history}


async def _seller_history(request: Request, *, seller_id: str) -> list[dict[str, Any]]:
    try:
        return cast(
            list[dict[str, Any]],
            await request.app.state.mongo_db["publicador_events"]
            .find({"seller_id": seller_id})
            .to_list(length=100),
        )
    except (AssertionError, KeyError):
        return cast(
            list[dict[str, Any]],
            await request.app.state.mongo_db["publicador_history"]
            .find({"seller_id": seller_id})
            .to_list(length=100),
        )


async def _history_for_draft(request: Request, *, draft: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        return await _repo(request).history_for_draft(
            draft_id=str(draft["_id"]),
            seller_id=str(draft["seller_id"]),
            account_id=str(draft["account_id"]),
        )
    except (AssertionError, KeyError):
        history = (
            await request.app.state.mongo_db["publicador_history"]
            .find({"seller_id": draft["seller_id"]})
            .to_list(length=100)
        )
        return [doc for doc in history if doc.get("draft_id") == draft.get("_id")]


def _authorize(request: Request, seller_id: str | int | None = None) -> JSONResponse | None:
    return authorize_module_admin(
        request,
        expected_module_id="publicador",
        seller_id=seller_id,
        verifier=verify_module_jwt,
    )


def _seller_id_from_request(request: Request) -> int:
    auth_header = request.headers.get("Authorization", "")
    claims = verify_module_jwt(auth_header.removeprefix("Bearer ").strip())
    return claims.seller_id


def _with_history(draft: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]:
    return {**draft, "history": [doc for doc in history if doc.get("draft_id") == draft.get("_id")]}


def _parse_date_filter(value: str | None, *, end_of_day: bool) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    if end_of_day and "T" not in value:
        return parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
    return parsed
