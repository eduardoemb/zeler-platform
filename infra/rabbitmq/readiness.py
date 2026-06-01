from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import aio_pika

Severity = Literal["pass", "fail"]


@dataclass(frozen=True)
class RabbitMqReadinessFinding:
    severity: Severity
    resource_type: Literal["exchange", "queue", "binding"]
    resource_name: str
    detail: str


@dataclass(frozen=True)
class RabbitMqReadinessReport:
    mode: Literal["offline", "offline-with-export", "amqp-passive"]
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


async def _passive_exchange_exists(
    *,
    connection: Any,
    name: str,
    exchange_type: str,
    durable: bool,
) -> bool:
    channel = await connection.channel()
    try:
        await channel.declare_exchange(
            name,
            exchange_type,
            durable=durable,
            passive=True,
        )
    except (aio_pika.exceptions.AMQPException, RuntimeError, TimeoutError):
        return False
    finally:
        with contextlib.suppress(aio_pika.exceptions.AMQPException, RuntimeError, TimeoutError):
            await channel.close()
    return True


async def _passive_queue_exists(
    *,
    connection: Any,
    name: str,
    durable: bool,
    arguments: dict[str, Any],
) -> bool:
    channel = await connection.channel()
    try:
        await channel.declare_queue(
            name,
            durable=durable,
            arguments=arguments,
            passive=True,
        )
    except (aio_pika.exceptions.AMQPException, RuntimeError, TimeoutError):
        return False
    finally:
        with contextlib.suppress(aio_pika.exceptions.AMQPException, RuntimeError, TimeoutError):
            await channel.close()
    return True


async def _build_rabbitmq_amqp_passive_readiness_report_async(
    *,
    definitions_path: Path,
    amqp_url: str,
    timeout_seconds: float,
) -> RabbitMqReadinessReport:
    definitions = _load_json_object(definitions_path)
    expected_exchanges = list(definitions.get("exchanges", []))
    expected_queues = list(definitions.get("queues", []))
    expected_bindings = list(definitions.get("bindings", []))
    summary = {
        "expected_exchanges": len(expected_exchanges),
        "expected_queues": len(expected_queues),
        "expected_bindings": len(expected_bindings),
        "checked_exchanges": 0,
        "checked_queues": 0,
        "missing_exchanges": 0,
        "missing_queues": 0,
        "missing_bindings": 0,
        "unchecked_bindings": len(expected_bindings),
    }
    findings: list[RabbitMqReadinessFinding] = []
    connection = None
    try:
        connection = await asyncio.wait_for(
            aio_pika.connect_robust(amqp_url, heartbeat=60),
            timeout=timeout_seconds,
        )
    except (aio_pika.exceptions.AMQPException, RuntimeError, TimeoutError, OSError):
        findings.append(
            RabbitMqReadinessFinding(
                severity="fail",
                resource_type="exchange",
                resource_name="amqp",
                detail="Unable to connect to RabbitMQ with the provided AMQP URL.",
            )
        )
    else:
        findings.append(
            RabbitMqReadinessFinding(
                severity="pass",
                resource_type="exchange",
                resource_name="amqp",
                detail="Connected to RabbitMQ using AMQP passive readiness mode.",
            )
        )
        for exchange in expected_exchanges:
            name = str(exchange.get("name", ""))
            exists = await _passive_exchange_exists(
                connection=connection,
                name=name,
                exchange_type=str(exchange.get("type", "")),
                durable=bool(exchange.get("durable", False)),
            )
            if exists:
                summary["checked_exchanges"] += 1
            else:
                summary["missing_exchanges"] += 1
                findings.append(
                    RabbitMqReadinessFinding(
                        severity="fail",
                        resource_type="exchange",
                        resource_name=name,
                        detail="Expected exchange is absent or not passively declarable.",
                    )
                )

        for queue in expected_queues:
            name = str(queue.get("name", ""))
            arguments = queue.get("arguments", {})
            if not isinstance(arguments, dict):
                arguments = {}
            exists = await _passive_queue_exists(
                connection=connection,
                name=name,
                durable=bool(queue.get("durable", False)),
                arguments=arguments,
            )
            if exists:
                summary["checked_queues"] += 1
            else:
                summary["missing_queues"] += 1
                findings.append(
                    RabbitMqReadinessFinding(
                        severity="fail",
                        resource_type="queue",
                        resource_name=name,
                        detail="Expected queue is absent or not passively declarable.",
                    )
                )
    finally:
        if connection is not None:
            with contextlib.suppress(aio_pika.exceptions.AMQPException, RuntimeError, TimeoutError):
                await connection.close()

    if not any(finding.severity == "fail" for finding in findings):
        findings.append(
            RabbitMqReadinessFinding(
                severity="pass",
                resource_type="binding",
                resource_name="management-export-unavailable",
                detail=(
                    "Bindings are not inspectable in AMQP passive mode; verify them with a "
                    "management export or after idempotent topology apply plus functional smoke."
                ),
            )
        )

    return RabbitMqReadinessReport(
        mode="amqp-passive",
        safe_to_execute=True,
        read_only=True,
        management_export_checked=False,
        mutations_attempted=0,
        summary=summary,
        findings=tuple(findings),
    )


def build_rabbitmq_amqp_passive_readiness_report(
    *,
    definitions_path: Path,
    amqp_url: str,
    timeout_seconds: float = 10,
) -> RabbitMqReadinessReport:
    return asyncio.run(
        _build_rabbitmq_amqp_passive_readiness_report_async(
            definitions_path=definitions_path,
            amqp_url=amqp_url,
            timeout_seconds=timeout_seconds,
        )
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
        "local JSON files, optional management exports, or passively declares expected "
        "AMQP resources.",
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
    parser.add_argument("--amqp-url", default=None)
    parser.add_argument("--timeout-seconds", type=float, default=10)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args()

    if args.amqp_url is not None:
        report = build_rabbitmq_amqp_passive_readiness_report(
            definitions_path=args.definitions,
            amqp_url=args.amqp_url,
            timeout_seconds=args.timeout_seconds,
        )
    else:
        report = build_rabbitmq_readiness_report(
            definitions_path=args.definitions,
            management_export_path=args.management_export,
        )
    if args.format == "json":
        print(json.dumps(report, default=lambda obj: obj.__dict__, indent=2), end="\n")
    else:
        print(render_rabbitmq_markdown(report), end="")
    return 1 if any(finding.severity == "fail" for finding in report.findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
