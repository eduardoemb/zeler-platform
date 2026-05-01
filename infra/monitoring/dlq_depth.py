from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx


async def fetch_dlq_depth(
    management_url: str,
    vhost: str,
    queue_name: str,
    *,
    http_client: Any | None = None,
) -> int:
    encoded_vhost = quote(vhost, safe="")
    encoded_queue = quote(queue_name, safe="")
    url = f"{management_url.rstrip('/')}/api/queues/{encoded_vhost}/{encoded_queue}"
    if http_client is not None:
        response = await http_client.get(url)
        response.raise_for_status()
        return int(response.json()["messages"])
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        return int(response.json()["messages"])


def main(
    argv: Sequence[str] | None = None,
    *,
    fetcher: Callable[[str, str, str], int] | None = None,
    now: Callable[[], str] | None = None,
) -> None:
    parser = argparse.ArgumentParser(description="Read RabbitMQ DLQ depth via management API")
    parser.add_argument("--management-url", required=True)
    parser.add_argument("--vhost", required=True)
    parser.add_argument("--queue", required=True)
    args = parser.parse_args(argv)

    if fetcher is None:
        depth = asyncio.run(fetch_dlq_depth(args.management_url, args.vhost, args.queue))
    else:
        depth = fetcher(args.management_url, args.vhost, args.queue)
    checked_at = now() if now is not None else datetime.now(UTC).isoformat().replace("+00:00", "Z")
    print(json.dumps({"queue": args.queue, "depth": depth, "checked_at": checked_at}))


if __name__ == "__main__":  # pragma: no cover
    main()
