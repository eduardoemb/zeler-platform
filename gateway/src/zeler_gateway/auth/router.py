from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, EmailStr
from pymongo.errors import DuplicateKeyError

# P1.15 stub only: this endpoint creates platform user records without
# authentication/session semantics. Full auth integration belongs to P5.

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    name: str
    auth_provider: Literal["local", "google", "meli", "internal"]


class RegisterResponse(BaseModel):
    id: str
    email: str
    name: str
    auth_provider: str


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=RegisterResponse,
)
async def register_user(payload: RegisterRequest, request: Request) -> RegisterResponse:
    now = datetime.now(UTC)
    user_id = ObjectId()
    document = {
        "_id": user_id,
        "email": str(payload.email),
        "name": payload.name,
        "auth_provider": payload.auth_provider,
        "created_at": now,
        "updated_at": now,
        "status": "active",
        "meli_account_ids": [],
        "roles": ["user"],
        "schema_version": 1,
    }

    try:
        await request.app.state.mongo_db["users"].insert_one(document)
    except DuplicateKeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="email already registered",
        ) from exc

    return RegisterResponse(
        id=str(user_id),
        email=str(payload.email),
        name=payload.name,
        auth_provider=payload.auth_provider,
    )
