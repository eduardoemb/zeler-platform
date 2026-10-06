"""Offline contract for the pure, bounded pilot monitor guard."""

from __future__ import annotations

import copy
import importlib
import os
import socket
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from bson.int64 import Int64

NOW = datetime(2026, 10, 6, 16, 40, tzinfo=UTC)
UNTIL = datetime(2026, 10, 6, 20, 32, 58, tzinfo=UTC)
START = datetime(2025, 9, 24, 5, 36, 28, tzinfo=UTC)
CUTOFF = datetime(2026, 9, 24, 5, 36, 28, tzinfo=UTC)
CAPS = dict(orders=800, questions=150, shipments=250, messages=300, claims_returns=500)
PRIVATE_MARKER = "SYNTHETIC_PRIVATE_BODY_NEVER_OUTPUT"


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setattr(os, "environ", {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path)})

    def denied(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("network forbidden in monitor guard tests")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)


def snapshots() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    consumed = dict(orders=43, questions=4, shipments=5, messages=4, claims_returns=1)
    maintenance = dict(orders=13, questions=3, shipments=3, messages=3, claims_returns=2)
    periodic_end = datetime(2026, 10, 6, 4, 30, 45, 407414, tzinfo=UTC)
    checkpoint = {
        "seller_id": "82453304",
        "source": "messages",
        "start": CUTOFF.isoformat(),
        "end": periodic_end.isoformat(),
        "target_ids": ["400"],
        "target_index": 0,
        "offset": 0,
        "issue_count": 0,
        "persisted": 0,
        "pending": [],
        "last_error": PRIVATE_MARKER,
    }
    plan: dict[str, Any] = {
        "_id": "82453304",
        "seller_id": "82453304",
        "eligible": True,
        "state": "active",
        "execution_id": "868b413e20184befb7e8358e0051924f",
        "execution_until": UNTIL,
        "execution_utc_day": "2026-10-06",
        "incremental_day": "2026-10-06",
        "date_from": START,
        "date_to": CUTOFF,
        "cutoff": CUTOFF,
        "policy_version": "synthetic-pilot-policy",
        "authority": {"kind": "scoped_pilot"},
        "sources": list(CAPS),
        "total_budget": 2000,
        "total_consumed": 57,
        "execution_attempt_limit": 2500,
        "execution_consumed": 81,
        "execution_sent": 79,
        "incremental_consumed": 24,
        "incremental_policy": {"max_daily_total": 500, "max_daily_source": 300},
        "budget": {
            s: {"physical_attempts": cap, "consumed": consumed[s]} for s, cap in CAPS.items()
        },
        "incremental_source_consumed": {**maintenance, "full_withdrawals": 0},
        "onboarding_sources": {
            "questions": {"state": "ready_with_observations", "failed_units": 1},
            "messages": {
                "state": "pending",
                "reason": "ValueError",
                "consecutive_failures": 1,
                "next_attempt_at": datetime(2026, 10, 6, 4, 33, 23, tzinfo=UTC),
            },
        },
        "collector_checkpoints": {},
        "message_periodic_recovery": {
            "sweep_start": CUTOFF,
            "sweep_end": periodic_end.replace(microsecond=407000),
            "checkpoint": checkpoint,
            "packs_completed": 0,
            "persisted": 0,
            "issue_count": 0,
        },
    }
    plan["budget"]["full_withdrawals"] = {"physical_attempts": 0, "consumed": 0}
    job = {
        "_id": "synthetic-q-job",
        "seller_id": "82453304",
        "read_model": "questions",
        "state": "pending",
        "attempts": 1,
        "date_from": START,
        "date_to": CUTOFF,
        "history_plan_id": "synthetic-plan",
        "history_acquisition_id": "synthetic-q-head",
        "history_generation": 1,
        "history_pass_number": 2,
        "history_checkpoint_revision": 4,
        "policy_authority": "synthetic-policy-authority",
    }
    head = {
        "_id": "synthetic-q-head",
        "job_id": job["_id"],
        "seller_id": "82453304",
        "read_model": "questions",
        "plan_id": job["history_plan_id"],
        "date_from": START,
        "date_to": CUTOFF,
        "generation": 1,
        "pass_number": 2,
        "checkpoint_revision": 4,
        "page_sequence": 3,
        "phase": "discover",
        "next_cursor": None,
        "observed_until": None,
        "discovered_count": 150,
        "fetched_count": 0,
        "published_count": 0,
    }
    baseline = copy.deepcopy({"plan": plan, "qjob": job, "qhead": head})
    return plan, job, head, baseline


def run(
    plan: dict[str, Any],
    job: dict[str, Any],
    head: dict[str, Any],
    baseline: dict[str, Any],
    now: datetime = NOW,
) -> dict[str, Any]:
    module = importlib.import_module("infra.operations.zelerdata_pilot_monitor_guard")
    result: dict[str, Any] = module.classify(plan, job, head, baseline, now)
    assert PRIVATE_MARKER not in str(result)
    return result


