from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any, Literal, cast

import aio_pika
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pymongo.errors import PyMongoError

from zeler_gateway.config import Settings
from zeler_platform_core.runtime.checks import OwnedAmqpTransport

GATEWAY_REQUIRED_REGISTRY_IDS = ("repricer", "sheets", "publicador", "autoreply", "zeler-app")
REPRICER_SWEEP_JOB_ID = "repricer-sweep-publisher"

CheckName = Literal["mongo", "registry"]
BrokerDependencyName = Literal["rabbitmq", "repricer_sweep_scheduler"]
CheckStatus = Literal["ok", "fail", "starting"]


class LivenessResponse(BaseModel):
    status: Literal["alive"]


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: dict[CheckName, CheckStatus]
    broker_dependencies: dict[BrokerDependencyName, CheckStatus]


router = APIRouter()


@router.get("/health", response_model=LivenessResponse)
async def health() -> LivenessResponse:
    return LivenessResponse(status="alive")


@router.get("/ready", response_model=ReadinessResponse)
async def ready(request: Request) -> JSONResponse:
    app_state: Any = request.app.state
    if not bool(getattr(app_state, "ready", False)):
        return _readiness_response("starting", "starting", "starting", "starting")

    settings = Settings()
    mongo_timeout_s = settings.ready_mongo_timeout_s
    rabbit_timeout_s = settings.ready_rabbitmq_timeout_s
    total_timeout_s = max(mongo_timeout_s, rabbit_timeout_s) + 0.2

    try:
        (
            mongo_result,
            registry_result,
            rabbit_result,
            scheduler_result,
        ) = await asyncio.wait_for(
            asyncio.gather(
                _check_mongo(app_state, mongo_timeout_s),
                _check_registry(app_state, mongo_timeout_s),
                _check_rabbit(app_state, rabbit_timeout_s, settings.rabbitmq_url),
                _check_repricer_sweep_scheduler(app_state),
                return_exceptions=True,
            ),
            timeout=total_timeout_s,
        )
    except TimeoutError:
        mongo_result = "fail"
        registry_result = "fail"
        rabbit_result = "fail"
        scheduler_result = "fail"

    mongo_status: CheckStatus = "ok" if mongo_result == "ok" else "fail"
    registry_status: CheckStatus = "ok" if registry_result == "ok" else "fail"
    rabbit_status: CheckStatus = "ok" if rabbit_result == "ok" else "fail"
    scheduler_status: CheckStatus = "ok" if scheduler_result == "ok" else "fail"
    return _readiness_response(mongo_status, registry_status, rabbit_status, scheduler_status)


async def _check_mongo(app_state: Any, timeout_s: float) -> CheckStatus:
    try:
        await asyncio.wait_for(app_state.mongo_client.admin.command("ping"), timeout=timeout_s)
    except (AttributeError, TimeoutError, RuntimeError, PyMongoError):
        return "fail"
    return "ok"


async def _check_registry(app_state: Any, timeout_s: float) -> CheckStatus:
    """Verify every required module registry entry exists and is enabled."""
    try:
        mongo_db = getattr(app_state, "mongo_db", None)
        if mongo_db is None:
            return "fail"
        collection = mongo_db["module_registry"]
        for module_id in GATEWAY_REQUIRED_REGISTRY_IDS:
            document = await asyncio.wait_for(
                collection.find_one({"_id": module_id}), timeout=timeout_s
            )
            if document is None or document.get("status") != "enabled":
                return "fail"
    except (AttributeError, KeyError, TimeoutError, RuntimeError, PyMongoError):
        return "fail"
    return "ok"


def _rabbit_lock(app_state: Any) -> asyncio.Lock:
    lock = getattr(app_state, "rabbit_lock", None)
    if lock is None:
        lock = asyncio.Lock()
        app_state.rabbit_lock = lock
    return lock


