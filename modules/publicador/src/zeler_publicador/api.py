from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from zeler_platform_core.auth.jwt import (
    ExpiredJWTError,
    InvalidJWTError,
    WrongAudienceError,
    verify_module_jwt,
)
from zeler_publicador.generator import ProductInfo


class DraftPayload(BaseModel):
    seller_id: str
    source_product: dict[str, Any]


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
        auth = _authorize(request)
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
        auth = _authorize(request)
        if auth is not None:
            return auth
        created_at = now()
        draft = {
            "_id": f"publicador-draft-{payload.seller_id}-{int(created_at.timestamp())}",
            "seller_id": payload.seller_id,
            "source_product": payload.source_product,
            "generated_listing": {},
            "status": "draft",
            "created_at": created_at,
            "updated_at": created_at,
            "schema_version": 1,
        }
        await request.app.state.mongo_db["publicador_drafts"].insert_one(draft)
        return JSONResponse(status_code=201, content=jsonable_encoder(draft))

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
            jsonable_encoder(
                {"item_id": result.item_id, "outcome": result.outcome, "payload": result.payload}
            )
        )

    return router


def _authorize(request: Request) -> JSONResponse | None:
    auth_header = request.headers.get("Authorization")
    if auth_header is None or not auth_header.startswith("Bearer "):
        return JSONResponse(
            status_code=401,
            content={"error": "invalid_token", "detail": "missing bearer token"},
        )
    try:
        verify_module_jwt(auth_header.removeprefix("Bearer ").strip())
    except (InvalidJWTError, ExpiredJWTError, WrongAudienceError) as exc:
        return JSONResponse(status_code=401, content={"error": "invalid_token", "detail": str(exc)})
    return None


def _with_history(draft: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]:
    return {**draft, "history": [doc for doc in history if doc.get("draft_id") == draft.get("_id")]}
