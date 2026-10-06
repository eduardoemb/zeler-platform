"""Only new Questions maintenance admission may defer after historical progress."""

from __future__ import annotations

import copy
import os
import socket
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from zeler_platform_core.history_onboarding import PLAN_COLLECTION
from zeler_sheets import history_onboarding as history
from zeler_sheets.formulas.recovery import RecoveryCapacityError

SELLER = "82453304"
START = datetime(2025, 9, 24, 5, 36, 28, tzinfo=UTC)
CUTOFF = datetime(2026, 9, 24, 5, 36, 28, tzinfo=UTC)
NOW = datetime(2026, 10, 6, 19, tzinfo=UTC)


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(os, "environ", {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path)})

    def denied(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("capacity tests forbid sockets")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)


class Rows:
    def __init__(self, job: dict[str, Any]) -> None:
        self.job = job

    async def find_one(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.job

    def find(self, *args: Any, **kwargs: Any) -> Rows:
        return self

    async def to_list(self, *, length: int) -> list[dict[str, Any]]:
        return [self.job]


def setup(
    monkeypatch: pytest.MonkeyPatch,
    *,
    enqueue_error: Exception | None = None,
    history_error: Exception | None = None,
    failed_job: bool = False,
) -> tuple[history.HistoryOnboardingWorker, dict[str, Any], Any, Any, Any, Any, Any]:
    job = {
        "_id": "synthetic-owned-Q",
        "state": "failed" if failed_job else "pending",
        "partial_done": failed_job,
        "history_pass_number": 2,
        "history_generation": 1,
        "history_checkpoint_revision": 5,
        "attempts": 0,
        "failure_reason": "source_rejected" if failed_job else None,
    }
    historic = SimpleNamespace(
        collection=Rows(job), enqueue=AsyncMock(), max_active_jobs_per_seller=4
    )
    live = SimpleNamespace(
        enqueue=AsyncMock(side_effect=enqueue_error), max_active_jobs_per_seller=4
    )
    plans = SimpleNamespace(update_one=AsyncMock())
    db = {PLAN_COLLECTION: plans}
    worker = history.HistoryOnboardingWorker(db, object(), object(), now=lambda: NOW)
    monkeypatch.setattr(
        worker,
        "queue",
        lambda seller, models: (
            historic if models in (frozenset({"questions"}), frozenset({"orders"})) else live
        ),
    )
    historical_step = AsyncMock(side_effect=history_error)
    live_step = AsyncMock()
    # Keep the actual coordinator and request keys; mock every claim/source boundary.
    monkeypatch.setattr(
        history, "FormulaRecoveryWorker", lambda **kwargs: SimpleNamespace(process_once=live_step)
    )
    monkeypatch.setattr(
        history, "HistoryQuestionsWorker", lambda raw: SimpleNamespace(process_once=historical_step)
    )
    monkeypatch.setattr(
        history, "HistoryOrdersWorker", lambda raw: SimpleNamespace(process_once=historical_step)
    )
    plan: dict[str, Any] = {
        "_id": SELLER,
        "seller_id": SELLER,
        "date_from": START,
        "cutoff": CUTOFF,
        "question_watermark": CUTOFF,
        "execution_id": "a" * 32,
        "total_consumed": 66,
        "incremental_consumed": 26,
        "execution_until": NOW.replace(hour=20, minute=32, second=58),
    }
    gateway = SimpleNamespace(incremental=False)
    detail = SimpleNamespace(incremental=False)
    return (
        worker,
        plan,
        historic,
        live,
        plans,
        historical_step,
        SimpleNamespace(
            gateway=gateway,
            detail=detail,
            live_step=live_step,
            job=job,
        ),
    )


@pytest.mark.asyncio
async def test_full_capacity_defers_only_new_q_incremental_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, plan, historic, live, plans, step, state = setup(
        monkeypatch, enqueue_error=RecoveryCapacityError("capacity")
    )
    before = copy.deepcopy((plan, state.job))
    result = await worker.advance_source(plan, "questions", state.gateway, state.detail)
    assert result == {
        "state": "running",
        "completed_units": 0,
        "pending_units": 1,
        "failed_units": 0,
        "incremental_state": "pending",
        "incremental_reason": "capacity",
    }
    assert (
        step.await_count == 1
        and historic.enqueue.await_count == 0
        and live.enqueue.await_count == 1
    )
    assert plans.update_one.await_count == state.live_step.await_count == 0
    assert historic.max_active_jobs_per_seller == live.max_active_jobs_per_seller == 4
    assert (plan, state.job) == before


@pytest.mark.asyncio
async def test_successful_incremental_admission_keeps_existing_watermark_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, plan, historic, live, plans, step, state = setup(monkeypatch)
    result = await worker.advance_source(plan, "questions", state.gateway, state.detail)
    assert result["state"] == "running" and "incremental_reason" not in result
    assert (
        step.await_count == 1
        and historic.enqueue.await_count == 0
        and live.enqueue.await_count == 1
    )
    assert plans.update_one.await_count == state.live_step.await_count == 1
    assert plans.update_one.call_args.args[1]["$set"]["question_watermark"] > CUTOFF


@pytest.mark.asyncio
async def test_noncapacity_incremental_error_propagates_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = RuntimeError("synthetic unexpected admission failure")
    worker, plan, _, _, plans, step, state = setup(monkeypatch, enqueue_error=error)
    with pytest.raises(RuntimeError) as caught:
        await worker.advance_source(plan, "questions", state.gateway, state.detail)
    assert caught.value is error and step.await_count == 1
    assert plans.update_one.await_count == state.live_step.await_count == 0


@pytest.mark.asyncio
async def test_capacity_from_historical_worker_is_not_suppressed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = RecoveryCapacityError("unexpected historical stage")
    worker, plan, _, live, plans, _, state = setup(monkeypatch, history_error=error)
    with pytest.raises(RecoveryCapacityError) as caught:
        await worker.advance_source(plan, "questions", state.gateway, state.detail)
    assert caught.value is error and live.enqueue.await_count == 0
    assert plans.update_one.await_count == state.live_step.await_count == 0


@pytest.mark.asyncio
async def test_orders_capacity_behavior_is_not_changed(monkeypatch: pytest.MonkeyPatch) -> None:
    error = RecoveryCapacityError("orders scan capacity")
    worker, plan, _, _, plans, _, state = setup(monkeypatch)
    monkeypatch.setattr(history, "ModificationScanStore", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        history,
        "ModificationScanWorker",
        lambda *args, **kwargs: SimpleNamespace(process_once=AsyncMock(side_effect=error)),
    )
    with pytest.raises(RecoveryCapacityError) as caught:
        await worker.advance_source(plan, "orders", state.gateway, state.detail)
    assert caught.value is error and plans.update_one.await_count == 0


@pytest.mark.asyncio
async def test_capacity_does_not_hide_or_reopen_an_old_failed_historical_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, plan, historic, _, plans, _, state = setup(
        monkeypatch, enqueue_error=RecoveryCapacityError("capacity"), failed_job=True
    )
    original = copy.deepcopy(state.job)
    result = await worker.advance_source(plan, "questions", state.gateway, state.detail)
    assert result["state"] == "ready_with_observations" and result["failed_units"] == 1
    assert result["pending_units"] == 0 and result["incremental_reason"] == "capacity"
    assert historic.enqueue.await_count == plans.update_one.await_count == 0
    assert state.job == original
