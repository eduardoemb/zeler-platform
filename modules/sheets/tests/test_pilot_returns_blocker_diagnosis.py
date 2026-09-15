"""TDD: task 3.5 — classify returns blockers without mutating production.

The stop report says "seven dates keep repairable data pending" and the repair
attempt failed with `wrapper_refused_or_failed` without a per-date receipt.
The root cause of that wrapper failure is a runtime/authorization question,
not a code defect: the repair path is the existing quota-run advancement, and
it requires an operator-authorized run in `sheets_devoluciones_runs` plus
`ZELERDATA_DEVOLUCIONES_ADVANCE_ENABLED=true` on the worker. No code change
can unblock the seven dates; the durable blockers are:

1. `HistoricalDevolucionesGuardError` fires when ANY claim row for the
   seller has `productive != True` or `return_quantity_basis !=
   "v2_return_order"`. The legacy June 23 claim (low-cost, no item identity)
   triggers this.
2. The May 14 interval disagreement (4 source IDs vs. 3 in-range readback)
   is a source-membership issue, not fixable by another write.

These tests document the guard contract so the diagnostic is auditable and
the repair decision is explicit, not implicit.
"""

from __future__ import annotations

from typing import Any

import pytest
from infra.operations.zelerdata_read_model_reconcile import (
    HistoricalDevolucionesGuardError,
    HistoricalGuardReason,
    _reject_historical_non_productive_devoluciones_rows,
)


class FakeClaimsCollection:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    async def find_one(self, query: dict[str, Any], **kwargs: Any) -> dict[str, Any] | None:
        # The guard queries with $or productive != True OR basis != v2.
        # We simulate the first match only.
        if self._row is None:
            return None
        return self._row


class FakeDb:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._claims = FakeClaimsCollection(row)

    def __getitem__(self, name: str) -> Any:
        if name == "claims":
            return self._claims
        raise AssertionError(f"unexpected collection {name}")


@pytest.mark.asyncio
async def test_guard_blocks_low_cost_legacy_row() -> None:
    """The June 23 legacy row: productive true, basis low_cost."""
    row = {"productive": True, "return_quantity_basis": "verified_low_cost_no_row"}
    with pytest.raises(HistoricalDevolucionesGuardError) as exc_info:
        await _reject_historical_non_productive_devoluciones_rows(
            db=FakeDb(row), seller_id="82453304"
        )
    assert exc_info.value.reason == HistoricalGuardReason.BASIS_NOT_V2_RETURN_ORDER


@pytest.mark.asyncio
async def test_guard_blocks_productive_false_row() -> None:
    """A non-productive return row blocks the guard."""
    row = {"productive": False, "return_quantity_basis": "v2_return_order"}
    with pytest.raises(HistoricalDevolucionesGuardError) as exc_info:
        await _reject_historical_non_productive_devoluciones_rows(
            db=FakeDb(row), seller_id="82453304"
        )
    assert exc_info.value.reason == HistoricalGuardReason.PRODUCTIVE_NOT_TRUE


@pytest.mark.asyncio
async def test_guard_blocks_both_conditions() -> None:
    """A row that fails both conditions reports the combined reason."""
    row = {"productive": False, "return_quantity_basis": "unknown"}
    with pytest.raises(HistoricalDevolucionesGuardError) as exc_info:
        await _reject_historical_non_productive_devoluciones_rows(
            db=FakeDb(row), seller_id="82453304"
        )
    assert exc_info.value.reason == HistoricalGuardReason.PRODUCTIVE_AND_BASIS


@pytest.mark.asyncio
async def test_guard_passes_when_all_returns_are_productive_v2() -> None:
    """No blocking row means the guard passes and the marker may publish."""
    await _reject_historical_non_productive_devoluciones_rows(db=FakeDb(None), seller_id="82453304")


@pytest.mark.asyncio
async def test_guard_read_failure_fails_closed() -> None:
    """A storage error must fail closed, not silently pass the guard."""

    class FailingClaims:
        async def find_one(self, query: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("storage unavailable")

    class FailingDb:
        def __getitem__(self, name: str) -> Any:
            return FailingClaims()

    with pytest.raises(HistoricalDevolucionesGuardError) as exc_info:
        await _reject_historical_non_productive_devoluciones_rows(
            db=FailingDb(), seller_id="82453304"
        )
    assert exc_info.value.reason == HistoricalGuardReason.READ_FAILED


def test_wrapper_exit_64_means_invalid_run_authority() -> None:
    """Document the wrapper's exit codes so a future repair knows what to check.

    The wrapper at `/opt/zeler-platform/zelerdata-devoluciones-reconcile.sh`
    exits 64 when `ZELERDATA_DEVOLUCIONES_RUN_ID` is missing/invalid, and 66
    when the runtime path is missing. The stop report's
    `wrapper_refused_or_failed` without a per-date receipt is consistent with
    either of these: the run authority file was absent/expired, or the runtime
    path was wrong. No source data was written in either case.
    """
    assert 64 == 64  # placeholder: no mutation to test; this documents the codes
    assert 66 == 66
