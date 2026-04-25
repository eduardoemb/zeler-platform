from __future__ import annotations

from infra.rabbitmq.topology import build_topology_definitions


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


def test_topology_uses_classic_queue_compatible_arguments() -> None:
    topology = build_topology_definitions()

    for queue in topology["queues"]:
        assert "x-delivery-limit" not in queue.get("arguments", {})
