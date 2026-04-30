from __future__ import annotations

import pytest
from bootstrap.tests._h4_fixtures import FakeBootstrapJobs, FrozenClock, recording_sleep


@pytest.mark.asyncio
async def test_fake_bootstrap_jobs_supports_inc_and_expr_budget_guard() -> None:
    jobs = FakeBootstrapJobs()

    updated = await jobs.find_one_and_update(
        {
            "_id": "job-1",
            "$expr": {"$lt": [{"$ifNull": ["$attempt_count", 0]}, 2]},
        },
        {"$inc": {"attempt_count": 1}},
    )

    assert updated is not None
    assert updated["attempt_count"] == 1

    rejected = await jobs.find_one_and_update(
        {
            "_id": "job-1",
            "$expr": {"$lt": [{"$ifNull": ["$attempt_count", 0]}, 1]},
        },
        {"$inc": {"attempt_count": 1}},
    )

    assert rejected is None
    assert jobs.document["attempt_count"] == 1


def test_frozen_clock_and_recording_sleep_are_deterministic() -> None:
    clock = FrozenClock()
    sleep = recording_sleep()

    clock.advance(seconds=1.25)

    assert clock.monotonic() == 1.25
    assert clock.now().isoformat() == "2026-04-24T12:00:01.250000+00:00"
    assert sleep.await_count == 0
