from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

Severity = Literal["pass", "fail"]


@dataclass(frozen=True)
class RabbitMqReadinessFinding:
    severity: Severity
    resource_type: Literal["exchange", "queue", "binding"]
    resource_name: str
    detail: str


@dataclass(frozen=True)
class RabbitMqReadinessReport:
    mode: Literal["offline", "offline-with-export"]
    safe_to_execute: bool
    read_only: bool
    management_export_checked: bool
    mutations_attempted: int
    summary: dict[str, int]
    findings: tuple[RabbitMqReadinessFinding, ...]


def _load_json_object(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        msg = f"JSON file must contain an object: {path}"
        raise ValueError(msg)
    return loaded


def _exchange_key(exchange: dict[str, Any]) -> tuple[str, str, bool]:
    return (
        str(exchange.get("name", "")),
        str(exchange.get("type", "")),
        bool(exchange.get("durable", False)),
    )


def _queue_key(queue: dict[str, Any]) -> tuple[str, bool, str]:
    arguments = queue.get("arguments", {})
    if isinstance(arguments, dict) and arguments.get("x-queue-type") == "classic":
        arguments = {key: value for key, value in arguments.items() if key != "x-queue-type"}
    return (
        str(queue.get("name", "")),
        bool(queue.get("durable", False)),
        json.dumps(arguments, sort_keys=True),
    )


def _binding_key(binding: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(binding.get("source", "")),
        str(binding.get("destination", "")),
        str(binding.get("routing_key", binding.get("routing_key", ""))),
    )


def build_rabbitmq_readiness_report(
    *,
    definitions_path: Path,
    management_export_path: Path | None = None,
) -> RabbitMqReadinessReport:
    definitions = _load_json_object(definitions_path)
    expected_exchanges = {_exchange_key(exchange) for exchange in definitions.get("exchanges", [])}
    expected_queues = {_queue_key(queue) for queue in definitions.get("queues", [])}
    expected_bindings = {_binding_key(binding) for binding in definitions.get("bindings", [])}

    summary = {
        "expected_exchanges": len(expected_exchanges),
        "expected_queues": len(expected_queues),
        "expected_bindings": len(expected_bindings),
        "missing_exchanges": 0,
        "missing_queues": 0,
        "missing_bindings": 0,
    }
    findings: list[RabbitMqReadinessFinding] = []

    if management_export_path is not None:
        current = _load_json_object(management_export_path)
        current_exchanges = {_exchange_key(exchange) for exchange in current.get("exchanges", [])}
        current_queues = {_queue_key(queue) for queue in current.get("queues", [])}
        current_bindings = {_binding_key(binding) for binding in current.get("bindings", [])}

        missing_exchanges = sorted(expected_exchanges - current_exchanges)
        missing_queues = sorted(expected_queues - current_queues)
        missing_bindings = sorted(expected_bindings - current_bindings)
        summary["missing_exchanges"] = len(missing_exchanges)
        summary["missing_queues"] = len(missing_queues)
        summary["missing_bindings"] = len(missing_bindings)

        findings.extend(
            RabbitMqReadinessFinding(
                severity="fail",
                resource_type="exchange",
                resource_name=f"{name} ({exchange_type}, durable={durable})",
                detail="Expected exchange is absent from management export.",
            )
            for name, exchange_type, durable in missing_exchanges
        )
        findings.extend(
            RabbitMqReadinessFinding(
                severity="fail",
                resource_type="queue",
                resource_name=name,
                detail=(
                    "Expected queue is absent from management export or differs "
                    "in durability/arguments."
                ),
            )
            for name, _durable, _arguments in missing_queues
        )
        findings.extend(
            RabbitMqReadinessFinding(
                severity="fail",
                resource_type="binding",
                resource_name=f"{source} -> {destination} [{routing_key}]",
                detail="Expected binding is absent from management export.",
            )
            for source, destination, routing_key in missing_bindings
        )

    if not findings:
        findings.append(
            RabbitMqReadinessFinding(
                severity="pass",
                resource_type="exchange",
                resource_name="definitions",
                detail="Expected topology definition is internally readable; no drift detected.",
            )
        )

    return RabbitMqReadinessReport(
        mode="offline-with-export" if management_export_path is not None else "offline",
        safe_to_execute=True,
        read_only=True,
        management_export_checked=management_export_path is not None,
        mutations_attempted=0,
        summary=summary,
        findings=tuple(findings),
    )


def render_rabbitmq_markdown(report: RabbitMqReadinessReport) -> str:
    lines = [
        "# RabbitMQ Readiness Validation",
        "",
        f"- mode: {report.mode}",
        f"- safe_to_execute: {str(report.safe_to_execute).lower()}",
        f"- read_only: {str(report.read_only).lower()}",
        f"- mutations_attempted: {report.mutations_attempted}",
        "- Safety model: No RabbitMQ mutations are attempted; this command only reads "
        "local JSON files and optional management exports.",
        "",
        "## Summary",
        "",
    ]
    lines.extend(f"- {key}: {value}" for key, value in sorted(report.summary.items()))
    lines.extend(["", "## Findings", ""])
    lines.extend(
        f"- [{finding.severity}] {finding.resource_type} "
        f"`{finding.resource_name}` — {finding.detail}"
        for finding in report.findings
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate RabbitMQ topology readiness without mutation."
    )
    parser.add_argument("--definitions", type=Path, default=Path("infra/rabbitmq/definitions.json"))
    parser.add_argument("--management-export", type=Path, default=None)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args()

    report = build_rabbitmq_readiness_report(
        definitions_path=args.definitions,
        management_export_path=args.management_export,
    )
    if args.format == "json":
        print(json.dumps(report, default=lambda obj: obj.__dict__, indent=2), end="\n")
    else:
        print(render_rabbitmq_markdown(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
