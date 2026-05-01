from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from zeler_gateway.config import Settings
from zeler_gateway.oauth.events import emit_accounts_linked
from zeler_gateway.tokens.encryption import encrypt_token

router = APIRouter(prefix="/oauth", tags=["oauth"])

MELI_AUTHORIZE_URL = "https://auth.mercadolibre.com/authorization"
MELI_TOKEN_URL = "https://api.mercadolibre.com/oauth/token"  # noqa: S105 - OAuth endpoint URL
APP_ID = "zeler-platform"


@router.get("/authorize")
async def authorize(request: Request, platform_user_id: str = Query(...)) -> RedirectResponse:
    settings = Settings()
    normalized_platform_user_id = platform_user_id.strip()
    if not normalized_platform_user_id:
        raise HTTPException(status_code=400, detail="platform_user_id is required")

    state = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)
    await request.app.state.mongo_db["meli_oauth_state"].insert_one(
        {
            "_id": state,
            "platform_user_id": normalized_platform_user_id,
            "code_verifier": code_verifier,
            "created_at": datetime.now(UTC),
        }
    )
    params = {
        "client_id": settings.meli_client_id,
        "redirect_uri": settings.meli_redirect_uri,
        "response_type": "code",
        "code_challenge": _pkce_challenge(code_verifier),
        "code_challenge_method": "S256",
        "state": state,
    }
    return RedirectResponse(url=f"{MELI_AUTHORIZE_URL}?{urlencode(params)}", status_code=302)


def _pkce_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


@router.get("/callback")
async def callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
) -> Response:
    settings = Settings()
    state_doc = await request.app.state.mongo_db["meli_oauth_state"].find_one_and_delete(
        {"_id": state}
    )
    if state_doc is None:
        return JSONResponse(status_code=400, content={"error": "invalid_state"})

    code_verifier = str(state_doc["code_verifier"])
    platform_user_id = str(state_doc["platform_user_id"])
    token_payload = await _exchange_authorization_code(
        code,
        code_verifier=code_verifier,
        settings=settings,
    )
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
        "platform_user_id": platform_user_id,
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
        "schema_version": 1,
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
    amqp_publisher = getattr(request.app.state, "amqp_publisher", None)
    if amqp_publisher is not None:
        await emit_accounts_linked(
            str(seller_id),
            platform_user_id,
            mongo_db=request.app.state.mongo_db,
            amqp_publisher=amqp_publisher,
        )
    return RedirectResponse(url=settings.oauth_success_url, status_code=302)


async def _exchange_authorization_code(
    code: str, *, code_verifier: str, settings: Settings
) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                MELI_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "client_id": settings.meli_client_id,
                    "client_secret": settings.meli_client_secret.get_secret_value(),
                    "code": code,
                    "code_verifier": code_verifier,
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
