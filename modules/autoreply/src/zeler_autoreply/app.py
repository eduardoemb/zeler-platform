from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from zeler_platform_core.runtime.health import HealthCheck, build_health_router
from zeler_platform_core.runtime.manifest import validate_manifest
from zeler_platform_core.runtime.registration import register_module


def build_app(*, mongo_db: object) -> FastAPI:
    app = FastAPI(title="zeler-autoreply")
    app.state.mongo_db = mongo_db
    manifest = validate_manifest(Path(__file__).resolve().parents[2] / "manifest.yaml")

    async def mongo_check() -> tuple[bool, str]:
        return True, "connected"

    app.include_router(
        build_health_router(
            manifest.name,
            checks=[HealthCheck(name="mongo", check=mongo_check)],
        )
    )

    async def register_startup() -> None:
        await register_module(manifest, mongo_db)

    app.router.on_startup.append(register_startup)
    return app
