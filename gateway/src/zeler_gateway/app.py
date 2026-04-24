from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]
from fastapi import FastAPI
from motor.motor_asyncio import AsyncIOMotorClient

from zeler_gateway.accounts.router import router as accounts_router
from zeler_gateway.auth.router import router as auth_router
from zeler_gateway.bootstrap_jobs.router import router as bootstrap_jobs_router
from zeler_gateway.config import get_settings
from zeler_gateway.internal.router import router as internal_router
from zeler_gateway.oauth.router import router as oauth_router
from zeler_gateway.observability.logging import configure_logging
from zeler_gateway.observability.metrics import metrics_middleware
from zeler_gateway.observability.metrics import router as metrics_router
from zeler_gateway.observability.tracing import configure_tracing
from zeler_gateway.proxy.router import router as proxy_router
from zeler_gateway.tokens.refresh_worker import refresh_once
from zeler_gateway.webhooks.router import router as webhooks_router

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    get_settings.cache_clear()
    settings = get_settings()
    configure_logging(environment=settings.environment)
    if settings.otel_enabled and settings.environment != "test":
        configure_tracing(
            app,
            service_name="zeler-meli-gateway",
            environment=settings.environment,
            otel_enabled=settings.otel_enabled,
            gcp_project_id=settings.gcp_project_id,
        )
    app.state.mongo_client = AsyncIOMotorClient(
        settings.mongo_uri,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
        socketTimeoutMS=30000,
    )
    app.state.mongo_db = app.state.mongo_client[settings.mongo_db]
    app.state.scheduler = AsyncIOScheduler()

    async def _scheduled_refresh() -> None:
        try:
            await refresh_once(app.state.mongo_db)
        except Exception:
            logger.exception("refresh worker pass failed")

    app.state.scheduler.add_job(
        _scheduled_refresh,
        "interval",
        minutes=5,
        id="meli-token-refresh",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    app.state.scheduler.start()

    try:
        yield
    finally:
        app.state.scheduler.shutdown(wait=False)
        app.state.mongo_client.close()


app = FastAPI(title="zeler-meli-gateway", lifespan=lifespan)
app.middleware("http")(metrics_middleware)
app.include_router(accounts_router)
app.include_router(auth_router)
app.include_router(bootstrap_jobs_router)
app.include_router(internal_router)
app.include_router(metrics_router)
app.include_router(oauth_router)
app.include_router(proxy_router, prefix="/proxy/meli")
app.include_router(webhooks_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
