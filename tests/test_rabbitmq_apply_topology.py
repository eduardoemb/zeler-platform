from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from infra.rabbitmq.apply_topology import apply_rabbitmq_topology, render_apply_markdown


def test_apply_rabbitmq_topology_declares_resources_idempotently(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    definitions_path = tmp_path / "definitions.json"
    definitions_path.write_text(
        json.dumps(
            {
                "exchanges": [{"name": "meli.events", "type": "topic", "durable": True}],
                "queues": [{"name": "zeler.autoreply.events", "durable": True, "arguments": {}}],
                "bindings": [
                    {
                        "source": "meli.events",
                        "destination": "zeler.autoreply.events",
                        "routing_key": "questions.new",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    class FakeExchange:
        def __init__(self, name: str) -> None:
            self.name = name

    class FakeQueue:
        def __init__(self, name: str) -> None:
            self.name = name

        async def bind(self, exchange: FakeExchange, routing_key: str) -> None:
            calls.append(("bind", (exchange.name, self.name), {"routing_key": routing_key}))

    class FakeChannel:
        async def declare_exchange(
            self,
            name: str,
            type: str,
            *,
            durable: bool,
        ) -> FakeExchange:
            calls.append(("exchange", (name, type), {"durable": durable}))
            return FakeExchange(name)

        async def declare_queue(
            self,
            name: str,
            *,
            durable: bool,
            arguments: dict[str, Any],
        ) -> FakeQueue:
            calls.append(("queue", (name,), {"durable": durable, "arguments": arguments}))
            return FakeQueue(name)

    class FakeConnection:
        async def channel(self) -> FakeChannel:
            return FakeChannel()

        async def close(self) -> None:
            calls.append(("connection.close", (), {}))

    async def fake_connect_robust(_url: str, **_kwargs: Any) -> FakeConnection:
        return FakeConnection()

    monkeypatch.setattr(
        "infra.rabbitmq.apply_topology.aio_pika.connect_robust",
        fake_connect_robust,
    )

    report = apply_rabbitmq_topology(
        definitions_path=definitions_path,
        amqp_url="amqps://example.test/vhost",
    )
    markdown = render_apply_markdown(report)

    assert report.ok is True
    assert report.safe_to_execute is False
    assert report.read_only is False
    assert report.mutations_attempted == 3
    assert report.summary == {
        "exchanges_declared": 1,
        "queues_declared": 1,
        "bindings_declared": 1,
    }
    assert ("exchange", ("meli.events", "topic"), {"durable": True}) in calls
    assert ("queue", ("zeler.autoreply.events",), {"durable": True, "arguments": {}}) in calls
    assert (
        "bind",
        ("meli.events", "zeler.autoreply.events"),
        {"routing_key": "questions.new"},
    ) in calls
    assert "amqps://" not in markdown
    assert "mutations_attempted: 3" in markdown
