from __future__ import annotations

import hmac
from datetime import UTC, datetime
from hashlib import sha256
from ipaddress import ip_address, ip_network
from typing import Annotated, Any, cast

import structlog
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request

from zeler_gateway.config import Settings
from zeler_gateway.webhooks.publisher import (
    AioPikaWebhookPublisher,
    WebhookPublisher,
    publish_webhook_event,
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _source_ip(request: Request, forwarded_for: str | None) -> str:
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    if request.client is None:
        return ""
    return request.client.host


def is_allowed_source_ip(source_ip: str, allowlist: str) -> bool:
    if not allowlist:
        return False
    parsed_ip = ip_address(source_ip)
    for entry in [item.strip() for item in allowlist.split(",") if item.strip()]:
        network = ip_network(entry, strict=False)
        if parsed_ip in network:
            return True
    return False


def verify_hmac_signature(body: bytes, signature: str | None, secret: str) -> bool:
    if not secret:
        return True
    if not signature:
        return False
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), body, sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _event_id(payload: dict[str, Any]) -> str:
    value = payload.get("_id") or payload.get("notification_id") or payload.get("id")
    if value is None:
        raise HTTPException(status_code=422, detail="webhook payload missing notification id")
    return str(value)


def _get_publisher(request: Request, settings: Settings) -> WebhookPublisher | None:
    injected = getattr(request.app.state, "webhook_publisher", None)
    if injected is not None:
        return cast(WebhookPublisher, injected)
    if not settings.rabbitmq_url:
        return None
    return AioPikaWebhookPublisher(
        rabbitmq_url=settings.rabbitmq_url, exchange_name=settings.rabbitmq_events_exchange
    )


async def _classify_and_publish(
    event: dict[str, Any], *, publisher: WebhookPublisher | None, db: Any, trace_id: str | None
) -> None:
    if publisher is None:
        logger.warning(
            "webhook.publisher_not_configured", event_id=event.get("_id"), topic=event.get("topic")
        )
        return
    try:
        await publish_webhook_event(event, publisher=publisher, trace_id=trace_id)
        await db["webhook_events"].update_one(
            {"_id": event["_id"]},
            {
                "$set": {
                    "published_at": datetime.now(UTC),
                    "classification": event.get("topic"),
                }
            },
            upsert=False,
        )
    except Exception:
        logger.exception(
            "webhook.publish_failed", event_id=event.get("_id"), topic=event.get("topic")
        )


@router.post("/meli")
async def receive_meli_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_forwarded_for: Annotated[str | None, Header(alias="X-Forwarded-For")] = None,
    x_meli_signature: Annotated[str | None, Header(alias="X-Meli-Signature")] = None,
) -> dict[str, Any]:
    settings = Settings()
    body = await request.body()
    source_ip = _source_ip(request, x_forwarded_for)
    if not is_allowed_source_ip(source_ip, settings.meli_allowed_ips):
        logger.warning("webhook.invalid_source_ip", source_ip=source_ip, path=str(request.url.path))
        raise HTTPException(status_code=401, detail="invalid webhook source")

    secret = settings.meli_webhook_hmac_secret.get_secret_value()
    if not verify_hmac_signature(body, x_meli_signature, secret):
        logger.warning("webhook.invalid_signature", source_ip=source_ip, path=str(request.url.path))
        raise HTTPException(status_code=401, detail="invalid webhook signature")

    payload = await request.json()
    event_id = _event_id(payload)
    received_at = datetime.now(UTC)
    document = {
        "_id": event_id,
        "topic": str(payload["topic"]),
        "user_id": int(payload["user_id"]),
        "resource": str(payload["resource"]),
        "received_at": received_at,
        "published_at": None,
        "classification": None,
        "raw_body": payload,
        "source_ip": source_ip,
        "schema_version": 1,
    }
    db = request.app.state.mongo_db
    result = await db["webhook_events"].update_one(
        {"_id": event_id}, {"$setOnInsert": document}, upsert=True
    )
    duplicate = (
        getattr(result, "upserted_id", None) is None and getattr(result, "matched_count", 0) > 0
    )
    if duplicate:
        return {"status": "accepted", "duplicate": True}

    publisher = _get_publisher(request, settings)
    background_tasks.add_task(
        _classify_and_publish,
        document,
        publisher=publisher,
        db=db,
        trace_id=request.headers.get("X-Trace-Id", ""),
    )
    return {"status": "accepted", "duplicate": False}
