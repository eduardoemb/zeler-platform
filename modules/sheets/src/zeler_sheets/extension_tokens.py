from __future__ import annotations

import hashlib
import hmac
import inspect
import secrets
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, field_serializer

from zeler_sheets.extension_token_encryption import (
    TOKEN_SECRET_FIELDS,
    ExtensionTokenSecretCipher,
)

TOKEN_PREFIX = "zs_ext_"  # noqa: S105 - public token discriminator, not a secret
TOKEN_PREFIX_LENGTH = 18
SCHEMA_VERSION = 1
DEFAULT_FORMULA_SCOPES = ("formulas:execute",)
TOKEN_NOT_FOUND_OR_FORBIDDEN = "TOKEN_NOT_FOUND_OR_FORBIDDEN"  # noqa: S105 - error code.
TOKEN_NOT_ACTIVE = "TOKEN_NOT_ACTIVE"  # noqa: S105 - error code.
TOKEN_NOT_REVOKED = "TOKEN_NOT_REVOKED"  # noqa: S105 - error code.
TOKEN_DELETED = "TOKEN_DELETED"  # noqa: S105 - error code.
TOKEN_EXPIRED = "TOKEN_EXPIRED"  # noqa: S105 - error code.
TOKEN_SECRET_UNAVAILABLE = "TOKEN_SECRET_UNAVAILABLE"  # noqa: S105 - error code.
LIFECYCLE_ERROR_MESSAGES = {
    TOKEN_NOT_FOUND_OR_FORBIDDEN: "extension token not found or forbidden",
    TOKEN_NOT_ACTIVE: "extension token is not active",
    TOKEN_NOT_REVOKED: "extension token must be revoked before delete",
    TOKEN_DELETED: "extension token is deleted",
    TOKEN_EXPIRED: "extension token expired",
    TOKEN_SECRET_UNAVAILABLE: "extension token secret is unavailable",
}
METADATA_EXCLUDED_FIELDS = TOKEN_SECRET_FIELDS | {"token_hash", "updated_at", "deleted_at"}


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
        secret_cipher: ExtensionTokenSecretCipher | None = None,
    ) -> None:
        self._collection = db["sheets_extension_tokens"]
        self._token_pepper = token_pepper
        self._now = now_fn or (lambda: datetime.now(UTC))
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self._audit_hook = audit_hook
        self._rate_limit_hook = rate_limit_hook
        self._secret_cipher = secret_cipher

    async def create_token(
        self,
        *,
        owner_user_id: str,
        label: str,
        seller_scopes: list[SellerScope],
        formula_scopes: list[str] | None = None,
        expires_at: datetime | None = None,
    ) -> IssuedExtensionToken:
        _validate_seller_scopes(seller_scopes)
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
        if self._secret_cipher is not None:
            doc.update(
                self._secret_cipher.encrypt(
                    token,
                    owner_user_id=owner_user_id,
                    token_id=token_id,
                )
            )
        doc["updated_at"] = now
        await self._collection.insert_one(doc)
        return IssuedExtensionToken(metadata=metadata, token_once=token)

    async def list_tokens(
        self,
        *,
        owner_user_id: str,
        allowed_seller_ids: set[str] | None = None,
    ) -> list[ExtensionTokenMetadata]:
        docs = await self._collection.find(
            {"owner_user_id": owner_user_id, "deleted_at": None}
        ).to_list(length=100)
        return [
            _metadata_from_doc(doc)
            for doc in docs
            if _seller_scope_allowed(doc, allowed_seller_ids)
        ]

    async def rotate_token(
        self,
        token_id: str,
        *,
        owner_user_id: str,
        allowed_seller_ids: set[str] | None = None,
    ) -> IssuedExtensionToken:
        existing = await self._get_manageable(
            token_id,
            owner_user_id=owner_user_id,
            allowed_seller_ids=allowed_seller_ids,
        )
        _ensure_not_deleted(existing)
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

    async def reveal_token(
        self,
        token_id: str,
        *,
        owner_user_id: str,
        allowed_seller_ids: set[str] | None = None,
    ) -> IssuedExtensionToken:
        doc = await self._get_manageable(
            token_id,
            owner_user_id=owner_user_id,
            allowed_seller_ids=allowed_seller_ids,
        )
        self._validate_revealable(doc)
        if self._secret_cipher is None or not _has_recoverable_secret(doc):
            raise _lifecycle_error(TOKEN_SECRET_UNAVAILABLE)
        try:
            token = await self._secret_cipher.decrypt(
                doc,
                owner_user_id=owner_user_id,
                token_id=token_id,
            )
        except Exception as exc:  # noqa: BLE001 - reveal must fail closed without leaking internals.
            raise _lifecycle_error(TOKEN_SECRET_UNAVAILABLE) from exc
        if doc.get("token_hash") != hash_extension_token(token, token_pepper=self._token_pepper):
            raise _lifecycle_error(TOKEN_SECRET_UNAVAILABLE)
        if doc.get("token_prefix") != token[:TOKEN_PREFIX_LENGTH]:
            raise _lifecycle_error(TOKEN_SECRET_UNAVAILABLE)
        return IssuedExtensionToken(metadata=_metadata_from_doc(doc), token_once=token)

    async def revoke_token(
        self,
        token_id: str,
        *,
        owner_user_id: str,
        allowed_seller_ids: set[str] | None = None,
    ) -> ExtensionTokenMetadata:
        existing = await self._get_manageable(
            token_id,
            owner_user_id=owner_user_id,
            allowed_seller_ids=allowed_seller_ids,
        )
        _ensure_not_deleted(existing)
        now = self._now()
        await self._collection.update_one(
            {"_id": token_id, "owner_user_id": owner_user_id},
            {"$set": {"status": "revoked", "revoked_at": now, "updated_at": now}},
        )
        revoked = await self._get_owned(token_id, owner_user_id=owner_user_id)
        return _metadata_from_doc(revoked)

    async def delete_token(
        self,
        token_id: str,
        *,
        owner_user_id: str,
        allowed_seller_ids: set[str] | None = None,
    ) -> ExtensionTokenMetadata:
        existing = await self._get_manageable(
            token_id,
            owner_user_id=owner_user_id,
            allowed_seller_ids=allowed_seller_ids,
        )
        _ensure_not_deleted(existing)
        if existing.get("status") != "revoked":
            raise _lifecycle_error(TOKEN_NOT_REVOKED)
        now = self._now()
        await self._collection.update_one(
            {"_id": token_id, "owner_user_id": owner_user_id},
            {"$set": {"deleted_at": now, "updated_at": now}},
        )
        deleted = dict(existing)
        deleted["deleted_at"] = now
        deleted["updated_at"] = now
        return _metadata_from_doc(deleted)

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

        scope: SellerScope | None = None
        try:
            self._validate_active(doc)
            scope = _resolve_seller_scope(doc, cuenta)
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

    async def _get_manageable(
        self,
        token_id: str,
        *,
        owner_user_id: str,
        allowed_seller_ids: set[str] | None,
    ) -> dict[str, Any]:
        try:
            doc = await self._get_owned(token_id, owner_user_id=owner_user_id)
        except KeyError as exc:
            raise _lifecycle_error(TOKEN_NOT_FOUND_OR_FORBIDDEN) from exc
        if not _seller_scope_allowed(doc, allowed_seller_ids):
            raise _lifecycle_error(TOKEN_NOT_FOUND_OR_FORBIDDEN)
        return doc

    def _new_token(self) -> str:
        secret = self._token_factory()
        return secret if secret.startswith(TOKEN_PREFIX) else f"{TOKEN_PREFIX}{secret}"

    def _validate_active(self, doc: dict[str, Any]) -> None:
        if doc.get("deleted_at") is not None:
            raise ExtensionTokenValidationError("TOKEN_REVOKED", "El token fue eliminado.")
        if doc.get("status") != "active":
            raise ExtensionTokenValidationError("TOKEN_REVOKED", "extension token is revoked")
        expires_at = doc.get("expires_at")
        if expires_at is not None and expires_at <= self._now():
            raise ExtensionTokenValidationError("TOKEN_REVOKED", "extension token expired")

    def _validate_revealable(self, doc: dict[str, Any]) -> None:
        if doc.get("deleted_at") is not None:
            raise _lifecycle_error(TOKEN_DELETED)
        if doc.get("status") != "active":
            raise _lifecycle_error(TOKEN_NOT_ACTIVE)
        expires_at = doc.get("expires_at")
        if expires_at is not None and expires_at <= self._now():
            raise _lifecycle_error(TOKEN_EXPIRED)

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
    payload = _metadata_payload(doc)
    payload["id"] = payload.pop("_id")
    return ExtensionTokenMetadata(**payload)


