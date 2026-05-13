from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from zeler_platform_core.auth.jwt import verify_module_jwt
from zeler_platform_core.auth.module_admin import authorize_module_admin
from zeler_sheets.extension_tokens import ExtensionTokenService, SellerScope


class ExportConfigPayload(BaseModel):
    spreadsheet_id: str
    worksheet_name: str = "Events"
    enabled: bool = True


class ManualSyncPayload(BaseModel):
    seller_id: str


class ExtensionTokenPayload(BaseModel):
    label: str
    seller_scopes: list[SellerScope]
    formula_scopes: list[str] | None = None
    expires_at: datetime | None = None


def build_router(
    *,
    clock: Callable[[], datetime] | None = None,
    extension_token_pepper: str | None = None,
    extension_token_factory: Callable[[], str] | None = None,
) -> APIRouter:
    now = clock or (lambda: datetime.now(UTC))
    router = APIRouter(prefix="/sheets", tags=["sheets"])

    @router.get("/exports")
    async def list_exports(request: Request, seller_id: str) -> JSONResponse:
        auth = _authorize(request, seller_id=seller_id)
        if auth is not None:
            return auth

        exports = (
            await request.app.state.mongo_db["sheets_exports"]
            .find({"seller_id": seller_id})
            .to_list(length=100)
        )
        jobs = (
            await request.app.state.mongo_db["sheets_sync_jobs"]
            .find({"seller_id": seller_id})
            .to_list(length=100)
        )
        last_job = _latest_job(jobs)

        return JSONResponse(
            jsonable_encoder([_with_last_sync(export, last_job) for export in exports])
        )

    @router.put("/exports/{seller_id}")
    async def configure_export(
        request: Request, seller_id: str, payload: ExportConfigPayload
    ) -> JSONResponse:
        auth = _authorize(request, seller_id=seller_id)
        if auth is not None:
            return auth

        export_id = _export_id(seller_id)
        existing = await request.app.state.mongo_db["sheets_exports"].find_one({"_id": export_id})
        current_time = now()
        doc = {
            "_id": export_id,
            "seller_id": seller_id,
            "spreadsheet_id": payload.spreadsheet_id,
            "worksheet_name": payload.worksheet_name,
            "enabled": payload.enabled,
            "created_at": existing.get("created_at", current_time) if existing else current_time,
            "updated_at": current_time,
            "schema_version": 1,
        }
        await request.app.state.mongo_db["sheets_exports"].replace_one(
            {"_id": export_id}, doc, upsert=True
        )
        return JSONResponse(jsonable_encoder(doc))

    @router.post("/sync-jobs", status_code=201)
    async def create_sync_job(request: Request, payload: ManualSyncPayload) -> JSONResponse:
        auth = _authorize(request, seller_id=payload.seller_id)
        if auth is not None:
            return auth

        export = await request.app.state.mongo_db["sheets_exports"].find_one(
            {"seller_id": payload.seller_id, "enabled": True}
        )
        if export is None:
            return JSONResponse(status_code=404, content={"error": "sheets_export_not_found"})

        requested_at = now()
        job = {
            "_id": f"sheets-sync-{payload.seller_id}-{int(requested_at.timestamp())}",
            "seller_id": payload.seller_id,
            "spreadsheet_id": str(export["spreadsheet_id"]),
            "state": "pending",
            "requested_at": requested_at,
            "updated_at": requested_at,
            "completed_at": None,
            "error": None,
            "schema_version": 1,
        }
        await request.app.state.mongo_db["sheets_sync_jobs"].insert_one(job)
        return JSONResponse(status_code=201, content=jsonable_encoder(job))

    @router.get("/sync-jobs")
    async def list_sync_jobs(request: Request, seller_id: str) -> JSONResponse:
        auth = _authorize(request, seller_id=seller_id)
        if auth is not None:
            return auth
        docs = (
            await request.app.state.mongo_db["sheets_sync_jobs"]
            .find({"seller_id": seller_id})
            .to_list(length=20)
        )
        return JSONResponse(jsonable_encoder(docs))

    @router.get("/extension-tokens")
    async def list_extension_tokens(
        request: Request, owner_user_id: str | None = None
    ) -> JSONResponse:
        auth = _authorize(request)
        if auth is not None:
            return auth
        claims = _claims(request)
        owner = owner_user_id or str(claims.issued_by or claims.seller_id)
        if owner != str(claims.issued_by or claims.seller_id):
            return JSONResponse(status_code=403, content={"error": "forbidden"})
        service = _extension_token_service(
            request,
            now=now,
            token_pepper=extension_token_pepper,
            token_factory=extension_token_factory,
        )
        tokens = await service.list_tokens(owner_user_id=owner)
        return JSONResponse(jsonable_encoder([token.model_dump(mode="json") for token in tokens]))

    @router.post("/extension-tokens", status_code=201)
    async def create_extension_token(
        request: Request, payload: ExtensionTokenPayload
    ) -> JSONResponse:
        auth = _authorize(request)
        if auth is not None:
            return auth
        claims = _claims(request)
        forbidden = _seller_scope_forbidden(payload.seller_scopes, seller_id=str(claims.seller_id))
        if forbidden is not None:
            return forbidden
        owner = str(claims.issued_by or claims.seller_id)
        service = _extension_token_service(
            request,
            now=now,
            token_pepper=extension_token_pepper,
            token_factory=extension_token_factory,
        )
        issued = await service.create_token(
            owner_user_id=owner,
            label=payload.label,
            seller_scopes=payload.seller_scopes,
            formula_scopes=payload.formula_scopes,
            expires_at=payload.expires_at,
        )
        body = issued.metadata.model_dump(mode="json") | {"token_once": issued.token_once}
        return JSONResponse(status_code=201, content=jsonable_encoder(body))

    @router.post("/extension-tokens/{token_id}:rotate")
    async def rotate_extension_token(request: Request, token_id: str) -> JSONResponse:
        auth = _authorize(request)
        if auth is not None:
            return auth
        claims = _claims(request)
        service = _extension_token_service(
            request,
            now=now,
            token_pepper=extension_token_pepper,
            token_factory=extension_token_factory,
        )
        try:
            issued = await service.rotate_token(
                token_id,
                owner_user_id=str(claims.issued_by or claims.seller_id),
            )
        except KeyError:
            return JSONResponse(status_code=404, content={"error": "extension_token_not_found"})
        body = issued.metadata.model_dump(mode="json") | {"token_once": issued.token_once}
        return JSONResponse(jsonable_encoder(body))

    @router.post("/extension-tokens/{token_id}:revoke")
    async def revoke_extension_token(request: Request, token_id: str) -> JSONResponse:
        auth = _authorize(request)
        if auth is not None:
            return auth
        claims = _claims(request)
        service = _extension_token_service(
            request,
            now=now,
            token_pepper=extension_token_pepper,
            token_factory=extension_token_factory,
        )
        try:
            metadata = await service.revoke_token(
                token_id,
                owner_user_id=str(claims.issued_by or claims.seller_id),
            )
        except KeyError:
            return JSONResponse(status_code=404, content={"error": "extension_token_not_found"})
        return JSONResponse(jsonable_encoder(metadata.model_dump(mode="json")))

    return router


