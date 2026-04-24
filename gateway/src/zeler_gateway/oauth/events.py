from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)


async def emit_accounts_linked(*, seller_id: int, platform_user_id: str) -> None:
    # TODO(P2): publish accounts.linked to RabbitMQ once AMQP wiring exists.
    logger.info("accounts.linked", seller_id=seller_id, platform_user_id=platform_user_id)


async def emit_accounts_revoked(*, seller_id: int, platform_user_id: str) -> None:
    # TODO(P2): publish accounts.revoked to RabbitMQ once AMQP wiring exists.
    logger.info("accounts.revoked", seller_id=seller_id, platform_user_id=platform_user_id)
