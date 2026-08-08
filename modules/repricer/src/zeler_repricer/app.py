from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI

from zeler_platform_core.runtime.checks import mongo_check_factory, rabbitmq_check_factory
from zeler_platform_core.runtime.health import HealthCheck, build_health_router
from zeler_platform_core.runtime.manifest import validate_manifest
from zeler_platform_core.runtime.registration import register_module, registration_matches_manifest
from zeler_repricer.api import build_router


def build_app(
    *,
    mongo_db: object,
    rabbitmq_url: str | None = None,
    rabbitmq_connect: Callable[..., Awaitable[Any]] | None = None,
) -> FastAPI:
    app = FastAPI(title="zeler-repricer")
    app.state.mongo_db = mongo_db
    manifest = validate_manifest(Path(__file__).resolve().parents[2] / "manifest.yaml")

    mongo_check = mongo_check_factory(mongo_db)
    rabbitmq_check = rabbitmq_check_factory(
        lambda: rabbitmq_url,
        timeout_seconds=5.0,
        connect=rabbitmq_connect,
    )

    async def registry_check() -> tuple[bool, str]:
        try:
            database = cast(Any, mongo_db)
            document = await database["module_registry"].find_one({"_id": manifest.module_id})
        except Exception:  # noqa: BLE001 - health must fail closed on registry read errors.
            return False, "registry_fingerprint_unavailable"
        if not registration_matches_manifest(document=document, manifest=manifest):
            return False, "registry_fingerprint_mismatch"
        return True, "registry_fingerprint_match"

    app.include_router(build_router())
    app.include_router(
        build_health_router(
            manifest.name,
            checks=[
                HealthCheck(name="mongo", check=mongo_check),
                HealthCheck(name="rabbitmq", check=rabbitmq_check),
                HealthCheck(name="registry", check=registry_check),
            ],
        )
    )

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
    return build_app(mongo_db=mongo_db, rabbitmq_url=os.environ.get("RABBITMQ_URL"))
