from __future__ import annotations

from infra.rabbitmq.topology import EXCHANGE, QUEUE_BINDINGS

from zeler_gateway.webhooks.classifier import TOPIC_ROUTING_KEYS, classify_webhook_topic
from zeler_platform_core.runtime.manifest import validate_manifest


def test_repricer_manifest_subscriptions_match_topology_and_classifier_outputs() -> None:
    manifest = validate_manifest("modules/repricer/manifest.yaml")
    topology_routing_keys = _routing_keys_for_queue_prefix("zeler.repricer.")
    emitted_routing_keys = {
        classify_webhook_topic(topic, _resource_for_topic(topic)).routing_key
        for topic in ("items", "items_prices")
    }

    assert set(manifest.routing_keys) == topology_routing_keys
    assert emitted_routing_keys <= _covered_routing_keys(
        emitted_routing_keys, patterns=manifest.routing_keys
    )


def _routing_keys_for_queue_prefix(queue_prefix: str) -> set[str]:
    return {
        routing_key
        for queue_name, routing_keys in QUEUE_BINDINGS.items()
        if queue_name.startswith(queue_prefix)
        for routing_key in routing_keys
    }


def _covered_routing_keys(routing_keys: set[str], *, patterns: list[str]) -> set[str]:
    return {
        routing_key
        for routing_key in routing_keys
        if any(_rabbitmq_topic_matches(pattern, routing_key) for pattern in patterns)
    }


def _rabbitmq_topic_matches(pattern: str, routing_key: str) -> bool:
    pattern_parts = pattern.split(".")
    key_parts = routing_key.split(".")
    return _topic_parts_match(pattern_parts, key_parts)


def _topic_parts_match(pattern_parts: list[str], key_parts: list[str]) -> bool:
    if not pattern_parts:
        return not key_parts
    pattern_segment = pattern_parts[0]
    if pattern_segment == "#":
        return any(
            _topic_parts_match(pattern_parts[1:], key_parts[index:])
            for index in range(len(key_parts) + 1)
        )
    if not key_parts:
        return False
    if pattern_segment == "*" or pattern_segment == key_parts[0]:
        return _topic_parts_match(pattern_parts[1:], key_parts[1:])
    return False


def _resource_for_topic(topic: str) -> str:
    return "/items/MLA123/prices" if topic == "items_prices" else "/items/MLA123"


def test_repricer_contract_topics_are_explicit_classifier_topics() -> None:
    assert TOPIC_ROUTING_KEYS["items"] == "items.updated"
    assert TOPIC_ROUTING_KEYS["items_prices"] == "items.price_updated"
    assert EXCHANGE == "meli.events"
