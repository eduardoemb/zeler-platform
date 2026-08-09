"""Guarded non-productive read-model marker transitions for ZelerData.

S1 slice: the 17-name read-model inventory, writer allowlists, and the
validation-only entry for ``set_read_model_marker_state``. Validation
rejects unsupported read models, target states outside ``{stale,
failed}``, unknown sources, and unapproved runtimes before any database
access. The generic write path (S2) and the devoluciones lease
delegation (S3) replace the placeholder below in their slices.
Reconciliation remains the sole authority for ``reconciled`` markers.
"""

from __future__ import annotations

from typing import Any

from zeler_platform_core.devoluciones_readiness import DEVOLUCIONES_READ_MODEL

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
    """Validate a non-productive marker transition before any DB access.

    The S1 entry is validation-only: unsupported read models, target
    states outside ``{stale, failed}``, unknown sources, and unapproved
    runtimes raise eagerly without touching the database. Valid
    transitions raise ``NotImplementedError`` until the generic write
    path (S2) and the devoluciones lease delegation (S3, ``operation``)
    land in their slices.
    """
    _validate_writer_inputs(
        seller_id=seller_id,
        read_model=read_model,
        target_state=target_state,
        source=source,
        approved_runtime=approved_runtime,
    )
    raise NotImplementedError("generic marker write arrives in S2; devoluciones delegation in S3")


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
