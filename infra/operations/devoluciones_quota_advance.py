from __future__ import annotations

import argparse
import asyncio
import json
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from infra.operations.zelerdata_read_model_reconcile import (
    advance_devoluciones_quota_run,
    create_runtime_db,
    execute_devoluciones_quota_window,
    readback_devoluciones_quota_run,
)

from zeler_platform_core.devoluciones_readiness import (
    DevolucionesOperationContext,
    acquire_devoluciones_operation,
    finish_devoluciones_operation,
    new_devoluciones_attempt_token,
    stable_devoluciones_operation_id,
)

APPROVED_SELLER_ID = "82453304"
_RUN_ID_PATTERN = re.compile(r"[0-9a-f]{64}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Advance one authorized DEVOLUCIONES window.")
    parser.add_argument("--run-id", required=True)
    return parser


async def advance_authorized_quota_run(
    *,
    db: Any,
    run_id: str,
    now: Callable[[], datetime] | None = None,
) -> dict[str, int]:
    _validate_run_id(run_id)
    runs = db["sheets_devoluciones_runs"]
    run = await runs.find_one({"_id": run_id})
    _validate_run(run)
    if run["state"] == "completed":
        return {"advanced": 0, "finalized": 0}

    operation = await acquire_devoluciones_operation(
        db=db,
        seller_id=APPROVED_SELLER_ID,
        scope="devoluciones",
        operation_id=stable_devoluciones_operation_id("quota_advance", run_id),
        attempt_token=new_devoluciones_attempt_token(),
        source_fingerprint=run_id,
    )
    clock = now or (lambda: datetime.now(UTC))
    try:
        outcome = await advance_devoluciones_quota_run(
            db=db,
            run_id=run_id,
            operation=operation,
            now=clock,
            source=lambda **kwargs: _execute_window(
                db=db,
                operation=operation,
                now=clock,
                **kwargs,
            ),
            readback=lambda **kwargs: readback_devoluciones_quota_run(db=db, **kwargs),
        )
        updated = await runs.find_one({"_id": run_id})
        if not isinstance(updated, Mapping) or updated.get("state") == "failed":
            raise RuntimeError("quota run failed")
    except Exception:
        await finish_devoluciones_operation(
            db=db,
            operation=operation,
            succeeded=False,
            error_code="quota_run_advancement_failed",
        )
        raise
    await finish_devoluciones_operation(db=db, operation=operation, succeeded=True)
    return outcome


async def _execute_window(
    *,
    db: Any,
    operation: DevolucionesOperationContext,
    now: Callable[[], datetime],
    window: Mapping[str, Any],
    **_: Any,
) -> dict[str, Any]:
    return await execute_devoluciones_quota_window(
        db=db,
        window=window,
        operation=operation,
        now=now,
    )


def _validate_run(run: Any) -> None:
    if not isinstance(run, Mapping):
        raise ValueError("quota run does not exist")
    if run.get("seller_id") != APPROVED_SELLER_ID or run.get("scope") != "devoluciones":
        raise ValueError("quota run is outside the approved boundary")
    if run.get("state") not in {"authorized", "active", "completed"}:
        raise ValueError("quota run state is invalid")


def _validate_run_id(run_id: str) -> None:
    if _RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise ValueError("run ID is invalid")


async def _run(args: argparse.Namespace) -> dict[str, int]:
    _validate_run_id(args.run_id)
    handle = create_runtime_db()
    try:
        return await advance_authorized_quota_run(db=handle.db, run_id=args.run_id)
    finally:
        handle.close()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        outcome = asyncio.run(_run(args))
    except (OSError, RuntimeError, ValueError) as exc:
        raise SystemExit("quota_run_advancement_failed") from exc
    print(json.dumps(outcome, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
