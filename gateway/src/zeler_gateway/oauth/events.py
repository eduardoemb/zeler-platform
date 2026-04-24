from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def emit_accounts_linked(*, seller_id: int, platform_user_id: str) -> None:
    # TODO(P2): publish accounts.linked to RabbitMQ once AMQP wiring exists.
    logger.info(
        "would emit accounts.linked",
        extra={"seller_id": seller_id, "platform_user_id": platform_user_id},
    )
