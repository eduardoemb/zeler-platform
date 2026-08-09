"""S1 tests for the guarded read-model freshness entry.

Covers Phase 1 S1 tasks 1.1-1.3 from
``openspec/changes/zelerdata-read-model-freshness-guards/tasks.md``: the
17-name inventory contract, target-state rejection, and runtime / read
model / source rejection before any database access. S2 (generic upsert,
session, retry) and S3 (devoluciones lease delegation) tests arrive in
their own slices.
"""

from __future__ import annotations

from typing import Any

import pytest
from infra.operations.zelerdata_read_model_reconcile import (
    READ_MODELS as RECONCILE_READ_MODELS,
)

from zeler_platform_core.devoluciones_readiness import DEVOLUCIONES_READ_MODEL
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
