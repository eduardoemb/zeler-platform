from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from pymongo.errors import PyMongoError

from zeler_platform_core.devoluciones_readiness import (
    DevolucionesLeaseLostError,
    acquire_devoluciones_operation,
    guarded_devoluciones_write,
)
from zeler_platform_core.devoluciones_runs import (
    MongoRunWindowRepository,
    RunBinding,
    partition_windows,
)


@pytest.mark.asyncio
async def test_replica_set_rejects_old_owner_and_commits_claim_with_checkpoint(
    default_mongo_uri: str,
) -> None:
    motor = pytest.importorskip("motor.motor_asyncio")
    client = motor.AsyncIOMotorClient(default_mongo_uri, serverSelectionTimeoutMS=500)
    try:
        try:
            await client.admin.command("ping")
        except PyMongoError as exc:  # pragma: no cover - local replica-set availability
            pytest.skip(f"local replica set unavailable: {exc.__class__.__name__}")
        db = client["zeler_platform_test_devoluciones_fencing"]
        await db["sheets_devoluciones_operations"].delete_many({})
        await db["sheets_read_model_freshness"].delete_many({})
        await db["claims"].delete_many({})
        operation = await acquire_devoluciones_operation(
            db=db,
            seller_id="test-seller",
            scope="devoluciones",
            operation_id="integration-operation",
            attempt_token=uuid4().hex,
            source_fingerprint="inventory-v1",
        )

        async def write_claim(session: Any) -> None:
            await db["claims"].replace_one(
                {"_id": "test-claim", "seller_id": "test-seller"},
                {"_id": "test-claim", "seller_id": "test-seller", "value": 1},
                upsert=True,
                session=session,
            )

        await guarded_devoluciones_write(
            db=db,
            operation=operation,
            seller_id="test-seller",
            checkpoint={"claim_id": "test-claim"},
            writer=write_claim,
        )
        operation_document = await db["sheets_devoluciones_operations"].find_one(
            {"seller_id": "test-seller", "scope": "devoluciones"}
        )
        assert operation_document["checkpoint"] == {"claim_id": "test-claim"}
        assert await db["claims"].count_documents({"_id": "test-claim"}) == 1

        old_owner = replace_operation_attempt(operation, "attempt-old")
        with pytest.raises(DevolucionesLeaseLostError):
            await guarded_devoluciones_write(
                db=db,
                operation=old_owner,
                seller_id="test-seller",
                checkpoint={"claim_id": "must-not-write"},
                writer=write_claim,
            )
    finally:
        client.close()


def replace_operation_attempt(operation: Any, attempt_token: str) -> Any:
    from dataclasses import replace

    return replace(operation, attempt_token=attempt_token)


@pytest.mark.asyncio
async def test_replica_set_replays_prepared_windows_resumes_next_and_fences_competitors(
    default_mongo_uri: str,
) -> None:
    motor = pytest.importorskip("motor.motor_asyncio")
    client = motor.AsyncIOMotorClient(default_mongo_uri, serverSelectionTimeoutMS=500)
    try:
        try:
            await client.admin.command("ping")
        except PyMongoError as exc:  # pragma: no cover - local replica-set availability
            pytest.skip(f"local replica set unavailable: {exc.__class__.__name__}")
        db = client["zeler_platform_test_devoluciones_fencing"]
        await db["sheets_devoluciones_operations"].delete_many({})
        await db["sheets_devoluciones_runs"].delete_many({})
        await db["sheets_devoluciones_run_windows"].delete_many({})
        operation = await acquire_devoluciones_operation(
            db=db,
            seller_id="test-seller",
            scope="devoluciones",
            operation_id="run-operation",
            attempt_token=uuid4().hex,
        )
        binding = RunBinding(
            authorization_id="authorization-1",
            cohort_id="cohort-1",
            seller_id="test-seller",
            scope="devoluciones",
            start=datetime(2026, 1, 1, tzinfo=UTC),
            end=datetime(2026, 1, 12, tzinfo=UTC),
            partition_version="v1",
            release_fingerprints={"sheets": "release-1"},
        )
        repository = MongoRunWindowRepository(db)
        await repository.create(binding, operation=operation)
        first, second = partition_windows(binding)

        assert (
            await repository.prepare(first, operation=operation, idempotency_key="attempt-1")
            is True
        )
        assert (
            await repository.prepare(first, operation=operation, idempotency_key="attempt-1")
            is True
        )
        assert (
            await db["sheets_devoluciones_run_windows"].count_documents({"run_id": binding.run_id})
            == 1
        )
        await db["sheets_devoluciones_run_windows"].update_one(
            {"_id": first.window_id}, {"$set": {"state": "completed"}}
        )
        assert await repository.read_next(binding.run_id, operation=operation) == second

        old_owner = replace_operation_attempt(operation, "attempt-old")
        assert (
            await repository.prepare(second, operation=old_owner, idempotency_key="attempt-2")
            is False
        )
        assert (
            await db["sheets_devoluciones_run_windows"].count_documents({"run_id": binding.run_id})
            == 1
        )
    finally:
        client.close()


