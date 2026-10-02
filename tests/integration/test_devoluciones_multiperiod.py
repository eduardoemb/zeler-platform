from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio

from zeler_platform_core.devoluciones_certificates import (
    CERTIFICATES,
    CoverageUnavailableError,
    make_certificate,
    publish_certificate,
    select_covering_proofs,
    validate_proof_vector,
)
from zeler_platform_core.devoluciones_readiness import (
    DevolucionesLeaseLostError,
    DevolucionesOperationContext,
    acquire_devoluciones_operation,
    guarded_devoluciones_write,
)


@pytest_asyncio.fixture
async def coverage_db(default_mongo_uri: str) -> AsyncIterator[Any]:
    from motor.motor_asyncio import AsyncIOMotorClient

    client: Any = AsyncIOMotorClient(
        default_mongo_uri, tz_aware=True, serverSelectionTimeoutMS=1000
    )
    assert (await client.admin.command("hello"))["isWritablePrimary"] is True
    name = "zeler_test_multiperiod_" + uuid4().hex
    db = client[name]
    yield db
    await client.drop_database(name)
    client.close()


def proof(month: int, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    return make_certificate(
        seller_id="seller",
        kind="joint_snapshot",
        source_identity=str(month),
        source_fingerprint="source",
        acquisition_fingerprint="acquired",
        date_from=datetime(2026, month, 1, tzinfo=UTC),
        date_to=datetime(2026, month, 11, tzinfo=UTC),
        acquired_at=now,
        expected_count=0,
        current_membership_hash="empty",
        current_read_model_fingerprint="empty",
        coverage_epoch=0,
        now=now,
    )


async def owner(db: Any) -> DevolucionesOperationContext:
    return await acquire_devoluciones_operation(
        db=db,
        seller_id="seller",
        scope="devoluciones",
        operation_id="test",
        attempt_token=uuid4().hex,
    )


async def publish(
    db: Any, operation: DevolucionesOperationContext, document: dict[str, Any]
) -> None:
    async def write(session: Any) -> None:
        return await publish_certificate(db, operation, document, session=session)

    await guarded_devoluciones_write(
        db=db, operation=operation, seller_id="seller", checkpoint={}, writer=write
    )


@pytest.mark.asyncio
async def test_additive_idempotent_publication_vector_and_gap(coverage_db: Any) -> None:
    db = coverage_db
    operation = await owner(db)
    june, august = proof(6), proof(8)
    await publish(db, operation, june)
    await publish(db, operation, august)
    await publish(db, operation, june)
    assert await db[CERTIFICATES].count_documents({}) == 2
    await db.sheets_devoluciones_operations.update_one(
        {"seller_id": "seller"}, {"$set": {"coverage_mode": "active"}}
    )
    vector = await select_covering_proofs(
        db, "seller", june["date_from"], june["date_to"], datetime.now(UTC)
    )
    assert len(vector.proofs) == 1
    await validate_proof_vector(db, vector, datetime.now(UTC))
    with pytest.raises(CoverageUnavailableError):
        await select_covering_proofs(
            db, "seller", june["date_from"], august["date_to"], datetime.now(UTC)
        )
    # A validity-only extension remains the same fact proof.
    await db[CERTIFICATES].update_one(
        {"_id": june["_id"]},
        {
            "$set": {
                "validated_at": datetime.now(UTC),
                "valid_until": datetime.now(UTC) + timedelta(minutes=30),
            }
        },
    )
    await validate_proof_vector(db, vector, datetime.now(UTC))
    await db[CERTIFICATES].delete_one({"_id": june["_id"]})
    with pytest.raises(CoverageUnavailableError):
        await validate_proof_vector(db, vector, datetime.now(UTC))


@pytest.mark.asyncio
async def test_conflicting_identity_and_lost_owner_cannot_publish(coverage_db: Any) -> None:
    db = coverage_db
    operation = await owner(db)
    june = proof(6)
    await publish(db, operation, june)
    with pytest.raises(CoverageUnavailableError):
        await publish(db, operation, june | {"acquisition_fingerprint": "changed"})
    await db.sheets_devoluciones_operations.update_one(
        {"seller_id": "seller"}, {"$inc": {"fence": 1}}
    )
    with pytest.raises(DevolucionesLeaseLostError):
        await publish(db, operation, proof(8))
    assert await db[CERTIFICATES].count_documents({}) == 1


@pytest.mark.asyncio
async def test_joint_readback_detects_same_count_drift_and_missing_order(coverage_db: Any) -> None:
    from zeler_sheets.devoluciones_reconciliation import (
        DevolucionesReadModelVerificationError,
        current_certificate_facts,
    )

    db = coverage_db
    now = datetime.now(UTC)
    claim = {
        "_id": "claim",
        "seller_id": "seller",
        "type": "returns",
        "date_created": datetime(2026, 6, 2, tzinfo=UTC),
        "order_id": "order",
        "item_id": "item",
        "status": "closed",
        "stage": "claim",
        "claim_version": 1,
        "last_updated": now,
        "return_last_updated": now,
        "productive": True,
        "return_id": "return",
        "return_status": "closed",
        "return_subtype": "return",
        "returned_quantity": 1,
        "return_quantity_basis": "v2_return_order",
    }
    await db.claims.insert_one(claim)
    await db.orders.insert_one(
        {
            "_id": "order",
            "seller_id": "seller",
            "items": [{"item_id": "item", "quantity": 2, "title": "one"}],
        }
    )
    before = await current_certificate_facts(
        db, "seller", proof(6)["date_from"], proof(6)["date_to"]
    )
    assert before["certified_count"] == 1
    await db.claims.update_one({"_id": "claim"}, {"$set": {"returned_quantity": 2}})
    after = await current_certificate_facts(
        db, "seller", proof(6)["date_from"], proof(6)["date_to"]
    )
    assert before["current_membership_hash"] == after["current_membership_hash"]
    assert before["current_read_model_fingerprint"] != after["current_read_model_fingerprint"]
    await db.orders.delete_many({})
    with pytest.raises(DevolucionesReadModelVerificationError):
        await current_certificate_facts(db, "seller", proof(6)["date_from"], proof(6)["date_to"])


@pytest.mark.asyncio
async def test_claim_mutation_invalidates_old_and_new_membership_not_unrelated(
    coverage_db: Any,
) -> None:
    from zeler_platform_core.devoluciones_readiness import finish_devoluciones_operation
    from zeler_sheets.claim_projection import persist_claim_projection

    db = coverage_db
    operation = await owner(db)
    for month in (5, 6, 8):
        await publish(db, operation, proof(month))
    await finish_devoluciones_operation(db=db, operation=operation, succeeded=True)
    await db.sheets_devoluciones_operations.update_one(
        {"seller_id": "seller"}, {"$set": {"coverage_mode": "active"}}
    )
    operation = await owner(db)
    now = datetime.now(UTC)
    original = {
        "_id": "moving",
        "seller_id": "seller",
        "type": "returns",
        "date_created": datetime(2026, 6, 2, tzinfo=UTC),
        "claim_version": 1,
        "last_updated": now,
        "return_last_updated": now,
    }
    await db.claims.insert_one(original)
    await persist_claim_projection(
        db=db,
        operation=operation,
        document=original | {"claim_version": 2, "date_created": datetime(2026, 8, 2, tzinfo=UTC)},
    )
    assert (await db[CERTIFICATES].find_one({"source_identity": "6"}))["state"] == "stale"
    assert (await db[CERTIFICATES].find_one({"source_identity": "8"}))["state"] == "stale"
    assert (await db[CERTIFICATES].find_one({"source_identity": "5"}))["state"] == "reconciled"
    revisions = {row["_id"]: row["revision"] async for row in db[CERTIFICATES].find({})}
    await persist_claim_projection(db=db, operation=operation, document=original)
    assert {row["_id"]: row["revision"] async for row in db[CERTIFICATES].find({})} == revisions


@pytest.mark.asyncio
async def test_shared_order_write_invalidates_both_claim_periods(coverage_db: Any) -> None:
    from zeler_platform_core.devoluciones_readiness import finish_devoluciones_operation
    from zeler_sheets.event_persistence import SheetsEventPersistence

    db = coverage_db
    operation = await owner(db)
    for month in (5, 6, 8):
        await publish(db, operation, proof(month))
    await finish_devoluciones_operation(db=db, operation=operation, succeeded=True)
    await db.sheets_devoluciones_operations.update_one(
        {"seller_id": "seller"}, {"$set": {"coverage_mode": "active"}}
    )
    operation = await owner(db)
    for month in (6, 8):
        await db.claims.insert_one(
            {
                "_id": str(month),
                "seller_id": "seller",
                "type": "returns",
                "order_id": "2001",
                "date_created": datetime(2026, month, 2, tzinfo=UTC),
            }
        )
    await SheetsEventPersistence(db=db)._persist_order(
        seller_id="seller",
        operation=operation,
        resource={
            "id": 2001,
            "buyer": {"id": 123},
            "date_created": "2025-01-01T00:00:00Z",
            "last_updated": "2026-10-02T00:00:00Z",
            "status": "paid",
            "currency_id": "MXN",
            "total_amount": 10,
            "order_items": [
                {"item": {"id": "MLM1", "title": "One"}, "quantity": 1, "unit_price": 10}
            ],
        },
    )
    assert (await db[CERTIFICATES].find_one({"source_identity": "6"}))["state"] == "stale"
    assert (await db[CERTIFICATES].find_one({"source_identity": "8"}))["state"] == "stale"
    assert (await db[CERTIFICATES].find_one({"source_identity": "5"}))["state"] == "reconciled"


@pytest.mark.asyncio
async def test_actual_quota_finalizer_preserves_two_periods(coverage_db: Any) -> None:
    from infra.operations.zelerdata_read_model_reconcile import (
        _finalize_devoluciones_quota_run,
        readback_devoluciones_quota_run,
    )

    from zeler_platform_core.devoluciones_readiness import finish_devoluciones_operation
    from zeler_platform_core.devoluciones_runs import (
        MongoRunWindowRepository,
        RunBinding,
        partition_windows,
    )
    from zeler_sheets.devoluciones_reconciliation import current_certificate_facts

    db = coverage_db
    operation = await owner(db)
    await finish_devoluciones_operation(db=db, operation=operation, succeeded=True)
    await db.sheets_devoluciones_operations.update_one(
        {"seller_id": "seller"}, {"$set": {"coverage_mode": "active"}}
    )
    operation = await owner(db)
    for month in (6, 8, 5, 9):
        bounds = proof(month)
        binding = RunBinding(
            "auth" + str(month),
            "cohort",
            "seller",
            "devoluciones",
            bounds["date_from"],
            bounds["date_to"],
            "v1",
            {"worker": "release"},
        )
        await MongoRunWindowRepository(db).create(binding, operation=operation)
        run = await db.sheets_devoluciones_runs.find_one({"_id": binding.run_id})
        facts = await current_certificate_facts(db, "seller", binding.start, binding.end)
        for window in partition_windows(binding):
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

        async def readback(**kwargs: Any) -> dict[str, Any]:
            return await readback_devoluciones_quota_run(db=db, **kwargs)

        assert (
            await _finalize_devoluciones_quota_run(
                db=db, run=run, operation=operation, current=datetime.now(UTC), readback=readback
            )
        )["finalized"] == 1
    assert await db[CERTIFICATES].count_documents({"kind": "quota_run"}) == 4


@pytest.mark.asyncio
async def test_joint_publication_requires_exact_source_fingerprint(coverage_db: Any) -> None:
    from dataclasses import replace

    from zeler_sheets.devoluciones_reconciliation import (
        current_certificate_facts,
        publish_joint_certificate,
    )

    db = coverage_db
    operation = replace(await owner(db), source_fingerprint="source")
    for month in (6, 8):
        document = proof(month)
        facts = await current_certificate_facts(
            db, "seller", document["date_from"], document["date_to"]
        )

        async def write(session: Any, document: Any = document, facts: Any = facts) -> None:
            await publish_joint_certificate(
                db,
                replace(operation, attempt_token=operation.attempt_token),
                document["date_from"],
                document["date_to"],
                expected_fingerprint=facts["current_read_model_fingerprint"],
                expected_ids=frozenset(),
                now=datetime.now(UTC),
                session=session,
            )

        # Real operation identity cannot be reused for a different acquisition interval.
        if month == 6:
            await guarded_devoluciones_write(
                db=db, operation=operation, seller_id="seller", checkpoint={}, writer=write
            )
        else:
            with pytest.raises(CoverageUnavailableError):
                await guarded_devoluciones_write(
                    db=db, operation=operation, seller_id="seller", checkpoint={}, writer=write
                )
    saved = await db[CERTIFICATES].find_one({})
    assert saved["kind"] == "joint_snapshot"
    assert await db.sheets_devoluciones_runs.count_documents({}) == 0


@pytest.mark.asyncio
async def test_formula_repository_uses_snapshot_proof_vector_and_rejects_gap(
    coverage_db: Any,
) -> None:
    from zeler_sheets.devoluciones_reconciliation import current_certificate_facts
    from zeler_sheets.formulas.dispatcher import FormulaDataUnavailableError
    from zeler_sheets.formulas.read_models import FormulaReadModelRepository

    db = coverage_db
    operation = await owner(db)
    for month in (6, 8):
        document = proof(month)
        facts = await current_certificate_facts(
            db, "seller", document["date_from"], document["date_to"]
        )
        await publish(db, operation, document | facts)
    await db.sheets_devoluciones_operations.update_one(
        {"seller_id": "seller"}, {"$set": {"coverage_mode": "active"}}
    )
    repo = FormulaReadModelRepository(db=db)
    kwargs = dict(
        seller_id="seller",
        date_from=proof(6)["date_from"],
        date_to=proof(6)["date_to"],
        now=datetime.now(UTC),
        formula="DEVOLUCIONES",
    )
    snapshot = await repo.require_devoluciones_reconciled_range(**kwargs)
    assert snapshot.claims == []
    assert snapshot.orders == []
    assert len(snapshot.vector.proofs) == 1
    await repo.validate_devoluciones_read_snapshot(**kwargs, snapshot=snapshot)
    await db.sheets_devoluciones_operations.update_one(
        {"seller_id": "seller"}, {"$inc": {"fence": 1}}
    )
    with pytest.raises(FormulaDataUnavailableError):
        await repo.validate_devoluciones_read_snapshot(**kwargs, snapshot=snapshot)
    with pytest.raises(FormulaDataUnavailableError):
        await repo.require_devoluciones_reconciled_range(
            **(kwargs | {"date_to": proof(8)["date_to"]})
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["unknown", "failed"])
async def test_unknown_and_explicit_failure_withdraw_all_certificates(
    coverage_db: Any, mode: Any
) -> None:
    from zeler_platform_core.devoluciones_readiness import (
        finish_devoluciones_operation,
        invalidate_devoluciones_readiness,
    )

    db = coverage_db
    operation = await owner(db)
    for month in (6, 8):
        await publish(db, operation, proof(month))
    await finish_devoluciones_operation(db=db, operation=operation, succeeded=True)
    await db.sheets_devoluciones_operations.update_one(
        {"seller_id": "seller"}, {"$set": {"coverage_mode": "active"}}
    )
    operation = await owner(db)
    if mode == "unknown":
        await invalidate_devoluciones_readiness(
            db=db, operation=operation, source="devoluciones_event_relevance_unknown"
        )
    else:
        from zeler_platform_core.read_model_freshness import set_read_model_marker_state

        await set_read_model_marker_state(
            db=db,
            seller_id="seller",
            read_model="devoluciones",
            target_state="failed",
            source="operator-action",
            approved_runtime=True,
            operation=operation,
        )
    assert (
        await db[CERTIFICATES].count_documents({"state": "stale", "needs_reacquisition": True}) == 2
    )


@pytest.mark.asyncio
async def test_bounded_renewal_is_fair_and_preserves_acquisition(coverage_db: Any) -> None:
    from zeler_platform_core.devoluciones_readiness import finish_devoluciones_operation
    from zeler_sheets.devoluciones_reconciliation import current_certificate_facts
    from zeler_sheets.devoluciones_runner import renew_due_certificates

    db = coverage_db
    operation = await owner(db)
    now = datetime.now(UTC)
    for month in (6, 8):
        document = proof(month, now=now - timedelta(minutes=31))
        facts = await current_certificate_facts(
            db, "seller", document["date_from"], document["date_to"]
        )
        await publish(db, operation, document | facts)
    await finish_devoluciones_operation(db=db, operation=operation, succeeded=True)
    await db.sheets_devoluciones_operations.update_one(
        {"seller_id": "seller"}, {"$set": {"coverage_mode": "active"}}
    )
    first = await renew_due_certificates(db, "seller", now=lambda: now, max_count=1)
    assert first["attempted"] == first["renewed"] == 1
    second = await renew_due_certificates(db, "seller", now=lambda: now, max_count=1)
    assert second["attempted"] == second["renewed"] == 1
    assert await db[CERTIFICATES].count_documents({"valid_until": {"$gt": now}}) == 2
    assert await db[CERTIFICATES].count_documents({"acquisition_fingerprint": "acquired"}) == 2
    measurement = (await db.sheets_devoluciones_operations.find_one({"seller_id": "seller"}))[
        "coverage_renewal"
    ]
    assert measurement["slowest_seconds"] > 0
    assert measurement["attempted"] == 1
    await db.sheets_devoluciones_operations.update_one(
        {"seller_id": "seller"}, {"$inc": {"fence": 1}}
    )
    refused = await renew_due_certificates(db, "seller", now=lambda: now + timedelta(minutes=15))
    assert refused["attempted"] == 0
    assert refused["reason"] == "incompatible_writer"


@pytest.mark.asyncio
@pytest.mark.parametrize("source_mode", ["disabled", "due", "failed"])
async def test_existing_refresh_entry_renews_active_certificates_without_source(
    coverage_db: Any,
    source_mode: str,
) -> None:
    from zeler_platform_core.devoluciones_readiness import finish_devoluciones_operation
    from zeler_sheets.devoluciones_reconciliation import current_certificate_facts
    from zeler_sheets.devoluciones_runner import advance_due_devoluciones_run

    db = coverage_db
    operation = await owner(db)
    document = proof(6)
    facts = await current_certificate_facts(
        db, "seller", document["date_from"], document["date_to"]
    )
    await publish(db, operation, document | facts)
    await finish_devoluciones_operation(db=db, operation=operation, succeeded=True)
    await db.sheets_devoluciones_operations.update_one(
        {"seller_id": "seller"}, {"$set": {"coverage_mode": "active"}}
    )
    original = await db[CERTIFICATES].find_one({})
    start = datetime.now(UTC)
    await db.sheets_devoluciones_runs.insert_one(
        {
            "_id": "authorized-august",
            "seller_id": "seller",
            "scope": "devoluciones",
            "state": "authorized",
            "expires_at": start + timedelta(hours=2),
            "not_before": start,
            "created_at": start,
        }
    )
    advanced: list[str] = []

    async def advance(**kwargs: Any) -> dict[str, int]:
        advanced.append(kwargs["run_id"])
        if source_mode == "failed":
            raise RuntimeError("source failed")
        return {"advanced": 1, "finalized": 0}

    for minute in (0, 15, 30, 45):
        clock = start + timedelta(minutes=minute)

        def cycle_clock(value: datetime = clock) -> datetime:
            return value

        if source_mode == "failed":
            with pytest.raises(RuntimeError, match="source failed"):
                await advance_due_devoluciones_run(db, "seller", now=cycle_clock, advance=advance)
        else:
            moved = await advance_due_devoluciones_run(
                db,
                "seller",
                advance_enabled=source_mode != "disabled",
                now=cycle_clock,
                advance=advance,
            )
            assert moved is (source_mode != "disabled")
        renewed = await db[CERTIFICATES].find_one({})
        assert renewed["valid_until"] > clock + timedelta(minutes=29)
        assert renewed["acquisition_fingerprint"] == original["acquisition_fingerprint"]
    assert advanced == ([] if source_mode == "disabled" else ["authorized-august"] * 4)


@pytest.mark.asyncio
async def test_real_strict_certificate_validator_and_unique_index(coverage_db: Any) -> None:
    import json
    from pathlib import Path

    from pymongo.errors import DuplicateKeyError, WriteError

    db = coverage_db
    payload = json.loads(
        Path("infra/mongo/schemas/sheets_devoluciones_certificates.json").read_text()
    )
    action = payload.pop("validationAction")
    level = payload.pop("validationLevel")
    await db.create_collection(
        CERTIFICATES, validator=payload, validationAction=action, validationLevel=level
    )
    await db[CERTIFICATES].create_index(
        [("seller_id", 1), ("kind", 1), ("source_identity", 1)], unique=True
    )
    valid = proof(6)
    await db[CERTIFICATES].insert_one(valid)
    for changes in (
        {"_id": "invalid", "unknown": "no"},
        {"_id": "invalid", "date_to": valid["date_from"]},
        {"_id": "invalid", "kind": "quota_run", "source_fingerprint": None},
    ):
        with pytest.raises(WriteError):
            await db[CERTIFICATES].insert_one(
                valid | changes | {"source_identity": "invalid-" + uuid4().hex}
            )
    with pytest.raises(DuplicateKeyError):
        await db[CERTIFICATES].insert_one(valid | {"_id": "duplicate"})


@pytest.mark.asyncio
async def test_authoritative_claim_transition_recertifies_without_changing_acquisition(
    coverage_db: Any,
) -> None:
    from dataclasses import replace

    from zeler_platform_core.devoluciones_readiness import finish_devoluciones_operation
    from zeler_sheets.claim_projection import persist_claim_projection
    from zeler_sheets.devoluciones_reconciliation import current_certificate_facts

    db = coverage_db
    operation = await owner(db)
    now = datetime.now(UTC)
    claim = {
        "_id": "claim",
        "seller_id": "seller",
        "type": "returns",
        "date_created": datetime(2026, 6, 2, tzinfo=UTC),
        "order_id": "order",
        "item_id": "item",
        "status": "closed",
        "stage": "claim",
        "claim_version": 1,
        "last_updated": now,
        "return_last_updated": now,
        "productive": True,
        "return_id": "return",
        "return_status": "closed",
        "return_subtype": "return",
        "returned_quantity": 1,
        "return_quantity_basis": "v2_return_order",
    }
    await db.claims.insert_one(claim)
    await db.orders.insert_one(
        {
            "_id": "order",
            "seller_id": "seller",
            "items": [{"item_id": "item", "quantity": 3, "title": "One"}],
        }
    )
    document = proof(6)
    facts = await current_certificate_facts(
        db, "seller", document["date_from"], document["date_to"]
    )
    await publish(db, operation, document | facts | {"expected_count": 1})
    before = await db[CERTIFICATES].find_one({})
    await finish_devoluciones_operation(db=db, operation=operation, succeeded=True)
    await db.sheets_devoluciones_operations.update_one(
        {"seller_id": "seller"}, {"$set": {"coverage_mode": "active"}}
    )
    operation = replace(await owner(db), source_fingerprint="authoritative-event")
    await persist_claim_projection(
        db=db, operation=operation, document=claim | {"claim_version": 2, "returned_quantity": 2}
    )
    after = await db[CERTIFICATES].find_one({})
    assert after["state"] == "reconciled"
    assert after["revision"] > before["revision"]
    assert after["current_read_model_fingerprint"] != before["current_read_model_fingerprint"]
    assert after["acquisition_fingerprint"] == before["acquisition_fingerprint"]
    assert after["date_from"] == before["date_from"] and after["date_to"] == before["date_to"]
    # Unexplained prior drift cannot be washed away by the next authoritative update.
    await db.claims.update_one({"_id": "claim"}, {"$set": {"returned_quantity": 3}})
    await persist_claim_projection(
        db=db, operation=operation, document=claim | {"claim_version": 3, "returned_quantity": 2}
    )
    assert (await db[CERTIFICATES].find_one({}))["state"] == "stale"


@pytest.mark.asyncio
@pytest.mark.parametrize("abort_external", [False, True])
async def test_known_shared_order_transition_recertifies_every_dependent_period(
    coverage_db: Any,
    abort_external: bool,
) -> None:
    from dataclasses import replace

    from zeler_platform_core.devoluciones_readiness import finish_devoluciones_operation
    from zeler_sheets.devoluciones_reconciliation import current_certificate_facts
    from zeler_sheets.event_persistence import SheetsEventPersistence

    db = coverage_db
    operation = await owner(db)
    now = datetime.now(UTC)
    await db.orders.insert_one(
        {
            "_id": "2001",
            "seller_id": "seller",
            "items": [{"item_id": "MLM1", "quantity": 3, "title": "Old"}],
        }
    )
    for month in (6, 8):
        await db.claims.insert_one(
            {
                "_id": str(month),
                "seller_id": "seller",
                "type": "returns",
                "date_created": datetime(2026, month, 2, tzinfo=UTC),
                "order_id": "2001",
                "item_id": "MLM1",
                "status": "closed",
                "stage": "claim",
                "claim_version": 1,
                "last_updated": now,
                "return_last_updated": now,
                "productive": True,
                "return_id": "r" + str(month),
                "return_status": "closed",
                "return_subtype": "return",
                "returned_quantity": 1,
                "return_quantity_basis": "v2_return_order",
            }
        )
        doc = proof(month)
        facts = await current_certificate_facts(db, "seller", doc["date_from"], doc["date_to"])
        await publish(db, operation, doc | facts | {"expected_count": 1})
    await finish_devoluciones_operation(db=db, operation=operation, succeeded=True)
    await db.sheets_devoluciones_operations.update_one(
        {"seller_id": "seller"}, {"$set": {"coverage_mode": "active"}}
    )
    operation = replace(await owner(db), source_fingerprint="order-event")
    await db.sheets_read_model_freshness.update_one(
        {"_id": "seller:devoluciones"},
        {
            "$set": {
                "state": "reconciled",
                "date_from": datetime(2026, 8, 1, tzinfo=UTC),
                "reconciled_until": datetime(2026, 8, 11, tzinfo=UTC),
            }
        },
    )

    async def write_order(session: Any = None) -> None:
        await SheetsEventPersistence(db=db)._persist_order(
            seller_id="seller",
            operation=operation,
            session=session,
            resource={
                "id": 2001,
                "buyer": {"id": 123},
                "date_created": "2025-01-01T00:00:00Z",
                "last_updated": "2026-10-02T00:00:00Z",
                "status": "paid",
                "currency_id": "MXN",
                "total_amount": 10,
                "order_items": [
                    {"item": {"id": "MLM1", "title": "New"}, "quantity": 3, "unit_price": 10}
                ],
            },
        )

    if abort_external:
        before = await db[CERTIFICATES].find({}).sort("_id", 1).to_list(None)
        before_order = await db.orders.find_one({"_id": "2001"})
        async with await db.client.start_session() as session:
            with pytest.raises(RuntimeError, match="outer abort"):
                async with session.start_transaction():
                    await write_order(session)
                    assert (
                        await db[CERTIFICATES].count_documents({"revision": 2}, session=session)
                        == 2
                    )
                    raise RuntimeError("outer abort")
        assert await db[CERTIFICATES].find({}).sort("_id", 1).to_list(None) == before
        assert await db.orders.find_one({"_id": "2001"}) == before_order
        return
    await write_order()
    assert await db[CERTIFICATES].count_documents({"state": "reconciled", "revision": 2}) == 2
    assert await db[CERTIFICATES].count_documents({"acquisition_fingerprint": "acquired"}) == 2

    assert (await db.sheets_read_model_freshness.find_one({"_id": "seller:devoluciones"}))[
        "state"
    ] == "stale"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "checkpoint",
    [{"order_id": "order", "repair": "identity"}, {"order_id": "order", "stage": "orders"}],
)
async def test_raw_repair_and_bootstrap_guards_cannot_bypass_dependency_invalidation(
    coverage_db: Any, checkpoint: Any
) -> None:
    from zeler_platform_core.devoluciones_readiness import finish_devoluciones_operation

    db = coverage_db
    operation = await owner(db)
    await publish(db, operation, proof(6))
    await db.claims.insert_one(
        {
            "_id": "claim",
            "seller_id": "seller",
            "type": "returns",
            "order_id": "order",
            "date_created": datetime(2026, 6, 2, tzinfo=UTC),
        }
    )
    await db.orders.insert_one({"_id": "order", "seller_id": "seller", "value": 1})
    await finish_devoluciones_operation(db=db, operation=operation, succeeded=True)
    await db.sheets_devoluciones_operations.update_one(
        {"seller_id": "seller"}, {"$set": {"coverage_mode": "active"}}
    )
    operation = await owner(db)

    async def write(session: Any) -> None:
        await db.orders.update_one({"_id": "order"}, {"$set": {"value": 2}}, session=session)

    await guarded_devoluciones_write(
        db=db, operation=operation, seller_id="seller", checkpoint=checkpoint, writer=write
    )
    assert (await db[CERTIFICATES].find_one({}))["state"] == "stale"


