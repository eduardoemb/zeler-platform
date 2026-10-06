"""Authenticated episode90 without replaying or reconstructing episode83 RAM."""

from __future__ import annotations

import copy
import os
import socket
from pathlib import Path
from typing import Any

import pytest

from tests.test_zelerdata_pilot_monitor_guard import authenticated, run


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(os, "environ", {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path)})

    def denied(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("episode tests forbid sockets")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)


def episode(
    failed: int = 2,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    plan, job, head, baseline = authenticated()
    plan.update(
        execution_consumed=90,
        execution_sent=87,
        total_consumed=65,
        claims_failed_units=failed,
        claims_completed_units=1,
    )
    plan["budget"]["orders"]["consumed"] = 51
    plan["onboarding_sources"]["claims_returns"] = {
        "state": "ready_with_observations",
        "reason": "exact_source_proof_unavailable",
        "pending_units": 36,
    }
    baseline["plan"] = copy.deepcopy(plan)
    baseline["plan"]["state"] = "paused"
    baseline["previous"].update(
        plan=copy.deepcopy(plan),
        origin_receipt_sha256=baseline["origin_receipt_sha256"],
    )
    return plan, job, head, baseline


@pytest.mark.parametrize("failed", [1, 2])
def test_real_episode90_keeps_historical_failure_visible_without_coverage(failed: int) -> None:
    args = episode(failed)
    before = copy.deepcopy(args)
    result = run(*args)
    assert result["status"] == "RUNNING"
    assert result["sources"]["claims_returns"] == "HISTORICAL_PENDING"
    assert result["claims_failed_units"] == failed and result["claims_completed_units"] == 1
    assert not result.get("coverage_complete") and not result.get("exact")
    assert args == before


def test_arbitrary_new_origin91_is_not_an_authorized_episode() -> None:
    plan, job, head, baseline = episode()
    plan.update(execution_consumed=91, execution_sent=88, total_consumed=66)
    plan["budget"]["orders"]["consumed"] += 1
    baseline["plan"] = copy.deepcopy(plan)
    baseline["plan"]["state"] = "paused"
    baseline["previous"]["plan"] = copy.deepcopy(plan)
    assert run(plan, job, head, baseline)["reason"] == "origin_policy_invalid"


def test_another_failed_claims_unit_stops_even_with_identical_reason() -> None:
    plan, job, head, baseline = episode()
    plan["claims_failed_units"] = 3
    assert run(plan, job, head, baseline)["reason"] == "fresh_source_failure"


def test_failed_count_below_original_episode_is_never_cleared() -> None:
    plan, job, head, baseline = episode()
    plan["claims_failed_units"] = 1
    assert run(plan, job, head, baseline)["status"] == "STOP"


def test_failed_count_below_previous_snapshot_is_never_cleared() -> None:
    plan, job, head, baseline = episode(1)
    baseline["previous"]["plan"]["claims_failed_units"] = 2
    assert run(plan, job, head, baseline)["status"] == "STOP"


def test_completed_units_are_progress_not_an_exact_source_certificate() -> None:
    plan, job, head, baseline = episode()
    plan["claims_completed_units"] = 2
    plan["onboarding_sources"]["claims_returns"] = {"state": "running", "reason": None}
    result = run(plan, job, head, baseline)
    assert result["status"] == "RUNNING" and result["sources"]["claims_returns"] == "IMPROVED"
    assert result["claims_completed_units"] == 2
    assert not result.get("coverage_complete") and not result.get("exact")


def test_completed_units_cannot_regress() -> None:
    plan, job, head, baseline = episode()
    plan["claims_completed_units"] = 0
    assert run(plan, job, head, baseline)["status"] == "STOP"


def test_false_failed_count_is_not_zero() -> None:
    plan, job, head, baseline = episode()
    plan["claims_failed_units"] = False
    assert run(plan, job, head, baseline)["status"] == "STOP"


def test_new_episode_still_requires_authentic_origin_pin() -> None:
    plan, job, head, baseline = episode()
    del baseline["origin_receipt_sha256"]
    assert run(plan, job, head, baseline)["reason"] == "origin_authentication_invalid"


def test_previous_snapshot_cannot_bind_another_episode_pin() -> None:
    plan, job, head, baseline = episode()
    baseline["previous"]["origin_receipt_sha256"] = "c" * 64
    assert run(plan, job, head, baseline)["reason"] == "origin_authentication_invalid"


def test_previous_snapshot_requires_an_episode_pin_for_origin90() -> None:
    plan, job, head, baseline = episode()
    del baseline["previous"]["origin_receipt_sha256"]
    assert run(plan, job, head, baseline)["reason"] == "origin_authentication_invalid"