@pytest.mark.asyncio
async def test_compatible_acquisition_acknowledges_fence_and_invalidates_legacy_gap(
    default_mongo_uri: str,
) -> None:
    from zeler_platform_core.devoluciones_certificates import CERTIFICATES
    from zeler_platform_core.devoluciones_readiness import finish_devoluciones_operation

    motor = pytest.importorskip("motor.motor_asyncio")
    client = motor.AsyncIOMotorClient(default_mongo_uri, serverSelectionTimeoutMS=500)
    db = client["zeler_platform_test_devoluciones_fencing"]
    seller = "compatibility-" + uuid4().hex
    try:
        assert (await client.admin.command("hello"))["isWritablePrimary"] is True
        first = await acquire_devoluciones_operation(
            db=db,
            seller_id=seller,
            scope="devoluciones",
            operation_id="first",
            attempt_token=uuid4().hex,
        )
        key = {"seller_id": seller, "scope": "devoluciones"}
        saved = await db.sheets_devoluciones_operations.find_one(key)
        assert saved["coverage_ack_fence"] == first.fence
        assert saved["coverage_mode"] == "legacy"
        await finish_devoluciones_operation(db=db, operation=first, succeeded=True)
        await db.sheets_devoluciones_operations.update_one(
            key, {"$set": {"coverage_mode": "active", "coverage_epoch": 2}}
        )
        await db[CERTIFICATES].insert_one(
            {
                "_id": seller,
                "seller_id": seller,
                "state": "reconciled",
                "revision": 1,
                "coverage_epoch": 2,
            }
        )
        # A legacy writer increments fence but preserves unknown acknowledgement fields.
        await db.sheets_devoluciones_operations.update_one(key, {"$inc": {"fence": 1}})
        next_owner = await acquire_devoluciones_operation(
            db=db,
            seller_id=seller,
            scope="devoluciones",
            operation_id="next",
            attempt_token=uuid4().hex,
            invalidate_readiness=False,
        )
        saved = await db.sheets_devoluciones_operations.find_one(key)
        proof = await db[CERTIFICATES].find_one({"_id": seller})
        assert saved["coverage_ack_fence"] == next_owner.fence
        assert saved["coverage_epoch"] == 3
        assert proof["state"] == "stale"
        assert proof["needs_reacquisition"] is True
        assert proof["revision"] == 2
    finally:
        await db.sheets_devoluciones_operations.delete_many({"seller_id": seller})
        await db[CERTIFICATES].delete_many({"seller_id": seller})
        client.close()


@pytest.mark.asyncio
async def test_renewal_acquisition_cannot_acknowledge_incompatible_writer(
    default_mongo_uri: str,
) -> None:
    from zeler_platform_core.devoluciones_readiness import DevolucionesLeaseConflictError

    motor = pytest.importorskip("motor.motor_asyncio")
    client = motor.AsyncIOMotorClient(default_mongo_uri, tz_aware=True)
    db = client["zeler_platform_test_devoluciones_fencing"]
    seller = "renewal-" + uuid4().hex
    try:
        await db.sheets_devoluciones_operations.insert_one(
            {
                "_id": seller + ":devoluciones",
                "seller_id": seller,
                "scope": "devoluciones",
                "state": "succeeded",
                "fence": 2,
                "coverage_ack_fence": 1,
                "coverage_mode": "active",
                "coverage_epoch": 1,
            }
        )
        with pytest.raises(DevolucionesLeaseConflictError):
            await acquire_devoluciones_operation(
                db=db,
                seller_id=seller,
                scope="devoluciones",
                operation_id="renewal",
                attempt_token=uuid4().hex,
                invalidate_readiness=False,
                require_coverage_compatible=True,
            )
        assert (await db.sheets_devoluciones_operations.find_one({"seller_id": seller}))[
            "coverage_ack_fence"
        ] == 1
    finally:
        await db.sheets_devoluciones_operations.delete_many({"seller_id": seller})
        client.close()
