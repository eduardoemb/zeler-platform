from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

SERVICES = ("gateway", "repricer", "sheets", "publicador", "autoreply")
MetricsSource = Callable[[str, str], int]
HealthSource = Callable[[Sequence[str], str], dict[str, bool]]
LogsSource = Callable[[str, str], list[dict[str, Any]]]
CountSource = Callable[[], int]
PausedAccountsSource = Callable[[str], int]


@dataclass(frozen=True)
class WaveEvaluation:
    passed: bool
    details: dict[str, dict[str, Any]]


def dlq_depth_flat(
    window: str = "24h",
    max_delta: int = 0,
    *,
    metrics_source: MetricsSource | None = None,
) -> tuple[bool, dict[str, Any]]:
    source = metrics_source or _missing_metrics_source
    delta = source("dlq_events_total", window)
    return delta <= max_delta, {"window": window, "delta": delta, "max_delta": max_delta}


def health_all_green(
    services: Sequence[str] = SERVICES,
    window: str = "1h",
    *,
    health_source: HealthSource | None = None,
) -> tuple[bool, dict[str, Any]]:
    source = health_source or _missing_health_source
    service_states = source(services, window)
    return all(service_states.get(service) is True for service in services), {
        "window": window,
        "services": service_states,
    }


def no_recent_errors(
    severity: str = "ERROR",
    window: str = "12h",
    *,
    logs_source: LogsSource | None = None,
) -> tuple[bool, dict[str, Any]]:
    source = logs_source or _missing_logs_source
    matches = source(severity, window)
    return len(matches) == 0, {"severity": severity, "window": window, "count": len(matches)}


def bootstrap_dispatcher_pending_count(
    max: int = 10,  # noqa: A002 - operator-facing predicate name from task text.
    *,
    bootstrap_source: CountSource | None = None,
) -> tuple[bool, dict[str, Any]]:
    source = bootstrap_source or _missing_count_source
    count = source()
    return count <= max, {"pending_count": count, "max": max}


def no_paused_accounts_below(
    threshold: int = 10,
    window: str = "24h",
    *,
    paused_accounts_source: PausedAccountsSource | None = None,
) -> tuple[bool, dict[str, Any]]:
    source = paused_accounts_source or _missing_paused_accounts_source
    count = source(window)
    return count <= threshold, {"paused_count": count, "threshold": threshold, "window": window}


def evaluate_wave(
    wave: int,
    *,
    metrics_source: MetricsSource | None = None,
    health_source: HealthSource | None = None,
    logs_source: LogsSource | None = None,
    bootstrap_source: CountSource | None = None,
    paused_accounts_source: PausedAccountsSource | None = None,
) -> WaveEvaluation:
    checks: list[tuple[str, Callable[[], tuple[bool, dict[str, Any]]]]] = [
        ("health_all_green", lambda: health_all_green(health_source=health_source)),
    ]
    if wave >= 2:
        checks.extend(
            [
                ("dlq_depth_flat", lambda: dlq_depth_flat(metrics_source=metrics_source)),
                ("no_recent_errors", lambda: no_recent_errors(logs_source=logs_source)),
                (
                    "bootstrap_dispatcher_pending_count",
                    lambda: bootstrap_dispatcher_pending_count(bootstrap_source=bootstrap_source),
                ),
                (
                    "no_paused_accounts_below",
                    lambda: no_paused_accounts_below(paused_accounts_source=paused_accounts_source),
                ),
            ]
        )
    details: dict[str, dict[str, Any]] = {}
    for name, check in checks:
        passed, check_details = check()
        details[name] = {"passed": passed, **check_details}
    return WaveEvaluation(
        passed=all(check_details["passed"] for check_details in details.values()),
        details=details,
    )


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Evaluate rollout wave readiness gates")
    parser.add_argument("--wave", type=int, required=True)
    args = parser.parse_args(argv)
    result = evaluate_wave(args.wave)
    _print_json(args.wave, result)
    raise SystemExit(0 if result.passed else 1)


def _print_json(wave: int, result: WaveEvaluation) -> None:
    gates = []
    for name, check_details in result.details.items():
        gates.append(
            {
                "gate": name,
                "status": "pass" if check_details["passed"] else "fail",
                "evidence": {key: value for key, value in check_details.items() if key != "passed"},
            }
        )
    print(
        json.dumps(
            {
                "wave": wave,
                "status": "pass" if result.passed else "fail",
                "gates": gates,
            }
        )
    )


def _missing_metrics_source(metric: str, window: str) -> int:
    raise RuntimeError(f"metrics_source is required for {metric} over {window}")


def _missing_health_source(services: Sequence[str], window: str) -> dict[str, bool]:
    raise RuntimeError(f"health_source is required for {','.join(services)} over {window}")


def _missing_logs_source(severity: str, window: str) -> list[dict[str, Any]]:
    raise RuntimeError(f"logs_source is required for {severity} over {window}")


def _missing_count_source() -> int:
    raise RuntimeError("bootstrap_source is required")


def _missing_paused_accounts_source(window: str) -> int:
    raise RuntimeError(f"paused_accounts_source is required over {window}")


if __name__ == "__main__":  # pragma: no cover
    main()
