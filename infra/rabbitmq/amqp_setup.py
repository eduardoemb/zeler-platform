from __future__ import annotations

import argparse
import json
from pathlib import Path

from infra.rabbitmq.topology import build_topology_definitions


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Generate idempotent RabbitMQ topology definitions"
    )
    parser.add_argument("--output", type=Path, default=Path("infra/rabbitmq/definitions.json"))
    args = parser.parse_args(argv)
    args.output.write_text(
        json.dumps(build_topology_definitions(), indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
