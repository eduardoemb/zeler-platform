from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import APIRouter

HealthCheckFn = Callable[[], Awaitable[tuple[bool, str]]]


@dataclass(frozen=True)
class HealthCheck:
    name: str
    check: HealthCheckFn


def build_health_router(module_id: str, checks: list[HealthCheck]) -> APIRouter:
    router = APIRouter(tags=[f"{module_id}-health"])

    @router.get("/health")
    async def health() -> dict[str, object]:
        results: dict[str, dict[str, object]] = {}
        ready = True
        for health_check in checks:
            ok, detail = await health_check.check()
            ready = ready and ok
            results[health_check.name] = {"ok": ok, "detail": detail}
        return {"module_id": module_id, "ready": ready, "checks": results}

    return router
