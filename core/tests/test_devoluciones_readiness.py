from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from zeler_platform_core.devoluciones_readiness import (
    DEVOLUCIONES_HEARTBEAT_INTERVAL,
    DEVOLUCIONES_LEASE_DURATION,
    DevolucionesLeaseLostError,
    DevolucionesOperationContext,
    acquire_devoluciones_operation,
    finish_devoluciones_operation,
    guarded_devoluciones_write,
    heartbeat_devoluciones_operation,
    maintain_devoluciones_heartbeat,
    new_devoluciones_attempt_token,
    operation_lease_guard,
    stable_devoluciones_operation_id,
    takeover_checkpoint,
)


class Result:
    def __init__(self, matched_count: int = 1) -> None:
        self.matched_count = matched_count


class RecordingCollection:
    def __init__(self, name: str, calls: list[tuple[Any, ...]]) -> None:
        self.name = name
        self.calls = calls
        self.next_result = Result()
        self.document: dict[str, Any] | None = None

    async def find_one(self, filter_spec: dict[str, Any], **kwargs: Any) -> dict[str, Any] | None:
        self.calls.append((self.name, "find_one", filter_spec, kwargs.get("session")))
        return self.document

    async def update_one(
        self,
        filter_spec: dict[str, Any],
        update: Any,
        *,
        upsert: bool = False,
        session: Any = None,
    ) -> Result:
        self.calls.append((self.name, "update_one", filter_spec, update, upsert, session))
        return self.next_result


class FakeTransaction:
    async def __aenter__(self) -> FakeTransaction:
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None


class FakeSession:
    def start_transaction(self) -> FakeTransaction:
        return FakeTransaction()

    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None


class FakeClient:
    def start_session(self) -> FakeSession:
        return FakeSession()


class FakeDb:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.client = FakeClient()
        self.collections = {
            "sheets_read_model_freshness": RecordingCollection(
                "sheets_read_model_freshness", self.calls
            ),
            "sheets_devoluciones_operations": RecordingCollection(
                "sheets_devoluciones_operations", self.calls
            ),
        }

    def __getitem__(self, name: str) -> RecordingCollection:
        return self.collections[name]


def _operation() -> DevolucionesOperationContext:
    return DevolucionesOperationContext(
        seller_id="82453304",
        scope="devoluciones",
        operation_id="operation-1",
        attempt_token=uuid4().hex,
        fence=4,
        owns_lease=True,
        source_fingerprint="inventory-v1",
    )


def test_operation_contract_uses_stable_ids_fresh_attempts_and_server_lease_guard() -> None:
    first = stable_devoluciones_operation_id("event", "claims.updated:notif-1")
    second = stable_devoluciones_operation_id("event", "claims.updated:notif-1")
    different = stable_devoluciones_operation_id("event", "claims.updated:notif-2")
    operation = _operation()
    guard = operation_lease_guard(operation)

    assert first == second
    assert first != different
    assert timedelta(seconds=120) == DEVOLUCIONES_LEASE_DURATION
    assert timedelta(seconds=30) == DEVOLUCIONES_HEARTBEAT_INTERVAL
    assert guard == {
        "seller_id": "82453304",
        "scope": "devoluciones",
        "operation_id": "operation-1",
        "attempt_token": operation.attempt_token,
        "fence": 4,
        "state": "running",
        "$expr": {"$gt": ["$lease_until", "$$NOW"]},
    }


@pytest.mark.asyncio
async def test_acquire_stales_joint_readiness_before_server_time_lease() -> None:
    db = FakeDb()

    operation = await acquire_devoluciones_operation(
        db=db,
        seller_id="82453304",
        scope="devoluciones",
        operation_id="operation-1",
        attempt_token=uuid4().hex,
        source_fingerprint="inventory-v1",
    )

    assert operation.fence == 1
    assert [call[0] for call in db.calls] == [
        "sheets_read_model_freshness",
        "sheets_read_model_freshness",
        "sheets_devoluciones_operations",
        "sheets_devoluciones_operations",
    ]
    stale_update = db.calls[1][3]
    lease_update = db.calls[3][3]
    assert stale_update[0]["$set"]["state"] == "stale"
    assert stale_update[0]["$set"]["updated_at"] == "$$NOW"
    assert lease_update[0]["$set"]["lease_until"] == {
        "$dateAdd": {"startDate": "$$NOW", "unit": "second", "amount": 120}
    }


@pytest.mark.asyncio
async def test_noninvalidating_acquire_captures_valid_marker_coverage_without_staling() -> None:
    db = FakeDb()
    coverage_start = datetime(2026, 5, 1, tzinfo=UTC)
    coverage_end = datetime(2026, 7, 1, tzinfo=UTC)
    db["sheets_read_model_freshness"].document = {
        "_id": "82453304:devoluciones",
        "seller_id": "82453304",
        "read_model": "devoluciones",
        "state": "reconciled",
        "date_from": coverage_start,
        "reconciled_until": coverage_end,
        "valid_until": datetime(2026, 7, 2, tzinfo=UTC),
    }

    operation = await acquire_devoluciones_operation(
        db=db,
        seller_id="82453304",
        scope="devoluciones",
        operation_id="order-event",
        attempt_token=uuid4().hex,
        source_fingerprint="event-1",
        invalidate_readiness=False,
    )

    freshness_updates = [
        call for call in db.calls if call[0:2] == ("sheets_read_model_freshness", "update_one")
    ]
    assert freshness_updates == []
    assert operation.required_coverage_start == coverage_start
    assert operation.required_coverage_end == coverage_end


