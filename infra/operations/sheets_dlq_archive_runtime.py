"""Execute the approved Sheets DLQ archive (Q4-b, Q11-c).

Ordering is the whole safety argument: for every message the runtime decides a
disposition from the same evidence rules as the dry-run plan, writes the
sanitized archive record *first*, and only then removes the delivery from the
queue. A retained message is requeued untouched. If the archive write fails,
the message is requeued and the run stops, because an unexplained removal is
exactly what this work is supposed to eliminate.

The runtime holds one queue and one collection; it never publishes, never
touches another queue, and never mutates read models.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, cast

from infra.operations.sheets_dlq_archive import (
    ARCHIVE_COLLECTION,
    RETENTION,
    ArchiveDecision,
    build_archive_record,
    decide_archive,
)

DLQ_QUEUE_NAME = "zeler.sheets.events.dlq"
DEFAULT_LIMIT = 500


class ArchiveableDelivery(Protocol):
    """Minimal delivery surface: read the body, then ack or requeue once."""

    body: bytes

    async def ack(self) -> None: ...

    async def nack_requeue(self) -> None: ...


class ArchiveBroker(Protocol):
    """Narrow broker surface: bounded get plus the two terminal dispositions."""

    async def get_one(self, queue_name: str) -> ArchiveableDelivery | None: ...

    async def close_channel(self) -> None: ...


ArchiveStore = Callable[[Mapping[str, Any]], Awaitable[None]]


@dataclass(frozen=True)
class ArchiveRunReport:
    """Sanitized outcome of one bounded archive run."""

    archived: int
    retained: int
    by_reason: Mapping[str, int]
    stopped_reason: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "queue": DLQ_QUEUE_NAME,
            "archived": self.archived,
            "retained": self.retained,
            "by_reason": dict(self.by_reason),
            "stopped_reason": self.stopped_reason,
        }


async def run_archive(
    *,
    broker: ArchiveBroker,
    store: ArchiveStore,
    reconciled_models_until: Mapping[str, Mapping[str, datetime]],
    limit: int = DEFAULT_LIMIT,
    retention: Any = RETENTION,
    now: Callable[[], datetime] | None = None,
    queue_name: str = DLQ_QUEUE_NAME,
) -> ArchiveRunReport:
    """Archive provably-superseded messages and requeue everything else."""
    current = (now or (lambda: datetime.now(UTC)))()
    archived = 0
    retained = 0
    by_reason: dict[str, int] = {}
    stopped_reason: str | None = None
    try:
        for _ in range(limit):
            delivery = await broker.get_one(queue_name)
            if delivery is None:
                break
            message = _decode(delivery.body)
            decision = decide_archive(
                message,
                reconciled_models_until=reconciled_models_until,
                now=current,
                retention=retention,
            )
            by_reason[decision.reason_code] = by_reason.get(decision.reason_code, 0) + 1
            if not decision.archive:
                await delivery.nack_requeue()
                retained += 1
                continue
            record = build_archive_record(message, decision, now=current)
            try:
                await store(record)
            except Exception:  # noqa: BLE001 - any write failure must stop the run
                # Never remove a message whose reason was not recorded. Requeue
                # it and stop, so a partial write cannot silently drop history.
                await delivery.nack_requeue()
                retained += 1
                stopped_reason = "archive_write_failed"
                break
            await delivery.ack()
            archived += 1
    finally:
        await broker.close_channel()
    return ArchiveRunReport(
        archived=archived,
        retained=retained,
        by_reason=by_reason,
        stopped_reason=stopped_reason,
    )


def _decode(body: bytes) -> Mapping[str, Any]:
    try:
        decoded = json.loads(body)
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, Mapping) else {}


def decide_only(
    message: Mapping[str, Any],
    *,
    reconciled_models_until: Mapping[str, Mapping[str, datetime]],
    now: datetime,
    retention: Any = RETENTION,
) -> ArchiveDecision:
    """Expose the shared decision for callers that plan without a broker."""
    return decide_archive(
        message,
        reconciled_models_until=reconciled_models_until,
        now=now,
        retention=retention,
    )


def mongo_archive_store(db: Any) -> ArchiveStore:
    """Return a store that persists one sanitized record per archived message."""

    async def store(record: Mapping[str, Any]) -> None:
        await db[ARCHIVE_COLLECTION].insert_one(dict(record))

    return store


class AioPikaArchiveBroker:
    """Bounded get with ack/requeue, built lazily on one dedicated connection."""

    def __init__(self, amqp_url: str, *, connect: Any = None, timeout: float = 15.0) -> None:
        self._amqp_url = amqp_url
        self._connect = connect
        self._timeout = timeout
        self._connection: Any | None = None
        self._channel: Any | None = None

    async def _ensure_channel(self) -> Any:
        if self._channel is None:
            import aio_pika

            if self._connection is None:
                self._connection = await aio_pika.connect_robust(
                    self._amqp_url, timeout=self._timeout
                )
            self._channel = await self._connection.channel()
        return self._channel

    async def get_one(self, queue_name: str) -> ArchiveableDelivery | None:
        channel = await self._ensure_channel()
        message = await channel.get(queue_name, no_ack=False, fail=False)
        return None if message is None else cast(ArchiveableDelivery, _AioPikaDelivery(message))

    async def close_channel(self) -> None:
        channel, self._channel = self._channel, None
        connection, self._connection = self._connection, None
        if channel is not None:
            await asyncio.wait_for(channel.close(), timeout=self._timeout)
        if connection is not None:
            await asyncio.wait_for(connection.close(), timeout=self._timeout)


class _AioPikaDelivery:
    def __init__(self, message: Any) -> None:
        self._message = message

    @property
    def body(self) -> bytes:
        return bytes(self._message.body)

    async def ack(self) -> None:
        await self._message.ack()

    async def nack_requeue(self) -> None:
        await self._message.nack(requeue=True, multiple=False)


def _reconciled_coverages(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, datetime]]:
    """Fold *reconciled* markers into per-seller, per-model coverage edges.

    Only a source reconciliation proves that every source event inside the
    interval is already in the read model. An observed-only heartbeat says the
    loop audited what it observed; it makes no claim about an event that never
    produced an observation, so it must never authorize an archive.
    """
    coverage: dict[str, dict[str, datetime]] = {}
    for row in rows:
        seller = str(row.get("seller_id") or "").strip()
        model = str(row.get("read_model") or "").strip()
        if not seller or not model:
            continue
        if str(row.get("state") or "").strip().casefold() != "reconciled":
            continue
        if str(row.get("coverage_basis") or "").strip() == "observed_only":
            continue
        edge = _utc_or_none(row.get("reconciled_until"))
        if edge is None:
            continue
        current = coverage.setdefault(seller, {}).get(model)
        if current is None or edge > current:
            coverage[seller][model] = edge
    return coverage


def _utc_or_none(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    return None


async def load_reconciled_coverages(
    db: Any, seller_ids: Sequence[str]
) -> dict[str, dict[str, datetime]]:
    """Read the freshness markers that authorize an archive decision."""
    rows = (
        await db["sheets_read_model_freshness"]
        .find({"seller_id": {"$in": list(seller_ids)}})
        .to_list(None)
    )
    return _reconciled_coverages(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Archive provably superseded Sheets DLQ messages with a recorded "
            "reason. Requires explicit runtime and archive confirmations."
        )
    )
    parser.add_argument("--seller-id", action="append", required=True)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--confirm-approved-runtime", action="store_true")
    parser.add_argument("--confirm-archive", action="store_true")
    return parser


async def run_authorized_archive(
    *,
    db: Any,
    amqp_url: str,
    seller_ids: Sequence[str],
    limit: int = DEFAULT_LIMIT,
    now: Callable[[], datetime] | None = None,
) -> ArchiveRunReport:
    """Load marker coverage, then run one bounded archive pass over the DLQ."""
    coverage = await load_reconciled_coverages(db, seller_ids)
    broker = AioPikaArchiveBroker(amqp_url)
    return await run_archive(
        broker=broker,
        store=mongo_archive_store(db),
        reconciled_models_until=coverage,
        limit=limit,
        now=now,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Execute one approved archive run and print its sanitized report."""
    args = build_parser().parse_args(argv)
    if not (args.confirm_approved_runtime and args.confirm_archive):
        raise SystemExit(
            "explicit --confirm-approved-runtime and --confirm-archive confirmations "
            "are required for an archive write"
        )
    amqp_url = os.environ.get("RABBITMQ_URL")
    mongo_uri = os.environ.get("MONGO_URI")
    mongo_db = os.environ.get("MONGO_DB")
    if not amqp_url or not mongo_uri or not mongo_db:
        raise SystemExit("runtime broker and Mongo configuration are required")

    from motor.motor_asyncio import AsyncIOMotorClient

    client: Any = AsyncIOMotorClient(mongo_uri)

    async def _run() -> ArchiveRunReport:
        try:
            return await run_authorized_archive(
                db=client[mongo_db],
                amqp_url=amqp_url,
                seller_ids=args.seller_id,
                limit=args.limit,
            )
        finally:
            client.close()

    report = asyncio.run(_run())
    print(json.dumps(report.as_dict(), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
