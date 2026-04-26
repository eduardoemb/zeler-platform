from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI

from zeler_platform_core.runtime.health import HealthCheck, build_health_router
from zeler_platform_core.runtime.manifest import validate_manifest
from zeler_platform_core.runtime.registration import register_module
from zeler_sheets.api import build_router
from zeler_sheets.google_oauth_router import build_router as build_google_oauth_router
from zeler_sheets.sheets_config import SheetsSettings, get_settings


def build_app(
    *,
    mongo_db: object,
    rabbitmq_ready: Callable[[], bool],
    kms_client: Any | None = None,
    settings: SheetsSettings | None = None,
    http_client_factory: Callable[[], httpx.AsyncClient] | None = None,
) -> FastAPI:
    app = FastAPI(title="zeler-sheets")
    app.state.mongo_db = mongo_db
    if kms_client is not None:
        app.state.kms_client = kms_client
    if settings is not None:
        app.state.settings = settings
    app.state.http_client_factory = http_client_factory or (lambda: httpx.AsyncClient(timeout=10.0))
    manifest = validate_manifest(Path(__file__).resolve().parents[2] / "manifest.yaml")

    async def mongo_check() -> tuple[bool, str]:
        return True, "connected"

    async def rabbitmq_check() -> tuple[bool, str]:
        return (True, "connected") if rabbitmq_ready() else (False, "consumer_stalled")

    app.include_router(build_router())
    app.include_router(build_google_oauth_router())
    app.include_router(
        build_health_router(
            manifest.name,
            checks=[
                HealthCheck(name="mongo", check=mongo_check),
                HealthCheck(name="rabbitmq", check=rabbitmq_check),
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

    from google.cloud import kms
    from motor.motor_asyncio import AsyncIOMotorClient

    mongo_uri = os.environ.get("MONGO_URI")
    mongo_db_name = os.environ.get("MONGO_DB")
    if not mongo_uri:
        raise RuntimeError("MONGO_URI is required for API mode")
    if not mongo_db_name:
        raise RuntimeError("MONGO_DB is required for API mode")

    mongo_db: object = AsyncIOMotorClient(mongo_uri)[mongo_db_name]
    return build_app(
        mongo_db=mongo_db,
        rabbitmq_ready=lambda: True,
        kms_client=kms.KeyManagementServiceClient(),
        settings=get_settings(),
    )
