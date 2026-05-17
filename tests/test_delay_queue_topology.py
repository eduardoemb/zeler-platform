from __future__ import annotations

import json
from pathlib import Path

DELAY_TOPOLOGY = Path("infra/rabbitmq/delay_queues.json")

DELAY_TARGET_QUEUES = (
    "zeler.repricer.items",
    "zeler.sheets.events",
    "zeler.autoreply.events",
)

RETIRED_FULLDOCK_QUEUE = "zeler.fulldock.events"


def test_each_worker_module_has_delay_queue_declared() -> None:
    topology = json.loads(DELAY_TOPOLOGY.read_text(encoding="utf-8"))
    queue_names = {queue["name"] for queue in topology["queues"]}

    for queue_name in DELAY_TARGET_QUEUES:
        assert f"{queue_name}.delay" in queue_names


def test_delay_topology_declares_publish_exchange_for_standalone_import() -> None:
    topology = json.loads(DELAY_TOPOLOGY.read_text(encoding="utf-8"))

    exchanges = {exchange["name"]: exchange for exchange in topology["exchanges"]}

    assert exchanges["meli.events"] == {"name": "meli.events", "type": "topic", "durable": True}


def test_delay_queues_are_bound_to_retry_publisher_routes() -> None:
    topology = json.loads(DELAY_TOPOLOGY.read_text(encoding="utf-8"))
    bindings = {
        (binding["source"], binding["destination"], binding["routing_key"])
        for binding in topology["bindings"]
    }

    for queue_name in DELAY_TARGET_QUEUES:
        delay_queue = f"{queue_name}.delay"
        assert ("meli.events", delay_queue, delay_queue) in bindings


def test_retired_fulldock_delay_queue_is_not_declared_or_bound() -> None:
    topology = json.loads(DELAY_TOPOLOGY.read_text(encoding="utf-8"))
    serialized_topology = json.dumps(topology, sort_keys=True)

    assert RETIRED_FULLDOCK_QUEUE not in serialized_topology


def test_delay_queue_has_dlx_to_main_queue() -> None:
    topology = json.loads(DELAY_TOPOLOGY.read_text(encoding="utf-8"))

    for queue in topology["queues"]:
        arguments = queue["arguments"]
        assert arguments["x-message-ttl"] == 30000
        assert arguments["x-dead-letter-exchange"] == ""
        assert arguments["x-dead-letter-routing-key"] == queue["name"].removesuffix(".delay")
