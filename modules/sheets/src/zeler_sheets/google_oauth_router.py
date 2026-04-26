from __future__ import annotations

import base64
import hashlib
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, RedirectResponse

from zeler_sheets.google_token_encryption import KmsClient
from zeler_sheets.google_token_store import GoogleTokenStore
from zeler_sheets.sheets_config import SheetsSettings, get_settings


def build_router() -> APIRouter:
    router = APIRouter(prefix="/oauth/google", tags=["google-oauth"])

    @router.get("/authorize")
    async def authorize(request: Request, seller_id: str) -> RedirectResponse:
        normalized_seller_id = seller_id.strip()
        if not normalized_seller_id:
            raise HTTPException(status_code=400, detail="seller_id is required")

        settings = _settings(request)
        now = _now(request)
        state_token = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(64)
        await _db(request)["google_oauth_state"].insert_one(
            {
                "_id": state_token,
                "seller_id": normalized_seller_id,
                "code_verifier": code_verifier,
                "created_at": now,
            }
        )

        params = {
            "client_id": settings.google_oauth_client_id,
            "redirect_uri": settings.google_oauth_redirect_uri,
            "response_type": "code",
            "scope": settings.google_sheets_scope,
            "code_challenge": _pkce_challenge(code_verifier),
            "code_challenge_method": "S256",
            "state": state_token,
            "access_type": "offline",
            "prompt": "consent",
        }
        return RedirectResponse(
            f"{settings.google_oauth_authorize_url}?{urlencode(params)}",
            status_code=302,
        )

    @router.get("/callback")
    async def callback(request: Request, code: str, state: str) -> JSONResponse:
        db = _db(request)
        state_doc = await db["google_oauth_state"].find_one_and_delete({"_id": state})
        if state_doc is None:
            return JSONResponse(status_code=400, content={"error": "invalid_state"})

        settings = _settings(request)
        seller_id = str(state_doc["seller_id"])
        async with _http_client_factory(request)() as client:
            token_response = await client.post(
                settings.google_oauth_token_url,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "code_verifier": str(state_doc["code_verifier"]),
                    "client_id": settings.google_oauth_client_id,
                    "client_secret": settings.google_oauth_client_secret.get_secret_value(),
                    "redirect_uri": settings.google_oauth_redirect_uri,
                },
            )

        if token_response.status_code >= 400:
            payload = _safe_json(token_response)
            return JSONResponse(
                status_code=400,
                content={"error": str(payload.get("error") or "google_token_exchange_failed")},
            )

        payload = cast(dict[str, Any], token_response.json())
        expires_at = _now(request) + timedelta(seconds=int(payload["expires_in"]))
        token_store = GoogleTokenStore(
            db=db,
            kms_client=_kms_client(request),
            http_client_factory=_http_client_factory(request),
            settings=settings,
            now_fn=lambda: _now(request),
        )
        try:
            await token_store.store_initial(
                seller_id,
                access_token=str(payload["access_token"]),
                refresh_token=(
                    str(payload["refresh_token"])
                    if payload.get("refresh_token") is not None
                    else None
                ),
                expires_at=expires_at,
                scopes=[settings.google_sheets_scope],
            )
        except ValueError:
            return JSONResponse(status_code=400, content={"error": "consent_required"})

        return JSONResponse(
            jsonable_encoder(
                {"status": "connected", "seller_id": seller_id, "expires_at": expires_at}
            )
        )

    return router


def _pkce_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _db(request: Request) -> Any:
    return request.app.state.mongo_db


def _settings(request: Request) -> SheetsSettings:
    settings = getattr(request.app.state, "settings", None)
    if isinstance(settings, SheetsSettings):
        return settings
    return get_settings()


def _kms_client(request: Request) -> KmsClient:
    return cast(KmsClient, request.app.state.kms_client)


def _http_client_factory(request: Request) -> Callable[[], httpx.AsyncClient]:
    return cast(Callable[[], httpx.AsyncClient], request.app.state.http_client_factory)


def _now(request: Request) -> datetime:
    now_fn = getattr(request.app.state, "now_fn", None)
    if callable(now_fn):
        return cast(datetime, now_fn())
    return datetime.now(UTC)


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {}
    if isinstance(payload, dict):
        return cast(dict[str, Any], payload)
    return {}
