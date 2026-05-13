from __future__ import annotations

import hashlib
import hmac
import inspect
import secrets
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, field_serializer

TOKEN_PREFIX = "zs_ext_"  # noqa: S105 - public token discriminator, not a secret
TOKEN_PREFIX_LENGTH = 18
SCHEMA_VERSION = 1
DEFAULT_FORMULA_SCOPES = ("formulas:execute",)


class SellerScope(BaseModel):
    seller_id: str
    nickname: str


class ExtensionTokenMetadata(BaseModel):
    id: str
    label: str
    token_prefix: str
    owner_user_id: str
    seller_scopes: list[SellerScope]
    formula_scopes: list[str]
    status: Literal["active", "revoked"]
    expires_at: datetime | None
    created_at: datetime
    rotated_at: datetime | None
    revoked_at: datetime | None
    last_used_at: datetime | None
    schema_version: int = SCHEMA_VERSION

    model_config = ConfigDict(from_attributes=True)

    @field_serializer(
        "expires_at",
        "created_at",
        "rotated_at",
        "revoked_at",
        "last_used_at",
        when_used="json",
    )
    def _serialize_datetime(self, value: datetime | None) -> str | None:
        return value.isoformat() if value is not None else None


class IssuedExtensionToken(BaseModel):
    metadata: ExtensionTokenMetadata
    token_once: str


class ExtensionTokenValidation(BaseModel):
    token_id: str
    seller_id: str
    seller_nickname: str
    formula_scopes: list[str]


class ExtensionTokenValidationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


AuditHook = Callable[[dict[str, Any]], Any | Awaitable[Any]]
RateLimitHook = Callable[[dict[str, Any]], bool | Awaitable[bool]]
TokenFactory = Callable[[], str]
Clock = Callable[[], datetime]


