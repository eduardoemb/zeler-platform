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
    "zeler.publicador.questions": ["questions.*"],
    "zeler.publicador.messages": ["messages.*"],
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
        exchanges.append({"name": dlx, "type": "direct", "durable": True})
        queues.append(_queue(f"{queue_name}.dlq"))
        queues.append(
            _queue(
                queue_name,
                {
                    "x-dead-letter-exchange": dlx,
                },
            )
        )
        bindings.append(
            {"source": dlx, "destination": f"{queue_name}.dlq", "routing_key": queue_name}
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
