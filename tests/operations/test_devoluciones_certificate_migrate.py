from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from infra.operations.devoluciones_certificate_migrate import migrate_certificates

from zeler_platform_core.devoluciones_certificates import CERTIFICATES, CoverageUnavailableError
from zeler_sheets.devoluciones_reconciliation import current_certificate_facts


@pytest_asyncio.fixture
async def migration_db(default_mongo_uri: str) -> AsyncIterator[Any]:
    from motor.motor_asyncio import AsyncIOMotorClient

    client: Any = AsyncIOMotorClient(default_mongo_uri, tz_aware=True)
    assert (await client.admin.command("hello"))["isWritablePrimary"] is True
    name = "zeler_test_cert_mig_" + uuid4().hex
    db = client[name]
    yield db
    await client.drop_database(name)
    client.close()


async def seed_marker(db: Any, **changes: Any) -> dict[str, Any]:
    start = datetime(2026, 6, 1, tzinfo=UTC)
    end = start + timedelta(days=10)
    now = datetime.now(UTC)
    facts = await current_certificate_facts(db, "seller", start, end)
    marker = {
        "_id": "seller:devoluciones",
        "seller_id": "seller",
        "read_model": "devoluciones",
        "state": "reconciled",
        "date_from": start,
        "reconciled_until": end,
        "fresh_until": end,
        "updated_at": now,
        "valid_until": now + timedelta(minutes=30),
        "source": "zelerdata_devoluciones_joint_reconcile",
        "revision": "genuine-legacy-attempt",
        "proof_fingerprint": facts["current_read_model_fingerprint"],
    } | changes
    await db.sheets_read_model_freshness.insert_one(marker)
    return marker


@pytest.mark.asyncio
async def test_dry_run_then_idempotent_legacy_migration_preserves_facts(migration_db: Any) -> None:
    db = migration_db
    await seed_marker(db)
    result = await migrate_certificates(db, "seller")
    assert result["eligible"] == 1 and result["written"] == 0
    assert await db[CERTIFICATES].count_documents({}) == 0
    assert await db.sheets_devoluciones_operations.count_documents({}) == 0
    for _ in range(2):
        result = await migrate_certificates(db, "seller", write=True, approved_runtime=True)
        assert result["eligible"] == 1
    assert await db[CERTIFICATES].count_documents({"kind": "legacy_joint_snapshot"}) == 1
    assert await db.sheets_devoluciones_runs.count_documents({}) == 0
    assert await db.claims.count_documents({}) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"source": "zelerdata_devoluciones_quota_run"},
        {"proof_fingerprint": "wrong"},
        {"valid_until": datetime(2026, 7, 1, tzinfo=UTC)},
        {"seller_id": "foreign"},
    ],
)
async def test_invalid_marker_is_never_fabricated_or_fallback(
    migration_db: Any, changes: dict[str, Any]
) -> None:
    db = migration_db
    await seed_marker(db, **changes)
    result = await migrate_certificates(db, "seller", write=True, approved_runtime=True)
    assert result["eligible"] == result["written"] == 0
    assert result["unsupported"] == 1
    assert await db[CERTIFICATES].count_documents({}) == 0


@pytest.mark.asyncio
async def test_activation_requires_authority_and_rollback_preserves_documents(
    migration_db: Any,
) -> None:
    db = migration_db
    await seed_marker(db)
    with pytest.raises(CoverageUnavailableError):
        await migrate_certificates(db, "seller", write=True)
    with pytest.raises(CoverageUnavailableError):
        await migrate_certificates(db, "seller", write=True, approved_runtime=True, activate=True)
    await migrate_certificates(
        db, "seller", write=True, approved_runtime=True, activate=True, compatible_writers=True
    )
    control = await db.sheets_devoluciones_operations.find_one({"seller_id": "seller"})
    assert control["coverage_mode"] == "active"
    result = await migrate_certificates(
        db, "seller", write=True, approved_runtime=True, rollback=True
    )
    assert result["mode"] == "legacy"
    assert await db[CERTIFICATES].count_documents({}) == 1
    assert (await db.sheets_devoluciones_operations.find_one({"seller_id": "seller"}))[
        "coverage_epoch"
    ] > control["coverage_epoch"]


async def seed_quota(db: Any, *, incomplete: bool = False, month: int = 6) -> str:
    from zeler_platform_core.devoluciones_runs import RunBinding, partition_windows

    start = datetime(2026, month, 1, tzinfo=UTC)
    end = start + timedelta(days=10)
    binding = RunBinding(
        "auth", "cohort", "seller", "devoluciones", start, end, "v1", {"worker": "source"}
    )
    now = datetime.now(UTC)
    await db.sheets_devoluciones_runs.insert_one(
        {
            "_id": binding.run_id,
            "seller_id": "seller",
            "scope": "devoluciones",
            "authorization_id": "auth",
            "cohort_id": "cohort",
            "start": start,
            "end": end,
            "partition_version": "v1",
            "release_fingerprints": {"worker": "source"},
            "state": "completed",
            "window_count": 1,
            "created_at": now,
            "updated_at": now,
            "expires_at": now - timedelta(days=1),
        }
    )
    if not incomplete:
        for window in partition_windows(binding):
            facts = await current_certificate_facts(db, "seller", window.start, window.end)
            await db.sheets_devoluciones_run_windows.insert_one(
                {
                    "_id": window.window_id,
                    "run_id": binding.run_id,
                    "index": window.index,
                    "start": window.start,
                    "end": window.end,
                    "state": "completed",
                    "expected_count": 0,
                    "persisted_count": 0,
                    "complete_count": 0,
                    "missing_count": 0,
                    "source_fingerprint": "source",
                    "read_model_fingerprint": facts["current_read_model_fingerprint"],
                }
            )
    return binding.run_id


