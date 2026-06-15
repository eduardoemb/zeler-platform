from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bson.decimal128 import Decimal128
from fastapi import APIRouter, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from zeler_platform_core.auth.jwt import verify_module_jwt
from zeler_platform_core.auth.module_admin import authorize_module_admin
from zeler_platform_core.models import SellerUnitCost
from zeler_sheets.extension_token_encryption import ExtensionTokenSecretCipher
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
from zeler_sheets.formulas.handlers_item_shipping_catalog import (
    build_item_shipping_catalog_formula_handlers,
)
from zeler_sheets.formulas.handlers_orders_questions import build_order_question_formula_handlers
from zeler_sheets.formulas.handlers_quality_calculator import (
    build_quality_calculator_formula_handlers,
)
from zeler_sheets.formulas.handlers_remaining_phase4 import (
    build_remaining_phase4_formula_handlers,
)
from zeler_sheets.formulas.handlers_returns_histories_withdrawals import (
    build_returns_histories_withdrawals_formula_handlers,
)
from zeler_sheets.formulas.read_models import FormulaReadModelRepository
from zeler_sheets.formulas.registry import FormulaRegistry
from zeler_sheets.formulas.runtime_states import (
    FormulaRuntimeState,
    build_explicit_unsupported_formula_handlers,
    get_formula_runtime_states,
)
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


class UnitCostConfigPayload(BaseModel):
    normalized_sku: str | None = None
    item_id: str | None = None
    variation_id: str | None = None
    unit_cost: Decimal
    currency: str
    source: str
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    created_by: str | None = None
    updated_by: str | None = None


ZELER_PLATFORM_APP_ID = "zeler-platform"


