from __future__ import annotations

from collections.abc import Callable

from fastapi import Request
from fastapi.responses import JSONResponse

from zeler_platform_core.auth.jwt import (
    ExpiredJWTError,
    InvalidJWTError,
    ModuleClaims,
    WrongAudienceError,
    verify_module_jwt,
)

ModuleJwtVerifier = Callable[[str], ModuleClaims]


def authorize_module_admin(
    request: Request,
    *,
    expected_module_id: str,
    seller_id: str | int | None = None,
    verifier: ModuleJwtVerifier = verify_module_jwt,
) -> JSONResponse | None:
    auth_header = request.headers.get("Authorization")
    if auth_header is None or not auth_header.startswith("Bearer "):
        return JSONResponse(
            status_code=401,
            content={"error": "invalid_token", "detail": "missing bearer token"},
        )

    try:
        claims = verifier(auth_header.removeprefix("Bearer ").strip())
    except (InvalidJWTError, ExpiredJWTError, WrongAudienceError) as exc:
        return JSONResponse(status_code=401, content={"error": "invalid_token", "detail": str(exc)})

    forbidden_detail = _module_admin_forbidden_detail(
        claims,
        expected_module_id=expected_module_id,
        seller_id=seller_id,
    )
    if forbidden_detail is not None:
        return JSONResponse(
            status_code=403,
            content={"error": "forbidden", "detail": forbidden_detail},
        )
    return None


def _module_admin_forbidden_detail(
    claims: ModuleClaims,
    *,
    expected_module_id: str,
    seller_id: str | int | None,
) -> str | None:
    if claims.token_type != "module_admin":  # noqa: S105 - token type discriminator, not a secret
        return "JWT token_type must be module_admin"
    if claims.module_id != expected_module_id:
        return f"JWT module_id must be {expected_module_id}"
    required_scope = f"admin:{expected_module_id}"
    if required_scope not in (claims.scopes or []):
        return f"JWT scopes must include {required_scope}"
    if seller_id is not None and str(claims.seller_id) != str(seller_id):
        return "JWT seller_id must match request seller_id"
    return None
