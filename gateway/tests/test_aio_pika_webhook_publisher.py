from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

import pytest

from zeler_gateway.webhooks.publisher import AioPikaWebhookPublisher


@pytest.mark.asyncio
async def test_aio_pika_publisher_ignores_header_exchange_override_and_uses_mandatory_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: dict[str, Any] = {"declared": [], "published": []}

    class FakeMessage:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    class FakeExchange:
        async def publish(
            self,
            message: FakeMessage,
            *,
            routing_key: str,
            mandatory: bool = False,
        ) -> None:
            recorded["published"].append(
                {"message": message, "routing_key": routing_key, "mandatory": mandatory}
            )

    class FakeChannel:
        async def declare_exchange(
            self, name: str, exchange_type: str, *, durable: bool
        ) -> FakeExchange:
            recorded["declared"].append((name, exchange_type, durable))
            return FakeExchange()

    class FakeConnection:
        async def __aenter__(self) -> FakeConnection:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def channel(
            self, *, publisher_confirms: bool, on_return_raises: bool = False
        ) -> FakeChannel:
            recorded["publisher_confirms"] = publisher_confirms
            recorded["on_return_raises"] = on_return_raises
            return FakeChannel()

    async def connect_robust(rabbitmq_url: str) -> FakeConnection:
        recorded["rabbitmq_url"] = rabbitmq_url
        return FakeConnection()

    fake_aio_pika = SimpleNamespace(
        connect_robust=connect_robust,
        ExchangeType=SimpleNamespace(TOPIC="topic"),
        DeliveryMode=SimpleNamespace(PERSISTENT="persistent"),
        Message=FakeMessage,
    )
    monkeypatch.setitem(sys.modules, "aio_pika", fake_aio_pika)
    publisher = AioPikaWebhookPublisher(
        rabbitmq_url="unused-rabbit-url",
        exchange_name="configured.events",
    )

    await publisher.publish(
        "items.updated",
        {"event_id": "event-1"},
        {"idempotency_key": "idem-1", "exchange": "wrong.events"},
    )

    assert recorded["rabbitmq_url"] == "unused-rabbit-url"
    assert recorded["publisher_confirms"] is True
    assert recorded["on_return_raises"] is True
    assert recorded["declared"] == [("configured.events", "topic", True)]
    assert recorded["published"][0]["routing_key"] == "items.updated"
    assert recorded["published"][0]["mandatory"] is True


@pytest.mark.asyncio
async def test_aio_pika_publisher_supports_explicit_internal_exchange_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: dict[str, Any] = {"declared": []}

    class FakeExchange:
        async def publish(self, _message: object, *, routing_key: str, mandatory: bool) -> None:
            recorded["published"] = {"routing_key": routing_key, "mandatory": mandatory}

    class FakeChannel:
        async def declare_exchange(
            self, name: str, _exchange_type: str, *, durable: bool
        ) -> FakeExchange:
            recorded["declared"].append((name, durable))
            return FakeExchange()

    class FakeConnection:
        async def __aenter__(self) -> FakeConnection:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def channel(
            self, *, publisher_confirms: bool, on_return_raises: bool = False
        ) -> FakeChannel:
            recorded["publisher_confirms"] = publisher_confirms
            recorded["on_return_raises"] = on_return_raises
            return FakeChannel()

    async def connect_robust(_rabbitmq_url: str) -> FakeConnection:
        return FakeConnection()

    monkeypatch.setitem(
        sys.modules,
        "aio_pika",
        SimpleNamespace(
            connect_robust=connect_robust,
            ExchangeType=SimpleNamespace(TOPIC="topic"),
            DeliveryMode=SimpleNamespace(PERSISTENT="persistent"),
            Message=lambda **kwargs: kwargs,
        ),
    )
    publisher = AioPikaWebhookPublisher(
        rabbitmq_url="unused-rabbit-url",
        exchange_name="configured.events",
    )

    await publisher.publish_to_exchange(
        "zeler.sheets.replay",
        "items.updated",
        {"event_id": "event-2"},
        {"idempotency_key": "idem-2"},
    )

    assert recorded["declared"] == [("zeler.sheets.replay", True)]
    assert recorded["publisher_confirms"] is True
    assert recorded["on_return_raises"] is True
    assert recorded["published"] == {"routing_key": "items.updated", "mandatory": True}
