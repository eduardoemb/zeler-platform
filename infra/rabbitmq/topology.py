from __future__ import annotations

import json
from pathlib import Path
from typing import Any

EXCHANGE = "meli.events"

QUEUE_BINDINGS = {
    "zeler.repricer.items": ["items.*"],
    "zeler.repricer.items_prices": ["items.price_updated"],
    "zeler.repricer.price_suggestion": ["price_suggestion.*"],
    "zeler.sheets.orders": ["orders.*"],
    "zeler.sheets.user_products": ["user_products.*"],
    "zeler.fulldock.stock_locations": ["stock_locations.*"],
    "zeler.fulldock.events": ["items.*", "shipments.*", "stock_locations.*"],
    "zeler.autoreply.events": ["questions.new", "messages.new"],
    "zeler.publicador.questions": ["questions.*"],
    "zeler.publicador.messages": ["messages.*"],
}

ACTIVE_QUEUE_DEAD_LETTER_ROUTING_KEYS = {
    "zeler.fulldock.events": "zeler.fulldock.events.dlq",
    "zeler.autoreply.events": "zeler.autoreply.events.dlq",
}

RETRY_DELAYS_MS = {
    "1s": 1_000,
    "5s": 5_000,
    "30s": 30_000,
    "2m": 120_000,
    "10m": 600_000,
}


def _queue(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"name": name, "durable": True, "arguments": arguments or {}}


def build_topology_definitions() -> dict[str, Any]:
    exchanges: list[dict[str, Any]] = [{"name": EXCHANGE, "type": "topic", "durable": True}]
    queues: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []

    for queue_name, routing_keys in QUEUE_BINDINGS.items():
        dlx = f"{queue_name}.dlx"
        dlq = f"{queue_name}.dlq"
        dead_letter_routing_key = ACTIVE_QUEUE_DEAD_LETTER_ROUTING_KEYS.get(queue_name)
        active_queue_arguments = {"x-dead-letter-exchange": dlx}
        if dead_letter_routing_key is not None:
            active_queue_arguments["x-dead-letter-routing-key"] = dead_letter_routing_key
        exchanges.append({"name": dlx, "type": "direct", "durable": True})
        queues.append(_queue(dlq))
        queues.append(
            _queue(
                queue_name,
                active_queue_arguments,
            )
        )
        bindings.append(
            {
                "source": dlx,
                "destination": dlq,
                "routing_key": dead_letter_routing_key or queue_name,
            }
        )
        for delay_name, ttl_ms in RETRY_DELAYS_MS.items():
            retry_queue = f"{queue_name}.retry.{delay_name}"
            queues.append(
                _queue(
                    retry_queue,
                    {
                        "x-message-ttl": ttl_ms,
                        "x-dead-letter-exchange": EXCHANGE,
                    },
                )
            )
        for routing_key in routing_keys:
            bindings.append(
                {"source": EXCHANGE, "destination": queue_name, "routing_key": routing_key}
            )
    queues.append(_queue("webhooks.unknown.dlq"))
    bindings.append(
        {
            "source": EXCHANGE,
            "destination": "webhooks.unknown.dlq",
            "routing_key": "webhooks.unknown.dlq",
        }
    )
    return {"exchanges": exchanges, "queues": queues, "bindings": bindings}


def write_definitions(path: Path) -> None:
    path.write_text(json.dumps(build_topology_definitions(), indent=2) + "\n", encoding="utf-8")
