"""Cleared source signature requires a linked durable Questions checkpoint advance."""

from __future__ import annotations

import copy
import os
import socket
from pathlib import Path
from typing import Any

import pytest

from tests.test_zelerdata_pilot_monitor_guard import run
from tests.test_zelerdata_pilot_monitor_origin_episodes import episode


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(os, "environ", {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path)})

    def denied(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("question progress tests forbid sockets")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)


def frames(
    *, capacity: bool = False
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    plan, job, head, baseline = episode()
    baseline["qhead"]["discovered_count"] = 0
    baseline["previous"]["qhead"]["discovered_count"] = 0
    if capacity:
        baseline["previous"]["plan"]["onboarding_sources"]["questions"] = {
            "state": "pending",
            "reason": "capacity",
        }
    plan["onboarding_sources"]["questions"] = {
        "state": "running",
        "reason": None,
        "completed_units": 0,
        "pending_units": 1,
        "failed_units": 0,
    }
    head.update(discovered_count=50, checkpoint_revision=5, page_sequence=4)
    job["history_checkpoint_revision"] = 5
    return plan, job, head, baseline


def test_linked_discover_progress_can_clear_historical_failed_signature() -> None:
    arguments = frames()
    before = copy.deepcopy(arguments)
    result = run(*arguments)
    assert result["status"] == "RUNNING" and result["sources"]["questions"] == "IMPROVED"
    assert not result.get("exact") and not result.get("coverage_complete")
    assert arguments == before


def test_linked_fetch_and_publication_progress_can_clear_previous_capacity() -> None:
    plan, job, head, baseline = frames(capacity=True)
    baseline["qhead"]["discovered_count"] = 50
    baseline["previous"]["qhead"]["discovered_count"] = 50
    head.update(fetched_count=1, published_count=1, phase="publish")
    result = run(plan, job, head, baseline)
    assert result["status"] == "RUNNING" and result["sources"]["questions"] == "IMPROVED"
    assert not result.get("exact") and not result.get("coverage_complete")


def test_cleared_capacity_without_durable_progress_stops() -> None:
    plan, job, head, baseline = frames(capacity=True)
    baseline["previous"]["qhead"] = copy.deepcopy(head)
    assert run(plan, job, head, baseline)["reason"] == "source_error_changed"


def test_capacity_still_present_is_not_generically_accepted() -> None:
    plan, job, head, baseline = frames()
    plan["onboarding_sources"]["questions"] = {"state": "pending", "reason": "capacity"}
    assert run(plan, job, head, baseline)["reason"] == "source_error_changed"


def test_real_new_source_failure_is_not_masked_by_checkpoint_progress() -> None:
    plan, job, head, baseline = frames()
    plan["onboarding_sources"]["questions"]["consecutive_failures"] = 1
    assert run(plan, job, head, baseline)["reason"] == "fresh_source_failure"


def test_progress_of_another_job_cannot_clear_this_signature() -> None:
    plan, job, head, baseline = frames()
    head["job_id"] = "another-synthetic-job"
    assert run(plan, job, head, baseline)["reason"] == "binding_loss"
