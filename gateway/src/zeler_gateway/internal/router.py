from __future__ import annotations

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


class TokenIssueRequest(BaseModel):
    seller_id: int
    scopes: list[str] = Field(min_length=1)
    ttl_s: int = Field(gt=0, le=300)
    token_kind: Literal["meli_access", "module_admin"] = "meli_access"  # noqa: S105 - token type discriminator, not a secret
    target_module_id: str | None = None


@router.post("/tokens/issue")
async def issue_token(request: Request, payload: TokenIssueRequest) -> JSONResponse:
    auth_header = request.headers.get("Authorization")
    if auth_header is None or not auth_header.startswith("Bearer "):
        return _json_error(401, "invalid_token", detail="missing bearer token")

    try:
        claims = verify_module_jwt(auth_header.removeprefix("Bearer ").strip())
    except (InvalidJWTError, ExpiredJWTError, WrongAudienceError) as exc:
        return _json_error(401, "invalid_token", detail=str(exc))

    if claims.seller_id != payload.seller_id:
        return _json_error(403, "seller_mismatch")

    db = request.app.state.mongo_db
    module = await db["module_registry"].find_one({"_id": claims.module_id, "status": "enabled"})
    if module is None:
        return _json_error(401, "unknown_module")
    allowed_scopes = cast(list[str], module.get("allowed_meli_scopes", []))
    if not all(_scope_allowed(scope, allowed_scopes) for scope in payload.scopes):
        return _json_error(403, "out_of_scope")

    if payload.token_kind == "module_admin":  # noqa: S105 - token type discriminator, not a secret
        if payload.target_module_id is None or not payload.target_module_id.strip():
            return _json_error(422, "target_module_id_required")
        admin_token = mint_module_jwt(
            payload.target_module_id.strip(), seller_id=payload.seller_id, ttl_s=payload.ttl_s
        )
        await _insert_issue_audit(
            db=db,
            module_id=claims.module_id,
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
        module_id=claims.module_id,
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