@pytest.mark.asyncio
async def test_heartbeat_loss_marks_context_lost_and_blocks_next_write() -> None:
    db = FakeDb()
    operation = _operation()
    db["sheets_devoluciones_operations"].next_result = Result(matched_count=0)

    with pytest.raises(DevolucionesLeaseLostError, match="heartbeat"):
        await heartbeat_devoluciones_operation(db=db, operation=operation)

    assert operation.lease_lost is True
    with pytest.raises(DevolucionesLeaseLostError, match="lost"):
        await guarded_devoluciones_write(
            db=db,
            operation=operation,
            seller_id="82453304",
            checkpoint={"claim_id": "519988001"},
            writer=lambda _session: None,
        )


@pytest.mark.asyncio
async def test_guarded_write_commits_guard_checkpoint_and_mutation_in_one_transaction() -> None:
    db = FakeDb()
    operation = _operation()
    sessions: list[Any] = []

    async def writer(session: Any) -> None:
        sessions.append(session)
        db.calls.append(("claims", "replace_one", session))

    await guarded_devoluciones_write(
        db=db,
        operation=operation,
        seller_id="82453304",
        checkpoint={"claim_id": "519988001"},
        writer=writer,
    )

    guard_call, mutation_call = db.calls
    assert guard_call[0:2] == ("sheets_devoluciones_operations", "update_one")
    assert guard_call[2] == operation_lease_guard(operation)
    assert guard_call[3]["$set"]["checkpoint"] == {"claim_id": "519988001"}
    assert mutation_call[0:2] == ("claims", "replace_one")
    assert guard_call[-1] is mutation_call[-1] is sessions[0]


@pytest.mark.asyncio
async def test_guarded_write_rejects_cross_seller_mutation_before_transaction() -> None:
    db = FakeDb()

    with pytest.raises(DevolucionesLeaseLostError, match="seller"):
        await guarded_devoluciones_write(
            db=db,
            operation=_operation(),
            seller_id="99999999",
            checkpoint={"claim_id": "519988001"},
            writer=lambda _session: None,
        )

    assert db.calls == []


@pytest.mark.asyncio
async def test_acquire_exposes_matching_resume_checkpoint_to_root() -> None:
    db = FakeDb()
    db["sheets_devoluciones_operations"].document = {
        "seller_id": "82453304",
        "scope": "devoluciones",
        "state": "failed",
        "fence": 4,
        "source_fingerprint": "inventory-v1",
        "checkpoint": {"claim_id": "519988001"},
    }

    operation = await acquire_devoluciones_operation(
        db=db,
        seller_id="82453304",
        scope="devoluciones",
        operation_id="operation-1",
        attempt_token=uuid4().hex,
        source_fingerprint="inventory-v1",
    )

    assert operation.fence == 5
    assert operation.checkpoint == {"claim_id": "519988001"}


@pytest.mark.asyncio
async def test_root_heartbeat_scope_renews_immediately_and_uses_30_second_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[DevolucionesOperationContext] = []

    async def heartbeat(*, db: Any, operation: DevolucionesOperationContext) -> None:
        del db
        calls.append(operation)

    monkeypatch.setattr(
        "zeler_platform_core.devoluciones_readiness.heartbeat_devoluciones_operation",
        heartbeat,
    )
    operation = _operation()

    async with maintain_devoluciones_heartbeat(db=object(), operation=operation):
        assert calls == [operation]

    assert timedelta(seconds=30) == DEVOLUCIONES_HEARTBEAT_INTERVAL


def test_takeover_resumes_only_matching_source_fingerprint() -> None:
    existing = {
        "source_fingerprint": "inventory-v1",
        "checkpoint": {"claim_id": "519988001"},
    }

    assert takeover_checkpoint(existing, source_fingerprint="inventory-v1") == {
        "claim_id": "519988001"
    }
    assert takeover_checkpoint(existing, source_fingerprint="inventory-v2") is None
    assert (
        takeover_checkpoint(
            {"source_fingerprint": None, "checkpoint": {"claim_id": "unsafe-resume"}},
            source_fingerprint=None,
        )
        is None
    )
    assert operation_lease_guard(replace(_operation(), fence=5))["fence"] == 5


def test_retry_keeps_stable_operation_id_but_uses_fresh_attempt_token() -> None:
    operation_id = stable_devoluciones_operation_id("event", "claims.updated:notif-1")

    first_attempt = new_devoluciones_attempt_token()
    second_attempt = new_devoluciones_attempt_token()

    assert operation_id == stable_devoluciones_operation_id("event", "claims.updated:notif-1")
    assert first_attempt != second_attempt
    assert len(first_attempt) == len(second_attempt) == 32


@pytest.mark.asyncio
async def test_root_failure_releases_operation_without_restoring_readiness() -> None:
    db = FakeDb()
    operation = _operation()

    await finish_devoluciones_operation(
        db=db,
        operation=operation,
        succeeded=False,
        error_code="projection_failed",
    )

    assert len(db.calls) == 1
    call = db.calls[0]
    assert call[0:2] == ("sheets_devoluciones_operations", "update_one")
    assert call[2] == operation_lease_guard(operation)
    assert call[3][0]["$set"]["state"] == "failed"
    assert call[3][0]["$set"]["lease_until"] == "$$NOW"