@pytest.mark.asyncio
async def test_status_separates_expired_interval_gap_and_due_backlog(coverage_db: Any) -> None:
    from zeler_platform_core.devoluciones_certificates import certificate_status

    db = coverage_db
    operation = await owner(db)
    now = datetime.now(UTC)
    await publish(db, operation, proof(6))
    await publish(db, operation, proof(8, now=now - timedelta(minutes=31)))
    await db.sheets_devoluciones_operations.update_one(
        {"seller_id": "seller"}, {"$set": {"coverage_mode": "active"}}
    )
    status = await certificate_status(db, "seller", datetime.now(UTC))
    assert [row["readable"] for row in status["intervals"]] == [True, False]
    assert status["expired"] == 1 and status["due"] == 2
    assert status["unacquired_gaps"] == [
        {"date_from": "2026-06-11T00:00:00+00:00", "date_to": "2026-08-01T00:00:00+00:00"}
    ]
    assert status["capacity"]["status"] == "unknown"


@pytest.mark.asyncio
async def test_active_alarm_reports_certificate_expiry_not_singleton_health(
    coverage_db: Any,
) -> None:
    from zeler_sheets.zelerdata_freshness_alarm import evaluate_refresh_alarms

    db = coverage_db
    operation = await owner(db)
    await publish(db, operation, proof(6, now=datetime.now(UTC) - timedelta(minutes=31)))
    await db.sheets_devoluciones_operations.update_one(
        {"seller_id": "seller"}, {"$set": {"coverage_mode": "active"}}
    )
    alarms = await evaluate_refresh_alarms(db, "seller", expected_models=["devoluciones"])
    assert any(alarm.reason == "certificate_coverage_degraded" for alarm in alarms)


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_after", [None, 3, 5])
async def test_actual_joint_finalizer_limits_evidence_to_acquired_period(
    coverage_db: Any, fail_after: int | None
) -> None:
    from dataclasses import replace

    from infra.operations.zelerdata_read_model_reconcile import (
        ExpectedReadModelCounts,
        ReconciliationControls,
        ReconciliationDateRange,
        ReconciliationRequest,
        collect_reconciliation_counts,
        write_complete_read_model_freshness_markers,
    )

    from zeler_platform_core.devoluciones_readiness import finish_devoluciones_operation
    from zeler_sheets.devoluciones_reconciliation import current_certificate_facts

    db = coverage_db
    operation = await owner(db)
    await finish_devoluciones_operation(db=db, operation=operation, succeeded=True)
    await db.sheets_devoluciones_operations.update_one(
        {"seller_id": "seller"}, {"$set": {"coverage_mode": "active"}}
    )
    operation = replace(
        await owner(db),
        source_fingerprint="source",
        required_coverage_start=datetime(2026, 6, 1, tzinfo=UTC),
        required_coverage_end=datetime(2026, 6, 11, tzinfo=UTC),
    )
    await db.claims.insert_one(
        {
            "_id": "outside",
            "seller_id": "seller",
            "type": "returns",
            "date_created": datetime(2026, 7, 1, tzinfo=UTC),
            "productive": False,
        }
    )
    start, end = datetime(2026, 8, 1, tzinfo=UTC), datetime(2026, 8, 11, tzinfo=UTC)
    request = ReconciliationRequest(
        "seller",
        ReconciliationDateRange("2026-08-01", "2026-08-10", start, end),
        False,
        True,
        True,
        False,
        ReconciliationControls(),
    )
    facts = await current_certificate_facts(db, "seller", start, end)
    expected = ExpectedReadModelCounts(
        {"claims": 0},
        refs={"claims": frozenset()},
        truth_mode={"claims": "expected"},
        source_fingerprint="source",
        read_model_fingerprint=facts["current_read_model_fingerprint"],
    )
    summary = await collect_reconciliation_counts(
        db=db, request=request, expected=expected, read_models=("claims",)
    )
    calls = 0

    def guard() -> None:
        nonlocal calls
        calls += 1
        if calls == fail_after:
            raise RuntimeError("publication age exceeded")

    if fail_after is None:
        await write_complete_read_model_freshness_markers(
            db=db,
            request=request,
            summary=summary,
            expected=expected,
            operation=operation,
            publication_guard=guard,
        )
    else:
        with pytest.raises(RuntimeError, match="publication age"):
            await write_complete_read_model_freshness_markers(
                db=db,
                request=request,
                summary=summary,
                expected=expected,
                operation=operation,
                publication_guard=guard,
            )
    assert await db[CERTIFICATES].count_documents(
        {"kind": "joint_snapshot", "date_from": start, "date_to": end, "state": "reconciled"}
    ) == int(fail_after is None)
    assert await db.sheets_devoluciones_runs.count_documents({}) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("race", [False, True])
