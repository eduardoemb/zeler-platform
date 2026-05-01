from __future__ import annotations

import json
from typing import Any

import pytest

from zeler_sheets.consumer import SheetsAmqpConsumerRunner, SheetsEvent


class FakeHandler:
    def __init__(self) -> None:
        self.events: list[SheetsEvent] = []

    async def handle(self, event: SheetsEvent) -> str:
        self.events.append(event)
        return "processed"


class FakeMessage:
    def __init__(self) -> None:
        self.body = json.dumps(
            {
                "event_id": "evt-paused",
                "event_type": "items.updated",
                "seller_id": 82453304,
                "resource": "/items/MLA123",
            }
        ).encode()
        self.headers: dict[str, Any] = {}
        self.acked = False

    async def ack(self) -> None:
        self.acked = True

    async def nack(self, *, requeue: bool = False) -> None:
        raise AssertionError(f"unexpected nack {requeue}")


@pytest.mark.asyncio
async def test_message_skipped_when_account_paused() -> None:
    handler = FakeHandler()
    runner = SheetsAmqpConsumerRunner(
        rabbitmq_url="amqp://test",
        handler=handler,
        account_status_source=lambda seller_id: "paused",
    )
    message = FakeMessage()

    await runner.handle_message(message)

    assert message.acked is True
    assert handler.events == []


@pytest.mark.asyncio
async def test_message_processed_when_account_active() -> None:
    handler = FakeHandler()
    runner = SheetsAmqpConsumerRunner(
        rabbitmq_url="amqp://test",
        handler=handler,
        account_status_source=lambda seller_id: "active",
    )
    message = FakeMessage()

    await runner.handle_message(message)

    assert message.acked is True
    assert [event.seller_id for event in handler.events] == [82453304]
