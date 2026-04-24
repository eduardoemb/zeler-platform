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

    meli_accounts = request.app.state.mongo_db["meli_accounts"]
    account_filter = {"seller_id": seller_id, "app_id": APP_ID}

    # Spec §1 R1.1: `connected_at` semantics differ by existing account state:
    #   - first connect (no existing doc)     → connected_at = now (via $setOnInsert)
    #   - duplicate connect while active      → preserve existing connected_at
    #   - re-link from revoked/invalid        → connected_at = now (a new connection)
    existing = await meli_accounts.find_one(account_filter)
    is_relink_after_revocation = existing is not None and existing.get("status") in {
        "revoked",
        "invalid",
        "invalid_grant",
    }

    # TODO(P1.x): fetch real nickname from GET /users/{user_id} once we have a settings toggle.
    doc_set: dict[str, Any] = {
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
        "last_refreshed_at": now,
    }
    doc_set_on_insert: dict[str, Any] = {
        "created_at": now,
        "connected_at": now,
    }
    if is_relink_after_revocation:
        # A re-link materially creates a new connection; bump connected_at.
        doc_set["connected_at"] = now

    await meli_accounts.update_one(
        account_filter,
        {"$set": doc_set, "$setOnInsert": doc_set_on_insert},
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