async def test_native_formula_overlap_counts_distinct_claims_once(
    coverage_db: Any, monkeypatch: pytest.MonkeyPatch, race: bool
) -> None:
    from zeler_platform_core.devoluciones_certificates import certificate_identity
    from zeler_sheets.devoluciones_reconciliation import current_certificate_facts
    from zeler_sheets.formulas.dispatcher import FormulaDispatcher, FormulaExecutionContext
    from zeler_sheets.formulas.handlers_returns_histories_withdrawals import (
        build_returns_histories_withdrawals_formula_handlers,
    )
    from zeler_sheets.formulas.read_models import FormulaReadModelRepository
    from zeler_sheets.formulas.registry import FormulaRegistry

    db = coverage_db
    operation = await owner(db)
    now = datetime.now(UTC)
    await db.orders.insert_one(
        {
            "_id": "order",
            "seller_id": "seller",
            "items": [{"item_id": "MLM1", "quantity": 3, "title": "One", "sku": "SKU"}],
        }
    )
    for index in (1, 2):
        await db.claims.insert_one(
            {
                "_id": str(index),
                "seller_id": "seller",
                "type": "returns",
                "date_created": datetime(2026, 6, 6 + index, tzinfo=UTC),
                "order_id": "order",
                "item_id": "MLM1",
                "status": "closed",
                "stage": "claim",
                "claim_version": 1,
                "last_updated": now,
                "return_last_updated": now,
                "productive": True,
                "return_id": "r" + str(index),
                "return_status": "closed",
                "return_subtype": "return",
                "returned_quantity": index,
                "return_quantity_basis": "v2_return_order",
            }
        )
    first = proof(6)
    second = proof(6) | {
        "_id": certificate_identity("seller", "joint_snapshot", "overlap"),
        "source_identity": "overlap",
        "date_from": datetime(2026, 6, 5, tzinfo=UTC),
        "date_to": datetime(2026, 6, 15, tzinfo=UTC),
    }
    for doc in (first, second):
        facts = await current_certificate_facts(db, "seller", doc["date_from"], doc["date_to"])
        await publish(db, operation, doc | facts | {"expected_count": 2})
    await db.sheets_devoluciones_operations.update_one(
        {"seller_id": "seller"}, {"$set": {"coverage_mode": "active"}}
    )
    from dataclasses import replace

    from zeler_sheets.claim_projection import persist_claim_projection
    from zeler_sheets.devoluciones_reconciliation import read_devoluciones_orders_by_id_keyset
    from zeler_sheets.formulas import read_models as read_module
    from zeler_sheets.formulas.dispatcher import FormulaDataUnavailableError

    original_read = read_devoluciones_orders_by_id_keyset

    async def racing_read(**kwargs: Any) -> Any:
        if race:
            claim = await db.claims.find_one({"_id": "1"})
            await persist_claim_projection(
                db=db,
                operation=replace(operation, coverage_mode="active"),
                document=claim | {"claim_version": 2, "returned_quantity": 2},
            )
        return await original_read(**kwargs)

    monkeypatch.setattr(read_module, "read_devoluciones_orders_by_id_keyset", racing_read)
    dispatcher = FormulaDispatcher(
        build_returns_histories_withdrawals_formula_handlers(FormulaReadModelRepository(db=db))
    )
    context = FormulaExecutionContext(
        contract=FormulaRegistry.default().find_required("ZELERDATA_DEVOLUCIONES"),
        cuenta="test",
        seller_id="seller",
        seller_nickname="test",
        token_id=uuid4().hex,
        args={"fecha_inicio": "2026-06-01", "fecha_final": "2026-06-14", "encabezados": "NO"},
        request_id="request",
    )
    if race:
        with pytest.raises(FormulaDataUnavailableError):
            await dispatcher.execute(context)
        assert (await db.claims.find_one({"_id": "1"}))["returned_quantity"] == 2
    else:
        result = await dispatcher.execute(context)
        assert result.values == [["MLM1", "SKU", 3, "One"]]


