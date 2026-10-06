"""Prospective diagnostic logging only: every source/DB boundary is mocked."""

from __future__ import annotations

import os
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from infra.operations import zelerdata_read_model_reconcile as reconcile

from zeler_platform_core.devoluciones_runs import RUNS_COLLECTION
from zeler_sheets import devoluciones_runner as runner
from zeler_sheets.claim_projection import ClaimProjectionError, ClaimProjectionReason
from zeler_sheets.devoluciones_reconciliation import (
    ClaimInventoryError,
    SourceCallBudgetError,
    _FocusedDevolucionesFailure,
    _FocusedSourceStage,
    _tag_private_focused_devoluciones_failure,
)
from zeler_sheets.formulas.pacing import HistoryPolicyWaitError

NOW = datetime(2026, 10, 6, 18, 20, tzinfo=UTC)
MARKER = "SYNTHETIC_PII_TOKEN_BODY_NEVER_LOG"
EVENT = "sheets.devoluciones_onboarding_source_proof_unavailable"


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(os, "environ", {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path)})

    def denied(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("diagnostic tests forbid sockets")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)


class Log:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail = fail

    def warning(self, event: str, **values: Any) -> None:
        self.calls.append((event, values))
        if self.fail:
            raise RuntimeError("synthetic logging backend failure")


async def execute(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    *,
    logging_fails: bool = False,
) -> tuple[dict[str, Any], Log, list[Exception]]:
    run: dict[str, Any] = {
        "_id": "synthetic-run",
        "state": "active",
        "start": NOW - timedelta(days=2),
        "end": NOW - timedelta(days=1),
        "expires_at": NOW + timedelta(minutes=30),
    }
    rows = SimpleNamespace(find_one=AsyncMock(return_value=run))
    db = {RUNS_COLLECTION: rows}
    log = Log(fail=logging_fails)
    monkeypatch.setattr(runner, "logger", log)
    monkeypatch.setattr(runner, "admit_onboarding_devoluciones", AsyncMock(return_value=run["_id"]))
    monkeypatch.setattr(runner, "_validated_onboarding_plan", AsyncMock(return_value={}))
    monkeypatch.setattr(runner, "_require_onboarding_certificate_mode", AsyncMock())
    monkeypatch.setattr(runner, "_renew_active_before_advance", AsyncMock())
    monkeypatch.setattr(runner, "_acquire_onboarding_operation", AsyncMock(return_value=object()))
    finished = AsyncMock()
    monkeypatch.setattr(runner, "_finish_onboarding_operation", finished)
    source_window = AsyncMock(side_effect=error)
    monkeypatch.setattr(reconcile, "execute_devoluciones_quota_window", source_window)
    caught: list[Exception] = []

    async def advance(**kwargs: Any) -> dict[str, int]:
        try:
            await kwargs["source"](window={"synthetic": True})
        except HistoryPolicyWaitError:
            raise
        except Exception as original:  # noqa: BLE001 - mimic existing terminal source handling
            caught.append(original)
            run["state"] = "failed"
        return {"advanced": 0, "finalized": 0}

    monkeypatch.setattr(reconcile, "advance_devoluciones_quota_run", advance)
    charge = AsyncMock()
    result = await runner.advance_onboarding_devoluciones(
        db,
        {"seller_id": "82453304"},
        gateway=object(),
        charge=charge,
        now=lambda: NOW,
    )
    assert source_window.await_count == 1 and charge.await_count == 0
    assert finished.await_count == 1
    assert "proof" not in result and result["advanced"] == result["finalized"] == 0
    assert MARKER not in repr(log.calls)
    return result, log, caught


def diagnostic(log: Log) -> dict[str, Any]:
    assert len(log.calls) == 1 and log.calls[0][0] == EVENT
    fields = log.calls[0][1]
    assert set(fields) <= {"failure_class", "source_stage", "source_family", "projection_reason"}
    return fields


@pytest.mark.asyncio
async def test_typed_source_stage_and_family_are_logged_without_changing_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_error = httpx.HTTPStatusError(
        MARKER,
        request=httpx.Request("GET", "https://offline.invalid/"),
        response=httpx.Response(500, text=MARKER),
    )
    error = ClaimInventoryError(MARKER, private_failure=_FocusedDevolucionesFailure.SOURCE)
    _tag_private_focused_devoluciones_failure(
        error,
        _FocusedDevolucionesFailure.SOURCE,
        source_stage=_FocusedSourceStage.RETURN_DETAIL,
        source_exc=source_error,
    )
    result, log, caught = await execute(monkeypatch, error)
    assert diagnostic(log) == {
        "failure_class": "source_failure",
        "source_stage": "return_detail",
        "source_family": "server",
    }
    assert caught == [error] and result["state"] == "failed"
    assert result["reason"] == "exact_source_proof_unavailable"


@pytest.mark.asyncio
async def test_untyped_source_tags_are_not_copied_to_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    error = RuntimeError(MARKER)
    error.__dict__.update(
        _focused_devoluciones_source_stage=MARKER, _focused_devoluciones_source_family=MARKER
    )
    result, log, caught = await execute(monkeypatch, error)
    assert diagnostic(log) == {"failure_class": "source_failure"}
    assert caught == [error] and result["reason"] == "exact_source_proof_unavailable"


@pytest.mark.asyncio
async def test_parser_reason_remains_a_closed_typed_value(monkeypatch: pytest.MonkeyPatch) -> None:
    error = ClaimProjectionError(MARKER, projection_reason=ClaimProjectionReason.ITEM_IDENTITY)
    result, log, caught = await execute(monkeypatch, error)
    assert diagnostic(log) == {
        "failure_class": "parser_failure",
        "projection_reason": "projection_item_identity",
    }
    assert caught == [error] and result["reason"] == "exact_source_proof_unavailable"


@pytest.mark.asyncio
async def test_safe_404_precondition_failure_is_not_a_fabricated_source_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = ClaimInventoryError(
        MARKER, private_failure=_FocusedDevolucionesFailure.SAFE_404_PRECONDITION
    )
    result, log, caught = await execute(monkeypatch, error)
    assert diagnostic(log) == {"failure_class": "safe_404_precondition_failure"}
    assert caught == [error] and result["reason"] == "exact_source_proof_unavailable"


@pytest.mark.asyncio
async def test_logging_failure_does_not_replace_original_source_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = RuntimeError(MARKER)
    result, log, caught = await execute(monkeypatch, error, logging_fails=True)
    assert diagnostic(log) == {"failure_class": "source_failure"}
    assert caught == [error] and result["reason"] == "exact_source_proof_unavailable"


@pytest.mark.asyncio
async def test_policy_wait_is_not_logged_as_source_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    result, log, caught = await execute(monkeypatch, HistoryPolicyWaitError(MARKER))
    assert log.calls == [] and caught == [] and result["reason"] == "policy_wait"
    assert result["state"] == "active"


@pytest.mark.asyncio
async def test_physical_budget_error_keeps_its_existing_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = SourceCallBudgetError(MARKER)
    result, log, caught = await execute(monkeypatch, error)
    assert log.calls == [] and caught == [error] and result["reason"] == "physical_budget_exceeded"


@pytest.mark.asyncio
async def test_generic_exception_logs_no_message_body_or_unsupported_projection_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = ClaimProjectionError(MARKER)
    error.__dict__["projection_reason"] = MARKER
    result, log, caught = await execute(monkeypatch, error)
    assert diagnostic(log) == {
        "failure_class": "parser_failure",
        "projection_reason": "projection_unknown",
    }
    assert caught == [error] and result["reason"] == "exact_source_proof_unavailable"
