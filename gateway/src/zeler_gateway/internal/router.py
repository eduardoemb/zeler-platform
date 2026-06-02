from __future__ import annotations

import base64
import hashlib
import hmac
import os
from datetime import UTC, datetime
from fnmatch import fnmatchcase
from typing import Any, Literal, cast

from bson import Int64
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from zeler_gateway.tokens.encryption import EncryptedToken, decrypt_token
from zeler_platform_core.auth.jwt import (
    ExpiredJWTError,
    InvalidJWTError,
    WrongAudienceError,
    mint_module_jwt,
    verify_module_jwt,
)

router = APIRouter(prefix="/internal", tags=["internal"])
ZELER_APP_CLIENT_ID = "zeler-app"
ZELER_PLATFORM_APP_ID = "zeler-platform"
ZELER_APP_SIGNATURE_HEADER = "X-Zeler-Signature"
ZELER_CLIENT_ID_HEADER = "X-Zeler-Client-Id"


class TokenIssueRequest(BaseModel):
    seller_id: int
    platform_user_id: str | None = None
    scopes: list[str] = Field(min_length=1)
    ttl_s: int = Field(gt=0, le=300)
    token_kind: Literal["meli_access", "module_admin"] = "meli_access"  # noqa: S105 - token type discriminator, not a secret
    target_module_id: str | None = None


@router.post("/tokens/issue")
async def issue_token(request: Request, payload: TokenIssueRequest) -> JSONResponse:
    caller = await _authenticate_issue_caller(request, payload)
    if isinstance(caller, JSONResponse):
        return caller

    db = request.app.state.mongo_db
    module = await db["module_registry"].find_one({"_id": caller["module_id"], "status": "enabled"})
    if module is None:
        return _json_error(401, "unknown_module")
    seller_authorization = await _authorize_token_issue_seller(
        db=db,
        payload=payload,
        module=module,
        caller_auth_scheme=caller["auth_scheme"],
    )
    if isinstance(seller_authorization, JSONResponse):
        return seller_authorization

    allowed_scopes = cast(list[str], module.get("allowed_meli_scopes", []))
    if not all(_scope_allowed(scope, allowed_scopes) for scope in payload.scopes):
        return _json_error(403, "out_of_scope")

    if payload.token_kind == "module_admin":  # noqa: S105 - token type discriminator, not a secret
        if payload.target_module_id is None or not payload.target_module_id.strip():
            return _json_error(422, "target_module_id_required")
        target_module_id = payload.target_module_id.strip()
        if not _module_admin_scopes_match_target(payload.scopes, target_module_id):
            return _json_error(403, "out_of_scope")
        admin_token = mint_module_jwt(
            target_module_id,
            seller_id=payload.seller_id,
            ttl_s=payload.ttl_s,
            token_type="module_admin",  # noqa: S106 - token type discriminator, not a secret
            scopes=payload.scopes,
            issued_by=caller["module_id"],
            platform_user_id=seller_authorization,
        )
        await _insert_issue_audit(
            db=db,
            module_id=caller["module_id"],
            seller_id=payload.seller_id,
            scopes=payload.scopes,
            ttl_s=payload.ttl_s,
            token_kind=payload.token_kind,
            target_module_id=target_module_id,
            platform_user_id=seller_authorization,
        )
        return JSONResponse(
            {
                "access_token": admin_token,
                "token_type": "Bearer",
                "expires_in": payload.ttl_s,
                "scopes": payload.scopes,
            }
        )

    account = await db["meli_accounts"].find_one(
        {"seller_id": payload.seller_id, "status": "active"}
    )
    if account is None:
        return _json_error(412, "account_not_active")

    access_token = await decrypt_token(
        EncryptedToken(
            ciphertext=cast(bytes, account["access_token_ciphertext"]),
            nonce=cast(bytes, account["token_nonce"]),
            dek_wrapped=cast(bytes, account["access_token_dek_wrapped"]),
            kms_key_version=cast(str, account["kms_key_version"]),
        ),
        account_id=str(payload.seller_id),
    )
    await _insert_issue_audit(
        db=db,
        module_id=caller["module_id"],
        seller_id=payload.seller_id,
        scopes=payload.scopes,
        ttl_s=payload.ttl_s,
        token_kind=payload.token_kind,
        target_module_id=None,
        platform_user_id=seller_authorization,
    )
    return JSONResponse(
        {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": payload.ttl_s,
            "scopes": payload.scopes,
        }
    )


def _scope_allowed(requested_scope: str, allowed_scopes: list[str]) -> bool:
    return any(fnmatchcase(requested_scope, allowed_scope) for allowed_scope in allowed_scopes)


def _module_admin_scopes_match_target(scopes: list[str], target_module_id: str) -> bool:
    return all(scope == f"admin:{target_module_id}" for scope in scopes)


