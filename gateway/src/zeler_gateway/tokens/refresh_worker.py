from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
import structlog
from cryptography.exceptions import InvalidTag
from pymongo import ReturnDocument

from zeler_gateway.config import Settings
from zeler_gateway.oauth.events import AmqpPublisher, emit_accounts_revoked
from zeler_gateway.observability.metrics import get_metrics_registry
from zeler_gateway.tokens.encryption import EncryptedToken, decrypt_token, encrypt_token

logger = structlog.get_logger(__name__)
DEFAULT_MELI_TOKEN_URL = "https://api.mercadolibre.com/oauth/token"  # noqa: S105


@dataclass(frozen=True)
class RefreshRunStats:
    attempted: int = 0
    succeeded: int = 0
    failed: int = 0
    revoked: int = 0
    skipped: int = 0

    def with_attempted(self) -> RefreshRunStats:
        return RefreshRunStats(
            attempted=self.attempted + 1,
            succeeded=self.succeeded,
            failed=self.failed,
            revoked=self.revoked,
            skipped=self.skipped,
        )

    def with_succeeded(self) -> RefreshRunStats:
        return RefreshRunStats(
            attempted=self.attempted,
            succeeded=self.succeeded + 1,
            failed=self.failed,
            revoked=self.revoked,
            skipped=self.skipped,
        )

    def with_failed(self) -> RefreshRunStats:
        return RefreshRunStats(
            attempted=self.attempted,
            succeeded=self.succeeded,
            failed=self.failed + 1,
            revoked=self.revoked,
            skipped=self.skipped,
        )

    def with_revoked(self) -> RefreshRunStats:
        return RefreshRunStats(
            attempted=self.attempted,
            succeeded=self.succeeded,
            failed=self.failed,
            revoked=self.revoked + 1,
            skipped=self.skipped,
        )

    def with_skipped(self) -> RefreshRunStats:
        return RefreshRunStats(
            attempted=self.attempted,
            succeeded=self.succeeded,
            failed=self.failed,
            revoked=self.revoked,
            skipped=self.skipped + 1,
        )


class InvalidGrantError(Exception):
    pass


class RefreshHTTPError(Exception):
    pass


