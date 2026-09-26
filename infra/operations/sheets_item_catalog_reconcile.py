"""Inspect or consolidate overlapping ZelerData item or buybox jobs."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import Any

from zeler_sheets.formulas.recovery_reconcile import (
    reconcile_buybox_catalog_jobs,
    reconcile_item_catalog_jobs,
)


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    mongo_uri = os.environ.get("MONGO_URI")
    mongo_db_name = os.environ.get("MONGO_DB")
    if not mongo_uri or not mongo_db_name:
        raise ValueError("runtime Mongo configuration is required")
    from motor.motor_asyncio import AsyncIOMotorClient

    client: AsyncIOMotorClient[Any] = AsyncIOMotorClient(mongo_uri)
    try:
        if args.read_model == "catalog_buybox_snapshots":
            reconcile = reconcile_buybox_catalog_jobs
        elif args.read_model == "item_formula_rows":
            reconcile = reconcile_item_catalog_jobs
        else:
            raise ValueError("unsupported catalog reconciliation model")
        result = await reconcile(
            client[mongo_db_name],
            seller_id=args.seller_id,
            execute=args.execute,
            expected_fingerprint=args.expected_fingerprint,
        )
    finally:
        client.close()
    return {
        "read_model": args.read_model,
        "fingerprint": result.fingerprint,
        "active_jobs": result.active_jobs,
        "superseded_jobs": result.superseded_jobs,
        "outstanding_ids": result.outstanding_ids,
        "applied": args.execute,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seller-id", required=True)
    parser.add_argument(
        "--read-model",
        choices=("item_formula_rows", "catalog_buybox_snapshots"),
        default="item_formula_rows",
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--expected-fingerprint")
    args = parser.parse_args()
    if args.execute and not args.expected_fingerprint:
        parser.error("--execute requires --expected-fingerprint from the dry run")
    if not args.execute and args.expected_fingerprint:
        parser.error("--expected-fingerprint requires --execute")
    try:
        report = asyncio.run(_run(args))
    except Exception as exc:  # noqa: BLE001 - never expose runtime connection details.
        raise SystemExit(f"catalog reconciliation refused: {type(exc).__name__}") from None
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
