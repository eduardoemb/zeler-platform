from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import tempfile
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from infra.operations.zelerdata_read_model_reconcile import create_runtime_db

from zeler_platform_core.devoluciones_readiness import (
    acquire_devoluciones_operation,
    finish_devoluciones_operation,
    new_devoluciones_attempt_token,
    stable_devoluciones_operation_id,
)
from zeler_platform_core.devoluciones_runs import MongoRunWindowRepository, RunBinding

APPROVED_SELLER_ID = "82453304"
RUN_ENVIRONMENT_FILE = Path("/etc/zeler-platform/zelerdata-devoluciones-quota-run.env")
_IDENTITY_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,128}")
_FINGERPRINT_NAME_PATTERN = re.compile(r"[a-z0-9._-]{1,64}")
_HASH_PATTERN = re.compile(r"[0-9a-f]{64}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Authorize one DEVOLUCIONES quota run.")
    parser.add_argument("--seller-id", required=True)
    parser.add_argument("--authorization-id", required=True)
    parser.add_argument("--cohort-id", required=True)
    parser.add_argument("--date-from", required=True)
    parser.add_argument("--date-to", required=True)
    parser.add_argument("--partition-version", default="v1")
    parser.add_argument("--release-fingerprint", action="append", required=True)
    parser.add_argument("--environment-file", type=Path, default=RUN_ENVIRONMENT_FILE)
    parser.add_argument("--confirm-approved-runtime", action="store_true")
    parser.add_argument("--confirm-run-authorization", action="store_true")
    return parser


def binding_from_args(args: argparse.Namespace) -> RunBinding:
    if not args.confirm_approved_runtime or not args.confirm_run_authorization:
        raise ValueError("explicit runtime and run authorization confirmation is required")
    if args.seller_id != APPROVED_SELLER_ID:
        raise ValueError("seller is outside the approved quota-run boundary")
    for value, field in (
        (args.authorization_id, "authorization ID"),
        (args.cohort_id, "cohort ID"),
        (args.partition_version, "partition version"),
    ):
        if _IDENTITY_PATTERN.fullmatch(value) is None:
            raise ValueError(f"{field} is invalid")
    fingerprints: dict[str, str] = {}
    for assignment in args.release_fingerprint:
        name, separator, fingerprint = assignment.partition("=")
        if (
            not separator
            or _FINGERPRINT_NAME_PATTERN.fullmatch(name) is None
            or _HASH_PATTERN.fullmatch(fingerprint) is None
            or name in fingerprints
        ):
            raise ValueError("release fingerprint is invalid")
        fingerprints[name] = fingerprint
    return RunBinding(
        authorization_id=args.authorization_id,
        cohort_id=args.cohort_id,
        seller_id=args.seller_id,
        scope="devoluciones",
        start=_utc_date(args.date_from, "date-from"),
        end=_utc_date(args.date_to, "date-to"),
        partition_version=args.partition_version,
        release_fingerprints=fingerprints,
    )


def write_run_environment(path: Path, run_id: str) -> None:
    if _HASH_PATTERN.fullmatch(run_id) is None:
        raise ValueError("run ID is invalid")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)  # noqa: S103 - root-only authority file.
            handle.write(f"ZELERDATA_DEVOLUCIONES_RUN_ID={run_id}\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        temporary_path.unlink(missing_ok=True)


async def authorize_quota_run(
    *,
    db: Any,
    binding: RunBinding,
    environment_file: Path,
    now: Callable[[], datetime] | None = None,
) -> str:
    operation = await acquire_devoluciones_operation(
        db=db,
        seller_id=binding.seller_id,
        scope=binding.scope,
        operation_id=stable_devoluciones_operation_id("quota_authorize", binding.run_id),
        attempt_token=new_devoluciones_attempt_token(),
        source_fingerprint=binding.run_id,
    )
    try:
        created = await MongoRunWindowRepository(db).create(
            binding,
            operation=operation,
            created_at=(now or (lambda: datetime.now(UTC)))(),
        )
        if not created:
            raise RuntimeError("quota run was not created")
    except Exception:
        await finish_devoluciones_operation(
            db=db,
            operation=operation,
            succeeded=False,
            error_code="quota_run_authorization_failed",
        )
        raise
    await finish_devoluciones_operation(db=db, operation=operation, succeeded=True)
    write_run_environment(environment_file, binding.run_id)
    return str(binding.run_id)


async def _run(args: argparse.Namespace) -> None:
    binding = binding_from_args(args)
    handle = create_runtime_db()
    try:
        await authorize_quota_run(
            db=handle.db,
            binding=binding,
            environment_file=args.environment_file,
        )
    finally:
        handle.close()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        asyncio.run(_run(args))
    except (OSError, RuntimeError, ValueError) as exc:
        raise SystemExit("quota_run_authorization_failed") from exc
    print(json.dumps({"authorized": True}, separators=(",", ":")))
    return 0


def _utc_date(value: str, field: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError as exc:
        raise ValueError(f"{field} must be a valid UTC date") from exc


if __name__ == "__main__":
    raise SystemExit(main())
