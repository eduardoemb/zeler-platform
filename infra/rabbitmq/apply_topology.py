from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aio_pika


@dataclass(frozen=True)
class RabbitMqTopologyApplyReport:
    ok: bool
    safe_to_execute: bool
    read_only: bool
    mutations_attempted: int
    summary: dict[str, int]


def _load_json_object(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        msg = f"JSON file must contain an object: {path}"
        raise ValueError(msg)
    return loaded


async def _apply_rabbitmq_topology_async(
    *,
    definitions_path: Path,
    amqp_url: str,
) -> RabbitMqTopologyApplyReport:
    definitions = _load_json_object(definitions_path)
    exchanges: dict[str, Any] = {}
    queues: dict[str, Any] = {}
    connection = await aio_pika.connect_robust(amqp_url, heartbeat=60)
    try:
        channel = await connection.channel()
        for exchange in definitions.get("exchanges", []):
            exchange_name = str(exchange.get("name", ""))
            exchanges[exchange_name] = await channel.declare_exchange(
                exchange_name,
                str(exchange.get("type", "")),
                durable=bool(exchange.get("durable", False)),
            )

        for queue in definitions.get("queues", []):
            queue_name = str(queue.get("name", ""))
            arguments = queue.get("arguments", {})
            if not isinstance(arguments, dict):
                arguments = {}
            queues[queue_name] = await channel.declare_queue(
                queue_name,
                durable=bool(queue.get("durable", False)),
                arguments=arguments,
            )

        binding_count = 0
        for binding in definitions.get("bindings", []):
            source = str(binding.get("source", ""))
            destination = str(binding.get("destination", ""))
            routing_key = str(binding.get("routing_key", ""))
            await queues[destination].bind(exchanges[source], routing_key=routing_key)
            binding_count += 1
    finally:
        await connection.close()

    summary = {
        "exchanges_declared": len(exchanges),
        "queues_declared": len(queues),
        "bindings_declared": binding_count,
    }
    return RabbitMqTopologyApplyReport(
        ok=True,
        safe_to_execute=False,
        read_only=False,
        mutations_attempted=sum(summary.values()),
        summary=summary,
    )


def apply_rabbitmq_topology(
    *,
    definitions_path: Path,
    amqp_url: str,
) -> RabbitMqTopologyApplyReport:
    return asyncio.run(
        _apply_rabbitmq_topology_async(
            definitions_path=definitions_path,
            amqp_url=amqp_url,
        )
    )


def render_apply_markdown(report: RabbitMqTopologyApplyReport) -> str:
    lines = [
        "# RabbitMQ Topology Apply",
        "",
        f"- ok: {str(report.ok).lower()}",
        f"- safe_to_execute: {str(report.safe_to_execute).lower()}",
        f"- read_only: {str(report.read_only).lower()}",
        f"- mutations_attempted: {report.mutations_attempted}",
        "- secrecy: AMQP URLs and credentials are never rendered.",
        "",
        "## Summary",
        "",
    ]
    lines.extend(f"- {key}: {value}" for key, value in sorted(report.summary.items()))
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply RabbitMQ topology idempotently.")
    parser.add_argument("--definitions", type=Path, default=Path("infra/rabbitmq/definitions.json"))
    parser.add_argument("--amqp-url", required=True)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args()

    report = apply_rabbitmq_topology(
        definitions_path=args.definitions,
        amqp_url=args.amqp_url,
    )
    if args.format == "json":
        print(json.dumps(report, default=lambda obj: obj.__dict__, indent=2), end="\n")
    else:
        print(render_apply_markdown(report), end="")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
