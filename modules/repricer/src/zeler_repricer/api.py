from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from zeler_platform_core.auth.jwt import verify_module_jwt
from zeler_platform_core.auth.module_admin import authorize_module_admin
from zeler_platform_core.models import RepricerRule


class RulePayload(BaseModel):
    id: str = Field(alias="_id")
    seller_id: str
    item_id: str
    strategy: str
    min_price: Decimal
    max_price: Decimal
    active: bool = True
    updated_at: datetime | None = None


def build_router() -> APIRouter:
    router = APIRouter(prefix="/repricer", tags=["repricer"])

    @router.get("/rules")
    async def list_rules(request: Request, seller_id: str) -> JSONResponse:
        auth = _authorize(request, seller_id=seller_id)
        if auth is not None:
            return auth
        docs = await (
            request.app.state.mongo_db["repricer_rules"]
            .find({"seller_id": seller_id})
            .to_list(length=100)
        )
        return JSONResponse(docs)

    @router.get("/history")
    async def list_history(request: Request, seller_id: str) -> JSONResponse:
        auth = _authorize(request, seller_id=seller_id)
        if auth is not None:
            return auth
        docs = await (
            request.app.state.mongo_db["repricer_history"]
            .find({"seller_id": seller_id})
            .to_list(length=20)
        )
        return JSONResponse(docs)

    @router.post("/rules", status_code=201)
    async def create_rule(request: Request, payload: RulePayload) -> JSONResponse:
        auth = _authorize(request, seller_id=payload.seller_id)
        if auth is not None:
            return auth
        if payload.min_price > payload.max_price:
            return JSONResponse(status_code=422, content={"error": "min_price_above_max_price"})
        now = payload.updated_at or datetime.now(UTC)
        rule = RepricerRule(
            _id=payload.id,
            seller_id=payload.seller_id,
            item_id=payload.item_id,
            strategy=payload.strategy,  # type: ignore[arg-type]
            min_price=payload.min_price,
            max_price=payload.max_price,
            active=payload.active,
            updated_at=now,
        )
        doc = rule.model_dump(mode="json", by_alias=True)
        await request.app.state.mongo_db["repricer_rules"].insert_one(doc)
        return JSONResponse(status_code=201, content=doc)

    @router.patch("/rules/{rule_id}")
    async def update_rule(request: Request, rule_id: str, patch: dict[str, Any]) -> JSONResponse:
        auth = _authorize(request)
        if auth is not None:
            return auth
        patch["updated_at"] = datetime.now(UTC)
        await request.app.state.mongo_db["repricer_rules"].update_one(
            {"_id": rule_id}, {"$set": patch}
        )
        return JSONResponse({"status": "updated"})

    @router.delete("/rules/{rule_id}")
    async def delete_rule(request: Request, rule_id: str) -> JSONResponse:
        auth = _authorize(request)
        if auth is not None:
            return auth
        await request.app.state.mongo_db["repricer_rules"].update_one(
            {"_id": rule_id}, {"$set": {"active": False, "updated_at": datetime.now(UTC)}}
        )
        return JSONResponse({"status": "deleted"})

    return router


def _authorize(request: Request, seller_id: str | int | None = None) -> JSONResponse | None:
    return authorize_module_admin(
        request,
        expected_module_id="repricer",
        seller_id=seller_id,
        verifier=verify_module_jwt,
    )
