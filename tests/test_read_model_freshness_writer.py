"""Tests for the guarded read-model freshness entry.

Covers Phase 1 S1-S2 tasks from
``openspec/changes/zelerdata-read-model-freshness-guards/tasks.md``: the
17-name inventory contract and pre-DB validation (1.1-1.3), plus the
generic ``stale``/``failed`` upsert at exact ``(seller_id, read_model)``
identity with ``$$NOW``/source metadata, fail-closed session behavior,
and the bounded same-pair retry (1.4-1.6). S3 (devoluciones lease
delegation) tests arrive in their own slice.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from infra.operations.zelerdata_read_model_reconcile import (
    READ_MODELS as RECONCILE_READ_MODELS,
)
from pymongo.errors import DuplicateKeyError

import tests.test_devoluciones_guarded_regressions as _devoluciones_tests
from zeler_platform_core.devoluciones_readiness import (
    DEVOLUCIONES_OPERATIONS_COLLECTION,
    DEVOLUCIONES_READ_MODEL,
    READ_MODEL_FRESHNESS_COLLECTION,
    DevolucionesLeaseLostError,
    DevolucionesOperationContext,
)
from zeler_platform_core.read_model_freshness import (
    ALL_READ_MODELS,
    READ_MODELS,
    WRITER_SOURCE_ALLOWLIST,
    WRITER_TARGET_STATES,
    set_read_model_marker_state,
)

SELLER_ID = "82453304"


class SpyDb:
    """Records collection access to prove validation precedes any DB use."""

    def __init__(self) -> None:
        self.calls: list[Any] = []

    def __getitem__(self, name: str) -> Any:
        self.calls.append(name)
        return object()


# 1.1 — inventory contract -------------------------------------------------


def test_core_inventory_matches_reconciliation_plus_devoluciones() -> None:
    assert READ_MODELS == RECONCILE_READ_MODELS
    assert len(ALL_READ_MODELS) == 17
    assert len(set(ALL_READ_MODELS)) == 17
    assert set(ALL_READ_MODELS) == set(RECONCILE_READ_MODELS) | {DEVOLUCIONES_READ_MODEL}
    assert DEVOLUCIONES_READ_MODEL in ALL_READ_MODELS


# 1.2 — target-state rejection ---------------------------------------------


@pytest.mark.asyncio
async def test_reconciled_target_state_rejected_before_db_access() -> None:
    db = SpyDb()
    with pytest.raises(ValueError, match="target_state"):
        await set_read_model_marker_state(
            db=db,
            seller_id=SELLER_ID,
            read_model="orders",
            target_state="reconciled",
            source="operator-action",
            approved_runtime=True,
        )
    assert db.calls == []


@pytest.mark.asyncio
async def test_fresh_target_state_rejected_before_db_access() -> None:
    db = SpyDb()
    with pytest.raises(ValueError, match="target_state"):
        await set_read_model_marker_state(
            db=db,
            seller_id=SELLER_ID,
            read_model="orders",
            target_state="fresh",
            source="operator-action",
            approved_runtime=True,
        )
    assert db.calls == []


def test_writer_target_state_allowlist_is_exact() -> None:
    assert frozenset({"stale", "failed"}) == WRITER_TARGET_STATES


# 1.3 — runtime / read-model / source rejection ----------------------------


@pytest.mark.asyncio
async def test_unapproved_runtime_rejected_before_db_access() -> None:
    db = SpyDb()
    with pytest.raises(RuntimeError, match="approved runtime"):
        await set_read_model_marker_state(
            db=db,
            seller_id=SELLER_ID,
            read_model="catalog_buybox_snapshots",
            target_state="stale",
            source="operator-action",
            approved_runtime=False,
        )
    assert db.calls == []


@pytest.mark.asyncio
async def test_unknown_read_model_rejected_before_db_access() -> None:
    db = SpyDb()
    with pytest.raises(ValueError, match="read model"):
        await set_read_model_marker_state(
            db=db,
            seller_id=SELLER_ID,
            read_model="not_a_read_model",
            target_state="stale",
            source="operator-action",
            approved_runtime=True,
        )
    assert db.calls == []


@pytest.mark.asyncio
async def test_unknown_source_rejected_before_db_access() -> None:
    db = SpyDb()
    with pytest.raises(ValueError, match="source"):
        await set_read_model_marker_state(
            db=db,
            seller_id=SELLER_ID,
            read_model="orders",
            target_state="stale",
            source="reconciliation",
            approved_runtime=True,
        )
    assert db.calls == []


def test_writer_source_allowlist_is_exactly_operator_action() -> None:
    assert frozenset({"operator-action"}) == WRITER_SOURCE_ALLOWLIST


# S2 memory fakes ----------------------------------------------------------
#
# Reuse the devoluciones regression fakes; the subclass scripts the race.


class _ConflictCollection(_devoluciones_tests._MemoryCollection):
    """Base collection plus update recording and scripted unique-index conflicts."""

    def __init__(
        self,
        documents: list[dict[str, Any]] | None = None,
        *,
        raise_on_upsert: bool = False,
        raise_on_second_upsert: bool = False,
        raise_on_retry: bool = False,
    ) -> None:
        super().__init__(documents)
        self.raise_on_upsert = raise_on_upsert
        self.raise_on_second_upsert = raise_on_second_upsert
        self.raise_on_retry = raise_on_retry
        self.upsert_attempts = 0
        self.update_calls: list[dict[str, Any]] = []

    async def update_one(
        self,
        filter_spec: dict[str, Any],
        update: dict[str, Any] | list[dict[str, Any]],
        *,
        upsert: bool = False,
        **kwargs: Any,
    ) -> _devoluciones_tests._WriteResult:
        session = kwargs.get("session")
        self.update_calls.append(
            {"filter": deepcopy(filter_spec), "upsert": upsert, "session": session}
        )
        if upsert:
            self.upsert_attempts += 1
            if self.raise_on_upsert or (self.raise_on_second_upsert and self.upsert_attempts >= 2):
                raise DuplicateKeyError("E11000 duplicate key error on same seller/read-model pair")
        if not upsert and self.raise_on_retry:
            raise DuplicateKeyError("E11000 duplicate key error on bounded retry")
        return await super().update_one(filter_spec, update, upsert=upsert, **kwargs)


class _MemoryDb(_devoluciones_tests._MemoryDb):
    """Base memory DB whose configured collections use the conflict fake."""

    def __init__(
        self,
        collections: dict[str, list[dict[str, Any]]] | None = None,
        *,
        collection_options: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(collections)
        for name, base in list(self.collections.items()):
            options = (collection_options or {}).get(name, {})
            self.collections[name] = _ConflictCollection(
                [deepcopy(document) for document in base.documents.values()],
                **options,
            )

    def __getitem__(self, name: str) -> _ConflictCollection:
        collection = self.collections.get(name)
        if collection is None:
            collection = _ConflictCollection()
            self.collections[name] = collection
        if not isinstance(collection, _ConflictCollection):
            raise TypeError(f"collection {name!r} is not a conflict collection")
        return collection


class _RecordingCollection:
    """Records update attempts to prove fail-closed behavior precedes writes."""

    def __init__(self) -> None:
        self.update_calls: list[Any] = []

    async def update_one(self, *args: Any, **kwargs: Any) -> _devoluciones_tests._WriteResult:
        self.update_calls.append((args, kwargs))
        return _devoluciones_tests._WriteResult()


# 1.4 — generic stale/failed upsert ----------------------------------------


@pytest.mark.asyncio
async def test_stale_upsert_creates_marker_with_now_and_operator_source() -> None:
    db = _MemoryDb({READ_MODEL_FRESHNESS_COLLECTION: []})
    await set_read_model_marker_state(
        db=db,
        seller_id=SELLER_ID,
        read_model="orders",
        target_state="stale",
        source="operator-action",
        approved_runtime=True,
    )
    marker = db[READ_MODEL_FRESHNESS_COLLECTION].documents[f"{SELLER_ID}:orders"]
    assert marker == {
        "_id": f"{SELLER_ID}:orders",
        "seller_id": SELLER_ID,
        "read_model": "orders",
        "state": "stale",
        "fresh_until": _devoluciones_tests.NOW,
        "valid_until": _devoluciones_tests.NOW,
        "updated_at": _devoluciones_tests.NOW,
        "source": "operator-action",
        "schema_version": 1,
    }
    assert db[READ_MODEL_FRESHNESS_COLLECTION].update_calls[0]["session"] is not None


@pytest.mark.asyncio
async def test_failed_upsert_creates_marker_with_now_and_operator_source() -> None:
    db = _MemoryDb({READ_MODEL_FRESHNESS_COLLECTION: []})
    await set_read_model_marker_state(
        db=db,
        seller_id=SELLER_ID,
        read_model="claims",
        target_state="failed",
        source="operator-action",
        approved_runtime=True,
    )
    marker = db[READ_MODEL_FRESHNESS_COLLECTION].documents[f"{SELLER_ID}:claims"]
    assert marker["state"] == "failed"
    assert marker["read_model"] == "claims"
    assert marker["fresh_until"] == _devoluciones_tests.NOW
    assert marker["valid_until"] == _devoluciones_tests.NOW
    assert marker["updated_at"] == _devoluciones_tests.NOW
    assert marker["source"] == "operator-action"


@pytest.mark.asyncio
async def test_stale_transition_updates_existing_marker_in_place() -> None:
    existing = {
        "_id": f"{SELLER_ID}:items",
        "seller_id": SELLER_ID,
        "read_model": "items",
        "state": "reconciled",
        "source": "zelerdata_read_model_reconcile",
        "schema_version": 1,
    }
    db = _MemoryDb({READ_MODEL_FRESHNESS_COLLECTION: [existing]})
    await set_read_model_marker_state(
        db=db,
        seller_id=SELLER_ID,
        read_model="items",
        target_state="stale",
        source="operator-action",
        approved_runtime=True,
    )
    marker = db[READ_MODEL_FRESHNESS_COLLECTION].documents[f"{SELLER_ID}:items"]
    assert marker["state"] == "stale"
    assert marker["seller_id"] == SELLER_ID
    assert marker["read_model"] == "items"
    assert marker["source"] == "operator-action"
    assert marker["fresh_until"] == _devoluciones_tests.NOW
    assert marker["updated_at"] == _devoluciones_tests.NOW
    assert db[READ_MODEL_FRESHNESS_COLLECTION].update_calls[0]["upsert"] is True


# 1.5 — fail closed without session/transaction support ---------------------


@pytest.mark.parametrize(
    "db",
    [
        SimpleNamespace(collection=_RecordingCollection()),
        SimpleNamespace(client=object(), collection=_RecordingCollection()),
    ],
    ids=["no-client", "no-session-support"],
)
@pytest.mark.asyncio
async def test_missing_session_support_fails_closed_before_any_write(
    db: SimpleNamespace,
) -> None:
    with pytest.raises(RuntimeError, match="transaction"):
        await set_read_model_marker_state(
            db=db,
            seller_id=SELLER_ID,
            read_model="orders",
            target_state="stale",
            source="operator-action",
            approved_runtime=True,
        )
    assert db.collection.update_calls == []


# 1.6 — same-pair concurrency, bounded retry, valid final state ------------


@pytest.mark.asyncio
async def test_concurrent_same_pair_writes_leave_one_valid_state() -> None:
    # Scripted conflict: the second upsert loses the unique-index insert race.
    db = _MemoryDb(
        {READ_MODEL_FRESHNESS_COLLECTION: []},
        collection_options={READ_MODEL_FRESHNESS_COLLECTION: {"raise_on_second_upsert": True}},
    )
    first = set_read_model_marker_state(
        db=db,
        seller_id=SELLER_ID,
        read_model="orders",
        target_state="stale",
        source="operator-action",
        approved_runtime=True,
    )
    second = set_read_model_marker_state(
        db=db,
        seller_id=SELLER_ID,
        read_model="orders",
        target_state="failed",
        source="operator-action",
        approved_runtime=True,
    )
    await asyncio.gather(first, second)
    marker = db[READ_MODEL_FRESHNESS_COLLECTION].documents[f"{SELLER_ID}:orders"]
    assert marker["state"] in {"stale", "failed"}
    calls = db[READ_MODEL_FRESHNESS_COLLECTION].update_calls
    assert sum(1 for call in calls if call["upsert"]) == 2
    assert sum(1 for call in calls if not call["upsert"]) == 1


@pytest.mark.asyncio
async def test_duplicate_conflict_retry_is_bounded_to_one_attempt() -> None:
    db = _MemoryDb(
        {READ_MODEL_FRESHNESS_COLLECTION: []},
        collection_options={
            READ_MODEL_FRESHNESS_COLLECTION: {"raise_on_upsert": True, "raise_on_retry": True}
        },
    )
    with pytest.raises(DuplicateKeyError):
        await set_read_model_marker_state(
            db=db,
            seller_id=SELLER_ID,
            read_model="orders",
            target_state="stale",
            source="operator-action",
            approved_runtime=True,
        )
    collection = db[READ_MODEL_FRESHNESS_COLLECTION]
    assert len(collection.update_calls) == 2
    assert collection.update_calls[0]["upsert"] is True
    assert collection.update_calls[1]["upsert"] is False


# 1.7 — devoluciones lease-guarded delegation ---------------------------------
#
# S3 wires devoluciones through the existing lease authority: ``stale``
# delegates to ``invalidate_devoluciones_readiness`` and ``failed`` uses
# ``guarded_devoluciones_write`` to set ``failed`` and expire the
# productive windows. Absent, foreign, lost, or expired leases fail
# before any marker mutation.


def _lease_operation(**overrides: Any) -> DevolucionesOperationContext:
    operation = _devoluciones_tests._operation()
    for name, value in overrides.items():
        setattr(operation, name, value)
    return operation


def _lease_db(
    operation: DevolucionesOperationContext,
    markers: list[dict[str, Any]] | None = None,
) -> _devoluciones_tests._MemoryDb:
    return _devoluciones_tests._MemoryDb(
        {
            DEVOLUCIONES_OPERATIONS_COLLECTION: [
                _devoluciones_tests._operation_document(operation)
            ],
            READ_MODEL_FRESHNESS_COLLECTION: markers or [],
        }
    )


@pytest.mark.asyncio
async def test_devoluciones_stale_delegates_to_invalidate_devoluciones_readiness() -> None:
    existing = {
        "_id": f"{SELLER_ID}:{DEVOLUCIONES_READ_MODEL}",
        "seller_id": SELLER_ID,
        "read_model": DEVOLUCIONES_READ_MODEL,
        "state": "reconciled",
        "source": "zelerdata_read_model_reconcile",
        "schema_version": 1,
    }
    operation = _lease_operation()
    db = _lease_db(operation, markers=[existing])
    await set_read_model_marker_state(
        db=db,
        seller_id=SELLER_ID,
        read_model=DEVOLUCIONES_READ_MODEL,
        target_state="stale",
        source="operator-action",
        approved_runtime=False,
        operation=operation,
    )
    marker = db[READ_MODEL_FRESHNESS_COLLECTION].documents[f"{SELLER_ID}:{DEVOLUCIONES_READ_MODEL}"]
    assert marker["state"] == "stale"
    assert marker["source"] == "devoluciones_operation_invalidate"
    assert marker["fresh_until"] == _devoluciones_tests.NOW
    assert marker["valid_until"] == _devoluciones_tests.NOW
    assert marker["updated_at"] == _devoluciones_tests.NOW
    operations = db[DEVOLUCIONES_OPERATIONS_COLLECTION].documents[f"{SELLER_ID}:devoluciones"]
    assert operations["checkpoint"] == {
        "phase": "readiness_invalidation",
        "source": "devoluciones_operation_invalidate",
    }


@pytest.mark.asyncio
async def test_devoluciones_failed_uses_guarded_write_with_expiry() -> None:
    operation = _lease_operation()
    db = _lease_db(operation)
    await set_read_model_marker_state(
        db=db,
        seller_id=SELLER_ID,
        read_model=DEVOLUCIONES_READ_MODEL,
        target_state="failed",
        source="operator-action",
        approved_runtime=False,
        operation=operation,
    )
    marker = db[READ_MODEL_FRESHNESS_COLLECTION].documents[f"{SELLER_ID}:{DEVOLUCIONES_READ_MODEL}"]
    assert marker["state"] == "failed"
    assert marker["source"] == "operator-action"
    assert marker["fresh_until"] == _devoluciones_tests.NOW
    assert marker["valid_until"] == _devoluciones_tests.NOW
    assert marker["updated_at"] == _devoluciones_tests.NOW
    assert marker["schema_version"] == 1
    operations = db[DEVOLUCIONES_OPERATIONS_COLLECTION].documents[f"{SELLER_ID}:devoluciones"]
    assert operations["checkpoint"] == {"phase": "failed_marker", "source": "operator-action"}


@pytest.mark.asyncio
async def test_devoluciones_without_operation_fails_before_db_access() -> None:
    db = SpyDb()
    with pytest.raises(DevolucionesLeaseLostError, match="lease"):
        await set_read_model_marker_state(
            db=db,
            seller_id=SELLER_ID,
            read_model=DEVOLUCIONES_READ_MODEL,
            target_state="stale",
            source="operator-action",
            approved_runtime=False,
            operation=None,
        )
    assert db.calls == []


@pytest.mark.parametrize("target_state", ["stale", "failed"])
@pytest.mark.asyncio
async def test_devoluciones_foreign_seller_lease_fails_before_marker_write(
    target_state: str,
) -> None:
    existing = {
        "_id": f"{SELLER_ID}:{DEVOLUCIONES_READ_MODEL}",
        "seller_id": SELLER_ID,
        "read_model": DEVOLUCIONES_READ_MODEL,
        "state": "reconciled",
        "source": "zelerdata_read_model_reconcile",
        "schema_version": 1,
    }
    operation = _lease_operation(seller_id="other-seller")
    db = _lease_db(operation, markers=[existing])
    with pytest.raises(DevolucionesLeaseLostError, match="seller"):
        await set_read_model_marker_state(
            db=db,
            seller_id=SELLER_ID,
            read_model=DEVOLUCIONES_READ_MODEL,
            target_state=target_state,
            source="operator-action",
            approved_runtime=False,
            operation=operation,
        )
    markers = db[READ_MODEL_FRESHNESS_COLLECTION].documents
    assert markers[f"{SELLER_ID}:{DEVOLUCIONES_READ_MODEL}"] == existing


@pytest.mark.parametrize(
    "overrides",
    [
        {"owns_lease": False},
        {"lease_lost": True},
        {"fence": 0},
    ],
    ids=["does-not-own", "lost", "invalid-fence"],
)
@pytest.mark.asyncio
async def test_devoluciones_lost_lease_fails_before_marker_write(overrides: dict[str, Any]) -> None:
    existing = {
        "_id": f"{SELLER_ID}:{DEVOLUCIONES_READ_MODEL}",
        "seller_id": SELLER_ID,
        "read_model": DEVOLUCIONES_READ_MODEL,
        "state": "reconciled",
        "source": "zelerdata_read_model_reconcile",
        "schema_version": 1,
    }
    operation = _lease_operation(**overrides)
    db = _lease_db(operation, markers=[existing])
    with pytest.raises(DevolucionesLeaseLostError):
        await set_read_model_marker_state(
            db=db,
            seller_id=SELLER_ID,
            read_model=DEVOLUCIONES_READ_MODEL,
            target_state="failed",
            source="operator-action",
            approved_runtime=False,
            operation=operation,
        )
    markers = db[READ_MODEL_FRESHNESS_COLLECTION].documents
    assert markers[f"{SELLER_ID}:{DEVOLUCIONES_READ_MODEL}"] == existing


@pytest.mark.asyncio
async def test_devoluciones_expired_lease_fails_before_marker_mutation() -> None:
    existing = {
        "_id": f"{SELLER_ID}:{DEVOLUCIONES_READ_MODEL}",
        "seller_id": SELLER_ID,
        "read_model": DEVOLUCIONES_READ_MODEL,
        "state": "reconciled",
        "source": "zelerdata_read_model_reconcile",
        "schema_version": 1,
    }
    operation = _lease_operation()
    operation_document = _devoluciones_tests._operation_document(operation)
    operation_document["lease_until"] = _devoluciones_tests.NOW - timedelta(seconds=1)
    db = _devoluciones_tests._MemoryDb(
        {
            DEVOLUCIONES_OPERATIONS_COLLECTION: [operation_document],
            READ_MODEL_FRESHNESS_COLLECTION: [existing],
        }
    )
    with pytest.raises(DevolucionesLeaseLostError, match="lease guard failed"):
        await set_read_model_marker_state(
            db=db,
            seller_id=SELLER_ID,
            read_model=DEVOLUCIONES_READ_MODEL,
            target_state="failed",
            source="operator-action",
            approved_runtime=False,
            operation=operation,
        )
    assert operation.lease_lost is True
    markers = db[READ_MODEL_FRESHNESS_COLLECTION].documents
    assert markers[f"{SELLER_ID}:{DEVOLUCIONES_READ_MODEL}"] == existing
