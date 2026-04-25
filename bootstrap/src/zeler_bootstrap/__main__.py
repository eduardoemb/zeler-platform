from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from zeler_bootstrap.runner import BootstrapDagRunner, build_default_stages
from zeler_bootstrap.runtime import BootstrapRuntimeSettings, build_runtime_dependencies
from zeler_bootstrap.stages import BootstrapDatabase, BootstrapGatewayClient, BootstrapPublisher
from zeler_bootstrap.state_machine import BootstrapJobsCollection, BootstrapStateMachine


async def run_bootstrap_job(
    *,
    seller_id: str,
    job_id: str,
    jobs_collection: BootstrapJobsCollection,
    database: BootstrapDatabase,
    gateway: BootstrapGatewayClient,
    publisher: BootstrapPublisher,
    now_fn: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    machine = BootstrapStateMachine(jobs_collection, job_id, now_fn=now_fn)
    runner = BootstrapDagRunner(
        machine, build_default_stages(gateway, database), publisher=publisher
    )
    job = await runner.run()
    if str(job["seller_id"]) != str(seller_id):
        msg = f"bootstrap job seller mismatch: expected {seller_id}, got {job['seller_id']}"
        raise ValueError(msg)
    return job


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a zeler-platform bootstrap job")
    parser.add_argument("--seller-id", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate arguments without connecting to Mongo/gateway; used by packaging tests.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    if args.dry_run:
        return
    dependencies = build_runtime_dependencies(BootstrapRuntimeSettings.from_env())
    asyncio.run(
        run_bootstrap_job(
            seller_id=args.seller_id,
            job_id=args.job_id,
            jobs_collection=dependencies.jobs_collection,
            database=dependencies.database,
            gateway=dependencies.gateway,
            publisher=dependencies.publisher,
        )
    )


if __name__ == "__main__":
    main()
