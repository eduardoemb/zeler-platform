from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from zeler_platform_core.auth.jwt import (
    ExpiredJWTError,
    InvalidJWTError,
    WrongAudienceError,
    verify_module_jwt,
)


class StockLocationPayload(BaseModel):
    location_id: str = Field(min_length=1)
    quantity: int = Field(ge=0)


class InventoryRulePayload(BaseModel):
    seller_id: str
    item_id: str
    enabled: bool = True
    stock_locations: list[StockLocationPayload]


class InventoryRulePatch(BaseModel):
    enabled: bool | None = None
    stock_locations: list[StockLocationPayload] | None = None


def build_router(*, clock: Callable[[], datetime] | None = None) -> APIRouter:
    now = clock or (lambda: datetime.now(UTC))
    router = APIRouter(prefix="/fulldock", tags=["fulldock"])

    @router.get("/inventory-rules")
    async def list_rules(request: Request, seller_id: str) -> JSONResponse:
        auth = _authorize(request)
        if auth is not None:
            return auth
        rules = (
            await request.app.state.mongo_db["fulldock_inventory_rules"]
            .find({"seller_id": seller_id})
            .to_list(length=100)
        )
        history = (
            await request.app.state.mongo_db["fulldock_history"]
            .find({"seller_id": seller_id})
            .to_list(length=100)
        )
        return JSONResponse(
            jsonable_encoder([_with_recent_history(rule, history) for rule in rules])
        )

    @router.post("/inventory-rules", status_code=201)
    async def create_rule(request: Request, payload: InventoryRulePayload) -> JSONResponse:
        auth = _authorize(request)
        if auth is not None:
            return auth
        created_at = now()
        doc = {
            "_id": f"fulldock-rule-{payload.seller_id}-{payload.item_id}",
            "seller_id": payload.seller_id,
            "item_id": payload.item_id,
            "enabled": payload.enabled,
            "stock_locations": [location.model_dump() for location in payload.stock_locations],
            "created_at": created_at,
            "updated_at": created_at,
            "schema_version": 1,
        }
        await request.app.state.mongo_db["fulldock_inventory_rules"].insert_one(doc)
        return JSONResponse(status_code=201, content=jsonable_encoder(doc))

    @router.patch("/inventory-rules/{rule_id}")
    async def update_rule(
        request: Request, rule_id: str, payload: InventoryRulePatch
    ) -> JSONResponse:
        auth = _authorize(request)
        if auth is not None:
            return auth
        current = await request.app.state.mongo_db["fulldock_inventory_rules"].find_one(
            {"_id": rule_id}
        )
        if current is None:
            return JSONResponse(status_code=404, content={"error": "fulldock_rule_not_found"})
        raw_updates = payload.model_dump(exclude_unset=True)
        updates = raw_updates
        updated = {**current, **updates, "updated_at": now()}
        await request.app.state.mongo_db["fulldock_inventory_rules"].replace_one(
            {"_id": rule_id}, updated, upsert=True
        )
        return JSONResponse(jsonable_encoder(updated))

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


def _with_recent_history(rule: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]:
    rule_history = [doc for doc in history if doc.get("rule_id") == rule.get("_id")]
    if not rule_history:
        rule_history = [doc for doc in history if doc.get("item_id") == rule.get("item_id")]
    return {**rule, "recent_history": rule_history[:5]}
