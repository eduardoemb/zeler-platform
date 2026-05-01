from __future__ import annotations

import json
from pathlib import Path

DELAY_TOPOLOGY = Path("infra/rabbitmq/delay_queues.json")


def test_each_worker_module_has_delay_queue_declared() -> None:
    topology = json.loads(DELAY_TOPOLOGY.read_text(encoding="utf-8"))
    queue_names = {queue["name"] for queue in topology["queues"]}

    for queue_name in (
        "zeler.repricer.items.delay",
        "zeler.sheets.events.delay",
        "zeler.autoreply.events.delay",
        "zeler.fulldock.events.delay",
    ):
        assert queue_name in queue_names


def test_delay_queue_has_dlx_to_main_queue() -> None:
    topology = json.loads(DELAY_TOPOLOGY.read_text(encoding="utf-8"))

    for queue in topology["queues"]:
        arguments = queue["arguments"]
        assert arguments["x-message-ttl"] == 30000
        assert arguments["x-dead-letter-exchange"] == "meli.events"
        assert isinstance(arguments["x-dead-letter-routing-key"], str)
        assert arguments["x-dead-letter-routing-key"]
