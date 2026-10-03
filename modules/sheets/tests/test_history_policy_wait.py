"""Operational holds preserve pending quota windows instead of source-failing them."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest
from infra.operations import zelerdata_read_model_reconcile as reconcile
from test_partial_history import db as db

from zeler_sheets.formulas.pacing import HistoryPolicyWaitError


class Rows:
    def __init__(self, row: dict[str, Any] | None = None) -> None:
        self.row = row or {}

    async def find_one(self, _: Any) -> dict[str, Any]:
        return deepcopy(self.row)

    async def update_one(self, _: Any, change: Any, **kwargs: Any) -> None:
        self.row.update(change.get("$set", {}))


@pytest.mark.asyncio
async def test_claims_quota_window_policy_wait_preserves_run_index_and_prepared_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 10, 3, tzinfo=UTC)
    run = {"_id": "run", "state": "active", "next_window_index": 0, "window_count": 1}
    runs, windows = Rows(run), Rows()
    database = {"sheets_devoluciones_runs": runs, "sheets_devoluciones_run_windows": windows}
    monkeypatch.setattr(
        reconcile, "devoluciones_run_allows_advancement", lambda *args, **kwargs: True
    )

    async def next_window(**_: Any) -> dict[str, Any]:
        return {"_id": "window", "index": 0}

    async def guarded(**kwargs: Any) -> None:
        await kwargs["writer"](None)

    async def source(**_: Any) -> Any:
        raise HistoryPolicyWaitError("operator pause")

    monkeypatch.setattr(reconcile, "_next_devoluciones_run_window", next_window)
    monkeypatch.setattr(reconcile, "guarded_devoluciones_write", guarded)
    with pytest.raises(HistoryPolicyWaitError):
        await reconcile.advance_devoluciones_quota_run(
            db=database,
            run_id="run",
            operation=cast(Any, SimpleNamespace(seller_id="123", fence=1)),
            now=lambda: now,
            source=source,
        )
    assert runs.row == run
    assert windows.row["state"] == "prepared"


@pytest.mark.asyncio
async def test_partial_policy_wait_does_not_classify_record_or_advance_cursor(db: Any) -> None:
    from test_partial_history import Worker, seed

    from zeler_sheets.partial_history import advance_partial_history

    class HeldWorker(Worker):
        async def _order_detail_with_source(self, *args: Any, **kwargs: Any) -> Any:
            raise HistoryPolicyWaitError("paused")

    job = await seed(db, count=1)
    head = await db.sheets_history_acquisitions.find_one({"_id": "acq"})
    with pytest.raises(HistoryPolicyWaitError):
        await advance_partial_history(db=db, job=job, worker=HeldWorker())
    assert await db.sheets_history_pending_records.count_documents({}) == 0
    assert await db.sheets_history_acquisitions.find_one({"_id": "acq"}) == head
