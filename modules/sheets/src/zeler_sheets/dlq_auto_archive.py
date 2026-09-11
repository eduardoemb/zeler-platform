"""Per-cycle DLQ auto-archive wiring (Q4-b, Q11-c).

The stuck queue must not be a one-off cleanup that silently refills. The refresh
loop owns a bounded archive pass, but the loop itself must not import the
maintenance CLI package: the operational surface stays behind this adapter so
the worker module keeps its dependency direction.

The archive decision is unchanged and stays evidence-based. A message is
removed only when a reconciled marker already proves its window is in the read
model, or when it is past the retention bound; everything else is requeued
untouched. A missing broker configuration fails loudly at build time instead of
quietly skipping the archive.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

__all__ = ["build_dlq_auto_archiver"]


def build_dlq_auto_archiver(db: Any, *, sellers: frozenset[str]) -> Callable[[], Awaitable[Any]]:
    """Return the per-cycle DLQ archive for the configured sellers."""
    from infra.operations.sheets_dlq_archive_runtime import (
        AioPikaArchiveBroker,
        load_reconciled_coverages,
        mongo_archive_store,
        run_archive,
    )

    amqp_url = os.environ.get("RABBITMQ_URL")
    if not amqp_url:
        raise RuntimeError("RABBITMQ_URL is required when the DLQ auto-archive is enabled")
    ordered_sellers = tuple(sorted(sellers))

    async def archive_once() -> Any:
        coverage = await load_reconciled_coverages(db, ordered_sellers)
        report = await run_archive(
            broker=AioPikaArchiveBroker(amqp_url),
            store=mongo_archive_store(db),
            reconciled_models_until=coverage,
        )
        # The report is already sanitized (counts and reason codes only), so it
        # is safe to log: a queue that starts growing again is then visible in
        # the same place as the rest of the refresh cycle.
        logger.info("zelerdata.dlq_auto_archive", **report.as_dict())
        return report

    return archive_once
