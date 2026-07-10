from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from pymongo.errors import PyMongoError

from zeler_platform_core.devoluciones_readiness import (
    DevolucionesLeaseLostError,
    acquire_devoluciones_operation,
    guarded_devoluciones_write,
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
