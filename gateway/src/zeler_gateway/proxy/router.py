from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from fnmatch import fnmatchcase
from typing import Any, cast

import httpx
import structlog
from bson import Int64
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pymongo.errors import PyMongoError

from zeler_gateway.config import Settings
from zeler_gateway.observability.metrics import (
    get_metrics_registry,
    record_latency,
    record_rate_limit_hit,
)
from zeler_gateway.proxy.rate_limit import RateLimitCounter, RateLimitExceeded
from zeler_gateway.proxy.retry import send_with_retry
from zeler_gateway.tokens.encryption import EncryptedToken, decrypt_token
from zeler_platform_core.auth.jwt import (
    ExpiredJWTError,
    InvalidJWTError,
    WrongAudienceError,
    verify_module_jwt,
)

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["proxy"])

MELI_API_BASE = "https://api.mercadolibre.com"
REFRESH_RETRY_AFTER_SECONDS = 5
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "authorization",
}

HttpClientFactory = Callable[[], httpx.AsyncClient]
NowFn = Callable[[], datetime]
SleepFn = Callable[[float], Awaitable[None]]


@router.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_meli(request: Request, full_path: str) -> Response:
    started = time.perf_counter()
    auth_header = request.headers.get("Authorization")
    if auth_header is None or not auth_header.startswith("Bearer "):
        return _json_error(401, "invalid_token", detail="missing bearer token")

    token = auth_header.removeprefix("Bearer ").strip()
    try:
        claims = verify_module_jwt(token)
    except (InvalidJWTError, ExpiredJWTError, WrongAudienceError) as exc:
        return _json_error(401, "invalid_token", detail=str(exc))

    db = request.app.state.mongo_db
    module = await db["module_registry"].find_one({"_id": claims.module_id, "status": "enabled"})
    if module is None:
        return _json_error(401, "unknown_module")

    upstream_path = f"/{full_path}"
    if not _scope_matches(
        method=request.method,
        path=upstream_path,
        allowed_scopes=cast(list[str], module.get("allowed_meli_scopes", [])),
    ):
        return _json_error(403, "out_of_scope")

    account = await db["meli_accounts"].find_one({"seller_id": claims.seller_id})
    if account is None:
        return _json_error(412, "account_not_active")

    account_status = account.get("status")
    now_fn = _proxy_wait_now(request)
    if account_status == "refresh_pending" and _lock_is_held(
        account.get("lock_held_until"), now_fn=now_fn
    ):
        refreshed_account = await _wait_for_active_account(
            db,
            claims.seller_id,
            now_fn=now_fn,
            sleep_fn=_proxy_wait_sleep(request),
        )
        if refreshed_account is None:
            return _json_error(
                503,
                "token_refresh_timeout",
                headers={"Retry-After": str(REFRESH_RETRY_AFTER_SECONDS)},
            )
        account = refreshed_account
        account_status = account.get("status")
    if account_status != "active":
        return _json_error(412, "account_not_active")

    counter = RateLimitCounter(db)
    try:
        await counter.check_and_increment(module_id=claims.module_id, seller_id=claims.seller_id)
    except RateLimitExceeded as exc:
        logger.info(
            "rate_limit_exceeded",
            module_id=claims.module_id,
            seller_id=claims.seller_id,
        )
        record_rate_limit_hit(module_id=claims.module_id, endpoint=upstream_path)
        record_latency(module_id=claims.module_id, endpoint=upstream_path, started=started)
        return _json_error(
            429,
            "rate_limit_exceeded",
            headers={"Retry-After": str(int(exc.retry_after_s))},
        )

    access_token = await decrypt_token(
        EncryptedToken(
            ciphertext=cast(bytes, account["access_token_ciphertext"]),
            nonce=cast(bytes, account["token_nonce"]),
            dek_wrapped=cast(bytes, account["access_token_dek_wrapped"]),
            kms_key_version=cast(str, account["kms_key_version"]),
        ),
        account_id=str(claims.seller_id),
    )

    upstream_response = await _forward_to_meli(
        request=request,
        full_path=full_path,
        access_token=access_token,
    )
    duration_ms = int((time.perf_counter() - started) * 1000)
    await _write_audit_log(
        request=request,
        module_id=claims.module_id,
        seller_id=claims.seller_id,
        method=request.method,
        path=upstream_path,
        upstream_status=upstream_response.status_code,
        duration_ms=duration_ms,
    )
    logger.info(
        "proxy.call",
        module_id=claims.module_id,
        seller_id=claims.seller_id,
        method=request.method,
        path=upstream_path,
        upstream_status=upstream_response.status_code,
        duration_ms=duration_ms,
    )
    metrics_registry = get_metrics_registry()
    metrics_registry.increment_call_count(
        module_id=claims.module_id,
        endpoint=upstream_path,
        status_code=upstream_response.status_code,
    )
    metrics_registry.observe_latency_ms(
        module_id=claims.module_id,
        endpoint=upstream_path,
        value_ms=duration_ms,
    )

    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers=_response_headers(upstream_response),
        media_type=upstream_response.headers.get("content-type"),
    )


