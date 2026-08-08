"""Bounded request correlation and sanitized internal-error handling."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from uuid import uuid4

import structlog
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.responses import Response

SERVICE_NAME = "zeler-meli-gateway"
REQUEST_ID_HEADER = "X-Request-Id"
ERROR_CLASS_UNKNOWN = "unknown"
REQUEST_CLASS_OK = "ok"
REQUEST_CLASS_CLIENT_ERROR = "client_error"
REQUEST_CLASS_SERVER_ERROR = "server_error"

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")

logger = structlog.get_logger(__name__)


def normalize_request_id(raw: str | None) -> str:
    """Accept a bounded inbound request id, otherwise generate one."""
    if raw is not None and _REQUEST_ID_PATTERN.match(raw):
        return raw
    return uuid4().hex


def classify_request_class(status_code: int) -> str:
    """Map an HTTP status code to the bounded request_class taxonomy."""
    if 200 <= status_code < 400:
        return REQUEST_CLASS_OK
    if 400 <= status_code < 500:
        return REQUEST_CLASS_CLIENT_ERROR
    return REQUEST_CLASS_SERVER_ERROR


def request_log_entry(
    *,
    request_id: str,
    route: str,
    method: str,
    status_code: int,
    request_class: str,
    error_class: str | None,
) -> dict[str, str | int | None]:
    """Build the bounded classified log payload without request data."""
    return {
        "service": SERVICE_NAME,
        "request_id": request_id,
        "route": route,
        "method": method,
        "status_code": status_code,
        "request_class": request_class,
        "error_class": error_class,
    }


def _route_label(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str):
        return path
    return request.url.path


async def request_context_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Stamp ``X-Request-Id`` and emit one classified log line per request."""
    request_id = normalize_request_id(request.headers.get(REQUEST_ID_HEADER))
    request.state.request_id = request_id
    route = _route_label(request)
    method = request.method
    try:
        response = await call_next(request)
    except Exception as exc:
        logger.info(
            "http.request",
            **request_log_entry(
                request_id=request_id,
                route=route,
                method=method,
                status_code=500,
                request_class=REQUEST_CLASS_SERVER_ERROR,
                error_class=type(exc).__name__,
            ),
        )
        raise
    response.headers[REQUEST_ID_HEADER] = request_id
    logger.info(
        "http.request",
        **request_log_entry(
            request_id=request_id,
            route=route,
            method=method,
            status_code=response.status_code,
            request_class=classify_request_class(response.status_code),
            error_class=None,
        ),
    )
    return response


def internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return a sanitized 500 containing only the bounded request id."""
    del exc
    request_id = getattr(request.state, "request_id", None) or normalize_request_id(
        request.headers.get(REQUEST_ID_HEADER)
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal",
            "error_class": ERROR_CLASS_UNKNOWN,
            "request_id": request_id,
        },
        headers={REQUEST_ID_HEADER: request_id},
    )
