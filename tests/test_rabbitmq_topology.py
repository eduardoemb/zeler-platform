from __future__ import annotations

import json
from pathlib import Path

from infra.operations.preflight import RABBITMQ_WORKER_TOPOLOGY
from infra.rabbitmq.topology import (
    ACTIVE_QUEUE_DEAD_LETTER_ROUTING_KEYS,
    build_topology_definitions,
)

from zeler_sheets.consumer import (
    SHEETS_DEFAULT_ROUTING_KEYS,
    SHEETS_EVENTS_DLX,
    SHEETS_EVENTS_QUEUE,
)

ROOT = Path(__file__).resolve().parents[1]


def test_topology_declares_meli_events_topic_exchange_and_module_queues() -> None:
    topology = build_topology_definitions()

    exchanges = {exchange["name"]: exchange for exchange in topology["exchanges"]}
    assert exchanges["meli.events"]["type"] == "topic"
    assert exchanges["meli.events"]["durable"] is True

    queues = {queue["name"]: queue for queue in topology["queues"]}
    for queue_name in [
        "zeler.repricer.items",
        "zeler.repricer.items_prices",
        "zeler.sheets.orders",
        "zeler.publicador.questions",
        "zeler.publicador.messages",
        "zeler.autoreply.events",
    ]:
        assert queues[queue_name]["durable"] is True
        assert queues[f"{queue_name}.dlq"]["durable"] is True
        assert queues[queue_name]["arguments"]["x-dead-letter-exchange"] == f"{queue_name}.dlx"


def test_topology_bindings_include_supported_module_routing_keys() -> None:
    topology = build_topology_definitions()
    bindings = {
        (binding["destination"], binding["routing_key"]) for binding in topology["bindings"]
    }

    assert ("zeler.repricer.items", "items.*") in bindings
    assert ("zeler.repricer.items_prices", "items.price_updated") in bindings
    assert ("zeler.sheets.orders", "orders.*") in bindings
    assert ("zeler.publicador.questions", "questions.*") in bindings
    assert ("zeler.publicador.messages", "messages.*") in bindings
    assert not any(destination.startswith("zeler.fulldock") for destination, _ in bindings)
    assert ("zeler.autoreply.events", "questions.new") in bindings
    assert ("zeler.autoreply.events", "messages.new") in bindings


def test_sheets_worker_queue_contract_matches_topology_and_preflight() -> None:
    topology = build_topology_definitions()

    exchanges = {exchange["name"]: exchange for exchange in topology["exchanges"]}
    queues = {queue["name"]: queue for queue in topology["queues"]}
    bindings = {
        (binding["source"], binding["destination"], binding["routing_key"])
        for binding in topology["bindings"]
    }

    sheets_topology = RABBITMQ_WORKER_TOPOLOGY["sheets"]
    assert sheets_topology is not None
    assert sheets_topology.queue == SHEETS_EVENTS_QUEUE
    assert sheets_topology.dlq == f"{SHEETS_EVENTS_QUEUE}.dlq"

    assert exchanges[SHEETS_EVENTS_DLX] == {
        "name": SHEETS_EVENTS_DLX,
        "type": "direct",
        "durable": True,
    }
    assert queues[SHEETS_EVENTS_QUEUE]["durable"] is True
    assert queues[SHEETS_EVENTS_QUEUE]["arguments"] == {
        "x-dead-letter-exchange": SHEETS_EVENTS_DLX,
        "x-dead-letter-routing-key": f"{SHEETS_EVENTS_QUEUE}.dlq",
    }
    assert ACTIVE_QUEUE_DEAD_LETTER_ROUTING_KEYS[SHEETS_EVENTS_QUEUE] == (
        f"{SHEETS_EVENTS_QUEUE}.dlq"
    )
    assert queues[sheets_topology.dlq]["durable"] is True
    assert (SHEETS_EVENTS_DLX, sheets_topology.dlq, f"{SHEETS_EVENTS_QUEUE}.dlq") in bindings

    for routing_key in SHEETS_DEFAULT_ROUTING_KEYS:
        assert ("meli.events", SHEETS_EVENTS_QUEUE, routing_key) in bindings


def test_topology_includes_new_queues() -> None:
    topology = build_topology_definitions()

    queue_names = {queue["name"] for queue in topology["queues"]}

    assert "zeler.repricer.price_suggestion" in queue_names
    assert "zeler.sheets.user_products" in queue_names
    assert "webhooks.unknown.dlq" in queue_names
    assert not any(queue_name.startswith("zeler.fulldock") for queue_name in queue_names)


def test_active_autoreply_queue_matches_migrated_dlq_arguments() -> None:
    topology = build_topology_definitions()
    queues = {queue["name"]: queue for queue in topology["queues"]}
    bindings = {
        (binding["source"], binding["destination"], binding["routing_key"])
        for binding in topology["bindings"]
    }

    queue_name = "zeler.autoreply.events"
    dlq_name = f"{queue_name}.dlq"
    dlx_name = f"{queue_name}.dlx"
    assert queues[queue_name]["arguments"] == {
        "x-dead-letter-exchange": dlx_name,
        "x-dead-letter-routing-key": dlq_name,
    }
    assert queues[dlq_name]["arguments"] == {}
    assert (dlx_name, dlq_name, dlq_name) in bindings


def test_unknown_dlq_bound_to_meli_events_exchange() -> None:
    topology = build_topology_definitions()

    bindings = {
        (binding["source"], binding["destination"], binding["routing_key"])
        for binding in topology["bindings"]
    }

    assert ("meli.events", "webhooks.unknown.dlq", "webhooks.unknown.dlq") in bindings


def test_topology_uses_classic_queue_compatible_arguments() -> None:
    topology = build_topology_definitions()

    for queue in topology["queues"]:
        assert "x-delivery-limit" not in queue.get("arguments", {})


def test_generated_definitions_json_matches_topology_builder() -> None:
    definitions = json.loads((ROOT / "infra/rabbitmq/definitions.json").read_text())

    assert definitions == build_topology_definitions()
