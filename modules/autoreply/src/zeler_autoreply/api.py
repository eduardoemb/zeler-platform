from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from zeler_autoreply.consumer import template_matches
from zeler_platform_core.auth.jwt import (
    ExpiredJWTError,
    InvalidJWTError,
    WrongAudienceError,
    verify_module_jwt,
)


class TemplatePayload(BaseModel):
    seller_id: str
    template_name: str
    match_type: str
    pattern: str
    answer_text: str
    enabled: bool = True


class TemplatePatch(BaseModel):
    template_name: str | None = None
    match_type: str | None = None
    pattern: str | None = None
    answer_text: str | None = None
    enabled: bool | None = None


class PreviewPayload(BaseModel):
    match_type: str
    pattern: str
    answer_text: str
    sample_text: str


def build_router(*, clock: Callable[[], datetime] | None = None) -> APIRouter:
    now = clock or (lambda: datetime.now(UTC))
    router = APIRouter(prefix="/autoreply", tags=["autoreply"])

    @router.get("/templates")
    async def list_templates(request: Request, seller_id: str) -> JSONResponse:
        auth = _authorize(request)
        if auth is not None:
            return auth
        templates = (
            await request.app.state.mongo_db["autoreply_templates"]
            .find({"seller_id": seller_id})
            .to_list(length=100)
        )
        history = (
            await request.app.state.mongo_db["autoreply_history"]
            .find({"seller_id": seller_id})
            .to_list(length=100)
        )
        return JSONResponse(
            jsonable_encoder([_with_recent_history(template, history) for template in templates])
        )

    @router.post("/templates", status_code=201)
    async def create_template(request: Request, payload: TemplatePayload) -> JSONResponse:
        auth = _authorize(request)
        if auth is not None:
            return auth
        created_at = now()
        doc = {
            "_id": f"autoreply-template-{payload.seller_id}-{int(created_at.timestamp())}",
            "seller_id": payload.seller_id,
            "template_name": payload.template_name,
            "match_type": payload.match_type,
            "pattern": payload.pattern,
            "answer_text": payload.answer_text,
            "enabled": payload.enabled,
            "created_at": created_at,
            "updated_at": created_at,
            "schema_version": 1,
        }
        await request.app.state.mongo_db["autoreply_templates"].insert_one(doc)
        return JSONResponse(status_code=201, content=jsonable_encoder(doc))

    @router.patch("/templates/{template_id}")
    async def update_template(
        request: Request, template_id: str, payload: TemplatePatch
    ) -> JSONResponse:
        auth = _authorize(request)
        if auth is not None:
            return auth
        current = await request.app.state.mongo_db["autoreply_templates"].find_one(
            {"_id": template_id}
        )
        if current is None:
            return JSONResponse(status_code=404, content={"error": "autoreply_template_not_found"})
        updates = payload.model_dump(exclude_unset=True)
        updated = {**current, **updates, "updated_at": now()}
        await request.app.state.mongo_db["autoreply_templates"].replace_one(
            {"_id": template_id}, updated, upsert=True
        )
        return JSONResponse(jsonable_encoder(updated))

    @router.delete("/templates/{template_id}", status_code=204)
    async def delete_template(request: Request, template_id: str) -> JSONResponse:
        auth = _authorize(request)
        if auth is not None:
            return auth
        current = await request.app.state.mongo_db["autoreply_templates"].find_one(
            {"_id": template_id}
        )
        if current is None:
            return JSONResponse(status_code=404, content={"error": "autoreply_template_not_found"})
        await request.app.state.mongo_db["autoreply_templates"].delete_one({"_id": template_id})
        return JSONResponse(status_code=204, content=None)

    @router.post("/templates/preview")
    async def preview_template(request: Request, payload: PreviewPayload) -> JSONResponse:
        auth = _authorize(request)
        if auth is not None:
            return auth
        return JSONResponse(
            {
                "matched": template_matches(
                    payload.sample_text,
                    payload.match_type,
                    payload.pattern,
                ),
                "answer_text": payload.answer_text,
            }
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


def _with_recent_history(template: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]:
    template_history = [doc for doc in history if doc.get("template_id") == template.get("_id")]
    if not template_history:
        template_history = history[:5]
    return {**template, "recent_history": template_history[:5]}
