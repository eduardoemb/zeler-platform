from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

HealthCheckResult = tuple[bool, str]
HealthCheckCoroutine = Callable[[], Awaitable[HealthCheckResult]]


def mongo_check_factory(
    motor_client: Any,
    *,
    ttl_seconds: float = 5,
    timeout_seconds: float = 5,
    clock: Callable[[], float] | None = None,
) -> HealthCheckCoroutine:
    now = clock or time.monotonic
    last_at: float | None = None
    last_result: HealthCheckResult | None = None
    lock = asyncio.Lock()

    async def mongo_check() -> HealthCheckResult:
        nonlocal last_at, last_result
        current = now()
        if last_at is not None and last_result is not None and current - last_at < ttl_seconds:
            return last_result
        async with lock:
            current = now()
            if last_at is not None and last_result is not None and current - last_at < ttl_seconds:
                return last_result
            try:
                command_owner = getattr(motor_client, "admin", motor_client)
                if not hasattr(command_owner, "command"):
                    fallback_result = (True, "connected")
                    last_at = current
                    last_result = fallback_result
                    return fallback_result
                await asyncio.wait_for(command_owner.command("ping"), timeout=timeout_seconds)
                result: HealthCheckResult = (True, "mongo_ok")
            except Exception as exc:  # noqa: BLE001 - health probes must never raise.
                result = (False, f"mongo_unreachable: {exc}")
            last_at = current
            last_result = result
            return result

    return mongo_check
