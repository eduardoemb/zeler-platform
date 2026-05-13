from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from zeler_autoreply.api import build_router
from zeler_platform_core.runtime.checks import mongo_check_factory
from zeler_platform_core.runtime.health import HealthCheck, build_health_router
from zeler_platform_core.runtime.manifest import validate_manifest
from zeler_platform_core.runtime.registration import register_module


def build_app(*, mongo_db: object) -> FastAPI:
    app = FastAPI(title="zeler-autoreply")
    app.state.mongo_db = mongo_db
    manifest = validate_manifest(Path(__file__).resolve().parents[2] / "manifest.yaml")

    mongo_check = mongo_check_factory(mongo_db)

    app.include_router(
        build_health_router(
            manifest.name,
            checks=[HealthCheck(name="mongo", check=mongo_check)],
        )
    )
    app.include_router(build_router())

    async def register_startup() -> None:
        await register_module(manifest, mongo_db)

    app.router.on_startup.append(register_startup)
    return app


def make_app() -> FastAPI:
    """No-arg factory for uvicorn --factory; resolves deps at call time."""
    import os

    from motor.motor_asyncio import AsyncIOMotorClient

    mongo_uri = os.environ.get("MONGO_URI")
    mongo_db_name = os.environ.get("MONGO_DB")
    if not mongo_uri:
        raise RuntimeError("MONGO_URI is required for API mode")
    if not mongo_db_name:
        raise RuntimeError("MONGO_DB is required for API mode")

    mongo_db: object = AsyncIOMotorClient(mongo_uri)[mongo_db_name]
    return build_app(mongo_db=mongo_db)
