"""Backfill ZELERDATA_RETIROS from the Full notifications already stored.

The gateway keeps every ``fbm_stock_operations`` notification in
``webhook_events`` (45-day TTL), including the ones it could not publish. This
tool re-reads those operations one by one through the gateway
(``GET /stock/fulfillment/operations/<id>``, module ``sheets``) and records them
exactly as the worker does: withdrawal operations in ``sheets_full_operations``
and the observed coverage marker. It never uses the operations search, whose
quota is very low.

Dry run is the default: it reads Mongo only and makes no gateway call. Writing
needs ``--execute --confirm-production-write``. Re-running is idempotent. A 429
stops the run; re-run later. Output is one sanitized JSON line with counts and
dates only, never operation or inventory identifiers.

Run it inside ``sheets-worker`` on the approved runtime::

    /app/.venv/bin/python -m infra.operations.zelerdata_full_withdrawals_backfill \\
      --seller-id <seller> --confirm-approved-runtime [--execute --confirm-production-write]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from zeler_platform_core.clients.meli_gateway_client import GatewayRateLimitError
from zeler_sheets.formulas.full_withdrawals import pair_full_withdrawals
from zeler_sheets.full_operations import (
    FBM_STOCK_OPERATIONS_TOPIC,
    FULL_OPERATIONS_COLLECTION,
    FULL_WITHDRAWALS_MARKER_SOURCE,
    FULL_WITHDRAWALS_READ_MODEL,
    READ_MODEL_FRESHNESS_COLLECTION,
    WITHDRAWAL_TYPES,
    acquire_full_operation,
    full_operation_id_from_resource,
)

DEFAULT_LIMIT = 500
MAX_LIMIT = 5000
DEFAULT_INTERVAL_SECONDS = 1.0


async def backfill_full_withdrawals(
    *,
    db: Any,
    gateway: Any,
    seller_id: str,
    limit: int,
    execute: bool,
    now_fn: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
) -> dict[str, Any]:
    notifications = (
        await db["webhook_events"]
        .find(
            {"topic": FBM_STOCK_OPERATIONS_TOPIC, "user_id": int(seller_id)},
            {"_id": 0, "resource": 1, "received_at": 1},
        )
        .sort([("received_at", 1), ("_id", 1)])
        .to_list(limit + 1)
    )
    truncated = len(notifications) > limit
    notifications = notifications[:limit]
    operation_ids: list[str] = []
    invalid_resources = 0
    for notification in notifications:
        try:
            operation_ids.append(full_operation_id_from_resource(str(notification["resource"])))
        except (KeyError, ValueError):
            invalid_resources += 1
    operation_ids = list(dict.fromkeys(operation_ids))
    received = [stamp for row in notifications if (stamp := _utc_or_none(row.get("received_at")))]
    report: dict[str, Any] = {
        "mode": "execute" if execute else "dry_run",
        "notifications": len(notifications),
        "operations": len(operation_ids),
        "invalid_resources": invalid_resources,
        "truncated": truncated,
        "oldest_notification_at": _iso(min(received, default=None)),
        "newest_notification_at": _iso(max(received, default=None)),
        "already_stored": await db[FULL_OPERATIONS_COLLECTION].count_documents(
            {"seller_id": seller_id, "operation_id": {"$in": operation_ids}}
        ),
        "fetched": 0,
        "outcomes": {},
        "errors": {},
        "stopped_reason": None,
    }
    if execute:
        outcomes: Counter[str] = Counter()
        errors: Counter[str] = Counter()
        for position, operation_id in enumerate(operation_ids):
            if position:
                await sleep(interval_seconds)
            report["fetched"] += 1
            try:
                outcome = await acquire_full_operation(
                    db=db,
                    gateway=gateway,
                    seller_id=seller_id,
                    resource=f"/stock/fulfillment/operations/{operation_id}",
                    now=now_fn(),
                )
            except GatewayRateLimitError:
                report["stopped_reason"] = "rate_limited"
                break
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429:
                    report["stopped_reason"] = "rate_limited"
                    break
                errors[f"http_{exc.response.status_code}"] += 1
                continue
            except (httpx.RequestError, TimeoutError):
                errors["transport"] += 1
                continue
            except ValueError:
                errors["invalid_operation"] += 1
                continue
            outcomes[outcome] += 1
        report["outcomes"] = dict(sorted(outcomes.items()))
        report["errors"] = dict(sorted(errors.items()))
    report["summary"] = await full_withdrawals_summary(db, seller_id=seller_id)
    return report


async def full_withdrawals_summary(db: Any, *, seller_id: str) -> dict[str, Any]:
    """What RETIROS serves for the seller now, as counts only."""
    marker = await db[READ_MODEL_FRESHNESS_COLLECTION].find_one(
        {
            "_id": f"{seller_id}:{FULL_WITHDRAWALS_READ_MODEL}",
            "seller_id": seller_id,
            "source": FULL_WITHDRAWALS_MARKER_SOURCE,
        }
    )
    operations = (
        await db[FULL_OPERATIONS_COLLECTION]
        .find(
            {"seller_id": seller_id, "type": {"$in": sorted(WITHDRAWAL_TYPES)}},
            {
                "_id": 0,
                "operation_id": 1,
                "inventory_id": 1,
                "type": 1,
                "date_created": 1,
                "detail": 1,
            },
        )
        .to_list(None)
    )
    withdrawals, unmatched = pair_full_withdrawals(operations)
    return {
        "coverage_from": _iso(_utc_or_none(marker.get("date_from")) if marker else None),
        "operations_by_type": dict(sorted(Counter(str(row["type"]) for row in operations).items())),
        "withdrawals_by_status": dict(sorted(Counter(row.status for row in withdrawals).items())),
        "unmatched_by_type": dict(sorted(Counter(row.kind for row in unmatched).items())),
        "approximate_rows": sum(row.approximate for row in withdrawals),
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=True, description=__doc__.splitlines()[0])
    parser.add_argument("--seller-id", required=True)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--interval-seconds", type=float, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-approved-runtime", action="store_true")
    parser.add_argument("--confirm-production-write", action="store_true")
    return parser


def _validate(args: argparse.Namespace) -> str | None:
    if not args.confirm_approved_runtime:
        return "APPROVED_RUNTIME_CONFIRMATION_REQUIRED"
    if args.execute and not args.confirm_production_write:
        return "PRODUCTION_WRITE_CONFIRMATION_REQUIRED"
    if args.confirm_production_write and not args.execute:
        return "PRODUCTION_WRITE_CONFIRMATION_REQUIRES_EXECUTE"
    seller = str(args.seller_id)
    if not seller.isascii() or not seller.isdecimal() or len(seller) > 20:
        return "INVALID_SELLER"
    if not 1 <= args.limit <= MAX_LIMIT:
        return "INVALID_LIMIT"
    if not 0 <= args.interval_seconds <= 60:
        return "INVALID_INTERVAL"
    return None


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    from motor.motor_asyncio import AsyncIOMotorClient

    mongo_uri, mongo_db = os.environ.get("MONGO_URI"), os.environ.get("MONGO_DB")
    if not mongo_uri or not mongo_db:
        raise RuntimeError("runtime Mongo configuration is required")
    client: AsyncIOMotorClient[Any] = AsyncIOMotorClient(mongo_uri, tz_aware=True)
    try:
        gateway = None
        if args.execute:
            from google.cloud import kms

            from zeler_sheets.consumer import DEFAULT_GATEWAY_BASE_URL, make_meli_gateway_client

            gateway = make_meli_gateway_client(
                base_url=os.environ.get("GATEWAY_BASE_URL", DEFAULT_GATEWAY_BASE_URL),
                kms_client=kms.KeyManagementServiceClient(),
            )
        return await backfill_full_withdrawals(
            db=client[mongo_db],
            gateway=gateway,
            seller_id=str(args.seller_id),
            limit=args.limit,
            execute=bool(args.execute),
            interval_seconds=args.interval_seconds,
        )
    finally:
        client.close()


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    refusal = _validate(args)
    if refusal is not None:
        print(refusal, file=sys.stderr)
        return 2
    try:
        output = asyncio.run(_run(args))
    except Exception as exc:  # noqa: BLE001 - report the class only, never runtime values.
        print(f"BACKFILL_FAILED {type(exc).__name__}", file=sys.stderr)
        return 1
    sys.stdout.write(json.dumps(output, sort_keys=True, separators=(",", ":")) + "\n")
    return 0


def _utc_or_none(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
