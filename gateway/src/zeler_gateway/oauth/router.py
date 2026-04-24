from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from zeler_gateway.config import Settings
from zeler_gateway.oauth.events import emit_accounts_linked
from zeler_gateway.oauth.state import mint_state_jwt, verify_state_jwt
from zeler_gateway.tokens.encryption import encrypt_token

router = APIRouter(prefix="/oauth", tags=["oauth"])

MELI_AUTHORIZE_URL = "https://auth.mercadolibre.com/authorization"
MELI_TOKEN_URL = "https://api.mercadolibre.com/oauth/token"  # noqa: S105 - OAuth endpoint URL
APP_ID = "zeler-platform"


@router.get("/authorize")
async def authorize(platform_user_id: str = Query(...)) -> RedirectResponse:
    settings = Settings()
    state = mint_state_jwt(platform_user_id, settings=settings)
    params = {
        "client_id": settings.meli_client_id,
        "redirect_uri": settings.meli_redirect_uri,
        "response_type": "code",
        "state": state,
    }
    return RedirectResponse(url=f"{MELI_AUTHORIZE_URL}?{urlencode(params)}", status_code=302)


@router.get("/callback")
async def callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
) -> RedirectResponse:
    settings = Settings()
    try:
        claims = verify_state_jwt(state, settings=settings)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=400, detail="invalid OAuth state") from exc

    token_payload = await _exchange_authorization_code(code, settings=settings)
    seller_id = int(token_payload["user_id"])
    now = datetime.now(UTC)
    expires_in = int(token_payload["expires_in"])
    scope = str(token_payload.get("scope", ""))

    access_enc = encrypt_token(str(token_payload["access_token"]), account_id=str(seller_id))
    refresh_enc = encrypt_token(str(token_payload["refresh_token"]), account_id=str(seller_id))

    # TODO(P1.x): fetch real nickname from GET /users/{user_id} once we have a settings toggle.
    doc_set = {
        "seller_id": seller_id,
        "nickname": f"seller_{seller_id}",
        "app_id": APP_ID,
        "platform_user_id": claims.platform_user_id,
        "access_token_ciphertext": access_enc.ciphertext,
        "access_token_dek_wrapped": access_enc.dek_wrapped,
        "refresh_token_ciphertext": refresh_enc.ciphertext,
        "refresh_token_dek_wrapped": refresh_enc.dek_wrapped,
        "token_nonce": access_enc.nonce,
        "refresh_token_nonce": refresh_enc.nonce,
        "scopes": scope.split(),
        "status": "active",
        "expires_at": now + timedelta(seconds=expires_in),
        "kms_key_version": access_enc.kms_key_version,
        "updated_at": now,
        "connected_at": now,
        "last_refreshed_at": now,
    }
    await request.app.state.mongo_db["meli_accounts"].update_one(
        {"seller_id": seller_id, "app_id": APP_ID},
        {"$set": doc_set, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    await emit_accounts_linked(seller_id=seller_id, platform_user_id=claims.platform_user_id)
    return RedirectResponse(url=settings.oauth_success_url, status_code=302)


async def _exchange_authorization_code(code: str, *, settings: Settings) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                MELI_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "client_id": settings.meli_client_id,
                    "client_secret": settings.meli_client_secret.get_secret_value(),
                    "code": code,
                    "redirect_uri": settings.meli_redirect_uri,
                },
            )
    except httpx.HTTPError as exc:
        # Network / transport failure reaching Meli is user-facing 400 from our callback
        # perspective: the auth code cannot be exchanged, no account should be linked.
        raise HTTPException(status_code=400, detail="OAuth code exchange failed") from exc

    if response.status_code >= 400:
        raise HTTPException(status_code=400, detail="OAuth code exchange failed")
    return cast(dict[str, Any], response.json())
