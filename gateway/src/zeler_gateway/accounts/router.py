from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api", tags=["accounts"])

_ACCOUNT_PROJECTION = {
    "access_token_ciphertext": 0,
    "access_token_dek_wrapped": 0,
    "refresh_token_ciphertext": 0,
    "refresh_token_dek_wrapped": 0,
    "token_nonce": 0,
    "refresh_token_nonce": 0,
    "kms_key_version": 0,
}


@router.get("/accounts")
async def list_accounts(request: Request, user_id: str = Query(..., min_length=1)) -> JSONResponse:
    cursor = request.app.state.mongo_db["meli_accounts"].find(
        {"platform_user_id": user_id},
        _ACCOUNT_PROJECTION,
    )
    documents = await cursor.sort("connected_at", -1).to_list(length=100)

    return JSONResponse(
        {
            "accounts": [_serialize_account(document) for document in documents],
        }
    )


def _serialize_account(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "seller_id": int(document["seller_id"]),
        "nickname": str(document.get("nickname", "")),
        "status": str(document.get("status", "error")),
        "connected_at": _format_datetime(document.get("connected_at")),
        "last_refreshed_at": _format_datetime(document.get("last_refreshed_at")),
    }


def _format_datetime(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        return str(value)

    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.astimezone(UTC).isoformat().replace("+00:00", "Z")