async def refresh_once(
    db: Any,
    *,
    meli_token_url: str = DEFAULT_MELI_TOKEN_URL,
    meli_client_id: str | None = None,
    meli_client_secret: str | None = None,
    now_fn: Callable[[], datetime] | None = None,
    http_client_factory: Callable[[], httpx.AsyncClient] | None = None,
    lifecycle_publisher: AmqpPublisher | None = None,
) -> RefreshRunStats:
    """Run one pass of the token refresh worker across eligible Meli accounts."""
    now = (now_fn or (lambda: datetime.now(UTC)))()
    refresh_window = now + timedelta(minutes=15)
    lock_deadline = now + timedelta(seconds=120)
    stats = RefreshRunStats()

    settings = Settings()
    resolved_client_id = meli_client_id if meli_client_id is not None else settings.meli_client_id
    resolved_client_secret = (
        meli_client_secret
        if meli_client_secret is not None
        else settings.meli_client_secret.get_secret_value()
    )
    resolved_http_client_factory = http_client_factory or (lambda: httpx.AsyncClient(timeout=10.0))

    query = {
        "status": {"$in": ["active", "refresh_pending"]},
        "expires_at": {"$lt": refresh_window},
    }

    async for candidate in db.meli_accounts.find(query, {"_id": 1}):
        locked = await db.meli_accounts.find_one_and_update(
            {
                "_id": candidate["_id"],
                "$or": [
                    {"lock_held_until": None},
                    {"lock_held_until": {"$lt": now}},
                ],
            },
            {"$set": {"lock_held_until": lock_deadline, "status": "refresh_pending"}},
            return_document=ReturnDocument.AFTER,
        )
        if locked is None:
            stats = stats.with_skipped()
            continue

        stats = stats.with_attempted()
        try:
            new_tokens = await _call_meli_refresh(
                refresh_ciphertext=cast(bytes, locked["refresh_token_ciphertext"]),
                refresh_dek_wrapped=cast(bytes, locked["refresh_token_dek_wrapped"]),
                refresh_nonce=cast(bytes, locked["refresh_token_nonce"]),
                kms_key_version=cast(str, locked["kms_key_version"]),
                account_id=str(locked["seller_id"]),
                meli_token_url=meli_token_url,
                meli_client_id=resolved_client_id,
                meli_client_secret=resolved_client_secret,
                http_client_factory=resolved_http_client_factory,
            )
        except InvalidGrantError:
            await db.meli_accounts.update_one(
                {"_id": locked["_id"]},
                {"$set": {"status": "revoked", "lock_held_until": None, "updated_at": now}},
            )
            await emit_accounts_revoked(
                seller_id=int(locked["seller_id"]),
                platform_user_id=cast(str, locked["platform_user_id"]),
                amqp_publisher=lifecycle_publisher,
                clock=lambda: now,
            )
            stats = stats.with_revoked()
            metrics_registry = get_metrics_registry()
            metrics_registry.increment_refresh_failure()
            metrics_registry.increment_invalid_grant()
            continue
        except (
            httpx.HTTPError,
            RefreshHTTPError,
            InvalidTag,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            await db.meli_accounts.update_one(
                {"_id": locked["_id"]},
                {
                    "$set": {
                        "status": "error",
                        "last_error": str(exc)[:500],
                        "lock_held_until": None,
                        "updated_at": now,
                    }
                },
            )
            stats = stats.with_failed()
            get_metrics_registry().increment_refresh_failure()
            continue

        access_enc = encrypt_token(
            cast(str, new_tokens["access_token"]), account_id=str(locked["seller_id"])
        )
        refresh_enc = encrypt_token(
            cast(str, new_tokens["refresh_token"]), account_id=str(locked["seller_id"])
        )
        expires_at = now + timedelta(seconds=int(new_tokens["expires_in"]))
        await db.meli_accounts.update_one(
            {"_id": locked["_id"]},
            {
                "$set": {
                    "access_token_ciphertext": access_enc.ciphertext,
                    "access_token_dek_wrapped": access_enc.dek_wrapped,
                    "refresh_token_ciphertext": refresh_enc.ciphertext,
                    "refresh_token_dek_wrapped": refresh_enc.dek_wrapped,
                    "token_nonce": access_enc.nonce,
                    "refresh_token_nonce": refresh_enc.nonce,
                    "kms_key_version": access_enc.kms_key_version,
                    "expires_at": expires_at,
                    "status": "active",
                    "lock_held_until": None,
                    "last_refresh_at": now,
                    "last_refreshed_at": now,
                    "updated_at": now,
                }
            },
        )
        stats = stats.with_succeeded()
        get_metrics_registry().increment_refresh_success()

    logger.info("refresh.run", **asdict(stats))
    return stats


async def _call_meli_refresh(
    *,
    refresh_ciphertext: bytes,
    refresh_dek_wrapped: bytes,
    refresh_nonce: bytes,
    kms_key_version: str,
    account_id: str,
    meli_token_url: str,
    meli_client_id: str,
    meli_client_secret: str,
    http_client_factory: Callable[[], httpx.AsyncClient],
) -> dict[str, Any]:
    refresh_token = await decrypt_token(
        EncryptedToken(
            ciphertext=refresh_ciphertext,
            dek_wrapped=refresh_dek_wrapped,
            nonce=refresh_nonce,
            kms_key_version=kms_key_version,
        ),
        account_id=account_id,
    )
    async with http_client_factory() as client:
        response = await client.post(
            meli_token_url,
            data={
                "grant_type": "refresh_token",
                "client_id": meli_client_id,
                "client_secret": meli_client_secret,
                "refresh_token": refresh_token,
            },
        )

    if response.status_code >= 400:
        payload = _safe_json(response)
        if 400 <= response.status_code < 500 and payload.get("error") == "invalid_grant":
            raise InvalidGrantError
        raise RefreshHTTPError(f"Meli refresh failed with status {response.status_code}")

    return cast(dict[str, Any], response.json())


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {}
    if isinstance(payload, dict):
        return cast(dict[str, Any], payload)
    return {}