async def _close_rabbit_connection(rabbit: Any) -> None:
    # Fit failed-attempt cleanup inside the aggregate readiness grace (0.2s).
    try:
        await asyncio.wait_for(rabbit.close(), timeout=0.1)
    finally:
        transport = getattr(rabbit, "_readiness_transport_owner", None)
        if transport is not None:
            transport.abort()


async def _connect_owned_rabbit(rabbitmq_url: str, timeout_s: float) -> Any:
    candidate: Any = None

    def create(*args: Any, **kwargs: Any) -> Any:
        nonlocal candidate
        candidate = aio_pika.RobustConnection(*args, **kwargs)
        transport = OwnedAmqpTransport(candidate.url)
        candidate.kwargs["transport_factory"] = transport
        candidate._readiness_transport_owner = transport
        return candidate

    try:
        candidate = await aio_pika.connect_robust(
            rabbitmq_url,
            heartbeat=60,
            timeout=timeout_s,
            connection_class=cast(type[aio_pika.abc.AbstractRobustConnection], create),
        )
        await candidate.connected.wait()
        if candidate.is_closed:
            raise RuntimeError("Rabbit connection closed during initialization")
        return candidate
    except BaseException:
        # connect_robust does not close the object it created when connect fails
        # or is cancelled. Retain that object before its first asynchronous work.
        if candidate is not None:
            with suppress(Exception):
                await _close_rabbit_connection(candidate)
        raise


async def _check_rabbit(app_state: Any, timeout_s: float, rabbitmq_url: str) -> CheckStatus:
    try:
        async with asyncio.timeout(timeout_s):
            async with _rabbit_lock(app_state):
                if getattr(app_state, "rabbit_shutdown", False):
                    return "fail"
                rabbit = getattr(app_state, "rabbit", None)
                if rabbit is None or rabbit.is_closed:
                    if rabbit is not None:
                        transport = getattr(rabbit, "_readiness_transport_owner", None)
                        if transport is not None:
                            transport.abort()
                    if not rabbitmq_url:
                        return "fail"
                    rabbit = await _connect_owned_rabbit(rabbitmq_url, timeout_s)
                    app_state.rabbit = rabbit
                # A robust connection owns its reconnect task. A readiness probe
                # waits for that connection, rather than replacing it on a gap.
                await rabbit.connected.wait()
                if rabbit.is_closed or getattr(app_state, "rabbit_shutdown", False):
                    return "fail"
    except (AttributeError, TimeoutError, *aio_pika.exceptions.CONNECTION_EXCEPTIONS):
        return "fail"
    return "ok"


async def close_owned_rabbit(app_state: Any) -> None:
    app_state.rabbit_shutdown = True
    async with _rabbit_lock(app_state):
        rabbit = getattr(app_state, "rabbit", None)
        app_state.rabbit = None
        if rabbit is not None:
            await _close_rabbit_connection(rabbit)


async def _check_repricer_sweep_scheduler(app_state: Any) -> CheckStatus:
    """Probe the in-process scheduler and its required sweep job."""
    scheduler = getattr(app_state, "scheduler", None)
    if scheduler is None or not bool(getattr(scheduler, "running", False)):
        return "fail"
    if scheduler.get_job(REPRICER_SWEEP_JOB_ID) is None:
        return "fail"
    return "ok"


def _readiness_response(
    mongo: CheckStatus,
    registry: CheckStatus,
    rabbitmq: CheckStatus,
    repricer_sweep_scheduler: CheckStatus,
) -> JSONResponse:
    response = ReadinessResponse(
        status=(
            "ready"
            if mongo == "ok"
            and registry == "ok"
            and rabbitmq == "ok"
            and repricer_sweep_scheduler == "ok"
            else "not_ready"
        ),
        checks={"mongo": mongo, "registry": registry},
        broker_dependencies={
            "rabbitmq": rabbitmq,
            "repricer_sweep_scheduler": repricer_sweep_scheduler,
        },
    )
    http_status = (
        status.HTTP_200_OK if response.status == "ready" else status.HTTP_503_SERVICE_UNAVAILABLE
    )
    return JSONResponse(status_code=http_status, content=response.model_dump())
