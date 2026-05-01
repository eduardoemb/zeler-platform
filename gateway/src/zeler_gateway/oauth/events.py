from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

import structlog

logger = structlog.get_logger(__name__)


class AmqpPublisher(Protocol):
    async def publish(
        self, *, exchange: str, routing_key: str, payload: dict[str, Any]
    ) -> None: ...


async def emit_accounts_linked(
    seller_id: str,
    platform_user_id: str,
    *,
    mongo_db: Any,
    amqp_publisher: AmqpPublisher,
    force: bool = False,
    clock: Any = None,
) -> None:
    now = (clock or (lambda: datetime.now(UTC)))()
    seller_id = str(seller_id)
    existing = await mongo_db["bootstrap_jobs"].find_one({"seller_id": seller_id})
    if (
        existing is not None
        and existing.get("state") in {"pending", "running", "succeeded"}
        and not force
    ):
        logger.info(
            "bootstrap.relink.skipped", seller_id=seller_id, platform_user_id=platform_user_id
        )
        return

    job_id = f"bootstrap-{seller_id}-oauth"
    job = {
        "_id": job_id,
        "state": "pending",
        "seller_id": seller_id,
        "triggered_by": "oauth_callback_force" if force else "oauth_callback",
        "dispatch_attempts": 0,
        "created_at": existing.get("created_at", now) if existing else now,
        "updated_at": now,
    }
    await mongo_db["bootstrap_jobs"].replace_one({"_id": job_id}, job, upsert=True)
    idempotency_suffix = "force" if force else "oauth"
    payload = {
        "seller_id": seller_id,
        "platform_user_id": platform_user_id,
        "occurred_at": now.isoformat(),
        "idempotency_key": f"accounts-linked-{seller_id}-{idempotency_suffix}",
    }
    await amqp_publisher.publish(
        exchange="meli.events", routing_key="accounts.linked", payload=payload
    )
    logger.info("accounts.linked", **payload)


async def emit_accounts_revoked(*, seller_id: int, platform_user_id: str) -> None:
    # TODO(P2): publish accounts.revoked to RabbitMQ once AMQP wiring exists.
    logger.info("accounts.revoked", seller_id=seller_id, platform_user_id=platform_user_id)
