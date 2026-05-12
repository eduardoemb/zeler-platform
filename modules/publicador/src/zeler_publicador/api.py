from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from zeler_platform_core.auth.jwt import verify_module_jwt
from zeler_platform_core.auth.module_admin import authorize_module_admin
from zeler_publicador.generator import ProductInfo


class DraftPayload(BaseModel):
    seller_id: str | None = None
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
    async def list_drafts(request: Request, seller_id: str) -> JSONResponse:
        auth = _authorize(request, seller_id=seller_id)
        if auth is not None:
            return auth
        drafts = (
            await request.app.state.mongo_db["publicador_drafts"]
            .find({"seller_id": seller_id})
            .to_list(length=100)
        )
        history = (
            await request.app.state.mongo_db["publicador_history"]
            .find({"seller_id": seller_id})
            .to_list(length=100)
        )
        return JSONResponse(jsonable_encoder([_with_history(draft, history) for draft in drafts]))

    @router.post("/drafts", status_code=201)
    async def create_draft(request: Request, payload: DraftPayload) -> JSONResponse:
        auth = _authorize(request, seller_id=payload.seller_id)
        if auth is not None:
            return auth
        created_at = now()
        seller_id = payload.seller_id or str(_seller_id_from_request(request))
        draft = {
            "_id": f"publicador-draft-{seller_id}-{int(created_at.timestamp())}",
            "seller_id": seller_id,
            "source_product": payload.to_source_product(),
            "generated_listing": {},
            "status": "draft",
            "created_at": created_at,
            "updated_at": created_at,
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

    return router


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
