from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import aio_pika
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]
from fastapi import FastAPI
from motor.motor_asyncio import AsyncIOMotorClient

from zeler_gateway.accounts.router import router as accounts_router
from zeler_gateway.auth.router import router as auth_router
from zeler_gateway.bootstrap_jobs.router import router as bootstrap_jobs_router
from zeler_gateway.config import Settings, get_settings
from zeler_gateway.internal.router import router as internal_router
from zeler_gateway.oauth.router import router as oauth_router
from zeler_gateway.observability.logging import configure_logging
from zeler_gateway.observability.metrics import metrics_middleware
from zeler_gateway.observability.metrics import router as metrics_router
from zeler_gateway.observability.tracing import configure_tracing
from zeler_gateway.proxy.router import router as proxy_router
from zeler_gateway.routes.health import router as health_router
from zeler_gateway.tokens.refresh_worker import refresh_once
from zeler_gateway.webhooks.classifier import MELI_EVENTS_EXCHANGE
from zeler_gateway.webhooks.publisher import AioPikaWebhookPublisher, WebhookPublisher
from zeler_gateway.webhooks.router import router as webhooks_router

logger = structlog.get_logger(__name__)


REPRICER_SWEEP_ROUTING_KEY = "repricer.sweep.requested"
DEFAULT_REPRICER_SWEEP_INTERVAL_MINUTES = 5


async def publish_repricer_sweep_requests(
    *,
    db: Any,
    publisher: WebhookPublisher,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    now = clock().astimezone(UTC)
    timestamp = now.strftime("%Y%m%dT%H%M%SZ")
    occurred_at = now.isoformat().replace("+00:00", "Z")
    cursor = db["repricer_catalog_rules"].find({"active": True}).sort(
        [("seller_id", 1), ("account_id", 1)]
    )
    documents = await cursor.to_list(length=1000)
    seller_accounts = sorted(
        {
            (str(document["seller_id"]), str(document["account_id"]))
            for document in documents
            if document.get("seller_id") is not None and document.get("account_id") is not None
        }
    )
    for seller_id, account_id in seller_accounts:
        payload = {
            "event_id": f"repricer-sweep-{seller_id}-{account_id}-{timestamp}",
            "event_type": REPRICER_SWEEP_ROUTING_KEY,
            "occurred_at": occurred_at,
            "seller_id": seller_id,
            "account_id": account_id,
            "schema_version": 1,
        }
        await publisher.publish(
            REPRICER_SWEEP_ROUTING_KEY,
            payload,
            {
                "idempotency_key": f"repricer-sweep:{seller_id}:{account_id}:{timestamp}",
                "exchange": MELI_EVENTS_EXCHANGE,
            },
        )
    return {
        "published": len(seller_accounts),
        "seller_accounts": [
            f"{seller_id}:{account_id}" for seller_id, account_id in seller_accounts
        ],
    }


def configure_repricer_sweep_scheduler(
    *,
    scheduler: Any,
    db: Any,
    publisher: WebhookPublisher,
    interval_minutes: int = DEFAULT_REPRICER_SWEEP_INTERVAL_MINUTES,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> None:
    async def _scheduled_repricer_sweep() -> None:
        try:
            await publish_repricer_sweep_requests(db=db, publisher=publisher, clock=clock)
        except Exception:
            logger.exception("repricer sweep publication failed")

    scheduler.add_job(
        _scheduled_repricer_sweep,
        "interval",
        minutes=interval_minutes,
        id="repricer-sweep-publisher",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )


def _log_hmac_policy(settings: Settings) -> None:
    require_signature = settings.meli_webhook_require_signature
    secret = settings.meli_webhook_hmac_secret.get_secret_value()
    policy_logger = structlog.wrap_logger(logging.getLogger(__name__))

    if require_signature and secret:
        policy_logger.info(
            "webhook.hmac_policy.required",
            message="HMAC validation enforced",
        )
        return

    if require_signature:
        policy_logger.error(
            "webhook.hmac_policy.required_but_missing_secret",
            message="HMAC validation required but secret not configured",
        )
        return

    if secret:
        policy_logger.warning(
            "webhook.hmac_policy.secret_set_but_skipped",
            message=(
                "HMAC secret is set but MELI_WEBHOOK_REQUIRE_SIGNATURE=False — "
                "signature will NOT be verified"
            ),
        )
        return

    policy_logger.info(
        "webhook.hmac_policy.skipped",
        message="HMAC validation disabled by config",
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    get_settings.cache_clear()
    settings = get_settings()
    configure_logging(environment=settings.environment)
    _log_hmac_policy(settings)
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
    app.state.rabbit = None
    app.state.ready = False
    if settings.rabbitmq_url:
        try:
            app.state.rabbit = await aio_pika.connect_robust(settings.rabbitmq_url, heartbeat=60)
            app.state.ready = True
        except (TimeoutError, RuntimeError, aio_pika.exceptions.AMQPException):
            logger.warning("rabbitmq connection unavailable during startup")
    else:
        logger.warning("rabbitmq connection unavailable during startup")
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
    if settings.rabbitmq_url:
        configure_repricer_sweep_scheduler(
            scheduler=app.state.scheduler,
            db=app.state.mongo_db,
            publisher=AioPikaWebhookPublisher(
                rabbitmq_url=settings.rabbitmq_url,
                exchange_name=settings.rabbitmq_events_exchange,
            ),
            interval_minutes=DEFAULT_REPRICER_SWEEP_INTERVAL_MINUTES,
        )
    app.state.scheduler.start()

    try:
        yield
    finally:
        if app.state.rabbit is not None:
            await app.state.rabbit.close()
        app.state.scheduler.shutdown(wait=False)
        app.state.mongo_client.close()


app = FastAPI(title="zeler-meli-gateway", lifespan=lifespan)
app.middleware("http")(metrics_middleware)
app.include_router(accounts_router)
app.include_router(auth_router)
app.include_router(bootstrap_jobs_router)
app.include_router(health_router)
app.include_router(internal_router)
app.include_router(metrics_router)
app.include_router(oauth_router)
app.include_router(proxy_router, prefix="/proxy/meli")
app.include_router(webhooks_router)