async def _authenticate_issue_caller(
    request: Request, payload: TokenIssueRequest
) -> dict[str, str] | JSONResponse:
    client_id = request.headers.get(ZELER_CLIENT_ID_HEADER)
    if client_id == ZELER_APP_CLIENT_ID:
        if payload.token_kind != "module_admin":  # noqa: S105 - token type discriminator
            return _json_error(403, "out_of_scope")
        if not await _verify_zeler_app_signature(request):
            return _json_error(401, "invalid_token", detail="invalid zeler-app signature")
        return {"module_id": ZELER_APP_CLIENT_ID, "auth_scheme": "zeler_app_hmac"}

    if _signed_platform_user_id(payload) is not None:
        return _json_error(403, "out_of_scope")

    auth_header = request.headers.get("Authorization")
    if auth_header is None or not auth_header.startswith("Bearer "):
        return _json_error(401, "invalid_token", detail="missing bearer token")

    try:
        claims = verify_module_jwt(auth_header.removeprefix("Bearer ").strip())
    except (InvalidJWTError, ExpiredJWTError, WrongAudienceError) as exc:
        return _json_error(401, "invalid_token", detail=str(exc))

    if claims.seller_id != payload.seller_id:
        return _json_error(403, "seller_mismatch")
    if claims.module_id == ZELER_APP_CLIENT_ID:
        return _json_error(401, "invalid_token", detail="zeler-app must use broker signature")
    return {"module_id": claims.module_id, "auth_scheme": "bearer"}


async def _verify_zeler_app_signature(request: Request) -> bool:
    secret = os.environ.get("ZELER_APP_BROKER_SECRET")
    if not secret:
        return False
    provided_signature = request.headers.get(ZELER_APP_SIGNATURE_HEADER)
    if provided_signature is None:
        return False
    body = await request.body()
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    expected_signature = "sha256=" + base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return hmac.compare_digest(provided_signature, expected_signature)


def _seller_allowed(seller_id: int, allowed_seller_ids: list[Any] | None) -> bool:
    if allowed_seller_ids is None:
        return True
    return str(seller_id) in _string_set(allowed_seller_ids)


async def _authorize_token_issue_seller(
    *,
    db: Any,
    payload: TokenIssueRequest,
    module: dict[str, Any],
    caller_auth_scheme: str,
) -> str | None | JSONResponse:
    signed_platform_user_id = _signed_platform_user_id(payload)
    if (
        caller_auth_scheme == "zeler_app_hmac"
        and _platform_user_id_field_present(payload)
        and signed_platform_user_id is None
    ):
        return _json_error(403, "seller_mismatch")

    if caller_auth_scheme == "zeler_app_hmac" and signed_platform_user_id is not None:
        owns_active_seller = await _platform_user_owns_active_seller(
            db, platform_user_id=signed_platform_user_id, seller_id=payload.seller_id
        )
        if not owns_active_seller:
            return _json_error(403, "seller_mismatch")
        return signed_platform_user_id

    if not _seller_allowed(
        payload.seller_id, cast(list[Any] | None, module.get("allowed_seller_ids"))
    ):
        return _json_error(403, "seller_mismatch")
    return None


def _signed_platform_user_id(payload: TokenIssueRequest) -> str | None:
    if payload.platform_user_id is None:
        return None
    platform_user_id = payload.platform_user_id.strip()
    if not platform_user_id:
        return None
    return platform_user_id


def _platform_user_id_field_present(payload: TokenIssueRequest) -> bool:
    return "platform_user_id" in payload.model_fields_set


def _string_set(raw_values: Any) -> set[str]:
    if not isinstance(raw_values, list):
        return set()
    return {str(value).strip() for value in raw_values if str(value).strip()}


async def _platform_user_owns_active_seller(
    db: Any, *, platform_user_id: str, seller_id: int
) -> bool:
    for normalized_seller_id in (seller_id, str(seller_id)):
        account = await db["meli_accounts"].find_one(
            {
                "platform_user_id": platform_user_id,
                "app_id": ZELER_PLATFORM_APP_ID,
                "seller_id": normalized_seller_id,
                "status": "active",
            }
        )
        if account is not None:
            return True
    return False


async def _insert_issue_audit(
    *,
    db: Any,
    module_id: str,
    seller_id: int,
    scopes: list[str],
    ttl_s: int,
    token_kind: str,
    target_module_id: str | None,
    platform_user_id: str | None,
) -> None:
    document: dict[str, Any] = {
        "at": datetime.now(UTC),
        "module_id": module_id,
        "seller_id": Int64(seller_id),
        "method": "POST",
        "path": "/internal/tokens/issue",
        "status": 200,
        "duration_ms": 0,
        "scopes": scopes,
        "ttl_s": ttl_s,
        "token_kind": token_kind,
        "decision": "issued",
        "schema_version": 1,
    }
    if target_module_id is not None:
        document["target_module_id"] = target_module_id
    if platform_user_id is not None:
        document["platform_user_id"] = platform_user_id
    await db["audit_log"].insert_one(document)


def _json_error(status_code: int, error: str, *, detail: str | None = None) -> JSONResponse:
    body: dict[str, Any] = {"error": error}
    if detail is not None:
        body["detail"] = detail
    return JSONResponse(status_code=status_code, content=body)
