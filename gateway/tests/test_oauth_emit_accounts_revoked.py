from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from structlog.testing import capture_logs

from zeler_gateway.oauth.events import emit_accounts_revoked


class RecordingPublisher:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def publish(self, *, exchange: str, routing_key: str, payload: dict[str, Any]) -> None:
        self.messages.append({"exchange": exchange, "routing_key": routing_key, "payload": payload})


NOW = datetime(2026, 8, 10, 12, 30, tzinfo=UTC)


@pytest.mark.asyncio
async def test_emit_accounts_revoked_publishes_normalized_payload() -> None:
    publisher = RecordingPublisher()

    await emit_accounts_revoked(
        seller_id=123,
        platform_user_id="u-1",
        amqp_publisher=publisher,
        clock=lambda: NOW,
    )

    occurred_at = NOW.isoformat()
    assert publisher.messages == [
        {
            "exchange": "meli.events",
            "routing_key": "accounts.revoked",
            "payload": {
                "seller_id": "123",
                "platform_user_id": "u-1",
                "occurred_at": occurred_at,
                "idempotency_key": f"accounts-revoked-123-u-1-{occurred_at}",
            },
        }
    ]


@pytest.mark.asyncio
async def test_emit_accounts_revoked_logs_when_publisher_is_not_configured() -> None:
    with capture_logs() as logs:
        await emit_accounts_revoked(
            seller_id=456,
            platform_user_id="u-2",
            amqp_publisher=None,
            clock=lambda: NOW,
        )

    assert {
        "event": "accounts.revoked",
        "log_level": "info",
        "seller_id": "456",
        "platform_user_id": "u-2",
        "occurred_at": NOW.isoformat(),
        "idempotency_key": f"accounts-revoked-456-u-2-{NOW.isoformat()}",
    } in logs