@dataclass(frozen=True)
class ExtensionTokenAuthContext:
    owner_user_id: str
    allowed_seller_ids: set[str]


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
    extension_token_secret_cipher: ExtensionTokenSecretCipher | None = None,
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

    @router.get("/unit-costs")
    async def list_unit_costs(request: Request, seller_id: str) -> JSONResponse:
        auth = _authorize(request, seller_id=seller_id)
        if auth is not None:
            return auth
        docs = (
            await request.app.state.mongo_db["seller_unit_costs"]
            .find({"seller_id": seller_id})
            .sort([("normalized_sku", 1), ("item_id", 1), ("variation_id", 1)])
            .to_list(length=500)
        )
        return JSONResponse(jsonable_encoder(_unit_cost_json_safe(docs)))

    @router.put("/unit-costs/{seller_id}")
    async def upsert_unit_cost(
        request: Request, seller_id: str, payload: UnitCostConfigPayload
    ) -> JSONResponse:
        auth = _authorize(request, seller_id=seller_id)
        if auth is not None:
            return auth
        current_time = now()
        payload_doc = payload.model_dump()
        effective_from = payload_doc.pop("effective_from") or current_time
        model_doc = SellerUnitCost(
            _id=_unit_cost_id(seller_id, payload),
            seller_id=seller_id,
            status="active",
            effective_from=effective_from,
            created_at=current_time,
            updated_at=current_time,
            **payload_doc,
        ).model_dump(by_alias=True)
        doc = cast(dict[str, Any], _bson_safe(model_doc))
        await request.app.state.mongo_db["seller_unit_costs"].replace_one(
            {"_id": doc["_id"]}, doc, upsert=True
        )
        return JSONResponse(jsonable_encoder(_unit_cost_json_safe(doc)))

    @router.post("/unit-costs/{seller_id}/{unit_cost_id}:deactivate")
    async def deactivate_unit_cost(
        request: Request, seller_id: str, unit_cost_id: str
    ) -> JSONResponse:
        auth = _authorize(request, seller_id=seller_id)
        if auth is not None:
            return auth
        collection = request.app.state.mongo_db["seller_unit_costs"]
        existing = await collection.find_one({"_id": unit_cost_id, "seller_id": seller_id})
        if existing is None:
            return JSONResponse(status_code=404, content={"error": "unit_cost_not_found"})
        await collection.update_one(
            {"_id": unit_cost_id, "seller_id": seller_id},
            {"$set": {"status": "inactive", "updated_at": now()}},
        )
        updated = await collection.find_one({"_id": unit_cost_id, "seller_id": seller_id})
        return JSONResponse(jsonable_encoder(_unit_cost_json_safe(updated)))

    @router.get("/extension-tokens")
    async def list_extension_tokens(
        request: Request, owner_user_id: str | None = None
    ) -> JSONResponse:
        auth = _authorize(request)
        if auth is not None:
            return auth
        claims = _claims(request)
        default_owner = _extension_token_owner(claims)
        owner = owner_user_id or default_owner
        if owner != default_owner:
            return JSONResponse(status_code=403, content={"error": "forbidden"})
        context = await _extension_token_auth_context(request, claims)
        if isinstance(context, JSONResponse):
            return context
        service = _extension_token_service(
            request,
            now=now,
            token_pepper=extension_token_pepper,
            token_factory=extension_token_factory,
            secret_cipher=extension_token_secret_cipher,
        )
        tokens = await service.list_tokens(
            owner_user_id=owner,
            allowed_seller_ids=context.allowed_seller_ids,
        )
        return JSONResponse(jsonable_encoder([token.model_dump(mode="json") for token in tokens]))

    @router.post("/extension-tokens", status_code=201)
    async def create_extension_token(
        request: Request, payload: ExtensionTokenPayload
    ) -> JSONResponse:
        auth = _authorize(request)
        if auth is not None:
            return auth
        claims = _claims(request)
        canonical_scopes_or_error = await _canonical_seller_scopes(
            request.app.state.mongo_db,
            payload.seller_scopes,
            claims=claims,
        )
        if isinstance(canonical_scopes_or_error, JSONResponse):
            return canonical_scopes_or_error
        if not getattr(claims, "platform_user_id", None):
            forbidden = _seller_scope_forbidden(
                canonical_scopes_or_error, seller_id=str(claims.seller_id)
            )
            if forbidden is not None:
                return forbidden
        owner = _extension_token_owner(claims)
        service = _extension_token_service(
            request,
            now=now,
            token_pepper=extension_token_pepper,
            token_factory=extension_token_factory,
            secret_cipher=extension_token_secret_cipher,
        )
        try:
            issued = await service.create_token(
                owner_user_id=owner,
                label=payload.label,
                seller_scopes=canonical_scopes_or_error,
                formula_scopes=payload.formula_scopes,
                expires_at=payload.expires_at,
            )
        except ExtensionTokenValidationError as exc:
            return JSONResponse(
                status_code=400,
                content={"error": "invalid_seller_scopes", "detail": exc.message},
            )
        body = issued.metadata.model_dump(mode="json") | {"token_once": issued.token_once}
        return JSONResponse(status_code=201, content=jsonable_encoder(body))

    @router.post("/extension-tokens/{token_id}:rotate")
    async def rotate_extension_token(request: Request, token_id: str) -> JSONResponse:
        auth = _authorize(request)
        if auth is not None:
            return auth
        claims = _claims(request)
        context = await _extension_token_auth_context(request, claims)
        if isinstance(context, JSONResponse):
            return context
        service = _extension_token_service(
            request,
            now=now,
            token_pepper=extension_token_pepper,
            token_factory=extension_token_factory,
            secret_cipher=extension_token_secret_cipher,
        )
        try:
            issued = await service.rotate_token(
                token_id,
                owner_user_id=context.owner_user_id,
                allowed_seller_ids=context.allowed_seller_ids,
            )
        except KeyError:
            return JSONResponse(status_code=404, content={"error": "extension_token_not_found"})
        except ExtensionTokenValidationError as exc:
            return _token_management_error(exc)
        body = issued.metadata.model_dump(mode="json") | {"token_once": issued.token_once}
        return JSONResponse(jsonable_encoder(body))

    @router.post("/extension-tokens/{token_id}:revoke")
    async def revoke_extension_token(request: Request, token_id: str) -> JSONResponse:
        auth = _authorize(request)
        if auth is not None:
            return auth
        claims = _claims(request)
        context = await _extension_token_auth_context(request, claims)
        if isinstance(context, JSONResponse):
            return context
        service = _extension_token_service(
            request,
            now=now,
            token_pepper=extension_token_pepper,
            token_factory=extension_token_factory,
            secret_cipher=extension_token_secret_cipher,
        )
        try:
            metadata = await service.revoke_token(
                token_id,
                owner_user_id=context.owner_user_id,
                allowed_seller_ids=context.allowed_seller_ids,
            )
        except KeyError:
            return JSONResponse(status_code=404, content={"error": "extension_token_not_found"})
        except ExtensionTokenValidationError as exc:
            return _token_management_error(exc)
        return JSONResponse(jsonable_encoder(metadata.model_dump(mode="json")))

    @router.post("/extension-tokens/{token_id}:reveal")
    async def reveal_extension_token(request: Request, token_id: str) -> JSONResponse:
        auth = _authorize(request)
        if auth is not None:
            return auth
        claims = _claims(request)
        context = await _extension_token_auth_context(request, claims)
        if isinstance(context, JSONResponse):
            return context
        service = _extension_token_service(
            request,
            now=now,
            token_pepper=extension_token_pepper,
            token_factory=extension_token_factory,
            secret_cipher=extension_token_secret_cipher,
        )
        try:
            revealed = await service.reveal_token(
                token_id,
                owner_user_id=context.owner_user_id,
                allowed_seller_ids=context.allowed_seller_ids,
            )
        except ExtensionTokenValidationError as exc:
            return _token_management_error(exc)
        body = revealed.metadata.model_dump(mode="json") | {"token_once": revealed.token_once}
        return JSONResponse(jsonable_encoder(body))

    @router.delete("/extension-tokens/{token_id}", status_code=204)
    async def delete_extension_token(request: Request, token_id: str) -> Response:
        auth = _authorize(request)
        if auth is not None:
            return auth
        claims = _claims(request)
        context = await _extension_token_auth_context(request, claims)
        if isinstance(context, JSONResponse):
            return context
        service = _extension_token_service(
            request,
            now=now,
            token_pepper=extension_token_pepper,
            token_factory=extension_token_factory,
            secret_cipher=extension_token_secret_cipher,
        )
        try:
            await service.delete_token(
                token_id,
                owner_user_id=context.owner_user_id,
                allowed_seller_ids=context.allowed_seller_ids,
            )
        except ExtensionTokenValidationError as exc:
            return _token_management_error(exc)
        return Response(status_code=204)

    @router.get("/formulas/inventory")
    async def list_formula_inventory() -> JSONResponse:
        runtime_states = get_formula_runtime_states()
        return JSONResponse(
            jsonable_encoder(
                {
                    "formulas": [
                        _contract_with_runtime_state(contract, runtime_states[contract.name])
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
    secret_cipher: ExtensionTokenSecretCipher | None = None,
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
    cipher = secret_cipher or getattr(request.app.state, "extension_token_secret_cipher", None)
    return ExtensionTokenService(
        db=request.app.state.mongo_db,
        token_pepper=str(pepper),
        now_fn=now,
        token_factory=token_factory,
        audit_hook=audit_hook,
        rate_limit_hook=rate_limit_hook,
        secret_cipher=cast(ExtensionTokenSecretCipher | None, cipher),
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
        secret_cipher=None,
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
        seller_timezone=await _seller_timezone(request, validation.seller_id),
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

    return {
        "ok": True,
        "values": _formula_json_safe(result.values),
        "meta": _formula_json_safe(result.meta),
    }, 200


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


def _contract_with_runtime_state(
    contract: FormulaContract,
    runtime_state: FormulaRuntimeState,
) -> dict[str, Any]:
    payload = contract.to_json_dict() | {"status": runtime_state.state}
    if runtime_state.state == "unsupported":
        payload["unsupported_reason"] = runtime_state.reason
    return payload


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
        | build_item_shipping_catalog_formula_handlers(repository, now_fn=now)
        | build_order_question_formula_handlers(repository, now_fn=now)
        | build_quality_calculator_formula_handlers(repository, now_fn=now)
        | build_remaining_phase4_formula_handlers(repository, now_fn=now)
        | build_returns_histories_withdrawals_formula_handlers(repository, now_fn=now)
        | build_explicit_unsupported_formula_handlers()
    )


async def _seller_timezone(request: Request, seller_id: str) -> str:
    collection = request.app.state.mongo_db["meli_accounts"]
    account = await collection.find_one({"seller_id": seller_id})
    if account is None:
        legacy_seller_id = _legacy_int_seller_id(seller_id)
        if legacy_seller_id is not None:
            account = await collection.find_one({"seller_id": legacy_seller_id})
    return _valid_timezone(account.get("timezone") if account else None)


def _legacy_int_seller_id(seller_id: str) -> int | None:
    try:
        return int(seller_id)
    except ValueError:
        return None


def _valid_timezone(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return "UTC"
    timezone = value.strip()
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        return "UTC"
    return timezone


def _bearer_token(request: Request) -> str:
    auth_header = request.headers.get("Authorization", "")
    scheme, separator, token = auth_header.partition(" ")
    if separator and scheme.casefold() == "bearer":
        return token.strip()
    return ""


def _formula_json_safe(value: Any) -> Any:
    if isinstance(value, Decimal128):
        return _decimal_to_sheet_number(value.to_decimal())
    if isinstance(value, Decimal):
        return _decimal_to_sheet_number(value)
    if isinstance(value, list):
        return [_formula_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_formula_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: _formula_json_safe(item) for key, item in value.items()}
    return value


def _decimal_to_sheet_number(value: Decimal) -> int | float | str:
    if not value.is_finite():
        return str(value)
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def _bson_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return Decimal128(value)
    if isinstance(value, list):
        return [_bson_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: _bson_safe(item) for key, item in value.items()}
    return value


def _unit_cost_json_safe(value: Any) -> Any:
    if isinstance(value, Decimal128):
        return _decimal_to_sheet_number(value.to_decimal())
    if isinstance(value, Decimal):
        return _decimal_to_sheet_number(value)
    if isinstance(value, list):
        return [_unit_cost_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: _unit_cost_json_safe(item) for key, item in value.items()}
    return value


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


def _unit_cost_id(seller_id: str, payload: UnitCostConfigPayload) -> str:
    identity = ":".join(
        [
            str(seller_id).strip(),
            str(payload.normalized_sku or "_").strip().upper() or "_",
            str(payload.item_id or "_").strip() or "_",
            str(payload.variation_id or "_").strip() or "_",
        ]
    )
    return f"seller-unit-cost:{identity}"


def _extension_token_owner(claims: Any) -> str:
    return str(getattr(claims, "platform_user_id", None) or claims.issued_by or claims.seller_id)


async def _extension_token_auth_context(
    request: Request,
    claims: Any,
) -> ExtensionTokenAuthContext | JSONResponse:
    return ExtensionTokenAuthContext(
        owner_user_id=_extension_token_owner(claims),
        allowed_seller_ids=await _allowed_extension_token_seller_ids(
            request.app.state.mongo_db,
            claims=claims,
        ),
    )


async def _allowed_extension_token_seller_ids(db: Any, *, claims: Any) -> set[str]:
    platform_user_id = getattr(claims, "platform_user_id", None)
    if not platform_user_id:
        return {str(claims.seller_id)}
    accounts = (
        await db["meli_accounts"]
        .find(
            {
                "platform_user_id": str(platform_user_id),
                "app_id": ZELER_PLATFORM_APP_ID,
                "status": "active",
            }
        )
        .to_list(length=100)
    )
    return {str(account["seller_id"]) for account in accounts}


def _token_management_error(exc: ExtensionTokenValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=_token_management_status(exc.code),
        content={"error": exc.code, "detail": _token_management_detail(exc.code)},
    )


def _token_management_status(code: str) -> int:
    return {
        "TOKEN_NOT_FOUND_OR_FORBIDDEN": 404,
        "TOKEN_NOT_ACTIVE": 409,
        "TOKEN_NOT_REVOKED": 409,
        "TOKEN_DELETED": 409,
        "TOKEN_EXPIRED": 409,
        "TOKEN_SECRET_UNAVAILABLE": 409,
    }.get(code, 400)


def _token_management_detail(code: str) -> str:
    return {
        "TOKEN_NOT_FOUND_OR_FORBIDDEN": "Token no encontrado o sin permisos.",
        "TOKEN_NOT_ACTIVE": "El token no está activo.",
        "TOKEN_NOT_REVOKED": "Revocá el token antes de eliminarlo.",
        "TOKEN_DELETED": "El token ya fue eliminado.",
        "TOKEN_EXPIRED": "El token está vencido.",
        "TOKEN_SECRET_UNAVAILABLE": (
            "Este token no se puede revelar. Generá o rotá el token para obtener "
            "un valor recuperable."
        ),
    }.get(code, "No se pudo completar la operación del token.")


async def _canonical_seller_scopes(
    db: Any,
    seller_scopes: list[SellerScope],
    *,
    claims: Any,
) -> list[SellerScope] | JSONResponse:
    platform_user_id = getattr(claims, "platform_user_id", None)
    if not platform_user_id:
        return seller_scopes
    if not seller_scopes:
        return JSONResponse(
            status_code=403,
            content={"error": "forbidden", "detail": "seller scopes must not be empty"},
        )

    canonical_scopes: list[SellerScope] = []
    for scope in seller_scopes:
        account = await _find_active_platform_account(
            db,
            platform_user_id=str(platform_user_id),
            seller_id=scope.seller_id,
        )
        if account is None:
            return JSONResponse(
                status_code=403,
                content={"error": "forbidden", "detail": "seller scope is not authorized"},
            )
        canonical_scopes.append(
            SellerScope(
                seller_id=str(account["seller_id"]),
                nickname=str(account.get("nickname") or account["seller_id"]),
            )
        )
    return canonical_scopes


async def _find_active_platform_account(
    db: Any, *, platform_user_id: str, seller_id: str
) -> dict[str, Any] | None:
    seller_id_values: list[str | int] = [seller_id]
    legacy_seller_id = _legacy_int_seller_id(seller_id)
    if legacy_seller_id is not None:
        seller_id_values.append(legacy_seller_id)
    for normalized_seller_id in seller_id_values:
        account = await db["meli_accounts"].find_one(
            {
                "platform_user_id": platform_user_id,
                "app_id": ZELER_PLATFORM_APP_ID,
                "seller_id": normalized_seller_id,
                "status": "active",
            }
        )
        if account is not None:
            return cast("dict[str, Any]", account)
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
