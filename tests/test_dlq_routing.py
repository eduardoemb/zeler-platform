from __future__ import annotations

from infra.rabbitmq.dlq import DlqDecision, decide_failure_route


def test_exhausted_retries_routes_to_dlq_and_alerts() -> None:
    decision = decide_failure_route(
        queue_name="zeler.repricer.items", routing_key="items.updated", attempt=5, max_retries=5
    )

    assert decision == DlqDecision(
        destination="zeler.repricer.items.dlq",
        alert=True,
        reason="retry_exhausted",
        labels={"queue": "zeler.repricer.items", "routing_key": "items.updated"},
    )


def test_retryable_failure_routes_to_delay_queue() -> None:
    decision = decide_failure_route(
        queue_name="zeler.repricer.items", routing_key="items.updated", attempt=2, max_retries=5
    )

    assert decision.destination == "zeler.repricer.items.retry.5s"
    assert decision.alert is False
    assert decision.reason == "retry_scheduled"