def _metadata_payload(doc: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in doc.items() if key not in METADATA_EXCLUDED_FIELDS}


def _has_recoverable_secret(doc: dict[str, Any]) -> bool:
    return all(doc.get(field) is not None for field in TOKEN_SECRET_FIELDS)


def _ensure_not_deleted(doc: dict[str, Any]) -> None:
    if doc.get("deleted_at") is not None:
        raise _lifecycle_error(TOKEN_DELETED)


def _lifecycle_error(code: str) -> ExtensionTokenValidationError:
    return ExtensionTokenValidationError(code, LIFECYCLE_ERROR_MESSAGES[code])


def _seller_scope_allowed(doc: dict[str, Any], allowed_seller_ids: set[str] | None) -> bool:
    if allowed_seller_ids is None:
        return True
    normalized = {str(seller_id) for seller_id in allowed_seller_ids}
    token_seller_ids = {
        str(scope["seller_id"])
        for scope in doc.get("seller_scopes", [])
        if scope.get("seller_id") is not None
    }
    return bool(token_seller_ids) and token_seller_ids.issubset(normalized)


def _resolve_seller_scope(doc: dict[str, Any], cuenta: str) -> SellerScope | None:
    requested = cuenta.strip()
    normalized = requested.casefold()
    scopes = [SellerScope(**raw_scope) for raw_scope in doc.get("seller_scopes", [])]
    seller_id_matches = [scope for scope in scopes if scope.seller_id == requested]
    if len(seller_id_matches) == 1:
        return seller_id_matches[0]
    if len(seller_id_matches) > 1:
        raise ExtensionTokenValidationError(
            "SELLER_FORBIDDEN", "extension token seller scope is ambiguous"
        )

    nickname_matches = [scope for scope in scopes if scope.nickname.casefold() == normalized]
    if len(nickname_matches) == 1:
        return nickname_matches[0]
    if len(nickname_matches) > 1:
        raise ExtensionTokenValidationError(
            "SELLER_FORBIDDEN", "extension token seller scope is ambiguous"
        )
    return None


def _validate_seller_scopes(seller_scopes: list[SellerScope]) -> None:
    if not seller_scopes:
        raise ExtensionTokenValidationError(
            "SELLER_SCOPE_INVALID", "extension token must include at least one seller scope"
        )

    seller_ids: set[str] = set()
    nicknames: set[str] = set()
    for scope in seller_scopes:
        seller_id = scope.seller_id.strip()
        nickname = scope.nickname.strip()
        if not seller_id or not nickname:
            raise ExtensionTokenValidationError(
                "SELLER_SCOPE_INVALID", "seller scopes must include seller_id and nickname"
            )
        normalized_seller_id = seller_id.casefold()
        normalized_nickname = nickname.casefold()
        if normalized_seller_id in seller_ids:
            raise ExtensionTokenValidationError(
                "SELLER_SCOPE_INVALID", "seller scopes must not contain duplicate seller_id values"
            )
        if normalized_nickname in nicknames:
            raise ExtensionTokenValidationError(
                "SELLER_SCOPE_INVALID", "seller scopes must not contain duplicate nicknames"
            )
        seller_ids.add(normalized_seller_id)
        nicknames.add(normalized_nickname)