def hash_extension_token(token: str, *, token_pepper: str) -> str:
    return hmac.new(
        token_pepper.encode("utf-8"),
        token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


class ExtensionTokenService:
    def __init__(
        self,
        *,
        db: Any,
        token_pepper: str,
        now_fn: Clock | None = None,
        token_factory: TokenFactory | None = None,
        audit_hook: AuditHook | None = None,
        rate_limit_hook: RateLimitHook | None = None,
    ) -> None:
        self._collection = db["sheets_extension_tokens"]
        self._token_pepper = token_pepper
        self._now = now_fn or (lambda: datetime.now(UTC))
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self._audit_hook = audit_hook
        self._rate_limit_hook = rate_limit_hook

    async def create_token(
        self,
        *,
        owner_user_id: str,
        label: str,
        seller_scopes: list[SellerScope],
        formula_scopes: list[str] | None = None,
        expires_at: datetime | None = None,
    ) -> IssuedExtensionToken:
        now = self._now()
        token = self._new_token()
        token_id = _token_id(token)
        metadata = ExtensionTokenMetadata(
            id=token_id,
            label=label,
            token_prefix=token[:TOKEN_PREFIX_LENGTH],
            owner_user_id=owner_user_id,
            seller_scopes=seller_scopes,
            formula_scopes=formula_scopes or list(DEFAULT_FORMULA_SCOPES),
            status="active",
            expires_at=expires_at,
            created_at=now,
            rotated_at=None,
            revoked_at=None,
            last_used_at=None,
            schema_version=SCHEMA_VERSION,
        )
        doc = _metadata_to_doc(metadata)
        doc["token_hash"] = hash_extension_token(token, token_pepper=self._token_pepper)
        doc["updated_at"] = now
        await self._collection.insert_one(doc)
        return IssuedExtensionToken(metadata=metadata, token_once=token)

    async def list_tokens(self, *, owner_user_id: str) -> list[ExtensionTokenMetadata]:
        docs = await self._collection.find({"owner_user_id": owner_user_id}).to_list(length=100)
        return [_metadata_from_doc(doc) for doc in docs]

    async def rotate_token(self, token_id: str, *, owner_user_id: str) -> IssuedExtensionToken:
        existing = await self._get_owned(token_id, owner_user_id=owner_user_id)
        now = self._now()
        await self._collection.update_one(
            {"_id": token_id, "owner_user_id": owner_user_id},
            {
                "$set": {
                    "status": "revoked",
                    "rotated_at": now,
                    "revoked_at": now,
                    "updated_at": now,
                }
            },
        )
        return await self.create_token(
            owner_user_id=owner_user_id,
            label=str(existing["label"]),
            seller_scopes=[SellerScope(**scope) for scope in existing["seller_scopes"]],
            formula_scopes=list(existing.get("formula_scopes") or DEFAULT_FORMULA_SCOPES),
            expires_at=existing.get("expires_at"),
        )

    async def revoke_token(self, token_id: str, *, owner_user_id: str) -> ExtensionTokenMetadata:
        await self._get_owned(token_id, owner_user_id=owner_user_id)
        now = self._now()
        await self._collection.update_one(
            {"_id": token_id, "owner_user_id": owner_user_id},
            {"$set": {"status": "revoked", "revoked_at": now, "updated_at": now}},
        )
        revoked = await self._get_owned(token_id, owner_user_id=owner_user_id)
        return _metadata_from_doc(revoked)

    async def validate_token(
        self,
        token: str,
        *,
        cuenta: str,
        formula: str,
        request_id: str | None = None,
    ) -> ExtensionTokenValidation:
        if not token:
            raise ExtensionTokenValidationError("TOKEN_MISSING", "missing extension token")

        doc = await self._collection.find_one(
            {"token_hash": hash_extension_token(token, token_pepper=self._token_pepper)}
        )
        if doc is None:
            raise ExtensionTokenValidationError("TOKEN_REVOKED", "extension token is not active")

        scope = _resolve_seller_scope(doc, cuenta)
        try:
            self._validate_active(doc)
            if scope is None:
                raise ExtensionTokenValidationError(
                    "SELLER_FORBIDDEN", "extension token cannot access seller"
                )
            await self._enforce_rate_limit(doc, scope, formula=formula, request_id=request_id)
        except ExtensionTokenValidationError as exc:
            await self._audit(
                doc,
                scope,
                formula=formula,
                request_id=request_id,
                outcome="denied",
                error_code=exc.code,
            )
            raise

        now = self._now()
        await self._collection.update_one(
            {"_id": doc["_id"]},
            {"$set": {"last_used_at": now, "updated_at": now}},
        )
        await self._audit(
            doc,
            scope,
            formula=formula,
            request_id=request_id,
            outcome="allowed",
            error_code=None,
        )
        return ExtensionTokenValidation(
            token_id=str(doc["_id"]),
            seller_id=scope.seller_id,
            seller_nickname=scope.nickname,
            formula_scopes=list(doc.get("formula_scopes") or DEFAULT_FORMULA_SCOPES),
        )

    async def _get_owned(self, token_id: str, *, owner_user_id: str) -> dict[str, Any]:
        doc = await self._collection.find_one({"_id": token_id, "owner_user_id": owner_user_id})
        if doc is None:
            raise KeyError(token_id)
        return cast("dict[str, Any]", doc)

    def _new_token(self) -> str:
        secret = self._token_factory()
        return secret if secret.startswith(TOKEN_PREFIX) else f"{TOKEN_PREFIX}{secret}"

    def _validate_active(self, doc: dict[str, Any]) -> None:
        if doc.get("status") != "active":
            raise ExtensionTokenValidationError("TOKEN_REVOKED", "extension token is revoked")
        expires_at = doc.get("expires_at")
        if expires_at is not None and expires_at <= self._now():
            raise ExtensionTokenValidationError("TOKEN_REVOKED", "extension token expired")

    async def _enforce_rate_limit(
        self,
        doc: dict[str, Any],
        scope: SellerScope,
        *,
        formula: str,
        request_id: str | None,
    ) -> None:
        if self._rate_limit_hook is None:
            return
        allowed = self._rate_limit_hook(
            {
                "token_id": str(doc["_id"]),
                "seller_id": scope.seller_id,
                "seller_nickname": scope.nickname,
                "formula": formula,
                "request_id": request_id,
            }
        )
        if inspect.isawaitable(allowed):
            allowed = await allowed
        if not allowed:
            raise ExtensionTokenValidationError("RATE_LIMITED", "extension token rate limited")

    async def _audit(
        self,
        doc: dict[str, Any],
        scope: SellerScope | None,
        *,
        formula: str,
        request_id: str | None,
        outcome: Literal["allowed", "denied"],
        error_code: str | None,
    ) -> None:
        if self._audit_hook is None:
            return
        result = self._audit_hook(
            {
                "token_id": str(doc["_id"]),
                "seller_id": scope.seller_id if scope else None,
                "seller_nickname": scope.nickname if scope else None,
                "formula": formula,
                "request_id": request_id,
                "outcome": outcome,
                "error_code": error_code,
                "occurred_at": self._now(),
            }
        )
        if inspect.isawaitable(result):
            await result


def _token_id(token: str) -> str:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:20]
    return f"sheets-ext-token-{digest}"


def _metadata_to_doc(metadata: ExtensionTokenMetadata) -> dict[str, Any]:
    doc = metadata.model_dump(mode="python")
    doc["_id"] = doc.pop("id")
    doc["seller_scopes"] = [scope.model_dump() for scope in metadata.seller_scopes]
    return doc


def _metadata_from_doc(doc: dict[str, Any]) -> ExtensionTokenMetadata:
    payload = dict(doc)
    payload["id"] = payload.pop("_id")
    payload.pop("token_hash", None)
    payload.pop("updated_at", None)
    return ExtensionTokenMetadata(**payload)


def _resolve_seller_scope(doc: dict[str, Any], cuenta: str) -> SellerScope | None:
    normalized = cuenta.casefold()
    for raw_scope in doc.get("seller_scopes", []):
        scope = SellerScope(**raw_scope)
        if scope.seller_id == cuenta or scope.nickname.casefold() == normalized:
            return scope
    return None
