"""Guarded non-productive read-model marker transitions for ZelerData.

S1 provides the 17-name inventory and writer allowlists validated before
any DB access. S2 upserts ``stale``/``failed`` markers at exact
``(seller_id, read_model)`` identity in a Mongo transaction with server
time (``$$NOW``) and the provided source, with one bounded exact-update
retry on unique-index races. S3 wires ``devoluciones`` through the
existing lease authority: ``stale`` delegates to
``invalidate_devoluciones_readiness`` and ``failed`` uses
``guarded_devoluciones_write`` to set ``failed`` and expire the
productive windows; absent, foreign, lost, or expired leases fail before
any marker mutation. Reconciliation stays the sole ``reconciled``
authority.
"""

from __future__ import annotations

import inspect
from typing import Any

from pymongo.errors import DuplicateKeyError

from zeler_platform_core.devoluciones_readiness import (
    DEVOLUCIONES_READ_MODEL,
    READ_MODEL_FRESHNESS_COLLECTION,
    DevolucionesLeaseLostError,
    DevolucionesOperationContext,
    guarded_devoluciones_write,
    invalidate_devoluciones_readiness,
)

__all__ = [
    "ALL_READ_MODELS",
    "DEVOLUCIONES_READ_MODEL",
    "READ_MODELS",
    "WRITER_SOURCE_ALLOWLIST",
    "WRITER_TARGET_STATES",
    "set_read_model_marker_state",
]

# The 16 reconciliation-owned read models, in the same order as
# ``infra.operations.zelerdata_read_model_reconcile.READ_MODELS``; the
# inventory contract test (task 1.1) locks that parity.
READ_MODELS: tuple[str, ...] = (
    "orders",
    "shipments",
    "items",
    "questions",
    "claims",
    "catalog_product_snapshots",
    "catalog_buybox_snapshots",
    "sheets_item_formula_rows",
    "sheets_item_sku_index",
    "item_status_states",
    "item_status_transitions",
    "price_history_snapshots",
    "stockout_snapshots",
    "stock_time_metrics",
    "catalog_time_metrics",
    "full_withdrawals",
)

# Full status inventory: the reconciliation models plus devoluciones.
ALL_READ_MODELS: tuple[str, ...] = (*READ_MODELS, DEVOLUCIONES_READ_MODEL)

# The generic writer records only operator-initiated transitions.
WRITER_SOURCE_ALLOWLIST: frozenset[str] = frozenset({"operator-action"})
WRITER_TARGET_STATES: frozenset[str] = frozenset({"stale", "failed"})


async def set_read_model_marker_state(
    *,
    db: Any,
    seller_id: str,
    read_model: str,
    target_state: str,
    source: str,
    approved_runtime: bool,
    operation: DevolucionesOperationContext | None = None,
) -> None:
    """Validate and apply a non-productive marker transition.

    Validation accepts known read models, the ``operator-action`` source,
    and ``stale|failed`` target states before any DB access.
    Non-devoluciones models are upserted at exact ``(seller_id,
    read_model)`` identity in a Mongo transaction with server time
    (``$$NOW``) and the provided source. Devoluciones transitions
    require a live caller-owned ``DevolucionesOperationContext``:
    ``stale`` delegates to ``invalidate_devoluciones_readiness`` and
    ``failed`` uses ``guarded_devoluciones_write`` with expired
    productive windows; absent, foreign, lost, or expired leases fail
    before any marker mutation.
    """
    _validate_writer_inputs(
        seller_id=seller_id,
        read_model=read_model,
        target_state=target_state,
        source=source,
        approved_runtime=approved_runtime,
    )
    if read_model == DEVOLUCIONES_READ_MODEL:
        if target_state == "stale":
            await _set_devoluciones_state(
                db=db,
                seller_id=seller_id,
                operation=operation,
            )
        else:
            await _set_devoluciones_failed(
                db=db,
                seller_id=seller_id,
                source=source,
                operation=operation,
            )
        return
    await _set_generic_state(
        db=db,
        seller_id=seller_id,
        read_model=read_model,
        target_state=target_state,
        source=source,
    )


async def _set_devoluciones_state(
    *,
    db: Any,
    seller_id: str,
    operation: DevolucionesOperationContext | None,
) -> None:
    """Delegate a devoluciones ``stale`` transition to the lease authority.

    The caller-owned operation lease must be present, match the target
    seller, remain live, and still be held in the operations collection;
    ``invalidate_devoluciones_readiness`` performs the guarded write.
    """
    operation = _require_matching_live_lease(seller_id=seller_id, operation=operation)
    await invalidate_devoluciones_readiness(db=db, operation=operation)