@pytest.mark.asyncio
async def test_due_query_uses_bounded_index_without_evicting_expired_history(
    coverage_db: Any,
) -> None:
    import json
    from pathlib import Path

    from zeler_platform_core.devoluciones_certificates import (
        certificate_identity,
        certificate_status,
    )

    db = coverage_db
    for index in json.loads(
        Path("infra/mongo/indexes/sheets_devoluciones_certificates.json").read_text()
    ):
        await db[CERTIFICATES].create_index(list(index["keys"].items()), **index["options"])
    now = datetime.now(UTC)
    for index in range(41):
        source = str(index)
        document = proof(6, now=now - timedelta(minutes=31)) | {
            "_id": certificate_identity("seller", "joint_snapshot", source),
            "source_identity": source,
        }
        await db[CERTIFICATES].insert_one(document)
    query = {"seller_id": "seller", "next_check_at": {"$lte": now}}
    explained = await db.command(
        "explain",
        {
            "find": CERTIFICATES,
            "filter": query,
            "sort": {"next_check_at": 1, "_id": 1},
            "limit": 20,
        },
        verbosity="executionStats",
    )
    assert "idx_devoluciones_certificate_due" in json.dumps(
        explained["queryPlanner"]["winningPlan"]
    )
    assert explained["executionStats"]["nReturned"] == 20
    assert explained["executionStats"]["totalDocsExamined"] <= 20
    status = await certificate_status(db, "seller", now)
    assert status["expired"] == 41 and status["due"] == 41
    assert len(status["intervals"]) == 41


