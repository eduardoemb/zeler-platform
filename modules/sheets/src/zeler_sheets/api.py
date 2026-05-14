from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from zeler_platform_core.auth.jwt import verify_module_jwt
from zeler_platform_core.auth.module_admin import authorize_module_admin
from zeler_sheets.extension_tokens import (
    AuditHook,
    ExtensionTokenService,
    ExtensionTokenValidationError,
    RateLimitHook,
    SellerScope,
)
from zeler_sheets.formulas.dispatcher import (
    FormulaDataUnavailableError,
    FormulaDispatcher,
    FormulaExecutionContext,
    FormulaExecutionResult,
)
from zeler_sheets.formulas.handlers_core import build_core_formula_handlers
from zeler_sheets.formulas.handlers_orders_questions import build_order_question_formula_handlers
from zeler_sheets.formulas.read_models import FormulaReadModelRepository
from zeler_sheets.formulas.registry import FormulaRegistry
from zeler_sheets.formulas.schemas import FormulaContract


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


class FormulaExecutePayload(BaseModel):
    formula: str
    cuenta: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None


class FormulaBatchPayload(BaseModel):
    requests: list[FormulaExecutePayload]


FormulaDispatchCallable = Callable[
    [FormulaExecutionContext], FormulaExecutionResult | Awaitable[FormulaExecutionResult]
]


def build_router(
    *,
    clock: Callable[[], datetime] | None = None,
    extension_token_pepper: str | None = None,
    extension_token_factory: Callable[[], str] | None = None,
    formula_audit_hook: AuditHook | None = None,
    formula_rate_limit_hook: RateLimitHook | None = None,
    formula_dispatcher: FormulaDispatcher | FormulaDispatchCallable | None = None,
) -> APIRouter:
    now = clock or (lambda: datetime.now(UTC))
    registry = FormulaRegistry.default()
    dispatcher = formula_dispatcher
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

    @router.get("/formulas/inventory")
    async def list_formula_inventory() -> JSONResponse:
        return JSONResponse(
            jsonable_encoder(
                {
                    "formulas": [
                        contract.to_json_dict() | {"status": "data_unavailable"}
                        for contract in registry.list_contracts()
                    ],
                    "error_codes": list(registry.error_codes),
                }
            )
        )

    @router.post("/formulas:execute")
    async def execute_formula(request: Request, payload: FormulaExecutePayload) -> JSONResponse:
        body, status = await _execute_formula_payload(
            request,
            payload,
            registry=registry,
            dispatcher=dispatcher,
            now=now,
            token_pepper=extension_token_pepper,
            token_factory=extension_token_factory,
            audit_hook=formula_audit_hook,
            rate_limit_hook=formula_rate_limit_hook,
        )
        return JSONResponse(status_code=status, content=jsonable_encoder(body))

    @router.post("/formulas:batch")
    async def execute_formula_batch(request: Request, payload: FormulaBatchPayload) -> JSONResponse:
        results = []
        for formula_request in payload.requests:
            body, status = await _execute_formula_payload(
                request,
                formula_request,
                registry=registry,
                dispatcher=dispatcher,
                now=now,
                token_pepper=extension_token_pepper,
                token_factory=extension_token_factory,
                audit_hook=formula_audit_hook,
                rate_limit_hook=formula_rate_limit_hook,
            )
            results.append({"status": status, "body": body})
        return JSONResponse(jsonable_encoder({"ok": True, "results": results}))

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
    audit_hook: AuditHook | None = None,
    rate_limit_hook: RateLimitHook | None = None,
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
        audit_hook=audit_hook,
        rate_limit_hook=rate_limit_hook,
    )


