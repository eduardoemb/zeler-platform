from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx
import structlog

logger = structlog.get_logger(__name__)
_RANDOM = random.SystemRandom()

RETRYABLE_EXCEPTIONS = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.ReadError,
)


async def send_with_retry(
    client: httpx.AsyncClient,
    request: httpx.Request,
    *,
    max_attempts: int = 3,
    base_delay_s: float = 0.5,
    backoff_factor: float = 2.0,
    jitter: float = 0.25,
    retry_after_budget_s: float = 30.0,
    sleep_fn: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> httpx.Response:
    attempts = max(1, max_attempts)
    retry_after_waited_s = 0.0
    last_error: httpx.TimeoutException | httpx.ConnectError | httpx.ReadError | None = None

    for attempt in range(1, attempts + 1):
        try:
            response = await client.send(_clone_request(request))
        except RETRYABLE_EXCEPTIONS as exc:
            last_error = exc
            if attempt >= attempts:
                raise
            sleep_s = _backoff_sleep_s(
                attempt=attempt,
                base_delay_s=base_delay_s,
                backoff_factor=backoff_factor,
                jitter=jitter,
            )
            logger.info(
                "proxy.retry",
                attempt=attempt,
                status_or_error=exc.__class__.__name__,
                sleep_s=sleep_s,
            )
            await sleep_fn(sleep_s)
            continue

        if not _should_retry_response(response):
            return response

        if attempt >= attempts:
            return response

        sleep_s = _retry_sleep_s(
            response=response,
            attempt=attempt,
            base_delay_s=base_delay_s,
            backoff_factor=backoff_factor,
            jitter=jitter,
        )
        if response.status_code == 429:
            if retry_after_waited_s + sleep_s > retry_after_budget_s:
                return response
            retry_after_waited_s += sleep_s

        logger.info(
            "proxy.retry",
            attempt=attempt,
            status_or_error=response.status_code,
            sleep_s=sleep_s,
        )
        await sleep_fn(sleep_s)

    if last_error is not None:
        raise last_error
    msg = "send_with_retry exited without response"
    raise RuntimeError(msg)


def _clone_request(request: httpx.Request) -> httpx.Request:
    return httpx.Request(
        request.method,
        request.url,
        headers=request.headers,
        content=request.content,
        extensions=request.extensions.copy(),
    )


def _should_retry_response(response: httpx.Response) -> bool:
    return response.status_code == 429 or 500 <= response.status_code <= 599


def _retry_sleep_s(
    *,
    response: httpx.Response,
    attempt: int,
    base_delay_s: float,
    backoff_factor: float,
    jitter: float,
) -> float:
    if response.status_code == 429:
        retry_after = _parse_retry_after(response.headers.get("Retry-After"))
        if retry_after is not None:
            return retry_after

    return _backoff_sleep_s(
        attempt=attempt,
        base_delay_s=base_delay_s,
        backoff_factor=backoff_factor,
        jitter=jitter,
    )


def _parse_retry_after(value: str | None) -> float | None:
    if value is None:
        return None

    stripped = value.strip()
    if stripped.isdecimal():
        return float(stripped)

    try:
        retry_at = parsedate_to_datetime(stripped)
    except (TypeError, ValueError):
        return None

    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)
    return max(0.0, (retry_at - datetime.now(UTC)).total_seconds())


def _backoff_sleep_s(
    *,
    attempt: int,
    base_delay_s: float,
    backoff_factor: float,
    jitter: float,
) -> float:
    delay = base_delay_s * (backoff_factor ** (attempt - 1))
    jitter_amount = delay * jitter
    return _RANDOM.uniform(delay - jitter_amount, delay + jitter_amount)