async def _write_audit_log(
    *,
    request: Request,
    module_id: str,
    seller_id: int,
    method: str,
    path: str,
    upstream_status: int,
    duration_ms: int,
) -> None:
    try:
        await request.app.state.mongo_db["audit_log"].insert_one(
            {
                "at": datetime.now(UTC),
                "module_id": module_id,
                "seller_id": Int64(seller_id),
                "method": method,
                "path": path,
                "status": upstream_status,
                "upstream_status": upstream_status,
                "duration_ms": duration_ms,
                "schema_version": 1,
            }
        )
    except PyMongoError as exc:
        logger.warning(
            "audit_log.write_failed",
            module_id=module_id,
            seller_id=seller_id,
            method=method,
            path=path,
            error=str(exc),
        )


def _scope_matches(*, method: str, path: str, allowed_scopes: list[str]) -> bool:
    requested = f"{method.upper()} {path}"
    return any(fnmatchcase(requested, scope) for scope in allowed_scopes)


async def _wait_for_active_account(
    db: Any,
    seller_id: int,
    *,
    timeout_s: float = 5.0,
    poll_interval_s: float = 0.2,
    now_fn: NowFn | None = None,
    sleep_fn: SleepFn = asyncio.sleep,
) -> dict[str, Any] | None:
    current_time = now_fn or _utcnow
    deadline = current_time().timestamp() + timeout_s
    while current_time().timestamp() < deadline:
        await sleep_fn(poll_interval_s)
        account = await db["meli_accounts"].find_one({"seller_id": seller_id})
        if account is None:
            return None
        if account.get("status") == "active" and not _lock_is_held(
            account.get("lock_held_until"), now_fn=current_time
        ):
            return cast(dict[str, Any], account)
    return None


def _lock_is_held(lock_held_until: Any, *, now_fn: NowFn | None = None) -> bool:
    if not isinstance(lock_held_until, datetime):
        return False
    lock_deadline = lock_held_until
    if lock_held_until.tzinfo is None:
        lock_deadline = lock_held_until.replace(tzinfo=UTC)
    current_time = now_fn or _utcnow
    return lock_deadline > current_time()


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _proxy_wait_now(request: Request) -> NowFn:
    now_fn = getattr(request.app.state, "proxy_wait_now", None)
    if now_fn is not None:
        return cast(NowFn, now_fn)
    return _utcnow


def _proxy_wait_sleep(request: Request) -> SleepFn:
    sleep_fn = getattr(request.app.state, "proxy_wait_sleep", None)
    if sleep_fn is not None:
        return cast(SleepFn, sleep_fn)
    return asyncio.sleep


async def _forward_to_meli(
    *, request: Request, full_path: str, access_token: str
) -> httpx.Response:
    settings = Settings()
    meli_api_base = getattr(settings, "meli_api_base", MELI_API_BASE)
    url = f"{meli_api_base.rstrip('/')}/{full_path.lstrip('/')}"
    body = await request.body()
    headers = _upstream_headers(request, access_token=access_token)
    factory = _http_client_factory(request)
    async with factory() as client:
        upstream_request = client.build_request(
            request.method,
            url,
            content=body,
            params=list(request.query_params.multi_items()),
            headers=headers,
        )
        sleep_fn = getattr(request.app.state, "proxy_retry_sleep", None)
        if sleep_fn is None:
            return await send_with_retry(client, upstream_request)
        return await send_with_retry(client, upstream_request, sleep_fn=cast(Any, sleep_fn))


def _http_client_factory(request: Request) -> HttpClientFactory:
    factory = getattr(request.app.state, "proxy_http_client_factory", None)
    if factory is not None:
        return cast(HttpClientFactory, factory)
    return lambda: httpx.AsyncClient(timeout=30.0)


def _upstream_headers(request: Request, *, access_token: str) -> dict[str, str]:
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS and not key.lower().startswith("x-forwarded-")
    }
    headers["Authorization"] = f"Bearer {access_token}"
    return headers


def _response_headers(response: httpx.Response) -> dict[str, str]:
    content_type = response.headers.get("content-type")
    if content_type is None:
        return {}
    return {"Content-Type": content_type}


def _json_error(
    status_code: int,
    error: str,
    *,
    detail: str | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, str] = {"error": error}
    if detail is not None:
        body["detail"] = detail
    return JSONResponse(status_code=status_code, content=body, headers=headers)
