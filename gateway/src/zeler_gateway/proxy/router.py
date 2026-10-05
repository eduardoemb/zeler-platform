from __future__ import annotations

import asyncio
import re
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
from pymongo import ReturnDocument
from pymongo.errors import PyMongoError

from zeler_gateway.config import Settings
from zeler_gateway.observability.metrics import (
    get_metrics_registry,
    record_latency,
    record_rate_limit_hit,
)
from zeler_gateway.proxy.rate_limit import RateLimitCounter, RateLimitExceeded
from zeler_gateway.proxy.retry import send_single_attempt, send_with_retry
from zeler_gateway.tokens.encryption import EncryptedToken, decrypt_token
from zeler_platform_core.auth.jwt import (
    ExpiredJWTError,
    InvalidJWTError,
    WrongAudienceError,
    verify_module_jwt,
)
from zeler_platform_core.history_onboarding import (
    PLAN_COLLECTION,
    POLICY_VERSION,
    history_execution_allowed,
    history_execution_query,
)

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["proxy"])

MELI_API_BASE = "https://api.mercadolibre.com"
REFRESH_RETRY_AFTER_SECONDS = 5


class HistoryPolicyRejectedError(Exception):
    """Authenticated historical request has no currently executable credit."""


class PilotGetBudgetWaitError(Exception):
    """Temporary opt-in pilot fence; never an upstream provider response."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


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
    "host",
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
    module = await db["module_registry"].find_one({"_id": claims.module_id})
    if module is None:
        return _json_error(401, "unknown_module")
    if module.get("status") != "enabled":
        return JSONResponse(
            status_code=412,
            content={"code": "module_disabled", "detail": f"module {claims.module_id} is disabled"},
        )

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
    if account_status == "paused":
        logger.info(
            "gateway.proxy.account_paused",
            seller_id=claims.seller_id,
            module_id=claims.module_id,
        )
        return JSONResponse(
            status_code=423,
            content={"code": "seller_paused"},
        )
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

    settings = Settings()
    counter = RateLimitCounter(db, default_limit=settings.gateway_proxy_rate_limit)
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

    request.state.history_module_id = claims.module_id
    request.state.history_seller_id = str(claims.seller_id)
    try:
        upstream_response = await _forward_to_meli(
            request=request,
            full_path=full_path,
            access_token=access_token,
        )
    except PilotGetBudgetWaitError as exc:
        await _write_audit_log(
            request=request,
            module_id=claims.module_id,
            seller_id=claims.seller_id,
            method=request.method,
            path=upstream_path,
            upstream_status=-1,
            response_status=429,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        return _json_error(
            429,
            exc.code,
            headers={
                "Retry-After": "5",
                "X-Zeler-Pilot-Get-Budget-Status": "wait",
                "X-Zeler-Upstream-Attempts": str(
                    getattr(request.state, "pilot_upstream_attempts", 0)
                ),
            },
        )
    except HistoryPolicyRejectedError:
        await _write_audit_log(
            request=request,
            module_id=claims.module_id,
            seller_id=claims.seller_id,
            method=request.method,
            path=upstream_path,
            upstream_status=-1,
            response_status=412,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        return _json_error(
            412,
            "history_policy_wait",
            headers={
                "X-Zeler-Upstream-Attempts": "0",
                "X-Zeler-History-Policy-Status": "wait",
            },
        )
    except httpx.RequestError:
        if getattr(request.state, "history_upstream_attempts", 0) == 1:
            await _write_audit_log(
                request=request,
                module_id=claims.module_id,
                seller_id=claims.seller_id,
                method=request.method,
                path=upstream_path,
                upstream_status=0,
                response_status=500,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        raise
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


def _history_trace(request: Request, module_id: str) -> str | None:
    value = request.headers.get("X-Zeler-History-Trace", "")
    if (
        module_id in {"bootstrap", "sheets"}
        and request.method == "GET"
        and request.headers.get("X-Zeler-Proxy-Retry") == "disabled"
        and re.fullmatch(
            r"h1-[a-f0-9]{32}:(?:orders|questions|shipments|messages|claims_returns):(?:initial|maintenance)",
            value,
        )
    ):
        return value
    return None


async def _write_audit_log(
    *,
    request: Request,
    module_id: str,
    seller_id: int,
    method: str,
    path: str,
    upstream_status: int,
    duration_ms: int,
    response_status: int | None = None,
) -> None:
    try:
        await request.app.state.mongo_db["audit_log"].insert_one(
            {
                "at": datetime.now(UTC),
                "module_id": module_id,
                "seller_id": Int64(seller_id),
                "method": method,
                "path": path,
                "status": upstream_status if response_status is None else response_status,
                "upstream_status": upstream_status,
                "duration_ms": duration_ms,
                "schema_version": 1,
                **(
                    {"trace_id": _history_trace(request, module_id)}
                    if _history_trace(request, module_id)
                    else {}
                ),
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
    normalized_path = path.split("?", 1)[0]
    if normalized_path.startswith("/post-purchase/v1/claims/") and normalized_path.endswith(
        "/detail"
    ):
        return False
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
    scope = settings.history_pilot_get_budget_sellers
    pilot_get = (
        request.method == "GET"
        and getattr(request.state, "history_module_id", "") == "sheets"
        and scope is not None
        and getattr(request.state, "history_seller_id", "") in scope
    )
    trace = _history_trace(request, getattr(request.state, "history_module_id", ""))
    if pilot_get and request.headers.get("X-Zeler-History-Trace") and trace is None:
        # A malformed/misconfigured historical request must not be charged again
        # as ordinary traffic or bypass its pre-reserved historical credit.
        raise PilotGetBudgetWaitError("pilot_execution_unavailable")

    async def before_attempt() -> None:
        await _reserve_pilot_get_send(request)

    async with factory() as client:
        upstream_request = client.build_request(
            request.method,
            url,
            content=body,
            params=list(request.query_params.multi_items()),
            headers=headers,
        )
        if request.headers.get("X-Zeler-Proxy-Retry") == "disabled":
            if pilot_get and trace is None:
                await before_attempt()
            else:
                await _reserve_history_send(request, full_path)
            return await send_single_attempt(client, upstream_request)
        sleep_fn = getattr(request.app.state, "proxy_retry_sleep", None)
        retry_kwargs: dict[str, Any] = {}
        if pilot_get:
            retry_kwargs["before_attempt"] = before_attempt
        if sleep_fn is None:
            return await send_with_retry(client, upstream_request, **retry_kwargs)
        return await send_with_retry(
            client,
            upstream_request,
            sleep_fn=cast(Any, sleep_fn),
            **retry_kwargs,
        )


def _pilot_plan_available(plan: Any, now: datetime) -> bool:
    return bool(
        isinstance(plan, dict)
        and plan.get("policy_version") == POLICY_VERSION
        and isinstance(plan.get("authority"), dict)
        and plan.get("authority", {}).get("kind") == "account_link_policy"
        and plan.get("state") == "active"
        and plan.get("eligible") is True
        and isinstance(plan.get("execution_id"), str)
        and re.fullmatch(r"[a-f0-9]{32}", plan["execution_id"])
        and isinstance(plan.get("execution_until"), datetime)
        and plan.get("execution_utc_day") == now.date().isoformat()
        and type(plan.get("execution_attempt_limit")) is int
        and plan["execution_attempt_limit"] >= 0
        and type(plan.get("execution_consumed")) is int
        and plan["execution_consumed"] >= 0
        and type(plan.get("execution_sent", 0)) is int
        and 0 <= plan.get("execution_sent", 0) <= plan["execution_consumed"]
        and history_execution_allowed(
            {
                "execution_until": plan["execution_until"],
                "execution_utc_day": plan["execution_utc_day"],
            },
            now=now,
        )
    )


async def _reserve_pilot_get_send(request: Request) -> None:
    """Charge ordinary physical GETs without consuming historical source credits.

    The authenticated caller/scope gate lives in _forward_to_meli. Reservations
    survive crashes and failed sends; no resets, refunds, source invention or
    subscription mutations. All retry attempts re-read and CAS at dispatch.
    """
    plans = request.app.state.mongo_db[PLAN_COLLECTION]
    seller = request.state.history_seller_id
    now = _proxy_wait_now(request)()
    plan = await plans.find_one({"_id": seller, "seller_id": seller})
    if not _pilot_plan_available(plan, now):
        raise PilotGetBudgetWaitError("pilot_execution_unavailable")
    execution = plan["execution_id"]
    previous_execution = getattr(request.state, "pilot_execution_id", execution)
    if previous_execution != execution:
        raise PilotGetBudgetWaitError("pilot_execution_unavailable")
    request.state.pilot_execution_id = execution
    if plan["execution_consumed"] >= plan["execution_attempt_limit"]:
        raise PilotGetBudgetWaitError("pilot_budget_exhausted")
    query = {
        "_id": seller,
        "seller_id": seller,
        "policy_version": POLICY_VERSION,
        "authority.kind": "account_link_policy",
        "state": "active",
        "eligible": True,
        "execution_id": execution,
        "execution_until": plan["execution_until"],
        "execution_utc_day": plan["execution_utc_day"],
        "execution_attempt_limit": plan["execution_attempt_limit"],
        "execution_consumed": {"$type": ["int", "long"], "$gte": 0},
        **history_execution_query(now),
    }
    query["$and"].append(
        {
            "$or": [
                {"execution_sent": {"$exists": False}},
                {"execution_sent": {"$type": ["int", "long"], "$gte": 0}},
            ]
        }
    )
    query["$and"].append(
        {"$expr": {"$lte": [{"$ifNull": ["$execution_sent", 0]}, "$execution_consumed"]}}
    )
    result = await plans.find_one_and_update(
        query,
        {"$inc": {"execution_consumed": 1, "execution_sent": 1}},
        return_document=ReturnDocument.AFTER,
    )
    if result is None or not history_execution_allowed(
        result, now=_proxy_wait_now(request)(), charged=True
    ):
        raise PilotGetBudgetWaitError("pilot_execution_unavailable")
    request.state.pilot_upstream_attempts = getattr(request.state, "pilot_upstream_attempts", 0) + 1


async def _reserve_history_send(request: Request, full_path: str) -> None:
    module = getattr(request.state, "history_module_id", "")
    trace = _history_trace(request, module)
    if trace is None:
        return
    execution, source, phase = trace[3:].split(":")
    path = "/" + full_path.lstrip("/").split("?", 1)[0]
    patterns = {
        "orders": r"/orders/(?:search|[0-9]+)",
        "questions": r"/questions/(?:search|[0-9]+)",
        "shipments": r"/shipments/[0-9]+(?:/costs|/payments)?",
        "messages": r"/messages/packs/[0-9]+/sellers/[0-9]+",
        "claims_returns": (
            r"/(?:orders/[0-9]+|post-purchase/v1/claims/(?:search|[0-9]+)|"
            r"post-purchase/v2/claims/[0-9]+/returns)"
        ),
    }
    if re.fullmatch(patterns[source], path) is None:
        raise HistoryPolicyRejectedError()
    credit = f"execution_charged.{execution}.{source}.{phase}"
    sent = f"execution_sent_by_source.{execution}.{source}.{phase}"
    query = {
        "_id": request.state.history_seller_id,
        "policy_version": POLICY_VERSION,
        "execution_id": execution,
        "state": "active",
        "eligible": True,
        "sources": source,
        **history_execution_query(_proxy_wait_now(request)(), charged=True),
    }
    query["$and"].append(
        {
            "$expr": {
                "$and": [
                    {"$lt": [{"$ifNull": ["$execution_sent", 0]}, "$execution_consumed"]},
                    {"$lt": [{"$ifNull": [f"${sent}", 0]}, {"$ifNull": [f"${credit}", 0]}]},
                ]
            }
        }
    )
    result = await request.app.state.mongo_db[PLAN_COLLECTION].find_one_and_update(
        query,
        {"$inc": {"execution_sent": 1, sent: 1}},
        return_document=ReturnDocument.AFTER,
    )
    if result is None or not history_execution_allowed(
        result,
        now=_proxy_wait_now(request)(),
        charged=True,
    ):
        raise HistoryPolicyRejectedError()
    # The persisted reservation is conservative across crashes/deadline crossings.
    # Only this marker followed by send/audit demonstrates a transport invocation;
    # it cannot prove the remote provider received the request.
    request.state.history_upstream_attempts = 1


def _http_client_factory(request: Request) -> HttpClientFactory:
    factory = getattr(request.app.state, "proxy_http_client_factory", None)
    if factory is not None:
        return cast(HttpClientFactory, factory)
    return lambda: httpx.AsyncClient(timeout=30.0)


def _upstream_headers(request: Request, *, access_token: str) -> dict[str, str]:
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
        and not key.lower().startswith("x-forwarded-")
        and key.lower() not in {"x-zeler-history-trace", "x-zeler-proxy-retry"}
    }
    headers["Authorization"] = f"Bearer {access_token}"
    return headers


def _response_headers(response: httpx.Response) -> dict[str, str]:
    headers: dict[str, str] = {}
    content_type = response.headers.get("content-type")
    if content_type is not None:
        headers["Content-Type"] = content_type
    upstream_attempts = response.headers.get("X-Zeler-Upstream-Attempts")
    if upstream_attempts is not None:
        headers["X-Zeler-Upstream-Attempts"] = upstream_attempts
    missing_content = response.headers.get("X-Content-Missing")
    if missing_content is not None:
        headers["X-Content-Missing"] = missing_content
    return headers


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
