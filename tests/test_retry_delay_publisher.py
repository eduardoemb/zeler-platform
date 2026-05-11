from __future__ import annotations

from typing import Any

import pytest
from infra.rabbitmq.retry_delay import RetryDelayPublisher


class FakeExchange:
    def __init__(self) -> None:
        self.published: list[tuple[Any, str]] = []

    async def publish(self, message: Any, routing_key: str) -> None:
        self.published.append((message, routing_key))


class FakeChannel:
    def __init__(self) -> None:
        self.exchange = FakeExchange()
        self.declared: list[dict[str, object]] = []

    async def declare_exchange(self, name: str, type: str, durable: bool) -> FakeExchange:
        self.declared.append({"exchange": name, "type": type, "durable": durable})
        return self.exchange


@pytest.mark.asyncio
async def test_retry_delay_publisher_publishes_with_expiration_to_delay_queue() -> None:
    channel = FakeChannel()
    publisher = RetryDelayPublisher(channel)

    await publisher.publish_delay(b'{"event_id":"evt-1"}', "zeler.repricer.items", delay_ms=5000)

    message, routing_key = channel.exchange.published[0]
    assert routing_key == "zeler.repricer.items.delay"
    assert message.body == b'{"event_id":"evt-1"}'
    assert message.expiration == 5000


@pytest.mark.asyncio
async def test_retry_delay_publisher_preserves_retry_headers() -> None:
    channel = FakeChannel()
    publisher = RetryDelayPublisher(channel)

    await publisher.publish_delay(
        b'{"event_id":"evt-1"}',
        "zeler.sheets.events",
        delay_ms=9000,
        headers={"x-zeler-retry-attempt": 2},
    )

    message, routing_key = channel.exchange.published[0]
    assert routing_key == "zeler.sheets.events.delay"
    assert message.headers == {"x-zeler-retry-attempt": 2}
