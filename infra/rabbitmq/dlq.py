from __future__ import annotations

from dataclasses import dataclass

RETRY_DELAYS = ["1s", "5s", "30s", "2m", "10m"]


@dataclass(frozen=True)
class DlqDecision:
    destination: str
    alert: bool
    reason: str
    labels: dict[str, str]


def decide_failure_route(
    *, queue_name: str, routing_key: str, attempt: int, max_retries: int = 5
) -> DlqDecision:
    labels = {"queue": queue_name, "routing_key": routing_key}
    if attempt >= max_retries:
        return DlqDecision(
            destination=f"{queue_name}.dlq",
            alert=True,
            reason="retry_exhausted",
            labels=labels,
        )
    delay = RETRY_DELAYS[min(max(attempt - 1, 0), len(RETRY_DELAYS) - 1)]
    return DlqDecision(
        destination=f"{queue_name}.retry.{delay}",
        alert=False,
        reason="retry_scheduled",
        labels=labels,
    )
