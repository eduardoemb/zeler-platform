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