async def _set_devoluciones_failed(
    *,
    db: Any,
    seller_id: str,
    source: str,
    operation: DevolucionesOperationContext | None,
) -> None:
    """Apply a devoluciones ``failed`` marker through the lease guard.

    The caller-owned operation lease must be present, match the target
    seller, remain live, and still be held in the operations collection;
    the guarded write sets ``failed`` and expires the productive windows.
    """
    operation = _require_matching_live_lease(seller_id=seller_id, operation=operation)

    async def write_failed_marker(session: Any) -> None:
        await db[READ_MODEL_FRESHNESS_COLLECTION].update_one(
            {"_id": f"{seller_id}:{DEVOLUCIONES_READ_MODEL}"},
            _devoluciones_failed_pipeline(seller_id=seller_id, source=source),
            upsert=True,
            session=session,
        )

    await guarded_devoluciones_write(
        db=db,
        operation=operation,
        seller_id=seller_id,
        checkpoint={"phase": "failed_marker", "source": source},
        writer=write_failed_marker,
    )


def _require_matching_live_lease(
    *,
    seller_id: str,
    operation: DevolucionesOperationContext | None,
) -> DevolucionesOperationContext:
    """Require a present lease owned by the target seller.

    A missing operation or a lease held by another seller fails before
    any DB access; the lease-guarded writer then enforces liveness and
    current ownership in the operations collection.
    """
    if operation is None:
        raise DevolucionesLeaseLostError(
            "devoluciones transitions require a live caller-owned operation lease"
        )
    if operation.seller_id != seller_id:
        raise DevolucionesLeaseLostError("mutation seller does not match operation seller")
    return operation


async def _set_generic_state(
    *,
    db: Any,
    seller_id: str,
    read_model: str,
    target_state: str,
    source: str,
) -> None:
    """Upsert a generic non-productive marker in a transaction.

    A duplicate-key conflict on the upsert gets one bounded exact-update
    retry; other errors propagate.
    """
    filter_spec = {
        "_id": f"{seller_id}:{read_model}",
        "seller_id": seller_id,
        "read_model": read_model,
    }
    pipeline = _marker_transition_pipeline(
        seller_id=seller_id,
        read_model=read_model,
        target_state=target_state,
        source=source,
    )
    try:
        async with await _start_session(db) as session, session.start_transaction():
            await db[READ_MODEL_FRESHNESS_COLLECTION].update_one(
                filter_spec,
                pipeline,
                upsert=True,
                session=session,
            )
    except DuplicateKeyError:
        # Bounded retry: the race already serialized the pair, so update in place.
        async with await _start_session(db) as session, session.start_transaction():
            await db[READ_MODEL_FRESHNESS_COLLECTION].update_one(
                filter_spec,
                pipeline,
                upsert=False,
                session=session,
            )


def _marker_transition_pipeline(
    *,
    seller_id: str,
    read_model: str,
    target_state: str,
    source: str,
) -> list[dict[str, Any]]:
    """Build the non-productive marker transition stages.

    ``fresh_until`` and ``valid_until`` collapse to server now, expiring
    the productive window immediately so the marker stays fail-closed.
    """
    return [
        {
            "$set": {
                "_id": f"{seller_id}:{read_model}",
                "seller_id": seller_id,
                "read_model": read_model,
                "state": target_state,
                "fresh_until": "$$NOW",
                "valid_until": "$$NOW",
                "updated_at": "$$NOW",
                "source": source,
                "schema_version": 1,
            }
        }
    ]


def _devoluciones_failed_pipeline(
    *,
    seller_id: str,
    source: str,
) -> list[dict[str, Any]]:
    """Build the devoluciones ``failed`` marker stages.

    Mirrors the lease-guarded invalidation shape but records ``failed``
    and the operator source while expiring both productive windows.
    """
    return [
        {
            "$set": {
                "_id": f"{seller_id}:{DEVOLUCIONES_READ_MODEL}",
                "seller_id": seller_id,
                "read_model": DEVOLUCIONES_READ_MODEL,
                "state": "failed",
                "fresh_until": "$$NOW",
                "valid_until": "$$NOW",
                "updated_at": "$$NOW",
                "source": source,
                "schema_version": 1,
            }
        }
    ]


async def _start_session(db: Any) -> Any:
    """Return a Mongo session, failing closed before any DB access otherwise."""
    client = getattr(db, "client", None)
    if client is None or not callable(getattr(client, "start_session", None)):
        raise RuntimeError("Mongo transaction-capable database client is required")
    session = client.start_session()
    if inspect.isawaitable(session):
        session = await session
    return session


def _validate_writer_inputs(
    *,
    seller_id: str,
    read_model: str,
    target_state: str,
    source: str,
    approved_runtime: bool,
) -> None:
    if not str(seller_id).strip():
        raise ValueError("seller_id is required")
    if read_model not in ALL_READ_MODELS:
        raise ValueError(f"unsupported read model: {read_model}")
    if target_state not in WRITER_TARGET_STATES:
        raise ValueError("target_state must be one of " + ", ".join(sorted(WRITER_TARGET_STATES)))
    if source not in WRITER_SOURCE_ALLOWLIST:
        raise ValueError("source must be one of " + ", ".join(sorted(WRITER_SOURCE_ALLOWLIST)))
    if read_model != DEVOLUCIONES_READ_MODEL and not approved_runtime:
        raise RuntimeError("approved runtime is required for generic marker writes")