@pytest.mark.asyncio
async def test_lease_expiry_after_provisional_publication_aborts_whole_transaction(
    coverage_db: Any,
) -> None:
    db = coverage_db
    from dataclasses import replace

    operation = replace(await owner(db), coverage_mode="active")
    await db.sheets_devoluciones_operations.update_one(
        {"seller_id": "seller"}, {"$set": {"coverage_mode": "active"}}
    )

    async def write(session: Any) -> None:
        await publish_certificate(db, operation, proof(6), session=session)
        await db.sheets_devoluciones_operations.update_one(
            {"seller_id": "seller"},
            {"$set": {"lease_until": datetime.now(UTC) - timedelta(seconds=1)}},
            session=session,
        )

    with pytest.raises(DevolucionesLeaseLostError):
        await guarded_devoluciones_write(
            db=db, operation=operation, seller_id="seller", checkpoint={}, writer=write
        )
    assert await db[CERTIFICATES].count_documents({}) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value", [("source_fingerprint", "replaced"), ("certified_count", 2)]
)
async def test_final_vector_rejects_immutable_evidence_changed_without_revision(
    coverage_db: Any, field: str, value: Any
) -> None:
    db = coverage_db
    operation = await owner(db)
    document = proof(6)
    await publish(db, operation, document)
    await db.sheets_devoluciones_operations.update_one(
        {"seller_id": "seller"}, {"$set": {"coverage_mode": "active"}}
    )
    vector = await select_covering_proofs(
        db, "seller", document["date_from"], document["date_to"], datetime.now(UTC)
    )
    await db[CERTIFICATES].update_one({"_id": document["_id"]}, {"$set": {field: value}})
    with pytest.raises(CoverageUnavailableError):
        await validate_proof_vector(db, vector, datetime.now(UTC))


@pytest.mark.asyncio
async def test_final_vector_revalidates_control_and_all_proofs_in_one_snapshot(
    coverage_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from zeler_platform_core import devoluciones_certificates as module

    db = coverage_db
    operation = await owner(db)
    document = proof(6)
    await publish(db, operation, document)
    await db.sheets_devoluciones_operations.update_one(
        {"seller_id": "seller"}, {"$set": {"coverage_mode": "active"}}
    )
    vector = await select_covering_proofs(
        db, "seller", document["date_from"], document["date_to"], datetime.now(UTC)
    )
    original = module.coverage_control

    async def require_snapshot(*args: Any, **kwargs: Any) -> Any:
        session = kwargs.get("session")
        assert session is not None and session.in_transaction
        return await original(*args, **kwargs)

    monkeypatch.setattr(module, "coverage_control", require_snapshot)
    await validate_proof_vector(db, vector, datetime.now(UTC))
