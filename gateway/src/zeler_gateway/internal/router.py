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
ZELER_APP_SIGNATURE_HEADER = "X-Zeler-Signature"
ZELER_CLIENT_ID_HEADER = "X-Zeler-Client-Id"


class TokenIssueRequest(BaseModel):
    seller_id: int
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
    if not _seller_allowed(
        payload.seller_id,
        cast(list[int] | None, module.get("allowed_seller_ids")),
    ):
        return _json_error(403, "seller_mismatch")
    allowed_scopes = cast(list[str], module.get("allowed_meli_scopes", []))
    if not all(_scope_allowed(scope, allowed_scopes) for scope in payload.scopes):
        return _json_error(403, "out_of_scope")

    if payload.token_kind == "module_admin":  # noqa: S105 - token type discriminator, not a secret
        if payload.target_module_id is None or not payload.target_module_id.strip():
            return _json_error(422, "target_module_id_required")
        admin_token = mint_module_jwt(
            payload.target_module_id.strip(),
            seller_id=payload.seller_id,
            ttl_s=payload.ttl_s,
            token_type="module_admin",  # noqa: S106 - token type discriminator, not a secret
            scopes=payload.scopes,
            issued_by=caller["module_id"],
        )
        await _insert_issue_audit(
            db=db,
            module_id=caller["module_id"],
            seller_id=payload.seller_id,
            scopes=payload.scopes,
            ttl_s=payload.ttl_s,
            token_kind=payload.token_kind,
            target_module_id=payload.target_module_id.strip(),
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


async def _authenticate_issue_caller(
    request: Request, payload: TokenIssueRequest
) -> dict[str, str] | JSONResponse:
    client_id = request.headers.get(ZELER_CLIENT_ID_HEADER)
    if client_id == ZELER_APP_CLIENT_ID:
        if payload.token_kind != "module_admin":  # noqa: S105 - token type discriminator
            return _json_error(403, "out_of_scope")
        if not await _verify_zeler_app_signature(request):
            return _json_error(401, "invalid_token", detail="invalid zeler-app signature")
        return {"module_id": ZELER_APP_CLIENT_ID}

    auth_header = request.headers.get("Authorization")
    if auth_header is None or not auth_header.startswith("Bearer "):
        return _json_error(401, "invalid_token", detail="missing bearer token")

    try:
        claims = verify_module_jwt(auth_header.removeprefix("Bearer ").strip())
    except (InvalidJWTError, ExpiredJWTError, WrongAudienceError) as exc:
        return _json_error(401, "invalid_token", detail=str(exc))

    if claims.seller_id != payload.seller_id:
        return _json_error(403, "seller_mismatch")
    return {"module_id": claims.module_id}


async def _verify_zeler_app_signature(request: Request) -> bool:
    secret = os.environ.get("ZELER_APP_BROKER_SECRET")
    if not secret:
        return False
    provided_signature = request.headers.get(ZELER_APP_SIGNATURE_HEADER)
    if provided_signature is None:
        return False
    body = await request.body()
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    expected_signature = "sha256=" + base64.urlsafe_b64encode(digest).rstrip(b"=").decode(
        "ascii"
    )
    return hmac.compare_digest(provided_signature, expected_signature)


def _seller_allowed(seller_id: int, allowed_seller_ids: list[int] | None) -> bool:
    if allowed_seller_ids is None:
        return True
    return seller_id in allowed_seller_ids


async def _insert_issue_audit(
    *,
    db: Any,
    module_id: str,
    seller_id: int,
    scopes: list[str],
    ttl_s: int,
    token_kind: str,
    target_module_id: str | None,
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
        "schema_version": 1,
    }
    if target_module_id is not None:
        document["target_module_id"] = target_module_id
    await db["audit_log"].insert_one(document)


def _json_error(status_code: int, error: str, *, detail: str | None = None) -> JSONResponse:
    body: dict[str, Any] = {"error": error}
    if detail is not None:
        body["detail"] = detail
    return JSONResponse(status_code=status_code, content=body)
