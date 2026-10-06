from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any, Protocol

import structlog

from zeler_gateway.config import Settings
from zeler_platform_core.history_onboarding import admit_history_onboarding
from zeler_platform_core.models.base import current_schema_version

logger = structlog.get_logger(__name__)


class AmqpPublisher(Protocol):
    async def publish(
        self, *, exchange: str, routing_key: str, payload: dict[str, Any]
    ) -> None: ...


def _history_admission_allowed(seller_id: str) -> bool:
    # Hold is intentionally independent of the worker flag. Unknown explicit
    # hold/scope values fail closed for history without breaking OAuth/bootstrap.
    hold = os.environ.get("ZELERDATA_HISTORY_ON_LINK_ADMISSION_HOLD", "false").strip().lower()
    if hold not in {"", "false", "0", "no", "off"}:
        return False
    raw = os.environ.get("ZELERDATA_HISTORY_ON_LINK_ADMISSION_SELLERS")
    if raw is None:
        return True
    sellers = frozenset(value.strip() for value in raw.split(","))
    if not sellers or any(
        not seller.isascii()
        or not seller.isdecimal()
        or len(seller) > 20
        or str(int(seller)) != seller
        for seller in sellers
    ):
        return False
    return seller_id in sellers


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
    if seller_id.isascii() and seller_id.isdecimal() and _history_admission_allowed(seller_id):
        pilot_scope = Settings().history_pilot_get_budget_sellers
        if pilot_scope is not None and seller_id in pilot_scope:
            await admit_history_onboarding(mongo_db, seller_id, now=now, pilot_seed=True)
        else:
            await admit_history_onboarding(mongo_db, seller_id, now=now)
    existing = None
    if not force:
        existing = await mongo_db["bootstrap_jobs"].find_one(
            {"seller_id": seller_id, "state": {"$in": ["pending", "running", "succeeded"]}}
        )
    if existing is None:
        # Preserve the original retry/force created_at without letting terminal
        # history hide an eligible record during an ordinary relink.
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
    job: dict[str, Any] = {
        "_id": job_id,
        "state": "pending",
        "seller_id": seller_id,
        "dag": {},
        "checkpoints": {},
        "triggered_by": "oauth_callback_force" if force else "oauth_callback",
        "dispatch_attempts": 0,
        "created_at": existing.get("created_at", now) if existing else now,
        "updated_at": now,
        "schema_version": current_schema_version("bootstrap_jobs"),
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


async def emit_accounts_revoked(
    *,
    seller_id: int,
    platform_user_id: str,
    amqp_publisher: AmqpPublisher | None = None,
    clock: Any = None,
) -> None:
    now = (clock or (lambda: datetime.now(UTC)))()
    normalized_seller_id = str(seller_id)
    occurred_at = now.isoformat()
    payload = {
        "seller_id": normalized_seller_id,
        "platform_user_id": platform_user_id,
        "occurred_at": occurred_at,
        "idempotency_key": (
            f"accounts-revoked-{normalized_seller_id}-{platform_user_id}-{occurred_at}"
        ),
    }
    if amqp_publisher is not None:
        await amqp_publisher.publish(
            exchange="meli.events",
            routing_key="accounts.revoked",
            payload=payload,
        )
    logger.info("accounts.revoked", **payload)