async def _execute_formula_payload(
    request: Request,
    payload: FormulaExecutePayload,
    *,
    registry: FormulaRegistry,
    dispatcher: FormulaDispatcher | FormulaDispatchCallable | None,
    now: Callable[[], datetime],
    token_pepper: str | None,
    token_factory: Callable[[], str] | None,
    audit_hook: AuditHook | None,
    rate_limit_hook: RateLimitHook | None,
) -> tuple[dict[str, Any], int]:
    if not payload.cuenta:
        return _formula_error("BAD_ARGUMENT", "missing required field cuenta", status_code=400)

    token_service = _extension_token_service(
        request,
        now=now,
        token_pepper=token_pepper,
        token_factory=token_factory,
        audit_hook=audit_hook,
        rate_limit_hook=rate_limit_hook,
    )
    try:
        validation = await token_service.validate_token(
            _bearer_token(request),
            cuenta=payload.cuenta,
            formula=payload.formula,
            request_id=payload.request_id,
        )
    except ExtensionTokenValidationError as exc:
        return _formula_error(exc.code, exc.message, status_code=_error_status(exc.code))

    contract = registry.find(payload.formula)
    if contract is None:
        return _formula_error(
            "FORMULA_UNKNOWN",
            f"unknown formula {payload.formula}",
            status_code=200,
        )

    missing_argument = _missing_required_argument(contract, payload.args)
    if missing_argument is not None:
        return _formula_error(
            "BAD_ARGUMENT",
            f"missing required argument {missing_argument}",
            status_code=400,
        )

    context = FormulaExecutionContext(
        contract=contract,
        cuenta=payload.cuenta,
        seller_id=validation.seller_id,
        seller_nickname=validation.seller_nickname,
        token_id=validation.token_id,
        args=payload.args,
        request_id=payload.request_id,
    )
    try:
        result = await _dispatch_formula(_runtime_dispatcher(request, dispatcher, now=now), context)
    except FormulaDataUnavailableError as exc:
        return _formula_error("DATA_UNAVAILABLE", exc.message, status_code=200)
    except Exception:  # noqa: BLE001 - Apps Script callers require stable error cells.
        return _formula_error(
            "INTERNAL",
            "internal formula error",
            status_code=500,
            retryable=True,
        )

    return {"ok": True, "values": result.values, "meta": result.meta}, 200


async def _dispatch_formula(
    dispatcher: FormulaDispatcher | FormulaDispatchCallable,
    context: FormulaExecutionContext,
) -> FormulaExecutionResult:
    if isinstance(dispatcher, FormulaDispatcher):
        return await dispatcher.execute(context)
    result = dispatcher(context)
    if inspect.isawaitable(result):
        return await result
    return result


def _runtime_dispatcher(
    request: Request,
    dispatcher: FormulaDispatcher | FormulaDispatchCallable | None,
    *,
    now: Callable[[], datetime],
) -> FormulaDispatcher | FormulaDispatchCallable:
    if dispatcher is not None:
        return dispatcher
    repository = FormulaReadModelRepository(db=request.app.state.mongo_db)
    return FormulaDispatcher(
        build_core_formula_handlers(repository, now_fn=now)
        | build_order_question_formula_handlers(repository)
    )


def _bearer_token(request: Request) -> str:
    auth_header = request.headers.get("Authorization", "")
    scheme, separator, token = auth_header.partition(" ")
    if separator and scheme.casefold() == "bearer":
        return token.strip()
    return ""


def _missing_required_argument(contract: FormulaContract, args: dict[str, Any]) -> str | None:
    for parameter in contract.parameters:
        if parameter.name == "cuenta":
            continue
        if parameter.required and parameter.name not in args:
            return parameter.name
    return None


def _formula_error(
    code: str,
    message: str,
    *,
    status_code: int,
    retryable: bool = False,
) -> tuple[dict[str, Any], int]:
    body = {
        "ok": False,
        "error": {"code": code, "message": message, "retryable": retryable},
        "values": [[f"{code}: {message}"]],
    }
    return body, status_code


def _error_status(code: str) -> int:
    return {
        "TOKEN_MISSING": 401,
        "TOKEN_REVOKED": 401,
        "SELLER_FORBIDDEN": 403,
        "RATE_LIMITED": 429,
    }.get(code, 400)


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