@pytest.mark.asyncio
@pytest.mark.parametrize("incomplete", [False, True])
async def test_expired_acquisition_with_complete_receipts_migrates_not_completed_only(
    migration_db: Any, incomplete: bool
) -> None:
    db = migration_db
    run_id = await seed_quota(db, incomplete=incomplete)
    for _ in range(2):
        result = await migrate_certificates(
            db, "seller", write=True, approved_runtime=True, run_id=run_id
        )
        assert result["eligible"] == int(not incomplete)
    assert await db[CERTIFICATES].count_documents({}) == int(not incomplete)


@pytest.mark.asyncio
async def test_activation_rejects_malformed_certificate_and_preserves_legacy_mode(
    migration_db: Any,
) -> None:
    db = migration_db
    await seed_marker(db)
    await migrate_certificates(db, "seller", write=True, approved_runtime=True)
    await db[CERTIFICATES].update_one(
        {}, {"$set": {"acquired_at": datetime.now(UTC) + timedelta(days=1)}}
    )
    with pytest.raises(CoverageUnavailableError):
        await migrate_certificates(
            db, "seller", write=True, approved_runtime=True, activate=True, compatible_writers=True
        )
    assert (await db.sheets_devoluciones_operations.find_one({"seller_id": "seller"}))[
        "coverage_mode"
    ] == "legacy"


@pytest.mark.asyncio
async def test_activation_checks_every_retained_certificate_not_only_marker(
    migration_db: Any,
) -> None:
    from zeler_platform_core.devoluciones_certificates import certificate_identity

    db = migration_db
    await seed_marker(db)
    await migrate_certificates(db, "seller", write=True, approved_runtime=True)
    extra = await db[CERTIFICATES].find_one({})
    extra.update(
        _id=certificate_identity("seller", "legacy_joint_snapshot", "other"),
        source_identity="other",
        date_from=datetime(2026, 8, 1, tzinfo=UTC),
        date_to=datetime(2026, 8, 11, tzinfo=UTC),
        acquired_at=datetime.now(UTC) + timedelta(days=1),
    )
    await db[CERTIFICATES].insert_one(extra)
    with pytest.raises(CoverageUnavailableError):
        await migrate_certificates(
            db, "seller", write=True, approved_runtime=True, activate=True, compatible_writers=True
        )


@pytest.mark.asyncio
async def test_rollback_withdraws_retained_proofs_and_reactivation_can_preserve_unavailable_history(
    migration_db: Any,
) -> None:
    db = migration_db
    await seed_marker(db)
    await migrate_certificates(
        db, "seller", write=True, approved_runtime=True, activate=True, compatible_writers=True
    )
    await migrate_certificates(db, "seller", write=True, approved_runtime=True, rollback=True)
    assert (await db[CERTIFICATES].find_one({}))["state"] == "stale"
    # A legacy mutation makes June unprovable; it must not be erased or falsely revived.
    await db.claims.insert_one(
        {
            "_id": "legacy",
            "seller_id": "seller",
            "type": "returns",
            "date_created": datetime(2026, 6, 2, tzinfo=UTC),
            "order_id": "missing",
            "item_id": "item",
        }
    )
    await db.sheets_read_model_freshness.update_one({}, {"$set": {"state": "stale"}})
    august = await seed_quota(db, month=8)
    result = await migrate_certificates(
        db,
        "seller",
        write=True,
        approved_runtime=True,
        activate=True,
        compatible_writers=True,
        run_id=august,
    )
    assert result["mode"] == "active" and result["unavailable"] == 1
    assert await db[CERTIFICATES].count_documents({}) == 2
    assert await db[CERTIFICATES].count_documents({"state": "reconciled"}) == 1
    assert await db.claims.count_documents({"_id": "legacy"}) == 1


@pytest.mark.asyncio
async def test_competing_owner_and_interrupted_migration_cannot_publish(
    migration_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from infra.operations import devoluciones_certificate_migrate as module

    from zeler_platform_core.devoluciones_readiness import (
        DevolucionesLeaseConflictError,
        acquire_devoluciones_operation,
        finish_devoluciones_operation,
    )

    db = migration_db
    await seed_marker(db)
    marker = await db.sheets_read_model_freshness.find_one({})
    operation = await acquire_devoluciones_operation(
        db=db,
        seller_id="seller",
        scope="devoluciones",
        operation_id="competitor",
        attempt_token=uuid4().hex,
        invalidate_readiness=False,
    )
    with pytest.raises(DevolucionesLeaseConflictError):
        await migrate_certificates(db, "seller", write=True, approved_runtime=True)
    assert await db[CERTIFICATES].count_documents({}) == 0
    await finish_devoluciones_operation(db=db, operation=operation, succeeded=True)
    from zeler_platform_core.devoluciones_certificates import publish_certificate

    original = publish_certificate

    async def interrupted(*args: Any, **kwargs: Any) -> Any:
        await original(*args, **kwargs)
        raise RuntimeError("interrupted after provisional certificate")

    monkeypatch.setattr(module, "publish_certificate", interrupted)
    with pytest.raises(RuntimeError, match="interrupted"):
        await migrate_certificates(db, "seller", write=True, approved_runtime=True)
    assert await db[CERTIFICATES].count_documents({}) == 0
    assert await db.sheets_read_model_freshness.find_one({}) == marker