def _authorize(request: Request, seller_id: str | int | None = None) -> JSONResponse | None:
    return authorize_module_admin(
        request,
        expected_module_id="sheets",
        seller_id=seller_id,
        verifier=verify_module_jwt,
    )


def _claims(request: Request) -> Any:
    auth_header = request.headers["Authorization"]
    return verify_module_jwt(auth_header.removeprefix("Bearer ").strip())


def _extension_token_service(
    request: Request,
    *,
    now: Callable[[], datetime],
    token_pepper: str | None,
    token_factory: Callable[[], str] | None,
) -> ExtensionTokenService:
    pepper = token_pepper or getattr(request.app.state, "extension_token_pepper", None)
    if pepper is None and hasattr(request.app.state, "settings"):
        pepper = getattr(request.app.state.settings, "extension_token_pepper", None)
    if pepper is None:
        raise RuntimeError("extension token pepper is not configured")
    if hasattr(pepper, "get_secret_value"):
        pepper = pepper.get_secret_value()
    return ExtensionTokenService(
        db=request.app.state.mongo_db,
        token_pepper=str(pepper),
        now_fn=now,
        token_factory=token_factory,
    )


def _seller_scope_forbidden(
    seller_scopes: list[SellerScope], *, seller_id: str
) -> JSONResponse | None:
    if any(scope.seller_id != seller_id for scope in seller_scopes):
        return JSONResponse(
            status_code=403,
            content={"error": "forbidden", "detail": "seller scopes must match JWT seller_id"},
        )
    return None


def _export_id(seller_id: str) -> str:
    return f"export-{seller_id}"


def _latest_job(jobs: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not jobs:
        return None
    return max(jobs, key=lambda job: str(job.get("updated_at") or job.get("requested_at") or ""))


def _with_last_sync(export: dict[str, Any], last_job: dict[str, Any] | None) -> dict[str, Any]:
    if last_job is None:
        return {**export, "last_sync_state": None, "last_sync_updated_at": None}
    return {
        **export,
        "last_sync_state": last_job.get("state"),
        "last_sync_updated_at": last_job.get("updated_at"),
    }
