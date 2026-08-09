"""Guarded non-productive read-model marker transitions for ZelerData.

S1 provides the 17-name inventory and writer allowlists validated before
any DB access. S2 upserts ``stale``/``failed`` markers at exact
``(seller_id, read_model)`` identity in a Mongo transaction with server
time (``$$NOW``) and the provided source, with one bounded exact-update
retry on unique-index races. S3 replaces the ``NotImplementedError``
below for ``devoluciones``. Reconciliation stays the sole ``reconciled``
authority.
"""

from __future__ import annotations

import inspect
from typing import Any

from pymongo.errors import DuplicateKeyError

from zeler_platform_core.devoluciones_readiness import (
    DEVOLUCIONES_READ_MODEL,
    READ_MODEL_FRESHNESS_COLLECTION,
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
    operation: Any = None,
) -> None:
    """Validate and apply a non-productive marker transition.

    Validation accepts known read models, the ``operator-action`` source,
    and ``stale|failed`` target states before any DB access.
    Non-devoluciones models are upserted at exact ``(seller_id,
    read_model)`` identity in a Mongo transaction with server time
    (``$$NOW``) and the provided source; devoluciones raises
    ``NotImplementedError`` until S3's lease-guarded delegation lands.
    """
    _validate_writer_inputs(
        seller_id=seller_id,
        read_model=read_model,
        target_state=target_state,
        source=source,
        approved_runtime=approved_runtime,
    )
    if read_model == DEVOLUCIONES_READ_MODEL:
        raise NotImplementedError("devoluciones lease-guarded delegation arrives in S3")
    await _set_generic_state(
        db=db,
        seller_id=seller_id,
        read_model=read_model,
        target_state=target_state,
        source=source,
    )


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