def test_historical_pending_and_bson_frozen_range_are_pure() -> None:
    arguments = snapshots()
    before = copy.deepcopy(arguments)
    result = run(*arguments)
    assert result["status"] == "RUNNING"
    assert result["sources"]["messages"] == "HISTORICAL_PENDING"
    assert result["questions"] == "pending" and result["snapshot_proven"] is False
    assert arguments == before


def test_cleared_error_with_real_progress_is_improvement() -> None:
    plan, job, head, baseline = snapshots()
    plan["onboarding_sources"]["messages"] = {"state": "running", "reason": None}
    plan["message_periodic_recovery"]["checkpoint"]["persisted"] = 1
    result = run(plan, job, head, baseline)
    assert result["status"] == "RUNNING" and result["sources"]["messages"] == "IMPROVED"


def test_same_value_error_with_second_failure_stops() -> None:
    plan, job, head, baseline = snapshots()
    plan["onboarding_sources"]["messages"]["consecutive_failures"] = 2
    assert run(plan, job, head, baseline)["status"] == "STOP"


def test_new_retry_time_without_new_error_text_stops() -> None:
    plan, job, head, baseline = snapshots()
    plan["onboarding_sources"]["messages"]["next_attempt_at"] += timedelta(seconds=60)
    assert run(plan, job, head, baseline)["status"] == "STOP"


def test_issue_growth_stops_without_rewriting_checkpoint() -> None:
    plan, job, head, baseline = snapshots()
    plan["message_periodic_recovery"]["checkpoint"]["issue_count"] = 1
    before = copy.deepcopy(plan)
    assert run(plan, job, head, baseline)["status"] == "STOP"
    assert plan == before


def test_false_counter_is_not_zero_but_bson_integer_is_supported() -> None:
    plan, job, head, baseline = snapshots()
    plan["incremental_source_consumed"]["orders"] = Int64(13)
    assert run(plan, job, head, baseline)["status"] == "RUNNING"
    plan["incremental_source_consumed"]["full_withdrawals"] = False
    assert run(plan, job, head, baseline)["status"] == "STOP"


def test_charge_send_gap_growth_stops() -> None:
    plan, job, head, baseline = snapshots()
    plan["execution_consumed"] += 1
    plan["total_consumed"] += 1
    plan["budget"]["orders"]["consumed"] += 1
    assert run(plan, job, head, baseline)["status"] == "STOP"


def test_full_source_cannot_be_enabled_or_consumed() -> None:
    plan, job, head, baseline = snapshots()
    plan["budget"]["full_withdrawals"]["physical_attempts"] = 1
    assert run(plan, job, head, baseline)["status"] == "STOP"


def test_fixed_authorized_clock_expiry_stops() -> None:
    assert run(*snapshots(), now=UNTIL)["status"] == "STOP"


def test_legitimate_verification_pass_three_is_not_binding_loss() -> None:
    plan, job, head, baseline = snapshots()
    head.update(pass_number=3, phase="verify", checkpoint_revision=5, page_sequence=4)
    job.update(history_pass_number=3, history_checkpoint_revision=5, attempts=0)
    assert run(plan, job, head, baseline)["status"] == "RUNNING"


def test_completed_finalizer_revision_lag_and_cleared_error_are_valid() -> None:
    plan, job, head, baseline = snapshots()
    head.update(phase="completed", checkpoint_revision=5, fetched_count=150, published_count=150)
    job["state"] = "completed"
    plan["onboarding_sources"]["questions"] = {"state": "ready", "completed_units": 1}
    result = run(plan, job, head, baseline)
    assert result["status"] == "RUNNING" and result["questions"] == "completed"


def test_running_job_without_owned_live_lease_stops() -> None:
    plan, job, head, baseline = snapshots()
    job.update(state="running", owner_present=False, lease_until=NOW + timedelta(seconds=30))
    assert run(plan, job, head, baseline)["status"] == "STOP"


def test_issue_growth_in_one_lane_is_not_hidden_by_retiring_another() -> None:
    plan, job, head, baseline = snapshots()
    baseline["plan"]["collector_checkpoints"]["messages"] = {
        **copy.deepcopy(plan["message_periodic_recovery"]["checkpoint"]),
        "start": START.isoformat(),
        "end": CUTOFF.isoformat(),
        "issue_count": 1,
    }
    plan["message_periodic_recovery"]["checkpoint"]["issue_count"] = 1
    assert run(plan, job, head, baseline)["status"] == "STOP"


def test_false_checkpoint_document_is_not_an_empty_missing_section() -> None:
    plan, job, head, baseline = snapshots()
    plan["message_periodic_recovery"] = False
    before = copy.deepcopy(plan)
    assert run(plan, job, head, baseline)["status"] == "STOP"
    assert plan == before
