from __future__ import annotations

import asyncio
from typing import Any, Literal

import aio_pika
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pymongo.errors import PyMongoError

from zeler_gateway.config import Settings

CheckName = Literal["mongo", "rabbitmq"]
CheckStatus = Literal["ok", "fail", "starting"]


class LivenessResponse(BaseModel):
    status: Literal["alive"]


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: dict[CheckName, CheckStatus]


router = APIRouter()


@router.get("/health", response_model=LivenessResponse)
async def health() -> LivenessResponse:
    return LivenessResponse(status="alive")


@router.get("/ready", response_model=ReadinessResponse)
async def ready(request: Request) -> JSONResponse:
    app_state: Any = request.app.state
    if not bool(getattr(app_state, "ready", False)):
        return _readiness_response("starting", "starting")

    settings = Settings()
    mongo_timeout_s = settings.ready_mongo_timeout_s
    rabbit_timeout_s = settings.ready_rabbitmq_timeout_s
    total_timeout_s = max(mongo_timeout_s, rabbit_timeout_s) + 0.2

    try:
        mongo_result, rabbit_result = await asyncio.wait_for(
            asyncio.gather(
                _check_mongo(app_state, mongo_timeout_s),
                _check_rabbit(app_state, rabbit_timeout_s, settings.rabbitmq_url),
                return_exceptions=True,
            ),
            timeout=total_timeout_s,
        )
    except TimeoutError:
        mongo_result = "fail"
        rabbit_result = "fail"

    mongo_status: CheckStatus = "ok" if mongo_result == "ok" else "fail"
    rabbit_status: CheckStatus = "ok" if rabbit_result == "ok" else "fail"
    return _readiness_response(mongo_status, rabbit_status)


async def _check_mongo(app_state: Any, timeout_s: float) -> CheckStatus:
    try:
        await asyncio.wait_for(app_state.mongo_client.admin.command("ping"), timeout=timeout_s)
    except (AttributeError, TimeoutError, RuntimeError, PyMongoError):
        return "fail"
    return "ok"


async def _check_rabbit(app_state: Any, timeout_s: float, rabbitmq_url: str) -> CheckStatus:
    try:
        rabbit = getattr(app_state, "rabbit", None)
        if rabbit is not None and bool(getattr(rabbit, "is_open", False)):
            return "ok"
        if not rabbitmq_url:
            return "fail"
        refreshed = await asyncio.wait_for(
            aio_pika.connect_robust(rabbitmq_url, heartbeat=60), timeout=timeout_s
        )
        app_state.rabbit = refreshed
    except (AttributeError, TimeoutError, RuntimeError, aio_pika.exceptions.AMQPException):
        return "fail"
    return "ok"


def _readiness_response(mongo: CheckStatus, rabbitmq: CheckStatus) -> JSONResponse:
    response = ReadinessResponse(
        status="ready" if mongo == "ok" and rabbitmq == "ok" else "not_ready",
        checks={"mongo": mongo, "rabbitmq": rabbitmq},
    )
    http_status = (
        status.HTTP_200_OK if response.status == "ready" else status.HTTP_503_SERVICE_UNAVAILABLE
    )
    return JSONResponse(status_code=http_status, content=response.model_dump())
