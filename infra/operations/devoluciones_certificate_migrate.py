"""Explicit, source-free certificate migration/activation in an approved runtime.

Default is read-only. Canonical data, source receipts and certificate history are
never deleted; rollback withdraws read authority before incompatible code returns.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from zeler_platform_core.devoluciones_certificates import (
    CERTIFICATES,
    CoverageUnavailableError,
    coverage_control,
    make_certificate,
    publish_certificate,
    quota_provenance,
    renewal_capacity,
    select_coverage,
    utc,
    validate_certificate,
    validate_provenance,
)
from zeler_platform_core.devoluciones_readiness import (
    acquire_devoluciones_operation,
    finish_devoluciones_operation,
    guarded_devoluciones_write,
    new_devoluciones_attempt_token,
)
from zeler_sheets.devoluciones_reconciliation import (
    DevolucionesReadModelVerificationError,
    current_certificate_facts,
)


async def _candidate(
    db: Any,
    seller_id: str,
    *,
    epoch: int,
    now: datetime,
    session: Any = None,
    run_id: str | None = None,
) -> dict[str, Any] | None:
    marker = await db.sheets_read_model_freshness.find_one(
        {"_id": f"{seller_id}:devoluciones"}, session=session
    )
    if run_id is None:
        if (
            not marker
            or marker.get("seller_id") != seller_id
            or marker.get("state") != "reconciled"
            or not isinstance(marker.get("valid_until"), datetime)
            or utc(marker["valid_until"]) <= now
            or not marker.get("revision")
            or not marker.get("proof_fingerprint")
        ):
            return None
        start, end = utc(marker.get("date_from")), utc(marker.get("reconciled_until"))
        source = marker.get("source")
        if source == "zelerdata_devoluciones_quota_run":
            run_id = str(marker["revision"])
        elif source != "zelerdata_devoluciones_joint_reconcile":
            return None
    if run_id is not None:
        run = await db.sheets_devoluciones_runs.find_one(
            {"_id": run_id, "seller_id": seller_id}, session=session
        )
        windows = [
            row
            async for row in db.sheets_devoluciones_run_windows.find(
                {"run_id": run_id}, session=session
            )
        ]
        evidence = quota_provenance(run or {}, windows)
        start, end = utc(run["start"]), utc(run["end"])
        if (
            marker
            and marker.get("revision") == run_id
            and (utc(marker["date_from"]) != start or utc(marker["reconciled_until"]) != end)
        ):
            return None
        for window in windows:
            facts = await current_certificate_facts(
                db, seller_id, utc(window["start"]), utc(window["end"]), session=session
            )
            if (
                facts["certified_count"] != window["expected_count"]
                or facts["current_read_model_fingerprint"] != window["read_model_fingerprint"]
            ):
                return None
        kind, identity = "quota_run", run_id
        acquired_at = utc(run.get("updated_at", run["created_at"]))
    else:
        kind, identity = "legacy_joint_snapshot", str(marker["revision"])
        acquired_at = utc(marker["updated_at"])
        evidence = {
            "source_fingerprint": None,
            "acquisition_fingerprint": marker["proof_fingerprint"],
        }
    facts = await current_certificate_facts(db, seller_id, start, end, session=session)
    if kind == "legacy_joint_snapshot":
        if facts["current_read_model_fingerprint"] != marker["proof_fingerprint"]:
            return None
        evidence["expected_count"] = facts["certified_count"]
    return make_certificate(
        seller_id=seller_id,
        kind=kind,
        source_identity=identity,
        date_from=start,
        date_to=end,
        acquired_at=acquired_at,
        coverage_epoch=epoch,
        now=now,
        current_membership_hash=facts["current_membership_hash"],
        current_read_model_fingerprint=facts["current_read_model_fingerprint"],
        **evidence,
    )


async def migrate_certificates(
    db: Any,
    seller_id: str,
    *,
    write: bool = False,
    approved_runtime: bool = False,
    activate: bool = False,
    compatible_writers: bool = False,
    rollback: bool = False,
    run_id: str | None = None,
) -> dict[str, Any]:
    if (
        not seller_id
        or (write and not approved_runtime)
        or (activate and not compatible_writers)
        or (activate and rollback)
    ):
        raise CoverageUnavailableError("migration authority or mode is invalid")
    control = await coverage_control(db, seller_id)
    summary: dict[str, Any] = {
        "eligible": 0,
        "written": 0,
        "unsupported": 0,
        "mode": control.get("coverage_mode", "legacy"),
        "dry_run": not write,
    }

    async def inspect(session: Any, epoch: int) -> dict[str, Any] | None:
        try:
            return await _candidate(
                db, seller_id, epoch=epoch, now=datetime.now(UTC), session=session, run_id=run_id
            )
        except (ValueError, KeyError, TypeError):
            return None

    if not write:
        candidate = await inspect(None, int(control.get("coverage_epoch", 0)))
        return summary | {
            "eligible": int(candidate is not None),
            "unsupported": int(candidate is None),
        }
    operation = await acquire_devoluciones_operation(
        db=db,
        seller_id=seller_id,
        scope="devoluciones",
        operation_id="certificate_migration",
        attempt_token=new_devoluciones_attempt_token(),
        invalidate_readiness=False,
    )
    succeeded = False
    try:

        async def mutate(session: Any) -> None:
            nonlocal summary
            if rollback:
                await db.sheets_devoluciones_operations.update_one(
                    {"seller_id": seller_id, "fence": operation.fence},
                    {"$set": {"coverage_mode": "legacy"}, "$inc": {"coverage_epoch": 1}},
                    session=session,
                )
                await db[CERTIFICATES].update_many(
                    {"seller_id": seller_id},
                    {
                        "$set": {
                            "state": "stale",
                            "needs_reacquisition": True,
                            "invalidation_reason": "incompatible_writer",
                        },
                        "$inc": {"revision": 1},
                    },
                    session=session,
                )
                summary["mode"] = "legacy"
                return
            candidate = await inspect(session, operation.coverage_epoch)
            summary["eligible"] = int(candidate is not None)
            summary["unsupported"] = int(candidate is None)
            if candidate:
                existing = await db[CERTIFICATES].find_one(
                    {"_id": candidate["_id"]}, session=session
                )
                await publish_certificate(db, operation, candidate, session=session)
                summary["written"] = int(existing is None)
            if not activate:
                return
            certificates = [
                row
                async for row in db[CERTIFICATES]
                .find({"seller_id": seller_id}, session=session)
                .max_time_ms(5000)
            ]
            if not certificates:
                raise CoverageUnavailableError("no migration proof supports activation")
            now = datetime.now(UTC)
            summary["capacity"] = renewal_capacity(
                len(certificates), control.get("coverage_renewal")
            )
            summary["unavailable"] = 0
            summary["reactivated"] = 0
            for certificate in certificates:
                validate_certificate(certificate, now=now)
                try:
                    await validate_provenance(db, certificate, session=session)
                    facts = await current_certificate_facts(
                        db,
                        seller_id,
                        utc(certificate["date_from"]),
                        utc(certificate["date_to"]),
                        session=session,
                    )
                    if any(certificate[key] != value for key, value in facts.items()):
                        raise CoverageUnavailableError(
                            "reactivation needs fresh joint certification"
                        )
                except (ValueError, DevolucionesReadModelVerificationError):
                    if certificate["state"] != "reconciled" and certificate["needs_reacquisition"]:
                        summary["unavailable"] += 1
                        continue
                    raise CoverageUnavailableError(
                        "reactivation joint certification failed"
                    ) from None
                summary["reactivated"] += 1
                await db[CERTIFICATES].update_one(
                    {"_id": certificate["_id"]},
                    {
                        "$set": {
                            "coverage_epoch": operation.coverage_epoch,
                            "state": "reconciled",
                            "needs_reacquisition": False,
                            "invalidation_reason": None,
                            "validated_at": now,
                            "valid_until": now + timedelta(minutes=30),
                        },
                        "$inc": {"revision": 1},
                    },
                    session=session,
                )
            if not summary["reactivated"]:
                raise CoverageUnavailableError("no current proof supports activation")
            marker = await db.sheets_read_model_freshness.find_one(
                {"_id": f"{seller_id}:devoluciones"}, session=session
            )
            if (
                marker
                and marker.get("state") == "reconciled"
                and utc(marker.get("valid_until")) > now
            ):
                updated = [
                    row
                    async for row in db[CERTIFICATES].find(
                        {"seller_id": seller_id}, session=session
                    )
                ]
                select_coverage(
                    updated,
                    seller_id,
                    utc(marker["date_from"]),
                    utc(marker["reconciled_until"]),
                    now,
                )
            await db.sheets_devoluciones_operations.update_one(
                {"seller_id": seller_id, "fence": operation.fence},
                {"$set": {"coverage_mode": "active"}},
                session=session,
            )
            summary["mode"] = "active"

        async with asyncio.timeout(30):
            await guarded_devoluciones_write(
                db=db,
                operation=operation,
                seller_id=seller_id,
                checkpoint={"phase": "certificate_migration"},
                writer=mutate,
            )
        succeeded = True
        return summary
    finally:
        await finish_devoluciones_operation(db=db, operation=operation, succeeded=succeeded)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seller-id", required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--activate", action="store_true")
    parser.add_argument("--rollback", action="store_true")
    parser.add_argument("--confirm-compatible-writers", action="store_true")
    parser.add_argument("--confirm-approved-runtime", action="store_true")
    args = parser.parse_args(argv)
    if not args.confirm_approved_runtime:
        parser.error("approved runtime confirmation required")
    from infra.operations.zelerdata_read_model_status import create_runtime_db

    async def execute() -> dict[str, Any]:
        db = create_runtime_db()
        try:
            return await migrate_certificates(
                db,
                args.seller_id,
                write=args.write,
                approved_runtime=args.confirm_approved_runtime,
                activate=args.activate,
                compatible_writers=args.confirm_compatible_writers,
                rollback=args.rollback,
                run_id=args.run_id,
            )
        finally:
            db.client.close()

    try:
        print(json.dumps(asyncio.run(execute()), sort_keys=True))
        return 0
    except Exception:  # noqa: BLE001 - never print runtime credentials or provider payloads
        print(json.dumps({"status": "refused", "reason": "certificate_migration_failed"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
