from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient

_MISSING = object()
_TYPES = {"returns", "mediations", "fulfillment", "cancel_purchase"}
_BASES = {"v2_return_order", "verified_low_cost_no_row"}
_WINDOW_SORT = {False: "false", None: "null", True: "true", "unknown": "unknown"}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--seller-id")
    parser.add_argument("--date-from")
    parser.add_argument("--date-to")
    parser.add_argument("--confirm-approved-runtime", action="store_true")
    return parser


def _date_window(args: argparse.Namespace) -> tuple[datetime, datetime] | None:
    if bool(args.date_from) != bool(args.date_to):
        raise ValueError
    if not args.date_from:
        return None
    try:
        start, end = date.fromisoformat(args.date_from), date.fromisoformat(args.date_to)
    except ValueError as exc:
        raise ValueError from exc
    if end < start:
        raise ValueError
    return (
        datetime.combine(start, datetime.min.time(), UTC),
        datetime.combine(end + timedelta(days=1), datetime.min.time(), UTC),
    )


def _normal(value: Any, allowed: set[str], *, boolean: bool = False) -> str:
    if value is _MISSING:
        return "missing"
    if value is None:
        return "null"
    if boolean:
        return "true" if value is True else "false" if value is False else "unknown"
    return value if isinstance(value, str) and value in allowed else "unknown"


def _window_value(value: Any, window: tuple[datetime, datetime] | None) -> bool | str | None:
    if window is None:
        return None
    if isinstance(value, datetime):
        current = value
    elif isinstance(value, str):
        try:
            current = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return "unknown"
    else:
        return "unknown"
    if current.tzinfo is None:
        return "unknown"
    return window[0] <= current.astimezone(UTC) < window[1]


def normalize_row(
    row: dict[str, Any], window: tuple[datetime, datetime] | None
) -> tuple[str, str, str, bool, bool | str | None]:
    item = row.get("item_id", _MISSING)
    return (
        _normal(row.get("type", _MISSING), _TYPES),
        _normal(row.get("productive", _MISSING), set(), boolean=True),
        _normal(row.get("return_quantity_basis", _MISSING), _BASES),
        item is not _MISSING and item is not None and item != "",
        _window_value(row.get("date_created", _MISSING), window),
    )


async def _classify(
    args: argparse.Namespace, window: tuple[datetime, datetime] | None
) -> dict[str, Any]:
    client: Any = None
    try:
        client = AsyncIOMotorClient(
            os.environ["MONGO_URI"],
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            socketTimeoutMS=30000,
            maxPoolSize=2,
            tz_aware=True,
        )
        cursor = (
            client[os.environ["MONGO_DB"]]["claims"]
            .find(
                {"seller_id": args.seller_id},
                {
                    "_id": 0,
                    "type": 1,
                    "productive": 1,
                    "return_quantity_basis": 1,
                    "item_id": 1,
                    "date_created": 1,
                },
            )
            .batch_size(200)
            .max_time_ms(30000)
        )
        counts: Counter[tuple[str, str, str, bool, bool | str | None]] = Counter()
        async for row in cursor:
            counts[normalize_row(row, window)] += 1
        groups = [
            {
                "type": key[0],
                "productive": key[1],
                "return_quantity_basis": key[2],
                "item_id_present": key[3],
                "in_requested_date_window": key[4],
                "count": count,
            }
            for key, count in sorted(
                counts.items(),
                key=lambda pair: (
                    *pair[0][:3],
                    "true" if pair[0][3] else "false",
                    _WINDOW_SORT[pair[0][4]],
                ),
            )
        ]
        return {
            "schema_version": "v1",
            "mode": "read_only",
            "date_window": None
            if window is None
            else {"date_from": args.date_from, "date_to": args.date_to},
            "groups": groups,
        }
    finally:
        if client is not None:
            client.close()


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if not args.seller_id:
        print("MISSING_SELLER", file=sys.stderr)
        return 2
    if not args.confirm_approved_runtime:
        print("APPROVED_RUNTIME_CONFIRMATION_REQUIRED", file=sys.stderr)
        return 2
    try:
        window = _date_window(args)
    except ValueError:
        print("INVALID_DATE_RANGE", file=sys.stderr)
        return 2
    try:
        output = asyncio.run(_classify(args, window))
    except Exception:  # noqa: BLE001 - external read failures must be fail-closed.
        print("READ_FAILED", file=sys.stderr)
        return 1
    sys.stdout.write(
        json.dumps(output, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
