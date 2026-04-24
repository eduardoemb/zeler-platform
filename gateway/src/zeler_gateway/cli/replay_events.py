from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient

from zeler_gateway.config import Settings
from zeler_gateway.webhooks.publisher import (
    AioPikaWebhookPublisher,
    WebhookPublisher,
    publish_webhook_event,
)


@dataclass(frozen=True)
class ReplayResult:
    candidates: list[str]
    replayed: int


async def replay_events(
    db: Any,
    *,
    publisher: WebhookPublisher,
    topic: str | None = None,
    seller_id: int | None = None,
    since: datetime | None = None,
    dry_run: bool = False,
    limit: int = 100,
) -> ReplayResult:
    query: dict[str, Any] = {}
    if topic is not None:
        query["topic"] = topic
    if seller_id is not None:
        query["user_id"] = seller_id
    if since is not None:
        query["received_at"] = {"$gte": since}

    cursor = db["webhook_events"].find(query).sort("received_at", 1).limit(limit)
    candidates: list[str] = []
    replayed = 0
    async for event in cursor:
        candidates.append(str(event["_id"]))
        if dry_run:
            continue
        await publish_webhook_event(event, publisher=publisher, trace_id="replay")
        replayed += 1
    return ReplayResult(candidates=candidates, replayed=replayed)


async def _run_from_args(args: argparse.Namespace) -> ReplayResult:
    settings = Settings()
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(settings.mongo_uri)
    try:
        publisher = AioPikaWebhookPublisher(rabbitmq_url=settings.rabbitmq_url)
        since = datetime.fromisoformat(args.since) if args.since else None
        return await replay_events(
            client[settings.mongo_db],
            publisher=publisher,
            topic=args.topic,
            seller_id=args.seller_id,
            since=since,
            dry_run=args.dry_run,
            limit=args.limit,
        )
    finally:
        client.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Replay stored Meli webhook events")
    parser.add_argument("--seller-id", type=int)
    parser.add_argument("--topic")
    parser.add_argument("--since")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    result = asyncio.run(_run_from_args(args))
    for event_id in result.candidates:
        print(event_id)
    print(f"replayed={result.replayed}")


if __name__ == "__main__":
    main()
